from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol, Sequence


ORDER_ALLOCATION_VERSION = "order_allocation_v0.1"


@dataclass(frozen=True)
class AllocationDecision:
    order_id: str
    winner_team_id: str | None
    policy_id: str
    reason: str
    contenders: tuple[str, ...] = ()
    trace: Mapping[str, Any] = field(default_factory=dict)


class OrderAllocationPolicy(Protocol):
    policy_id: str

    def allocate(self, order: Mapping[str, Any], claims: Sequence[Mapping[str, Any]], context: Mapping[str, Any]) -> AllocationDecision: ...


def _claim_value(claim: Mapping[str, Any], key: str, default: float = 0.0) -> float:
    value = claim.get(key, default)
    return float(value) if isinstance(value, (int, float)) else default


class FirstComeFirstServedPolicy:
    policy_id = "first_come_first_served"

    def allocate(self, order: Mapping[str, Any], claims: Sequence[Mapping[str, Any]], context: Mapping[str, Any]) -> AllocationDecision:
        if not claims:
            return AllocationDecision(order["order_id"], None, self.policy_id, "no_claims")
        winner = min(claims, key=lambda claim: (_claim_value(claim, "submitted_at", float("inf")), str(claim.get("team_id"))))
        return AllocationDecision(order["order_id"], winner.get("team_id"), self.policy_id, "earliest_submission", tuple(str(claim.get("team_id")) for claim in claims))


class AuctionHighestBidPolicy:
    policy_id = "auction_highest_bid"

    def allocate(self, order: Mapping[str, Any], claims: Sequence[Mapping[str, Any]], context: Mapping[str, Any]) -> AllocationDecision:
        if not claims:
            return AllocationDecision(order["order_id"], None, self.policy_id, "no_claims")
        winner = max(claims, key=lambda claim: (_claim_value(claim, "bid_wan"), -_claim_value(claim, "submitted_at", float("inf")), str(claim.get("team_id"))))
        return AllocationDecision(order["order_id"], winner.get("team_id"), self.policy_id, "highest_bid", tuple(str(claim.get("team_id")) for claim in claims), {"winning_bid_wan": _claim_value(winner, "bid_wan")})


class SelectionPriorityPolicy:
    """A configurable version of the XA-style priority hierarchy.

    The hierarchy is injected through context so alternate competition rules
    can use different rankings without changing the allocation engine.
    """

    policy_id = "selection_priority"

    def __init__(self, hierarchy: Sequence[str] = ("market_leader", "product_advertising", "market_advertising", "sales_rank", "submitted_at")) -> None:
        self.hierarchy = tuple(hierarchy)

    def allocate(self, order: Mapping[str, Any], claims: Sequence[Mapping[str, Any]], context: Mapping[str, Any]) -> AllocationDecision:
        if not claims:
            return AllocationDecision(order["order_id"], None, self.policy_id, "no_claims")

        def key(claim: Mapping[str, Any]) -> tuple[Any, ...]:
            result = []
            for field in self.hierarchy:
                value = claim.get(field)
                if field in {"market_leader", "product_advertising", "market_advertising"}:
                    result.append(-(1 if value is True else float(value) if isinstance(value, (int, float)) else 0.0))
                elif field == "sales_rank":
                    result.append(float(value) if isinstance(value, (int, float)) else float("inf"))
                elif field == "submitted_at":
                    result.append(float(value) if isinstance(value, (int, float)) else float("inf"))
                else:
                    result.append(value)
            result.append(str(claim.get("team_id")))
            return tuple(result)

        winner = min(claims, key=key)
        return AllocationDecision(order["order_id"], winner.get("team_id"), self.policy_id, "configured_priority_hierarchy", tuple(str(claim.get("team_id")) for claim in claims), {"hierarchy": self.hierarchy})


class SeededRandomTieBreakPolicy:
    policy_id = "seeded_random_tie_break"

    def __init__(self, primary_policy: OrderAllocationPolicy, seed: int = 0) -> None:
        self.primary_policy = primary_policy
        self.seed = seed

    def allocate(self, order: Mapping[str, Any], claims: Sequence[Mapping[str, Any]], context: Mapping[str, Any]) -> AllocationDecision:
        if not claims:
            return AllocationDecision(order["order_id"], None, self.policy_id, "no_claims")
        base = self.primary_policy.allocate(order, claims, context)
        if len(claims) <= 1:
            return AllocationDecision(order["order_id"], base.winner_team_id, self.policy_id, base.reason, base.contenders, {**base.trace, "seed": self.seed, "tie": False})
        # Randomness is only used among exact primary-key ties. The hash makes
        # the result stable across process order and reproducible by seed.
        contenders = list(claims)
        rng_seed = int(hashlib.sha256(f"{self.seed}|{order['order_id']}".encode()).hexdigest()[:16], 16)
        rng = random.Random(rng_seed)
        winner = rng.choice(sorted(contenders, key=lambda claim: str(claim.get("team_id"))))
        return AllocationDecision(order["order_id"], winner.get("team_id"), self.policy_id, "seeded_tie_break", tuple(str(claim.get("team_id")) for claim in contenders), {"seed": self.seed, "primary_policy": getattr(self.primary_policy, "policy_id", type(self.primary_policy).__name__)})


class ReplayObservedAllocationPolicy:
    policy_id = "replay_observed_allocation"

    def allocate(self, order: Mapping[str, Any], claims: Sequence[Mapping[str, Any]], context: Mapping[str, Any]) -> AllocationDecision:
        owner = order.get("owner_team_id")
        return AllocationDecision(order["order_id"], owner, self.policy_id, "owner_from_observed_order_pool", tuple(str(claim.get("team_id")) for claim in claims), {"provenance": order.get("provenance")})


class OrderAllocationEngine:
    def __init__(self, policy: OrderAllocationPolicy) -> None:
        self.policy = policy

    def allocate(self, orders: Sequence[Mapping[str, Any]], claims_by_order: Mapping[str, Sequence[Mapping[str, Any]]], context: Mapping[str, Any] | None = None) -> list[AllocationDecision]:
        context = context or {}
        return [self.policy.allocate(order, claims_by_order.get(str(order["order_id"]), ()), context) for order in orders]
