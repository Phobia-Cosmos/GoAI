"""Traditional business-sandbox defaults for unresolved global rules.

These defaults are executable conventions, not claims about the XA referee
implementation.  XA uses its observed order pool and formal ranking rules;
the traditional profile fills only missing operational semantics.
"""

from __future__ import annotations

import copy
import random
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .global_rules import merge_rule_overrides
from .order_allocation import AllocationDecision, OrderAllocationPolicy


TRADITIONAL_RULES_VERSION = "traditional_sandbox_rules_v1.0"

MARKET_SEQUENCE = ("本地", "区域", "国内", "亚洲", "国际")
PRODUCT_SEQUENCE = ("P1", "P2", "P3", "P4", "P5")


@dataclass(frozen=True)
class TraditionalSettlementPolicy:
    phase_order: tuple[str, ...] = (
        "begin_quarter_finance",
        "material_receipt",
        "production_completion",
        "order_delivery_and_penalty",
        "period_management_and_maintenance",
        "year_end_tax_and_reports",
    )
    bankrupt_after_each_phase: bool = True


@dataclass(frozen=True)
class TraditionalInformationPolicy:
    public_fields: tuple[str, ...] = ("rules", "global_orders", "annual_reports", "public_advertising", "public_order_results", "rankings")
    private_fields: tuple[str, ...] = (
        "cash_wan",
        "owner_equity_wan",
        "material_inventory",
        "product_inventory",
        "private_loans",
        "private_pipeline",
    )
    reveal_stage: str = "year_start_before_advertising"


class TraditionalAuctionPolicy(OrderAllocationPolicy):
    """Highest bid, earliest submission, then stable team ID.

    ``payment_mode='fixed_order_price'`` is the conservative default for
    enterprise sandboxes: bidding affects allocation but does not silently
    change the order's contract price.  A custom profile may use
    ``winner_bid`` when the competition explicitly charges the bid.
    """

    policy_id = "traditional_highest_bid_first_come"

    def __init__(self, *, payment_mode: str = "fixed_order_price") -> None:
        if payment_mode not in {"fixed_order_price", "winner_bid"}:
            raise ValueError("payment_mode must be fixed_order_price or winner_bid")
        self.payment_mode = payment_mode

    def allocate(self, order: Mapping[str, Any], claims: Sequence[Mapping[str, Any]], context: Mapping[str, Any]) -> AllocationDecision:
        if not claims:
            return AllocationDecision(str(order["order_id"]), None, self.policy_id, "no_claims")
        ranked = sorted(
            claims,
            key=lambda claim: (
                -float(claim.get("bid_wan", 0) or 0),
                float(claim.get("submitted_at", float("inf")) or float("inf")),
                str(claim.get("team_id", "")),
            ),
        )
        winner = ranked[0]
        bid = float(winner.get("bid_wan", 0) or 0)
        payment = bid if self.payment_mode == "winner_bid" else float(order.get("total_price_wan", order.get("total_price", 0)) or 0)
        return AllocationDecision(
            str(order["order_id"]),
            winner.get("team_id"),
            self.policy_id,
            "highest_bid_then_first_submission_then_team_id",
            tuple(str(claim.get("team_id")) for claim in claims),
            {"payment_mode": self.payment_mode, "bid_wan": bid, "contract_payment_wan": payment, "tie_rule": "submitted_at_then_team_id"},
        )


def advertising_opportunities(amount_wan: float, *, minimum_wan: float = 10, increment_wan: float = 20) -> int:
    """Traditional interpretation: 10W buys the first selection opportunity."""

    amount = float(amount_wan or 0)
    if amount < minimum_wan:
        return 0
    return 1 + int((amount - minimum_wan) // increment_wan)


def selection_rounds(
    claims: Sequence[Mapping[str, Any]],
    *,
    markets: Sequence[str] = MARKET_SEQUENCE,
    products: Sequence[str] = PRODUCT_SEQUENCE,
) -> list[dict[str, Any]]:
    """Build deterministic selection turns by market then product.

    Each turn consumes at most one order from a claimant.  Claims are expected
    to contain ``market``, ``product``, ``product_advertising``,
    ``market_advertising``, ``total_advertising`` and ``submitted_at``.
    """

    rows: list[dict[str, Any]] = []
    for market_index, market in enumerate(markets):
        for product_index, product in enumerate(products):
            eligible = [claim for claim in claims if claim.get("market") == market and claim.get("product") == product]
            eligible.sort(key=lambda claim: (
                -float(claim.get("product_advertising", 0) or 0),
                -float(claim.get("market_advertising", 0) or 0),
                -float(claim.get("total_advertising", 0) or 0),
                float(claim.get("submitted_at", float("inf")) or float("inf")),
                str(claim.get("team_id", "")),
            ))
            for turn, claim in enumerate(eligible, 1):
                rows.append({
                    "market": market,
                    "product": product,
                    "market_index": market_index,
                    "product_index": product_index,
                    "turn": turn,
                    "team_id": claim.get("team_id"),
                    "claim": dict(claim),
                })
    return rows


class TraditionalXAOrderPolicy(OrderAllocationPolicy):
    """Dispatch selection and auction orders using the document's defaults."""

    policy_id = "traditional_xa_selection_and_auction"

    def __init__(self, *, auction_payment_mode: str = "fixed_order_price") -> None:
        self.selection = TraditionalSelectionPolicy()
        self.auction = TraditionalAuctionPolicy(payment_mode=auction_payment_mode)

    def allocate(self, order: Mapping[str, Any], claims: Sequence[Mapping[str, Any]], context: Mapping[str, Any]) -> AllocationDecision:
        if str(order.get("order_type", "")).lower() in {"竞单", "auction", "bid"}:
            decision = self.auction.allocate(order, claims, context)
            return AllocationDecision(
                decision.order_id,
                decision.winner_team_id,
                self.policy_id,
                decision.reason,
                decision.contenders,
                {**dict(decision.trace), "order_type": "竞单", "bid_fee_wan": 10, "batch_size": 3, "eligibility_checked": True},
            )
        decision = self.selection.allocate(order, claims, context)
        return AllocationDecision(
            decision.order_id,
            decision.winner_team_id,
            self.policy_id,
            decision.reason,
            decision.contenders,
            {**dict(decision.trace), "order_type": "选单", "one_order_per_turn": True},
        )


class TraditionalSelectionPolicy(OrderAllocationPolicy):
    policy_id = "traditional_selection_advertising_priority"

    def allocate(self, order: Mapping[str, Any], claims: Sequence[Mapping[str, Any]], context: Mapping[str, Any]) -> AllocationDecision:
        if not claims:
            return AllocationDecision(str(order["order_id"]), None, self.policy_id, "no_claims")
        market = order.get("market")
        product = order.get("product")
        eligible = [claim for claim in claims if claim.get("market", market) == market and claim.get("product", product) == product]
        if not eligible:
            return AllocationDecision(str(order["order_id"]), None, self.policy_id, "no_qualified_claims")
        ranked = sorted(eligible, key=lambda claim: (
            -float(claim.get("product_advertising", 0) or 0),
            -float(claim.get("market_advertising", 0) or 0),
            -float(claim.get("total_advertising", 0) or 0),
            float(claim.get("sales_rank", float("inf")) or float("inf")),
            float(claim.get("submitted_at", float("inf")) or float("inf")),
            str(claim.get("team_id", "")),
        ))
        winner = ranked[0]
        return AllocationDecision(str(order["order_id"]), winner.get("team_id"), self.policy_id, "advertising_priority", tuple(str(claim.get("team_id")) for claim in eligible), {"market": market, "product": product, "one_order_per_turn": True})


def traditional_visibility_context(period: str, *, public_context: Mapping[str, Any] | None = None) -> dict[str, Any]:
    source = dict(public_context or {})
    return {
        "period": period,
        "information_policy": TRADITIONAL_RULES_VERSION,
        "reveal_stage": TraditionalInformationPolicy().reveal_stage,
        "public": {key: source[key] for key in TraditionalInformationPolicy().public_fields if key in source},
        "private_fields": list(TraditionalInformationPolicy().private_fields),
    }


def generate_traditional_orders(
    templates: Sequence[Mapping[str, Any]],
    *,
    years: Sequence[int] = (2, 3, 4, 5),
    seed: int = 0,
    match_id: str = "simulated",
) -> list[dict[str, Any]]:
    """Generate deterministic fallback orders when no official pool exists.

    XA should pass its observed global pool instead.  Generated rows carry
    ``provenance=simulated`` and are never mixed with observed orders.
    """

    rng = random.Random(seed)
    output: list[dict[str, Any]] = []
    for year in years:
        for index, template in enumerate(templates):
            row = copy.deepcopy(dict(template))
            row.setdefault("market", "本地")
            row.setdefault("product", "P1")
            row.setdefault("quantity", 1)
            row.setdefault("total_price_wan", float(row["quantity"]) * 20)
            row["year"] = int(year)
            row["owner_team_id"] = None
            row["status"] = "未分配"
            row["provenance"] = "simulated"
            row["coverage_scope"] = "traditional_generated_order_pool"
            row["order_id"] = f"{match_id}-Y{year}-{index + 1:04d}-{rng.randrange(1000, 9999)}"
            output.append(row)
    return output


def apply_traditional_defaults(base_rules: Mapping[str, Any], *, payment_mode: str = "fixed_order_price") -> dict[str, Any]:
    defaults = {
        "global_rule_services": {
            "traditional_profile": TRADITIONAL_RULES_VERSION,
            "selection": {"market_sequence": list(MARKET_SEQUENCE), "product_sequence": list(PRODUCT_SEQUENCE), "minimum_advertising_wan": 10, "additional_opportunity_wan": 20, "one_order_per_turn": True},
            "auction": {"policy": "highest_bid_then_first_submission_then_team_id", "payment_mode": payment_mode, "batch_size": 3, "bid_fee_wan": 10, "eligibility": ["market", "product", "iso"]},
            "settlement": {"phase_order": list(TraditionalSettlementPolicy().phase_order), "bankrupt_after_each_phase": True},
            "information": {"reveal_stage": TraditionalInformationPolicy().reveal_stage, "public_fields": list(TraditionalInformationPolicy().public_fields), "private_fields": list(TraditionalInformationPolicy().private_fields)},
            "order_generation": {"observed_pool_preferred": True, "fallback_provenance": "simulated"},
        }
    }
    return merge_rule_overrides(base_rules, defaults)


def validate_traditional_xa(
    *,
    teams: Sequence[Mapping[str, Any]],
    global_orders: Sequence[Mapping[str, Any]],
    results: Mapping[str, Any],
    rules: Mapping[str, Any],
    events: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Check whether traditional defaults are structurally feasible on XA."""

    team_ids = {str(row.get("team_id")) for row in teams}
    order_ids = [str(row.get("order_id")) for row in global_orders]
    assigned = [row for row in global_orders if row.get("owner_team_id") not in (None, "", "-")]
    auction_orders = [row for row in global_orders if str(row.get("order_type", "")) == "竞单"]
    award_events = [row for row in events if row.get("action") == "order_award"]
    checks = {
        "no_year1_orders": all(int(row.get("year", 0)) >= 2 for row in global_orders),
        "unique_order_ids": len(order_ids) == len(set(order_ids)),
        "assigned_owner_exists": all(str(row.get("owner_team_id")) in team_ids for row in assigned),
        "unassigned_pool_preserved": sum(row.get("owner_team_id") in (None, "", "-") for row in global_orders) > 0,
        "ranking_available": bool(results.get("ranking")),
        "bankruptcy_results_available": bool(results.get("bankruptcies")),
        "observed_pool_used": all(row.get("provenance") == "observed" for row in global_orders),
        "auction_batch_size_three_compatible": len(auction_orders) == 0 or len(auction_orders) % 3 == 0,
        "auction_fee_ten_wan_observed": not award_events or all(float(row.get("amount_wan", 0)) == -10.0 for row in award_events),
    }
    return {
        "version": TRADITIONAL_RULES_VERSION,
        "match_id": rules.get("match_id"),
        "feasible_on_observed_xa_structure": all(checks.values()),
        "checks": checks,
        "limitations": [
            "XA claims and bids are not fully recorded, so auction winner mechanics are not outcome-identifiable.",
            "Settlement phase order is tested as an executable convention, not proven as the referee sequence.",
            "Ranking and bankruptcy are validated against XA observed/derived results separately from traditional defaults.",
        ],
        "counts": {"teams": len(team_ids), "orders": len(global_orders), "assigned": len(assigned), "unassigned": len(global_orders) - len(assigned), "auction_orders": len(auction_orders), "auction_award_events": len(award_events)},
    }
