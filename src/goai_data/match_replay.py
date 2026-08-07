"""Match-specific inferred rule packs and deterministic replay artifacts.

This module deliberately keeps inferred and simulated values separate from the
original dataset.  It is a runtime bridge for historical matches whose formal
rule workbook is unavailable; it is not a claim that the reconstructed rules
are official referee rules.
"""

from __future__ import annotations

import copy
import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Mapping

from .hard_constraints import validate_match
from .traditional_rules import TRADITIONAL_RULES_VERSION, apply_traditional_defaults


MATCH_REPLAY_VERSION = "match_replay_v1.0"


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    path.write_text("".join(json.dumps(dict(row), ensure_ascii=False, sort_keys=True) + "\n" for row in rows), encoding="utf-8")


def _observed_capital(events: list[dict[str, Any]]) -> list[float]:
    return sorted({float(row["amount_wan"]) for row in events if row.get("action") == "capital_injection" and isinstance(row.get("amount_wan"), (int, float))})


def _observed_fee(events: list[dict[str, Any]]) -> list[float]:
    return sorted({abs(float(row["amount_wan"])) for row in events if row.get("action") == "administrative_fee" and isinstance(row.get("amount_wan"), (int, float))})


def infer_runtime_rules(match_dir: Path, *, xa_reference: Mapping[str, Any] | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    """Create a match-specific runtime rule pack without changing ``rules.json``."""

    match_dir = match_dir.resolve()
    match_id = json.loads((match_dir / "manifest.json").read_text(encoding="utf-8"))["match_id"]
    base = json.loads((match_dir / "rules.json").read_text(encoding="utf-8"))
    teams = load_jsonl(match_dir / "teams.jsonl")
    events = load_jsonl(match_dir / "events.jsonl")
    orders = load_jsonl(match_dir / "global_orders.jsonl")
    observed_orders = [row for row in orders if row.get("provenance") == "observed"]
    order_types = Counter(str(row.get("order_type")) for row in observed_orders if row.get("order_type"))
    explicit_types = sorted(order_types)
    auction_observed = any("竞单" in value or value.lower() in {"auction", "bid"} for value in explicit_types)
    selection_observed = any("选单" in value or value.lower() in {"selection", "select"} for value in explicit_types)
    capital = _observed_capital(events)
    fee = _observed_fee(events)
    action_set = sorted({row.get("action") for row in events if row.get("included_in_match") and row.get("action")})
    simulated_count = sum(row.get("provenance") == "simulated" for row in orders)

    rules = copy.deepcopy(base)
    formal = match_id == "LX_XA" and base.get("binding_status") == "confirmed_formal_source"
    rules["rule_pack_id"] = base.get("rule_pack_id", match_id) if formal else f"{match_id}_runtime_inferred_v2"
    rules["binding_status"] = "confirmed_formal_source" if formal else "runtime_inferred_match_specific"
    rules["provenance"] = "observed" if formal else "inferred"
    rules["runtime_version"] = MATCH_REPLAY_VERSION
    rules["runtime_rule_status"] = "formal_xa" if formal else "candidate_for_simulation"
    parameters = rules.setdefault("parameters", {})
    if capital and not formal:
        parameters["initial_cash_wan"] = capital[0]
    if fee and not formal:
        parameters["management_fee_per_quarter_wan"] = fee[0]

    payment_mode = "fixed_order_price"
    rules = apply_traditional_defaults(rules, payment_mode=payment_mode)
    # ``apply_traditional_defaults`` uses the generic override marker.  Keep
    # the stronger match-level truth label so downstream consumers can tell a
    # formal XA source from an inferred historical profile.
    rules["binding_status"] = "confirmed_formal_source" if formal else "runtime_inferred_match_specific"
    rules["provenance"] = "observed" if formal else "inferred"
    rules["runtime_rule_status"] = "formal_xa" if formal else "candidate_for_simulation"
    services = rules.setdefault("global_rule_services", {})
    services["traditional_profile"] = TRADITIONAL_RULES_VERSION
    services["order_mode"] = "selection_and_auction" if auction_observed else ("selection_only" if selection_observed else "order_type_unobserved")
    services["auction_enabled"] = bool(auction_observed)
    services["selection_enabled"] = bool(selection_observed or not explicit_types)
    services["observed_order_types"] = explicit_types
    services["participant_count"] = len(teams)
    services["replay_policy"] = "replay_observed_owner_and_preserve_simulated_unassigned"
    rules["parameter_evidence"] = {
        "initial_cash_wan": {"values": capital, "provenance": "observed_event_fingerprint" if capital else "missing"},
        "management_fee_per_quarter_wan": {"values": fee, "provenance": "observed_event_fingerprint" if fee else "missing"},
        "observed_action_set": {"values": action_set, "provenance": "observed_event_set"},
        "observed_order_types": {"values": explicit_types, "counts": dict(order_types), "provenance": "observed_order_exports" if explicit_types else "missing"},
        "participants": {"value": len(teams), "provenance": "observed_team_exports"},
    }
    rules["simulation_policy"] = {
        "observed_orders_are_replayed": True,
        "simulated_unallocated_orders_are_scenario_only": simulated_count > 0,
        "simulated_unallocated_order_count": simulated_count,
        "auction_generated": False if not auction_observed else "only_from_observed_order_types",
        "warning": "This runtime pack is inferred for simulation and replay; it is not an official historical rule source.",
    }
    if formal:
        rules["simulation_policy"]["warning"] = "XA formal rules are observed; traditional services only fill executable interfaces not present in the workbook."

    report = {
        "match_id": match_id,
        "runtime_rule_pack_id": rules["rule_pack_id"],
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "status": rules["runtime_rule_status"],
        "evidence": rules["parameter_evidence"],
        "order_mode": services["order_mode"],
        "unresolved": [
            "official_global_rule_workbook" if not formal else None,
            "complete_preselection_unassigned_pool" if simulated_count else None,
            "full_financial_settlement_semantics",
        ],
    }
    report["unresolved"] = [item for item in report["unresolved"] if item]
    if xa_reference and not formal:
        report["xa_reference"] = {"rule_pack_id": xa_reference.get("rule_pack_id"), "domains_reused": ["selection", "auction", "bankruptcy", "scoring", "settlement_interface"]}
    return rules, report


def _phase_for_action(action: str | None) -> str:
    if action in {"capital_injection", "short_loan_borrow", "long_loan_borrow", "short_loan_principal_payment", "long_loan_principal_payment", "short_loan_interest_payment", "long_loan_interest_payment", "receivable_discount", "factory_discount"}:
        return "finance"
    if action in {"material_order", "material_receipt_payment", "emergency_purchase"}:
        return "procurement"
    if action in {"production", "production_line_investment", "production_line_order", "production_line_conversion", "maintenance"}:
        return "capacity_and_production"
    if action in {"order_delivery", "receivable_maturity", "penalty_payment", "inventory_sale"}:
        return "orders_and_settlement"
    if action in {"advertising", "market_development", "iso_development", "product_development"}:
        return "development_and_marketing"
    return "other"


def build_replay_artifacts(match_dir: Path, rules: Mapping[str, Any], inference_report: Mapping[str, Any], *, seed: int = 0) -> dict[str, Any]:
    """Write deterministic event, quarter, order and final result logs."""

    match_dir = match_dir.resolve()
    match_id = inference_report["match_id"]
    events = load_jsonl(match_dir / "events.jsonl")
    orders = load_jsonl(match_dir / "global_orders.jsonl")
    teams = load_jsonl(match_dir / "teams.jsonl")
    quarter_states = load_jsonl(match_dir / "quarter_states.jsonl")
    final_states = load_jsonl(match_dir / "final_states.jsonl")
    results = json.loads((match_dir / "results.json").read_text(encoding="utf-8"))

    by_team_previous: dict[str, float | None] = defaultdict(lambda: None)
    event_rows: list[dict[str, Any]] = []
    for event in sorted((row for row in events if row.get("included_in_match")), key=lambda row: (row["year"], row["quarter"], row["team_id"], row["sequence_in_source"])):
        before = by_team_previous[event["team_id"]]
        if before is None and isinstance(event.get("balance_wan"), (int, float)) and isinstance(event.get("amount_wan"), (int, float)):
            before = float(event["balance_wan"]) - float(event["amount_wan"])
        after = event.get("balance_wan")
        event_rows.append({
            "match_id": match_id,
            "event_id": event["event_id"],
            "team_id": event["team_id"],
            "period": event.get("period"),
            "year": event.get("year"),
            "quarter": event.get("quarter"),
            "sequence_in_source": event.get("sequence_in_source"),
            "action": event.get("action"),
            "phase": _phase_for_action(event.get("action")),
            "amount_wan": event.get("amount_wan"),
            "cash_before_wan": before,
            "cash_after_wan": after,
            "cash_identity_passed": before is None or after is None or event.get("amount_wan") is None or abs(float(before) + float(event["amount_wan"]) - float(after)) <= 1e-6,
            "provenance": event.get("provenance", "observed"),
            "rule_pack_id": rules["rule_pack_id"],
        })
        by_team_previous[event["team_id"]] = float(after) if isinstance(after, (int, float)) else before

    quarter_rows = []
    for row in sorted(quarter_states, key=lambda item: (item["period_index"], item["team_id"])):
        quarter_rows.append({
            **row,
            "run_mode": "traditional_candidate_replay" if inference_report["status"] != "formal_xa" else "formal_xa_replay",
            "rule_pack_id": rules["rule_pack_id"],
            "bankruptcy_check": "cash_after_each_phase_required",
        })

    allocation_rows = []
    for order in sorted(orders, key=lambda item: str(item["order_id"])):
        owner = order.get("owner_team_id")
        order_type = str(order.get("order_type") or "未知")
        allocation_rows.append({
            "match_id": match_id,
            "order_id": order["order_id"],
            "order_type": order.get("order_type"),
            "market": order.get("market"),
            "product": order.get("product"),
            "owner_team_id": owner,
            "winner_team_id": owner,
            "status": order.get("status"),
            "allocation_policy": "replay_observed_owner" if order.get("provenance") == "observed" else "preserve_simulated_unassigned",
            "traditional_policy": "traditional_highest_bid_first_come" if "竞单" in order_type else "traditional_selection_advertising_priority",
            "auction_enabled_for_match": bool(rules.get("global_rule_services", {}).get("auction_enabled")),
            "provenance": order.get("provenance"),
            "seed": seed,
            "rule_pack_id": rules["rule_pack_id"],
        })

    observed_ranking = results.get("ranking", [])
    ranking_by_team = {row.get("team_id"): row for row in observed_ranking}
    ranked = sorted(final_states, key=lambda row: (
        row.get("bankruptcy_period") is not None,
        -(float(row["final_cash_wan"]) if isinstance(row.get("final_cash_wan"), (int, float)) else float("-inf")),
        -(float(row["development_potential"]) if isinstance(row.get("development_potential"), (int, float)) else float("-inf")),
        str(row.get("team_id")),
    ))
    simulated_ranking = []
    for index, row in enumerate(ranked, 1):
        simulated_ranking.append({
            "rank": index,
            "team_id": row.get("team_id"),
            "final_cash_wan": row.get("final_cash_wan"),
            "development_potential": row.get("development_potential"),
            "bankruptcy_period": row.get("bankruptcy_period"),
            "ranking_basis": "final_cash_then_development_potential_excluding_no_observation",
            "official_rank": ranking_by_team.get(row.get("team_id"), {}).get("rank"),
            "provenance": "simulated" if match_id != "LX_XA" else "derived_from_formal_assets",
        })
    final_result = {
        "match_id": match_id,
        "run_version": MATCH_REPLAY_VERSION,
        "rule_pack_id": rules["rule_pack_id"],
        "result_status": "formal_xa_replay_with_simulated_service_logs" if match_id == "LX_XA" else "candidate_replay_simulated_ranking",
        "team_count": len(teams),
        "observed_result": results,
        "simulated_ranking": simulated_ranking,
        "ranking_warning": "旧场次没有官方最终排名；此排序仅用于运行接口和策略比较。" if match_id != "LX_XA" else "XA 的正式分数仍以 observed_result 为准。",
        "provenance": {"events": "observed", "quarter_states": "derived", "orders": "observed_plus_simulated", "ranking": "simulated" if match_id != "LX_XA" else "derived_and_checked"},
    }

    validation = validate_match(match_dir).to_dict()
    run_summary = {
        "match_id": match_id,
        "run_version": MATCH_REPLAY_VERSION,
        "rule_pack_id": rules["rule_pack_id"],
        "seed": seed,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "scope": "deterministic historical event replay, traditional order-policy dispatch, quarter and cash audit",
        "simulation_scope": "partial_accounting" if match_id != "LX_XA" else "formal_observed_data_plus_service_replay",
        "counts": {"events": len(event_rows), "quarters": len(quarter_rows), "orders": len(allocation_rows), "teams": len(teams)},
        "cash_identity_passed": all(row["cash_identity_passed"] for row in event_rows),
        "hard_constraints_passed": validation["passed"],
        "provenance_summary": {"observed_events": len(event_rows), "observed_orders": sum(row.get("provenance") == "observed" for row in allocation_rows), "simulated_orders": sum(row.get("provenance") == "simulated" for row in allocation_rows)},
        "limitations": ["没有把推断规则升级为正式规则", "没有凭空重建旧场官方未分配订单", "尚未执行完整税费、折旧、应收和三表结算动力学"],
    }
    _write_json(match_dir / "rules_inferred_v2.json", dict(rules))
    _write_json(match_dir / "rule_inference_report.json", dict(inference_report))
    _write_jsonl(match_dir / "traditional_event_replay.jsonl", event_rows)
    _write_jsonl(match_dir / "traditional_quarter_log.jsonl", quarter_rows)
    _write_jsonl(match_dir / "traditional_order_allocation.jsonl", allocation_rows)
    _write_json(match_dir / "traditional_final_results.json", final_result)
    _write_json(match_dir / "traditional_validation.json", validation)
    _write_json(match_dir / "traditional_rule_run.json", run_summary)
    return run_summary
