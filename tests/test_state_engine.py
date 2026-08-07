from pathlib import Path

from goai_data.state_engine import ExperimentalState, ExperimentalStateEngine


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATABASE = PROJECT_ROOT / "data" / "processed" / "v1" / "goai.sqlite"


def initial_state(engine: ExperimentalStateEngine) -> ExperimentalState:
    result = engine.initial_state()
    assert result.status == "success"
    return ExperimentalState.from_dict(result.result)


def test_material_orders_arrive_by_lead_time_and_pay_on_arrival() -> None:
    engine = ExperimentalStateEngine(DATABASE)
    state = initial_state(engine)
    ordered = engine.apply_action(
        state,
        {
            "action_type": "material_order",
            "parameters": {"materials": {"R1": 2, "R3": 1}},
        },
    )
    assert ordered.status == "success"
    state = ExperimentalState.from_dict(ordered.result["state"])
    assert state.cash_wan == 710
    assert len(state.pending_material_orders) == 2

    first = engine.advance_quarter(state)
    assert first.status == "success"
    state = ExperimentalState.from_dict(first.result["state"])
    assert (state.year, state.quarter) == (1, 2)
    assert state.cash_wan == 686
    assert state.material_inventory["R1"] == 2
    assert state.material_inventory["R3"] == 0

    second = engine.advance_quarter(state)
    assert second.status == "success"
    state = ExperimentalState.from_dict(second.result["state"])
    assert (state.year, state.quarter) == (1, 3)
    assert state.cash_wan == 667
    assert state.material_inventory["R3"] == 1
    assert state.pending_material_orders == []


def test_short_loan_repaid_after_four_quarters_under_experimental_policy() -> None:
    engine = ExperimentalStateEngine(DATABASE)
    state = initial_state(engine)
    borrowed = engine.apply_action(
        state,
        {
            "action_type": "short_loan_borrow",
            "parameters": {"principal_wan": 100, "term_quarters": 4},
        },
    )
    assert borrowed.status == "success"
    state = ExperimentalState.from_dict(borrowed.result["state"])
    assert state.cash_wan == 810
    assert state.short_loans[0]["amount_due_wan"] == 105

    for _ in range(4):
        advanced = engine.advance_quarter(state)
        assert advanced.status == "success"
        state = ExperimentalState.from_dict(advanced.result["state"])
    assert (state.year, state.quarter) == (2, 1)
    assert state.cash_wan == 665
    assert state.short_loans[0]["status"] == "repaid_experimental"


def test_quarter_advance_rejects_cash_break_and_keeps_state() -> None:
    engine = ExperimentalStateEngine(DATABASE)
    state = initial_state(engine)
    state.cash_wan = 5
    original_id = state.state_id
    result = engine.advance_quarter(state)
    assert result.status == "rejected"
    assert result.result["unchanged_state"]["state_id"] == original_id
    assert result.result["projected_cash_wan"] == -5
