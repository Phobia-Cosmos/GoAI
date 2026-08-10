"""Record complete multi-agent sandbox matches as agent-consumable episodes."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .decision_system import AgentObservation
from .full_sandbox import (
    FullCompetitionArena,
    FullFinancialDynamics,
    SeededHeuristicPolicy,
    write_simulated_match,
)


RECORDED_MATCH_VERSION = "goai_recorded_match_v1.0"


def _private_state(state: Mapping[str, Any]) -> dict[str, Any]:
    value = copy.deepcopy(dict(state))
    journal = value.pop("journal", [])
    reports = value.pop("reports", [])
    value["journal_event_count"] = len(journal)
    value["report_count"] = len(reports)
    return value


def serialize_observation(observation: AgentObservation, *, step: int) -> dict[str, Any]:
    public = dict(observation.public_state)
    visible_orders = list(public.pop("available_orders", []) or [])
    published_results = list(public.pop("public_order_results", []) or [])
    public.update(
        {
            "available_order_ids": [str(row["order_id"]) for row in visible_orders],
            "published_order_result_count": len(published_results),
            "published_order_ids": [str(row["order_id"]) for row in published_results],
            "global_orders_ref": "global_orders.jsonl",
            "order_results_ref": "order_log.jsonl",
        }
    )
    return {
        "format_version": RECORDED_MATCH_VERSION,
        "observation_id": f"{observation.match_id}:{observation.agent_id}:step-{step}",
        "match_id": observation.match_id,
        "step": step,
        "period": observation.period,
        "period_index": observation.period_index,
        "agent_id": observation.agent_id,
        "private_state": _private_state(observation.private_state),
        "public_state": public,
        "legal_actions": copy.deepcopy(list(observation.legal_actions)),
        "provenance": "simulated",
    }


def compact_state(observation: AgentObservation, *, step: int) -> dict[str, Any]:
    private = observation.private_state
    return {
        "step": step,
        "match_id": observation.match_id,
        "team_id": observation.agent_id,
        "period": observation.period,
        "period_index": observation.period_index,
        "cash_wan": private.get("cash_wan"),
        "owner_equity_wan": private.get("owner_equity_wan"),
        "debt_wan": private.get("debt_wan"),
        "receivables_wan": private.get("receivables_wan"),
        "bankrupt": private.get("bankrupt"),
        "assigned_order_count": len(private.get("assigned_orders") or []),
        "delivered_order_count": len(private.get("delivered_orders") or []),
        "defaulted_order_count": len(private.get("defaulted_orders") or []),
        "event_count": len(private.get("journal") or []),
        "provenance": "simulated",
    }


def run_recorded_competition(
    rules: Mapping[str, Any],
    orders: Sequence[Mapping[str, Any]],
    *,
    seed: int,
    complexity_profile: str = "large",
    policy_factory: Callable[[str], Any] | None = None,
    arena_kwargs: Mapping[str, Any] | None = None,
) -> tuple[FullCompetitionArena, dict[str, list[dict[str, Any]]]]:
    """Run all agents from reset to termination and retain every I/O boundary."""

    team_ids = list((rules.get("participants") or {}).get("team_ids") or [])
    if not team_ids:
        raise ValueError("recorded competition requires participants.team_ids")
    arena = FullCompetitionArena(
        FullFinancialDynamics(rules),
        team_ids,
        orders,
        max_periods=20,
        stop_when_all_bankrupt=False,
        **dict(arena_kwargs or {}),
    )
    policies = (
        {team_id: policy_factory(team_id) for team_id in team_ids}
        if policy_factory is not None
        else {
            team_id: SeededHeuristicPolicy(
                team_id,
                seed,
                rules=rules,
                complexity_profile=complexity_profile,
            )
            for team_id in team_ids
        }
    )
    observations = arena.reset(seed=seed)
    artifacts: dict[str, list[dict[str, Any]]] = {
        "observations": [],
        "actions": [],
        "feedback": [],
        "quarter_states": [],
        "trace": [],
    }
    artifacts["quarter_states"].extend(
        compact_state(observation, step=0) for observation in observations.values()
    )
    while not arena.terminated:
        step = len(artifacts["trace"]) + 1
        period = next(iter(observations.values())).period
        for observation in observations.values():
            artifacts["observations"].append(serialize_observation(observation, step=step))
        actions = {team_id: policies[team_id].act(observations[team_id]) for team_id in team_ids}
        for team_id, action in actions.items():
            artifacts["actions"].append(
                {
                    "format_version": RECORDED_MATCH_VERSION,
                    "action_id": f"{rules.get('match_id')}:{team_id}:step-{step}",
                    "match_id": rules.get("match_id"),
                    "step": step,
                    "period": period,
                    "agent_id": team_id,
                    "observation_id": f"{rules.get('match_id')}:{team_id}:step-{step}",
                    "action_bundle": copy.deepcopy(action),
                    "provenance": "simulated",
                }
            )
        result = arena.step(actions)
        for team_id in team_ids:
            info = copy.deepcopy(dict(result.infos[team_id]))
            feedback = {
                "format_version": RECORDED_MATCH_VERSION,
                "feedback_id": f"{rules.get('match_id')}:{team_id}:step-{step}",
                "match_id": rules.get("match_id"),
                "step": step,
                "period": period,
                "agent_id": team_id,
                "action_id": f"{rules.get('match_id')}:{team_id}:step-{step}",
                "reward": result.rewards[team_id],
                "events": info.get("events") or [],
                "action_status": info.get("action_status"),
                "action_rejections": info.get("action_rejections") or [],
                "bankrupt": info.get("bankrupt"),
                "balance_gap_wan": info.get("balance_gap_wan"),
                "terminated": result.terminated,
                "next_observation_id": None if result.terminated else f"{rules.get('match_id')}:{team_id}:step-{step + 1}",
                "provenance": "simulated",
            }
            artifacts["feedback"].append(feedback)
            observer = getattr(policies[team_id], "observe_feedback", None)
            if callable(observer):
                observer(copy.deepcopy(feedback), result.observations[team_id])
        artifacts["trace"].append(
            {
                "step": step,
                "period": period,
                "actions": copy.deepcopy(actions),
                "rewards": dict(result.rewards),
                "infos": copy.deepcopy(dict(result.infos)),
                "terminated": result.terminated,
                "provenance": "simulated",
            }
        )
        observations = result.observations
        artifacts["quarter_states"].extend(
            compact_state(observation, step=step) for observation in observations.values()
        )
    return arena, artifacts


def _write_jsonl(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def write_recorded_competition(
    output_dir: Path,
    *,
    rules: Mapping[str, Any],
    orders: Sequence[Mapping[str, Any]],
    arena: FullCompetitionArena,
    artifacts: Mapping[str, Sequence[Mapping[str, Any]]],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    write_simulated_match(output_dir, rules=rules, orders=orders, arena=arena)
    for name in ("observations", "actions", "feedback", "quarter_states", "trace"):
        _write_jsonl(output_dir / f"{name}.jsonl", artifacts[name])
    manifest_path = output_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest.update(
        {
            "format_version": RECORDED_MATCH_VERSION,
            "recording_scope": "complete_global_environment_with_agent_private_observation_isolation",
            "files": [
                "manifest.json",
                "rules.json",
                "global_orders.jsonl",
                "teams.jsonl",
                "observations.jsonl",
                "actions.jsonl",
                "feedback.jsonl",
                "quarter_states.jsonl",
                "trace.jsonl",
                "events.jsonl",
                "order_log.jsonl",
                "reports.jsonl",
                "states.jsonl",
                "results.json",
            ],
            "information_policy": "global_environment_truth_isolated_from_agent_private_observations",
        }
    )
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
