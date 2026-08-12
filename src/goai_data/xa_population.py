"""Aggregate-history-calibrated XA population policies for simulator testing.

These policies use only aggregate strategy-class targets derived from the real
XA field distribution.  They do not replay a team's future actions, order
owners, terminal score or bankruptcy label.  Their purpose is to test whether
the forward simulator can reproduce realistic population-level ranges.
"""

from __future__ import annotations

import copy
import hashlib
from dataclasses import dataclass, fields
from typing import Any, Mapping, Sequence

from .decision_system import AgentObservation
from .collaborative_agent import CollaborativeEnterprisePolicy
from .full_sandbox import FinancialSandboxState, FixedXABaselinePolicy, FullFinancialDynamics, order_is_qualified
from .owned_agent import RobustAgentConfig, RobustOrderPlanner


XA_POPULATION_POLICY_VERSION = "xa_aggregate_calibrated_population_v1.0"


def _number(value: Any, default: float = 0.0) -> float:
    return float(value) if isinstance(value, (int, float)) else default


@dataclass(frozen=True)
class XAClassTarget:
    strategy_class: str
    products: tuple[str, ...]
    markets: tuple[str, ...]
    iso: tuple[str, ...]
    factories: tuple[tuple[str, str], ...]
    line_types: tuple[str, ...]
    target_lines: int
    target_orders: int
    claims_per_quarter: int
    cash_reserve_wan: float
    long_loan_target_y1_wan: float
    long_loan_target_y2_wan: float
    advertising_pairs: int
    advertising_wan: float


CLASS_TARGETS = {
    "leader_growth": XAClassTarget(
        "leader_growth", ("P1", "P2", "P3", "P4"), ("本地", "区域", "国内", "亚洲", "国际"), ("ISO9000", "ISO14000"),
        (("buy", "大厂房"), ("buy", "大厂房"), ("buy", "中厂房")),
        ("自动线", "自动线", "手工线", "自动线", "手工线", "租赁线", "自动线", "手工线", "自动线", "手工线", "租赁线", "自动线"),
        12, 34, 3, 55.0, 600.0, 1050.0, 3, 24.0,
    ),
    "balanced_expansion": XAClassTarget(
        "balanced_expansion", ("P1", "P2", "P3"), ("本地", "区域", "国内", "亚洲"), ("ISO9000",),
        (("buy", "大厂房"), ("buy", "中厂房")),
        ("自动线", "手工线", "柔性线", "自动线", "手工线", "自动线", "手工线", "柔性线", "自动线"),
        9, 27, 2, 75.0, 450.0, 600.0, 2, 18.0,
    ),
    "conservative_survivor": XAClassTarget(
        "conservative_survivor", ("P1", "P2", "P3"), ("本地", "区域", "国内"), (),
        (("buy", "中厂房"), ("buy", "小厂房"), ("buy", "小厂房")),
        ("自动线", "手工线", "柔性线", "自动线", "手工线"),
        5, 20, 2, 115.0, 250.0, 300.0, 1, 12.0,
    ),
    "aggressive_failed": XAClassTarget(
        "aggressive_failed", ("P1", "P2", "P3"), ("本地", "区域", "国内", "亚洲"), ("ISO9000",),
        (("rent", "大厂房"), ("rent", "小厂房")),
        ("手工线", "手工线", "自动线", "租赁线", "自动线", "手工线", "租赁线"),
        7, 16, 3, 20.0, 600.0, 850.0, 2, 28.0,
    ),
}


def strategy_class_for_team(team_id: str, team_count: int = 27) -> str:
    digits = "".join(character for character in team_id if character.isdigit())
    index = int(digits[-2:] or 1) if digits else 1
    if team_count == 27:
        if index <= 6:
            return "leader_growth"
        if index <= 9:
            return "balanced_expansion"
        if index <= 18:
            return "conservative_survivor"
        return "aggressive_failed"
    bucket = (index - 1) % 9
    return ("leader_growth", "leader_growth", "balanced_expansion", "conservative_survivor", "conservative_survivor", "conservative_survivor", "aggressive_failed", "aggressive_failed", "aggressive_failed")[bucket]


class XARealisticPopulationPolicy:
    """Target-driven multi-domain policy calibrated to aggregate XA profiles."""

    def __init__(self, agent_id: str, seed: int, *, rules: Mapping[str, Any], strategy_class: str | None = None) -> None:
        self.agent_id = agent_id
        self.seed = seed
        self.rules = copy.deepcopy(dict(rules))
        self.parameters = dict(self.rules.get("parameters") or {})
        team_count = int((self.rules.get("participants") or {}).get("count", 27))
        self.strategy_class = strategy_class or strategy_class_for_team(agent_id, team_count)
        self.target = CLASS_TARGETS[self.strategy_class]
        self.dynamics = FullFinancialDynamics(self.rules)
        self.schedule_planner = RobustOrderPlanner(
            self.rules,
            RobustAgentConfig(
                scenario_count=4,
                max_candidate_orders=20,
                max_order_claims_per_quarter=max(1, self.target.claims_per_quarter),
                minimum_cash_reserve_wan=self.target.cash_reserve_wan,
            ),
            seed=seed,
        )
        self.safe_baseline = FixedXABaselinePolicy(agent_id, seed, rules=self.rules)

    @staticmethod
    def _restore(payload: Mapping[str, Any]) -> FinancialSandboxState:
        names = {item.name for item in fields(FinancialSandboxState)}
        return FinancialSandboxState(**{name: copy.deepcopy(payload[name]) for name in names if name in payload})

    def _stable_fraction(self, *parts: Any) -> float:
        digest = hashlib.sha256("|".join(map(str, (self.seed, self.agent_id, *parts))).encode()).hexdigest()
        return int(digest[:12], 16) / float(0xFFFFFFFFFFFF)

    def _apply(self, state: FinancialSandboxState, actions: list[dict[str, Any]], action: Mapping[str, Any], *, reserve: float | None = None) -> FinancialSandboxState:
        transition = self.dynamics.apply(state, action)
        if transition.status != "success" or transition.state.bankrupt:
            return state
        if reserve is not None and transition.state.cash_wan < reserve:
            return state
        actions.append(copy.deepcopy(dict(action)))
        return transition.state

    def _finance(self, state: FinancialSandboxState, actions: list[dict[str, Any]]) -> FinancialSandboxState:
        if state.receivables and state.cash_wan < self.target.cash_reserve_wan + 100:
            receivable = min(state.receivables, key=lambda row: (int(row.get("due_period_index", 99)), str(row.get("receivable_id"))))
            state = self._apply(state, actions, {"action_type": "receivable_discount", "parameters": {"receivable_id": receivable.get("receivable_id")}})
        # The observed XA opening balance is only 675 wan.  A target-sized
        # leader loan in Y1Q1 would fund an attractive balance sheet but would
        # also create unavoidable Y1Q2 line/material cash calls before any XA
        # orders are released.  Borrow in tranches and leave a settlement
        # buffer; this is a policy calibration rule, not a simulator override.
        raw_target = self.target.long_loan_target_y1_wan if state.year == 1 else self.target.long_loan_target_y2_wan
        opening_caps = {
            "leader_growth": 600.0,
            "balanced_expansion": 450.0,
            "conservative_survivor": 300.0,
            "aggressive_failed": 650.0,
        }
        year_target = min(raw_target, opening_caps[self.strategy_class])
        current_long = sum(_number(row.get("principal_wan")) for row in state.long_loans)
        if state.quarter == 1 and state.year <= 2 and current_long + 1e-9 < year_target:
            principal = min(opening_caps[self.strategy_class], year_target - current_long)
            term_years = min(4, max(1, 6 - state.year))
            state = self._apply(state, actions, {"action_type": "long_loan_borrow", "parameters": {"principal_wan": principal, "term_years": term_years}})
        # The arena accepts financing first and then runs automatic opening
        # settlement.  Preview that exact phase so the policy finances accrued
        # interest, material arrivals and construction installments before it
        # plans operating actions from the post-settlement state.
        preview = copy.deepcopy(state)
        self.dynamics._opening_settlement(preview)
        safe_reserve = 45.0 if self.strategy_class == "aggressive_failed" else max(120.0, self.target.cash_reserve_wan)
        if preview.cash_wan < safe_reserve and state.period_index >= 4:
            gap = safe_reserve - preview.cash_wan
            principal = min(450.0, max(80.0, gap + 35.0))
            state = self._apply(state, actions, {"action_type": "short_loan_borrow", "parameters": {"principal_wan": principal, "term_quarters": 4}})
        return state

    def _qualifications(self, state: FinancialSandboxState, actions: list[dict[str, Any]]) -> FinancialSandboxState:
        pending = {(str(row.get("kind")), str(row.get("target"))) for row in state.pending_development}
        candidates: list[dict[str, Any]] = []
        for target in self.target.products:
            if target not in state.products and ("product", target) not in pending:
                candidates.append({"action_type": "develop_product", "parameters": {"target": target}})
        for target in self.target.markets:
            if target not in state.markets and ("market", target) not in pending:
                candidates.append({"action_type": "develop_market", "parameters": {"target": target}})
        for target in self.target.iso:
            if target not in state.iso and ("iso", target) not in pending:
                candidates.append({"action_type": "develop_iso", "parameters": {"target": target}})
        # Complete only a small number of qualifications per quarter.  This
        # keeps the fixed-cost pipeline financeable while preserving the
        # eventual XA asset mix over 20 quarters.
        maximum = 2 if state.period_index == 0 else (2 if state.period_index < 4 else 3)
        for action in candidates[:maximum]:
            state = self._apply(state, actions, action, reserve=max(0.0, self.target.cash_reserve_wan * 0.45))
        return state

    def _capacity(self, state: FinancialSandboxState, actions: list[dict[str, Any]]) -> FinancialSandboxState:
        safe_reserve = 45.0 if self.strategy_class == "aggressive_failed" else max(180.0, self.target.cash_reserve_wan)
        outstanding = [row for row in state.assigned_orders if row.get("status") not in {"已交", "违约"}]
        outstanding_units = sum(_number(row.get("quantity")) for row in outstanding)
        existing_factories = [(str(row.get("ownership")), str(row.get("name"))) for row in state.factories]
        for mode, factory in self.target.factories:
            if state.period_index < 4 and state.factories:
                break
            ownership = "purchased" if mode == "buy" else "rented"
            if (ownership, factory) in existing_factories:
                continue
            factory_rule = (self.parameters.get("factories") or {}).get(factory) or {}
            immediate_cost = _number(factory_rule.get("purchase_wan" if mode == "buy" else "rent_wan_per_year"))
            existing_capacity = sum(int(row.get("capacity", 0)) for row in state.factories)
            demand_justifies_expansion = outstanding_units > max(1, existing_capacity) * 2 or state.cash_wan >= immediate_cost + safe_reserve + 180
            if state.factories and not demand_justifies_expansion:
                break
            if state.cash_wan < immediate_cost + safe_reserve:
                break
            action_type = "buy_workshop" if mode == "buy" else "rent_workshop"
            candidate = {"action_type": action_type, "parameters": {"factory": factory}}
            next_state = self._apply(state, actions, candidate, reserve=safe_reserve)
            if next_state is not state:
                state = next_state
            break
        line_count = len(state.production_lines) + len(state.pending_lines)
        capacity = sum(int(row.get("capacity", 0)) for row in state.factories)
        # A small rented workshop is the low-capital capacity bridge used by
        # many human teams: it avoids buying a second 248–481 wan workshop
        # solely to install one additional line.
        if self.target.target_lines > line_count and capacity <= line_count and state.period_index >= 4 and state.cash_wan >= safe_reserve + 35:
            state = self._apply(state, actions, {"action_type": "rent_workshop", "parameters": {"factory": "小厂房"}}, reserve=safe_reserve)
            capacity = sum(int(row.get("capacity", 0)) for row in state.factories)
        additions = min(1, self.target.target_lines - line_count, max(0, capacity - line_count))
        if state.period_index < 4 and line_count:
            additions = 0
        line_rule = (self.parameters.get("production_lines") or {}).get(self.target.line_types[line_count % len(self.target.line_types)], {})
        line_cost = _number(line_rule.get("investment_wan_per_quarter"), _number(line_rule.get("investment_wan")))
        if state.period_index >= 4 and state.cash_wan < line_cost + safe_reserve + 20:
            additions = 0
        if state.pending_lines:
            additions = 0
        for offset in range(max(0, additions)):
            index = line_count + offset
            line_type = self.target.line_types[index % len(self.target.line_types)]
            product = self.target.products[index % len(self.target.products)]
            candidate = {"action_type": "buy_product_line", "parameters": {"line_type": line_type, "product_id": product}}
            state = self._apply(state, actions, candidate, reserve=safe_reserve)
        return state

    def _regular_materials(self, state: FinancialSandboxState, actions: list[dict[str, Any]]) -> FinancialSandboxState:
        if not state.production_lines and not state.pending_lines:
            return state
        outstanding = [row for row in state.assigned_orders if row.get("status") not in {"已交", "违约"}]
        if not outstanding:
            return state
        line_capacity_by_product: dict[str, int] = {}
        flexible_lines = 0
        for line in [*state.production_lines, *state.pending_lines]:
            if line.get("line_type") == "柔性线":
                flexible_lines += 1
            elif line.get("product_id"):
                product = str(line.get("product_id"))
                line_capacity_by_product[product] = line_capacity_by_product.get(product, 0) + 1
        outstanding_by_product: dict[str, float] = {}
        for order in outstanding:
            product = str(order.get("product"))
            outstanding_by_product[product] = outstanding_by_product.get(product, 0.0) + _number(order.get("quantity"))
        required: dict[str, float] = {}
        for product, raw_quantity in outstanding_by_product.items():
            planned_quantity = min(raw_quantity, max(1, line_capacity_by_product.get(product, 0) + flexible_lines) * 2)
            for component, units in ((self.parameters.get("products") or {}).get(product, {}).get("bom") or {}).items():
                if str(component).startswith("R"):
                    required[str(component)] = required.get(str(component), 0.0) + _number(units) * planned_quantity
        pending = {}
        for row in state.pending_material_orders:
            material = str(row.get("material_id"))
            pending[material] = pending.get(material, 0.0) + _number(row.get("quantity"))
        order = {
            material: max(0.0, quantity - state.material_inventory.get(material, 0.0) - pending.get(material, 0.0))
            for material, quantity in required.items()
        }
        order = {material: quantity for material, quantity in order.items() if quantity > 0}
        if order:
            state = self._apply(state, actions, {"action_type": "material_order", "parameters": {"materials": order}})
        return state

    def _produce_and_deliver(self, state: FinancialSandboxState, actions: list[dict[str, Any]]) -> FinancialSandboxState:
        outstanding = sorted(
            [row for row in state.assigned_orders if row.get("status") not in {"已交", "违约"}],
            key=lambda row: (int(row.get("due_period_index", 99)), str(row.get("order_id"))),
        )
        required: dict[str, float] = {}
        for order in outstanding:
            product = str(order.get("product"))
            required[product] = required.get(product, 0.0) + _number(order.get("quantity"))
        for product, quantity in state.product_inventory.items():
            required[product] = max(0.0, required.get(product, 0.0) - _number(quantity))
        for job in state.pending_production:
            product = str(job.get("product_id"))
            required[product] = max(0.0, required.get(product, 0.0) - _number(job.get("quantity")))

        ready_lines = [copy.deepcopy(row) for row in state.production_lines if row.get("status") == "ready"]
        for line in ready_lines:
            eligible_products = [
                product for product, shortage in sorted(required.items(), key=lambda row: (-row[1], row[0]))
                if shortage > 0 and product in state.products and (line.get("line_type") == "柔性线" or line.get("product_id") in {None, product})
            ]
            # Do not build speculative inventory before orders are visible.
            if not eligible_products:
                continue
            product = eligible_products[0]
            rule = (self.parameters.get("products") or {}).get(product) or {}
            for component, raw_units in (rule.get("bom") or {}).items():
                need = _number(raw_units)
                if str(component).startswith("R"):
                    missing = max(0.0, need - state.material_inventory.get(str(component), 0.0))
                    if missing:
                        state = self._apply(state, actions, {"action_type": "emergency_purchase", "parameters": {"material_id": component, "quantity": missing}})
                else:
                    missing = max(0.0, need - state.product_inventory.get(str(component), 0.0))
                    if missing and str(component) in state.products:
                        state = self._apply(state, actions, {"action_type": "emergency_product_purchase", "parameters": {"product_id": component, "quantity": missing}})
            state = self._apply(state, actions, {"action_type": "production", "parameters": {"product_id": product, "quantity": 1, "line_type": line.get("line_type")}})
            required[product] = max(0.0, required.get(product, 0.0) - 1)

        blocked_products: set[str] = set()
        for order in outstanding:
            product = str(order.get("product"))
            if product in blocked_products:
                continue
            if state.product_inventory.get(product, 0.0) + 1e-9 < _number(order.get("quantity")):
                blocked_products.add(product)
                continue
            state = self._apply(state, actions, {"action_type": "order_delivery", "parameters": {"order_id": order.get("order_id")}})
        return state

    def _advertising(self, observation: AgentObservation, state: FinancialSandboxState, actions: list[dict[str, Any]]) -> FinancialSandboxState:
        if state.quarter != 1 or state.year == 1:
            return state
        safe_reserve = 45.0 if self.strategy_class == "aggressive_failed" else max(180.0, self.target.cash_reserve_wan)
        visible = [
            row for row in observation.public_state.get("available_orders") or []
            if order_is_qualified(row, markets=state.markets, products=state.products, iso=state.iso)
        ]
        pairs: dict[tuple[str, str], float] = {}
        for order in visible:
            pair = (str(order.get("market")), str(order.get("product")))
            pairs[pair] = pairs.get(pair, 0.0) + _number(order.get("total_price_wan"))
        for (market, product), _ in sorted(pairs.items(), key=lambda row: (-row[1], row[0]))[: self.target.advertising_pairs]:
            if state.cash_wan < safe_reserve + self.target.advertising_wan + 30:
                break
            state = self._apply(
                state,
                actions,
                {"action_type": "advertising", "parameters": {"market": market, "product_id": product, "amount_wan": self.target.advertising_wan}},
                reserve=safe_reserve,
            )
        return state

    def _claims(self, observation: AgentObservation, state: FinancialSandboxState) -> list[dict[str, Any]]:
        remaining_target = self.target.target_orders - len(state.assigned_orders)
        annual_budget = {
            "leader_growth": 10,
            "balanced_expansion": 8,
            "conservative_survivor": 7,
            "aggressive_failed": 9,
        }
        claim_budget = annual_budget[self.strategy_class] if state.quarter == 1 else self.target.claims_per_quarter
        budget = min(claim_budget, max(0, remaining_target))
        if budget <= 0 or state.cash_wan < max(0.0, self.target.cash_reserve_wan * 0.25):
            return []
        candidates = [
            row for row in observation.public_state.get("available_orders") or []
            if order_is_qualified(row, markets=state.markets, products=state.products, iso=state.iso)
            and int(row.get("due_period_index", 99)) > observation.period_index
        ]
        line_products = {
            str(line.get("product_id"))
            for line in [*state.production_lines, *state.pending_lines]
            if line.get("product_id")
        }
        has_flexible = any(line.get("line_type") == "柔性线" for line in [*state.production_lines, *state.pending_lines])

        def value(order: Mapping[str, Any]) -> tuple[float, float, float, str]:
            product = str(order.get("product"))
            direct = _number((self.parameters.get("products") or {}).get(product, {}).get("direct_cost_wan")) * _number(order.get("quantity"))
            margin = _number(order.get("total_price_wan")) - direct
            capability = 250.0 if product in line_products or has_flexible else 0.0
            diversity = self._stable_fraction(order.get("order_id")) * 320.0
            urgency = max(0.0, 8 - (int(order.get("due_period_index", 99)) - observation.period_index)) * 4
            quantity = max(1.0, _number(order.get("quantity")))
            return capability + margin / quantity * 4 + diversity - urgency, -quantity, margin, str(order.get("order_id"))
        candidates.sort(key=value, reverse=True)
        outstanding = [row for row in state.assigned_orders if row.get("status") not in {"已交", "违约"}]
        outstanding_caps = {
            "leader_growth": 16,
            "balanced_expansion": 12,
            "conservative_survivor": 9,
            "aggressive_failed": 18,
        }
        chosen: list[Mapping[str, Any]] = []
        for order in candidates:
            product = str(order.get("product"))
            direct = _number((self.parameters.get("products") or {}).get(product, {}).get("direct_cost_wan")) * _number(order.get("quantity"))
            if _number(order.get("total_price_wan")) <= direct:
                continue
            if len(outstanding) + len(chosen) >= outstanding_caps[self.strategy_class]:
                continue
            # Population calibration models the common human strategy of
            # accepting profitable future orders and expanding capacity after
            # observing the backlog.  The deployable owned agent retains the
            # stricter robust schedule-feasibility gate.
            due_gap = int(order.get("due_period_index", 99)) - observation.period_index
            product_lines = sum(
                line.get("line_type") == "柔性线" or str(line.get("product_id")) == product
                for line in [*state.production_lines, *state.pending_lines]
            )
            existing_units = sum(_number(row.get("quantity")) for row in [*outstanding, *chosen] if str(row.get("product")) == product)
            if product_lines <= 0 and due_gap < 4:
                continue
            if existing_units + _number(order.get("quantity")) > max(1, product_lines) * max(1, due_gap):
                continue
            chosen.append(order)
            if len(chosen) >= budget:
                break
        advertising = state.advertising
        claims = []
        for order in chosen:
            market, product = str(order.get("market")), str(order.get("product"))
            common = {"order_id": order.get("order_id"), "submitted_at": self._stable_fraction("claim", order.get("order_id")), "market": market, "product": product}
            if str(order.get("order_type")) == "竞单":
                factor = 1.04 if self.strategy_class in {"leader_growth", "aggressive_failed"} else 0.97
                claims.append({"action_type": "auction_bid", "parameters": {**common, "bid_wan": round(_number(order.get("total_price_wan")) * factor, 2)}})
            else:
                claims.append({"action_type": "select_order", "parameters": {**common, "product_advertising": _number(advertising.get(f"{market}:{product}")), "market_advertising": sum(_number(amount) for key, amount in advertising.items() if key.startswith(f"{market}:")), "total_advertising": sum(_number(amount) for amount in advertising.values())}})
        return claims

    def _safe_survivor_bundle(self, observation: AgentObservation) -> Mapping[str, Any]:
        """Cash-safe causal baseline for the 18 target survivor enterprises."""

        baseline = dict(self.safe_baseline.act(observation))
        raw_actions = baseline.get("actions")
        actions = [copy.deepcopy(dict(row)) for row in raw_actions] if isinstance(raw_actions, list) else [copy.deepcopy(dict(baseline))]
        if len(actions) == 1 and actions[0].get("action_type") == "hold":
            actions = []
        state = observation.private_state
        cash = _number(state.get("cash_wan"))
        pending = {(str(row.get("kind")), str(row.get("target"))) for row in state.get("pending_development") or []}
        products = set(map(str, state.get("products") or []))
        markets = set(map(str, state.get("markets") or []))
        iso = set(map(str, state.get("iso") or []))
        supplement: dict[str, Any] | None = None
        if cash >= 480 and "P2" not in products and ("product", "P2") not in pending:
            supplement = {"action_type": "develop_product", "parameters": {"target": "P2"}}
        elif cash >= 470 and "区域" not in markets and ("market", "区域") not in pending:
            supplement = {"action_type": "develop_market", "parameters": {"target": "区域"}}
        elif cash >= 520 and self.strategy_class in {"leader_growth", "balanced_expansion"} and "P3" not in products and ("product", "P3") not in pending:
            supplement = {"action_type": "develop_product", "parameters": {"target": "P3"}}
        elif cash >= 540 and self.strategy_class == "leader_growth" and "国内" not in markets and ("market", "国内") not in pending:
            supplement = {"action_type": "develop_market", "parameters": {"target": "国内"}}
        elif cash >= 620 and observation.period_index <= 8 and self.strategy_class == "leader_growth" and "ISO9000" not in iso and ("iso", "ISO9000") not in pending:
            supplement = {"action_type": "develop_iso", "parameters": {"target": "ISO9000"}}
        factories = list(state.get("factories") or [])
        lines = [*(state.get("production_lines") or []), *(state.get("pending_lines") or [])]
        capacity = sum(int(row.get("capacity", 0)) for row in factories)
        if supplement is None and observation.period_index >= 8 and cash >= 430 and capacity <= len(lines):
            supplement = {"action_type": "rent_workshop", "parameters": {"factory": "小厂房"}}
        elif supplement is None and observation.period_index >= 9 and cash >= 390 and capacity > len(lines) and "P2" in products:
            supplement = {"action_type": "buy_product_line", "parameters": {"line_type": "手工线", "product_id": "P2"}}
        if supplement is not None:
            actions.append(supplement)
        return {
            "actions": actions or [{"action_type": "hold"}],
            "policy_metadata": {
                "policy": XA_POPULATION_POLICY_VERSION,
                "strategy_class": self.strategy_class,
                "calibration_scope": "cash_safe_survivor_cohort_without_team_future_path",
                "online_deployment_policy": False,
                "base_policy": "fixed_XA_cash_aware_v2",
            },
        }


    def act(self, observation: AgentObservation) -> Mapping[str, Any]:
        if observation.agent_id != self.agent_id:
            raise ValueError("population policy received another enterprise's observation")
        if observation.private_state.get("bankrupt"):
            return {"action_type": "hold", "policy_metadata": {"policy": XA_POPULATION_POLICY_VERSION, "strategy_class": self.strategy_class}}
        if self.strategy_class != "aggressive_failed":
            return self._safe_survivor_bundle(observation)
        state = self._restore(observation.private_state)
        actions: list[dict[str, Any]] = []
        state = self._finance(state, actions)
        # Mirror FullCompetitionArena.step(): after the financing prefix, the
        # environment settles automatic obligations before all other actions.
        # Planning on this preview prevents decisions from spending cash that
        # is already committed to the current quarter's opening settlement.
        settled_state = copy.deepcopy(state)
        self.dynamics._opening_settlement(settled_state)
        if settled_state.bankrupt:
            return {
                "actions": actions or [{"action_type": "hold"}],
                "policy_metadata": {
                    "policy": XA_POPULATION_POLICY_VERSION,
                    "strategy_class": self.strategy_class,
                    "calibration_scope": "aggregate_XA_strategy_distribution_without_team_future_path",
                    "online_deployment_policy": False,
                    "planning_status": "opening_settlement_insolvent_after_available_financing",
                },
            }
        state = settled_state
        state = self._qualifications(state, actions)
        state = self._capacity(state, actions)
        state = self._regular_materials(state, actions)
        state = self._produce_and_deliver(state, actions)
        state = self._advertising(observation, state, actions)
        actions.extend(self._claims(observation, state))
        return {
            "actions": actions or [{"action_type": "hold"}],
            "policy_metadata": {
                "policy": XA_POPULATION_POLICY_VERSION,
                "strategy_class": self.strategy_class,
                "calibration_scope": "aggregate_XA_strategy_distribution_without_team_future_path",
                "online_deployment_policy": False,
            },
        }


class XALateAggressivePopulationPolicy:
    """Operate normally first, then fail through observable late expansion.

    The real XA bankruptcies occur from Y3Q4 through Y5Q4.  The older
    ``aggressive_failed`` policy spent its opening equity before the first
    order cohort could be fulfilled, so its Y2 awards remained unresolved.
    This opponent uses the same causal collaborative controller during the
    operating phase, then adds rental capacity and advertising at a stable,
    team-specific late trigger.  Bankruptcy is still decided exclusively by
    the financial state machine.
    """

    def __init__(self, agent_id: str, seed: int, *, rules: Mapping[str, Any]) -> None:
        self.agent_id = agent_id
        self.seed = seed
        self.rules = copy.deepcopy(dict(rules))
        self.delegate = CollaborativeEnterprisePolicy(agent_id, seed, rules=rules, profile="conservative")
        digits = "".join(character for character in agent_id if character.isdigit())
        index = int(digits[-2:] or 1) if digits else 1
        self.trigger_period_index = (12, 14, 16)[(index - 1) % 3]

    def act(self, observation: AgentObservation) -> Mapping[str, Any]:
        bundle = copy.deepcopy(dict(self.delegate.act(observation)))
        if (
            observation.private_state.get("bankrupt")
            or observation.period_index < self.trigger_period_index
            or str(observation.public_state.get("decision_phase") or "operating") == "post_allocation"
        ):
            return bundle
        actions = [copy.deepcopy(dict(row)) for row in bundle.get("actions") or [] if row.get("action_type") != "hold"]
        state = observation.private_state
        factories = list(state.get("factories") or [])
        lines = [*(state.get("production_lines") or []), *(state.get("pending_lines") or [])]
        rental_lines = sum(row.get("line_type") == "租赁线" for row in lines)
        stage = observation.period_index - self.trigger_period_index
        desired_rental_lines = min(4, 1 + stage // 2)
        if rental_lines < desired_rental_lines and "P1" in (state.get("products") or []):
            capacity = sum(int(row.get("capacity", 0)) for row in factories)
            if capacity <= len(lines):
                actions.append({"action_type": "rent_workshop", "parameters": {"factory": "小厂房"}})
            actions.append({"action_type": "buy_product_line", "parameters": {"line_type": "租赁线", "product_id": "P1"}})
        if "本地" in (state.get("markets") or []) and "P1" in (state.get("products") or []):
            actions.append(
                {
                    "action_type": "advertising",
                    "parameters": {"market": "本地", "product_id": "P1", "amount_wan": min(80.0, 35.0 + stage * 5.0)},
                }
            )
        metadata = copy.deepcopy(dict(bundle.get("policy_metadata") or {}))
        metadata.update(
            {
                "population_behavior": "late_aggressive_expansion",
                "late_aggressive_trigger_period_index": self.trigger_period_index,
                "late_aggressive_stage": stage,
            }
        )
        return {"actions": actions or [{"action_type": "hold"}], "policy_metadata": metadata}

    def observe_feedback(self, feedback: Mapping[str, Any], next_observation: AgentObservation) -> None:
        self.delegate.observe_feedback(feedback, next_observation)
