import copy
import json
from pathlib import Path

from goai_data.full_sandbox import FullCompetitionArena, FullFinancialDynamics, build_fixed_xa_rule_pack
from goai_data.historical_strategies import build_historical_xa_profiles


ROOT = Path(__file__).resolve().parents[1] / "data" / "processed" / "v2" / "matches" / "LX_XA"


def test_historical_profiles_cover_all_xa_enterprises_and_orders() -> None:
    profiles, orders, actions = build_historical_xa_profiles(ROOT)
    assert len(profiles) == 27
    assert len(orders) == 796
    assert sum(profile.delivered_order_count for profile in profiles.values()) == 544
    assert {profile.strategy_class for profile in profiles.values()} == {
        "leader_growth", "balanced_expansion", "conservative_survivor", "aggressive_failed",
    }
    assert actions


def test_observed_owner_orders_are_released_in_their_competition_year() -> None:
    base = json.loads((ROOT / "rules.json").read_text(encoding="utf-8"))
    rules = build_fixed_xa_rule_pack(base, match_id="RELEASE_TEST", team_count=1)
    rules["participants"] = {"count": 1, "team_ids": ["XA01"]}
    order = {
        "order_id": "O1", "owner_team_id": "XA01", "release_period_index": 4,
        "due_period_index": 7, "market": "本地", "product": "P1", "iso": "-",
        "quantity": 1, "total_price_wan": 30, "order_type": "选单",
    }
    arena = FullCompetitionArena(FullFinancialDynamics(rules), ["XA01"], [order], preassignment_mode="release_schedule", stop_when_all_bankrupt=False)
    arena.reset()
    assert arena.states["XA01"].assigned_orders == []
    hold = {"XA01": {"action_type": "hold"}}
    for _ in range(4):
        arena.step(copy.deepcopy(hold))
    assert [row["order_id"] for row in arena.states["XA01"].assigned_orders] == ["O1"]
    assert arena.order_log[0]["period"] == "Y2Q1"
