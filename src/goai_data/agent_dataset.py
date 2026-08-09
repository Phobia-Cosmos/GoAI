"""Build leakage-safe XA datasets for late-joining decision agents.

The normalized historical and simulated match files are judge/offline views.
This module adds an agent-facing index without copying or rewriting those source
artifacts.  Every transition separates information available at decision time
from labels that are only valid for offline analysis.
"""

from __future__ import annotations

import json
import os
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


AGENT_DATASET_VERSION = "goai_agent_dataset_v1.0"
REAL_DATASET_ID = "xa_real_v1"


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> int:
    materialized = list(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in materialized),
        encoding="utf-8",
    )
    return len(materialized)


def _reference(target: Path, from_directory: Path) -> str:
    return Path(os.path.relpath(target.resolve(), from_directory.resolve())).as_posix()


def _period_index(period: str) -> int:
    year, quarter = period.removeprefix("Y").split("Q", 1)
    return (int(year) - 1) * 4 + int(quarter) - 1


def _result_labels(results: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    labels: dict[str, dict[str, Any]] = {}
    for row in results.get("ranking") or []:
        labels[str(row["team_id"])] = {
            "rank": row.get("rank"),
            "official_score": row.get("official_score"),
            "score": row.get("score", row.get("recomputed_score")),
            "owner_equity_wan": row.get("owner_equity_wan"),
            "development_potential": row.get("development_potential"),
            "bankrupt": False,
        }
    for row in results.get("bankruptcies") or []:
        team_id = str(row["team_id"])
        labels.setdefault(team_id, {}).update(
            {
                "bankrupt": True,
                "bankruptcy_period": row.get("period", row.get("bankruptcy_period")),
            }
        )
    return labels


def _decision_event(event: Mapping[str, Any]) -> dict[str, Any] | None:
    if event.get("control_type") not in {"direct_decision", "conditional_decision"}:
        return None
    return {
        "event_id": event.get("event_id"),
        "action": event.get("action"),
        "amount_wan": event.get("amount_wan"),
        "parameters": event.get("parameters") or {},
        "parameter_parse_status": event.get("parameter_parse_status"),
        "provenance": event.get("provenance"),
    }


def build_real_xa_view(source: Path, output: Path) -> dict[str, Any]:
    """Build period-start historical transitions with no opponent leakage."""

    required = ("manifest.json", "rules.json", "teams.jsonl", "events.jsonl", "quarter_states.jsonl", "results.json")
    missing = [name for name in required if not (source / name).exists()]
    if missing:
        raise FileNotFoundError(f"XA real dataset is missing: {', '.join(missing)}")

    source_manifest = _read_json(source / "manifest.json")
    teams = _read_jsonl(source / "teams.jsonl")
    states = _read_jsonl(source / "quarter_states.jsonl")
    events = _read_jsonl(source / "events.jsonl")
    results = _read_json(source / "results.json")
    labels = _result_labels(results)

    events_by_team_period: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    history_count: dict[str, int] = defaultdict(int)
    for event in sorted(events, key=lambda row: (str(row.get("team_id")), int(row.get("sequence_in_source", 0)))):
        events_by_team_period[(str(event.get("team_id")), str(event.get("period")))].append(event)

    transitions: list[dict[str, Any]] = []
    for state in sorted(states, key=lambda row: (str(row["team_id"]), int(row["period_index"]))):
        team_id = str(state["team_id"])
        period = str(state["period"])
        period_events = events_by_team_period[(team_id, period)]
        historical_actions = [value for event in period_events if (value := _decision_event(event)) is not None]
        decision_index = _period_index(period)
        transitions.append(
            {
                "dataset_id": REAL_DATASET_ID,
                "episode_id": f"{REAL_DATASET_ID}:{team_id}",
                "observation_id": f"{REAL_DATASET_ID}:{team_id}:{period}:start",
                "decision_index": decision_index,
                "period": period,
                "decision_time": "period_start",
                "observation": {
                    "agent_id": team_id,
                    "private_state": {
                        "cash_wan": state.get("start_cash_wan"),
                        "known_own_history_event_count": history_count[team_id],
                        "completeness": "cash_at_period_start_plus_external_own_history_reference",
                        "own_history_ref": {
                            "path": _reference(source / "events.jsonl", output),
                            "selector": {
                                "team_id": team_id,
                                "period_index_lt": decision_index,
                                "period_index_derivation": "(year-1)*4+(quarter-1)",
                            },
                        },
                    },
                    "public_state": {
                        "rules_ref": _reference(source / "rules.json", output),
                        "completed_public_years": list(range(1, decision_index // 4 + 1)),
                        "annual_public_ref": _reference(source / "annual_public.jsonl", output),
                        "annual_public_release_policy": "year_y_records_are_available_from_Y(y+1)Q1; source rows require semantic parsing",
                        "runtime_feed_required": ["currently_available_orders", "published_order_results", "announcements"],
                    },
                    "legal_actions": None,
                    "legal_actions_status": "must_be_computed_from_complete_runtime_state_and_XA_rules",
                    "visibility_policy": "own_private_history_plus_released_public_information",
                },
                "offline_labels": {
                    "historical_decision_events": historical_actions,
                    "realized_feedback": {
                        "end_cash_wan": state.get("end_cash_wan"),
                        "event_count": state.get("event_count"),
                        "provenance": state.get("provenance"),
                    },
                    "terminal_result": labels.get(team_id),
                    "label_policy": "trajectory_evidence_not_stepwise_optimal_action",
                },
                "excluded_from_observation": [
                    "other_teams_private_states_and_events",
                    "future_own_events",
                    "future_public_records",
                    "final_order_owner_and_delivery_status",
                    "terminal_rank_and_score",
                ],
                "provenance": "observed_and_derived",
            }
        )
        history_count[team_id] += len(period_events)

    team_ids = sorted({str(row["team_id"]) for row in teams})
    manifest = {
        "format_version": AGENT_DATASET_VERSION,
        "dataset_id": REAL_DATASET_ID,
        "dataset_kind": "real_historical",
        "source_match_id": source_manifest.get("match_id"),
        "baseline": "XA",
        "provenance": ["observed", "derived"],
        "team_count": len(team_ids),
        "transition_count": len(transitions),
        "decision_horizon": 20,
        "source_manifest_ref": _reference(source / "manifest.json", output),
        "transitions_file": "transitions.jsonl",
        "training_policy": {
            "allowed": ["trajectory_analysis", "behavior_cloning_candidate_generation", "offline_evaluation"],
            "forbidden": ["treating_each_historical_action_as_optimal", "using_offline_labels_in_observation", "opponent_private_state_leakage"],
        },
        "limitations": [
            "period-start private state is cash-complete but not a complete historical balance-sheet snapshot",
            "annual public rows need semantic parsing and explicit release-time confirmation",
            "legal actions require a complete runtime state supplied when the agent connects",
        ],
    }
    _write_json(output / "manifest.json", manifest)
    _write_jsonl(output / "transitions.jsonl", transitions)
    return manifest


def build_simulated_xa_view(source: Path, output: Path) -> dict[str, Any]:
    """Build simulator transitions from saved pre-state, action and feedback rows."""

    required = ("manifest.json", "rules.json", "teams.jsonl", "trace.jsonl", "quarter_states.jsonl", "results.json")
    missing = [name for name in required if not (source / name).exists()]
    if missing:
        raise FileNotFoundError(f"XA simulation is missing: {', '.join(missing)}")

    source_manifest = _read_json(source / "manifest.json")
    teams = _read_jsonl(source / "teams.jsonl")
    states = _read_jsonl(source / "quarter_states.jsonl")
    trace = _read_jsonl(source / "trace.jsonl")
    labels = _result_labels(_read_json(source / "results.json"))
    states_by_team_step = {(str(row["team_id"]), int(row["step"])): row for row in states}
    recorded_mode = all(
        (source / name).exists()
        for name in ("observations.jsonl", "actions.jsonl", "feedback.jsonl")
    )

    transitions: list[dict[str, Any]] = []
    if recorded_mode:
        observations_by_key = {
            (str(row["agent_id"]), int(row["step"])): row
            for row in _read_jsonl(source / "observations.jsonl")
        }
        feedback_by_key = {
            (str(row["agent_id"]), int(row["step"])): row
            for row in _read_jsonl(source / "feedback.jsonl")
        }
        action_rows = _read_jsonl(source / "actions.jsonl")
        for action_row in sorted(action_rows, key=lambda row: (int(row["step"]), str(row["agent_id"]))):
            step = int(action_row["step"])
            team_id = str(action_row["agent_id"])
            period = str(action_row["period"])
            observation_row = observations_by_key[(team_id, step)]
            feedback_row = feedback_by_key[(team_id, step)]
            after = states_by_team_step.get((team_id, step))
            public_state = dict(observation_row["public_state"])
            public_state["global_orders_ref"] = _reference(source / "global_orders.jsonl", output)
            public_state["order_results_ref"] = _reference(source / "order_log.jsonl", output)
            transitions.append(
                {
                    "dataset_id": source.name,
                    "episode_id": f"{source.name}:{team_id}",
                    "observation_id": observation_row["observation_id"],
                    "decision_index": step - 1,
                    "period": period,
                    "decision_time": "period_start",
                    "observation": {
                        "agent_id": team_id,
                        "private_state": observation_row["private_state"],
                        "public_state": public_state,
                        "legal_actions": observation_row["legal_actions"],
                        "visibility_policy": public_state.get("information_policy"),
                    },
                    "offline_labels": {
                        "action_bundle": action_row["action_bundle"],
                        "reward": feedback_row.get("reward"),
                        "environment_feedback": feedback_row,
                        "realized_feedback": after,
                        "terminal_result": labels.get(team_id),
                        "label_policy": "generated_cash_aware_baseline_policy_not_optimal_action",
                    },
                    "excluded_from_observation": [
                        "other_agents_private_states",
                        "unreleased_global_orders",
                        "future_actions_and_feedback",
                        "terminal_rank_and_score",
                    ],
                    "provenance": "simulated",
                }
            )
    else:
        for trace_row in sorted(trace, key=lambda row: int(row["step"])):
            step = int(trace_row["step"])
            period = str(trace_row["period"])
            for team_id, action in sorted((trace_row.get("actions") or {}).items()):
                before = states_by_team_step.get((team_id, step - 1))
                after = states_by_team_step.get((team_id, step))
                if before is None or after is None:
                    raise ValueError(f"missing simulation state pair for {team_id} step {step}")
                transitions.append(
                    {
                        "dataset_id": source.name,
                        "episode_id": f"{source.name}:{team_id}",
                        "observation_id": f"{source.name}:{team_id}:{period}:start",
                        "decision_index": step - 1,
                        "period": period,
                        "decision_time": "period_start",
                        "observation": {
                            "agent_id": team_id,
                            "private_state": {
                                key: before.get(key)
                                for key in (
                                    "cash_wan",
                                    "owner_equity_wan",
                                    "debt_wan",
                                    "receivables_wan",
                                    "bankrupt",
                                    "assigned_order_count",
                                    "delivered_order_count",
                                    "defaulted_order_count",
                                    "event_count",
                                )
                            },
                            "public_state": {
                                "rules_ref": _reference(source / "rules.json", output),
                                "global_orders_ref": _reference(source / "global_orders.jsonl", output),
                                "order_visibility_rule": "release_period_index<=decision_index and owner_team_id is empty",
                            },
                            "legal_actions": None,
                            "legal_actions_status": "recompute_with_FullFinancialDynamics_from_full_state",
                            "visibility_policy": "simulator_private_state_isolation",
                        },
                        "offline_labels": {
                            "action_bundle": action,
                            "reward": (trace_row.get("rewards") or {}).get(team_id),
                            "realized_feedback": after,
                            "terminal_result": labels.get(team_id),
                            "label_policy": "generated_baseline_policy_not_optimal_action",
                        },
                        "excluded_from_observation": [
                            "other_agents_private_states",
                            "future_actions_and_feedback",
                            "terminal_rank_and_score",
                        ],
                        "provenance": "simulated",
                    }
                )

    manifest = {
        "format_version": AGENT_DATASET_VERSION,
        "dataset_id": source.name,
        "dataset_kind": "simulated",
        "source_match_id": source_manifest.get("source_match_id", "LX_XA"),
        "simulated_match_id": source_manifest.get("match_id"),
        "baseline": "XA",
        "generation_seed": source_manifest.get("generation_seed"),
        "provenance": ["simulated"],
        "team_count": len(teams),
        "transition_count": len(transitions),
        "decision_horizon": len(trace),
        "source_manifest_ref": _reference(source / "manifest.json", output),
        "transitions_file": "transitions.jsonl",
        "training_eligible": bool(source_manifest.get("training_eligible", False)),
        "observation_completeness": "full_decision_state_without_journal_report_blobs" if recorded_mode else "compact_financial_summary",
        "limitations": [
            "journal and annual report bodies are stored in separate source files and represented by counts",
            "actions come from seeded heuristic policies and are baseline behavior, not optimal labels",
        ],
    }
    _write_json(output / "manifest.json", manifest)
    _write_jsonl(output / "transitions.jsonl", transitions)
    return manifest


def build_xa_agent_dataset(data_root: Path, output_root: Path, simulation_sources: Sequence[Path]) -> dict[str, Any]:
    data_root = data_root.resolve()
    output_root = output_root.resolve()
    real_source = data_root / "processed" / "v2" / "matches" / "LX_XA"
    real_manifest = build_real_xa_view(real_source, output_root / "real")
    simulation_manifests = [
        build_simulated_xa_view(source.resolve(), output_root / "simulated" / source.name)
        for source in simulation_sources
    ]
    catalog = {
        "format_version": AGENT_DATASET_VERSION,
        "baseline": "XA",
        "objective": "late-joining partially observable rolling decision support",
        "real": {"manifest": "real/manifest.json", **real_manifest},
        "simulated": [
            {"manifest": f"simulated/{manifest['dataset_id']}/manifest.json", **manifest}
            for manifest in simulation_manifests
        ],
        "information_boundary": {
            "available_at_connection": ["XA_rules", "current_own_state", "own_operation_history_to_cutoff", "released_public_information"],
            "available_after_each_action": ["platform_feedback", "updated_own_state", "newly_released_public_information"],
            "never_assumed_available": ["opponent_private_operations", "opponent_private_state", "future_information", "terminal_result"],
        },
        "metric_policy": {
            "required": ["hard_constraint_feasibility", "cash_safety", "solvency", "competition_terminal_score"],
            "optional_plugins": ["VPD", "PSS", "EPSS", "capacity_utilization", "strategy_stability"],
            "vpd_required": False,
        },
    }
    _write_json(output_root / "catalog.json", catalog)
    return catalog
