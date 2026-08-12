import json
from pathlib import Path

from goai_data.full_sandbox import (
    FullCompetitionArena,
    FullFinancialDynamics,
    SeededHeuristicPolicy,
    generate_global_orders,
    generate_simulated_rule_pack,
    generate_xa_empirical_global_orders,
    order_is_qualified,
    order_iso_requirements,
)


BASE_RULES = Path("/home/undefined/Disk/datasets/goai/processed/v2/matches/LX_XA/rules.json")
XA_ORDERS = Path(__file__).resolve().parents[1] / "data" / "processed" / "v2" / "matches" / "LX_XA" / "global_orders.jsonl"


def rules(seed: int = 1, team_count: int = 3):
    return generate_simulated_rule_pack(json.loads(BASE_RULES.read_text(encoding="utf-8")), seed=seed, match_id="TEST", team_count=team_count)


def assert_balanced(state) -> None:
    assert abs(state.balance_gap_wan) <= 1e-6


def test_order_iso_normalization_and_qualification_supports_combined_requirements() -> None:
    assert order_iso_requirements("9K") == ("ISO9000",)
    assert order_iso_requirements("14K") == ("ISO14000",)
    assert order_iso_requirements("9K 14K") == ("ISO9000", "ISO14000")
    order = {"market": "国内", "product": "P3", "required_iso": ["ISO9000", "ISO14000"]}
    assert not order_is_qualified(order, markets=["国内"], products=["P3"], iso=["ISO9000"])
    assert order_is_qualified(order, markets=["国内"], products=["P3"], iso=["ISO9000", "ISO14000"])


def test_empirical_xa_orders_preserve_shape_without_terminal_labels() -> None:
    templates = [json.loads(line) for line in XA_ORDERS.read_text(encoding="utf-8").splitlines() if line.strip()]
    generated_rules = rules(9, 27)
    generated_rules["match_id"] = "EMPIRICAL"
    orders = generate_xa_empirical_global_orders(generated_rules, templates, seed=10, price_jitter=0)
    assert len(orders) == len(templates) == 796
    assert {year: sum(row["year"] == year for row in orders) for year in (2, 3, 4, 5)} == {2: 169, 3: 172, 4: 214, 5: 241}
    assert min(row["quantity"] for row in orders) == 1
    assert max(row["quantity"] for row in orders) == 5
    assert all(row["release_period"] == f"Y{row['year']}Q1" for row in orders)
    assert all(row["owner_team_id"] is None and row["status"] == "未分配" for row in orders)
    assert all("final_owner_team_id" not in row and "final_status" not in row and "delivered_period" not in row for row in orders)
    assert [(row["market"], row["product"], row["quantity"], row["required_iso"]) for row in orders] != [
        (row["market"], row["product"], row["quantity"], list(order_iso_requirements(row))) for row in templates
    ]


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


def test_optional_two_stage_quarter_exposes_actual_award_before_settlement() -> None:
    generated = rules(15, 1)
    team_id = generated["participants"]["team_ids"][0]
    order = {
        "match_id": generated["match_id"], "order_id": "TWO-STAGE-1", "year": 1,
        "release_period": "Y1Q1", "release_period_index": 0, "due_period": "Y1Q2",
        "due_period_index": 1, "market": "本地", "product": "P1", "required_iso": [],
        "quantity": 1.0, "total_price_wan": 100.0, "order_type": "选单",
        "owner_team_id": None, "status": "未分配",
    }
    initial = {
        team_id: {
            "markets": ["本地"], "products": ["P1"],
            "product_inventory": {"P1": 1.0}, "product_inventory_value_wan": {"P1": 16.0},
        }
    }
    arena = FullCompetitionArena(FullFinancialDynamics(generated), [team_id], [order], initial_states=initial, post_allocation_phase=True, stop_when_all_bankrupt=False)
    first = arena.reset()[team_id]
    assert first.public_state["decision_phase"] == "operating"
    allocation = arena.step({team_id: {"action_type": "select_order", "parameters": {"order_id": order["order_id"], "market": "本地", "product": "P1", "submitted_at": 0.1}}})
    assert allocation.observations[team_id].period == "Y1Q1"
    assert allocation.observations[team_id].public_state["decision_phase"] == "post_allocation"
    assert allocation.observations[team_id].private_state["assigned_orders"][0]["order_id"] == "TWO-STAGE-1"
    settled = arena.step({team_id: {"actions": [{"action_type": "order_delivery", "parameters": {"order_id": "TWO-STAGE-1"}}, {"action_type": "advertising", "parameters": {"market": "本地", "product_id": "P1", "amount_wan": 1}}]}})
    assert settled.observations[team_id].period == "Y1Q2"
    assert settled.observations[team_id].public_state["decision_phase"] == "operating"
    assert any(event["event_type"] == "order_delivered" for event in settled.infos[team_id]["events"])
    assert settled.infos[team_id]["action_rejections"] == ["订单分配后阶段不允许动作：advertising"]


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
    # The enterprise observes Y1Q2 and gets one final delivery/financing
    # action opportunity before obligations due in Y1Q2 are settled.
    state = engine.advance_quarter(state).state
    assert state.defaulted_orders[0]["order_id"] == "LATE"
    expected = 2 * generated["parameters"]["management_fee_per_quarter_wan"] + round(100 * generated["parameters"]["default_penalty_rate"])
    assert round(before_equity - state.owner_equity_wan, 6) == round(expected, 6)
    assert_balanced(state)


def test_long_loan_interest_and_principal_settle_at_next_year_start_without_factory_depreciation() -> None:
    generated = rules(36, 1)
    engine = FullFinancialDynamics(generated)
    state = engine.initial_state("TEST01")
    state = engine.apply(state, {"action_type": "long_loan_borrow", "parameters": {"principal_wan": 100, "term_years": 1}}).state
    state = engine.apply(state, {"action_type": "buy_workshop", "parameters": {"factory": "小厂房"}}).state
    initial_book = state.factories[0]["book_value_wan"]
    for _ in range(4):
        state = engine.advance_quarter(state).state
    assert state.long_loans
    state = engine.advance_quarter(state).state
    assert not state.long_loans
    assert state.factories[0]["book_value_wan"] == initial_book
    assert len(state.reports) == 1
    assert "interest_expense" not in state.reports[0]["income_statement"]["details"]
    assert state.annual_income["interest_expense"] < 0
    assert_balanced(state)


def test_formal_emergency_product_purchase_uses_three_times_direct_cost() -> None:
    generated = rules(38, 1)
    engine = FullFinancialDynamics(generated)
    state = engine.initial_state("TEST01")
    before_cash = state.cash_wan
    transition = engine.apply(state, {"action_type": "emergency_product_purchase", "parameters": {"product_id": "P1", "quantity": 2}})
    assert transition.status == "success"
    expected_cost = 2 * generated["parameters"]["products"]["P1"]["direct_cost_wan"] * 3
    assert transition.state.cash_wan == before_cash - expected_cost
    assert transition.state.product_inventory["P1"] == 2
    assert_balanced(transition.state)


def test_receivable_discount_supports_formal_term_bucket_amounts() -> None:
    generated = rules(39, 1)
    engine = FullFinancialDynamics(generated)
    state = engine.initial_state("TEST01")
    state.receivables = [
        {"receivable_id": "AR1", "amount_wan": 50, "due_period_index": 4},
        {"receivable_id": "AR2", "amount_wan": 40, "due_period_index": 4},
    ]
    state.owner_equity_wan = state.total_assets_wan - state.debt_wan
    transition = engine.apply(state, {"action_type": "receivable_discount", "parameters": {"term_amounts": {"4": 77}}})
    assert transition.status == "success"
    assert transition.state.cash_wan == state.cash_wan + 70
    assert transition.state.receivables_wan == 13
    assert_balanced(transition.state)


def test_flexible_line_can_switch_product_without_implicit_asset_value_fee() -> None:
    generated = rules(40, 1)
    engine = FullFinancialDynamics(generated)
    state = engine.initial_state("TEST01")
    state.products.append("P2")
    state.production_lines.append({"line_id": "FLEX-1", "line_type": "柔性线", "product_id": "P1", "status": "ready", "ownership": "rented", "cost_wan": 0})
    line_id = "FLEX-1"
    before_cash = state.cash_wan
    converted = engine.apply(state, {"action_type": "convert_product_line", "parameters": {"line_id": line_id, "product_id": "P2"}})
    assert converted.status == "success"
    assert converted.state.cash_wan == before_cash
    converted.state.material_inventory.update({"R2": 1, "R3": 1})
    converted.state.material_inventory_value_wan.update({"R2": 9, "R3": 9})
    converted.state.owner_equity_wan = converted.state.total_assets_wan - converted.state.debt_wan
    produced = engine.apply(converted.state, {"action_type": "production", "parameters": {"product_id": "P2", "quantity": 1}})
    assert produced.status == "success"
    assert_balanced(produced.state)


def test_checkpoint_assisted_reconstruction_preserves_observed_cash_and_equity() -> None:
    generated = rules(43, 1)
    generated["financial_rules"]["defer_bankruptcy_to_historical_checkpoint"] = True
    engine = FullFinancialDynamics(generated)
    arena = FullCompetitionArena(
        engine, ["TEST01"], [], stop_when_all_bankrupt=False,
        quarter_checkpoints={"TEST01": {0: {"period": "Y1Q1", "cash_wan": 700, "owner_equity_wan": 690, "bankrupt": False}}},
    )
    observation = arena.reset()["TEST01"]
    arena.step({"TEST01": {"action_type": "hold"}})
    state = arena.states["TEST01"]
    assert state.cash_wan == 700
    assert state.owner_equity_wan == 690
    assert state.calibration_residual_asset_wan == -10
    assert any(event["event_type"] == "historical_checkpoint_assimilated" for event in state.journal)
    assert_balanced(state)


def test_multi_team_environment_runs_twenty_quarters_with_balanced_accounts() -> None:
    generated = rules(41, 3)
    orders = generate_global_orders(generated, seed=42, orders_per_year=5)
    engine = FullFinancialDynamics(generated)
    arena = FullCompetitionArena(engine, generated["participants"]["team_ids"], orders)
    policies = {team_id: SeededHeuristicPolicy(team_id, 41) for team_id in arena.agent_ids}
    observations = arena.reset()
    assert all("available_orders" not in observation.private_state for observation in observations.values())
    assert all("available_orders" in observation.public_state for observation in observations.values())
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


def test_order_portfolio_fallback_gives_loser_another_order_in_same_turn() -> None:
    generated = rules(51, 2)
    orders = [
        {
            "order_id": order_id,
            "order_type": "选单",
            "market": "本地",
            "product": "P1",
            "quantity": 1,
            "total_price_wan": 80,
            "release_period_index": 0,
            "due_period_index": 6,
            "owner_team_id": None,
            "status": "未分配",
        }
        for order_id in ("O1", "O2", "O3")
    ]
    team_ids = generated["participants"]["team_ids"]
    initial = {team_id: {"products": ["P1"], "markets": ["本地"]} for team_id in team_ids}
    arena = FullCompetitionArena(FullFinancialDynamics(generated), team_ids, orders, initial_states=initial)
    arena.reset()

    def portfolio(fallback: str) -> dict:
        return {
            "action_type": "order_portfolio",
            "parameters": {
                "candidate_slots": [[
                    {"action_type": "select_order", "parameters": {"order_id": "O1"}},
                    {"action_type": "select_order", "parameters": {"order_id": fallback}},
                ]],
                "target_count": 1,
            },
        }

    arena.step({team_ids[0]: portfolio("O2"), team_ids[1]: portfolio("O3")})
    winners = [row["winner_team_id"] for row in arena.order_log if row.get("winner_team_id")]
    assert sorted(winners) == sorted(team_ids)
    assert len({row["order_id"] for row in arena.order_log if row.get("winner_team_id")}) == 2
    assert all(row["trace"]["fallback_queue"] for row in arena.order_log)


def test_year_end_depreciation_immediately_marks_negative_equity_bankruptcy() -> None:
    engine = FullFinancialDynamics(rules(52, 1))
    state = engine.initial_state("TEST01")
    state = engine.apply(state, {"action_type": "rent_workshop", "parameters": {"factory": "小厂房"}}).state
    state = engine.apply(state, {"action_type": "buy_product_line", "parameters": {"line_type": "手工线", "product_id": "P1"}}).state
    state.production_lines[0]["maintenance_wan_per_year"] = 0
    state.production_lines[0]["completed_year"] = 1
    state.owner_equity_wan = 5
    state.calibration_residual_asset_wan += state.owner_equity_wan - (state.total_assets_wan - state.debt_wan)
    assert_balanced(state)
    events = engine._year_end(state, closing_year=2)
    assert any(event["event_type"] == "depreciation" for event in events)
    assert state.bankrupt is True
    assert "negative_equity" in state.bankruptcy_reasons
    assert "year_end_depreciation" in state.bankruptcy_reasons
    assert_balanced(state)
