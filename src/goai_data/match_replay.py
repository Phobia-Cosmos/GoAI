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

from .global_rules import development_potential, rank_final_states
from .hard_constraints import validate_match
from .traditional_rules import TRADITIONAL_RULES_VERSION, apply_traditional_defaults


MATCH_REPLAY_VERSION = "match_replay_v1.1"


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


def verify_xa_historical_outcome(
    *,
    rules: Mapping[str, Any],
    quarter_states: list[dict[str, Any]],
    final_states: list[dict[str, Any]],
    results: Mapping[str, Any],
) -> dict[str, Any]:
    """Verify that observed XA trajectories reproduce the formal outcome.

    This is deliberately an outcome replay: cash events and exported terminal
    accounting states are observed inputs.  Passing this audit proves that the
    score, rank and bankruptcy services consume those inputs correctly; it does
    not prove that candidate settlement rules can regenerate every accounting
    state from business actions alone.
    """

    recomputed = rank_final_states(final_states, rules)
    official = list(results.get("ranking") or [])
    official_by_team = {str(row.get("team_id")): row for row in official}
    recomputed_by_team = {str(row.get("team_id")): row for row in recomputed}

    rank_mismatches: list[dict[str, Any]] = []
    score_mismatches: list[dict[str, Any]] = []
    state_mismatches: list[dict[str, Any]] = []
    official_order = [str(row.get("team_id")) for row in official]
    recomputed_order = [str(row.get("team_id")) for row in recomputed]
    if official_order != recomputed_order:
        rank_mismatches.append({"official": official_order, "recomputed": recomputed_order})
    for team_id in sorted(set(official_by_team) | set(recomputed_by_team)):
        expected = official_by_team.get(team_id)
        actual = recomputed_by_team.get(team_id)
        if expected is None or actual is None:
            score_mismatches.append({"team_id": team_id, "official": expected, "recomputed": actual})
            continue
        expected_score = int(expected.get("official_score", expected.get("rounded_recomputed_score", -1)))
        if int(actual["rounded_score"]) != expected_score:
            score_mismatches.append({"team_id": team_id, "official_score": expected_score, "recomputed_score": actual["rounded_score"]})
        if float(actual["owner_equity_wan"]) != float(expected["owner_equity_wan"]) or float(actual["development_potential"]) != float(expected["development_potential"]):
            state_mismatches.append({
                "team_id": team_id,
                "official_equity_wan": expected.get("owner_equity_wan"),
                "recomputed_equity_wan": actual.get("owner_equity_wan"),
                "official_potential": expected.get("development_potential"),
                "recomputed_potential": actual.get("development_potential"),
            })

    potential_mismatches = []
    for row in final_states:
        recomputed_potential = development_potential(row.get("assets") or {}, rules)
        if float(recomputed_potential) != float(row.get("development_potential", 0)):
            potential_mismatches.append({"team_id": row.get("team_id"), "recorded": row.get("development_potential"), "recomputed": recomputed_potential})

    official_bankruptcies = {str(row.get("team_id")): row.get("period") for row in results.get("bankruptcies") or []}
    replayed_bankruptcies = {str(row.get("team_id")): row.get("bankruptcy_period") for row in final_states if row.get("bankruptcy_period")}
    bankruptcy_mismatches = [] if official_bankruptcies == replayed_bankruptcies else [{"official": official_bankruptcies, "replayed": replayed_bankruptcies}]

    final_quarter_cash = {str(row.get("team_id")): row.get("end_cash_wan") for row in quarter_states if int(row.get("period_index", 0)) == 20}
    cash_mismatches = []
    for row in final_states:
        team_id = str(row.get("team_id"))
        if final_quarter_cash.get(team_id) != row.get("final_cash_wan"):
            cash_mismatches.append({"team_id": team_id, "quarter_cash_wan": final_quarter_cash.get(team_id), "final_cash_wan": row.get("final_cash_wan")})

    checks = {
        "rank_order": {"passed": not rank_mismatches, "mismatches": rank_mismatches, "ranked_team_count": len(recomputed)},
        "official_scores": {"passed": not score_mismatches, "mismatches": score_mismatches, "matched_team_count": len(recomputed) - len(score_mismatches)},
        "terminal_equity_and_potential": {"passed": not state_mismatches, "mismatches": state_mismatches},
        "potential_from_assets": {"passed": not potential_mismatches, "mismatches": potential_mismatches},
        "bankruptcy_team_and_period": {"passed": not bankruptcy_mismatches, "mismatches": bankruptcy_mismatches, "bankrupt_team_count": len(replayed_bankruptcies)},
        "terminal_cash": {"passed": not cash_mismatches, "mismatches": cash_mismatches, "team_count": len(final_states)},
    }
    return {
        "mode": "observed_trajectory_outcome_replay",
        "exact_outcome_match": all(check["passed"] for check in checks.values()),
        "causal_dynamics_replay": False,
        "checks": checks,
        "recomputed_ranking": recomputed,
        "limitations": [
            "667 operating cash events have partial business parameters and another 20 are unparsed",
            "bankrupt teams have no exported terminal owner equity, and several bankruptcies occurred while cash remained positive",
            "quarterly non-cash accounting snapshots and exact hidden settlement order are unavailable",
        ],
    }


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
        owner = order.get("final_owner_team_id", order.get("owner_team_id"))
        order_type = str(order.get("order_type") or "未知")
        allocation_rows.append({
            "match_id": match_id,
            "order_id": order["order_id"],
            "order_type": order.get("order_type"),
            "market": order.get("market"),
            "product": order.get("product"),
            "owner_team_id": owner,
            "winner_team_id": owner,
            "status": order.get("final_status", order.get("status")),
            "result_information_boundary": "offline_match_end_label_not_release_time_state",
            "allocation_policy": "replay_observed_owner" if order.get("provenance") == "observed" else "preserve_simulated_unassigned",
            "traditional_policy": "traditional_highest_bid_first_come" if "竞单" in order_type else "traditional_selection_advertising_priority",
            "auction_enabled_for_match": bool(rules.get("global_rule_services", {}).get("auction_enabled")),
            "provenance": order.get("provenance"),
            "seed": seed,
            "rule_pack_id": rules["rule_pack_id"],
        })

    observed_ranking = results.get("ranking", [])
    ranking_by_team = {row.get("team_id"): row for row in observed_ranking}
    if match_id == "LX_XA":
        recomputed_ranking = rank_final_states(final_states, rules)
        ranking_basis = "owner_equity_times_development_potential_multiplier_excluding_bankrupt"
    else:
        # Historical matches without exported terminal equity retain the old
        # candidate ordering.  It is intentionally not labelled as XA score.
        ranked_candidates = sorted(final_states, key=lambda row: (
            row.get("bankruptcy_period") is not None,
            -(float(row["final_cash_wan"]) if isinstance(row.get("final_cash_wan"), (int, float)) else float("-inf")),
            -(float(row["development_potential"]) if isinstance(row.get("development_potential"), (int, float)) else float("-inf")),
            str(row.get("team_id")),
        ))
        recomputed_ranking = [
            {
                "rank": index,
                "team_id": row.get("team_id"),
                "final_cash_wan": row.get("final_cash_wan"),
                "development_potential": row.get("development_potential"),
                "bankruptcy_period": row.get("bankruptcy_period"),
            }
            for index, row in enumerate(ranked_candidates, 1)
        ]
        ranking_basis = "candidate_final_cash_then_development_potential"
    simulated_ranking = [
        {
            **row,
            "official_rank": ranking_by_team.get(row.get("team_id"), {}).get("rank"),
            "ranking_basis": ranking_basis,
            "provenance": "derived_from_terminal_state_and_rule_pack",
        }
        for row in recomputed_ranking
    ]
    outcome_verification = verify_xa_historical_outcome(
        rules=rules,
        quarter_states=quarter_states,
        final_states=final_states,
        results=results,
    ) if match_id == "LX_XA" else None
    final_result = {
        "match_id": match_id,
        "run_version": MATCH_REPLAY_VERSION,
        "rule_pack_id": rules["rule_pack_id"],
        "result_status": "formal_xa_replay_with_simulated_service_logs" if match_id == "LX_XA" else "candidate_replay_simulated_ranking",
        "team_count": len(teams),
        "observed_result": results,
        "recomputed_ranking": simulated_ranking,
        "simulated_ranking": simulated_ranking,
        "outcome_replay_verification": outcome_verification,
        "ranking_warning": "旧场次没有官方最终排名；此排序仅用于运行接口和策略比较。" if match_id != "LX_XA" else "XA 终局裁判已从终局状态重算；这不等于从不完整业务动作因果重建全部会计状态。",
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
        "simulation_scope": "partial_accounting" if match_id != "LX_XA" else "exact_observed_outcome_replay_not_full_causal_dynamics",
        "counts": {"events": len(event_rows), "quarters": len(quarter_rows), "orders": len(allocation_rows), "teams": len(teams)},
        "cash_identity_passed": all(row["cash_identity_passed"] for row in event_rows),
        "hard_constraints_passed": validation["passed"],
        "provenance_summary": {"observed_events": len(event_rows), "observed_orders": sum(row.get("provenance") == "observed" for row in allocation_rows), "simulated_orders": sum(row.get("provenance") == "simulated" for row in allocation_rows)},
        "exact_historical_outcome_match": outcome_verification["exact_outcome_match"] if outcome_verification else None,
        "causal_dynamics_replay": False,
        "limitations": ["没有把推断规则升级为正式规则", "没有凭空重建旧场官方未分配订单", "历史结果回放可精确验收终局，但不完整动作参数和季度非现金状态仍不足以证明完整因果动力学"],
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
