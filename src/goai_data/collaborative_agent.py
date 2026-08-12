"""Explicit multi-specialist collaboration for one owned XA enterprise.

The specialists do not control separate companies.  They collaborate on one
enterprise decision bundle through a shared blackboard.  Every final bundle is
replayed by the deterministic financial dynamics before it is submitted.
"""

from __future__ import annotations

import copy
import hashlib
from dataclasses import dataclass, fields
from typing import Any, Mapping, Sequence

from .decision_system import AgentObservation
from .full_sandbox import FinancialSandboxState, FullFinancialDynamics, order_is_qualified


COLLABORATIVE_AGENT_VERSION = "owned_enterprise_specialist_committee_v0.8_two_stage"


def _number(value: Any, default: float = 0.0) -> float:
    return float(value) if isinstance(value, (int, float)) else default


def _product_portfolio(agent_id: str, profile: str) -> tuple[str, ...]:
    """Return a stable three-product specialization without future labels."""

    if profile != "leader":
        return ("P1", "P2", "P3")
    bucket = int(hashlib.sha256(f"portfolio|{agent_id}".encode()).hexdigest()[:8], 16) % 2
    return ("P1", "P2", "P4") if bucket == 0 else ("P1", "P3", "P5")


@dataclass(frozen=True)
class SpecialistProposal:
    specialist_id: str
    objective: str
    actions: tuple[Mapping[str, Any], ...]
    dependencies: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()
    evidence: Mapping[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "specialist_id": self.specialist_id,
            "objective": self.objective,
            "actions": [copy.deepcopy(dict(row)) for row in self.actions],
            "dependencies": list(self.dependencies),
            "assumptions": list(self.assumptions),
            "evidence": copy.deepcopy(dict(self.evidence or {})),
        }


class SharedDecisionBlackboard:
    def __init__(self, observation: AgentObservation, rules: Mapping[str, Any], profile: str) -> None:
        self.observation = observation
        self.rules = rules
        self.parameters = dict(rules.get("parameters") or {})
        self.profile = profile
        self.state = observation.private_state
        self.visible_orders = list(observation.public_state.get("available_orders") or [])
        self.outstanding_orders = [row for row in self.state.get("assigned_orders") or [] if row.get("status") not in {"已交", "违约"}]
        self.period_index = observation.period_index
        self.remaining_quarters = max(0, 20 - observation.period_index)

    def demand_by_product(self) -> dict[str, float]:
        result: dict[str, float] = {}
        for order in [*self.outstanding_orders, *self.visible_orders]:
            product = str(order.get("product"))
            direct = _number((self.parameters.get("products") or {}).get(product, {}).get("direct_cost_wan")) * _number(order.get("quantity"))
            result[product] = result.get(product, 0.0) + max(0.0, _number(order.get("total_price_wan")) - direct)
        return result


class TreasurySpecialist:
    specialist_id = "treasury_agent"

    def propose(self, board: SharedDecisionBlackboard, dynamics: FullFinancialDynamics) -> SpecialistProposal:
        state = board.state
        actions: list[Mapping[str, Any]] = []
        cash = _number(state.get("cash_wan"))
        # XA has no first-year order pool.  Debt therefore funds only the
        # minimum pre-order capability package, not an unconstrained capacity
        # build whose interest starts one year before revenue.
        # Long debt is expensive in XA (12% each year).  Use it only for the
        # pre-order construction gap; once contracts exist, shorter 5% debt
        # and receivable collection finance working capital more cheaply.
        profile_principal = 0.0
        if board.period_index == 0 and profile_principal > 0 and not state.get("long_loans"):
            actions.append({"action_type": "long_loan_borrow", "parameters": {"principal_wan": profile_principal, "term_years": 4}})
            cash += profile_principal
        preview = CollaborativeEnterprisePolicy.restore_state(state)
        for action in actions:
            transition = dynamics.apply(preview, action)
            if transition.status == "success":
                preview = transition.state
        if str(board.observation.public_state.get("decision_phase") or "operating") != "post_allocation":
            dynamics._opening_settlement(preview)
        reserve = {"leader": 180.0, "balanced": 220.0, "conservative": 260.0}[board.profile]
        upcoming_obligations = sum(_number(row.get("total_cost_wan")) for row in state.get("pending_material_orders") or [])
        if int(state.get("quarter", 1)) == 4:
            upcoming_obligations += _number(board.parameters.get("management_fee_per_quarter_wan"), 14)
            upcoming_obligations += sum(_number(row.get("maintenance_wan_per_year")) for row in [*(state.get("production_lines") or []), *(state.get("pending_lines") or [])])
            upcoming_obligations += sum(
                _number(row.get("principal_wan")) * _number(row.get("rate"))
                for row in state.get("long_loans") or []
                if int(row.get("next_interest_period_index", 10**9)) <= board.period_index + 1
            )
        ready_line_count = sum(row.get("status") == "ready" for row in state.get("production_lines") or [])
        outstanding_units = sum(_number(row.get("quantity")) for row in board.outstanding_orders)
        maximum_direct_cost = max((_number(row.get("direct_cost_wan")) for row in (board.parameters.get("products") or {}).values()), default=0.0)
        upcoming_obligations += min(outstanding_units, ready_line_count) * maximum_direct_cost * 1.25
        effective_cash = preview.cash_wan - upcoming_obligations
        if effective_cash < reserve:
            receivables = sorted(state.get("receivables") or [], key=lambda row: (int(row.get("due_period_index", 99)), str(row.get("receivable_id"))))
            if receivables:
                actions.append({"action_type": "receivable_discount", "parameters": {"receivable_id": receivables[0].get("receivable_id")}})
                effective_cash += _number(receivables[0].get("amount_wan")) * 0.9
            # A short bridge is permitted only against already-awarded order
            # revenue, receivables and productive assets.  Discounting one
            # receivable and borrowing are allowed together when the complete
            # production/settlement bundle still needs it.
            if effective_cash < reserve:
                gross_backlog = sum(_number(row.get("total_price_wan")) for row in board.outstanding_orders)
                gross_receivables = sum(_number(row.get("amount_wan")) for row in state.get("receivables") or [])
                maturing_short_obligation = sum(
                    _number(row.get("principal_wan")) + _number(row.get("interest_wan"))
                    for row in state.get("short_loans") or []
                    if int(row.get("due_period_index", 10**9)) <= board.period_index
                )
                # XA's frozen short-loan rule has no explicit aggregate
                # collateral ceiling.  Existing short debt therefore must
                # not be subtracted a second time from an invented ceiling:
                # doing so prevented a solvent firm from refinancing a loan
                # at maturity.  We still cap the policy's request by assets
                # and contracted/receivable cash flows so the agent cannot
                # create an unlimited debt spiral.
                financing_capacity = max(
                    maturing_short_obligation,
                    gross_backlog * 0.85
                    + gross_receivables * 0.7
                    + _number(state.get("fixed_assets_wan")) * 0.35,
                )
                need = max(0.0, reserve - effective_cash + 40.0)
                # The frozen XA rule defines a four-quarter short loan and has
                # no terminal forced-liquidation clause.  Do not shorten a
                # Y5 loan merely because its contractual maturity lies after
                # the competition; it remains a liability in terminal equity.
                term = 4
                principal = min(financing_capacity, max(60.0, need))
                if principal >= 60:
                    actions.append({"action_type": "short_loan_borrow", "parameters": {"principal_wan": round(principal, 0), "term_quarters": term}})
        return SpecialistProposal(
            self.specialist_id,
            "fund current-quarter settlement and the agreed operating portfolio",
            tuple(actions),
            evidence={"observed_cash_wan": cash, "post_opening_preview_cash_wan": preview.cash_wan, "upcoming_obligations_wan": upcoming_obligations, "effective_cash_wan": effective_cash, "reserve_wan": reserve},
        )


class CapabilitySpecialist:
    specialist_id = "capability_agent"

    def propose(self, board: SharedDecisionBlackboard, _: FullFinancialDynamics) -> SpecialistProposal:
        state = board.state
        pending = {(str(row.get("kind")), str(row.get("target"))) for row in state.get("pending_development") or []}
        products = list(state.get("products") or [])
        markets = list(state.get("markets") or [])
        iso = list(state.get("iso") or [])
        actions: list[Mapping[str, Any]] = []
        # Qualifications are a portfolio decision made before demand becomes
        # visible.  Waiting for three deliveries before opening the next
        # market made the policy permanently ineligible for most of the XA
        # pool.  Profiles differ in product breadth, while all survivor
        # profiles build the five markets and both ISO certificates early
        # enough for their multi-year lead times.
        # Three products match the observed XA population mean (2.89) and
        # cover the profitable raw-material products without forcing the
        # P4/P5 component-production chain before the first revenue arrives.
        base_products = _product_portfolio(board.observation.agent_id, board.profile)
        base_markets = ["本地", "区域", "国内"]
        realised_orders = len(state.get("assigned_orders") or [])
        if board.period_index >= 5 and realised_orders >= 3:
            base_markets.extend(["亚洲", "国际"])
        for target in base_products:
            if target not in products and ("product", target) not in pending:
                actions.append({"action_type": "develop_product", "parameters": {"target": target}})
        for target in base_markets:
            if target not in markets and ("market", target) not in pending:
                actions.append({"action_type": "develop_market", "parameters": {"target": target}})
        iso_targets = ["ISO9000"]
        if board.period_index >= 5 and realised_orders >= 3:
            iso_targets.append("ISO14000")
        for target in iso_targets:
            if target not in iso and ("iso", target) not in pending:
                actions.append({"action_type": "develop_iso", "parameters": {"target": target}})
        cash = _number(state.get("cash_wan"))
        equity = _number(state.get("owner_equity_wan"))
        delivered = len(state.get("delivered_orders") or [])
        # Growth is unlocked by the complete realised trajectory (cash,
        # equity and deliveries), not by the attractiveness of one order.
        if board.period_index >= 4 and cash >= 320 and equity >= 360 and delivered >= 3:
            growth_targets = [("market", "国内", "develop_market", markets)]
            if board.profile in {"leader", "balanced"}:
                growth_targets.extend([("market", "亚洲", "develop_market", markets), ("iso", "ISO9000", "develop_iso", iso)])
            if board.profile == "leader":
                growth_targets.extend([("market", "国际", "develop_market", markets), ("iso", "ISO14000", "develop_iso", iso)])
            for kind, target, action_type, collection in growth_targets:
                if target not in collection and (kind, target) not in pending:
                    actions.append({"action_type": action_type, "parameters": {"target": target}})
                    break
        return SpecialistProposal(
            self.specialist_id,
            "open profitable product-market combinations before annual order selection",
            tuple(actions[:8]),
            dependencies=("treasury_agent",),
            evidence={"products": products, "markets": markets, "iso": iso, "visible_orders": len(board.visible_orders)},
        )


class CapacitySpecialist:
    specialist_id = "capacity_agent"

    def propose(self, board: SharedDecisionBlackboard, _: FullFinancialDynamics) -> SpecialistProposal:
        state = board.state
        factories = list(state.get("factories") or [])
        lines = [*(state.get("production_lines") or []), *(state.get("pending_lines") or [])]
        actions: list[Mapping[str, Any]] = []
        initial_target = 2 if board.profile == "leader" else 1
        backlog_units = sum(_number(row.get("quantity")) for row in board.outstanding_orders)
        backlog_margin = sum(
            max(0.0, _number(row.get("total_price_wan")) - _number((board.parameters.get("products") or {}).get(str(row.get("product")), {}).get("direct_cost_wan")) * _number(row.get("quantity")))
            for row in board.outstanding_orders
        )
        current_lines = len(lines)
        delivered = len(state.get("delivered_orders") or [])
        backlog_by_product: dict[str, float] = {}
        margin_by_product: dict[str, float] = {}
        line_count_by_product: dict[str, int] = {}
        pending_by_product: dict[str, float] = {}
        for order in board.outstanding_orders:
            product = str(order.get("product"))
            quantity = _number(order.get("quantity"))
            backlog_by_product[product] = backlog_by_product.get(product, 0.0) + quantity
            direct = _number((board.parameters.get("products") or {}).get(product, {}).get("direct_cost_wan")) * quantity
            margin_by_product[product] = margin_by_product.get(product, 0.0) + max(0.0, _number(order.get("total_price_wan")) - direct)
        for line in lines:
            product = str(line.get("product_id") or "")
            line_count_by_product[product] = line_count_by_product.get(product, 0) + 1
        for job in state.get("pending_production") or []:
            product = str(job.get("product_id") or "")
            pending_by_product[product] = pending_by_product.get(product, 0.0) + _number(job.get("quantity"))
        product_expansion_need: dict[str, int] = {}
        for product, units in backlog_by_product.items():
            net_units = max(
                0.0,
                units
                - _number((state.get("product_inventory") or {}).get(product))
                - pending_by_product.get(product, 0.0),
            )
            covered_units = line_count_by_product.get(product, 0) * 2
            uncovered_units = max(0.0, net_units - covered_units)
            candidate_lines = min(3, int((uncovered_units + 3) // 4)) if uncovered_units > 0 else 0
            # One automatic line's conservative lifecycle burden includes
            # maintenance, at least one depreciation charge and a financing
            # buffer.  Do not expand one product merely because unrelated
            # products make the total backlog look profitable.
            if candidate_lines and margin_by_product.get(product, 0.0) >= candidate_lines * 80.0:
                product_expansion_need[product] = candidate_lines
        can_expand = (
            board.period_index >= 5
            and _number(state.get("cash_wan")) >= {"leader": 180.0, "balanced": 200.0, "conservative": 220.0}[board.profile]
            and _number(state.get("owner_equity_wan")) >= 100.0
            and bool(product_expansion_need)
        )
        expansion_count = 0
        if can_expand:
            expansion_count = min(3, sum(product_expansion_need.values()))
        desired = initial_target if board.period_index < 4 else current_lines + expansion_count
        desired = min(desired, {"leader": 12, "balanced": 10, "conservative": 8}[board.profile])
        capacity = sum(int(row.get("capacity", 0)) for row in factories)
        purchased_target = {"leader": 3, "balanced": 2, "conservative": 2}[board.profile]
        planned_purchases = sum(row.get("ownership") == "purchased" for row in factories)

        def add_small_factory() -> None:
            nonlocal capacity, planned_purchases
            # Preserve roughly the real XA survivor mix: own the stable base
            # capacity so its value remains on the balance sheet, then lease
            # burst capacity instead of locking every expansion into cash.
            if planned_purchases < purchased_target:
                actions.append({"action_type": "buy_workshop", "parameters": {"factory": "小厂房"}})
                planned_purchases += 1
            else:
                actions.append({"action_type": "rent_workshop", "parameters": {"factory": "小厂房"}})
            capacity += 1

        if capacity < desired:
            if not factories:
                add_small_factory()
            while capacity < desired:
                add_small_factory()
        additions = min(max(0, desired - len(lines)), max(0, capacity - len(lines)))
        additions = min(additions, initial_target if board.period_index == 0 else expansion_count)
        existing_products = set(state.get("products") or []) | {str(row.get("target")) for row in state.get("pending_development") or [] if row.get("kind") == "product"}
        # Capacity proposals are produced in parallel with capability
        # proposals.  Build against the jointly agreed initial P1/P2/P3
        # portfolio instead of looking only at yesterday's completed
        # qualifications (which made every initial line P1/P2-only).
        portfolio = _product_portfolio(board.observation.agent_id, board.profile)
        preferred = [product for product in portfolio if product in existing_products or board.period_index == 0]
        if not preferred:
            preferred = ["P1", "P2", "P3"]
        if board.outstanding_orders:
            preferred.sort(key=lambda product: (-product_expansion_need.get(product, 0), -(backlog_by_product.get(product, 0.0) / max(1, line_count_by_product.get(product, 0))), product))
        product_offset = int(hashlib.sha256(board.observation.agent_id.encode()).hexdigest()[:8], 16) % len(preferred)
        planned_product_expansions = dict(product_expansion_need)
        for index in range(additions):
            if board.period_index == 0 and "P4" in portfolio:
                product = "P2"
            elif board.period_index == 0 and "P5" in portfolio:
                product = "P3"
            elif board.outstanding_orders and planned_product_expansions:
                product = max(planned_product_expansions, key=lambda value: (planned_product_expansions[value], backlog_by_product.get(value, 0.0), value))
                planned_product_expansions[product] -= 1
                if planned_product_expansions[product] <= 0:
                    del planned_product_expansions[product]
            else:
                product = preferred[index % len(preferred)] if board.outstanding_orders else preferred[(product_offset + len(lines) + index) % len(preferred)]
            # Automatic starter lines complete during the order-free first
            # year.  Later expansions keep the one-quarter production cycle;
            # a uniform manual-line experiment could not meet XA's short
            # delivery windows even though its initial capital cost was lower.
            line_type = "自动线"
            actions.append({"action_type": "buy_product_line", "parameters": {"line_type": line_type, "product_id": product}})
        return SpecialistProposal(
            self.specialist_id,
            "size product-specific capacity from the complete order backlog rather than one isolated order",
            tuple(actions),
            dependencies=("treasury_agent", "capability_agent"),
            evidence={"current_lines": len(lines), "current_factory_capacity": capacity, "desired_lines": desired, "backlog_units": backlog_units, "backlog_margin_wan": backlog_margin, "product_expansion_need": product_expansion_need, "backlog_by_product": backlog_by_product},
        )


class FulfillmentSpecialist:
    specialist_id = "fulfillment_agent"

    def propose(self, board: SharedDecisionBlackboard, _: FullFinancialDynamics) -> SpecialistProposal:
        state = board.state
        outstanding = sorted(board.outstanding_orders, key=lambda row: (int(row.get("due_period_index", 99)), str(row.get("order_id"))))
        inventory = {str(key): _number(value) for key, value in (state.get("product_inventory") or {}).items()}
        inventory_value = {str(key): _number(value) for key, value in (state.get("product_inventory_value_wan") or {}).items()}
        materials = {str(key): _number(value) for key, value in (state.get("material_inventory") or {}).items()}
        # The arena executes financing and then quarter-opening settlement
        # before operating actions.  Materials due now are therefore usable
        # by this bundle even though the observation still lists them as
        # pending.  Ignoring them caused a duplicate emergency purchase after
        # the same material had already arrived and been paid for.
        for material_order in state.get("pending_material_orders") or []:
            if int(material_order.get("arrival_period_index", 10**9)) <= board.period_index:
                material_id = str(material_order.get("material_id"))
                materials[material_id] = materials.get(material_id, 0.0) + _number(material_order.get("quantity"))
        pending: dict[str, float] = {}
        for job in state.get("pending_production") or []:
            product = str(job.get("product_id"))
            quantity = _number(job.get("quantity"))
            if int(job.get("completion_period_index", 10**9)) <= board.period_index:
                # The arena performs opening settlement after financing and
                # before operating actions.  Products completing now are
                # therefore available to an order_delivery action in this
                # same bundle, just like materials arriving at opening.
                inventory[product] = inventory.get(product, 0.0) + quantity
            else:
                pending[product] = pending.get(product, 0.0) + quantity
        required: dict[str, float] = {}
        for order in outstanding:
            product = str(order.get("product"))
            required[product] = required.get(product, 0.0) + _number(order.get("quantity"))
        # Expand final-product demand into component demand.  P4 consumes P2
        # and P5 consumes P3 in the frozen XA BOM; without this expansion the
        # upstream line stayed idle until the downstream production action was
        # rejected for missing components.
        for product, quantity in list(required.items()):
            for component, units in ((board.parameters.get("products") or {}).get(product, {}).get("bom") or {}).items():
                component = str(component)
                if not component.startswith("R"):
                    required[component] = required.get(component, 0.0) + quantity * _number(units)
        actions: list[Mapping[str, Any]] = []
        planned_delivery_ids: set[str] = set()
        for order in outstanding:
            product, quantity = str(order.get("product")), _number(order.get("quantity"))
            if inventory.get(product, 0.0) >= quantity:
                actions.append({"action_type": "order_delivery", "parameters": {"order_id": order.get("order_id")}})
                planned_delivery_ids.add(str(order.get("order_id")))
                unit_book_value = inventory_value.get(product, 0.0) / inventory.get(product, 1.0)
                inventory_value[product] = max(0.0, inventory_value.get(product, 0.0) - unit_book_value * quantity)
                inventory[product] -= quantity
        emergency_multiplier = _number(board.parameters.get("emergency_product_price_multiplier"), 3.0)
        default_penalty_rate = _number(board.parameters.get("default_penalty_rate"), 0.2)
        for order in outstanding:
            order_id = str(order.get("order_id"))
            if order_id in planned_delivery_ids or int(order.get("due_period_index", 99)) > board.period_index:
                continue
            product, quantity = str(order.get("product")), _number(order.get("quantity"))
            on_hand = inventory.get(product, 0.0)
            existing_units = min(quantity, on_hand)
            existing_book_value = (inventory_value.get(product, 0.0) / on_hand * existing_units) if on_hand > 0 else 0.0
            missing = max(0.0, quantity - on_hand)
            product_rule = (board.parameters.get("products") or {}).get(product) or {}
            emergency_cost = missing * _number(product_rule.get("direct_cost_wan")) * emergency_multiplier
            # Buy a missing terminal lot only when completing it is no worse
            # for equity than accepting the contractual default penalty.
            # The joint risk replay still rejects the action if cash cannot
            # actually fund it after opening settlement.
            avoided_penalty = _number(order.get("total_price_wan")) * default_penalty_rate
            incremental_equity = _number(order.get("total_price_wan")) + avoided_penalty - existing_book_value - emergency_cost
            if missing > 0 and incremental_equity >= 0:
                actions.append({"action_type": "emergency_product_purchase", "parameters": {"product_id": product, "quantity": missing}})
                inventory[product] = inventory.get(product, 0.0) + missing
                inventory_value[product] = inventory_value.get(product, 0.0) + emergency_cost
            if inventory.get(product, 0.0) >= quantity:
                actions.append({"action_type": "order_delivery", "parameters": {"order_id": order.get("order_id")}})
                planned_delivery_ids.add(order_id)
                unit_book_value = inventory_value.get(product, 0.0) / inventory.get(product, 1.0)
                inventory_value[product] = max(0.0, inventory_value.get(product, 0.0) - unit_book_value * quantity)
                inventory[product] -= quantity
                required[product] = max(0.0, required.get(product, 0.0) - quantity)
        ready_lines = [copy.deepcopy(row) for row in state.get("production_lines") or [] if row.get("status") == "ready"]
        for line in ready_lines:
            products = [
                product for product, quantity in sorted(required.items(), key=lambda row: (-row[1], row[0]))
                if quantity - inventory.get(product, 0.0) - pending.get(product, 0.0) > 0
                and product in state.get("products", [])
                and (line.get("line_type") == "柔性线" or str(line.get("product_id")) == product)
            ]
            if not products:
                continue
            product = products[0]
            product_rule = (board.parameters.get("products") or {}).get(product) or {}
            can_produce = True
            for component, units in (product_rule.get("bom") or {}).items():
                component = str(component)
                if component.startswith("R"):
                    missing = max(0.0, _number(units) - materials.get(component, 0.0))
                    if missing:
                        actions.append({"action_type": "emergency_purchase", "parameters": {"material_id": component, "quantity": missing}})
                        materials[component] = materials.get(component, 0.0) + missing
                    materials[component] -= _number(units)
                elif inventory.get(component, 0.0) >= _number(units):
                    inventory[component] -= _number(units)
                else:
                    can_produce = False
                    break
            if not can_produce:
                continue
            actions.append({"action_type": "production", "parameters": {"product_id": product, "quantity": 1, "line_type": line.get("line_type")}})
            pending[product] = pending.get(product, 0.0) + 1
        # Maintain a rolling two-batch material cover.  After orders are won,
        # this is capped by the outstanding production need; immediately
        # before an annual order pool it pre-positions a starter stock.  The
        # order is paid only when it arrives, so Treasury sees and finances
        # that opening obligation in the next decision bundle.
        if board.period_index < 19:
            forecast_materials: dict[str, float] = {}
            remaining_by_product = {
                product: max(0.0, quantity - inventory.get(product, 0.0) - pending.get(product, 0.0))
                for product, quantity in required.items()
            }
            line_counts: dict[str, int] = {}
            for line in [*(state.get("production_lines") or []), *(state.get("pending_lines") or [])]:
                product = str(line.get("product_id") or "")
                line_counts[product] = line_counts.get(product, 0) + 1
            for product, line_count in line_counts.items():
                product_rule = (board.parameters.get("products") or {}).get(product) or {}
                starter_need = line_count * 2 if state.get("quarter") == 4 and not required else 0.0
                planned_batches = min(max(starter_need, remaining_by_product.get(product, 0.0)), line_count * 2)
                for component, units in (product_rule.get("bom") or {}).items():
                    if str(component).startswith("R"):
                        forecast_materials[str(component)] = forecast_materials.get(str(component), 0.0) + _number(units) * planned_batches
            for pending_order in state.get("pending_material_orders") or []:
                if int(pending_order.get("arrival_period_index", 10**9)) > board.period_index:
                    material_id = str(pending_order.get("material_id"))
                    forecast_materials[material_id] = max(0.0, forecast_materials.get(material_id, 0.0) - _number(pending_order.get("quantity")))
            for material_id, available in materials.items():
                forecast_materials[material_id] = max(0.0, forecast_materials.get(material_id, 0.0) - available)
            forecast_materials = {key: round(value, 6) for key, value in forecast_materials.items() if value > 1e-9}
            if forecast_materials:
                actions.append({"action_type": "material_order", "parameters": {"materials": forecast_materials}})
        return SpecialistProposal(
            self.specialist_id,
            "produce the whole earliest-due backlog and deliver complete orders",
            tuple(actions),
            dependencies=("treasury_agent", "capacity_agent"),
            evidence={"outstanding_orders": len(outstanding), "required_units_by_product": required, "ready_lines": len(ready_lines)},
        )


class OrderPortfolioSpecialist:
    specialist_id = "order_portfolio_agent"

    def __init__(self, seed: int, agent_id: str, *, allow_prospective_new_cell: bool = False) -> None:
        self.seed = seed
        self.agent_id = agent_id
        self.allow_prospective_new_cell = allow_prospective_new_cell

    def _fraction(self, order_id: Any) -> float:
        digest = hashlib.sha256(f"{self.seed}|{self.agent_id}|{order_id}".encode()).hexdigest()
        return int(digest[:12], 16) / float(0xFFFFFFFFFFFF)

    def propose(self, board: SharedDecisionBlackboard, state: Mapping[str, Any]) -> SpecialistProposal:
        parameters = board.parameters
        outstanding = board.outstanding_orders
        committed: dict[str, float] = {}
        for order in outstanding:
            product = str(order.get("product"))
            committed[product] = committed.get(product, 0.0) + _number(order.get("quantity"))
        candidates: list[tuple[float, float, float, Mapping[str, Any]]] = []
        maximum_lines = {"leader": 12, "balanced": 10, "conservative": 8}[board.profile]
        qualified_products = [product for product in _product_portfolio(board.observation.agent_id, board.profile) if product in state.get("products", [])]
        target_lines_by_product: dict[str, int] = {}
        if qualified_products:
            for index, product in enumerate(qualified_products):
                target_lines_by_product[product] = maximum_lines // len(qualified_products) + (1 if index < maximum_lines % len(qualified_products) else 0)
        line_cells = {
            str(line.get("product_id"))
            for line in [*(state.get("production_lines") or []), *(state.get("pending_lines") or [])]
            if line.get("product_id")
        }
        # Permit exactly one new product cell in the rolling portfolio.  The
        # earlier strict gate required an existing line before an enterprise
        # could win its first order for that product, leaving qualified public
        # orders untouched.  Conversely, assuming a new line for every product
        # overcommitted cash and capacity.  Choose one cell from current public
        # demand; if it wins, the Capacity specialist observes that realised
        # backlog next quarter and must actually install the line.
        new_cell_value: dict[str, float] = {}
        for visible in board.visible_orders:
            product = str(visible.get("product"))
            # A first new cell is a low-risk P1/P2/P3 expansion.  P4/P5
            # require a component-production chain; selecting them without an
            # already-operating chain creates attractive-looking revenue but
            # weak terminal equity and avoidable defaults.
            if product in line_cells or product not in qualified_products or product not in {"P1", "P2", "P3"}:
                continue
            product_rule = (parameters.get("products") or {}).get(product) or {}
            direct = _number(product_rule.get("direct_cost_wan")) * _number(visible.get("quantity"))
            new_cell_value[product] = new_cell_value.get(product, 0.0) + max(0.0, _number(visible.get("total_price_wan")) - direct)
        expansion_cash_floor = {"leader": 400.0, "balanced": 350.0, "conservative": 300.0}[board.profile]
        expansion_equity_floor = {"leader": 300.0, "balanced": 260.0, "conservative": 240.0}[board.profile]
        planned_new_cell = (
            max(new_cell_value, key=lambda product: (new_cell_value[product], product), default=None)
            if self.allow_prospective_new_cell
            and board.profile != "leader"
            and _number(state.get("cash_wan")) >= expansion_cash_floor
            and _number(state.get("owner_equity_wan")) >= expansion_equity_floor
            else None
        )
        rejection_reasons: dict[str, int] = {}

        def reject(reason: str) -> None:
            rejection_reasons[reason] = rejection_reasons.get(reason, 0) + 1

        for order in board.visible_orders:
            if not order_is_qualified(order, markets=state.get("markets") or [], products=state.get("products") or [], iso=state.get("iso") or []):
                reject("qualification")
                continue
            product = str(order.get("product"))
            quantity = _number(order.get("quantity"))
            # Capacity after Y5Q4 cannot improve the terminal score.  Orders
            # whose contractual due date falls beyond the 20-quarter match
            # must still fit inside the remaining competition horizon.
            gap = min(int(order.get("due_period_index", 99)), 20) - board.period_index
            product_lines = [line for line in [*(state.get("production_lines") or []), *(state.get("pending_lines") or [])] if str(line.get("product_id")) == product]
            # Sum whole batches line by line.  Using the fastest cycle for a
            # mixed automatic/manual fleet overstated every manual line and
            # created orders that could not be completed.
            capacity = 0
            for line in product_lines:
                production_quarters = max(1, int((parameters.get("production_lines") or {}).get(str(line.get("line_type")), {}).get("production_quarters", 1)))
                installation_delay = max(0, int(line.get("completion_period_index", board.period_index)) - board.period_index) if line.get("status") == "installing" else 0
                capacity += max(0, (gap - 1 - installation_delay) // production_quarters)
            # Finished goods are executable capacity, not sunk history.  The
            # previous planner ignored warehouse stock and rejected orders
            # even when the complete lot was already available.  Outstanding
            # commitments are compared below against inventory plus future
            # production as one shared capacity budget.
            on_hand = max(0.0, _number((state.get("product_inventory") or {}).get(product)))
            capacity += on_hand
            # A human order plan may reserve capacity that will be installed
            # after winning the annual pool.  Add only the profile's bounded
            # future manual-line slots, with one quarter reserved for the
            # post-award build decision and two quarters per batch.  The
            # Capacity specialist must then actually finance and install the
            # lines; otherwise normal due-date/default transitions still
            # apply.
            # Reserve future expansion only behind an existing product cell.
            # Assuming a brand-new line for every qualified product let one
            # enterprise win P1/P2/P3 simultaneously, even though the next
            # quarter's risk review could finance only one of those cells.
            two_stage = bool(board.observation.public_state.get("post_allocation_phase_enabled"))
            prospective_limit = (
                {"leader": 4, "balanced": 3, "conservative": 2}[board.profile]
                if two_stage
                else (2 if board.profile in {"leader", "balanced"} else 1)
            )
            component = {"P4": "P2", "P5": "P3"}.get(product)
            component_cell_exists = bool(
                component
                and any(str(line.get("product_id")) == component for line in [*(state.get("production_lines") or []), *(state.get("pending_lines") or [])])
            )
            prospective_lines = min(prospective_limit, max(0, target_lines_by_product.get(product, 0) - len(product_lines))) if product_lines or component_cell_exists else 0
            if not product_lines and not component_cell_exists and product == planned_new_cell:
                prospective_lines = 1
            capacity += prospective_lines * max(0, (gap - 2) // 2)
            if committed.get(product, 0.0) + quantity > capacity:
                reject("existing_commitment_exceeds_candidate_capacity")
                continue
            product_rule = (parameters.get("products") or {}).get(product) or {}
            unit_cost = _number(product_rule.get("process_wan")) + sum(_number((parameters.get("materials") or {}).get(str(component), {}).get("price_wan")) * 2 * _number(units) for component, units in (product_rule.get("bom") or {}).items() if str(component).startswith("R"))
            conservative_margin = _number(order.get("total_price_wan")) - unit_cost * quantity
            if conservative_margin <= 15:
                reject("insufficient_conservative_margin")
                continue
            # Prefer profitable small lots that can be completed as a whole.
            # The random term diversifies opponents but must not dominate
            # delivery feasibility as it did in v0.1.
            score = conservative_margin / max(1.0, quantity) * 8 + self._fraction(order.get("order_id")) * 250 - quantity * 8 + gap * 30
            candidates.append((score, conservative_margin, float(capacity), order))
        candidates.sort(key=lambda row: (-row[0], -row[1], _number(row[3].get("quantity")), str(row[3].get("order_id"))))
        annual_budget = {"leader": 12, "balanced": 10, "conservative": 8}[board.profile]
        budget = annual_budget if board.period_index % 4 == 0 else 3
        remaining_target = {"leader": 42, "balanced": 34, "conservative": 28}[board.profile] - len(state.get("assigned_orders") or [])
        selected: list[Mapping[str, Any]] = []
        planned_commitment = dict(committed)
        selected_margin = 0.0
        for _, margin, feasible_capacity, order in candidates:
            if len(selected) >= max(0, min(budget, remaining_target)):
                reject("portfolio_budget_or_lifecycle_target")
                break
            product = str(order.get("product"))
            quantity = _number(order.get("quantity"))
            if planned_commitment.get(product, 0.0) + quantity > feasible_capacity:
                reject("joint_portfolio_capacity")
                continue
            selected.append(order)
            planned_commitment[product] = planned_commitment.get(product, 0.0) + quantity
            selected_margin += margin
        advertising = state.get("advertising") or {}
        actions: list[Mapping[str, Any]] = []
        advertising_plan: dict[str, float] = {str(key): _number(value) for key, value in advertising.items()}
        advertising_amount = {"leader": 3.0, "balanced": 2.0, "conservative": 1.0}[board.profile]
        for key in sorted({f"{order.get('market')}:{order.get('product')}" for order in selected if str(order.get("order_type")) != "竞单"}):
            if advertising_plan.get(key, 0.0) <= 0:
                market, product = key.split(":", 1)
                actions.append({"action_type": "advertising", "parameters": {"market": market, "product_id": product, "amount_wan": advertising_amount}})
                advertising_plan[key] = advertising_amount

        def claim_for(order: Mapping[str, Any]) -> dict[str, Any]:
            market, product = str(order.get("market")), str(order.get("product"))
            common = {"order_id": order.get("order_id"), "market": market, "product": product, "submitted_at": self._fraction(order.get("order_id"))}
            if str(order.get("order_type")) == "竞单":
                return {"action_type": "auction_bid", "parameters": {**common, "bid_wan": round(_number(order.get("total_price_wan")) * 0.98, 2)}}
            return {"action_type": "select_order", "parameters": {**common, "product_advertising": _number(advertising_plan.get(f"{market}:{product}")), "market_advertising": sum(_number(value) for key, value in advertising_plan.items() if key.startswith(f"{market}:")), "total_advertising": sum(_number(value) for value in advertising_plan.values())}}

        selected_ids = {str(order.get("order_id")) for order in selected}
        candidate_slots: list[list[dict[str, Any]]] = []
        for primary in selected:
            primary_product = str(primary.get("product"))
            primary_quantity = _number(primary.get("quantity"))
            primary_due = int(primary.get("due_period_index", 99))
            alternatives = []
            for _, _, feasible_capacity, alternative in candidates:
                if str(alternative.get("order_id")) in selected_ids:
                    continue
                # Losing a selection turn releases the primary order's unit
                # reservation.  A fallback no larger than that primary keeps
                # aggregate units bounded; product-specific imbalance is then
                # handed to the Capacity specialist, which builds against the
                # realised (not hypothetical) awarded portfolio next quarter.
                if _number(alternative.get("quantity")) > primary_quantity:
                    continue
                alternative_product = str(alternative.get("product"))
                alternative_quantity = _number(alternative.get("quantity"))
                if alternative_product != primary_product:
                    # A fallback must reuse the exact product-specific
                    # reservation of its primary slot.  Treating the same
                    # warehouse unit as backing several cross-product slots
                    # over-awarded orders after conflicts were resolved.
                    continue
                # Reusing the primary product reservation is safe only when
                # the fallback is no larger and no earlier.
                if int(alternative.get("due_period_index", 99)) < primary_due:
                    continue
                alternatives.append(alternative)
                if len(alternatives) >= 64:
                    break
            candidate_slots.append([claim_for(primary), *(claim_for(order) for order in alternatives)])
        if candidate_slots:
            actions.append({"action_type": "order_portfolio", "parameters": {"candidate_slots": candidate_slots, "target_count": len(candidate_slots)}})
        return SpecialistProposal(
            self.specialist_id,
            "select a joint profitable order portfolio within shared product capacity",
            tuple(actions),
            dependencies=("capability_agent", "capacity_agent", "risk_critic_agent"),
            assumptions=("future opponent choices remain unknown",),
            evidence={"visible_orders": len(board.visible_orders), "qualified_candidates": len(candidates), "selected_orders": len(selected), "fallback_candidates": sum(max(0, len(slot) - 1) for slot in candidate_slots), "conservative_margin_wan": selected_margin, "planned_units_by_product": planned_commitment, "rejection_reasons": rejection_reasons},
        )


class RiskCriticSpecialist:
    specialist_id = "risk_critic_agent"
    # Production and the materials required by an already-awarded order are
    # fulfilment obligations, not discretionary growth spending.  Pruning
    # them to protect a static cash/equity floor turns a profitable backlog
    # into defaults and makes the floor worse one quarter later.  The critic
    # may still remove future-facing development, capacity and advertising.
    DISCRETIONARY = {"develop_product", "develop_market", "develop_iso", "rent_workshop", "buy_workshop", "buy_product_line", "advertising"}

    def review(
        self,
        board: SharedDecisionBlackboard,
        dynamics: FullFinancialDynamics,
        finance_actions: Sequence[Mapping[str, Any]],
        operating_actions: Sequence[Mapping[str, Any]],
    ) -> tuple[FinancialSandboxState, list[Mapping[str, Any]], list[dict[str, Any]]]:
        finance = list(finance_actions)
        candidates = list(operating_actions)
        removals: list[dict[str, Any]] = []
        reserve = {"leader": 140.0, "balanced": 180.0, "conservative": 220.0}[board.profile]
        while True:
            state = CollaborativeEnterprisePolicy.restore_state(board.state)
            accepted: list[Mapping[str, Any]] = []
            failed = False
            for action in finance:
                transition = dynamics.apply(state, action)
                if transition.status != "success" or transition.state.bankrupt:
                    failed = True
                    break
                state = transition.state
                accepted.append(action)
            if not failed:
                dynamics._opening_settlement(state)
                failed = state.bankrupt
            if not failed:
                for action in candidates:
                    transition = dynamics.apply(state, action)
                    if transition.status != "success" or transition.state.bankrupt:
                        failed = True
                        break
                    state = transition.state
                    accepted.append(action)
            annual_fixed = sum(_number(row.get("maintenance_wan_per_year")) for row in [*state.production_lines, *state.pending_lines])
            annual_fixed += sum(_number(row.get("annual_rent_wan")) for row in state.factories if row.get("ownership") == "rented")
            annual_fixed += sum(_number(row.get("principal_wan")) * _number(row.get("rate")) for row in state.long_loans)
            annual_fixed += sum(
                _number(row.get("installment_wan"))
                for row in state.pending_development
                if row.get("payment_timing") == "year_end"
            )
            future_material_cash = sum(_number(row.get("total_cost_wan")) for row in state.pending_material_orders)
            remaining_year_fraction = max(0.25, (4 - state.quarter + 1) / 4)
            safe_cash = state.cash_wan - future_material_cash - annual_fixed * remaining_year_fraction - _number(board.parameters.get("management_fee_per_quarter_wan"), 14) * max(1, 4 - state.quarter)
            depreciation_due = sum(
                min(
                    max(0.0, _number(asset.get("book_value_wan")) - _number(asset.get("residual_value_wan"))),
                    _number(asset.get("depreciation_fee_wan")),
                )
                for asset in state.production_lines
                if asset.get("ownership") == "purchased" and state.year > int(asset.get("completed_year", state.year))
            )
            projected_equity_after_fixed = state.owner_equity_wan - annual_fixed * remaining_year_fraction - _number(board.parameters.get("management_fee_per_quarter_wan"), 14) * max(1, 4 - state.quarter) - depreciation_due
            backlog_margin = sum(
                max(
                    0.0,
                    _number(order.get("total_price_wan"))
                    - _number((board.parameters.get("products") or {}).get(str(order.get("product")), {}).get("direct_cost_wan")) * _number(order.get("quantity")),
                )
                for order in board.outstanding_orders
            )
            secured_margin = backlog_margin * 0.25
            equity_floor = {"leader": 170.0, "balanced": 210.0, "conservative": 250.0}[board.profile]
            if not failed and safe_cash + secured_margin >= reserve and projected_equity_after_fixed + secured_margin >= equity_floor:
                return state, accepted, removals
            removable = next((index for index in range(len(candidates) - 1, -1, -1) if candidates[index].get("action_type") in self.DISCRETIONARY), None)
            if removable is None:
                return state, accepted, removals + [{"reason": "no_discretionary_action_left", "failed": failed, "safe_cash_wan": safe_cash, "projected_equity_after_fixed_wan": projected_equity_after_fixed}]
            removed = candidates.pop(removable)
            removals.append({"reason": "risk_budget_prune", "action": copy.deepcopy(dict(removed)), "failed": failed, "safe_cash_wan": safe_cash, "projected_equity_after_fixed_wan": projected_equity_after_fixed})


class CollaborativeEnterprisePolicy:
    """Coordinator for six explicit specialist agents controlling one firm."""

    def __init__(
        self,
        agent_id: str,
        seed: int,
        *,
        rules: Mapping[str, Any],
        profile: str = "balanced",
        allow_prospective_new_cell: bool = False,
    ) -> None:
        if profile not in {"leader", "balanced", "conservative"}:
            raise ValueError("collaborative profile must be leader, balanced or conservative")
        self.agent_id = agent_id
        self.seed = seed
        self.rules = copy.deepcopy(dict(rules))
        self.profile = profile
        self.allow_prospective_new_cell = allow_prospective_new_cell
        self.dynamics = FullFinancialDynamics(self.rules)
        self.treasury = TreasurySpecialist()
        self.capability = CapabilitySpecialist()
        self.capacity = CapacitySpecialist()
        self.fulfillment = FulfillmentSpecialist()
        self.orders = OrderPortfolioSpecialist(seed, agent_id, allow_prospective_new_cell=allow_prospective_new_cell)
        self.critic = RiskCriticSpecialist()
        self.decision_history: list[dict[str, Any]] = []
        self.feedback_history: list[dict[str, Any]] = []

    @staticmethod
    def restore_state(payload: Mapping[str, Any]) -> FinancialSandboxState:
        names = {item.name for item in fields(FinancialSandboxState)}
        return FinancialSandboxState(**{name: copy.deepcopy(payload[name]) for name in names if name in payload})

    def act(self, observation: AgentObservation) -> Mapping[str, Any]:
        if observation.agent_id != self.agent_id:
            raise ValueError("collaborative policy received another enterprise's observation")
        if observation.private_state.get("bankrupt"):
            return {"action_type": "hold", "policy_metadata": {"policy": COLLABORATIVE_AGENT_VERSION}}
        board = SharedDecisionBlackboard(observation, self.rules, self.profile)
        decision_phase = str(observation.public_state.get("decision_phase") or "operating")
        if decision_phase == "post_allocation":
            # The opening settlement already ran in the operating phase, so
            # this review must replay only the newly informed fulfillment
            # bundle.  It considers all outstanding orders together and may
            # finance the aggregate working-capital gap before producing.
            treasury = self.treasury.propose(board, self.dynamics)
            capacity = self.capacity.propose(board, self.dynamics)
            fulfillment = self.fulfillment.propose(board, self.dynamics)
            projected = self.restore_state(board.state)
            accepted: list[Mapping[str, Any]] = []
            removals: list[dict[str, Any]] = []
            allowed = {
                "short_loan_borrow", "long_loan_borrow", "receivable_discount",
                "rent_workshop", "buy_workshop", "buy_product_line", "convert_product_line",
                "material_order", "emergency_purchase", "emergency_product_purchase",
                "production", "order_delivery",
            }
            for action in [*treasury.actions, *capacity.actions, *fulfillment.actions]:
                if action.get("action_type") not in allowed:
                    removals.append({"reason": "not_allowed_in_post_allocation_phase", "action": copy.deepcopy(dict(action))})
                    continue
                transition = self.dynamics.apply(projected, action)
                if transition.status != "success" or transition.state.bankrupt:
                    removals.append({"reason": "post_allocation_replay_rejected", "action": copy.deepcopy(dict(action)), "violations": list(transition.violations)})
                    continue
                projected = transition.state
                accepted.append(copy.deepcopy(dict(action)))
            audit = {
                "period": observation.period,
                "decision_phase": decision_phase,
                "profile": self.profile,
                "specialist_proposals": [treasury.to_dict(), capacity.to_dict(), fulfillment.to_dict()],
                "risk_review": {"specialist_id": self.critic.specialist_id, "removed_actions": removals, "projected_cash_wan": projected.cash_wan, "projected_equity_wan": projected.owner_equity_wan, "projected_bankrupt": projected.bankrupt},
                "coordination_protocol": "actual_allocation_feedback_then_joint_working_capital_and_fulfillment_replay",
                "information_scope": "owned_private_state_plus_actual_public_allocation_results",
                "portfolio_scope": "all_outstanding_orders_jointly_scheduled_by_due_date_product_inventory_materials_and_lines",
                "vpd_role": "offline_complete_trajectory_acceptance_not_single_action_selector",
            }
            self.decision_history.append(copy.deepcopy(audit))
            return {
                "actions": accepted or [{"action_type": "hold"}],
                "policy_metadata": {
                    "policy": COLLABORATIVE_AGENT_VERSION,
                    "owned_enterprise_only": True,
                    "specialist_count": 6,
                    "decision_phase": decision_phase,
                    "planning_audit": audit,
                },
            }
        treasury = self.treasury.propose(board, self.dynamics)
        capability = self.capability.propose(board, self.dynamics)
        capacity = self.capacity.propose(board, self.dynamics)
        fulfillment = self.fulfillment.propose(board, self.dynamics)
        operating = [*capability.actions, *capacity.actions, *fulfillment.actions]
        preliminary, _, _ = self.critic.review(board, self.dynamics, treasury.actions, operating)
        order_proposal = self.orders.propose(board, preliminary.to_dict())
        advertising_actions = [action for action in order_proposal.actions if action.get("action_type") == "advertising"]
        claims = [copy.deepcopy(dict(action)) for action in order_proposal.actions if action.get("action_type") in {"select_order", "auction_bid", "order_portfolio"}]
        # The final risk pass replays finance, capability, capacity,
        # fulfillment and advertising as one bundle.  Claims are nonfinancial
        # allocation requests, so they are appended only after their reported
        # advertising values have been reconciled with that final projection.
        projected, accepted, removals = self.critic.review(board, self.dynamics, treasury.actions, [*operating, *advertising_actions])
        def reconcile_claim(claim: dict[str, Any]) -> None:
            if claim.get("action_type") == "order_portfolio":
                for slot in (claim.get("parameters") or {}).get("candidate_slots") or []:
                    for candidate in slot:
                        reconcile_claim(candidate)
                return
            if claim.get("action_type") != "select_order":
                return
            values = claim.setdefault("parameters", {})
            market, product = str(values.get("market")), str(values.get("product"))
            values["product_advertising"] = _number(projected.advertising.get(f"{market}:{product}"))
            values["market_advertising"] = sum(_number(value) for key, value in projected.advertising.items() if key.startswith(f"{market}:"))
            values["total_advertising"] = sum(_number(value) for value in projected.advertising.values())
        for claim in claims:
            reconcile_claim(claim)
        actions = [*accepted, *claims]
        proposals = [treasury, capability, capacity, fulfillment, order_proposal]
        audit = {
            "period": observation.period,
            "profile": self.profile,
            "specialist_proposals": [proposal.to_dict() for proposal in proposals],
            "risk_review": {"specialist_id": self.critic.specialist_id, "removed_actions": removals, "projected_cash_wan": projected.cash_wan, "projected_equity_wan": projected.owner_equity_wan, "projected_bankrupt": projected.bankrupt},
            "coordination_protocol": "shared_blackboard_then_joint_bundle_then_finance_opening_operating_replay_then_order_portfolio",
            "information_scope": "owned_private_state_plus_released_public_orders_only",
            "vpd_role": "offline_complete_trajectory_acceptance_not_single_action_selector",
        }
        self.decision_history.append(copy.deepcopy(audit))
        return {
            "actions": actions or [{"action_type": "hold"}],
            "policy_metadata": {
                "policy": COLLABORATIVE_AGENT_VERSION,
                "owned_enterprise_only": True,
                "specialist_count": 6,
                "allow_prospective_new_cell": self.allow_prospective_new_cell,
                "planning_audit": audit,
            },
        }

    def observe_feedback(self, feedback: Mapping[str, Any], next_observation: AgentObservation) -> None:
        if str(feedback.get("agent_id")) != self.agent_id or next_observation.agent_id != self.agent_id:
            raise ValueError("collaborative policy received another enterprise's feedback")
        record = {"period": feedback.get("period"), "status": feedback.get("action_status"), "rejections": list(feedback.get("action_rejections") or []), "reward": feedback.get("reward"), "bankrupt": feedback.get("bankrupt"), "next_period": next_observation.period}
        self.feedback_history.append(record)
        if self.decision_history:
            self.decision_history[-1]["feedback"] = copy.deepcopy(record)
