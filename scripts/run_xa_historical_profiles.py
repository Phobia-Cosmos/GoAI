#!/usr/bin/env python3
"""Run XA historical-path reconstruction and competitive simulations."""

from __future__ import annotations

import argparse
import copy
import json
from collections import defaultdict
from pathlib import Path
from statistics import mean
from typing import Any, Mapping

from goai_data.competition_xlsx import SimulatedCompetitionXlsxImporter, export_competition_xlsx
from goai_data.full_sandbox import FULL_SANDBOX_VERSION, build_fixed_xa_rule_pack
from goai_data.historical_strategies import HISTORICAL_STRATEGY_VERSION, HistoricalXAProfilePolicy, build_historical_xa_profiles
from goai_data.recorded_match import run_recorded_competition, write_recorded_competition


def _number(value: Any, default: float = 0.0) -> float:
    return float(value) if isinstance(value, (int, float)) else default


def _average(rows: list[Mapping[str, Any]], field: str) -> float:
    values = [float(row[field]) for row in rows if isinstance(row.get(field), (int, float))]
    return mean(values) if values else 0.0


def _comparison(mode: str, *, arena: Any, artifacts: Mapping[str, list[dict[str, Any]]], profiles: Mapping[str, Any], official: Mapping[str, Any]) -> dict[str, Any]:
    actual_rank = list(official.get("ranking") or [])
    simulated = arena.final_results()
    simulated_rank = list(simulated.get("ranking") or [])
    simulated_by_team = {row["team_id"]: row for row in simulated.get("states") or []}
    official_by_team = {row["team_id"]: row for row in actual_rank}
    strategy_rows: dict[str, list[str]] = defaultdict(list)
    for team_id, profile in profiles.items():
        strategy_rows[profile.strategy_class].append(team_id)
    strategy_summary = {}
    for strategy, team_ids in sorted(strategy_rows.items()):
        real_survivors = [official_by_team[team_id] for team_id in team_ids if team_id in official_by_team]
        sim_survivors = [simulated_by_team[team_id] for team_id in team_ids if not simulated_by_team[team_id]["bankrupt"]]
        strategy_summary[strategy] = {
            "team_count": len(team_ids),
            "real_bankruptcies": sum(profiles[team_id].bankrupt for team_id in team_ids),
            "simulated_bankruptcies": sum(simulated_by_team[team_id]["bankrupt"] for team_id in team_ids),
            "real_survivor_mean_equity_wan": _average(real_survivors, "owner_equity_wan"),
            "simulated_survivor_mean_equity_wan": _average(sim_survivors, "owner_equity_wan"),
            "real_survivor_mean_potential": _average(real_survivors, "development_potential"),
            "simulated_survivor_mean_potential": _average(sim_survivors, "development_potential"),
        }
    journal = [event for state in arena.states.values() for event in state.journal]
    rejected = sum(len(row.get("action_rejections") or []) for row in artifacts["feedback"])
    common_survivors = sorted(set(official_by_team) & {row["team_id"] for row in simulated_rank})
    potential_mae = mean(abs(simulated_by_team[team_id]["development_potential"] - profiles[team_id].development_potential) for team_id in profiles)
    equity_mae = mean(abs(simulated_by_team[team_id]["owner_equity_wan"] - official_by_team[team_id]["owner_equity_wan"]) for team_id in common_survivors) if common_survivors else None
    assimilations = [event for event in journal if event.get("event_type") == "historical_checkpoint_assimilated"]
    checkpoint_summary = None
    if assimilations:
        cash_residuals = [abs(_number(event.get("cash_residual_wan"))) for event in assimilations]
        noncash_residuals = [abs(_number(event.get("noncash_residual_change_wan"))) for event in assimilations if isinstance(event.get("equity_target_wan"), (int, float))]
        checkpoint_summary = {
            "checkpoint_count": len(assimilations),
            "cash_mean_absolute_residual_wan": mean(cash_residuals) if cash_residuals else 0.0,
            "cash_max_absolute_residual_wan": max(cash_residuals, default=0.0),
            "annual_noncash_mean_absolute_residual_wan": mean(noncash_residuals) if noncash_residuals else 0.0,
            "annual_noncash_max_absolute_residual_wan": max(noncash_residuals, default=0.0),
            "meaning": "unexplained state transition remaining after replaying identifiable historical actions; not an online model score",
        }
    return {
        "format_version": "goai_XA_historical_profile_comparison_v1.0",
        "mode": mode,
        "historical_information_boundary": "uses_full_future_historical_paths_for_calibration_not_online_decision",
        "real_XA": {
            "teams": 27, "bankruptcies": len(official.get("bankruptcies") or []), "survivors": len(actual_rank),
            "delivered_orders": sum(profile.delivered_order_count for profile in profiles.values()),
            "survivor_mean_equity_wan": _average(actual_rank, "owner_equity_wan"),
            "survivor_mean_development_potential": _average(actual_rank, "development_potential"),
            "survivor_mean_score": _average(actual_rank, "official_score"),
        },
        "simulated": {
            "teams": len(simulated_by_team), "bankruptcies": len(simulated.get("bankruptcies") or []), "survivors": len(simulated_rank),
            "awarded_orders": len(arena.order_log),
            "delivered_orders": sum(event.get("event_type") == "order_delivered" for event in journal),
            "defaulted_orders": sum(event.get("event_type") == "order_default_penalty" for event in journal),
            "survivor_mean_equity_wan": _average(simulated_rank, "owner_equity_wan"),
            "survivor_mean_development_potential": _average(simulated_rank, "development_potential"),
            "survivor_mean_score": _average(simulated_rank, "score"),
            "action_rejections": rejected,
        },
        "team_level_error": {"common_survivor_count": len(common_survivors), "survivor_equity_mae_wan": equity_mae, "all_team_development_potential_mae": potential_mae},
        "checkpoint_assimilation": checkpoint_summary,
        "strategy_class_summary": strategy_summary,
        "interpretation": "checkpoint_assisted measures missing transitions against observed cash/annual equity and reproduces observed bankruptcy labels by construction; conditioned tests identifiable actions with observed owners but no financial checkpoints; competitive removes observed owners and is the strongest counterfactual scenario",
    }


def _run(mode: str, *, match_dir: Path, output_root: Path, seed: int, export_xlsx: bool) -> dict[str, Any]:
    profiles, source_orders, inverse_actions = build_historical_xa_profiles(match_dir)
    base = json.loads((match_dir / "rules.json").read_text(encoding="utf-8"))
    match_id = f"SIM_XA_PROFILE_{mode.upper()}"
    rules = build_fixed_xa_rule_pack(base, match_id=match_id, team_count=27, seed=seed, source_rule_path=(match_dir / "rules.json").as_posix())
    team_ids = sorted(profiles)
    rules["participants"] = {"count": len(team_ids), "team_ids": team_ids}
    rules["generation"].update({"mode": f"historical_profile_{mode}", "historical_strategy_version": HISTORICAL_STRATEGY_VERSION, "uses_future_historical_path": True, "online_agent_eligible": False})
    checkpoints: dict[str, dict[int, dict[str, Any]]] = defaultdict(dict)
    historical_line_types: dict[str, dict[int, str]] = defaultdict(dict)
    for row in (json.loads(line) for line in (match_dir / "inverse_quarter_states.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()):
        for line in row.get("production_lines") or []:
            if isinstance(line.get("line_id"), int) and line.get("line_type"):
                historical_line_types[str(row["team_id"])][int(line["line_id"])] = str(line["line_type"])
    if mode == "checkpoint_assisted":
        for row in (json.loads(line) for line in (match_dir / "inverse_quarter_states.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()):
            checkpoints[str(row["team_id"])][int(row["period_index"])] = row
        rules["financial_rules"]["defer_bankruptcy_to_historical_checkpoint"] = True
        rules["generation"]["checkpoint_information_boundary"] = "cash_every_quarter_annual_equity_and_observed_bankruptcy_future_leakage"
    orders = copy.deepcopy(source_orders)
    if mode == "competitive":
        for order in orders:
            order["owner_team_id"] = None
            order["status"] = "-"
    historical_orders_by_team: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for order in source_orders:
        owner = order.get("calibration_owner_team_id")
        if owner:
            historical_orders_by_team[str(owner)].append(order)
    arena, artifacts = run_recorded_competition(
        rules, orders, seed=seed,
        policy_factory=lambda team_id: HistoricalXAProfilePolicy(team_id, rules=rules, profile=profiles[team_id], inverse_actions=inverse_actions, historical_orders=historical_orders_by_team[team_id], historical_line_types=historical_line_types[team_id], mode="competitive" if mode == "competitive" else "conditioned", seed=seed),
        arena_kwargs={
            "preassignment_mode": "initial" if mode == "competitive" else "release_schedule",
            "quarter_checkpoints": checkpoints,
        },
    )
    output_dir = output_root / f"{match_id}_seed_{seed}"
    write_recorded_competition(output_dir, rules=rules, orders=orders, arena=arena, artifacts=artifacts)
    official = json.loads((match_dir / "results.json").read_text(encoding="utf-8"))
    comparison = _comparison(mode, arena=arena, artifacts=artifacts, profiles=profiles, official=official)
    (output_dir / "historical_profile_comparison.json").write_text(json.dumps(comparison, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output_dir / "strategy_profiles.json").write_text(json.dumps({"version": HISTORICAL_STRATEGY_VERSION, "profiles": [profile.to_dict() for profile in profiles.values()]}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if export_xlsx:
        export_competition_xlsx(output_dir / "competition_xlsx", rules=rules, orders=orders, arena=arena)
        SimulatedCompetitionXlsxImporter(output_dir / "competition_xlsx", output_dir / "xlsx_imported").import_bundle()
    manifest_path = output_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"].extend(["historical_profile_comparison.json", "strategy_profiles.json"])
    manifest["historical_calibration_mode"] = mode
    manifest["uses_future_historical_path"] = True
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"mode": mode, "output_dir": output_dir.as_posix(), "comparison": comparison}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--match-dir", type=Path, default=Path("data/processed/v2/matches/LX_XA"))
    parser.add_argument("--output-root", type=Path, default=Path("data/simulations/xa_historical_profiles_v1"))
    parser.add_argument("--seed", type=int, default=20260810)
    parser.add_argument("--mode", action="append", choices=("checkpoint_assisted", "conditioned", "competitive"), dest="modes")
    parser.add_argument("--no-xlsx", action="store_true")
    args = parser.parse_args()
    runs = [_run(mode, match_dir=args.match_dir.resolve(), output_root=args.output_root.resolve(), seed=args.seed, export_xlsx=not args.no_xlsx) for mode in (args.modes or ("checkpoint_assisted", "conditioned", "competitive"))]
    summary = {"sandbox_version": FULL_SANDBOX_VERSION, "historical_strategy_version": HISTORICAL_STRATEGY_VERSION, "runs": runs}
    args.output_root.mkdir(parents=True, exist_ok=True)
    (args.output_root / f"summary_seed_{args.seed}.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
