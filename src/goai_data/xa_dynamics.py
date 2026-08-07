from __future__ import annotations

import copy
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Mapping

from .decision_system import AgentObservation, ArenaStep, MultiAgentEnvironment
from .global_rules import is_bankrupt, merge_rule_overrides
from .order_allocation import OrderAllocationEngine, SelectionPriorityPolicy
from .traditional_rules import TraditionalXAOrderPolicy, traditional_visibility_context


XA_DYNAMICS_VERSION = "xa_dynamics_v0.2_configurable_counterfactual_kernel"


def _period_index(year: int, quarter: int) -> int:
    return (year - 1) * 4 + (quarter - 1)


def _period_from_index(index: int) -> tuple[int, int]:
    return index // 4 + 1, index % 4 + 1


def _amount(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) else None


@dataclass
class XAState:
    match_id: str
    team_id: str
    year: int = 1
    quarter: int = 1
    cash_wan: float = 675.0
    owner_equity_wan: float = 675.0
    debt_wan: float = 0.0
    material_inventory: dict[str, float] = field(default_factory=dict)
    product_inventory: dict[str, float] = field(default_factory=dict)
    markets: list[str] = field(default_factory=list)
    products: list[str] = field(default_factory=list)
    iso: list[str] = field(default_factory=list)
    factories: list[dict[str, Any]] = field(default_factory=list)
    production_lines: list[dict[str, Any]] = field(default_factory=list)
    pending_material_orders: list[dict[str, Any]] = field(default_factory=list)
    pending_development: list[dict[str, Any]] = field(default_factory=list)
    pending_lines: list[dict[str, Any]] = field(default_factory=list)
    pending_production: list[dict[str, Any]] = field(default_factory=list)
    short_loans: list[dict[str, Any]] = field(default_factory=list)
    receivables: list[dict[str, Any]] = field(default_factory=list)
    delivered_orders: list[dict[str, Any]] = field(default_factory=list)
    available_orders: list[dict[str, Any]] = field(default_factory=list)
    assigned_orders: list[dict[str, Any]] = field(default_factory=list)
    advertising: dict[str, float] = field(default_factory=dict)
    cumulative_revenue_wan: float = 0.0
    cumulative_expense_wan: float = 0.0
    event_log: list[dict[str, Any]] = field(default_factory=list)
    bankrupt: bool = False
    accounting_status: str = "cash_and_commitments_partial_accounting"

    @property
    def period_index(self) -> int:
        return _period_index(self.year, self.quarter)

    @property
    def period(self) -> str:
        return f"Y{self.year}Q{self.quarter}"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self) | {"period": self.period, "period_index": self.period_index}


@dataclass(frozen=True)
class XATransition:
    status: str
    state: XAState
    event: Mapping[str, Any] = field(default_factory=dict)
    violations: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


class XADynamics:
    """Deterministic XA cash/commitment kernel.

    This kernel deliberately rejects unresolved shared-order actions. It is a
    foundation for replay and counterfactual tests, not a claim that every
    accounting and competition rule is complete.
    """

    def __init__(self, rules: Mapping[str, Any], *, material_payment_timing: str = "arrival", overrides: Mapping[str, Any] | None = None) -> None:
        normalized_rules = dict(rules)
        if "parameters" not in normalized_rules and "formal_parameters" in normalized_rules:
            normalized_rules["parameters"] = copy.deepcopy(normalized_rules["formal_parameters"])
        services = normalized_rules.get("global_rule_services") or {}
        order_pool = services.get("order_pool") or {}
        if order_pool.get("selection_priority") and not normalized_rules["parameters"].get("selection_priority"):
            normalized_rules["parameters"]["selection_priority"] = list(order_pool["selection_priority"])
        self.rules = merge_rule_overrides(normalized_rules, overrides)
        self.parameters = dict(self.rules.get("parameters") or {})
        self.material_payment_timing = material_payment_timing

    @classmethod
    def from_rules_file(cls, path: Path, **kwargs: Any) -> "XADynamics":
        return cls(json.loads(path.read_text(encoding="utf-8")), **kwargs)

    def initial_state(
        self,
        team_id: str,
        match_id: str = "LX_XA",
        initial_state: Mapping[str, Any] | None = None,
        initial_orders: list[Mapping[str, Any]] | None = None,
    ) -> XAState:
        initial_cash = float(self.parameters.get("initial_cash_wan", 675))
        configured = dict(self.rules.get("initial_state") or {})
        configured.update(dict(initial_state or {}))
        state = XAState(
            match_id=match_id,
            team_id=team_id,
            cash_wan=float(configured.get("cash_wan", initial_cash)),
            owner_equity_wan=float(configured.get("owner_equity_wan", configured.get("cash_wan", initial_cash))),
            debt_wan=float(configured.get("debt_wan", 0.0)),
            material_inventory=dict(configured.get("material_inventory") or {key: 0.0 for key in self.parameters.get("materials", {})}),
            product_inventory=dict(configured.get("product_inventory") or {key: 0.0 for key in self.parameters.get("products", {})}),
            markets=list(configured.get("markets") or []),
            products=list(configured.get("products") or []),
            iso=list(configured.get("iso") or []),
            factories=copy.deepcopy(list(configured.get("factories") or [])),
            production_lines=copy.deepcopy(list(configured.get("production_lines") or [])),
            available_orders=copy.deepcopy(list(initial_orders or configured.get("available_orders") or [])),
        )
        return state

    def legal_actions(self, state: XAState, public_context: Mapping[str, Any] | None = None) -> tuple[Mapping[str, Any], ...]:
        if state.bankrupt:
            return ({"action_type": "hold"},)
        names = ("short_loan_borrow", "material_order", "advertising", "develop_product", "develop_market", "develop_iso", "buy_workshop", "rent_workshop", "buy_product_line", "production", "order_delivery")
        return ({"action_type": "hold"}, {"action_type": "advance_quarter"}, *( {"action_type": name} for name in names))

    def apply(self, state: XAState, action: Mapping[str, Any], public_context: Mapping[str, Any] | None = None) -> XATransition:
        action_type = action.get("action_type")
        parameters = dict(action.get("parameters") or {})
        if state.bankrupt:
            if action_type in {"hold", "advance_quarter"}:
                return XATransition("success", copy.deepcopy(state), {"event_type": "bankrupt_hold", "cash_effect_wan": 0.0})
            return self._reject(state, "企业已经破产")
        if action_type in {"hold", "advance_quarter"}:
            return XATransition("success", copy.deepcopy(state), {"event_type": action_type, "cash_effect_wan": 0.0})
        handlers = {
            "short_loan_borrow": self._short_loan,
            "material_order": self._material_order,
            "develop_product": lambda current, values: self._development(current, "product", values),
            "develop_market": lambda current, values: self._development(current, "market", values),
            "develop_iso": lambda current, values: self._development(current, "iso", values),
            "buy_workshop": lambda current, values: self._workshop(current, "buy", values),
            "rent_workshop": lambda current, values: self._workshop(current, "rent", values),
            "buy_product_line": self._product_line,
            "advertising": self._advertise,
            "production": self._production,
            "order_delivery": self._delivery,
        }
        if action_type in {"select_order", "auction_bid", "order_award"}:
            return self._reject(state, "共享订单分配需要 OrderAllocationResolver 插件")
        handler = handlers.get(action_type)
        return handler(state, parameters) if handler else self._reject(state, f"XA Dynamics 未实现动作：{action_type}")

    def advance_quarter(self, state: XAState) -> XATransition:
        if state.bankrupt:
            return XATransition("success", copy.deepcopy(state), {"event_type": "bankrupt_hold", "from_period": state.period, "to_period": state.period, "cash_effect_wan": 0.0})
        next_state = copy.deepcopy(state)
        fee = float(self.parameters.get("management_fee_per_quarter_wan", 14))
        charged = self._charge(next_state, fee, "quarterly_management_fee")
        if charged is not None:
            return charged
        next_index = state.period_index + 1
        next_state.year, next_state.quarter = _period_from_index(next_index)
        event: dict[str, Any] = {"event_type": "quarter_advanced", "from_period": state.period, "to_period": next_state.period, "cash_effect_wan": -fee, "settlements": []}

        for order in list(next_state.pending_material_orders):
            if order["arrival_period_index"] <= next_index:
                if self.material_payment_timing == "arrival":
                    charged = self._charge(next_state, order["total_cost_wan"], "material_arrival_payment")
                    if charged is not None:
                        return charged
                    event["cash_effect_wan"] -= order["total_cost_wan"]
                next_state.material_inventory[order["material_id"]] += order["quantity"]
                next_state.pending_material_orders.remove(order)
                event["settlements"].append({"type": "material_arrival", "order_id": order["order_id"]})

        for item in list(next_state.pending_development):
            item["remaining_quarters"] -= 1
            if item["remaining_quarters"] <= 0:
                bucket = next_state.products if item["kind"] == "product" else next_state.markets if item["kind"] == "market" else next_state.iso
                if item["target"] not in bucket:
                    bucket.append(item["target"])
                next_state.pending_development.remove(item)
                event["settlements"].append({"type": "qualification_completed", "kind": item["kind"], "target": item["target"]})

        for line in list(next_state.pending_lines):
            line["remaining_install_quarters"] -= 1
            if line["remaining_install_quarters"] <= 0:
                line["status"] = "ready"
                next_state.production_lines.append(line)
                next_state.pending_lines.remove(line)
                event["settlements"].append({"type": "production_line_ready", "line_id": line["line_id"]})

        for job in list(next_state.pending_production):
            job["remaining_quarters"] -= 1
            if job["remaining_quarters"] <= 0:
                next_state.product_inventory[job["product_id"]] += job["quantity"]
                next_state.pending_production.remove(job)
                event["settlements"].append({"type": "production_completed", "job_id": job["job_id"]})

        for loan in list(next_state.short_loans):
            if loan["due_period_index"] <= next_index:
                charged = self._charge(next_state, loan["amount_due_wan"], "short_loan_maturity")
                if charged is not None:
                    return charged
                next_state.debt_wan -= loan["principal_wan"]
                event["cash_effect_wan"] -= loan["amount_due_wan"]
                next_state.short_loans.remove(loan)
                event["settlements"].append({"type": "short_loan_repaid", "loan_id": loan["loan_id"]})

        for receivable in list(next_state.receivables):
            if receivable["due_period_index"] <= next_index:
                next_state.cash_wan += receivable["amount_wan"]
                next_state.receivables.remove(receivable)
                event["cash_effect_wan"] += receivable["amount_wan"]
                event["settlements"].append({"type": "receivable_collected", "receivable_id": receivable["receivable_id"]})
        bankrupt, reasons = is_bankrupt(next_state.cash_wan, next_state.owner_equity_wan, self.rules)
        if bankrupt:
            next_state.bankrupt = True
            next_state.accounting_status = "bankrupt"
            event["bankruptcy"] = {"reasons": list(reasons)}
        next_state.event_log.append(event)
        return XATransition("success", next_state, event, warnings=("XA v0.1 未实现完整折旧、税费和订单分配结算",))

    def _short_loan(self, state: XAState, values: Mapping[str, Any]) -> XATransition:
        principal, term = _amount(values.get("principal_wan")), values.get("term_quarters", values.get("term"))
        if principal is None or principal <= 0 or not isinstance(term, int) or term <= 0:
            return self._reject(state, "short_loan_borrow 需要正数 principal_wan 和正整数 term_quarters")
        rate = float((self.parameters.get("short_loan") or {}).get("rate", 0.05))
        interest = principal * rate * term / 4
        next_state = copy.deepcopy(state)
        next_state.cash_wan += principal
        next_state.debt_wan += principal
        loan = {"loan_id": f"SL-{len(next_state.short_loans) + 1}", "principal_wan": principal, "interest_wan": interest, "amount_due_wan": principal + interest, "due_period_index": state.period_index + term}
        next_state.short_loans.append(loan)
        event = {"event_type": "short_loan_borrowed", "cash_effect_wan": principal, "loan": loan}
        next_state.event_log.append(event)
        return XATransition("success", next_state, event)

    def _material_order(self, state: XAState, values: Mapping[str, Any]) -> XATransition:
        materials, rules = values.get("materials"), self.parameters.get("materials") or {}
        if not isinstance(materials, Mapping) or not materials:
            return self._reject(state, "material_order 需要 materials")
        next_state, created = copy.deepcopy(state), []
        for material_id, raw_quantity in sorted(materials.items()):
            quantity, rule = _amount(raw_quantity), rules.get(material_id)
            if quantity is None or quantity <= 0 or not rule:
                return self._reject(state, f"无效原料订购：{material_id}")
            price, lead = float(rule["price_wan"]), int(rule.get("lead_quarters", 0))
            created.append({"order_id": f"MO-{len(next_state.pending_material_orders) + len(created) + 1}", "material_id": material_id, "quantity": quantity, "unit_price_wan": price, "total_cost_wan": quantity * price, "arrival_period_index": state.period_index + lead})
        next_state.pending_material_orders.extend(created)
        event = {"event_type": "material_ordered", "cash_effect_wan": 0.0, "orders": created}
        next_state.event_log.append(event)
        return XATransition("success", next_state, event)

    def _development(self, state: XAState, kind: str, values: Mapping[str, Any]) -> XATransition:
        target = values.get("target") or values.get("product_id") or values.get("market") or values.get("iso")
        collection_key = {"product": "products", "market": "markets", "iso": "iso"}[kind]
        rule = (self.parameters.get(collection_key) or {}).get(target)
        bucket = state.products if kind == "product" else state.markets if kind == "market" else state.iso
        if not isinstance(target, str) or not rule:
            return self._reject(state, "开发动作缺少有效 target")
        if target in bucket or any(item["kind"] == kind and item["target"] == target for item in state.pending_development):
            return self._reject(state, f"{target} 已完成或正在开发")
        if kind == "product":
            fee, duration = float(rule["development_wan_per_quarter"]), int(rule["quarters"])
        else:
            fee, duration = float(rule["fee_wan_per_year"]) / 4, int(rule["years"]) * 4
        next_state = copy.deepcopy(state)
        charged = self._charge(next_state, fee, f"{kind}_development")
        if charged is not None:
            return charged
        item = {"kind": kind, "target": target, "remaining_quarters": duration}
        next_state.pending_development.append(item)
        event = {"event_type": f"{kind}_development_started", "target": target, "cash_effect_wan": -fee, "remaining_quarters": duration}
        next_state.event_log.append(event)
        return XATransition("success", next_state, event)

    def _workshop(self, state: XAState, mode: str, values: Mapping[str, Any]) -> XATransition:
        name = values.get("factory") or values.get("name")
        rule = (self.parameters.get("factories") or {}).get(name)
        if not isinstance(name, str) or not rule:
            return self._reject(state, "厂房动作需要有效 factory")
        price = float(rule["purchase_wan"]) if mode == "buy" else float(rule["rent_wan_per_year"]) / 4
        next_state = copy.deepcopy(state)
        charged = self._charge(next_state, price, f"{mode}_workshop")
        if charged is not None:
            return charged
        factory = {"factory_id": f"F-{len(next_state.factories) + 1}", "name": name, "mode": "purchased" if mode == "buy" else "rented", "capacity": int(rule["capacity"])}
        next_state.factories.append(factory)
        event = {"event_type": f"{mode}_workshop", "cash_effect_wan": -price, "factory": factory}
        next_state.event_log.append(event)
        return XATransition("success", next_state, event)

    def _product_line(self, state: XAState, values: Mapping[str, Any]) -> XATransition:
        line_type = values.get("line_type") or values.get("name")
        rule = (self.parameters.get("production_lines") or {}).get(line_type)
        if not isinstance(line_type, str) or not rule:
            return self._reject(state, "生产线动作需要有效 line_type")
        investment = float(rule.get("investment_wan_per_quarter", rule.get("investment_wan", 0)))
        install = int(rule.get("install_quarters", 0))
        next_state = copy.deepcopy(state)
        charged = self._charge(next_state, investment, "production_line_order")
        if charged is not None:
            return charged
        line = {"line_id": f"L-{len(next_state.production_lines) + len(next_state.pending_lines) + 1}", "line_type": line_type, "product_id": values.get("product_id"), "status": "ready" if install == 0 else "installing", "remaining_install_quarters": install}
        (next_state.production_lines if install == 0 else next_state.pending_lines).append(line)
        event = {"event_type": "production_line_ordered", "cash_effect_wan": -investment, "line": line}
        next_state.event_log.append(event)
        return XATransition("success", next_state, event)

    def _advertise(self, state: XAState, values: Mapping[str, Any]) -> XATransition:
        amount = _amount(values.get("amount_wan"))
        if amount is None or amount <= 0:
            return self._reject(state, "advertising 需要正数 amount_wan")
        next_state = copy.deepcopy(state)
        charged = self._charge(next_state, amount, "advertising")
        if charged is not None:
            return charged
        key = f"{values.get('market', 'unknown')}:{values.get('product_id', 'unknown')}"
        next_state.advertising[key] = next_state.advertising.get(key, 0.0) + amount
        event = {"event_type": "advertising", "cash_effect_wan": -amount, "key": key, "amount_wan": amount}
        next_state.event_log.append(event)
        return XATransition("success", next_state, event)

    def _production(self, state: XAState, values: Mapping[str, Any]) -> XATransition:
        product_id, quantity = values.get("product_id"), _amount(values.get("quantity", 1))
        product_rule = (self.parameters.get("products") or {}).get(product_id)
        line = next((item for item in state.production_lines if item.get("product_id") in {None, product_id} and item.get("status") == "ready"), None)
        if not isinstance(product_id, str) or quantity is None or quantity <= 0 or product_id not in state.products or not product_rule:
            return self._reject(state, "production 需要已完成产品资格和正数 quantity")
        if line is None:
            return self._reject(state, "没有可用生产线")
        next_state = copy.deepcopy(state)
        for material_id, units in (product_rule.get("bom") or {}).items():
            if material_id.startswith("R") and next_state.material_inventory.get(material_id, 0.0) < float(units) * quantity:
                return self._reject(state, f"原料不足：{material_id}")
        for material_id, units in (product_rule.get("bom") or {}).items():
            if material_id.startswith("R"):
                next_state.material_inventory[material_id] -= float(units) * quantity
        fee = float(product_rule["process_wan"]) * quantity
        charged = self._charge(next_state, fee, "production")
        if charged is not None:
            return charged
        line_rule = (self.parameters.get("production_lines") or {}).get(line["line_type"], {})
        job = {"job_id": f"P-{len(next_state.pending_production) + 1}", "product_id": product_id, "quantity": quantity, "remaining_quarters": int(line_rule.get("production_quarters", 1))}
        next_state.pending_production.append(job)
        event = {"event_type": "production_started", "cash_effect_wan": -fee, "job": job, "line_id": line["line_id"]}
        next_state.event_log.append(event)
        return XATransition("success", next_state, event)

    def _delivery(self, state: XAState, values: Mapping[str, Any]) -> XATransition:
        product_id, quantity, amount, term = values.get("product_id"), _amount(values.get("quantity")), _amount(values.get("total_amount_wan")), values.get("receivable_term_quarters", 0)
        if not isinstance(product_id, str) or quantity is None or quantity <= 0 or amount is None or amount <= 0 or not isinstance(term, int) or term < 0:
            return self._reject(state, "order_delivery 参数不完整")
        if state.product_inventory.get(product_id, 0.0) < quantity:
            return self._reject(state, "产成品库存不足")
        next_state = copy.deepcopy(state)
        next_state.product_inventory[product_id] -= quantity
        if term == 0:
            next_state.cash_wan += amount
        else:
            next_state.receivables.append({"receivable_id": f"AR-{len(next_state.receivables) + 1}", "amount_wan": amount, "due_period_index": state.period_index + term})
        next_state.cumulative_revenue_wan += amount
        event = {"event_type": "order_delivered", "cash_effect_wan": amount if term == 0 else 0.0, "product_id": product_id, "quantity": quantity, "amount_wan": amount, "term_quarters": term}
        next_state.delivered_orders.append(event)
        next_state.event_log.append(event)
        return XATransition("success", next_state, event)

    @staticmethod
    def _charge(state: XAState, amount: float, reason: str) -> XATransition | None:
        if state.cash_wan - amount < 0:
            return XATransition("rejected", state, violations=(f"现金不足：{reason} 需要 {amount}W，当前 {state.cash_wan}W",))
        state.cash_wan -= amount
        state.cumulative_expense_wan += amount
        return None

    @staticmethod
    def _reject(state: XAState, message: str) -> XATransition:
        return XATransition("rejected", state, violations=(message,))


class XACounterfactualArena(MultiAgentEnvironment):
    """Run deterministic joint actions and re-run all enterprises after a change.

    ``initial_states`` and ``initial_orders`` make the environment reusable for
    different team counts and order pools.  ``replay`` is the counterfactual
    entry point: actions before the changed period are replayed, then the
    alternative action is applied and every later settlement is recomputed.
    """

    def __init__(
        self,
        dynamics: XADynamics,
        agent_ids: tuple[str, ...] | None = None,
        public_context: Mapping[str, Any] | None = None,
        *,
        initial_states: Mapping[str, Mapping[str, Any]] | None = None,
        initial_orders: list[Mapping[str, Any]] | None = None,
        max_periods: int = 20,
        order_engine: OrderAllocationEngine | None = None,
    ) -> None:
        self.dynamics = dynamics
        configured_ids = tuple(agent_ids or tuple((initial_states or {}).keys()))
        if not configured_ids:
            configured_ids = tuple(str(item) for item in (dynamics.rules.get("participants") or {}).get("team_ids", ()))
        if not configured_ids:
            raise ValueError("agent_ids or initial_states or rules.participants.team_ids is required")
        self._agent_ids = tuple(sorted(configured_ids))
        self.public_context = dict(public_context or {})
        self.initial_state_overrides = {str(key): dict(value) for key, value in (initial_states or {}).items()}
        self.initial_orders = copy.deepcopy(list(initial_orders or self.public_context.get("initial_orders") or []))
        self.max_periods = int(max_periods)
        if order_engine is None:
            traditional_profile = bool((dynamics.rules.get("global_rule_services") or {}).get("traditional_profile"))
            if traditional_profile:
                order_engine = OrderAllocationEngine(TraditionalXAOrderPolicy())
                self.order_engine = order_engine
                self.states: dict[str, XAState] = {}
                self.terminated = False
                return
            source_hierarchy = tuple((dynamics.parameters.get("selection_priority") or ()))
            aliases = {
                "prior_market_leader": "market_leader",
                "market_product_advertising": "product_advertising",
                "market_total_advertising": "market_advertising",
                "market_sales_rank": "sales_rank",
                "advertising_submission_time": "submitted_at",
            }
            hierarchy = tuple(aliases.get(item, item) for item in source_hierarchy) or ("market_leader", "product_advertising", "market_advertising", "sales_rank", "submitted_at")
            order_engine = OrderAllocationEngine(SelectionPriorityPolicy(hierarchy))
        self.order_engine = order_engine
        self.states: dict[str, XAState] = {}
        self.terminated = False

    @property
    def agent_ids(self) -> tuple[str, ...]:
        return self._agent_ids

    def reset(self, seed: int | None = None) -> Mapping[str, AgentObservation]:
        self.states = {
            agent_id: self.dynamics.initial_state(
                agent_id,
                initial_state=self.initial_state_overrides.get(agent_id),
                initial_orders=self.initial_orders,
            )
            for agent_id in self.agent_ids
        }
        self.terminated = False
        return self._observations()

    def _observations(self) -> dict[str, AgentObservation]:
        traditional = bool((self.dynamics.rules.get("global_rule_services") or {}).get("traditional_profile"))
        observations = {}
        for agent_id in self.agent_ids:
            state = self.states[agent_id]
            if traditional:
                public = traditional_visibility_context(state.period, public_context={**self.public_context, "period": state.period})
                public.update({"agent_ids": self.agent_ids, "information_policy": "traditional_year_start_public"})
            else:
                public = {"period": state.period, "agent_ids": self.agent_ids, "public_context": self.public_context, "information_policy": "private_state_isolation"}
            observations[agent_id] = AgentObservation(state.match_id, agent_id, state.period_index, state.period, state.to_dict(), public, self.dynamics.legal_actions(state, self.public_context))
        return observations

    def step(self, actions: Mapping[str, Mapping[str, Any]]) -> ArenaStep:
        if self.terminated:
            raise RuntimeError("arena is terminated; call reset()")
        if set(actions) != set(self.agent_ids):
            raise ValueError("one action is required for every agent")
        next_states: dict[str, XAState] = {agent_id: copy.deepcopy(state) for agent_id, state in self.states.items()}
        rewards, infos = {}, {}
        allocation_events: dict[str, dict[str, Any]] = {}
        grouped_claims: dict[str, list[dict[str, Any]]] = {}
        grouped_orders: dict[str, Mapping[str, Any]] = {}
        for agent_id, action in actions.items():
            if action.get("action_type") not in {"select_order", "auction_bid"}:
                continue
            values = dict(action.get("parameters") or {})
            order_id = str(values.get("order_id") or "")
            order = next((item for item in next_states[agent_id].available_orders if str(item.get("order_id")) == order_id), None)
            if order is None:
                order = next((item for item in self.initial_orders if str(item.get("order_id")) == order_id), None)
            if not order_id or order is None:
                raise ValueError(f"{agent_id}: 订单 {order_id or '<missing>'} 不在可用初始订单池中")
            grouped_orders[order_id] = order
            grouped_claims.setdefault(order_id, []).append({**values, "team_id": agent_id})
        if grouped_orders:
            decisions = self.order_engine.allocate(list(grouped_orders.values()), grouped_claims, self.public_context)
            for decision in decisions:
                allocation_events[decision.order_id] = {
                    "order_id": decision.order_id,
                    "winner_team_id": decision.winner_team_id,
                    "policy_id": decision.policy_id,
                    "reason": decision.reason,
                    "contenders": list(decision.contenders),
                    "trace": dict(decision.trace),
                }
                if decision.winner_team_id:
                    winner_state = next_states[decision.winner_team_id]
                    order = grouped_orders[decision.order_id]
                    winner_state.assigned_orders.append(copy.deepcopy(dict(order)))
                    for participant_state in next_states.values():
                        participant_state.available_orders = [item for item in participant_state.available_orders if str(item.get("order_id")) != decision.order_id]
        for agent_id in self.agent_ids:
            before = self.states[agent_id]
            action = actions[agent_id]
            if action.get("action_type") in {"select_order", "auction_bid"}:
                order_id = str((action.get("parameters") or {}).get("order_id") or "")
                allocation = allocation_events[order_id]
                transition = XATransition("success", next_states[agent_id], {"event_type": "order_claim_submitted", **allocation})
            else:
                transition = self.dynamics.apply(before, action, self.public_context)
                if transition.status != "success":
                    raise ValueError(f"{agent_id}: {'; '.join(transition.violations)}")
            settled = self.dynamics.advance_quarter(transition.state)
            if settled.status != "success":
                raise ValueError(f"{agent_id}: {'; '.join(settled.violations)}")
            next_states[agent_id] = settled.state
            rewards[agent_id] = settled.state.cash_wan - before.cash_wan
            infos[agent_id] = {"action_event": dict(transition.event), "settlement_event": dict(settled.event), "warnings": list(settled.warnings), "order_allocation": allocation_events.get(str((action.get("parameters") or {}).get("order_id")))}
        self.states = next_states
        self.terminated = all(state.period_index >= self.max_periods - 1 for state in self.states.values())
        return ArenaStep(self._observations(), rewards, self.terminated, infos)

    def replay(
        self,
        action_schedule: Mapping[int, Mapping[str, Mapping[str, Any]]],
        *,
        changed_period_index: int | None = None,
        alternative_actions: Mapping[str, Mapping[str, Any]] | None = None,
        seed: int | None = None,
    ) -> dict[str, Any]:
        """Replay a joint schedule and return the full counterfactual trace.

        If ``changed_period_index`` and ``alternative_actions`` are provided,
        the alternative replaces the historical action at that period; all
        following periods are then executed from the changed states.
        """

        observations = self.reset(seed=seed)
        trace: list[dict[str, Any]] = []
        while not self.terminated:
            period_index = next(iter(observations.values())).period_index
            actions = dict(action_schedule.get(period_index) or {
                agent_id: {"action_type": "hold"} for agent_id in self.agent_ids
            })
            if changed_period_index is not None and period_index == changed_period_index and alternative_actions is not None:
                actions.update({agent_id: dict(action) for agent_id, action in alternative_actions.items()})
            result = self.step(actions)
            trace.append({
                "period_index": period_index,
                "actions": copy.deepcopy(actions),
                "rewards": dict(result.rewards),
                "infos": copy.deepcopy(dict(result.infos)),
                "states": {agent_id: observation.private_state for agent_id, observation in result.observations.items()},
            })
            observations = result.observations
        return {
            "dynamics_version": XA_DYNAMICS_VERSION,
            "counterfactual": changed_period_index is not None,
            "changed_period_index": changed_period_index,
            "agent_ids": list(self.agent_ids),
            "initial_order_count": len(self.initial_orders),
            "trace": trace,
            "final_states": {agent_id: observation.private_state for agent_id, observation in observations.items()},
        }
