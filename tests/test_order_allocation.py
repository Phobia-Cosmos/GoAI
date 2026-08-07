from goai_data.order_allocation import (
    AuctionHighestBidPolicy,
    FirstComeFirstServedPolicy,
    OrderAllocationEngine,
    ReplayObservedAllocationPolicy,
    SeededRandomTieBreakPolicy,
    SelectionPriorityPolicy,
)


ORDER = {"order_id": "X-001", "owner_team_id": "T9", "provenance": "observed"}
CLAIMS = [
    {"team_id": "T1", "market_leader": False, "product_advertising": 20, "market_advertising": 40, "sales_rank": 2, "submitted_at": 2, "bid_wan": 100},
    {"team_id": "T2", "market_leader": True, "product_advertising": 0, "market_advertising": 0, "sales_rank": 5, "submitted_at": 5, "bid_wan": 80},
]


def test_allocation_policies_are_replaceable() -> None:
    assert FirstComeFirstServedPolicy().allocate(ORDER, CLAIMS, {}).winner_team_id == "T1"
    assert AuctionHighestBidPolicy().allocate(ORDER, CLAIMS, {}).winner_team_id == "T1"
    assert SelectionPriorityPolicy().allocate(ORDER, CLAIMS, {}).winner_team_id == "T2"
    assert ReplayObservedAllocationPolicy().allocate(ORDER, CLAIMS, {}).winner_team_id == "T9"


def test_seeded_tie_break_is_reproducible() -> None:
    claims = [{"team_id": "T1"}, {"team_id": "T2"}]
    policy_a = SeededRandomTieBreakPolicy(FirstComeFirstServedPolicy(), seed=42)
    policy_b = SeededRandomTieBreakPolicy(FirstComeFirstServedPolicy(), seed=42)
    assert policy_a.allocate(ORDER, claims, {}).winner_team_id == policy_b.allocate(ORDER, claims, {}).winner_team_id


def test_engine_applies_selected_policy_to_each_order() -> None:
    decisions = OrderAllocationEngine(FirstComeFirstServedPolicy()).allocate([ORDER], {"X-001": CLAIMS})
    assert decisions[0].policy_id == "first_come_first_served"
    assert decisions[0].winner_team_id == "T1"
