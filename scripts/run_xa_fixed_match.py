"""Run one complete match with exact XA parameters and random global orders."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from statistics import mean
from typing import Any

from goai_data.competition_xlsx import SimulatedCompetitionXlsxImporter, export_competition_xlsx
from goai_data.full_sandbox import (
    FULL_SANDBOX_VERSION,
    FixedXABaselinePolicy,
    build_fixed_xa_rule_pack,
    generate_initial_visible_orders,
    generate_xa_shaped_global_orders,
)
from goai_data.recorded_match import RECORDED_MATCH_VERSION, run_recorded_competition, write_recorded_competition


DEFAULT_RULES = Path("data/processed/v2/matches/LX_XA/rules.json")
DEFAULT_OUTPUT_ROOT = Path("data/simulations/xa_fixed_v1")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _mean(rows: list[dict[str, Any]], field: str) -> float:
    values = [float(row[field]) for row in rows if isinstance(row.get(field), (int, float))]
    return mean(values) if values else 0.0


def _real_xa_comparison(base_path: Path, *, arena: Any) -> dict[str, Any] | None:
    match_dir = base_path.parent
    required = (match_dir / "results.json", match_dir / "global_orders.jsonl")
    if not all(path.exists() for path in required):
        return None
    real_results = json.loads(required[0].read_text(encoding="utf-8"))
    real_orders = _read_jsonl(required[1])
    real_survivors = list(real_results.get("ranking") or [])
    simulated_results = arena.final_results()
    simulated_survivors = list(simulated_results.get("ranking") or [])
    simulated_events = [event for state in arena.states.values() for event in state.journal]
    team_count = len(arena.states)
    return {
        "format_version": "goai_real_simulated_XA_comparison_v1.0",
        "comparison_scope": "real XA observed outcome versus calibrated simulator with baseline policies and a new random order seed",
        "not_a_policy_equivalence_test": True,
        "real_XA": {
            "teams": 27,
            "bankruptcies": len(real_results.get("bankruptcies") or []),
            "survivors": len(real_survivors),
            "orders": len(real_orders),
            "delivered_orders": sum(str(row.get("status")) == "已交" for row in real_orders),
            "unassigned_orders": sum(row.get("final_owner_team_id", row.get("owner_team_id")) in {None, ""} for row in real_orders),
            "survivor_mean_equity_wan": _mean(real_survivors, "owner_equity_wan"),
            "survivor_mean_development_potential": _mean(real_survivors, "development_potential"),
            "survivor_mean_score": _mean(real_survivors, "official_score"),
            "all_team_mean_score_with_bankrupt_as_zero": sum(float(row.get("official_score", 0)) for row in real_survivors) / 27,
        },
        "simulated": {
            "teams": team_count,
            "bankruptcies": len(simulated_results.get("bankruptcies") or []),
            "survivors": len(simulated_survivors),
            "orders": len(arena.global_orders),
            "awarded_orders": len(arena.order_log),
            "delivered_orders": sum(event.get("event_type") == "order_delivered" for event in simulated_events),
            "defaulted_orders": sum(event.get("event_type") == "order_default_penalty" for event in simulated_events),
            "survivor_mean_equity_wan": _mean(simulated_survivors, "owner_equity_wan"),
            "survivor_mean_development_potential": _mean(simulated_survivors, "development_potential"),
            "survivor_mean_score": _mean(simulated_survivors, "score"),
            "all_team_mean_score_with_bankrupt_as_zero": sum(float(row.get("score", 0)) for row in simulated_survivors) / team_count,
        },
        "interpretation": [
            "the simulator now uses XA-calibrated settlement semantics, but the random orders and baseline decisions are not the historical XA decisions",
            "a final-score gap therefore measures policy and scenario mismatch as well as remaining dynamics mismatch",
            "exact historical outcome replay remains a separate observed-data acceptance test",
        ],
    }


def _validation(
    *,
    base_rules: dict[str, Any],
    rules: dict[str, Any],
    orders: list[dict[str, Any]],
    arena: Any,
    artifacts: dict[str, list[dict[str, Any]]],
    expected_year_counts: dict[str, int],
    expected_auction_count: int,
    expected_initial_preassigned: int,
) -> dict[str, Any]:
    team_count = len(rules["participants"]["team_ids"])
    step_count = len(artifacts["trace"])
    expected_transitions = team_count * step_count
    year_counts: dict[str, int] = {}
    for order in orders:
        year = str(order["year"])
        year_counts[year] = year_counts.get(year, 0) + 1
    checks = {
        "exact_XA_parameters": rules["parameters"] == base_rules["parameters"],
        "no_rule_parameter_changes": not rules["generation"]["parameter_changes"],
        "twenty_quarters_completed": step_count == 20,
        "all_agents_observed_each_step": len(artifacts["observations"]) == expected_transitions,
        "all_agents_acted_each_step": len(artifacts["actions"]) == expected_transitions,
        "all_agents_received_feedback_each_step": len(artifacts["feedback"]) == expected_transitions,
        "initial_and_feedback_states_recorded": len(artifacts["quarter_states"]) == team_count * (step_count + 1),
        "expected_order_count_shape": year_counts == expected_year_counts,
        "expected_auction_count_shape": sum(order["order_type"] == "竞单" for order in orders) == expected_auction_count,
        "expected_initial_preallocation": sum(order.get("owner_team_id") not in {None, ""} and int(order.get("release_period_index", -1)) == 0 for order in orders) == expected_initial_preassigned,
        "all_accounts_balanced": all(abs(state.balance_gap_wan) <= 1e-5 for state in arena.states.values()),
        "agent_private_observation_isolated": all(
            "other_agents" not in observation["private_state"]
            and "states" not in observation["public_state"]
            for observation in artifacts["observations"]
        ),
        "terminal_results_generated": len(arena.final_results()["ranking"]) + len(arena.final_results()["bankruptcies"]) == team_count,
    }
    return {
        "format_version": "goai_XA_fixed_validation_v1.0",
        "passed": all(checks.values()),
        "checks": checks,
        "counts": {
            "teams": team_count,
            "steps": step_count,
            "orders": len(orders),
            "auctions": sum(order["order_type"] == "竞单" for order in orders),
            "observations": len(artifacts["observations"]),
            "actions": len(artifacts["actions"]),
            "feedback": len(artifacts["feedback"]),
            "quarter_states": len(artifacts["quarter_states"]),
            "events": sum(len(state.journal) for state in arena.states.values()),
            "reports": sum(len(state.reports) for state in arena.states.values()),
            "bankruptcies": sum(state.bankrupt for state in arena.states.values()),
            "initial_public_unassigned_orders": sum(order.get("owner_team_id") in {None, ""} and int(order.get("release_period_index", -1)) == 0 for order in orders),
            "initial_preassigned_orders": sum(order.get("owner_team_id") not in {None, ""} and int(order.get("release_period_index", -1)) == 0 for order in orders),
        },
        "rule_boundary": {
            "formal": "all values under parameters are copied exactly from normalized XA rules.json",
            "candidate": "financial_rules contains deterministic settlement services for unresolved XA procedure details",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="使用固定 XA 参数和随机全局订单运行完整五年多 Agent 比赛")
    parser.add_argument("--base-rules", type=Path, default=DEFAULT_RULES)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--match-id", default="SIM_XA_FIXED")
    parser.add_argument("--seed", type=int, default=20260809)
    parser.add_argument("--team-count", type=int, default=27)
    parser.add_argument("--initial-order-count", type=int, default=0, help="Y1Q1 立即可见的场景扩展订单总数")
    parser.add_argument("--initial-preassigned-count", type=int, default=0, help="初始订单中随机预分配给不同企业的数量")
    parser.add_argument("--no-xlsx", action="store_true")
    args = parser.parse_args()
    if not 0 <= args.initial_preassigned_count <= min(args.initial_order_count, args.team_count):
        parser.error("--initial-preassigned-count 必须不大于初始订单数和企业数")

    base_path = args.base_rules.resolve()
    base_rules = json.loads(base_path.read_text(encoding="utf-8"))
    rules = build_fixed_xa_rule_pack(
        base_rules,
        match_id=args.match_id,
        team_count=args.team_count,
        seed=args.seed,
        source_rule_path=args.base_rules.as_posix(),
    )
    orders = generate_xa_shaped_global_orders(rules, seed=args.seed + 1)
    initial_orders = generate_initial_visible_orders(
        rules,
        seed=args.seed + 2,
        team_ids=rules["participants"]["team_ids"],
        order_count=args.initial_order_count,
        preassigned_count=args.initial_preassigned_count,
    )
    if initial_orders:
        rules["binding_status"] = "XA_fixed_parameters_with_explicit_initial_order_scenario"
        rules["generation"]["mode"] = "fixed_XA_rules_random_orders_with_initial_visibility_extension"
        rules["scenario_overrides"] = {
            "initial_orders": {
                "enabled": True,
                "order_count": len(initial_orders),
                "preassigned_count": args.initial_preassigned_count,
                "release_period": "Y1Q1",
                "provenance": "simulated_scenario_override",
                "formal_XA_difference": "formal XA records first_year_has_orders=false",
            }
        }
        orders = initial_orders + orders
    arena, artifacts = run_recorded_competition(
        rules,
        orders,
        seed=args.seed,
        complexity_profile="large",
        policy_factory=lambda team_id: FixedXABaselinePolicy(team_id, args.seed, rules=rules),
    )
    output_dir = args.output_root.resolve() / f"{args.match_id}_seed_{args.seed}"
    write_recorded_competition(output_dir, rules=rules, orders=orders, arena=arena, artifacts=artifacts)
    xlsx_manifest = None
    imported_manifest = None
    if not args.no_xlsx:
        xlsx_manifest = export_competition_xlsx(output_dir / "competition_xlsx", rules=rules, orders=orders, arena=arena)
        imported_manifest = SimulatedCompetitionXlsxImporter(
            output_dir / "competition_xlsx",
            output_dir / "xlsx_imported",
        ).import_bundle()

    expected_year_counts = {"2": 169, "3": 172, "4": 214, "5": 241}
    if initial_orders:
        expected_year_counts["1"] = len(initial_orders)
    validation = _validation(
        base_rules=base_rules,
        rules=rules,
        orders=orders,
        arena=arena,
        artifacts=artifacts,
        expected_year_counts=expected_year_counts,
        expected_auction_count=24 + sum(order["order_type"] == "竞单" for order in initial_orders),
        expected_initial_preassigned=args.initial_preassigned_count,
    )
    validation["xlsx_exported"] = xlsx_manifest is not None
    validation["xlsx_team_file_count"] = xlsx_manifest["team_count"] if xlsx_manifest else 0
    validation["xlsx_round_trip_imported"] = imported_manifest is not None
    validation["xlsx_imported_team_count"] = imported_manifest["team_count"] if imported_manifest else 0
    (output_dir / "validation.json").write_text(json.dumps(validation, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary = {
        "format_version": RECORDED_MATCH_VERSION,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "match_id": args.match_id,
        "source_match_id": "LX_XA",
        "seed": args.seed,
        "rule_mode": rules["generation"]["mode"],
        "sandbox_version": FULL_SANDBOX_VERSION,
        "validation_passed": validation["passed"],
        **validation["counts"],
        "xlsx_exported": xlsx_manifest is not None,
        "xlsx_round_trip_imported": imported_manifest is not None,
        "output_dir": output_dir.as_posix(),
        "provenance": "simulated",
    }
    (output_dir / "run_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    comparison = _real_xa_comparison(base_path, arena=arena)
    if comparison is not None:
        (output_dir / "real_XA_comparison.json").write_text(json.dumps(comparison, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    manifest_path = output_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"].extend(["validation.json", "run_summary.json"])
    if comparison is not None:
        manifest["files"].append("real_XA_comparison.json")
    if xlsx_manifest is not None:
        manifest["files"].extend(["competition_xlsx/manifest.json", "xlsx_imported/manifest.json"])
    manifest["xlsx_round_trip_imported"] = imported_manifest is not None
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if validation["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
