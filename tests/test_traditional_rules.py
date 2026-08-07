import json
from pathlib import Path

from goai_data.traditional_rules import (
    TraditionalAuctionPolicy,
    apply_traditional_defaults,
    generate_traditional_orders,
    validate_traditional_xa,
)


ROOT = Path("/home/undefined/Disk/datasets/goai/processed/v2/matches/LX_XA")


def test_traditional_auction_is_deterministic_and_configurable() -> None:
    policy = TraditionalAuctionPolicy(payment_mode="winner_bid")
    decision = policy.allocate(
        {"order_id": "O1", "total_price_wan": 100},
        [
            {"team_id": "B", "bid_wan": 20, "submitted_at": 1},
            {"team_id": "A", "bid_wan": 20, "submitted_at": 1},
        ],
        {},
    )
    assert decision.winner_team_id == "A"
    assert decision.trace["contract_payment_wan"] == 20


def test_traditional_order_generation_never_creates_year1_orders() -> None:
    rows = generate_traditional_orders([{"market": "本地", "product": "P1", "quantity": 2}], seed=1)
    assert rows and min(row["year"] for row in rows) == 2
    assert all(row["owner_team_id"] is None and row["provenance"] == "simulated" for row in rows)


def test_traditional_defaults_are_feasible_on_xa_observed_structure() -> None:
    rules = json.loads((ROOT / "rules.json").read_text(encoding="utf-8"))
    teams = [json.loads(line) for line in (ROOT / "teams.jsonl").read_text(encoding="utf-8").splitlines()]
    orders = [json.loads(line) for line in (ROOT / "global_orders.jsonl").read_text(encoding="utf-8").splitlines()]
    results = json.loads((ROOT / "results.json").read_text(encoding="utf-8"))
    report = validate_traditional_xa(teams=teams, global_orders=orders, results=results, rules=rules)
    assert report["feasible_on_observed_xa_structure"] is True
    assert apply_traditional_defaults(rules)["global_rule_services"]["traditional_profile"]
