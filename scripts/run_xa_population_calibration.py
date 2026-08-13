"""Calibrate simulated XA population outcomes against aggregate real XA metrics."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from statistics import mean, median
from typing import Any, Mapping, Sequence

from goai_data.full_sandbox import build_fixed_xa_rule_pack, generate_xa_empirical_global_orders
from goai_data.collaborative_agent import COLLABORATIVE_AGENT_VERSION, CollaborativeEnterprisePolicy
from goai_data.recorded_match import run_recorded_competition, write_recorded_competition
from goai_data.xa_population import CLASS_TARGETS, XALateAggressivePopulationPolicy, XARealisticPopulationPolicy, strategy_class_for_team


DEFAULT_MATCH_DIR = Path("data/processed/v2/matches/LX_XA")
DEFAULT_OUTPUT_ROOT = Path("data/experiments/xa_population_calibration_v1")

METRIC_DEFINITIONS = {
    "survivor_mean_equity_wan": "sum(final owner equity of non-bankrupt teams) / non-bankrupt team count",
    "awarded_orders_per_team": "count(orders with a winner) / all participating team count",
    "delivered_orders_per_team": "count(order_delivered events) / all participating team count",
    "delivery_rate_of_awarded": "count(order_delivered events) / count(orders with a winner)",
    "survivor_mean_score": "sum(final score of non-bankrupt teams) / non-bankrupt team count",
    "all_team_mean_score": "sum(final score, bankrupt team treated as zero) / all participating team count",
    "mean_products/markets/iso/completed_lines/purchased_factories": "sum(final capability count of non-bankrupt teams) / non-bankrupt team count",
}


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _avg(rows: Sequence[Mapping[str, Any]], field: str) -> float:
    values = [float(row[field]) for row in rows if isinstance(row.get(field), (int, float))]
    return mean(values) if values else 0.0


def _real_metrics(match_dir: Path) -> dict[str, Any]:
    results = _read_json(match_dir / "results.json")
    orders = _read_jsonl(match_dir / "global_orders.jsonl")
    survivors = list(results.get("ranking") or [])
    teams = 27
    awarded = sum(row.get("final_owner_team_id") not in {None, ""} for row in orders)
    delivered = sum(row.get("final_status") == "已交" for row in orders)
    defaulted = sum(row.get("final_status") == "违约" for row in orders)
    return {
        "teams": teams,
        "survivors": len(survivors),
        "bankruptcies": len(results.get("bankruptcies") or []),
        "survival_rate": len(survivors) / 27,
        "survivor_mean_score": _avg(survivors, "official_score"),
        "all_team_mean_score": sum(float(row.get("official_score", 0)) for row in survivors) / 27,
        "survivor_mean_equity_wan": _avg(survivors, "owner_equity_wan"),
        "survivor_mean_development_potential": _avg(survivors, "development_potential"),
        "orders": len(orders),
        "awarded_orders": awarded,
        "awarded_orders_per_team": awarded / teams,
        "delivered_orders": delivered,
        "delivered_orders_per_team": delivered / teams,
        "delivery_rate_of_awarded": delivered / awarded if awarded else 0.0,
        "defaulted_orders": defaulted,
        "defaulted_orders_per_team": defaulted / teams,
        "unassigned_orders": sum(row.get("final_owner_team_id") in {None, ""} for row in orders),
        "mean_products": 2.89,
        "mean_markets": 4.89,
        "mean_iso": 1.78,
        "mean_completed_lines": 8.83,
        "mean_purchased_factories": 2.39,
        "metric_provenance": "observed_XA_results_orders_and_normalized_aggregate_assets",
    }


def _simulated_metrics(arena: Any, strategy_by_team: Mapping[str, str]) -> dict[str, Any]:
    results = arena.final_results()
    survivors = list(results.get("ranking") or [])
    result_by_team = {row["team_id"]: row for row in results.get("states") or []}
    score_by_team = {row["team_id"]: float(row.get("score", 0.0)) for row in survivors}
    events = [event for state in arena.states.values() for event in state.journal]
    all_scores = [score_by_team.get(team_id, 0.0) for team_id in arena.agent_ids]

    def state_mean(function: Any, *, survivors_only: bool = False) -> float:
        states = [state for state in arena.states.values() if not survivors_only or not state.bankrupt]
        return mean(function(state) for state in states) if states else 0.0

    class_rows: dict[str, dict[str, Any]] = {}
    for strategy_class in CLASS_TARGETS:
        team_ids = [team_id for team_id, value in strategy_by_team.items() if value == strategy_class]
        states = [arena.states[team_id] for team_id in team_ids]
        class_survivors = [result_by_team[team_id] for team_id in team_ids if not result_by_team[team_id]["bankrupt"]]
        class_rows[strategy_class] = {
            "teams": len(team_ids),
            "survivors": len(class_survivors),
            "bankruptcies": len(team_ids) - len(class_survivors),
            "mean_score_with_bankrupt_as_zero": mean(score_by_team.get(team_id, 0.0) for team_id in team_ids),
            "survivor_mean_equity_wan": _avg(class_survivors, "owner_equity_wan"),
            "mean_products": mean(len(state.products) for state in states),
            "mean_markets": mean(len(state.markets) for state in states),
            "mean_iso": mean(len(state.iso) for state in states),
            "mean_completed_lines": mean(len(state.production_lines) for state in states),
            "mean_assigned_orders": mean(len(state.assigned_orders) for state in states),
        }
    awarded = sum(bool(row.get("winner_team_id")) for row in arena.order_log)
    delivered = sum(event.get("event_type") == "order_delivered" for event in events)
    defaulted = sum(event.get("event_type") == "order_default_penalty" for event in events)
    teams = len(arena.states)
    return {
        "teams": teams,
        "survivors": len(survivors),
        "bankruptcies": len(results.get("bankruptcies") or []),
        "survival_rate": len(survivors) / len(arena.states),
        "survivor_mean_score": _avg(survivors, "score"),
        "survivor_median_score": median([float(row["score"]) for row in survivors]) if survivors else 0.0,
        "highest_score": max([float(row["score"]) for row in survivors], default=0.0),
        "all_team_mean_score": mean(all_scores),
        "survivor_mean_equity_wan": _avg(survivors, "owner_equity_wan"),
        "survivor_mean_development_potential": _avg(survivors, "development_potential"),
        "orders": len(arena.global_orders),
        "awarded_orders": awarded,
        "awarded_orders_per_team": awarded / teams,
        "delivered_orders": delivered,
        "delivered_orders_per_team": delivered / teams,
        "delivery_rate_of_awarded": delivered / awarded if awarded else 0.0,
        "defaulted_orders": defaulted,
        "defaulted_orders_per_team": defaulted / teams,
        "unassigned_orders": len(arena.global_orders) - awarded,
        "mean_products": state_mean(lambda state: len(state.products), survivors_only=True),
        "mean_markets": state_mean(lambda state: len(state.markets), survivors_only=True),
        "mean_iso": state_mean(lambda state: len(state.iso), survivors_only=True),
        "mean_completed_lines": state_mean(lambda state: len(state.production_lines), survivors_only=True),
        "mean_purchased_factories": state_mean(lambda state: sum(row.get("ownership") == "purchased" for row in state.factories), survivors_only=True),
        "mean_cash_wan": state_mean(lambda state: state.cash_wan),
        "mean_debt_wan": state_mean(lambda state: state.debt_wan),
        "action_rejections": sum(event.get("event_type") == "action_rejected" for event in events),
        "all_accounts_balanced": all(abs(state.balance_gap_wan) <= 1e-5 for state in arena.states.values()),
        "by_strategy_class": class_rows,
    }


def _differences(real: Mapping[str, Any], simulated: Mapping[str, Any]) -> dict[str, float]:
    fields = (
        "survival_rate", "survivor_mean_score", "all_team_mean_score", "survivor_mean_equity_wan",
        "survivor_mean_development_potential", "awarded_orders", "awarded_orders_per_team", "delivered_orders",
        "delivered_orders_per_team", "delivery_rate_of_awarded", "defaulted_orders", "defaulted_orders_per_team",
        "unassigned_orders", "mean_products", "mean_markets", "mean_iso", "mean_completed_lines", "mean_purchased_factories",
    )
    return {field: round(float(simulated[field]) - float(real[field]), 4) for field in fields}


def run_seed(match_dir: Path, output_root: Path, seed: int, *, record: bool, survivor_policy: str = "hybrid", post_allocation_phase: bool = False, allow_prospective_new_cell: bool = False) -> dict[str, Any]:
    base_rules = _read_json(match_dir / "rules.json")
    templates = _read_jsonl(match_dir / "global_orders.jsonl")
    match_id = f"SIM_XA_POPULATION_{seed}"
    rules = build_fixed_xa_rule_pack(base_rules, match_id=match_id, team_count=27, seed=seed, source_rule_path=(match_dir / "rules.json").as_posix())
    rules["generation"]["mode"] = "fixed_XA_rules_empirical_order_shape_aggregate_population"
    rules["generation"]["population_calibration"] = "aggregate_XA_strategy_classes_without_team_future_paths"
    # Orders are allocated after the operating action phase in the current
    # arena.  A two-quarter grace is the candidate traditional-sandbox
    # interpretation that gives a newly selected order at least one full
    # production opportunity before the terminal due check.
    orders = generate_xa_empirical_global_orders(rules, templates, seed=seed + 1, price_jitter=0.03, due_grace_quarters=2)
    strategy_by_team: dict[str, str] = {}

    def policy_factory(team_id: str) -> Any:
        strategy_class = strategy_class_for_team(team_id, 27)
        strategy_by_team[team_id] = strategy_class
        if survivor_policy == "all_collaborative" or (survivor_policy == "collaborative" and strategy_class != "aggressive_failed"):
            profile = {"leader_growth": "leader", "balanced_expansion": "balanced", "conservative_survivor": "conservative", "aggressive_failed": "conservative"}[strategy_class]
            return CollaborativeEnterprisePolicy(team_id, seed, rules=rules, profile=profile, allow_prospective_new_cell=allow_prospective_new_cell)
        if survivor_policy == "collaborative_late_failure" and strategy_class != "aggressive_failed":
            profile = {"leader_growth": "leader", "balanced_expansion": "balanced", "conservative_survivor": "conservative"}[strategy_class]
            return CollaborativeEnterprisePolicy(team_id, seed, rules=rules, profile=profile, allow_prospective_new_cell=allow_prospective_new_cell)
        if survivor_policy == "collaborative_late_failure" and strategy_class == "aggressive_failed":
            return XALateAggressivePopulationPolicy(team_id, seed, rules=rules)
        return XARealisticPopulationPolicy(team_id, seed, rules=rules, strategy_class=strategy_class)

    arena, artifacts = run_recorded_competition(rules, orders, seed=seed, policy_factory=policy_factory, arena_kwargs={"post_allocation_phase": post_allocation_phase})
    seed_dir = output_root / f"seed_{seed}"
    if record:
        write_recorded_competition(seed_dir, rules=rules, orders=orders, arena=arena, artifacts=artifacts)
    simulated = _simulated_metrics(arena, strategy_by_team)
    real = _real_metrics(match_dir)
    report = {
        "format_version": "goai_XA_population_calibration_v1.0",
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "seed": seed,
        "survivor_policy": survivor_policy,
        "post_allocation_phase": post_allocation_phase,
        "allow_prospective_new_cell": allow_prospective_new_cell,
        "real_XA": real,
        "simulated": simulated,
        "simulated_minus_real": _differences(real, simulated),
        "causal_boundary": "uses real aggregate order shape and strategy-class counts, but no terminal owner, score, bankruptcy label or team future path",
        "metric_definitions": METRIC_DEFINITIONS,
        "provenance": "simulated_calibration_experiment",
    }
    seed_dir.mkdir(parents=True, exist_ok=True)
    (seed_dir / "calibration_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def aggregate_reports(
    output_root: Path,
    reports: Sequence[Mapping[str, Any]],
    *,
    seeds: Sequence[int],
    survivor_policy: str,
    post_allocation_phase: bool,
    allow_prospective_new_cell: bool,
) -> dict[str, Any]:
    if not reports:
        raise ValueError("at least one seed report is required")
    mean_simulated = {
        field: mean(float(report["simulated"][field]) for report in reports)
        for field in reports[0]["simulated"]
        if isinstance(reports[0]["simulated"][field], (int, float, bool))
    }
    real = reports[0]["real_XA"]
    comparison_fields = (
        "survivor_mean_score", "all_team_mean_score", "survivor_mean_equity_wan",
        "survivor_mean_development_potential", "awarded_orders_per_team",
        "delivered_orders_per_team", "delivery_rate_of_awarded",
    )
    aggregate = {
        "format_version": "goai_XA_population_multiseed_calibration_v1.0",
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "seeds": list(seeds),
        "survivor_policy": survivor_policy,
        "post_allocation_phase": post_allocation_phase,
        "allow_prospective_new_cell": allow_prospective_new_cell,
        "collaborative_agent_version": COLLABORATIVE_AGENT_VERSION if survivor_policy in {"collaborative", "collaborative_late_failure", "all_collaborative"} else None,
        "real_XA": real,
        "simulated_seed_metrics": [report["simulated"] for report in reports],
        "mean_simulated": mean_simulated,
        "mean_simulated_minus_real": {field: mean_simulated[field] - float(real[field]) for field in comparison_fields},
        "mean_simulated_as_fraction_of_real": {field: mean_simulated[field] / float(real[field]) if float(real[field]) else 0.0 for field in comparison_fields},
        "metric_definitions": METRIC_DEFINITIONS,
        "reports": [f"seed_{seed}/calibration_report.json" for seed in seeds],
        "provenance": "simulated_calibration_experiment",
    }
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "summary.json").write_text(json.dumps(aggregate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return aggregate


def main() -> int:
    parser = argparse.ArgumentParser(description="运行固定 XA 规则、经验订单形状和聚合企业策略的完整 20 季校准")
    parser.add_argument("--match-dir", type=Path, default=DEFAULT_MATCH_DIR)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--seeds", nargs="+", type=int, default=[20260811, 20260812, 20260813])
    parser.add_argument("--record-all", action="store_true", help="为每个种子保存完整逐季轨迹；默认仅保存校准指标")
    parser.add_argument("--survivor-policy", choices=("hybrid", "collaborative", "collaborative_late_failure", "all_collaborative"), default="hybrid", help="18 家目标存续企业采用的策略；collaborative 使用六专业 Agent 协作；collaborative_late_failure 另用晚期扩张型对手复现破产生命周期；all_collaborative 让 27 家都由协作 Agent 决策并由环境自然判定破产")
    parser.add_argument("--post-allocation-phase", action="store_true", help="在每季度订单分配后开放一次基于实际获单的履约决策，再执行季度结算")
    parser.add_argument("--allow-prospective-new-cell", action="store_true", help="允许订单 Agent 为一个尚无产线的 P1-P3 产品预留扩线能力；仅用于对照实验")
    parser.add_argument("--summarize-existing", action="store_true", help="不重跑比赛，从输出目录中已有的种子报告重建多种子 summary.json")
    args = parser.parse_args()
    match_dir = args.match_dir.resolve()
    output_root = args.output_root.resolve()
    if args.summarize_existing:
        reports = [_read_json(output_root / f"seed_{seed}" / "calibration_report.json") for seed in args.seeds]
        for seed, report in zip(args.seeds, reports):
            if int(report.get("seed", -1)) != seed:
                raise ValueError(f"seed report mismatch: expected {seed}, got {report.get('seed')}")
            expected = (args.survivor_policy, args.post_allocation_phase, args.allow_prospective_new_cell)
            actual = (report.get("survivor_policy"), bool(report.get("post_allocation_phase")), bool(report.get("allow_prospective_new_cell")))
            if actual != expected:
                raise ValueError(f"seed {seed} configuration mismatch: expected {expected}, got {actual}")
    else:
        reports = [run_seed(match_dir, output_root, seed, record=args.record_all or index == 0, survivor_policy=args.survivor_policy, post_allocation_phase=args.post_allocation_phase, allow_prospective_new_cell=args.allow_prospective_new_cell) for index, seed in enumerate(args.seeds)]
    aggregate = aggregate_reports(
        output_root,
        reports,
        seeds=args.seeds,
        survivor_policy=args.survivor_policy,
        post_allocation_phase=args.post_allocation_phase,
        allow_prospective_new_cell=args.allow_prospective_new_cell,
    )
    print(json.dumps(aggregate, ensure_ascii=False, indent=2))
    return 0 if all(report["simulated"]["all_accounts_balanced"] for report in reports) else 1


if __name__ == "__main__":
    raise SystemExit(main())
