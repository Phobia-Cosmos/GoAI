#!/usr/bin/env python3
"""Evaluate one owned robust enterprise against uncertain simulated opponents."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import mean
from typing import Any, Mapping

from goai_data.full_sandbox import (
    FixedXABaselinePolicy,
    SeededHeuristicPolicy,
    build_fixed_xa_rule_pack,
    generate_xa_shaped_global_orders,
)
from goai_data.owned_agent import OWNED_AGENT_VERSION, OwnedEnterpriseRobustPolicy, RobustAgentConfig
from goai_data.recorded_match import run_recorded_competition


def _opponent(team_id: str, seed: int, rules: Mapping[str, Any], profile: str):
    if profile == "conservative":
        return FixedXABaselinePolicy(team_id, seed, rules=rules)
    policy = SeededHeuristicPolicy(team_id, seed, rules=rules, complexity_profile="stress" if profile == "aggressive" else "large")
    if profile == "aggressive":
        numeric = int(team_id[-2:]) if team_id[-2:].isdigit() else 0
        policy.strategy = "growth" if numeric % 2 else "operations"
    return policy


def _owned_result(arena: Any, owned_team_id: str, artifacts: Mapping[str, list[dict[str, Any]]]) -> dict[str, Any]:
    results = arena.final_results()
    state = arena.states[owned_team_id]
    ranking = next((row for row in results["ranking"] if row["team_id"] == owned_team_id), None)
    rejections = [
        reason
        for row in artifacts["feedback"]
        if row["agent_id"] == owned_team_id
        for event in row["events"]
        if event.get("event_type") == "action_rejected"
        for reason in [str(event.get("reason"))]
    ]
    return {
        "team_id": owned_team_id,
        "bankrupt": state.bankrupt,
        "bankruptcy_period": state.bankruptcy_period,
        "rank": ranking.get("rank") if ranking else None,
        "score": ranking.get("score") if ranking else 0.0,
        "owner_equity_wan": state.owner_equity_wan,
        "development_potential": ranking.get("development_potential") if ranking else None,
        "assigned_orders": len(state.assigned_orders),
        "delivered_orders": len(state.delivered_orders),
        "defaulted_orders": len(state.defaulted_orders),
        "action_rejection_count": len(rejections),
        "action_rejections": rejections,
        "minimum_cash_wan": min(
            float(row["cash_wan"])
            for row in artifacts["quarter_states"]
            if row["team_id"] == owned_team_id and isinstance(row.get("cash_wan"), (int, float))
        ),
    }


def _run_variant(
    base_rules: Mapping[str, Any],
    *,
    order_seed: int,
    policy_seed: int,
    opponent_profile: str,
    variant: str,
    team_count: int,
    config: RobustAgentConfig,
) -> dict[str, Any]:
    match_id = f"OWNED_{opponent_profile.upper()}_{order_seed}"
    rules = build_fixed_xa_rule_pack(base_rules, match_id=match_id, team_count=team_count, seed=policy_seed)
    orders = generate_xa_shaped_global_orders(rules, seed=order_seed)
    owned_team_id = rules["participants"]["team_ids"][0]
    owned_policy: OwnedEnterpriseRobustPolicy | None = None

    def factory(team_id: str):
        nonlocal owned_policy
        if team_id != owned_team_id:
            return _opponent(team_id, policy_seed, rules, opponent_profile)
        if variant == "robust":
            owned_policy = OwnedEnterpriseRobustPolicy(team_id, policy_seed, rules=rules, config=config)
            return owned_policy
        return FixedXABaselinePolicy(team_id, policy_seed, rules=rules)

    arena, artifacts = run_recorded_competition(rules, orders, seed=policy_seed, policy_factory=factory)
    result = _owned_result(arena, owned_team_id, artifacts)
    result.update(
        {
            "variant": variant,
            "order_seed": order_seed,
            "policy_seed": policy_seed,
            "opponent_profile": opponent_profile,
            "team_count": team_count,
            "global_order_count": len(orders),
            "decision_count": len(owned_policy.decision_history) if owned_policy else 20,
            "decision_audit": owned_policy.decision_history if owned_policy else [],
        }
    )
    return result


def _summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    output = {}
    for variant in ("baseline", "robust"):
        selected = [row for row in rows if row["variant"] == variant]
        output[variant] = {
            "runs": len(selected),
            "mean_score": mean(row["score"] for row in selected),
            "mean_rank": mean((row["rank"] or row["team_count"] + 1) for row in selected),
            "bankruptcy_rate": mean(float(row["bankrupt"]) for row in selected),
            "default_rate": mean(float(row["defaulted_orders"] > 0) for row in selected),
            "mean_equity_wan": mean(row["owner_equity_wan"] for row in selected),
            "mean_development_potential": mean((row["development_potential"] or 0) for row in selected),
            "mean_assigned_orders": mean(row["assigned_orders"] for row in selected),
            "mean_delivered_orders": mean(row["delivered_orders"] for row in selected),
            "mean_minimum_cash_wan": mean(row["minimum_cash_wan"] for row in selected),
            "total_action_rejections": sum(row["action_rejection_count"] for row in selected),
        }
    output["paired"] = {
        "mean_score_delta_robust_minus_baseline": output["robust"]["mean_score"] - output["baseline"]["mean_score"],
        "mean_rank_delta_robust_minus_baseline": output["robust"]["mean_rank"] - output["baseline"]["mean_rank"],
    }
    return output


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-rules", type=Path, default=Path("data/processed/v2/matches/LX_XA/rules.json"))
    parser.add_argument("--output", type=Path, default=Path("data/experiments/owned_agent_robust_v1/results.json"))
    parser.add_argument("--order-seed", type=int, action="append")
    parser.add_argument("--opponent-profile", choices=("conservative", "mixed", "aggressive"), action="append")
    parser.add_argument("--team-count", type=int, default=27)
    parser.add_argument("--scenario-count", type=int, default=48)
    args = parser.parse_args()
    base_rules = json.loads(args.base_rules.read_text(encoding="utf-8"))
    order_seeds = args.order_seed or [20260810, 20260820, 20260830]
    opponent_profiles = args.opponent_profile or ["conservative", "mixed", "aggressive"]
    config = RobustAgentConfig(scenario_count=args.scenario_count)
    rows = []
    for order_seed in order_seeds:
        for opponent_profile in opponent_profiles:
            policy_seed = order_seed - 1
            for variant in ("baseline", "robust"):
                rows.append(
                    _run_variant(
                        base_rules,
                        order_seed=order_seed,
                        policy_seed=policy_seed,
                        opponent_profile=opponent_profile,
                        variant=variant,
                        team_count=args.team_count,
                        config=config,
                    )
                )
    payload = {
        "experiment_id": "owned_agent_robust_v1",
        "agent_version": OWNED_AGENT_VERSION,
        "objective": "one_owned_enterprise_against_uncontrolled_partially_observed_opponents",
        "information_boundary": "owned_private_state_plus_released_public_information_only",
        "formal_XA_parameters_changed": False,
        "config": config.__dict__,
        "summary": _summarize(rows),
        "runs": rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": args.output.as_posix(), "summary": payload["summary"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

