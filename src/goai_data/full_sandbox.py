"""Complete candidate financial sandbox for configurable multi-team matches.

Any normalized match rule pack can be used as the generation template.  Rules
and orders produced by this module are explicitly simulated and are never
promoted to official historical facts.  The accounting kernel uses
double-entry-compatible state transitions: cash, receivables, inventories,
fixed assets, debt and equity remain balanced.
"""

from __future__ import annotations

import copy
import hashlib
import json
import random
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .decision_system import AgentObservation, ArenaStep, MultiAgentEnvironment
from .global_rules import development_potential, rank_final_states
from .order_allocation import OrderAllocationEngine
from .traditional_rules import TraditionalXAOrderPolicy, advertising_opportunities


FULL_SANDBOX_VERSION = "full_financial_sandbox_v1.0"
COMPLEXITY_PROFILES: dict[str, dict[str, Any]] = {
    "small": {
        "team_count": 4,
        "orders_per_year": 15,
        "auction_ratio": 0.08,
        "variability": 0.10,
        "initial_cash_multiplier": 1.0,
        "max_order_claims_per_quarter": 1,
    },
    "standard": {
        "team_count": 20,
        "orders_per_year": 60,
        "auction_ratio": 0.12,
        "variability": 0.15,
        "initial_cash_multiplier": 1.15,
        "max_order_claims_per_quarter": 2,
    },
    "large": {
        "team_count": 24,
        "orders_per_year": 100,
        "auction_ratio": 0.18,
        "variability": 0.20,
        "initial_cash_multiplier": 3.0,
        "max_order_claims_per_quarter": 3,
    },
    "stress": {
        "team_count": 32,
        "orders_per_year": 160,
        "auction_ratio": 0.25,
        "variability": 0.25,
        "initial_cash_multiplier": 4.0,
        "max_order_claims_per_quarter": 4,
    },
}
DEFAULT_PHASE_ORDER = (
    "management_fee",
    "material_arrival",
    "development_installments",
    "capacity_and_production_completion",
    "loan_and_receivable_settlement",
    "order_deadline_and_penalty",
    "year_end_maintenance_rent_depreciation_tax_reports",
)


def _candidate_financial_rules(parameters: Mapping[str, Any]) -> dict[str, Any]:
    """Return deterministic settlement services for rules not unique in XA data."""

    return {
        "version": FULL_SANDBOX_VERSION,
        "phase_order": list(DEFAULT_PHASE_ORDER),
        "bankruptcy_check_after_each_phase": True,
        "factory_depreciation_years": 10,
        "production_line_depreciation_years": 5,
        "factory_disposal_book_value_rate": 0.70,
        "production_line_disposal_book_value_rate": 0.60,
        "emergency_material_price_multiplier": 1.50,
        "receivable_discount_rates": copy.deepcopy(parameters.get("receivable_discount") or {"terms_1_2": 0.08, "terms_3_4": 0.09}),
        "long_loan_interest_timing": "year_end",
        "short_loan_interest_timing": "maturity",
        "tax_timing": "year_end",
        "report_timing": "year_end_after_tax",
        "auction_bid_fee_wan": 10,
        "auction_batch_size": 3,
        "auction_payment_mode": "fixed_order_price",
        "unclaimed_orders_carry_forward": False,
        "provenance": "candidate_traditional_sandbox_service",
    }


def _number(value: Any, default: float = 0.0) -> float:
    return float(value) if isinstance(value, (int, float)) else default


def _period_index(year: int, quarter: int) -> int:
    return (year - 1) * 4 + (quarter - 1)


def _period_from_index(index: int) -> tuple[int, int]:
    return index // 4 + 1, index % 4 + 1


def _period_label(index: int) -> str:
    year, quarter = _period_from_index(index)
    return f"Y{year}Q{quarter}"


def _stable_id(prefix: str, *parts: Any) -> str:
    digest = hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()[:10]
    return f"{prefix}-{digest}"


def _jitter(rng: random.Random, value: float, spread: float, *, minimum: float = 0.0, digits: int = 2) -> float:
    return round(max(minimum, value * rng.uniform(1.0 - spread, 1.0 + spread)), digits)


def generate_simulated_rule_pack(
    base_rules: Mapping[str, Any],
    *,
    seed: int,
    match_id: str = "SIM",
    variability: float = 0.15,
    team_count: int = 20,
    source_match_id: str | None = None,
    source_rule_path: str | None = None,
    initial_cash_multiplier: float = 1.0,
    complexity_profile: str = "standard",
) -> dict[str, Any]:
    """Generate a reproducible rule pack from any normalized match rule pack."""

    rng = random.Random(seed)
    rules = copy.deepcopy(dict(base_rules))
    original_parameters = copy.deepcopy(rules.get("parameters") or {})
    params = rules.setdefault("parameters", {})
    if complexity_profile not in COMPLEXITY_PROFILES:
        raise ValueError(f"unknown complexity profile: {complexity_profile}")
    if initial_cash_multiplier <= 0:
        raise ValueError("initial_cash_multiplier must be positive")
    params["initial_cash_wan"] = round(_jitter(rng, _number(params.get("initial_cash_wan"), 675), variability, minimum=100) * initial_cash_multiplier, 0)
    params["management_fee_per_quarter_wan"] = round(_jitter(rng, _number(params.get("management_fee_per_quarter_wan"), 14), variability, minimum=1), 0)
    params["tax_rate"] = round(rng.uniform(0.20, 0.30), 4)
    params["default_penalty_rate"] = round(rng.uniform(0.15, 0.30), 4)
    for factory in (params.get("factories") or {}).values():
        factory["purchase_wan"] = round(_jitter(rng, _number(factory.get("purchase_wan")), variability, minimum=1), 0)
        factory["rent_wan_per_year"] = round(_jitter(rng, _number(factory.get("rent_wan_per_year")), variability, minimum=1), 0)
    for line in (params.get("production_lines") or {}).values():
        line["investment_wan"] = round(_jitter(rng, _number(line.get("investment_wan")), variability, minimum=0), 0)
        line["maintenance_wan_per_year"] = round(_jitter(rng, _number(line.get("maintenance_wan_per_year")), variability, minimum=0), 0)
    for product in (params.get("products") or {}).values():
        product["process_wan"] = round(_jitter(rng, _number(product.get("process_wan")), variability, minimum=1), 0)
        product["development_wan_per_quarter"] = round(_jitter(rng, _number(product.get("development_wan_per_quarter")), variability, minimum=1), 0)
        product["direct_cost_wan"] = round(_jitter(rng, _number(product.get("direct_cost_wan")), variability, minimum=1), 0)
    for material in (params.get("materials") or {}).values():
        material["price_wan"] = round(_jitter(rng, _number(material.get("price_wan")), variability, minimum=1), 0)
    rules["match_id"] = match_id
    rules["rule_pack_id"] = f"{match_id}_simulated_rules_seed_{seed}"
    rules["parent_rule_pack_id"] = base_rules.get("rule_pack_id")
    rules["binding_status"] = "simulated_configurable_rule_pack"
    rules["provenance"] = "simulated"
    rules["participants"] = {"count": team_count, "team_ids": [f"{match_id}{index:02d}" for index in range(1, team_count + 1)]}
    rules["financial_rules"] = _candidate_financial_rules(params)
    changes = []
    for key in ("initial_cash_wan", "management_fee_per_quarter_wan", "tax_rate", "default_penalty_rate"):
        if original_parameters.get(key) != params.get(key):
            changes.append({"path": f"parameters.{key}", "before": original_parameters.get(key), "after": params.get(key)})
    for group, numeric_keys in {
        "factories": ("purchase_wan", "rent_wan_per_year"),
        "production_lines": ("investment_wan", "maintenance_wan_per_year"),
        "products": ("process_wan", "development_wan_per_quarter", "direct_cost_wan"),
        "materials": ("price_wan",),
    }.items():
        for name, current in (params.get(group) or {}).items():
            previous = (original_parameters.get(group) or {}).get(name, {})
            for key in numeric_keys:
                if previous.get(key) != current.get(key):
                    changes.append({"path": f"parameters.{group}.{name}.{key}", "before": previous.get(key), "after": current.get(key)})
    source_id = source_match_id or str(base_rules.get("match_id") or "unknown")
    rules["generation"] = {
        "seed": seed,
        "variability": variability,
        "complexity_profile": complexity_profile,
        "initial_cash_multiplier": initial_cash_multiplier,
        "source_match_id": source_id,
        "source_rule_pack_id": base_rules.get("rule_pack_id"),
        "source_rule_path": source_rule_path,
        "reference": f"normalized rule pack for {source_id}",
        "parameter_changes": changes,
        "provenance": "simulated",
    }
    return rules


def build_fixed_xa_rule_pack(
    base_rules: Mapping[str, Any],
    *,
    match_id: str = "SIM_XA_FIXED",
    team_count: int = 27,
    seed: int = 0,
    source_rule_path: str | None = None,
) -> dict[str, Any]:
    """Create an executable pack with exact XA parameters and fixed services.

    Formal XA parameters are copied byte-for-byte at the value level.  Only the
    match identity, participants and explicit candidate settlement services are
    added.  The seed controls orders and policies, never the rule parameters.
    """

    rules = copy.deepcopy(dict(base_rules))
    parameters = copy.deepcopy(dict(base_rules.get("parameters") or {}))
    if not parameters:
        raise ValueError("fixed XA simulation requires a normalized parameters object")
    required = {
        "initial_cash_wan",
        "management_fee_per_quarter_wan",
        "tax_rate",
        "default_penalty_rate",
        "factories",
        "production_lines",
        "products",
        "markets",
        "iso",
        "materials",
    }
    missing = sorted(required - set(parameters))
    if missing:
        raise ValueError(f"fixed XA rules are missing parameters: {', '.join(missing)}")
    source_match_id = str(base_rules.get("match_id") or "LX_XA")
    source_rule_pack_id = str(base_rules.get("rule_pack_id") or "unknown")
    rules.update(
        {
            "match_id": match_id,
            "rule_pack_id": f"{match_id}_fixed_{source_rule_pack_id}",
            "parent_rule_pack_id": source_rule_pack_id,
            "binding_status": "simulation_with_exact_XA_parameters",
            "provenance": "derived_rule_pack_with_observed_XA_parameters",
            "parameters": parameters,
            "participants": {
                "count": team_count,
                "team_ids": [f"{match_id}{index:02d}" for index in range(1, team_count + 1)],
            },
            "financial_rules": _candidate_financial_rules(parameters),
            "generation": {
                "seed": seed,
                "mode": "fixed_XA_rules_random_orders",
                "source_match_id": source_match_id,
                "source_rule_pack_id": source_rule_pack_id,
                "source_rule_path": source_rule_path,
                "parameter_changes": [],
                "parameters_provenance": "observed_formal_XA",
                "settlement_services_provenance": "candidate_traditional_sandbox_service",
            },
        }
    )
    return rules


def generate_global_orders(
    rules: Mapping[str, Any],
    *,
    seed: int,
    orders_per_year: int = 60,
    years: Sequence[int] = (2, 3, 4, 5),
    auction_ratio: float = 0.08,
    complexity: str = "standard",
) -> list[dict[str, Any]]:
    """Generate a complete reproducible unallocated global order pool."""

    if complexity not in COMPLEXITY_PROFILES:
        raise ValueError(f"unknown complexity profile: {complexity}")
    if orders_per_year <= 0:
        raise ValueError("orders_per_year must be positive")
    if not 0 <= auction_ratio <= 1:
        raise ValueError("auction_ratio must be between 0 and 1")
    rng = random.Random(seed)
    params = rules.get("parameters", rules)
    markets = list((params.get("markets") or {}).keys()) or ["本地"]
    products = list((params.get("products") or {}).keys()) or ["P1"]
    iso_values = ["-"] + list((params.get("iso") or {}).keys())
    output: list[dict[str, Any]] = []
    quantity_ranges = {
        "small": ((1, 2), (1, 4)),
        "standard": ((1, 3), (2, 7)),
        "large": ((1, 4), (2, 9)),
        "stress": ((2, 5), (3, 12)),
    }
    entry_range, advanced_range = quantity_ranges[complexity]
    segments = ("价格敏感型", "稳定供货型", "高质量型", "战略客户型")
    priorities = ("普通", "加急", "关键", "长期")
    combinations = [(market, product) for market in markets for product in products]
    for year in years:
        planned: list[tuple[str, str]] = combinations[:]
        rng.shuffle(planned)
        while len(planned) < orders_per_year:
            planned.append((rng.choice(markets), rng.choice(products)))
        for index, (planned_market, planned_product) in enumerate(planned[:orders_per_year], 1):
            entry_level = rng.random() < (0.30 if complexity in {"large", "stress"} else 0.38)
            product = products[0] if entry_level and rng.random() < 0.75 else planned_product
            market = markets[0] if entry_level and rng.random() < 0.75 else planned_market
            quantity = rng.randint(*(entry_range if entry_level else advanced_range))
            direct_cost = _number((params.get("products") or {}).get(product, {}).get("direct_cost_wan"), 20)
            market_factor = 1.0 + 0.08 * markets.index(market)
            margin_bounds = (1.25, 2.65) if complexity in {"large", "stress"} else (1.35, 2.30)
            margin = rng.uniform(*margin_bounds)
            total = round(max(direct_cost * quantity * market_factor * margin, direct_cost * quantity + 1), 0)
            quarter = rng.randint(1, 4)
            delivery_term = rng.randint(2 if complexity in {"large", "stress"} else 1, 6 if complexity == "stress" else (5 if complexity == "large" else 4))
            due_index = min(19, _period_index(year, quarter) + delivery_term)
            order_type = "竞单" if rng.random() < auction_ratio else "选单"
            output.append({
                "match_id": rules.get("match_id", "SIM"),
                "order_id": f"{rules.get('match_id', 'SIM')}-{year}-{index:04d}",
                "year": year,
                "release_period": f"Y{year}Q{quarter}",
                "release_period_index": _period_index(year, quarter),
                "due_period": _period_label(due_index),
                "due_period_index": due_index,
                "market": market,
                "product": product,
                "iso": "-" if entry_level else rng.choice(iso_values),
                "quantity": float(quantity),
                "total_price_wan": float(total),
                "delivery_term_quarters": delivery_term,
                "receivable_term_quarters": rng.randint(0, 4),
                "order_type": order_type,
                "customer_segment": rng.choice(segments),
                "priority": rng.choices(priorities, weights=(55, 20, 15, 10), k=1)[0],
                "owner_team_id": None,
                "status": "未分配",
                "provenance": "simulated",
                "generation_seed": seed,
            })
    return output


def generate_xa_shaped_global_orders(
    rules: Mapping[str, Any],
    *,
    seed: int,
    yearly_counts: Mapping[int, int] | None = None,
    auction_count: int = 24,
) -> list[dict[str, Any]]:
    """Generate a random order pool with the observed XA year/type shape."""

    counts = dict(yearly_counts or {2: 169, 3: 172, 4: 214, 5: 241})
    if any(year < 1 or count <= 0 for year, count in counts.items()):
        raise ValueError("XA yearly order counts require positive years and counts")
    orders: list[dict[str, Any]] = []
    for offset, (year, count) in enumerate(sorted(counts.items())):
        orders.extend(
            generate_global_orders(
                rules,
                seed=seed + offset * 1009,
                orders_per_year=count,
                years=(year,),
                auction_ratio=0.0,
                complexity="large",
            )
        )
    if not 0 <= auction_count <= len(orders):
        raise ValueError("auction_count must fit inside the generated order pool")
    auction_indexes = set(random.Random(seed + 7919).sample(range(len(orders)), auction_count))
    for index, order in enumerate(orders):
        order["order_type"] = "竞单" if index in auction_indexes else "选单"
        order["order_shape_profile"] = "observed_XA_counts_randomized_content_v1"
    return orders


def generate_initial_visible_orders(
    rules: Mapping[str, Any],
    *,
    seed: int,
    team_ids: Sequence[str],
    order_count: int = 54,
    preassigned_count: int = 18,
) -> list[dict[str, Any]]:
    """Generate Y1Q1 public orders and a seeded private preallocation subset."""

    if order_count <= 0:
        return []
    if not 0 <= preassigned_count <= min(order_count, len(team_ids)):
        raise ValueError("preassigned_count must fit both initial orders and unique teams")
    rng = random.Random(seed)
    params = rules.get("parameters", rules)
    direct_cost = _number((params.get("products") or {}).get("P1", {}).get("direct_cost_wan"), 16)
    orders: list[dict[str, Any]] = []
    for index in range(1, order_count + 1):
        quantity = rng.randint(1, 4)
        price = round(direct_cost * quantity * rng.uniform(1.45, 2.25), 0)
        due_index = rng.choice((4, 5))
        orders.append(
            {
                "match_id": rules.get("match_id"),
                "order_id": f"{rules.get('match_id')}-INITIAL-{index:04d}",
                "year": 1,
                "release_period": "Y1Q1",
                "release_period_index": 0,
                "due_period": _period_label(due_index),
                "due_period_index": due_index,
                "market": "本地",
                "product": "P1",
                "iso": "-",
                "quantity": float(quantity),
                "total_price_wan": float(price),
                "delivery_term_quarters": due_index,
                "receivable_term_quarters": rng.randint(0, 4),
                "order_type": "选单",
                "customer_segment": rng.choice(("价格敏感型", "稳定供货型", "战略客户型")),
                "priority": rng.choice(("普通", "加急", "关键")),
                "owner_team_id": None,
                "status": "未分配",
                "initial_visibility": "public_unassigned",
                "provenance": "simulated",
                "generation_seed": seed,
            }
        )
    auction_indexes = set(rng.sample(range(order_count), max(1, round(order_count * 24 / 796))))
    for index in auction_indexes:
        orders[index]["order_type"] = "竞单"
    selected_orders = rng.sample(range(order_count), preassigned_count)
    selected_teams = rng.sample(list(team_ids), preassigned_count)
    for order_index, team_id in zip(selected_orders, selected_teams):
        orders[order_index]["owner_team_id"] = team_id
        orders[order_index]["status"] = "已分配"
        orders[order_index]["initial_visibility"] = "private_preassigned_public_result"
    return orders


@dataclass
class FinancialSandboxState:
    match_id: str
    team_id: str
    year: int = 1
    quarter: int = 1
    cash_wan: float = 675.0
    owner_equity_wan: float = 675.0
    material_inventory: dict[str, float] = field(default_factory=dict)
    material_inventory_value_wan: dict[str, float] = field(default_factory=dict)
    product_inventory: dict[str, float] = field(default_factory=dict)
    product_inventory_value_wan: dict[str, float] = field(default_factory=dict)
    markets: list[str] = field(default_factory=lambda: ["本地"])
    products: list[str] = field(default_factory=lambda: ["P1"])
    iso: list[str] = field(default_factory=list)
    factories: list[dict[str, Any]] = field(default_factory=list)
    production_lines: list[dict[str, Any]] = field(default_factory=list)
    pending_material_orders: list[dict[str, Any]] = field(default_factory=list)
    pending_development: list[dict[str, Any]] = field(default_factory=list)
    pending_lines: list[dict[str, Any]] = field(default_factory=list)
    pending_production: list[dict[str, Any]] = field(default_factory=list)
    short_loans: list[dict[str, Any]] = field(default_factory=list)
    long_loans: list[dict[str, Any]] = field(default_factory=list)
    receivables: list[dict[str, Any]] = field(default_factory=list)
    available_orders: list[dict[str, Any]] = field(default_factory=list)
    assigned_orders: list[dict[str, Any]] = field(default_factory=list)
    delivered_orders: list[dict[str, Any]] = field(default_factory=list)
    defaulted_orders: list[dict[str, Any]] = field(default_factory=list)
    advertising: dict[str, float] = field(default_factory=dict)
    annual_income: dict[str, float] = field(default_factory=dict)
    annual_cash_flow: dict[str, float] = field(default_factory=dict)
    reports: list[dict[str, Any]] = field(default_factory=list)
    journal: list[dict[str, Any]] = field(default_factory=list)
    bankrupt: bool = False
    bankruptcy_period: str | None = None
    bankruptcy_reasons: list[str] = field(default_factory=list)
    competition_complete: bool = False
    accounting_status: str = "full_candidate_accounting"

    @property
    def period_index(self) -> int:
        return _period_index(self.year, self.quarter)

    @property
    def period(self) -> str:
        return f"Y{self.year}Q{self.quarter}"

    @property
    def debt_wan(self) -> float:
        return sum(_number(row.get("principal_wan")) for row in self.short_loans + self.long_loans)

    @property
    def receivables_wan(self) -> float:
        return sum(_number(row.get("amount_wan")) for row in self.receivables)

    @property
    def work_in_process_wan(self) -> float:
        return sum(_number(row.get("inventory_cost_wan")) for row in self.pending_production)

    @property
    def fixed_assets_wan(self) -> float:
        return sum(_number(row.get("book_value_wan")) for row in self.factories + self.production_lines + self.pending_lines if row.get("ownership") == "purchased")

    @property
    def total_assets_wan(self) -> float:
        return self.cash_wan + self.receivables_wan + sum(self.material_inventory_value_wan.values()) + sum(self.product_inventory_value_wan.values()) + self.work_in_process_wan + self.fixed_assets_wan

    @property
    def balance_gap_wan(self) -> float:
        return self.total_assets_wan - self.debt_wan - self.owner_equity_wan

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value.update({"period": self.period, "period_index": self.period_index, "debt_wan": self.debt_wan, "receivables_wan": self.receivables_wan, "work_in_process_wan": self.work_in_process_wan, "fixed_assets_wan": self.fixed_assets_wan, "total_assets_wan": self.total_assets_wan, "balance_gap_wan": self.balance_gap_wan})
        return value


@dataclass(frozen=True)
class FinancialTransition:
    status: str
    state: FinancialSandboxState
    events: tuple[Mapping[str, Any], ...] = ()
    violations: tuple[str, ...] = ()


class FullFinancialDynamics:
    """Executable candidate rules for five-year enterprise competition."""

    ACTIONS = (
        "short_loan_borrow", "long_loan_borrow", "receivable_discount",
        "material_order", "emergency_purchase", "develop_product", "develop_market", "develop_iso",
        "buy_workshop", "rent_workshop", "sell_workshop", "buy_product_line", "convert_product_line", "sell_product_line",
        "advertising", "production", "order_delivery", "hold",
    )

    def __init__(self, rules: Mapping[str, Any]) -> None:
        self.rules = copy.deepcopy(dict(rules))
        self.parameters = dict(self.rules.get("parameters") or {})
        self.financial_rules = dict(self.rules.get("financial_rules") or {})

    def initial_state(self, team_id: str, *, initial_state: Mapping[str, Any] | None = None, orders: Sequence[Mapping[str, Any]] = ()) -> FinancialSandboxState:
        configured = dict(initial_state or {})
        cash = _number(configured.get("cash_wan"), _number(self.parameters.get("initial_cash_wan"), 675))
        materials = {key: 0.0 for key in (self.parameters.get("materials") or {})}
        materials.update(dict(configured.get("material_inventory") or {}))
        products = {key: 0.0 for key in (self.parameters.get("products") or {})}
        products.update(dict(configured.get("product_inventory") or {}))
        material_values = dict(configured.get("material_inventory_value_wan") or {key: materials[key] * _number((self.parameters.get("materials") or {}).get(key, {}).get("price_wan")) for key in materials})
        product_values = dict(configured.get("product_inventory_value_wan") or {key: products[key] * _number((self.parameters.get("products") or {}).get(key, {}).get("direct_cost_wan")) for key in products})
        state = FinancialSandboxState(
            match_id=str(self.rules.get("match_id", "SIM")), team_id=team_id, cash_wan=cash,
            material_inventory=materials, material_inventory_value_wan=material_values,
            product_inventory=products, product_inventory_value_wan=product_values,
            markets=list(configured.get("markets") or ["本地"]), products=list(configured.get("products") or ["P1"]), iso=list(configured.get("iso") or []),
            factories=copy.deepcopy(list(configured.get("factories") or [])), production_lines=copy.deepcopy(list(configured.get("production_lines") or [])),
            available_orders=copy.deepcopy(list(orders)),
        )
        state.owner_equity_wan = _number(configured.get("owner_equity_wan"), state.total_assets_wan - state.debt_wan)
        return state

    def legal_actions(self, state: FinancialSandboxState) -> tuple[Mapping[str, Any], ...]:
        return ({"action_type": "hold"},) if state.bankrupt else tuple({"action_type": value} for value in self.ACTIONS)

    def apply(self, state: FinancialSandboxState, action: Mapping[str, Any]) -> FinancialTransition:
        if state.bankrupt:
            return FinancialTransition("success", copy.deepcopy(state), ({"event_type": "bankrupt_hold"},)) if action.get("action_type") == "hold" else self._reject(state, "企业已经破产")
        action_type = str(action.get("action_type") or "")
        values = dict(action.get("parameters") or {})
        if action_type == "hold":
            return FinancialTransition("success", copy.deepcopy(state), ({"event_type": "hold"},))
        handlers = {
            "short_loan_borrow": lambda current: self._borrow(current, values, "short"),
            "long_loan_borrow": lambda current: self._borrow(current, values, "long"),
            "receivable_discount": lambda current: self._discount(current, values),
            "material_order": lambda current: self._material_order(current, values),
            "emergency_purchase": lambda current: self._emergency_purchase(current, values),
            "develop_product": lambda current: self._development(current, "product", values),
            "develop_market": lambda current: self._development(current, "market", values),
            "develop_iso": lambda current: self._development(current, "iso", values),
            "buy_workshop": lambda current: self._factory(current, "buy", values),
            "rent_workshop": lambda current: self._factory(current, "rent", values),
            "sell_workshop": lambda current: self._sell_asset(current, "factory", values),
            "buy_product_line": lambda current: self._line(current, values),
            "convert_product_line": lambda current: self._convert_line(current, values),
            "sell_product_line": lambda current: self._sell_asset(current, "line", values),
            "advertising": lambda current: self._advertise(current, values),
            "production": lambda current: self._production(current, values),
            "order_delivery": lambda current: self._deliver(current, values),
        }
        if action_type not in handlers:
            return self._reject(state, f"未实现动作：{action_type}")
        result = handlers[action_type](state)
        self._assert_balance(result.state)
        return result

    def _journal(self, state: FinancialSandboxState, event_type: str, *, cash: float = 0.0, equity: float = 0.0, cash_category: str | None = None, income_category: str | None = None, details: Mapping[str, Any] | None = None) -> dict[str, Any]:
        state.cash_wan += cash
        state.owner_equity_wan += equity
        if cash_category:
            state.annual_cash_flow[cash_category] = state.annual_cash_flow.get(cash_category, 0.0) + cash
        if income_category:
            state.annual_income[income_category] = state.annual_income.get(income_category, 0.0) + equity
        event = {"event_type": event_type, "period": state.period, "cash_effect_wan": cash, "equity_effect_wan": equity, **dict(details or {})}
        state.journal.append(event)
        self._bankruptcy_check(state, event_type)
        return event

    def _expense(self, state: FinancialSandboxState, amount: float, category: str, details: Mapping[str, Any] | None = None) -> dict[str, Any]:
        return self._journal(state, category, cash=-amount, equity=-amount, cash_category=category, income_category=category, details=details)

    def _borrow(self, state: FinancialSandboxState, values: Mapping[str, Any], kind: str) -> FinancialTransition:
        principal = _number(values.get("principal_wan"))
        if principal <= 0:
            return self._reject(state, "贷款金额必须为正数")
        next_state = copy.deepcopy(state)
        if kind == "short":
            term = int(values.get("term_quarters", 4))
            if term <= 0:
                return self._reject(state, "短贷期限必须为正数")
            rate = _number((self.parameters.get("short_loan") or {}).get("rate"), 0.05)
            loan = {"loan_id": _stable_id("SL", state.team_id, state.period, len(state.short_loans)), "principal_wan": principal, "rate": rate, "due_period_index": state.period_index + term, "interest_wan": principal * rate * term / 4}
            next_state.short_loans.append(loan)
        else:
            term_years = int(values.get("term_years", 4))
            rule = self.parameters.get("long_loan") or {}
            if principal < _number(rule.get("minimum_wan"), 10) or term_years <= 0 or term_years > int(rule.get("max_years", 4)):
                return self._reject(state, "长贷金额或期限不符合规则")
            limit = max(0.0, state.owner_equity_wan * _number(rule.get("max_total_multiple_prior_equity"), 3))
            if sum(_number(row.get("principal_wan")) for row in state.long_loans) + principal > limit:
                return self._reject(state, "长贷超过所有者权益倍数上限")
            loan = {"loan_id": _stable_id("LL", state.team_id, state.period, len(state.long_loans)), "principal_wan": principal, "rate": _number(rule.get("annual_rate"), 0.12), "due_period_index": state.period_index + term_years * 4, "last_interest_year": state.year - 1}
            next_state.long_loans.append(loan)
        event = self._journal(next_state, f"{kind}_loan_borrowed", cash=principal, cash_category="financing_inflow", details={"loan": loan})
        return FinancialTransition("success", next_state, (event,))

    def _discount(self, state: FinancialSandboxState, values: Mapping[str, Any]) -> FinancialTransition:
        receivable_id = str(values.get("receivable_id") or "")
        item = next((row for row in state.receivables if str(row.get("receivable_id")) == receivable_id), None)
        if item is None:
            return self._reject(state, "应收款不存在")
        remaining = max(1, int(item["due_period_index"]) - state.period_index)
        discount = self.parameters.get("receivable_discount") or {}
        rate = _number(discount.get("terms_1_2" if remaining <= 2 else "terms_3_4"), 0.09)
        gross = _number(item.get("amount_wan"))
        net = gross * (1.0 - rate)
        next_state = copy.deepcopy(state)
        next_item = next(row for row in next_state.receivables if str(row.get("receivable_id")) == receivable_id)
        next_state.receivables.remove(next_item)
        event = self._journal(next_state, "receivable_discounted", cash=net, equity=-(gross - net), cash_category="receivable_discount", income_category="discount_expense", details={"receivable_id": receivable_id, "gross_wan": gross, "discount_rate": rate})
        return FinancialTransition("success", next_state, (event,))

    def _material_order(self, state: FinancialSandboxState, values: Mapping[str, Any]) -> FinancialTransition:
        materials = values.get("materials")
        if not isinstance(materials, Mapping) or not materials:
            return self._reject(state, "material_order 需要 materials")
        next_state = copy.deepcopy(state)
        created = []
        for material_id, raw_quantity in materials.items():
            rule = (self.parameters.get("materials") or {}).get(material_id)
            quantity = _number(raw_quantity)
            if not rule or quantity <= 0:
                return self._reject(state, f"无效原料：{material_id}")
            created.append({"order_id": _stable_id("MO", state.team_id, state.period, material_id, len(next_state.pending_material_orders)), "material_id": material_id, "quantity": quantity, "unit_price_wan": _number(rule.get("price_wan")), "total_cost_wan": quantity * _number(rule.get("price_wan")), "arrival_period_index": state.period_index + int(rule.get("lead_quarters", 1))})
        next_state.pending_material_orders.extend(created)
        event = self._journal(next_state, "material_ordered", details={"orders": created})
        return FinancialTransition("success", next_state, (event,))

    def _emergency_purchase(self, state: FinancialSandboxState, values: Mapping[str, Any]) -> FinancialTransition:
        material_id, quantity = str(values.get("material_id") or ""), _number(values.get("quantity"))
        rule = (self.parameters.get("materials") or {}).get(material_id)
        if not rule or quantity <= 0:
            return self._reject(state, "紧急采购参数无效")
        multiplier = _number(self.financial_rules.get("emergency_material_price_multiplier"), 1.5)
        cost = quantity * _number(rule.get("price_wan")) * multiplier
        next_state = copy.deepcopy(state)
        next_state.material_inventory[material_id] = next_state.material_inventory.get(material_id, 0.0) + quantity
        next_state.material_inventory_value_wan[material_id] = next_state.material_inventory_value_wan.get(material_id, 0.0) + cost
        event = self._journal(next_state, "emergency_material_purchase", cash=-cost, cash_category="inventory_purchase", details={"material_id": material_id, "quantity": quantity, "cost_wan": cost})
        return FinancialTransition("success", next_state, (event,))

    def _development(self, state: FinancialSandboxState, kind: str, values: Mapping[str, Any]) -> FinancialTransition:
        target = str(values.get("target") or values.get("product_id") or values.get("market") or values.get("iso") or "")
        collection = {"product": "products", "market": "markets", "iso": "iso"}[kind]
        rule = (self.parameters.get(collection) or {}).get(target)
        bucket = getattr(state, collection)
        if not rule or target in bucket or any(row.get("kind") == kind and row.get("target") == target for row in state.pending_development):
            return self._reject(state, "开发对象无效、已完成或正在开发")
        duration = int(rule.get("quarters", int(rule.get("years", 1)) * 4))
        installment = _number(rule.get("development_wan_per_quarter"), _number(rule.get("fee_wan_per_year")) / 4)
        next_state = copy.deepcopy(state)
        pending = {"development_id": _stable_id("DEV", state.team_id, state.period, kind, target), "kind": kind, "target": target, "remaining_installments": max(0, duration - 1), "installment_wan": installment}
        next_state.pending_development.append(pending)
        event = self._expense(next_state, installment, f"{kind}_development_expense", {"target": target, "installment": 1, "total_installments": duration})
        if duration == 1:
            getattr(next_state, collection).append(target)
            next_state.pending_development.remove(pending)
        return FinancialTransition("success", next_state, (event,))

    def _factory(self, state: FinancialSandboxState, mode: str, values: Mapping[str, Any]) -> FinancialTransition:
        name = str(values.get("factory") or values.get("name") or "")
        rule = (self.parameters.get("factories") or {}).get(name)
        if not rule:
            return self._reject(state, "厂房类型无效")
        next_state = copy.deepcopy(state)
        factory_id = _stable_id("F", state.team_id, state.period, len(state.factories))
        if mode == "buy":
            cost = _number(rule.get("purchase_wan"))
            asset = {"factory_id": factory_id, "name": name, "ownership": "purchased", "capacity": int(rule.get("capacity", 0)), "cost_wan": cost, "book_value_wan": cost, "accumulated_depreciation_wan": 0.0}
            next_state.factories.append(asset)
            event = self._journal(next_state, "factory_purchased", cash=-cost, cash_category="fixed_asset_purchase", details={"factory": asset})
        else:
            rent = _number(rule.get("rent_wan_per_year"))
            asset = {"factory_id": factory_id, "name": name, "ownership": "rented", "capacity": int(rule.get("capacity", 0)), "annual_rent_wan": rent, "next_rent_period_index": state.period_index + 4}
            next_state.factories.append(asset)
            event = self._expense(next_state, rent, "factory_rent_expense", {"factory": asset})
        return FinancialTransition("success", next_state, (event,))

    def _line(self, state: FinancialSandboxState, values: Mapping[str, Any]) -> FinancialTransition:
        line_type = str(values.get("line_type") or values.get("name") or "")
        rule = (self.parameters.get("production_lines") or {}).get(line_type)
        used = len(state.production_lines) + len(state.pending_lines)
        capacity = sum(int(row.get("capacity", 0)) for row in state.factories)
        if not rule or used >= capacity:
            return self._reject(state, "生产线类型无效或厂房容量不足")
        cost = _number(rule.get("investment_wan"))
        install = int(rule.get("install_quarters", 0))
        line = {"line_id": _stable_id("L", state.team_id, state.period, used), "line_type": line_type, "product_id": values.get("product_id"), "ownership": "rented" if line_type == "租赁线" else "purchased", "cost_wan": cost, "book_value_wan": cost, "accumulated_depreciation_wan": 0.0, "maintenance_wan_per_year": _number(rule.get("maintenance_wan_per_year")), "status": "ready" if install == 0 else "installing", "remaining_install_quarters": install}
        next_state = copy.deepcopy(state)
        (next_state.production_lines if install == 0 else next_state.pending_lines).append(line)
        event = self._journal(next_state, "production_line_ordered", cash=-cost, cash_category="fixed_asset_purchase", details={"line": line})
        return FinancialTransition("success", next_state, (event,))

    def _convert_line(self, state: FinancialSandboxState, values: Mapping[str, Any]) -> FinancialTransition:
        line_id, product_id = str(values.get("line_id") or ""), str(values.get("product_id") or "")
        line = next((row for row in state.production_lines if str(row.get("line_id")) == line_id), None)
        if line is None or product_id not in state.products or line.get("status") != "ready":
            return self._reject(state, "生产线不存在、忙碌或产品资格不足")
        fee = _number(values.get("conversion_fee_wan"), max(1.0, _number(line.get("cost_wan")) * 0.10))
        next_state = copy.deepcopy(state)
        next_line = next(row for row in next_state.production_lines if str(row.get("line_id")) == line_id)
        next_line["product_id"] = product_id
        event = self._expense(next_state, fee, "production_line_conversion_expense", {"line_id": line_id, "product_id": product_id})
        return FinancialTransition("success", next_state, (event,))

    def _sell_asset(self, state: FinancialSandboxState, kind: str, values: Mapping[str, Any]) -> FinancialTransition:
        collection = state.factories if kind == "factory" else state.production_lines
        key = "factory_id" if kind == "factory" else "line_id"
        asset_id = str(values.get(key) or "")
        asset = next((row for row in collection if str(row.get(key)) == asset_id), None)
        if asset is None or asset.get("ownership") != "purchased" or asset.get("status") == "busy":
            return self._reject(state, "资产不存在、非自有或正在使用")
        rate_key = "factory_disposal_book_value_rate" if kind == "factory" else "production_line_disposal_book_value_rate"
        proceeds = _number(asset.get("book_value_wan")) * _number(self.financial_rules.get(rate_key), 0.6)
        book = _number(asset.get("book_value_wan"))
        next_state = copy.deepcopy(state)
        target_collection = next_state.factories if kind == "factory" else next_state.production_lines
        target_collection.remove(next(row for row in target_collection if str(row.get(key)) == asset_id))
        event = self._journal(next_state, f"{kind}_sold", cash=proceeds, equity=proceeds - book, cash_category="fixed_asset_disposal", income_category="asset_disposal_gain_loss", details={key: asset_id, "book_value_wan": book, "proceeds_wan": proceeds})
        return FinancialTransition("success", next_state, (event,))

    def _advertise(self, state: FinancialSandboxState, values: Mapping[str, Any]) -> FinancialTransition:
        amount = _number(values.get("amount_wan"))
        if amount <= 0:
            return self._reject(state, "广告金额必须为正数")
        next_state = copy.deepcopy(state)
        key = f"{values.get('market', '本地')}:{values.get('product_id', 'P1')}"
        next_state.advertising[key] = next_state.advertising.get(key, 0.0) + amount
        event = self._expense(next_state, amount, "advertising_expense", {"advertising_key": key, "opportunities": advertising_opportunities(next_state.advertising[key])})
        return FinancialTransition("success", next_state, (event,))

    @staticmethod
    def _consume_inventory(quantity_bucket: dict[str, float], value_bucket: dict[str, float], item_id: str, quantity: float) -> float | None:
        available = quantity_bucket.get(item_id, 0.0)
        if available < quantity:
            return None
        average = value_bucket.get(item_id, 0.0) / available if available else 0.0
        consumed = average * quantity
        quantity_bucket[item_id] = available - quantity
        value_bucket[item_id] = max(0.0, value_bucket.get(item_id, 0.0) - consumed)
        return consumed

    def _production(self, state: FinancialSandboxState, values: Mapping[str, Any]) -> FinancialTransition:
        product_id, quantity = str(values.get("product_id") or ""), _number(values.get("quantity"), 1)
        rule = (self.parameters.get("products") or {}).get(product_id)
        line = next((row for row in state.production_lines if row.get("status") == "ready" and row.get("product_id") in {None, product_id}), None)
        if not rule or product_id not in state.products or quantity <= 0 or line is None:
            return self._reject(state, "生产资格、数量或生产线无效")
        next_state = copy.deepcopy(state)
        consumed_value = 0.0
        for item_id, raw_units in (rule.get("bom") or {}).items():
            required = _number(raw_units) * quantity
            if item_id.startswith("R"):
                consumed = self._consume_inventory(next_state.material_inventory, next_state.material_inventory_value_wan, item_id, required)
            else:
                consumed = self._consume_inventory(next_state.product_inventory, next_state.product_inventory_value_wan, item_id, required)
            if consumed is None:
                return self._reject(state, f"BOM 库存不足：{item_id}")
            consumed_value += consumed
        process_cost = _number(rule.get("process_wan")) * quantity
        next_state.cash_wan -= process_cost
        next_state.annual_cash_flow["production_processing"] = next_state.annual_cash_flow.get("production_processing", 0.0) - process_cost
        next_line = next(row for row in next_state.production_lines if row.get("line_id") == line.get("line_id"))
        next_line["status"] = "busy"
        duration = int((self.parameters.get("production_lines") or {}).get(line.get("line_type"), {}).get("production_quarters", 1))
        job = {"job_id": _stable_id("JOB", state.team_id, state.period, len(state.pending_production)), "line_id": line.get("line_id"), "product_id": product_id, "quantity": quantity, "remaining_quarters": duration, "inventory_cost_wan": consumed_value + process_cost}
        next_state.pending_production.append(job)
        event = {"event_type": "production_started", "period": state.period, "cash_effect_wan": -process_cost, "equity_effect_wan": 0.0, "job": job}
        next_state.journal.append(event)
        self._bankruptcy_check(next_state, "production_started")
        return FinancialTransition("success", next_state, (event,))

    def _deliver(self, state: FinancialSandboxState, values: Mapping[str, Any]) -> FinancialTransition:
        order_id = str(values.get("order_id") or "")
        order = next((row for row in state.assigned_orders if str(row.get("order_id")) == order_id and row.get("status") not in {"已交", "违约"}), None)
        if order is None:
            return self._reject(state, "订单不存在或已经结算")
        product_id, quantity = str(order.get("product")), _number(order.get("quantity"))
        if state.product_inventory.get(product_id, 0.0) < quantity:
            return self._reject(state, "产成品库存不足")
        next_state = copy.deepcopy(state)
        cost = self._consume_inventory(next_state.product_inventory, next_state.product_inventory_value_wan, product_id, quantity) or 0.0
        next_order = next(row for row in next_state.assigned_orders if str(row.get("order_id")) == order_id)
        next_order["status"] = "已交"
        next_order["delivered_period"] = state.period
        amount = _number(order.get("total_price_wan"))
        term = int(order.get("receivable_term_quarters") or 0)
        next_state.owner_equity_wan += amount - cost
        next_state.annual_income["revenue"] = next_state.annual_income.get("revenue", 0.0) + amount
        next_state.annual_income["cost_of_goods_sold"] = next_state.annual_income.get("cost_of_goods_sold", 0.0) - cost
        if term == 0:
            next_state.cash_wan += amount
            next_state.annual_cash_flow["customer_collection"] = next_state.annual_cash_flow.get("customer_collection", 0.0) + amount
        else:
            next_state.receivables.append({"receivable_id": _stable_id("AR", state.team_id, order_id), "order_id": order_id, "amount_wan": amount, "due_period_index": state.period_index + term})
        delivered = copy.deepcopy(next_order)
        next_state.delivered_orders.append(delivered)
        event = {"event_type": "order_delivered", "period": state.period, "cash_effect_wan": amount if term == 0 else 0.0, "equity_effect_wan": amount - cost, "order_id": order_id, "revenue_wan": amount, "cost_of_goods_sold_wan": cost, "receivable_term_quarters": term}
        next_state.journal.append(event)
        self._bankruptcy_check(next_state, "order_delivered")
        return FinancialTransition("success", next_state, (event,))

    def advance_quarter(self, state: FinancialSandboxState) -> FinancialTransition:
        if state.bankrupt:
            next_state = copy.deepcopy(state)
            next_index = state.period_index + 1
            if next_index > 19:
                next_state.competition_complete = True
                return FinancialTransition("success", next_state, ({"event_type": "bankrupt_hold", "period": state.period}, {"event_type": "competition_complete", "period": state.period}))
            next_state.year, next_state.quarter = _period_from_index(next_index)
            return FinancialTransition("success", next_state, ({"event_type": "bankrupt_hold", "period": state.period}, {"event_type": "quarter_advanced", "from_period": state.period, "to_period": next_state.period}))
        next_state = copy.deepcopy(state)
        events: list[Mapping[str, Any]] = []
        next_index = state.period_index + 1
        if next_index > 19:
            if state.quarter == 4 and not any(int(report.get("year", -1)) == state.year for report in state.reports):
                events.extend(self._year_end(next_state, closing_year=state.year))
            next_state.competition_complete = True
            if not next_state.bankrupt:
                next_state.accounting_status = "competition_complete"
            events.append({"event_type": "competition_complete", "period": state.period})
            self._assert_balance(next_state)
            return FinancialTransition("success", next_state, tuple(events))
        events.append(self._expense(next_state, _number(self.parameters.get("management_fee_per_quarter_wan"), 14), "management_fee_expense"))
        if next_state.bankrupt:
            return FinancialTransition("success", next_state, tuple(events))

        for order in list(next_state.pending_material_orders):
            if int(order["arrival_period_index"]) <= next_index:
                cost = _number(order.get("total_cost_wan"))
                material_id, quantity = str(order["material_id"]), _number(order.get("quantity"))
                next_state.cash_wan -= cost
                next_state.annual_cash_flow["inventory_purchase"] = next_state.annual_cash_flow.get("inventory_purchase", 0.0) - cost
                next_state.material_inventory[material_id] = next_state.material_inventory.get(material_id, 0.0) + quantity
                next_state.material_inventory_value_wan[material_id] = next_state.material_inventory_value_wan.get(material_id, 0.0) + cost
                next_state.pending_material_orders.remove(order)
                event = {"event_type": "material_arrived", "period": state.period, "cash_effect_wan": -cost, "equity_effect_wan": 0.0, "order": order}
                next_state.journal.append(event); events.append(event); self._bankruptcy_check(next_state, "material_arrival")
                if next_state.bankrupt:
                    return FinancialTransition("success", next_state, tuple(events))

        for item in list(next_state.pending_development):
            installment = _number(item.get("installment_wan"))
            events.append(self._expense(next_state, installment, f"{item['kind']}_development_expense", {"target": item["target"]}))
            item["remaining_installments"] = int(item.get("remaining_installments", 0)) - 1
            if item["remaining_installments"] <= 0:
                collection = {"product": "products", "market": "markets", "iso": "iso"}[item["kind"]]
                bucket = getattr(next_state, collection)
                if item["target"] not in bucket:
                    bucket.append(item["target"])
                next_state.pending_development.remove(item)
                events.append({"event_type": "development_completed", "kind": item["kind"], "target": item["target"], "period": state.period})
            if next_state.bankrupt:
                return FinancialTransition("success", next_state, tuple(events))

        for line in list(next_state.pending_lines):
            line["remaining_install_quarters"] = int(line.get("remaining_install_quarters", 0)) - 1
            if line["remaining_install_quarters"] <= 0:
                line["status"] = "ready"
                next_state.production_lines.append(line)
                next_state.pending_lines.remove(line)
                events.append({"event_type": "production_line_ready", "line_id": line["line_id"], "period": state.period})
        for job in list(next_state.pending_production):
            job["remaining_quarters"] = int(job.get("remaining_quarters", 0)) - 1
            if job["remaining_quarters"] <= 0:
                product_id, quantity, value = str(job["product_id"]), _number(job["quantity"]), _number(job["inventory_cost_wan"])
                next_state.product_inventory[product_id] = next_state.product_inventory.get(product_id, 0.0) + quantity
                next_state.product_inventory_value_wan[product_id] = next_state.product_inventory_value_wan.get(product_id, 0.0) + value
                line = next((row for row in next_state.production_lines if row.get("line_id") == job.get("line_id")), None)
                if line:
                    line["status"] = "ready"
                next_state.pending_production.remove(job)
                events.append({"event_type": "production_completed", "job_id": job["job_id"], "period": state.period})

        for loan in list(next_state.short_loans):
            if int(loan["due_period_index"]) <= next_index:
                amount = _number(loan["principal_wan"]) + _number(loan["interest_wan"])
                next_state.cash_wan -= amount
                next_state.owner_equity_wan -= _number(loan["interest_wan"])
                next_state.annual_cash_flow["loan_repayment"] = next_state.annual_cash_flow.get("loan_repayment", 0.0) - amount
                next_state.annual_income["interest_expense"] = next_state.annual_income.get("interest_expense", 0.0) - _number(loan["interest_wan"])
                next_state.short_loans.remove(loan)
                event = {"event_type": "short_loan_repaid", "period": state.period, "cash_effect_wan": -amount, "equity_effect_wan": -_number(loan["interest_wan"]), "loan_id": loan["loan_id"]}
                next_state.journal.append(event); events.append(event); self._bankruptcy_check(next_state, "short_loan_repayment")
                if next_state.bankrupt:
                    return FinancialTransition("success", next_state, tuple(events))
        for receivable in list(next_state.receivables):
            if int(receivable["due_period_index"]) <= next_index:
                amount = _number(receivable["amount_wan"])
                next_state.cash_wan += amount
                next_state.annual_cash_flow["customer_collection"] = next_state.annual_cash_flow.get("customer_collection", 0.0) + amount
                next_state.receivables.remove(receivable)
                event = {"event_type": "receivable_collected", "period": state.period, "cash_effect_wan": amount, "equity_effect_wan": 0.0, "receivable_id": receivable["receivable_id"]}
                next_state.journal.append(event); events.append(event)

        delivered_ids = {str(row.get("order_id")) for row in next_state.delivered_orders}
        defaulted_ids = {str(row.get("order_id")) for row in next_state.defaulted_orders}
        for order in next_state.assigned_orders:
            if int(order.get("due_period_index", 99)) <= next_index and str(order.get("order_id")) not in delivered_ids | defaulted_ids:
                penalty = _number(order.get("total_price_wan")) * _number(self.parameters.get("default_penalty_rate"), 0.2)
                events.append(self._expense(next_state, penalty, "order_default_penalty", {"order_id": order.get("order_id")}))
                order["status"] = "违约"
                next_state.defaulted_orders.append(copy.deepcopy(order))
                if next_state.bankrupt:
                    return FinancialTransition("success", next_state, tuple(events))

        next_year, next_quarter = _period_from_index(next_index)
        if state.quarter == 4:
            events.extend(self._year_end(next_state, closing_year=state.year))
            if next_state.bankrupt:
                return FinancialTransition("success", next_state, tuple(events))
        next_state.year, next_state.quarter = next_year, next_quarter
        events.append({"event_type": "quarter_advanced", "from_period": state.period, "to_period": next_state.period})
        self._assert_balance(next_state)
        return FinancialTransition("success", next_state, tuple(events))

    def _year_end(self, state: FinancialSandboxState, *, closing_year: int) -> list[Mapping[str, Any]]:
        events: list[Mapping[str, Any]] = []
        for line in state.production_lines:
            maintenance = _number(line.get("maintenance_wan_per_year"))
            if maintenance:
                events.append(self._expense(state, maintenance, "maintenance_expense", {"line_id": line.get("line_id")}))
                if state.bankrupt:
                    return events
        for factory in state.factories:
            if factory.get("ownership") == "rented" and int(factory.get("next_rent_period_index", 99)) <= state.period_index + 1:
                rent = _number(factory.get("annual_rent_wan"))
                events.append(self._expense(state, rent, "factory_rent_expense", {"factory_id": factory.get("factory_id")}))
                factory["next_rent_period_index"] = int(factory.get("next_rent_period_index", state.period_index + 1)) + 4
                if state.bankrupt:
                    return events
        for loan in list(state.long_loans):
            interest = _number(loan.get("principal_wan")) * _number(loan.get("rate"))
            events.append(self._expense(state, interest, "interest_expense", {"loan_id": loan.get("loan_id"), "loan_type": "long"}))
            if int(loan.get("due_period_index", 99)) <= state.period_index + 1:
                principal = _number(loan.get("principal_wan"))
                state.cash_wan -= principal
                state.annual_cash_flow["loan_repayment"] = state.annual_cash_flow.get("loan_repayment", 0.0) - principal
                state.long_loans.remove(loan)
                event = {"event_type": "long_loan_principal_repaid", "period": state.period, "cash_effect_wan": -principal, "equity_effect_wan": 0.0, "loan_id": loan.get("loan_id")}
                state.journal.append(event); events.append(event); self._bankruptcy_check(state, "long_loan_repayment")
            if state.bankrupt:
                return events
        factory_years = max(1, int(self.financial_rules.get("factory_depreciation_years", 10)))
        line_years = max(1, int(self.financial_rules.get("production_line_depreciation_years", 5)))
        for asset, years, asset_type in [(row, factory_years, "factory") for row in state.factories] + [(row, line_years, "production_line") for row in state.production_lines]:
            if asset.get("ownership") != "purchased":
                continue
            depreciation = min(_number(asset.get("book_value_wan")), _number(asset.get("cost_wan")) / years)
            if depreciation <= 0:
                continue
            asset["book_value_wan"] = _number(asset.get("book_value_wan")) - depreciation
            asset["accumulated_depreciation_wan"] = _number(asset.get("accumulated_depreciation_wan")) + depreciation
            state.owner_equity_wan -= depreciation
            state.annual_income["depreciation_expense"] = state.annual_income.get("depreciation_expense", 0.0) - depreciation
            event = {"event_type": "depreciation", "period": state.period, "cash_effect_wan": 0.0, "equity_effect_wan": -depreciation, "asset_type": asset_type, "asset_id": asset.get("factory_id", asset.get("line_id")), "amount_wan": depreciation}
            state.journal.append(event); events.append(event)
        pretax = sum(state.annual_income.values())
        tax = max(0.0, pretax * _number(self.parameters.get("tax_rate"), 0.25))
        if tax:
            events.append(self._expense(state, tax, "income_tax_expense", {"pretax_income_wan": pretax}))
            if state.bankrupt:
                return events
        report = self._build_report(state, closing_year)
        state.reports.append(report)
        events.append({"event_type": "annual_reports_generated", "year": closing_year, "report_id": report["report_id"], "period": state.period})
        state.annual_income = {}
        state.annual_cash_flow = {}
        return events

    def _build_report(self, state: FinancialSandboxState, year: int) -> dict[str, Any]:
        current_assets = state.cash_wan + state.receivables_wan + sum(state.material_inventory_value_wan.values()) + sum(state.product_inventory_value_wan.values()) + state.work_in_process_wan
        fixed_assets = state.fixed_assets_wan
        revenue = _number(state.annual_income.get("revenue"))
        cogs = -_number(state.annual_income.get("cost_of_goods_sold"))
        expenses = -sum(value for key, value in state.annual_income.items() if key not in {"revenue", "cost_of_goods_sold", "income_tax_expense"} and value < 0)
        tax = -_number(state.annual_income.get("income_tax_expense"))
        net_income = sum(state.annual_income.values())
        return {
            "report_id": f"{state.match_id}:{state.team_id}:Y{year}", "match_id": state.match_id, "team_id": state.team_id, "year": year, "provenance": "simulated",
            "balance_sheet": {"cash_wan": state.cash_wan, "receivables_wan": state.receivables_wan, "materials_wan": sum(state.material_inventory_value_wan.values()), "products_wan": sum(state.product_inventory_value_wan.values()), "work_in_process_wan": state.work_in_process_wan, "current_assets_wan": current_assets, "fixed_assets_wan": fixed_assets, "total_assets_wan": current_assets + fixed_assets, "liabilities_wan": state.debt_wan, "owner_equity_wan": state.owner_equity_wan, "liabilities_and_equity_wan": state.debt_wan + state.owner_equity_wan, "balance_gap_wan": state.balance_gap_wan},
            "income_statement": {"revenue_wan": revenue, "cost_of_goods_sold_wan": cogs, "other_expenses_wan": expenses, "income_tax_wan": tax, "net_income_wan": net_income, "details": copy.deepcopy(state.annual_income)},
            "cash_flow_statement": {"net_cash_flow_wan": sum(state.annual_cash_flow.values()), "details": copy.deepcopy(state.annual_cash_flow)},
        }

    def _bankruptcy_check(self, state: FinancialSandboxState, reason: str) -> None:
        reasons = []
        if state.cash_wan < 0:
            reasons.append("cash_flow_break")
        if state.owner_equity_wan < 0:
            reasons.append("negative_equity")
        if reasons and not state.bankrupt:
            state.bankrupt = True
            state.bankruptcy_period = state.period
            state.bankruptcy_reasons = reasons + [reason]
            state.accounting_status = "bankrupt"

    @staticmethod
    def _reject(state: FinancialSandboxState, message: str) -> FinancialTransition:
        return FinancialTransition("rejected", copy.deepcopy(state), violations=(message,))

    @staticmethod
    def _assert_balance(state: FinancialSandboxState) -> None:
        if abs(state.balance_gap_wan) > 1e-5:
            raise AssertionError(f"accounting balance broken for {state.team_id} {state.period}: {state.balance_gap_wan}")


class FullCompetitionArena(MultiAgentEnvironment):
    """Multi-team environment with shared orders and full candidate accounting."""

    def __init__(
        self,
        dynamics: FullFinancialDynamics,
        team_ids: Sequence[str],
        global_orders: Sequence[Mapping[str, Any]],
        *,
        initial_states: Mapping[str, Mapping[str, Any]] | None = None,
        order_engine: OrderAllocationEngine | None = None,
        max_periods: int = 20,
        stop_when_all_bankrupt: bool = True,
    ) -> None:
        self.dynamics = dynamics
        self._agent_ids = tuple(sorted(map(str, team_ids)))
        self.global_orders = copy.deepcopy(list(global_orders))
        self.initial_states = {str(key): dict(value) for key, value in (initial_states or {}).items()}
        payment_mode = str(dynamics.financial_rules.get("auction_payment_mode", "fixed_order_price"))
        self.order_engine = order_engine or OrderAllocationEngine(TraditionalXAOrderPolicy(auction_payment_mode=payment_mode))
        self.max_periods = max_periods
        self.stop_when_all_bankrupt = stop_when_all_bankrupt
        self.states: dict[str, FinancialSandboxState] = {}
        self.order_log: list[dict[str, Any]] = []
        self.terminated = False

    @property
    def agent_ids(self) -> tuple[str, ...]:
        return self._agent_ids

    def reset(self, seed: int | None = None) -> Mapping[str, AgentObservation]:
        self.states = {team_id: self.dynamics.initial_state(team_id, initial_state=self.initial_states.get(team_id), orders=self.global_orders) for team_id in self.agent_ids}
        self.order_log = []
        preassigned_ids = set()
        for source_order in self.global_orders:
            owner = source_order.get("owner_team_id")
            if owner in {None, ""}:
                continue
            owner = str(owner)
            if owner not in self.states:
                raise ValueError(f"preassigned order has unknown owner: {owner}")
            order = copy.deepcopy(source_order)
            order["status"] = "已分配"
            self.states[owner].assigned_orders.append(order)
            preassigned_ids.add(str(order["order_id"]))
            self.order_log.append(
                {
                    "period": "Y1Q1",
                    "order_id": order["order_id"],
                    "winner_team_id": owner,
                    "policy_id": "seeded_initial_preallocation",
                    "reason": "scenario_initial_preassignment",
                    "contenders": [owner],
                    "trace": {"initial_visibility": order.get("initial_visibility")},
                    "provenance": "simulated",
                }
            )
        if preassigned_ids:
            for state in self.states.values():
                state.available_orders = [row for row in state.available_orders if str(row.get("order_id")) not in preassigned_ids]
        self.terminated = False
        return self._observations()

    def _visible_orders(self, state: FinancialSandboxState) -> list[dict[str, Any]]:
        return [copy.deepcopy(row) for row in state.available_orders if int(row.get("release_period_index", 0)) <= state.period_index and row.get("owner_team_id") in {None, ""}]

    def _observations(self) -> dict[str, AgentObservation]:
        observations = {}
        for team_id, state in self.states.items():
            private_state = state.to_dict()
            private_state.pop("available_orders", None)
            observations[team_id] = AgentObservation(
                state.match_id,
                team_id,
                state.period_index,
                state.period,
                private_state,
                {
                    "period": state.period,
                    "available_orders": self._visible_orders(state),
                    "public_order_results": copy.deepcopy(self.order_log),
                    "agent_ids": list(self.agent_ids),
                    "information_policy": "rules_orders_reports_public_private_operations_isolated",
                },
                self.dynamics.legal_actions(state),
            )
        return observations

    @staticmethod
    def _action_list(action: Mapping[str, Any]) -> list[Mapping[str, Any]]:
        rows = action.get("actions")
        return list(rows) if isinstance(rows, list) else [action]

    def _eligible(self, state: FinancialSandboxState, order: Mapping[str, Any]) -> bool:
        return str(order.get("market")) in state.markets and str(order.get("product")) in state.products and (order.get("iso") in {None, "", "-"} or str(order.get("iso")) in state.iso)

    def step(self, actions: Mapping[str, Mapping[str, Any]]) -> ArenaStep:
        if self.terminated:
            raise RuntimeError("arena is terminated; call reset()")
        if set(actions) != set(self.agent_ids):
            raise ValueError("one action bundle is required for every agent")
        before = copy.deepcopy(self.states)
        next_states = copy.deepcopy(self.states)
        claims_by_order: dict[str, list[dict[str, Any]]] = {}
        order_by_id = {str(row["order_id"]): row for row in self.global_orders}
        action_events: dict[str, list[Mapping[str, Any]]] = {team_id: [] for team_id in self.agent_ids}
        for team_id in self.agent_ids:
            for action in self._action_list(actions[team_id]):
                action_type = action.get("action_type")
                if action_type in {"select_order", "auction_bid"}:
                    values = dict(action.get("parameters") or {})
                    order_id = str(values.get("order_id") or "")
                    order = order_by_id.get(order_id)
                    if order is None or order not in self._visible_orders(next_states[team_id]) or not self._eligible(next_states[team_id], order):
                        raise ValueError(f"{team_id}: 订单不存在、尚未发布或资格不足：{order_id}")
                    expected_action = "auction_bid" if str(order.get("order_type")) == "竞单" else "select_order"
                    if action_type != expected_action:
                        raise ValueError(f"{team_id}: 订单 {order_id} 需要动作 {expected_action}")
                    if action_type == "auction_bid":
                        fee = _number(self.dynamics.financial_rules.get("auction_bid_fee_wan"), 10)
                        fee_result = self.dynamics._expense(next_states[team_id], fee, "auction_bid_fee", {"order_id": order_id})
                        action_events[team_id].append(fee_result)
                    claims_by_order.setdefault(order_id, []).append({**values, "team_id": team_id})
                    continue
                transition = self.dynamics.apply(next_states[team_id], action)
                if transition.status != "success":
                    raise ValueError(f"{team_id}: {'; '.join(transition.violations)}")
                next_states[team_id] = transition.state
                action_events[team_id].extend(transition.events)
        if claims_by_order:
            decisions = self.order_engine.allocate([order_by_id[key] for key in claims_by_order], claims_by_order, {"period": next(iter(next_states.values())).period})
            for decision in decisions:
                order = copy.deepcopy(order_by_id[decision.order_id])
                order["owner_team_id"] = decision.winner_team_id
                order["status"] = "已分配" if decision.winner_team_id else "流单"
                allocation = {"period": next(iter(next_states.values())).period, "order_id": decision.order_id, "winner_team_id": decision.winner_team_id, "policy_id": decision.policy_id, "reason": decision.reason, "contenders": list(decision.contenders), "trace": dict(decision.trace), "provenance": "simulated"}
                self.order_log.append(allocation)
                if decision.winner_team_id:
                    next_states[decision.winner_team_id].assigned_orders.append(order)
                for state in next_states.values():
                    state.available_orders = [row for row in state.available_orders if str(row.get("order_id")) != decision.order_id]
        infos: dict[str, Any] = {}
        rewards: dict[str, float] = {}
        for team_id in self.agent_ids:
            transition = self.dynamics.advance_quarter(next_states[team_id])
            if transition.status != "success":
                raise ValueError(f"{team_id}: {'; '.join(transition.violations)}")
            next_states[team_id] = transition.state
            action_events[team_id].extend(transition.events)
            expected_next_index = before[team_id].period_index + 1
            if transition.state.bankrupt and not transition.state.competition_complete and transition.state.period_index < expected_next_index:
                if expected_next_index > self.max_periods - 1:
                    transition.state.competition_complete = True
                    action_events[team_id].append({"event_type": "competition_complete", "period": transition.state.period, "reason": "bankruptcy_during_final_settlement"})
                else:
                    from_period = transition.state.period
                    transition.state.year, transition.state.quarter = _period_from_index(expected_next_index)
                    action_events[team_id].append({"event_type": "quarter_advanced_after_bankruptcy", "from_period": from_period, "to_period": transition.state.period})
            rewards[team_id] = transition.state.owner_equity_wan - before[team_id].owner_equity_wan
            infos[team_id] = {"events": copy.deepcopy(action_events[team_id]), "bankrupt": transition.state.bankrupt, "balance_gap_wan": transition.state.balance_gap_wan}
        self.states = next_states
        all_complete = all(state.competition_complete for state in self.states.values())
        all_inactive = all(state.bankrupt or state.competition_complete for state in self.states.values())
        self.terminated = all_inactive if self.stop_when_all_bankrupt else all_complete
        return ArenaStep(self._observations(), rewards, self.terminated, infos)

    def final_results(self) -> dict[str, Any]:
        rows = []
        for state in self.states.values():
            assets = {"markets": state.markets, "products": state.products, "iso": state.iso, "purchased_factories": [row["name"] for row in state.factories if row.get("ownership") == "purchased"], "completed_lines": [row["line_type"] for row in state.production_lines]}
            rows.append({"team_id": state.team_id, "owner_equity_wan": state.owner_equity_wan, "development_potential": development_potential(assets, self.dynamics.rules), "bankrupt": state.bankrupt, "bankruptcy_period": state.bankruptcy_period, "cash_wan": state.cash_wan, "reports": len(state.reports)})
        return {"match_id": self.dynamics.rules.get("match_id"), "sandbox_version": FULL_SANDBOX_VERSION, "ranking": rank_final_states(rows, self.dynamics.rules), "bankruptcies": [row for row in rows if row["bankrupt"]], "states": rows, "order_log": copy.deepcopy(self.order_log), "provenance": "simulated"}


class LegacySeededHeuristicPolicy:
    """Small deterministic baseline that exercises the complete environment."""

    def __init__(self, agent_id: str, seed: int = 0) -> None:
        self.agent_id = agent_id
        self.rng = random.Random(int(hashlib.sha256(f"{seed}|{agent_id}".encode()).hexdigest()[:16], 16))

    def act(self, observation: AgentObservation) -> Mapping[str, Any]:
        state = observation.private_state
        if state.get("bankrupt"):
            return {"action_type": "hold"}
        actions: list[dict[str, Any]] = []
        cash = _number(state.get("cash_wan"))
        if not state.get("factories") and cash > 100:
            actions.append({"action_type": "buy_workshop", "parameters": {"factory": "小厂房"}})
        elif not state.get("production_lines") and not state.get("pending_lines") and cash > 80:
            actions.append({"action_type": "buy_product_line", "parameters": {"line_type": "手工线", "product_id": "P1"}})

        assigned = [row for row in state.get("assigned_orders", []) if row.get("status") not in {"已交", "违约"}]
        for order in sorted(assigned, key=lambda row: (row.get("due_period_index", 99), str(row.get("order_id")))):
            product, quantity = str(order.get("product")), _number(order.get("quantity"))
            if _number((state.get("product_inventory") or {}).get(product)) >= quantity:
                actions.append({"action_type": "order_delivery", "parameters": {"order_id": order["order_id"]}})
                break

        visible = list((observation.public_state or {}).get("available_orders") or [])
        qualified = [row for row in visible if row.get("market") in state.get("markets", []) and row.get("product") in state.get("products", []) and row.get("iso") in {None, "", "-", *state.get("iso", [])}]
        if qualified and cash > 30:
            qualified.sort(key=lambda row: (_number(row.get("quantity")), -int(row.get("delivery_term_quarters", 0)), -_number(row.get("total_price_wan")), str(row.get("order_id"))))
            order = self.rng.choice(qualified[: min(8, len(qualified))])
            if str(order.get("order_type")) == "竞单":
                actions.append({"action_type": "auction_bid", "parameters": {"order_id": order["order_id"], "bid_wan": max(1.0, _number(order.get("total_price_wan")) * self.rng.uniform(0.8, 1.1)), "submitted_at": self.rng.random(), "market": order.get("market"), "product": order.get("product")}})
            else:
                actions.append({"action_type": "select_order", "parameters": {"order_id": order["order_id"], "product_advertising": _number((state.get("advertising") or {}).get(f"{order.get('market')}:{order.get('product')}")), "market_advertising": sum(_number(value) for key, value in (state.get("advertising") or {}).items() if key.startswith(f"{order.get('market')}:") ), "total_advertising": sum(_number(value) for value in (state.get("advertising") or {}).values()), "submitted_at": self.rng.random(), "market": order.get("market"), "product": order.get("product")}})

        ready_line = next((row for row in state.get("production_lines", []) if row.get("status") == "ready" and row.get("product_id") in {None, "P1"}), None)
        outstanding_p1 = sum(_number(row.get("quantity")) for row in assigned if row.get("product") == "P1")
        covered_p1 = _number((state.get("product_inventory") or {}).get("P1")) + sum(_number(row.get("quantity")) for row in state.get("pending_production", []) if row.get("product_id") == "P1")
        if ready_line and outstanding_p1 > covered_p1 and cash > 80:
            materials = state.get("material_inventory") or {}
            if _number(materials.get("R1")) < 1:
                actions.append({"action_type": "emergency_purchase", "parameters": {"material_id": "R1", "quantity": 2}})
            actions.append({"action_type": "production", "parameters": {"product_id": "P1", "quantity": 1}})
        if cash < 120 and assigned and not state.get("short_loans"):
            actions.insert(0, {"action_type": "short_loan_borrow", "parameters": {"principal_wan": 100, "term_quarters": 4}})
        return {"actions": actions or [{"action_type": "hold"}]}


class FixedXABaselinePolicy:
    """Cash-aware baseline for the exact XA capital and cost parameters.

    It deliberately limits order commitments to what one production line can
    fulfill.  The policy is a reproducible opponent baseline, not an expert.
    """

    STRATEGIES = ("safe", "balanced", "growth")

    def __init__(self, agent_id: str, seed: int = 0, *, rules: Mapping[str, Any] | None = None) -> None:
        self.agent_id = agent_id
        self.rules = copy.deepcopy(dict(rules or {}))
        self.parameters = dict(self.rules.get("parameters") or {})
        numeric_suffix = agent_id[len(agent_id.rstrip("0123456789")) :]
        comparison_agent_id = numeric_suffix or agent_id
        digest = hashlib.sha256(f"fixed-xa|{seed}|{comparison_agent_id}".encode()).hexdigest()
        self.rng = random.Random(int(digest[:16], 16))
        self.strategy = self.STRATEGIES[int(digest[16:24], 16) % len(self.STRATEGIES)]

    def _claim(self, order: Mapping[str, Any], state: Mapping[str, Any]) -> dict[str, Any]:
        market, product = str(order.get("market")), str(order.get("product"))
        advertising = state.get("advertising") or {}
        common = {
            "order_id": order["order_id"],
            "submitted_at": self.rng.random(),
            "market": market,
            "product": product,
        }
        if str(order.get("order_type")) == "竞单":
            return {
                "action_type": "auction_bid",
                "parameters": {**common, "bid_wan": _number(order.get("total_price_wan")) * 0.9},
            }
        return {
            "action_type": "select_order",
            "parameters": {
                **common,
                "product_advertising": _number(advertising.get(f"{market}:{product}")),
                "market_advertising": sum(_number(value) for key, value in advertising.items() if key.startswith(f"{market}:")),
                "total_advertising": sum(_number(value) for value in advertising.values()),
            },
        }

    def act(self, observation: AgentObservation) -> Mapping[str, Any]:
        state = observation.private_state
        if state.get("bankrupt"):
            return {"action_type": "hold"}
        actions: list[dict[str, Any]] = []
        cash = _number(state.get("cash_wan"))
        planned_cash = cash
        period_index = int(observation.period_index)

        if not state.get("factories") and planned_cash >= 180:
            actions.append({"action_type": "buy_workshop", "parameters": {"factory": "小厂房"}})
            planned_cash -= _number((self.parameters.get("factories") or {}).get("小厂房", {}).get("purchase_wan"), 72)
        if not state.get("production_lines") and not state.get("pending_lines") and planned_cash >= 120:
            actions.append({"action_type": "buy_product_line", "parameters": {"line_type": "手工线", "product_id": "P1"}})
            planned_cash -= _number((self.parameters.get("production_lines") or {}).get("手工线", {}).get("investment_wan"), 40)

        assigned = [row for row in state.get("assigned_orders", []) if row.get("status") not in {"已交", "违约"}]
        inventory = {key: _number(value) for key, value in (state.get("product_inventory") or {}).items()}
        for order in sorted(assigned, key=lambda row: (int(row.get("due_period_index", 99)), str(row.get("order_id")))):
            product, quantity = str(order.get("product")), _number(order.get("quantity"))
            if inventory.get(product, 0.0) >= quantity:
                actions.append({"action_type": "order_delivery", "parameters": {"order_id": order["order_id"]}})
                inventory[product] -= quantity

        pending_p1 = sum(
            _number(row.get("quantity"))
            for row in state.get("pending_production", [])
            if row.get("product_id") == "P1"
        )
        required_p1 = sum(_number(row.get("quantity")) for row in assigned if row.get("product") == "P1")
        shortage = max(0.0, required_p1 - inventory.get("P1", 0.0) - pending_p1)
        ready_line = next(
            (
                row
                for row in state.get("production_lines", [])
                if row.get("status") == "ready" and row.get("product_id") in {None, "P1"}
            ),
            None,
        )
        if shortage > 0 and ready_line is not None:
            materials = {key: _number(value) for key, value in (state.get("material_inventory") or {}).items()}
            missing_r1 = max(0.0, shortage - materials.get("R1", 0.0))
            emergency_cost = missing_r1 * _number((self.parameters.get("materials") or {}).get("R1", {}).get("price_wan"), 8) * 1.5
            process_cost = shortage * _number((self.parameters.get("products") or {}).get("P1", {}).get("process_wan"), 8)
            if planned_cash - emergency_cost - process_cost >= 100:
                if missing_r1:
                    actions.append({"action_type": "emergency_purchase", "parameters": {"material_id": "R1", "quantity": missing_r1}})
                actions.append({"action_type": "production", "parameters": {"product_id": "P1", "quantity": shortage}})
                planned_cash -= emergency_cost + process_cost

        if period_index % 4 == 0 and period_index > 0:
            ad_amount = {"safe": 4.0, "balanced": 8.0, "growth": 12.0}[self.strategy]
            if planned_cash - ad_amount >= 140:
                actions.append({"action_type": "advertising", "parameters": {"market": "本地", "product_id": "P1", "amount_wan": ad_amount}})
                planned_cash -= ad_amount

        if self.strategy in {"balanced", "growth"} and period_index >= 8 and "区域" not in state.get("markets", []) and not any(row.get("kind") == "market" and row.get("target") == "区域" for row in state.get("pending_development", [])) and planned_cash >= 420:
            actions.append({"action_type": "develop_market", "parameters": {"target": "区域"}})
            planned_cash -= _number((self.parameters.get("markets") or {}).get("区域", {}).get("fee_wan_per_year"), 8) / 4

        has_uncovered_commitment = bool(assigned) or pending_p1 > 0 or shortage > 0
        if not has_uncovered_commitment and planned_cash >= 160:
            visible = list((observation.public_state or {}).get("available_orders") or [])
            candidates = [
                order
                for order in visible
                if order.get("market") == "本地"
                and order.get("product") == "P1"
                and order.get("iso") in {None, "", "-"}
                and _number(order.get("quantity")) <= 4
                and int(order.get("due_period_index", 0)) - period_index >= 4
                and _number(order.get("total_price_wan")) >= _number(order.get("quantity")) * 24
            ]
            if candidates:
                candidates.sort(
                    key=lambda row: (
                        _number(row.get("total_price_wan")) - _number(row.get("quantity")) * 20,
                        -_number(row.get("quantity")),
                        str(row.get("order_id")),
                    ),
                    reverse=True,
                )
                shortlist = candidates[: min(6, len(candidates))]
                actions.append(self._claim(self.rng.choice(shortlist), state))

        if planned_cash < 80 and assigned and not state.get("short_loans"):
            actions.insert(0, {"action_type": "short_loan_borrow", "parameters": {"principal_wan": 100, "term_quarters": 4}})
        return {
            "actions": actions or [{"action_type": "hold"}],
            "policy_metadata": {"strategy": self.strategy, "policy": "fixed_XA_cash_aware_v1"},
        }


class SeededHeuristicPolicy:
    """Deterministic diversified baseline for large synthetic competitions."""

    STRATEGIES = ("balanced", "growth", "operations", "finance")

    def __init__(self, agent_id: str, seed: int = 0, *, rules: Mapping[str, Any] | None = None, complexity_profile: str = "standard") -> None:
        if complexity_profile not in COMPLEXITY_PROFILES:
            raise ValueError(f"unknown complexity profile: {complexity_profile}")
        self.agent_id = agent_id
        self.rules = copy.deepcopy(dict(rules or {}))
        self.parameters = dict(self.rules.get("parameters") or {})
        digest = hashlib.sha256(f"{seed}|{agent_id}".encode()).hexdigest()
        self.rng = random.Random(int(digest[:16], 16))
        self.strategy = self.STRATEGIES[int(digest[16:24], 16) % len(self.STRATEGIES)]
        self.complexity_profile = complexity_profile
        self.max_claims = int(COMPLEXITY_PROFILES[complexity_profile]["max_order_claims_per_quarter"])

    def _preferred(self, available: Sequence[str], preferences: Sequence[str]) -> str | None:
        return next((value for value in preferences if value in available), available[0] if available else None)

    def _development_action(self, state: Mapping[str, Any]) -> tuple[dict[str, Any] | None, float]:
        if len(state.get("pending_development", [])) >= 2:
            return None, 0.0
        pending = {(str(row.get("kind")), str(row.get("target"))) for row in state.get("pending_development", [])}
        portfolios = {
            "balanced": (("product", "P2"), ("market", "区域"), ("iso", "ISO9000"), ("product", "P3"), ("market", "国内")),
            "growth": (("product", "P2"), ("market", "区域"), ("product", "P3"), ("market", "国内"), ("iso", "ISO9000"), ("product", "P4"), ("market", "亚洲"), ("iso", "ISO14000"), ("product", "P5")),
            "operations": (("product", "P2"), ("product", "P3"), ("market", "区域"), ("product", "P4"), ("iso", "ISO9000"), ("market", "国内"), ("product", "P5")),
            "finance": (("market", "区域"), ("product", "P2"), ("iso", "ISO9000"), ("market", "国内"), ("product", "P3")),
        }
        collections = {"product": "products", "market": "markets", "iso": "iso"}
        action_names = {"product": "develop_product", "market": "develop_market", "iso": "develop_iso"}
        for kind, target in portfolios[self.strategy]:
            rule = (self.parameters.get(collections[kind]) or {}).get(target)
            if not rule or target in state.get(collections[kind], []) or (kind, target) in pending:
                continue
            installment = _number(rule.get("development_wan_per_quarter"), _number(rule.get("fee_wan_per_year")) / 4)
            return {"action_type": action_names[kind], "parameters": {"target": target}}, installment
        return None, 0.0

    def _order_claim(self, order: Mapping[str, Any], state: Mapping[str, Any]) -> dict[str, Any]:
        advertising = state.get("advertising") or {}
        market, product = str(order.get("market")), str(order.get("product"))
        common = {"order_id": order["order_id"], "submitted_at": self.rng.random(), "market": market, "product": product}
        if str(order.get("order_type")) == "竞单":
            aggressiveness = {"balanced": 0.94, "growth": 1.08, "operations": 1.0, "finance": 0.88}[self.strategy]
            return {"action_type": "auction_bid", "parameters": {**common, "bid_wan": max(1.0, _number(order.get("total_price_wan")) * aggressiveness * self.rng.uniform(0.92, 1.08))}}
        return {"action_type": "select_order", "parameters": {**common, "product_advertising": _number(advertising.get(f"{market}:{product}")), "market_advertising": sum(_number(value) for key, value in advertising.items() if key.startswith(f"{market}:")), "total_advertising": sum(_number(value) for value in advertising.values())}}

    def act(self, observation: AgentObservation) -> Mapping[str, Any]:
        state = observation.private_state
        if state.get("bankrupt"):
            return {"action_type": "hold"}
        actions: list[dict[str, Any]] = []
        cash = _number(state.get("cash_wan"))
        planned_cash = cash
        period_index = int(state.get("period_index", observation.period_index))
        quarter = int(state.get("quarter", period_index % 4 + 1))
        reserve = {"balanced": 140.0, "growth": 120.0, "operations": 140.0, "finance": 180.0}[self.strategy] + (20.0 if self.complexity_profile in {"large", "stress"} else 0.0)

        if period_index == 0 and self.strategy in {"growth", "operations"} and not state.get("long_loans"):
            principal = 150.0 if self.strategy == "growth" else 100.0
            actions.append({"action_type": "long_loan_borrow", "parameters": {"principal_wan": principal, "term_years": 4}})
            planned_cash += principal
        elif cash < reserve and not state.get("short_loans"):
            principal = max(120.0, reserve + 80.0 - cash)
            actions.append({"action_type": "short_loan_borrow", "parameters": {"principal_wan": round(principal, 0), "term_quarters": max(4, 21 - period_index)}})
            planned_cash += principal
        elif state.get("receivables") and cash < reserve * 1.35:
            receivable = min(state["receivables"], key=lambda row: (int(row.get("due_period_index", 99)), str(row.get("receivable_id"))))
            actions.append({"action_type": "receivable_discount", "parameters": {"receivable_id": receivable["receivable_id"]}})
            planned_cash += _number(receivable.get("amount_wan")) * 0.9

        inventory = {key: _number(value) for key, value in (state.get("product_inventory") or {}).items()}
        assigned = [row for row in state.get("assigned_orders", []) if row.get("status") not in {"已交", "违约"}]
        delivered_count = 0
        for order in sorted(assigned, key=lambda row: (int(row.get("due_period_index", 99)), str(row.get("order_id")))):
            product, quantity = str(order.get("product")), _number(order.get("quantity"))
            if inventory.get(product, 0.0) >= quantity:
                actions.append({"action_type": "order_delivery", "parameters": {"order_id": order["order_id"]}})
                inventory[product] -= quantity
                delivered_count += 1
                if delivered_count >= 2:
                    break

        factories = list(state.get("factories") or [])
        factory_rules = self.parameters.get("factories") or {}
        if not factories:
            preferences = {"balanced": ("中厂房", "小厂房", "大厂房"), "growth": ("中厂房", "大厂房", "小厂房"), "operations": ("中厂房", "大厂房", "小厂房"), "finance": ("小厂房", "中厂房", "大厂房")}[self.strategy]
            factory = self._preferred(list(factory_rules), preferences)
            if factory:
                cost = _number(factory_rules[factory].get("purchase_wan"))
                if planned_cash - cost >= reserve:
                    actions.append({"action_type": "buy_workshop", "parameters": {"factory": factory}})
                    planned_cash -= cost
        else:
            capacity = sum(int(row.get("capacity", 0)) for row in factories)
            lines = list(state.get("production_lines") or [])
            pending_lines = list(state.get("pending_lines") or [])
            target_lines = min(capacity, {"balanced": 2, "growth": 2, "operations": 2, "finance": 1}[self.strategy])
            if len(lines) + len(pending_lines) < target_lines:
                line_rules = self.parameters.get("production_lines") or {}
                preferences = {"balanced": ("自动线", "手工线", "租赁线", "柔性线"), "growth": ("自动线", "柔性线", "手工线", "租赁线"), "operations": ("自动线", "手工线", "柔性线", "租赁线"), "finance": ("手工线", "自动线", "租赁线", "柔性线")}[self.strategy]
                line_type = self._preferred(list(line_rules), preferences)
                if line_type:
                    cost = _number(line_rules[line_type].get("investment_wan"))
                    developed_products = list(state.get("products") or ["P1"])
                    product_id = developed_products[(len(lines) + len(pending_lines)) % len(developed_products)]
                    if planned_cash - cost >= reserve:
                        actions.append({"action_type": "buy_product_line", "parameters": {"line_type": line_type, "product_id": product_id}})
                        planned_cash -= cost

        development, installment = self._development_action(state)
        if development and planned_cash - installment >= reserve:
            actions.append(development)
            planned_cash -= installment

        if quarter == 1 and period_index > 0:
            markets = list(state.get("markets") or ["本地"])
            products = list(state.get("products") or ["P1"])
            ad_count = 2 if self.strategy in {"growth", "balanced"} else 1
            for offset in range(min(ad_count, len(markets) * len(products))):
                market = markets[(period_index // 4 + offset + len(self.agent_id)) % len(markets)]
                product = products[(offset + len(self.agent_id)) % len(products)]
                amount = {"balanced": 18.0, "growth": 28.0, "operations": 14.0, "finance": 10.0}[self.strategy]
                if planned_cash - amount < reserve:
                    break
                actions.append({"action_type": "advertising", "parameters": {"market": market, "product_id": product, "amount_wan": amount}})
                planned_cash -= amount

        if period_index % 4 == 0 and planned_cash > reserve + 80 and self.parameters.get("materials"):
            materials = {material_id: float(1 + (int(hashlib.sha256(f"{self.agent_id}|{period_index}|{material_id}".encode()).hexdigest()[:2], 16) % 3)) for material_id in list(self.parameters["materials"])[:1]}
            actions.append({"action_type": "material_order", "parameters": {"materials": materials}})

        outstanding_by_product: dict[str, float] = {}
        for order in assigned:
            product = str(order.get("product"))
            outstanding_by_product[product] = outstanding_by_product.get(product, 0.0) + _number(order.get("quantity"))
        pending_by_product: dict[str, float] = {}
        for job in state.get("pending_production", []):
            product = str(job.get("product_id"))
            pending_by_product[product] = pending_by_product.get(product, 0.0) + _number(job.get("quantity"))
        for target_product in sorted(outstanding_by_product, key=lambda product: (-outstanding_by_product[product], product)):
            shortfall = outstanding_by_product[target_product] - inventory.get(target_product, 0.0) - pending_by_product.get(target_product, 0.0)
            if shortfall <= 0:
                continue
            product_to_make = target_product
            quantity = min(20.0, max(1.0, shortfall))
            product_rule = (self.parameters.get("products") or {}).get(product_to_make) or {}
            for component_id, raw_units in (product_rule.get("bom") or {}).items():
                if str(component_id).startswith("P") and inventory.get(str(component_id), 0.0) < _number(raw_units) * quantity:
                    product_to_make = str(component_id)
                    quantity = min(6.0, max(1.0, _number(raw_units) * quantity - inventory.get(product_to_make, 0.0)))
                    product_rule = (self.parameters.get("products") or {}).get(product_to_make) or {}
                    break
            ready_line = next((row for row in state.get("production_lines", []) if row.get("status") == "ready" and row.get("product_id") in {None, product_to_make}), None)
            if not ready_line or product_to_make not in state.get("products", []):
                continue
            material_inventory = {key: _number(value) for key, value in (state.get("material_inventory") or {}).items()}
            emergency_cost = 0.0
            emergency_actions: list[dict[str, Any]] = []
            feasible = True
            for component_id, raw_units in (product_rule.get("bom") or {}).items():
                required = _number(raw_units) * quantity
                if str(component_id).startswith("R"):
                    missing = max(0.0, required - material_inventory.get(str(component_id), 0.0))
                    if missing:
                        material_rule = (self.parameters.get("materials") or {}).get(str(component_id))
                        if not material_rule:
                            feasible = False
                            break
                        emergency_cost += missing * _number(material_rule.get("price_wan")) * 1.5
                        emergency_actions.append({"action_type": "emergency_purchase", "parameters": {"material_id": component_id, "quantity": missing}})
                elif inventory.get(str(component_id), 0.0) < required:
                    feasible = False
                    break
            process_cost = _number(product_rule.get("process_wan")) * quantity
            if feasible and planned_cash - emergency_cost - process_cost >= reserve:
                actions.extend(emergency_actions)
                actions.append({"action_type": "production", "parameters": {"product_id": product_to_make, "quantity": quantity}})
                planned_cash -= emergency_cost + process_cost
                break

        visible = list((observation.public_state or {}).get("available_orders") or [])
        qualified = [row for row in visible if row.get("market") in state.get("markets", []) and row.get("product") in state.get("products", []) and row.get("iso") in {None, "", "-", *state.get("iso", [])} and int(row.get("due_period_index", 99)) > period_index + 1]
        current_commitment = sum(_number(row.get("quantity")) for row in assigned)
        capacity_factor = max(1, len(state.get("production_lines", [])) + len(state.get("pending_lines", [])))
        claim_budget = max(0, min(self.max_claims, int((capacity_factor * 12 - current_commitment) // 2)))
        if qualified and claim_budget and planned_cash > reserve:
            def desirability(order: Mapping[str, Any]) -> tuple[float, str]:
                direct_cost = _number((self.parameters.get("products") or {}).get(str(order.get("product")), {}).get("direct_cost_wan"), 1)
                value = _number(order.get("total_price_wan")) - direct_cost * _number(order.get("quantity"))
                stable_noise = int(hashlib.sha256(f"{self.agent_id}|{order.get('order_id')}".encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
                return (value + stable_noise * 80 - _number(order.get("quantity")) * 2, str(order.get("order_id")))
            qualified.sort(key=desirability, reverse=True)
            candidate_pool = qualified[: min(len(qualified), max(12, claim_budget * 8))]
            chosen: list[Mapping[str, Any]] = []
            while candidate_pool and len(chosen) < claim_budget:
                index = self.rng.randrange(min(len(candidate_pool), 12))
                chosen.append(candidate_pool.pop(index))
            for order in chosen:
                if str(order.get("order_type")) == "竞单":
                    fee = _number((self.rules.get("financial_rules") or {}).get("auction_bid_fee_wan"), 10)
                    if planned_cash - fee < reserve:
                        continue
                    planned_cash -= fee
                actions.append(self._order_claim(order, state))

        return {"actions": actions or [{"action_type": "hold"}], "policy_metadata": {"strategy": self.strategy, "complexity_profile": self.complexity_profile}}


def write_simulated_match(output_dir: Path, *, rules: Mapping[str, Any], orders: Sequence[Mapping[str, Any]], arena: FullCompetitionArena | None = None) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "format_version": "goai_simulated_match_v1.0",
        "match_id": rules.get("match_id"),
        "sandbox_version": FULL_SANDBOX_VERSION,
        "rule_pack_id": rules.get("rule_pack_id"),
        "parent_rule_pack_id": rules.get("parent_rule_pack_id"),
        "source_match_id": (rules.get("generation") or {}).get("source_match_id"),
        "generation_seed": (rules.get("generation") or {}).get("seed"),
        "provenance": "simulated",
        "training_eligible": False,
        "truth_policy": "Generated rules, orders, events, reports and rankings are simulation artifacts, not historical facts.",
    }
    (output_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output_dir / "rules.json").write_text(json.dumps(rules, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output_dir / "global_orders.jsonl").write_text("".join(json.dumps(dict(row), ensure_ascii=False, sort_keys=True) + "\n" for row in orders), encoding="utf-8")
    if arena is not None:
        (output_dir / "results.json").write_text(json.dumps(arena.final_results(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (output_dir / "teams.jsonl").write_text("".join(json.dumps({"match_id": state.match_id, "team_id": state.team_id, "status": "破产" if state.bankrupt else "完成", "bankruptcy_period": state.bankruptcy_period, "provenance": "simulated"}, ensure_ascii=False, sort_keys=True) + "\n" for state in arena.states.values()), encoding="utf-8")
        (output_dir / "states.jsonl").write_text("".join(json.dumps(state.to_dict(), ensure_ascii=False, sort_keys=True) + "\n" for state in arena.states.values()), encoding="utf-8")
        (output_dir / "reports.jsonl").write_text("".join(json.dumps(report, ensure_ascii=False, sort_keys=True) + "\n" for state in arena.states.values() for report in state.reports), encoding="utf-8")
        (output_dir / "events.jsonl").write_text("".join(json.dumps({"match_id": state.match_id, "team_id": state.team_id, "sequence": index, "provenance": "simulated", **event}, ensure_ascii=False, sort_keys=True) + "\n" for state in arena.states.values() for index, event in enumerate(state.journal, 1)), encoding="utf-8")
        (output_dir / "order_log.jsonl").write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in arena.order_log), encoding="utf-8")
