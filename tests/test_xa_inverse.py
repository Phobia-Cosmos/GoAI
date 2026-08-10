import json
from pathlib import Path

from goai_data.full_sandbox import FullFinancialDynamics, build_fixed_xa_rule_pack
from goai_data.xa_inverse import build_xa_inverse_artifacts


ROOT = Path(__file__).resolve().parents[1] / "data" / "processed" / "v2" / "matches" / "LX_XA"


def test_xa_inverse_reconstructs_initial_state_loans_and_depreciation() -> None:
    report = build_xa_inverse_artifacts(ROOT)
    assert report["initial_state"]["passed"] is True
    assert report["terminal_outcome_replay"]["exact_outcome_match"] is True
    assert report["terminal_outcome_replay"]["causal_dynamics_replay"] is False
    assert report["initial_state"]["matched_teams"] == 27
    assert report["loan_reconstruction"]["short_loan"]["matched"] == 253
    assert report["loan_reconstruction"]["long_loan"]["matched"] == 53
    assert report["depreciation_reconstruction"]["passed_on_identifiable_histories"] is True
    assert report["depreciation_reconstruction"]["matched"] == 102
    assert report["tax_reconstruction"]["calculation_passed"] is True
    assert report["tax_reconstruction"]["next_year_q1_payment_passed"] is True
    assert report["production_batch_reconstruction"]["passed"] is True
    assert report["reconstructed_counts"]["quarter_states"] == 540
    assert report["reconstructed_counts"]["delivered_order_actions"] == 544


def test_fixed_xa_simulator_starts_without_unearned_qualifications() -> None:
    base = json.loads((ROOT / "rules.json").read_text(encoding="utf-8"))
    fixed = build_fixed_xa_rule_pack(base, team_count=1)
    state = FullFinancialDynamics(fixed).initial_state(fixed["participants"]["team_ids"][0])
    assert state.cash_wan == 675
    assert state.owner_equity_wan == 675
    assert state.markets == []
    assert state.products == []
    assert state.iso == []


def test_market_development_is_paid_at_year_end() -> None:
    base = json.loads((ROOT / "rules.json").read_text(encoding="utf-8"))
    fixed = build_fixed_xa_rule_pack(base, team_count=1)
    engine = FullFinancialDynamics(fixed)
    state = engine.initial_state("XA_TEST")
    started = engine.apply(state, {"action_type": "develop_market", "parameters": {"target": "本地"}})
    assert started.status == "success"
    state = started.state
    assert state.cash_wan == 675
    for _ in range(3):
        state = engine.advance_quarter(state).state
    assert state.cash_wan == 675 - 3 * 14
    state = engine.advance_quarter(state).state
    assert "本地" in state.markets
    assert state.reports[0]["income_statement"]["details"]["market_development_expense"] == -8


def test_formal_line_installments_and_build_year_depreciation() -> None:
    base = json.loads((ROOT / "rules.json").read_text(encoding="utf-8"))
    fixed = build_fixed_xa_rule_pack(base, team_count=1)
    engine = FullFinancialDynamics(fixed)
    state = engine.initial_state("XA_TEST", initial_state={"factories": [{"factory_id": "F1", "name": "大厂房", "ownership": "rented", "capacity": 6, "annual_rent_wan": 51, "next_rent_period_index": 4}]})
    state = engine.apply(state, {"action_type": "buy_product_line", "parameters": {"line_type": "柔性线", "product_id": "P1"}}).state
    assert state.cash_wan == 615
    assert state.pending_lines[0]["book_value_wan"] == 60
    for _ in range(4):
        state = engine.advance_quarter(state).state
    line = state.production_lines[0]
    assert line["book_value_wan"] == 180
    assert line["accumulated_depreciation_wan"] == 0
