import json
from pathlib import Path

from goai_data.xa_dynamics import XACounterfactualArena, XADynamics


RULES = Path("/home/undefined/Disk/datasets/goai/processed/v2/matches/LX_XA/rules.json")
FROZEN_RULES = Path("/home/undefined/Disk/datasets/goai/processed/v2/matches/LX_XA/rules_frozen.json")


def dynamics() -> XADynamics:
    return XADynamics(json.loads(RULES.read_text(encoding="utf-8")))


def test_xa_frozen_rule_pack_is_accepted_by_dynamics() -> None:
    engine = XADynamics(json.loads(FROZEN_RULES.read_text(encoding="utf-8")))
    assert engine.initial_state("XA01").cash_wan == 675


def test_xa_initial_cash_and_management_fee_are_deterministic() -> None:
    engine = dynamics()
    state = engine.initial_state("XA01")
    assert state.cash_wan == 675
    advanced = engine.advance_quarter(state)
    assert advanced.status == "success"
    assert advanced.state.cash_wan == 661
    assert advanced.state.period == "Y1Q2"


def test_xa_short_loan_and_material_arrival_follow_rule_parameters() -> None:
    engine = dynamics()
    state = engine.initial_state("XA01")
    borrowed = engine.apply(state, {"action_type": "short_loan_borrow", "parameters": {"principal_wan": 100, "term_quarters": 4}})
    assert borrowed.status == "success"
    assert borrowed.state.cash_wan == 775
    ordered = engine.apply(borrowed.state, {"action_type": "material_order", "parameters": {"materials": {"R1": 2}}})
    assert ordered.status == "success"
    advanced = engine.advance_quarter(ordered.state)
    assert advanced.status == "success"
    assert advanced.state.material_inventory["R1"] == 2
    assert advanced.state.cash_wan == 745


def test_xa_counterfactual_arena_advances_all_agents_and_isolates_private_state() -> None:
    arena = XACounterfactualArena(dynamics(), ("XA01", "XA02"))
    observations = arena.reset()
    assert observations["XA01"].private_state["cash_wan"] == 675
    action = {agent_id: {"action_type": "hold"} for agent_id in arena.agent_ids}
    result = arena.step(action)
    assert result.observations["XA01"].period == "Y1Q2"
    assert result.observations["XA01"].private_state["cash_wan"] == 661
    assert result.observations["XA01"].public_state["information_policy"] == "private_state_isolation"


def test_xa_shared_order_actions_are_not_silently_serialized() -> None:
    arena = XACounterfactualArena(dynamics(), ("XA01", "XA02"))
    arena.reset()
    actions = {agent_id: {"action_type": "select_order", "parameters": {"order_id": "X21-0001"}} for agent_id in arena.agent_ids}
    try:
        arena.step(actions)
    except ValueError as exc:
        assert "不在可用初始订单池" in str(exc)
    else:
        raise AssertionError("shared order actions must wait for a resolver")


def test_xa_counterfactual_replay_recomputes_from_changed_period_and_supports_custom_initial_state() -> None:
    arena = XACounterfactualArena(
        dynamics(),
        ("XA01", "XA02", "XA03"),
        initial_states={"XA01": {"cash_wan": 700}},
        initial_orders=[{"order_id": "O-1", "year": 2, "owner_team_id": None}],
        max_periods=3,
    )
    result = arena.replay(
        {},
        changed_period_index=0,
        alternative_actions={"XA01": {"action_type": "short_loan_borrow", "parameters": {"principal_wan": 100, "term_quarters": 1}}},
    )
    assert result["counterfactual"] is True
    assert result["agent_ids"] == ["XA01", "XA02", "XA03"]
    assert result["initial_order_count"] == 1
    assert result["trace"][0]["actions"]["XA01"]["action_type"] == "short_loan_borrow"
    assert result["final_states"]["XA01"]["cash_wan"] != result["final_states"]["XA02"]["cash_wan"]


def test_xa_shared_order_claims_use_replaceable_global_allocator() -> None:
    arena = XACounterfactualArena(
        dynamics(),
        ("XA01", "XA02"),
        initial_orders=[{"order_id": "O-1", "market": "本地", "product": "P1"}],
        max_periods=2,
    )
    arena.reset()
    result = arena.step({
        "XA01": {"action_type": "select_order", "parameters": {"order_id": "O-1", "market_leader": True}},
        "XA02": {"action_type": "select_order", "parameters": {"order_id": "O-1", "market_leader": False}},
    })
    assert result.infos["XA01"]["order_allocation"]["winner_team_id"] == "XA01"
    assert result.infos["XA02"]["order_allocation"]["winner_team_id"] == "XA01"
