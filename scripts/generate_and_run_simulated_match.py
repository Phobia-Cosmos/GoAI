"""Generate a seeded rule pack and run a complete multi-team sandbox match."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from goai_data.competition_xlsx import SimulatedCompetitionXlsxImporter, export_competition_xlsx
from goai_data.full_sandbox import (
    COMPLEXITY_PROFILES,
    FULL_SANDBOX_VERSION,
    FullCompetitionArena,
    FullFinancialDynamics,
    SeededHeuristicPolicy,
    generate_global_orders,
    generate_simulated_rule_pack,
    write_simulated_match,
)


DEFAULT_DATASET = Path("/home/undefined/Disk/datasets/goai/processed/v2")
SOURCE_TEAM_COUNTS = {"AB": 20, "AG": 19, "CA": 20, "CB": 20, "CD": 20, "CE": 20, "EA": 20, "EB": 20, "EC": 20, "EF": 20, "LX_XA": 27, "OP": 20, "ZY": 18, "ZZ": 16}


def _load_base_rule(dataset_root: Path, base_match: str, explicit_path: Path | None = None) -> tuple[dict[str, Any], Path]:
    if explicit_path is not None:
        path = explicit_path.resolve()
    else:
        match_dir = dataset_root.resolve() / "matches" / base_match
        inferred = match_dir / "rules_inferred_v2.json"
        path = inferred if inferred.exists() else match_dir / "rules.json"
    if not path.exists():
        raise FileNotFoundError(f"找不到基础规则：{path}")
    return json.loads(path.read_text(encoding="utf-8")), path


def _run_one(args: argparse.Namespace, base_match: str, *, match_id: str, seed: int) -> dict[str, Any]:
    base, base_path = _load_base_rule(args.dataset_root, base_match, args.base_rules if not args.all_base_matches else None)
    profile = COMPLEXITY_PROFILES[args.scale_profile]
    team_count = args.team_count if args.team_count is not None else max(int(profile["team_count"]), SOURCE_TEAM_COUNTS.get(base_match, int(profile["team_count"])))
    variability = args.variability if args.variability is not None else float(profile["variability"])
    initial_cash_multiplier = args.initial_cash_multiplier if args.initial_cash_multiplier is not None else float(profile["initial_cash_multiplier"])
    auction_ratio = args.auction_ratio if args.auction_ratio is not None else float(profile["auction_ratio"])
    orders_per_year = args.orders_per_year if args.orders_per_year is not None else int(profile["orders_per_year"])
    rules = generate_simulated_rule_pack(base, seed=seed, match_id=match_id, variability=variability, team_count=team_count, source_match_id=base_match, source_rule_path=str(base_path), initial_cash_multiplier=initial_cash_multiplier, complexity_profile=args.scale_profile)
    order_years = (1, 2, 3, 4, 5) if (rules.get("parameters") or {}).get("first_year_has_orders") else (2, 3, 4, 5)
    orders = generate_global_orders(rules, seed=seed + 1, orders_per_year=orders_per_year, years=order_years, auction_ratio=auction_ratio, complexity=args.scale_profile)
    team_ids = rules["participants"]["team_ids"]
    dynamics = FullFinancialDynamics(rules)
    arena = FullCompetitionArena(dynamics, team_ids, orders)
    policies = {team_id: SeededHeuristicPolicy(team_id, seed, rules=rules, complexity_profile=args.scale_profile) for team_id in team_ids}
    observations = arena.reset(seed=seed)
    trace = []
    quarter_states = []

    def state_snapshot(team_id: str, observation: Any, step: int) -> dict[str, Any]:
        private = observation.private_state
        return {"step": step, "match_id": match_id, "team_id": team_id, "period": observation.period, "period_index": observation.period_index, "cash_wan": private.get("cash_wan"), "owner_equity_wan": private.get("owner_equity_wan"), "debt_wan": private.get("debt_wan"), "receivables_wan": private.get("receivables_wan"), "bankrupt": private.get("bankrupt"), "assigned_order_count": len(private.get("assigned_orders") or []), "delivered_order_count": len(private.get("delivered_orders") or []), "defaulted_order_count": len(private.get("defaulted_orders") or []), "event_count": len(private.get("journal") or [])}

    quarter_states.extend(state_snapshot(team_id, observation, 0) for team_id, observation in observations.items())
    while not arena.terminated:
        actions = {team_id: policies[team_id].act(observations[team_id]) for team_id in team_ids}
        result = arena.step(actions)
        trace_row = {"step": len(trace) + 1, "period": next(iter(observations.values())).period, "actions": actions, "rewards": dict(result.rewards), "infos": dict(result.infos)}
        if args.full_trace:
            trace_row["states"] = {team_id: observation.private_state for team_id, observation in result.observations.items()}
        trace.append(trace_row)
        observations = result.observations
        quarter_states.extend(state_snapshot(team_id, observation, len(trace)) for team_id, observation in observations.items())

    output_dir = args.output_root.resolve() / f"{match_id}_seed_{seed}"
    write_simulated_match(output_dir, rules=rules, orders=orders, arena=arena)
    (output_dir / "trace.jsonl").write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in trace), encoding="utf-8")
    (output_dir / "quarter_states.jsonl").write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in quarter_states), encoding="utf-8")
    xlsx_manifest = None
    imported_manifest = None
    if not args.no_xlsx:
        bundle_dir = output_dir / "competition_xlsx"
        xlsx_manifest = export_competition_xlsx(bundle_dir, rules=rules, orders=orders, arena=arena)
        if not args.no_round_trip:
            imported_manifest = SimulatedCompetitionXlsxImporter(bundle_dir, output_dir / "xlsx_imported").import_bundle()
    balance_gaps = {team_id: arena.states[team_id].balance_gap_wan for team_id in team_ids}
    summary = {
        "match_id": match_id,
        "source_match_id": base_match,
        "source_rule_path": str(base_path),
        "sandbox_version": FULL_SANDBOX_VERSION,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "seed": seed,
        "complexity_profile": args.scale_profile,
        "variability": variability,
        "initial_cash_multiplier": initial_cash_multiplier,
        "team_count": len(team_ids),
        "order_count": len(orders),
        "steps": len(trace),
        "event_count": sum(len(state.journal) for state in arena.states.values()),
        "event_type_count": len({str(event.get("event_type")) for state in arena.states.values() for event in state.journal}),
        "distinct_event_types": sorted({str(event.get("event_type")) for state in arena.states.values() for event in state.journal}),
        "final_periods": sorted({state.period for state in arena.states.values()}),
        "bankruptcy_count": sum(state.bankrupt for state in arena.states.values()),
        "annual_report_count": sum(len(state.reports) for state in arena.states.values()),
        "allocation_count": len(arena.order_log),
        "assigned_order_count": sum(1 for row in arena.order_log if row.get("winner_team_id")),
        "selection_order_count": sum(1 for row in arena.order_log if row.get("trace", {}).get("order_type") == "选单"),
        "auction_order_count": sum(1 for row in arena.order_log if row.get("trace", {}).get("order_type") == "竞单"),
        "delivered_order_count": sum(len(state.delivered_orders) for state in arena.states.values()),
        "defaulted_order_count": sum(len(state.defaulted_orders) for state in arena.states.values()),
        "market_count": len((rules.get("parameters") or {}).get("markets") or {}),
        "product_count": len((rules.get("parameters") or {}).get("products") or {}),
        "max_absolute_balance_gap_wan": max(abs(value) for value in balance_gaps.values()),
        "accounting_balanced": all(abs(value) <= 1e-5 for value in balance_gaps.values()),
        "xlsx_exported": xlsx_manifest is not None,
        "xlsx_round_trip_imported": imported_manifest is not None,
        "xlsx_team_file_count": xlsx_manifest["team_count"] if xlsx_manifest else 0,
        "xlsx_file_count": len(xlsx_manifest.get("files", {}).get("enterprise", [])) if xlsx_manifest else 0,
        "output_dir": str(output_dir),
        "provenance": "simulated",
    }
    (output_dir / "run_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="从任意比赛规则包生成随机五年多企业沙盘及比赛式 XLSX 资料")
    parser.add_argument("--dataset-root", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--base-match", default="LX_XA", help="基础比赛 ID，例如 AB、AG、ZY、ZZ、LX_XA")
    parser.add_argument("--all-base-matches", action="store_true", help="为数据集 matches/ 下的所有比赛各生成一场")
    parser.add_argument("--base-rules", type=Path, default=None, help="显式规则 JSON；仅单场模式使用")
    parser.add_argument("--output-root", type=Path, default=Path("/home/undefined/Disk/datasets/goai/simulations"))
    parser.add_argument("--match-id", default=None, help="新比赛 ID；默认 SIM_<基础比赛>")
    parser.add_argument("--seed", type=int, default=20260807)
    parser.add_argument("--scale-profile", choices=sorted(COMPLEXITY_PROFILES), default="large", help="规模档位；显式数量参数会覆盖档位")
    parser.add_argument("--team-count", type=int, default=None)
    parser.add_argument("--orders-per-year", type=int, default=None)
    parser.add_argument("--variability", type=float, default=None)
    parser.add_argument("--auction-ratio", type=float, default=None)
    parser.add_argument("--initial-cash-multiplier", type=float, default=None)
    parser.add_argument("--match-id-prefix", default="SIM", help="生成比赛 ID 前缀")
    parser.add_argument("--no-xlsx", action="store_true", help="不导出比赛式 XLSX")
    parser.add_argument("--no-round-trip", action="store_true", help="导出 XLSX 后不执行回读验证")
    parser.add_argument("--full-trace", action="store_true", help="保存每一步完整私有状态；大型批次默认仅保存紧凑快照")
    args = parser.parse_args()
    if args.auction_ratio is not None and not 0 <= args.auction_ratio <= 1: parser.error("--auction-ratio 必须在 0 到 1 之间")
    if args.all_base_matches:
        base_matches = sorted(path.name for path in (args.dataset_root.resolve() / "matches").iterdir() if path.is_dir() and ((path / "rules_inferred_v2.json").exists() or (path / "rules.json").exists()))
    else:
        base_matches = [args.base_match]
    summaries = []
    for index, base_match in enumerate(base_matches):
        match_id = args.match_id if len(base_matches) == 1 and args.match_id else f"{args.match_id_prefix}_{base_match}"
        summaries.append(_run_one(args, base_match, match_id=match_id, seed=args.seed + index * 1000))
    batch_summary = {
        "format_version": "goai_simulated_match_batch_v1.0",
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "dataset_root": str(args.dataset_root.resolve()),
        "seed": args.seed,
        "all_base_matches": args.all_base_matches,
        "generated_matches": len(summaries),
        "complexity_profile": args.scale_profile,
        "total_team_count": sum(row["team_count"] for row in summaries),
        "total_order_count": sum(row["order_count"] for row in summaries),
        "total_event_count": sum(row["event_count"] for row in summaries),
        "total_assigned_order_count": sum(row["assigned_order_count"] for row in summaries),
        "total_delivered_order_count": sum(row["delivered_order_count"] for row in summaries),
        "total_defaulted_order_count": sum(row["defaulted_order_count"] for row in summaries),
        "total_xlsx_file_count": sum(row["xlsx_file_count"] for row in summaries),
        "accounting_balanced": all(row["accounting_balanced"] for row in summaries),
        "xlsx_round_trip_imported": all(row["xlsx_round_trip_imported"] for row in summaries) if not args.no_xlsx and not args.no_round_trip else False,
        "runs": summaries,
        "provenance": "simulated",
    }
    args.output_root.mkdir(parents=True, exist_ok=True)
    batch_name = f"all_template_generation_summary_seed_{args.seed}.json" if args.all_base_matches else f"{summaries[0]['match_id']}_generation_summary_seed_{args.seed}.json"
    (args.output_root / batch_name).write_text(json.dumps(batch_summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(batch_summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
