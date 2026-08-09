import json
from pathlib import Path

from goai_data.full_sandbox import (
    FixedXABaselinePolicy,
    build_fixed_xa_rule_pack,
    generate_global_orders,
    generate_initial_visible_orders,
    generate_xa_shaped_global_orders,
)
from goai_data.recorded_match import run_recorded_competition


BASE_RULES = Path(__file__).resolve().parents[1] / "data" / "processed" / "v2" / "matches" / "LX_XA" / "rules.json"


def base_rules():
    return json.loads(BASE_RULES.read_text(encoding="utf-8"))


def test_fixed_xa_rule_pack_never_randomizes_formal_parameters() -> None:
    base = base_rules()
    first = build_fixed_xa_rule_pack(base, match_id="FIXED", team_count=3, seed=1)
    second = build_fixed_xa_rule_pack(base, match_id="FIXED", team_count=3, seed=999)
    assert first["parameters"] == base["parameters"] == second["parameters"]
    assert first["generation"]["parameter_changes"] == []
    assert first["generation"]["parameters_provenance"] == "observed_formal_XA"
    assert first["financial_rules"]["provenance"] == "candidate_traditional_sandbox_service"


def test_xa_shaped_random_orders_preserve_observed_counts() -> None:
    rules = build_fixed_xa_rule_pack(base_rules(), match_id="FIXED", team_count=3, seed=5)
    orders = generate_xa_shaped_global_orders(rules, seed=6)
    assert len(orders) == 796
    assert {year: sum(row["year"] == year for row in orders) for year in (2, 3, 4, 5)} == {2: 169, 3: 172, 4: 214, 5: 241}
    assert sum(row["order_type"] == "竞单" for row in orders) == 24
    assert all(row["owner_team_id"] is None and row["status"] == "未分配" for row in orders)


def test_recorded_environment_runs_full_loop_and_isolates_private_state() -> None:
    rules = build_fixed_xa_rule_pack(base_rules(), match_id="FIXED", team_count=3, seed=11)
    orders = generate_global_orders(rules, seed=12, orders_per_year=5, years=(2, 3, 4, 5), complexity="large")
    arena, artifacts = run_recorded_competition(
        rules,
        orders,
        seed=11,
        policy_factory=lambda team_id: FixedXABaselinePolicy(team_id, 11, rules=rules),
    )
    assert len(artifacts["trace"]) == 20
    assert len(artifacts["observations"]) == 60
    assert len(artifacts["actions"]) == 60
    assert len(artifacts["feedback"]) == 60
    assert len(artifacts["quarter_states"]) == 63
    assert all(row["agent_id"] in row["observation_id"] for row in artifacts["observations"])
    assert all("states" not in row["public_state"] for row in artifacts["observations"])
    assert all("available_orders" not in row["private_state"] for row in artifacts["observations"])
    assert all(abs(state.balance_gap_wan) <= 1e-5 for state in arena.states.values())
    assert any(not state.bankrupt for state in arena.states.values())


def test_initial_orders_split_public_visibility_and_private_preassignment() -> None:
    rules = build_fixed_xa_rule_pack(base_rules(), match_id="INITIAL", team_count=3, seed=21)
    orders = generate_initial_visible_orders(
        rules,
        seed=22,
        team_ids=rules["participants"]["team_ids"],
        order_count=6,
        preassigned_count=2,
    )
    assert sum(row["owner_team_id"] is None for row in orders) == 4
    assert sum(row["owner_team_id"] is not None for row in orders) == 2
    arena, artifacts = run_recorded_competition(
        rules,
        orders,
        seed=21,
        policy_factory=lambda team_id: FixedXABaselinePolicy(team_id, 21, rules=rules),
    )
    first = [row for row in artifacts["observations"] if row["step"] == 1]
    assert all(len(row["public_state"]["available_order_ids"]) == 4 for row in first)
    assigned_counts = [len(row["private_state"]["assigned_orders"]) for row in first]
    assert sorted(assigned_counts) == [0, 1, 1]
    assert all("available_orders" not in row["private_state"] for row in first)
    assert len(arena.order_log) >= 2


def test_fixed_xa_policy_cohort_is_stable_across_scenario_match_ids() -> None:
    rules = build_fixed_xa_rule_pack(base_rules(), match_id="BASE", team_count=1, seed=30)
    base = FixedXABaselinePolicy("SIM_XA_FIXED07", 30, rules=rules)
    scenario = FixedXABaselinePolicy("SIM_XA_INITIAL07", 30, rules=rules)
    assert base.strategy == scenario.strategy
    assert base.rng.random() == scenario.rng.random()
