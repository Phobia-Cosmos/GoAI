import json
from pathlib import Path

import pytest

from goai_data.full_sandbox import (
    FullCompetitionArena,
    FullFinancialDynamics,
    build_fixed_xa_rule_pack,
    generate_initial_visible_orders,
)
from goai_data.owned_agent import OwnedEnterpriseRobustPolicy, RobustAgentConfig


BASE_RULES = Path(__file__).resolve().parents[1] / "data" / "processed" / "v2" / "matches" / "LX_XA" / "rules.json"


def rules(team_count: int = 3):
    return build_fixed_xa_rule_pack(json.loads(BASE_RULES.read_text(encoding="utf-8")), match_id="OWNED_TEST", team_count=team_count, seed=17)


def test_owned_policy_uses_one_enterprise_observation_and_records_robust_search() -> None:
    generated = rules()
    orders = generate_initial_visible_orders(
        generated,
        seed=18,
        team_ids=generated["participants"]["team_ids"],
        order_count=8,
        preassigned_count=0,
    )
    owned_id = generated["participants"]["team_ids"][0]
    initial_states = {
        owned_id: {
            "production_lines": [
                {
                    "line_id": "READY-P1",
                    "line_type": "自动线",
                    "product_id": "P1",
                    "ownership": "rented",
                    "cost_wan": 0.0,
                    "book_value_wan": 0.0,
                    "accumulated_depreciation_wan": 0.0,
                    "maintenance_wan_per_year": 0.0,
                    "status": "ready",
                }
            ]
        }
    }
    arena = FullCompetitionArena(FullFinancialDynamics(generated), generated["participants"]["team_ids"], orders, initial_states=initial_states)
    observations = arena.reset()
    policy = OwnedEnterpriseRobustPolicy(owned_id, 17, rules=generated, config=RobustAgentConfig(scenario_count=6))
    action = policy.act(observations[owned_id])
    audit = action["policy_metadata"]["planning_audit"]
    assert action["policy_metadata"]["owned_enterprise_only"] is True
    assert audit["candidate_count"] > 1
    assert audit["information_scope"].startswith("own_private_state")
    assert audit["opponent_model"]["input_scope"] == "released_public_order_results_only"
    assert len(policy.decision_history) == 1
    with pytest.raises(ValueError, match="another enterprise"):
        policy.act(observations[generated["participants"]["team_ids"][1]])


def test_invalid_enterprise_action_is_rejected_without_terminating_match() -> None:
    generated = rules(2)
    arena = FullCompetitionArena(FullFinancialDynamics(generated), generated["participants"]["team_ids"], [])
    arena.reset()
    first, second = arena.agent_ids
    result = arena.step({first: {"action_type": "not_a_real_action"}, second: {"action_type": "hold"}})
    assert result.terminated is False
    assert result.infos[first]["action_status"] == "partially_rejected"
    assert result.infos[first]["action_rejections"] == ["未实现动作：not_a_real_action"]
    assert result.infos[second]["action_status"] == "accepted"
    assert arena.states[first].period == "Y1Q2"


def test_paid_intelligence_is_optional_private_and_charged_by_environment() -> None:
    generated = rules(2)
    generated["financial_rules"]["information_purchase"]["enabled"] = True
    arena = FullCompetitionArena(FullFinancialDynamics(generated), generated["participants"]["team_ids"], [])
    arena.reset()
    buyer, target = arena.agent_ids
    initial_cash = arena.states[buyer].cash_wan
    result = arena.step(
        {
            buyer: {"action_type": "spy_information_purchase", "parameters": {"target_team_id": target}},
            target: {"action_type": "hold"},
        }
    )
    assert result.infos[buyer]["action_status"] == "accepted"
    assert len(arena.states[buyer].intelligence_reports) == 1
    report = arena.states[buyer].intelligence_reports[0]
    assert report["target_team_id"] == target
    assert report["visibility"] == "buyer_private_legally_purchased"
    assert not arena.states[target].intelligence_reports
    expected = initial_cash - 5 - generated["parameters"]["management_fee_per_quarter_wan"]
    assert arena.states[buyer].cash_wan == expected
    assert "intelligence_reports" not in result.observations[target].public_state


def test_public_order_results_hide_referee_contention_trace() -> None:
    generated = rules(2)
    orders = generate_initial_visible_orders(
        generated,
        seed=19,
        team_ids=generated["participants"]["team_ids"],
        order_count=1,
        preassigned_count=0,
    )
    arena = FullCompetitionArena(FullFinancialDynamics(generated), generated["participants"]["team_ids"], orders)
    arena.reset()
    first, second = arena.agent_ids
    order = orders[0]
    claim = {
        "action_type": "auction_bid" if order["order_type"] == "竞单" else "select_order",
        "parameters": {
            "order_id": order["order_id"],
            "bid_wan": order["total_price_wan"],
            "market": order["market"],
            "product": order["product"],
            "submitted_at": 0.1,
        },
    }
    result = arena.step({first: claim, second: {"action_type": "hold"}})
    public_result = result.observations[first].public_state["public_order_results"][0]
    assert public_result["winner_team_id"] == first
    assert "contenders" not in public_result
    assert "trace" not in public_result
    assert "contenders" in arena.order_log[0]
