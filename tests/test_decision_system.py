from pathlib import Path

from goai_data.decision_system import (
    ArenaRunner,
    CandidateOutcome,
    HistoricalReplayArena,
    MetricAblationExperiment,
    MetricContext,
    MetricSuite,
    ReplayPolicy,
    WeightedDecisionStrategy,
)


DATASET_ROOT = Path("/home/undefined/Disk/datasets/goai/processed/v2")


def candidates() -> list[CandidateOutcome]:
    return [
        CandidateOutcome(
            candidate_id="safe",
            initial_state={"cash_wan": 675, "owner_equity_wan": 675},
            final_state={
                "cash_wan": 300,
                "owner_equity_wan": 760,
                "assets_wan": 900,
                "debt_wan": 140,
                "orders_assigned": 8,
                "orders_delivered": 8,
                "available_capacity": 10,
                "used_capacity": 6,
                "development_potential": 35,
            },
            trajectory=({"cash_wan": 420}, {"cash_wan": 300}),
        ),
        CandidateOutcome(
            candidate_id="growth",
            initial_state={"cash_wan": 675, "owner_equity_wan": 675},
            final_state={
                "cash_wan": 70,
                "owner_equity_wan": 930,
                "assets_wan": 1300,
                "debt_wan": 370,
                "orders_assigned": 12,
                "orders_delivered": 11,
                "available_capacity": 12,
                "used_capacity": 11,
                "development_potential": 70,
            },
            trajectory=({"cash_wan": 150}, {"cash_wan": 70}),
        ),
    ]


def test_metric_profiles_can_change_the_selected_candidate() -> None:
    suite = MetricSuite()
    context = MetricContext(initial_cash_wan=675, cash_buffer_wan=200)
    safe = WeightedDecisionStrategy(suite, "safety").select(candidates(), context)
    growth = WeightedDecisionStrategy(suite, "growth").select(candidates(), context)
    assert safe["selected_candidate_id"] == "safe"
    assert growth["selected_candidate_id"] == "growth"

    experiment = MetricAblationExperiment(suite).compare_profiles(candidates(), context)
    assert set(experiment["comparisons"]) == {"safety", "balanced", "growth"}


def test_historical_replay_arena_runs_all_xa_enterprises_in_lockstep() -> None:
    arena = HistoricalReplayArena(DATASET_ROOT, "LX_XA")
    policies = {agent_id: ReplayPolicy(agent_id) for agent_id in arena.agent_ids}
    result = ArenaRunner().run(arena, policies)
    assert result["agent_count"] == 27
    assert result["steps"] == 19
    assert all(observation.period == "Y5Q4" for observation in result["final_observations"].values())
    assert result["final_observations"]["XA01"].public_state["information_policy"] == "no_other_team_private_cash"
    assert [row["team_id"] for row in result["terminal_results"]["ranking"]][:3] == ["XA07", "XA13", "XA06"]
    assert {row["team_id"]: row["period"] for row in result["terminal_results"]["bankruptcies"]} == {
        "XA04": "Y5Q1", "XA05": "Y4Q1", "XA09": "Y3Q4", "XA14": "Y4Q4", "XA16": "Y3Q4",
        "XA17": "Y4Q4", "XA20": "Y4Q4", "XA23": "Y5Q4", "XA24": "Y5Q1",
    }
    assert result["final_observations"]["XA04"].private_state["bankrupt"] is True
    assert result["final_observations"]["XA07"].private_state["terminal_state"]["score"] == 3790.5


def test_arena_rejects_missing_or_counterfactual_joint_actions() -> None:
    arena = HistoricalReplayArena(DATASET_ROOT, "ZY")
    arena.reset()
    try:
        arena.step({agent_id: {"action_type": "hold"} for agent_id in arena.agent_ids})
    except ValueError as exc:
        assert "invalid joint action" in str(exc)
    else:
        raise AssertionError("counterfactual replay action should be rejected")
