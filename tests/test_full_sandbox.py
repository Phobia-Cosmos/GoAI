import json
from pathlib import Path

from goai_data.full_sandbox import (
    FullCompetitionArena,
    FullFinancialDynamics,
    SeededHeuristicPolicy,
    generate_global_orders,
    generate_simulated_rule_pack,
)


BASE_RULES = Path("/home/undefined/Disk/datasets/goai/processed/v2/matches/LX_XA/rules.json")


def rules(seed: int = 1, team_count: int = 3):
    return generate_simulated_rule_pack(json.loads(BASE_RULES.read_text(encoding="utf-8")), seed=seed, match_id="TEST", team_count=team_count)


def assert_balanced(state) -> None:
    assert abs(state.balance_gap_wan) <= 1e-6


def test_seeded_rule_and_order_generation_is_reproducible() -> None:
    first_rules = rules(11)
    second_rules = rules(11)
    assert first_rules == second_rules
    first = generate_global_orders(first_rules, seed=12, orders_per_year=4)
    second = generate_global_orders(second_rules, seed=12, orders_per_year=4)
    assert first == second
    assert len(first) == 16
    assert min(row["year"] for row in first) == 2
    assert all(row["provenance"] == "simulated" and row["owner_team_id"] is None for row in first)


def test_large_profile_expands_order_attributes_and_complexity() -> None:
    generated = generate_simulated_rule_pack(json.loads(BASE_RULES.read_text(encoding="utf-8")), seed=13, match_id="LARGE", team_count=24, complexity_profile="large", initial_cash_multiplier=3.0)
    orders = generate_global_orders(generated, seed=14, orders_per_year=100, auction_ratio=0.18, complexity="large")
    assert generated["generation"]["complexity_profile"] == "large"
    assert generated["parameters"]["initial_cash_wan"] >= 1500
    assert len(orders) == 400
    assert {row["order_type"] for row in orders} == {"选单", "竞单"}
    assert all(row["customer_segment"] and row["priority"] for row in orders)
    assert len({(row["market"], row["product"]) for row in orders}) >= 20


def test_full_financial_lifecycle_stays_balanced_and_generates_reports() -> None:
    engine = FullFinancialDynamics(rules(21, 1))
    state = engine.initial_state("TEST01")
    for action in (
        {"action_type": "buy_workshop", "parameters": {"factory": "小厂房"}},
        {"action_type": "buy_product_line", "parameters": {"line_type": "手工线", "product_id": "P1"}},
        {"action_type": "emergency_purchase", "parameters": {"material_id": "R1", "quantity": 2}},
        {"action_type": "production", "parameters": {"product_id": "P1", "quantity": 1}},
    ):
        transition = engine.apply(state, action)
        assert transition.status == "success"
        state = transition.state
        assert_balanced(state)
    state = engine.advance_quarter(state).state
    state = engine.advance_quarter(state).state
    assert state.product_inventory["P1"] == 1
    state.assigned_orders.append({"order_id": "O1", "product": "P1", "quantity": 1, "total_price_wan": 80, "receivable_term_quarters": 2, "due_period_index": 5, "status": "已分配"})
    state = engine.apply(state, {"action_type": "order_delivery", "parameters": {"order_id": "O1"}}).state
    assert state.receivables
    state = engine.apply(state, {"action_type": "receivable_discount", "parameters": {"receivable_id": state.receivables[0]["receivable_id"]}}).state
    assert not state.receivables
    assert_balanced(state)
    state = engine.advance_quarter(state).state
    state = engine.advance_quarter(state).state
    assert len(state.reports) == 1
    assert abs(state.reports[0]["balance_sheet"]["balance_gap_wan"]) <= 1e-6


def test_order_default_penalty_is_an_executable_transition() -> None:
    generated = rules(31, 1)
    engine = FullFinancialDynamics(generated)
    state = engine.initial_state("TEST01")
    state.assigned_orders.append({"order_id": "LATE", "product": "P1", "quantity": 1, "total_price_wan": 100, "due_period_index": 1, "status": "已分配"})
    before_equity = state.owner_equity_wan
    state = engine.advance_quarter(state).state
    assert state.defaulted_orders[0]["order_id"] == "LATE"
    expected = generated["parameters"]["management_fee_per_quarter_wan"] + 100 * generated["parameters"]["default_penalty_rate"]
    assert round(before_equity - state.owner_equity_wan, 6) == round(expected, 6)
    assert_balanced(state)


def test_long_loan_interest_principal_depreciation_and_tax_close_at_year_end() -> None:
    generated = rules(36, 1)
    engine = FullFinancialDynamics(generated)
    state = engine.initial_state("TEST01")
    state = engine.apply(state, {"action_type": "long_loan_borrow", "parameters": {"principal_wan": 100, "term_years": 1}}).state
    state = engine.apply(state, {"action_type": "buy_workshop", "parameters": {"factory": "小厂房"}}).state
    initial_book = state.factories[0]["book_value_wan"]
    for _ in range(4):
        state = engine.advance_quarter(state).state
    assert not state.long_loans
    assert state.factories[0]["book_value_wan"] < initial_book
    assert len(state.reports) == 1
    assert state.reports[0]["income_statement"]["details"]["interest_expense"] < 0
    assert_balanced(state)


def test_multi_team_environment_runs_twenty_quarters_with_balanced_accounts() -> None:
    generated = rules(41, 3)
    orders = generate_global_orders(generated, seed=42, orders_per_year=5)
    engine = FullFinancialDynamics(generated)
    arena = FullCompetitionArena(engine, generated["participants"]["team_ids"], orders)
    policies = {team_id: SeededHeuristicPolicy(team_id, 41) for team_id in arena.agent_ids}
    observations = arena.reset()
    steps = 0
    while not arena.terminated:
        result = arena.step({team_id: policies[team_id].act(observations[team_id]) for team_id in arena.agent_ids})
        observations = result.observations
        steps += 1
    assert steps == 20
    assert all(len(state.reports) == 5 for state in arena.states.values())
    assert all(abs(state.balance_gap_wan) <= 1e-6 for state in arena.states.values())
    assert arena.order_log
    assert arena.final_results()["sandbox_version"]
