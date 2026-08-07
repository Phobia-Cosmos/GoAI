from pathlib import Path

from goai_data.agent import AgentTools, DeterministicAdvisoryAgent, snapshot_from_result


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATABASE = PROJECT_ROOT / "data" / "processed" / "v1" / "goai.sqlite"


def test_rule_gating_and_action_space() -> None:
    tools = AgentTools(DATABASE)
    status = tools.rule_status()
    assert status.status == "success"
    assert status.result["rule_pack"]["simulation_ready"] == 0

    formal = tools.available_actions(mode="formal")
    assert formal.status == "rejected"

    experimental = tools.available_actions(mode="experimental")
    assert experimental.status == "success"
    assert len(experimental.result["actions"]) == 20
    assert {item["canonical_action"] for item in experimental.result["actions"]}.isdisjoint(
        {"order_award", "capital_injection", "tax_payment"}
    )


def test_snapshots_and_cash_simulation() -> None:
    tools = AgentTools(DATABASE)
    historical_result = tools.team_snapshot("ZY02")
    historical = snapshot_from_result(historical_result)
    assert historical.cash_wan == 70
    assert historical.rule_version == "unknown"

    scenario_result = tools.scenario_snapshot()
    scenario = snapshot_from_result(scenario_result)
    assert scenario.cash_wan == 430
    assert scenario.year == 5
    assert scenario.quarter == 4

    simulation = tools.simulate_plan(
        historical,
        [{"action_type": "advertising", "parameters": {"amount_wan": 20}}],
    )
    assert simulation.status == "success"
    assert simulation.result["projected_cash_wan"] == 50
    assert simulation.result["formal_commit_allowed"] is False

    rejected = tools.simulate_plan(
        historical,
        [{"action_type": "advertising", "parameters": {"amount_wan": 80}}],
    )
    assert rejected.status == "rejected"


def test_advisory_agent_compares_candidate_cash_safety() -> None:
    tools = AgentTools(DATABASE)
    snapshot = snapshot_from_result(tools.team_snapshot("ZY02"))
    result = DeterministicAdvisoryAgent(tools).evaluate(
        snapshot,
        [
            {
                "candidate_id": "conservative",
                "actions": [{"action_type": "advertising", "parameters": {"amount_wan": 20}}],
            },
            {
                "candidate_id": "aggressive",
                "actions": [{"action_type": "advertising", "parameters": {"amount_wan": 60}}],
            },
        ],
    )
    assert result.status == "success"
    assert result.result["recommended_candidate_id"] == "conservative"
    assert result.result["formal_commit_allowed"] is False
