"""Inverse reconstruction of XA intermediate states from observed exports.

The output is a calibrated historical estimate, not a hidden-state oracle.
Every field carries provenance and no counterfactual simulator may read future
checkpoints after its branch period.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping

from .global_rules import development_potential


XA_INVERSE_VERSION = "xa_inverse_reconstruction_v1.0"


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _period_index(value: str | None) -> int | None:
    if not value:
        return None
    match = re.fullmatch(r"Y(\d+)Q(\d+)", value)
    if not match:
        match = re.fullmatch(r"第(\d+)年(\d+)季", value)
    return (int(match.group(1)) - 1) * 4 + int(match.group(2)) - 1 if match else None


def _period(index: int) -> str:
    return f"Y{index // 4 + 1}Q{index % 4 + 1}"


def _team_from_path(path: str) -> str | None:
    match = re.search(r"/(XA\d+)\.xls$", path)
    return match.group(1) if match else None


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    path.write_text("".join(json.dumps(dict(row), ensure_ascii=False, sort_keys=True) + "\n" for row in rows), encoding="utf-8")


def _raw_cell_maps(rows: list[dict[str, Any]]) -> dict[tuple[str, str], dict[tuple[int, int], Any]]:
    output: dict[tuple[str, str], dict[tuple[int, int], Any]] = defaultdict(dict)
    for row in rows:
        team_id = _team_from_path(str(row.get("source_path") or ""))
        if team_id:
            output[(team_id, str(row.get("sheet")))][(int(row["row"]), int(row["column"]))] = row.get("value")
    return output


def _qualification_timelines(cells: Mapping[tuple[str, str], Mapping[tuple[int, int], Any]], rules: Mapping[str, Any]) -> tuple[list[dict[str, Any]], dict[str, dict[str, list[dict[str, Any]]]]]:
    params = rules["parameters"]
    specs = (
        ("market", "markets", 2, 6, lambda rule: int(rule.get("years", 1)) * 4),
        ("product", "products", 8, 12, lambda rule: int(rule.get("quarters", 1))),
        ("iso", "iso", 14, 18, lambda rule: int(rule.get("years", 1)) * 4),
    )
    actions: list[dict[str, Any]] = []
    timelines: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    for (team_id, sheet), values in cells.items():
        if sheet != "研发认证":
            continue
        for kind, collection, name_column, completion_column, duration_fn in specs:
            for row_number in range(4, 40):
                target = values.get((row_number, name_column))
                completion = _period_index(values.get((row_number, completion_column)))
                rule = (params.get(collection) or {}).get(target)
                if not rule or completion is None:
                    continue
                duration = duration_fn(rule)
                start = completion - duration + 1
                item = {"kind": kind, "target": target, "start_period": _period(start), "start_period_index": start, "completion_period": _period(completion), "completion_period_index": completion, "duration_quarters": duration, "provenance": "derived_from_observed_completion_and_formal_duration"}
                timelines[team_id][collection].append(item)
                actions.append({"team_id": team_id, "action_type": f"develop_{kind}", **item})
    return sorted(actions, key=lambda row: (row["start_period_index"], row["team_id"], row["kind"], row["target"])), timelines


def _asset_timelines(cells: Mapping[tuple[str, str], Mapping[tuple[int, int], Any]], rules: Mapping[str, Any]) -> tuple[list[dict[str, Any]], dict[str, dict[str, list[dict[str, Any]]]]]:
    params = rules["parameters"]
    actions: list[dict[str, Any]] = []
    timelines: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    for (team_id, sheet), values in cells.items():
        if sheet != "厂房与生产线":
            continue
        for row_number in range(4, 200):
            name = values.get((row_number, 3))
            if name in (params.get("factories") or {}):
                acquired = _period_index(values.get((row_number, 10)))
                if acquired is None:
                    continue
                status = str(values.get((row_number, 4)) or "")
                item = {"factory_id": values.get((row_number, 2)), "name": name, "ownership": "purchased" if status == "购买" else "rented", "acquired_period": _period(acquired), "acquired_period_index": acquired, "provenance": "observed_enterprise_asset_export"}
                timelines[team_id]["factories"].append(item)
                actions.append({"team_id": team_id, "action_type": "buy_workshop" if item["ownership"] == "purchased" else "rent_workshop", **item})
            if name in (params.get("production_lines") or {}):
                started = _period_index(values.get((row_number, 12)))
                completed = _period_index(values.get((row_number, 11)))
                if completed is None:
                    continue
                item = {"line_id": values.get((row_number, 2)), "line_type": name, "product_id": values.get((row_number, 5)), "start_period": _period(started) if started is not None else None, "start_period_index": started, "completion_period": _period(completed), "completion_period_index": completed, "accumulated_depreciation_wan": values.get((row_number, 7)), "provenance": "observed_enterprise_asset_export"}
                timelines[team_id]["production_lines"].append(item)
                actions.append({"team_id": team_id, "action_type": "buy_product_line", **item})
    return sorted(actions, key=lambda row: (row.get("start_period_index", row.get("acquired_period_index", 99)) or 99, row["team_id"], row["action_type"])), timelines


def _loan_reconstruction(events: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    by_team: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        if event.get("included_in_match"):
            by_team[str(event["team_id"])].append(event)
    inferred: list[dict[str, Any]] = []
    short_passed = 0
    long_passed = 0
    long_total = 0
    for team_id, rows in by_team.items():
        short_borrow = {(_period_index(row["period"]), row["amount_wan"]): row for row in rows if row.get("action") == "short_loan_borrow"}
        for repayment in (row for row in rows if row.get("action") == "short_loan_repayment"):
            due = _period_index(repayment["period"])
            candidates = [row for (period, _), row in short_borrow.items() if period == due - 4]
            borrower = candidates[0] if len(candidates) == 1 else None
            principal = float(borrower["amount_wan"]) if borrower else None
            expected = float(math.floor(principal * 1.05 + 0.5)) if principal is not None else None
            passed = expected == abs(float(repayment["amount_wan"]))
            short_passed += int(passed)
            inferred.append({"team_id": team_id, "period": repayment["period"], "action_type": "short_loan_repayment", "principal_wan": principal, "interest_wan": None if principal is None else expected - principal, "cash_payment_wan": abs(float(repayment["amount_wan"])), "matched_borrow_event_id": borrower.get("event_id") if borrower else None, "passed": passed, "provenance": "inferred_from_formal_four_quarter_maturity"})
        active: list[dict[str, Any]] = []
        for row in sorted(rows, key=lambda item: item["sequence_in_source"]):
            period = _period_index(row["period"])
            if row.get("action") == "long_loan_repayment":
                due = [loan for loan in active if period > loan["start"] and (period - loan["start"]) % 4 == 0 and period <= loan["start"] + loan["term"] * 4]
                interest = float(math.floor(sum(loan["principal"] * 0.12 for loan in due) + 0.5))
                principal = sum(loan["principal"] for loan in due if period == loan["start"] + loan["term"] * 4)
                expected = interest + principal
                passed = expected == abs(float(row["amount_wan"]))
                long_passed += int(passed); long_total += 1
                inferred.append({"team_id": team_id, "period": row["period"], "action_type": "long_loan_repayment", "principal_wan": principal, "interest_wan": interest, "cash_payment_wan": abs(float(row["amount_wan"])), "matched_borrow_event_ids": [loan["event_id"] for loan in due], "passed": passed, "provenance": "inferred_from_aggregate_half_up_annual_interest"})
                active = [loan for loan in active if period != loan["start"] + loan["term"] * 4]
            if row.get("action") == "long_loan_borrow":
                parameters = row.get("parameters") or {}
                active.append({"event_id": row["event_id"], "start": period, "principal": float(row["amount_wan"]), "term": int(parameters.get("term", 4))})
    short_total = sum(row.get("action") == "short_loan_repayment" and row.get("included_in_match") for row in events)
    return inferred, {"short_loan": {"passed": short_passed == short_total, "matched": short_passed, "total": short_total}, "long_loan": {"passed": long_passed == long_total, "matched": long_passed, "total": long_total, "rounding": "aggregate_interest_half_up"}}


def _order_timelines(cells: Mapping[tuple[str, str], Mapping[tuple[int, int], Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for (team_id, sheet), values in cells.items():
        if sheet != "订单信息":
            continue
        for row_number in range(4, 500):
            order_id = values.get((row_number, 2))
            if not isinstance(order_id, str):
                continue
            delivered = _period_index(values.get((row_number, 12)))
            status = str(values.get((row_number, 7)) or "")
            award_year_match = re.fullmatch(r"第(\d+)年", str(values.get((row_number, 8)) or ""))
            rows.append({
                "record_type": "order_history_reconstruction", "team_id": team_id, "order_id": order_id,
                "action_type": "order_delivery" if delivered is not None else ("order_default" if "违约" in status else "order_unfulfilled"),
                "delivered_period": _period(delivered) if delivered is not None else None, "delivered_period_index": delivered,
                "award_year": int(award_year_match.group(1)) if award_year_match else None,
                "market": values.get((row_number, 3)), "product": values.get((row_number, 4)), "quantity": values.get((row_number, 5)),
                "total_price_wan": values.get((row_number, 6)), "delivery_term": values.get((row_number, 9)), "receivable_term": values.get((row_number, 10)), "iso": values.get((row_number, 11)),
                "status": status, "provenance": "observed_enterprise_order_export",
            })
    return sorted(rows, key=lambda row: (row.get("delivered_period_index") if row.get("delivered_period_index") is not None else 99, row["team_id"], row["order_id"]))


def build_xa_inverse_artifacts(match_dir: Path) -> dict[str, Any]:
    match_dir = match_dir.resolve()
    rules = json.loads((match_dir / "rules.json").read_text(encoding="utf-8"))
    events = _jsonl(match_dir / "events.jsonl")
    reports = _jsonl(match_dir / "reports.jsonl")
    raw_cells = _jsonl(match_dir / "raw_cells.jsonl")
    quarter_cash = _jsonl(match_dir / "quarter_states.jsonl")
    final_states = _jsonl(match_dir / "final_states.jsonl")
    results = json.loads((match_dir / "results.json").read_text(encoding="utf-8"))
    historical_replay_path = match_dir / "traditional_final_results.json"
    historical_replay = json.loads(historical_replay_path.read_text(encoding="utf-8")) if historical_replay_path.exists() else {}
    outcome_verification = historical_replay.get("outcome_replay_verification") or {}
    cells = _raw_cell_maps(raw_cells)
    qualification_actions, qualifications = _qualification_timelines(cells, rules)
    asset_actions, assets = _asset_timelines(cells, rules)
    loan_actions, loan_audit = _loan_reconstruction(events)
    order_actions = _order_timelines(cells)
    observed_actions = [
        {
            "record_type": "observed_cash_event", "team_id": row["team_id"], "period": row["period"],
            "period_index": _period_index(row["period"]), "action_type": row["action"], "parameters": row.get("parameters") or {},
            "cash_effect_wan": row["amount_wan"], "cash_after_wan": row["balance_wan"], "source_event_id": row["event_id"],
            "parameter_parse_status": row.get("parameter_parse_status"), "provenance": "observed",
        }
        for row in events if row.get("included_in_match")
    ]

    report_index: dict[tuple[str, int, str], dict[str, float]] = defaultdict(dict)
    for row in reports:
        if row.get("report_variant") == "system" and isinstance(row.get("year"), int):
            report_index[(str(row["team_id"]), int(row["year"]), str(row["statement"]))][str(row["metric"])] = float(row["value_wan"])

    tax_checks = []
    tax_payments = {
        (str(row["team_id"]), int(row["year"])): abs(float(row["amount_wan"]))
        for row in events
        if row.get("included_in_match") and row.get("action") == "tax_payment"
    }
    for team_id in sorted({str(row["team_id"]) for row in final_states}):
        carried_loss = 0.0
        for year in range(1, 6):
            income = report_index.get((team_id, year, "income_statement"), {})
            pretax = income.get("税前利润")
            observed_tax = income.get("所得税")
            if pretax is None or observed_tax is None:
                continue
            taxable = max(0.0, pretax - carried_loss)
            expected_tax = float(math.floor(taxable * float(rules["parameters"].get("tax_rate", 0.25)) + 0.5))
            carried_loss = max(0.0, carried_loss - pretax) if pretax >= 0 else carried_loss - pretax
            next_year_payment = tax_payments.get((team_id, year + 1)) if year < 5 else None
            tax_checks.append({
                "team_id": team_id, "year": year, "pretax_profit_wan": pretax,
                "loss_carryforward_after_wan": carried_loss, "observed_tax_wan": observed_tax,
                "predicted_tax_wan": expected_tax, "calculation_passed": observed_tax == expected_tax,
                "next_year_q1_payment_wan": next_year_payment,
                "payment_passed": year == 5 or observed_tax == 0 or next_year_payment == observed_tax,
            })

    production_checks = []
    product_rules = rules["parameters"]["products"]
    for row in events:
        if not row.get("included_in_match") or row.get("action") != "production":
            continue
        assignments = (row.get("parameters") or {}).get("line_assignments") or []
        expected = sum(float((product_rules.get(str(item.get("product_id"))) or {}).get("process_wan", 0)) for item in assignments)
        observed = abs(float(row["amount_wan"]))
        production_checks.append({
            "event_id": row["event_id"], "team_id": row["team_id"], "period": row["period"],
            "line_assignment_count": len(assignments), "observed_process_cost_wan": observed,
            "predicted_one_batch_process_cost_wan": expected, "passed": observed == expected,
        })
    teams = sorted({row["team_id"] for row in final_states})
    initial_fields = {"现金": 675.0, "应收款": 0.0, "在制品": 0.0, "产成品": 0.0, "固定资产合计": 0.0, "负债合计": 0.0, "所有者权益合计": 675.0}
    initial_mismatches = []
    for team_id in teams:
        balance = report_index[(team_id, 0, "balance_sheet")]
        for metric, expected in initial_fields.items():
            if balance.get(metric) != expected:
                initial_mismatches.append({"team_id": team_id, "metric": metric, "expected": expected, "actual": balance.get(metric)})

    final_by_team = {row["team_id"]: row for row in final_states}
    bankruptcy_index = {row["team_id"]: _period_index(row["period"]) for row in results.get("bankruptcies", [])}
    quarter_rows = []
    for cash in sorted(quarter_cash, key=lambda row: (row["period_index"], row["team_id"])):
        team_id, index = str(cash["team_id"]), int(cash["period_index"]) - 1
        year = index // 4 + 1
        completed = {
            collection: sorted(item["target"] for item in qualifications[team_id][collection] if item["completion_period_index"] <= index)
            for collection in ("markets", "products", "iso")
        }
        current_factories = [item for item in assets[team_id]["factories"] if item["acquired_period_index"] <= index]
        current_lines = [item for item in assets[team_id]["production_lines"] if item["completion_period_index"] <= index]
        potential_assets = {**completed, "purchased_factories": [item["name"] for item in current_factories if item["ownership"] == "purchased"], "completed_lines": [item["line_type"] for item in current_lines]}
        balance = report_index.get((team_id, year, "balance_sheet"), {}) if index % 4 == 3 else {}
        income = report_index.get((team_id, year, "income_statement"), {}) if index % 4 == 3 else {}
        quarter_rows.append({
            "match_id": "LX_XA", "team_id": team_id, "period": _period(index), "period_index": index,
            "cash_wan": cash["end_cash_wan"], "cash_provenance": "derived_exact_from_observed_cash_events",
            "markets": completed["markets"], "products": completed["products"], "iso": completed["iso"],
            "factories": current_factories, "production_lines": current_lines,
            "development_potential": development_potential(potential_assets, rules),
            "owner_equity_wan": balance.get("所有者权益合计"), "liabilities_wan": balance.get("负债合计"),
            "receivables_wan": balance.get("应收款"), "work_in_process_wan": balance.get("在制品"),
            "product_inventory_wan": balance.get("产成品"), "material_inventory_wan": balance.get("原材料"),
            "fixed_assets_wan": balance.get("固定资产合计"), "annual_net_income_wan": income.get("年度净利润"),
            "accounting_checkpoint": "observed_exact_annual" if balance else "missing_between_annual_exports",
            "bankrupt": bankruptcy_index.get(team_id) is not None and index >= int(bankruptcy_index[team_id]),
            "provenance": "observed_plus_deterministic_inverse",
        })

    depreciation_checks = []
    line_rules = rules["parameters"]["production_lines"]
    sold_line_teams = {row["team_id"] for row in events if row.get("included_in_match") and row.get("action") == "production_line_sale"}
    for team_id in teams:
        for year in range(1, 6):
            observed = report_index.get((team_id, year, "income_statement"), {}).get("折旧")
            if observed is None:
                continue
            predicted = 0.0
            for line in assets[team_id]["production_lines"]:
                completed_year = line["completion_period_index"] // 4 + 1
                rule = line_rules[line["line_type"]]
                if completed_year < year < completed_year + int(rule.get("depreciation_years", 0)):
                    predicted += float(rule.get("depreciation_fee_wan", 0))
            depreciation_checks.append({"team_id": team_id, "year": year, "observed_wan": observed, "predicted_wan": predicted, "passed": observed == predicted, "known_sold_line_history_gap": team_id in sold_line_teams})
    identifiable_depreciation = [row for row in depreciation_checks if not row["known_sold_line_history_gap"]]
    report = {
        "version": XA_INVERSE_VERSION,
        "match_id": "LX_XA",
        "status": "calibrated_intermediate_reconstruction",
        "terminal_outcome_replay": {"exact_outcome_match": outcome_verification.get("exact_outcome_match"), "causal_dynamics_replay": outcome_verification.get("causal_dynamics_replay", False), "source": "traditional_final_results.json" if outcome_verification else None},
        "initial_state": {"passed": not initial_mismatches, "matched_teams": len(teams) - len({row["team_id"] for row in initial_mismatches}), "total_teams": len(teams), "mismatches": initial_mismatches, "recommended_simulator_initial_state": {"cash_wan": 675, "owner_equity_wan": 675, "markets": [], "products": [], "iso": [], "factories": [], "production_lines": [], "receivables": [], "short_loans": [], "long_loans": []}},
        "loan_reconstruction": loan_audit,
        "development_timing": {"market_event_quarters": dict(Counter(row["quarter"] for row in events if row.get("included_in_match") and row.get("action") == "market_development")), "iso_event_quarters": dict(Counter(row["quarter"] for row in events if row.get("included_in_match") and row.get("action") == "iso_development")), "formal_payment_timing": "year_end"},
        "depreciation_reconstruction": {"passed_on_identifiable_histories": all(row["passed"] for row in identifiable_depreciation), "matched": sum(row["passed"] for row in identifiable_depreciation), "total": len(identifiable_depreciation), "excluded_sold_line_team_count": len(sold_line_teams), "all_checks": depreciation_checks},
        "tax_reconstruction": {"calculation_passed": all(row["calculation_passed"] for row in tax_checks), "calculation_matched": sum(row["calculation_passed"] for row in tax_checks), "calculation_total": len(tax_checks), "next_year_q1_payment_passed": all(row["payment_passed"] for row in tax_checks), "observed_nonzero_next_year_payments": len(tax_payments), "all_checks": tax_checks},
        "production_batch_reconstruction": {"passed": all(row["passed"] for row in production_checks), "matched": sum(row["passed"] for row in production_checks), "total": len(production_checks), "interpretation": "each recorded line assignment incurs exactly one product process fee; combined with formal batch_capacity=1"},
        "reconstructed_counts": {"quarter_states": len(quarter_rows), "observed_cash_actions": len(observed_actions), "qualification_actions": len(qualification_actions), "asset_actions": len(asset_actions), "loan_settlements": len(loan_actions), "team_order_histories": len(order_actions), "delivered_order_actions": sum(row["action_type"] == "order_delivery" for row in order_actions)},
        "simulator_changes_supported": ["empty_initial_qualifications_and_assets", "annual_market_and_iso_payments", "formal_line_installments_residual_and_depreciation", "no_factory_depreciation", "aggregate_half_up_long_loan_interest", "short_loan_half_up_maturity_payment", "tax_loss_carryforward_and_next_q1_payment", "one_unit_per_line_production_batch"],
        "remaining_non_identifiable": ["failed_order_claims_and_complete_auction_bids", "quarterly_non_cash_inventory_between_annual_checkpoints", "sold_line_instance_history_for_four_teams", "exact_bankruptcy_equity_inside_the_failure_quarter"],
        "truth_policy": "inferred states remain inferred; counterfactual branches cannot consume future checkpoints",
    }
    _write_jsonl(match_dir / "inverse_quarter_states.jsonl", quarter_rows)
    _write_jsonl(match_dir / "inverse_actions.jsonl", [*observed_actions, *qualification_actions, *asset_actions, *loan_actions, *order_actions])
    _write_json(match_dir / "inverse_calibration_report.json", report)
    manifest_path = match_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["derived_artifacts"] = sorted(set(manifest.get("derived_artifacts") or []) | {"inverse_actions.jsonl", "inverse_calibration_report.json", "inverse_quarter_states.jsonl"})
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report
