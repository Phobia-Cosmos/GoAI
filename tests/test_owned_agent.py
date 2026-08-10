import json
from pathlib import Path

import pytest

from goai_data.full_sandbox import (
    FullCompetitionArena,
    FullFinancialDynamics,
    build_fixed_xa_rule_pack,
    generate_initial_visible_orders,
)
from goai_data.owned_agent import ComplexBusinessPlanner, OwnedEnterpriseRobustPolicy, RobustAgentConfig, RobustOrderPlanner


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
            "markets": ["本地"],
            "products": ["P1"],
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
    assert audit["business_candidate_count"] >= 5
    assert audit["selected_business_plan"]["action_domains"]
    assert audit["selection_basis"].startswith("hard_constraints")
    assert audit["vpd_role"].startswith("offline_acceptance_metric")
    assert audit["information_scope"].startswith("own_private_state")
    assert audit["opponent_model"]["input_scope"] == "released_public_order_results_only"
    assert len(policy.decision_history) == 1
    policy.observe_feedback(
        {
            "agent_id": owned_id,
            "period": "Y1Q1",
            "action_status": "accepted",
            "action_rejections": [],
            "reward": 0.0,
            "bankrupt": False,
            "events": [],
        },
        observations[owned_id],
    )
    assert policy.feedback_history[0]["information_scope"].startswith("owned_feedback")
    assert policy.decision_history[0]["feedback"]["action_status"] == "accepted"
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
    assert arena.states[first].last_action_feedback["status"] == "partially_rejected"


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
    initial_states = {team_id: {"markets": ["本地"], "products": ["P1"]} for team_id in generated["participants"]["team_ids"]}
    arena = FullCompetitionArena(FullFinancialDynamics(generated), generated["participants"]["team_ids"], orders, initial_states=initial_states)
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


def test_order_planner_reserves_a_post_allocation_production_and_delivery_window() -> None:
    generated = rules(1)
    team_id = generated["participants"]["team_ids"][0]
    orders = generate_initial_visible_orders(generated, seed=20, team_ids=[team_id], order_count=1, preassigned_count=0)
    orders[0]["due_period"] = "Y1Q3"
    orders[0]["due_period_index"] = 2
    initial_states = {
        team_id: {
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
    arena = FullCompetitionArena(FullFinancialDynamics(generated), [team_id], orders, initial_states=initial_states)
    observation = arena.reset()[team_id]
    planner = RobustOrderPlanner(generated, RobustAgentConfig(scenario_count=6), seed=20)
    plan = planner.plan(observation)
    assert plan["selected"].order_ids == ()
    assert len(plan["evaluations"]) == 1


def test_terminal_order_labels_are_not_exposed_to_online_agent() -> None:
    generated = rules(1)
    team_id = generated["participants"]["team_ids"][0]
    orders = generate_initial_visible_orders(generated, seed=21, team_ids=[team_id], order_count=2, preassigned_count=0)
    orders[0].update(
        {
            "final_owner_team_id": team_id,
            "final_status": "已交",
            "final_result_available_at": "match_end_offline_label",
            "calibration_owner_team_id": team_id,
        }
    )
    observation = FullCompetitionArena(FullFinancialDynamics(generated), [team_id], orders).reset()[team_id]
    visible = observation.public_state["available_orders"][0]
    assert visible["owner_team_id"] is None
    assert visible["status"] == "未分配"
    assert not {"final_owner_team_id", "final_status", "final_result_available_at", "calibration_owner_team_id"} & visible.keys()


def test_complex_planner_builds_multi_domain_multi_product_candidates_through_dynamics() -> None:
    generated = rules(1)
    team_id = generated["participants"]["team_ids"][0]
    orders = generate_initial_visible_orders(generated, seed=22, team_ids=[team_id], order_count=6, preassigned_count=0)
    for index, order in enumerate(orders):
        order["product"] = ("P1", "P2", "P3")[index % 3]
        order["market"] = ("本地", "区域", "国内")[index % 3]
        order["iso"] = "ISO9000" if index == 5 else "-"
        order["quantity"] = 12.0
        order["total_price_wan"] = 240.0 + index * 20
    initial = {
        team_id: {
            "cash_wan": 1200.0,
            "owner_equity_wan": 1200.0,
            "products": ["P1", "P2", "P3"],
            "markets": ["本地", "区域", "国内"],
        }
    }
    observation = FullCompetitionArena(FullFinancialDynamics(generated), [team_id], orders, initial_states=initial).reset()[team_id]
    config = RobustAgentConfig(scenario_count=4, max_new_lines_per_quarter=3)
    plan = ComplexBusinessPlanner(generated, config, seed=22).plan(observation)
    assert len(plan["evaluations"]) >= 5
    assert any(len({action.get("parameters", {}).get("product_id") for action in row.accepted_actions if action.get("action_type") == "buy_product_line"}) >= 2 for row in plan["evaluations"])
    assert any(len(row.action_domains) >= 3 for row in plan["evaluations"])
    projected = FullFinancialDynamics(generated).initial_state(team_id, initial_state=initial[team_id], orders=orders)
    for action in plan["selected_actions"]:
        transition = FullFinancialDynamics(generated).apply(projected, action)
        assert transition.status == "success"
        projected = transition.state


def test_outstanding_order_does_not_block_safe_new_claims_or_late_investment_candidates() -> None:
    generated = rules(1)
    team_id = generated["participants"]["team_ids"][0]
    orders = generate_initial_visible_orders(generated, seed=23, team_ids=[team_id], order_count=3, preassigned_count=0)
    for order in orders:
        order.update({"product": "P1", "market": "本地", "total_price_wan": 300.0, "quantity": 1.0, "due_period_index": 18})
    committed = dict(orders[0])
    committed.update({"order_id": "COMMITTED-1", "owner_team_id": team_id, "status": "已分配", "due_period_index": 17})
    initial = {
        team_id: {
            "cash_wan": 1000.0,
            "owner_equity_wan": 1016.0,
            "products": ["P1"],
            "markets": ["本地"],
            "assigned_orders": [committed],
            "product_inventory": {"P1": 1.0},
            "product_inventory_value_wan": {"P1": 16.0},
            "factories": [{"factory_id": "F1", "name": "大厂房", "ownership": "rented", "capacity": 6, "annual_rent_wan": 0.0}],
            "production_lines": [
                {"line_id": "L1", "line_type": "柔性线", "product_id": "P1", "ownership": "purchased", "book_value_wan": 0.0, "maintenance_wan_per_year": 0.0, "status": "ready"}
            ],
        }
    }
    arena = FullCompetitionArena(FullFinancialDynamics(generated), [team_id], orders, initial_states=initial)
    arena.reset()
    arena.states[team_id].year = 4
    arena.states[team_id].quarter = 1
    observation = arena._observations()[team_id]
    policy = OwnedEnterpriseRobustPolicy(team_id, 23, rules=generated, config=RobustAgentConfig(scenario_count=4))
    decision = policy.act(observation)
    assert any(action["action_type"] in {"select_order", "auction_bid"} for action in decision["actions"])
    audit = decision["policy_metadata"]["planning_audit"]
    assert audit["business_demand_summary"]["outstanding_order_count"] == 1
    assert any(
        action.get("action_type") in {"develop_product", "develop_market", "develop_iso", "buy_workshop", "rent_workshop", "buy_product_line", "advertising"}
        for candidate in audit["business_candidates"]
        for action in candidate["accepted_actions"]
    )


def test_joint_schedule_does_not_overcount_slow_line_before_delivery_deadline() -> None:
    generated = rules(1)
    planner = RobustOrderPlanner(generated, RobustAgentConfig(scenario_count=4), seed=24)
    state = {
        "product_inventory": {"P1": 0.0},
        "pending_production": [],
        "pending_lines": [],
        "production_lines": [
            {"line_id": "MANUAL-1", "line_type": "手工线", "product_id": "P1", "status": "ready"}
        ],
    }
    order = {"order_id": "SLOW-1", "product": "P1", "quantity": 2.0, "due_period_index": 8, "status": "已分配"}
    assert planner._schedule_feasible(state, [order], now=4) is False
