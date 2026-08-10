"""Rolling robust decision policy for the one enterprise owned by the user.

The competition arena may contain many simulated opponent policies, but this
module controls exactly one enterprise.  It consumes only that enterprise's
private state and released public information.  Referee truth and opponent
private states are intentionally absent from every planning interface.
"""

from __future__ import annotations

import copy
import hashlib
import itertools
import math
import random
from dataclasses import dataclass, fields
from statistics import mean
from typing import Any, Mapping, Sequence

from .decision_system import AgentObservation
from .full_sandbox import FinancialSandboxState, FullFinancialDynamics
from .global_rules import development_potential


OWNED_AGENT_VERSION = "owned_enterprise_complex_rolling_agent_v0.3"
COMPLEX_PLANNER_VERSION = "complex_business_portfolio_planner_v1.0"


def _number(value: Any, default: float = 0.0) -> float:
    return float(value) if isinstance(value, (int, float)) else default


@dataclass(frozen=True)
class RobustAgentConfig:
    """Risk and search controls for one owned enterprise."""

    horizon_quarters: int = 8
    scenario_count: int = 64
    max_candidate_orders: int = 12
    max_order_claims_per_quarter: int = 3
    max_parallel_development: int = 3
    max_new_lines_per_quarter: int = 3
    max_production_actions_per_quarter: int = 8
    max_delivery_actions_per_quarter: int = 10
    max_advertising_pairs: int = 3
    production_batch_units: float = 1.0
    minimum_cash_reserve_wan: float = 60.0
    growth_cash_reserve_wan: float = 120.0
    max_bankruptcy_probability: float = 0.10
    max_default_probability: float = 0.05
    tail_fraction: float = 0.20
    downside_weight: float = 0.60
    bankruptcy_penalty: float = 1500.0
    default_penalty: float = 500.0
    operating_profile: str = "balanced"
    enable_information_purchase: bool = True
    information_budget_wan: float = 10.0

    def __post_init__(self) -> None:
        if self.horizon_quarters <= 0 or self.scenario_count <= 0:
            raise ValueError("planning horizon and scenario count must be positive")
        if self.max_candidate_orders <= 0 or self.max_order_claims_per_quarter <= 0:
            raise ValueError("candidate and claim limits must be positive")
        if min(self.max_parallel_development, self.max_new_lines_per_quarter, self.max_production_actions_per_quarter, self.max_delivery_actions_per_quarter, self.max_advertising_pairs) <= 0:
            raise ValueError("complex planning limits must be positive")
        if not 0 < self.tail_fraction <= 1:
            raise ValueError("tail_fraction must be in (0, 1]")
        if self.operating_profile not in {"balanced", "growth", "operations", "finance"}:
            raise ValueError("unsupported operating_profile")


@dataclass(frozen=True)
class OrderBundleEvaluation:
    candidate_id: str
    order_ids: tuple[str, ...]
    feasible: bool
    objective: float
    mean_terminal_score: float
    downside_terminal_score: float
    bankruptcy_probability: float
    default_probability: float
    minimum_cash_wan: float
    expected_orders_won: float
    scenario_count: int
    violations: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "order_ids": list(self.order_ids),
            "feasible": self.feasible,
            "objective": self.objective,
            "mean_terminal_score": self.mean_terminal_score,
            "downside_terminal_score": self.downside_terminal_score,
            "bankruptcy_probability": self.bankruptcy_probability,
            "default_probability": self.default_probability,
            "minimum_cash_wan": self.minimum_cash_wan,
            "expected_orders_won": self.expected_orders_won,
            "scenario_count": self.scenario_count,
            "violations": list(self.violations),
        }


class PartialOpponentModel:
    """Scenario model derived only from public allocation outcomes."""

    COMPETITION_LEVELS = (
        ("quiet", 0.68, 0.90),
        ("normal", 0.40, 1.00),
        ("crowded", 0.20, 1.12),
    )

    def __init__(self, public_state: Mapping[str, Any], agent_id: str) -> None:
        results = list(public_state.get("public_order_results") or [])
        decided = [row for row in results if row.get("winner_team_id")]
        own_wins = sum(str(row.get("winner_team_id")) == agent_id for row in decided)
        self.observed_decisions = len(decided)
        self.own_public_win_rate = own_wins / len(decided) if decided else None
        self.public_winner_counts: dict[str, int] = {}
        for row in decided:
            winner = str(row.get("winner_team_id"))
            self.public_winner_counts[winner] = self.public_winner_counts.get(winner, 0) + 1

    def strongest_public_opponent(self, agent_id: str) -> str | None:
        candidates = [(count, team_id) for team_id, count in self.public_winner_counts.items() if team_id != agent_id]
        return max(candidates, default=(0, None))[1]

    def win_probability(self, order: Mapping[str, Any], level: tuple[str, float, float], advertising_wan: float) -> float:
        _, base, _ = level
        if str(order.get("order_type")) == "竞单":
            base *= 0.72
        ad_factor = min(1.6, 0.75 + math.log1p(max(0.0, advertising_wan)) / 4)
        learned = 1.0
        if self.own_public_win_rate is not None:
            learned = 0.65 + min(0.70, self.own_public_win_rate)
        return min(0.92, max(0.05, base * ad_factor * learned))


class RobustOrderPlanner:
    """Enumerate order bundles and rank them across hidden-opponent scenarios."""

    def __init__(self, rules: Mapping[str, Any], config: RobustAgentConfig, *, seed: int) -> None:
        self.rules = copy.deepcopy(dict(rules))
        self.parameters = dict(self.rules.get("parameters") or {})
        self.financial_rules = dict(self.rules.get("financial_rules") or {})
        self.config = config
        self.seed = seed

    def _qualified_orders(self, observation: AgentObservation, state: Mapping[str, Any]) -> list[Mapping[str, Any]]:
        period_index = observation.period_index
        markets = set(state.get("markets") or [])
        products = set(state.get("products") or [])
        iso = set(state.get("iso") or []) | {None, "", "-"}
        output = []
        for order in observation.public_state.get("available_orders") or []:
            if order.get("market") not in markets or order.get("product") not in products or order.get("iso") not in iso:
                continue
            product = str(order.get("product"))
            matching_lines = [
                row
                for row in list(state.get("production_lines") or []) + list(state.get("pending_lines") or [])
                if row.get("line_type") == "柔性线" or row.get("product_id") in {None, product}
            ]
            inventory = _number((state.get("product_inventory") or {}).get(product))
            if not matching_lines and inventory < _number(order.get("quantity")):
                continue
            # Allocation happens before the same step's quarter advance.  An
            # order due in the immediately following period would default
            # before the winner gets another action opportunity.
            minimum_lead = 2
            if inventory < _number(order.get("quantity")):
                lead_options = []
                for line in matching_lines:
                    line_rule = (self.parameters.get("production_lines") or {}).get(str(line.get("line_type")), {})
                    lead_options.append(
                        max(0, int(line.get("remaining_install_quarters", 0)))
                        + max(1, int(line_rule.get("production_quarters", 1)))
                        + 2
                    )
                minimum_lead = min(lead_options)
            if int(order.get("due_period_index", 99)) - period_index < minimum_lead:
                continue
            quantity = _number(order.get("quantity"))
            direct = _number((self.parameters.get("products") or {}).get(product, {}).get("direct_cost_wan"))
            margin = _number(order.get("total_price_wan")) - direct * quantity
            if quantity > 0 and margin > 0:
                output.append(order)
        output.sort(key=self._standalone_value, reverse=True)
        return output[: self.config.max_candidate_orders]

    def _standalone_value(self, order: Mapping[str, Any]) -> tuple[float, str]:
        product = str(order.get("product"))
        quantity = _number(order.get("quantity"))
        direct = _number((self.parameters.get("products") or {}).get(product, {}).get("direct_cost_wan"))
        margin = _number(order.get("total_price_wan")) - direct * quantity
        slack = int(order.get("due_period_index", 99)) - int(order.get("release_period_index", 0))
        bid_fee = _number(self.financial_rules.get("auction_bid_fee_wan"), 10) if str(order.get("order_type")) == "竞单" else 0.0
        return (margin - bid_fee + min(slack, 8) * 1.5 - quantity * 2, str(order.get("order_id")))

    def _candidate_bundles(self, orders: Sequence[Mapping[str, Any]]) -> list[tuple[Mapping[str, Any], ...]]:
        bundles: list[tuple[Mapping[str, Any], ...]] = [tuple()]
        maximum = min(self.config.max_order_claims_per_quarter, len(orders))
        for size in range(1, maximum + 1):
            bundles.extend(
                bundle
                for bundle in itertools.combinations(orders, size)
                if sum(_number(order.get("quantity")) for order in bundle) <= 18
            )
        return bundles

    def _base_potential(self, state: Mapping[str, Any]) -> float:
        assets = {
            "markets": list(state.get("markets") or []),
            "products": list(state.get("products") or []),
            "iso": list(state.get("iso") or []),
            "purchased_factories": [row.get("name") for row in state.get("factories") or [] if row.get("ownership") == "purchased"],
            "completed_lines": [row.get("line_type") for row in state.get("production_lines") or []],
        }
        return development_potential(assets, self.rules)

    def _capacity_before_due(self, state: Mapping[str, Any], product: str, due_index: int, now: int) -> float:
        horizon = max(0, min(self.config.horizon_quarters, due_index - now))
        capacity = _number((state.get("product_inventory") or {}).get(product))
        for line in state.get("production_lines") or []:
            if line.get("line_type") != "柔性线" and line.get("product_id") not in {None, product}:
                continue
            line_rule = (self.parameters.get("production_lines") or {}).get(str(line.get("line_type")), {})
            duration = max(1, int(line_rule.get("production_quarters", 1)))
            capacity += (horizon // duration) * self.config.production_batch_units
        for line in state.get("pending_lines") or []:
            if line.get("line_type") != "柔性线" and line.get("product_id") not in {None, product}:
                continue
            ready_after = max(0, int(line.get("remaining_install_quarters", 0)))
            line_rule = (self.parameters.get("production_lines") or {}).get(str(line.get("line_type")), {})
            duration = max(1, int(line_rule.get("production_quarters", 1)))
            capacity += (max(0, horizon - ready_after) // duration) * self.config.production_batch_units
        return capacity

    def _schedule_feasible(self, state: Mapping[str, Any], orders: Sequence[Mapping[str, Any]], now: int) -> bool:
        """Conservatively validate a joint multi-product production schedule.

        Flexible-line capacity is shared once across all products.  This avoids
        the optimistic error of counting the same flexible line independently
        for every product in an order bundle.
        """

        active = [row for row in orders if row.get("status") not in {"已交", "违约"}]
        if not active:
            return True
        inventory = {str(key): _number(value) for key, value in (state.get("product_inventory") or {}).items()}
        pending_by_product: dict[str, list[tuple[int, float]]] = {}
        busy_until: dict[str, int] = {}
        for job in state.get("pending_production") or []:
            product = str(job.get("product_id"))
            ready_after = max(0, int(job.get("remaining_quarters", 0)))
            pending_by_product.setdefault(product, []).append((ready_after, _number(job.get("quantity"))))
            busy_until[str(job.get("line_id"))] = max(busy_until.get(str(job.get("line_id")), 0), ready_after)

        lines = []
        for line in state.get("production_lines") or []:
            item = dict(line)
            item["ready_after"] = busy_until.get(str(line.get("line_id")), 0 if line.get("status") == "ready" else 1)
            lines.append(item)
        for line in state.get("pending_lines") or []:
            item = dict(line)
            item["ready_after"] = max(0, int(line.get("completion_period_index", now)) - now)
            lines.append(item)

        deadlines = sorted({int(row.get("due_period_index", 99)) for row in active})
        for due in deadlines:
            horizon = due - now
            if horizon <= 0:
                available_now = dict(inventory)
                for product, jobs in pending_by_product.items():
                    available_now[product] = available_now.get(product, 0.0) + sum(quantity for ready_after, quantity in jobs if ready_after <= 0)
                if any(
                    sum(_number(row.get("quantity")) for row in active if str(row.get("product")) == product and int(row.get("due_period_index", 99)) <= due) > available_now.get(product, 0.0) + 1e-9
                    for product in {str(row.get("product")) for row in active}
                ):
                    return False
                continue

            required_shortage: dict[str, float] = {}
            for product in {str(row.get("product")) for row in active}:
                required = sum(
                    _number(row.get("quantity"))
                    for row in active
                    if str(row.get("product")) == product and int(row.get("due_period_index", 99)) <= due
                )
                supplied = inventory.get(product, 0.0) + sum(quantity for ready_after, quantity in pending_by_product.get(product, []) if ready_after <= horizon)
                required_shortage[product] = max(0.0, required - supplied)

            total_slots = 0.0
            product_slots = {product: 0.0 for product in required_shortage}
            for line in lines:
                rule = (self.parameters.get("production_lines") or {}).get(str(line.get("line_type")), {})
                duration = max(1, int(rule.get("production_quarters", 1)))
                batch = _number(rule.get("batch_capacity"), 1)
                usable = max(0, horizon - int(line.get("ready_after", 0)))
                # A one-quarter line releases inventory in its start period.
                # Slower lines need one additional action boundary before the
                # first completed batch can be delivered.
                slots = (usable if duration == 1 else max(0, (usable - 1) // duration)) * batch
                total_slots += slots
                for product in product_slots:
                    if line.get("line_type") == "柔性线" or line.get("product_id") in {None, product}:
                        product_slots[product] += slots
            if sum(required_shortage.values()) > total_slots + 1e-9:
                return False
            if any(shortage > product_slots.get(product, 0.0) + 1e-9 for product, shortage in required_shortage.items()):
                return False
        return True

    def _cash_schedule(self, state: Mapping[str, Any], now: int) -> tuple[dict[int, float], dict[int, float]]:
        """Return deterministic cash outflows and inflows for the risk horizon."""

        horizon = self.config.horizon_quarters
        outflows = {step: _number(self.parameters.get("management_fee_per_quarter_wan"), 14) for step in range(1, horizon + 1)}
        inflows = {step: 0.0 for step in range(1, horizon + 1)}

        def step_for(period_index: Any) -> int:
            return max(1, int(period_index) - now + 1)

        for row in state.get("pending_material_orders") or []:
            step = step_for(row.get("arrival_period_index", 10**9))
            if step <= horizon:
                outflows[step] += _number(row.get("total_cost_wan"))
        for row in state.get("pending_lines") or []:
            remaining = _number(row.get("remaining_investment_wan"))
            step = step_for(row.get("next_investment_period_index", 10**9))
            installment = _number((self.parameters.get("production_lines") or {}).get(str(row.get("line_type")), {}).get("investment_wan_per_quarter"), remaining)
            while remaining > 0 and step <= horizon:
                payment = min(remaining, installment)
                outflows[step] += payment
                remaining -= payment
                step += 1
        for row in state.get("pending_development") or []:
            count = int(row.get("remaining_installments", 0))
            step = step_for(row.get("next_payment_period_index", 10**9))
            interval = 4 if row.get("payment_timing") == "year_end" else 1
            for _ in range(count):
                if step <= horizon:
                    outflows[step] += _number(row.get("installment_wan"))
                step += interval
        for row in state.get("short_loans") or []:
            step = step_for(row.get("due_period_index", 10**9))
            if step <= horizon:
                outflows[step] += _number(row.get("principal_wan")) + _number(row.get("interest_wan"))
        for row in state.get("long_loans") or []:
            interest_step = step_for(row.get("next_interest_period_index", 10**9))
            while interest_step <= horizon:
                outflows[interest_step] += _number(row.get("principal_wan")) * _number(row.get("rate"))
                interest_step += 4
            principal_step = step_for(row.get("due_period_index", 10**9))
            if principal_step <= horizon:
                outflows[principal_step] += _number(row.get("principal_wan"))
        for row in state.get("receivables") or []:
            step = step_for(row.get("due_period_index", 10**9))
            if step <= horizon:
                inflows[step] += _number(row.get("amount_wan"))
        if int(state.get("quarter", 1)) == 1 and _number(state.get("tax_payable_wan")) > 0:
            outflows[1] += _number(state.get("tax_payable_wan"))
        for step in range(1, horizon + 1):
            settlement_period = now + step - 1
            if settlement_period % 4 != 3:
                continue
            outflows[step] += sum(_number(row.get("maintenance_wan_per_year")) for row in state.get("production_lines") or [])
            outflows[step] += sum(_number(row.get("annual_rent_wan")) for row in state.get("factories") or [] if row.get("ownership") == "rented")
        return outflows, inflows

    def _evaluate_bundle(
        self,
        bundle: tuple[Mapping[str, Any], ...],
        observation: AgentObservation,
        state: Mapping[str, Any],
        opponent: PartialOpponentModel,
    ) -> OrderBundleEvaluation:
        signature = ",".join(str(row.get("order_id")) for row in bundle) or "hold"
        candidate_id = "bundle-" + hashlib.sha256(signature.encode()).hexdigest()[:10]
        current_equity = _number(state.get("owner_equity_wan"), _number(state.get("cash_wan")))
        current_cash = _number(state.get("cash_wan"))
        potential = self._base_potential(state)
        assigned = [row for row in state.get("assigned_orders") or [] if row.get("status") not in {"已交", "违约"}]
        advertising = sum(_number(value) for value in (state.get("advertising") or {}).values())
        scheduled_outflows, scheduled_inflows = self._cash_schedule(state, observation.period_index)
        scores: list[float] = []
        minimum_cash_values: list[float] = []
        bankruptcies = 0
        defaults = 0
        wins = 0
        for scenario_index in range(self.config.scenario_count):
            digest = hashlib.sha256(f"{self.seed}|{observation.agent_id}|{observation.period_index}|{candidate_id}|{scenario_index}".encode()).hexdigest()
            rng = random.Random(int(digest[:16], 16))
            level = PartialOpponentModel.COMPETITION_LEVELS[scenario_index % len(PartialOpponentModel.COMPETITION_LEVELS)]
            cost_shock = rng.uniform(0.92, 1.18) * level[2]
            # Scenario zero is deliberately adversarial: every submitted claim
            # wins and input costs are high.  A policy must survive the fact
            # that order acquisition itself is uncertain in both directions.
            if scenario_index == 0:
                cost_shock = 1.18 * PartialOpponentModel.COMPETITION_LEVELS[-1][2]
                won = list(bundle)
            else:
                won = [order for order in bundle if rng.random() <= opponent.win_probability(order, level, advertising)]
            wins += len(won)
            bid_fees = sum(_number(self.financial_rules.get("auction_bid_fee_wan"), 10) for row in bundle if str(row.get("order_type")) == "竞单")
            production_cost = 0.0
            margin = 0.0
            scenario_default = not self._schedule_feasible(state, [*assigned, *won], observation.period_index)
            receipt_schedule: dict[int, float] = {}
            production_cash_schedule: dict[int, float] = {}
            for order in sorted(won, key=lambda row: int(row.get("due_period_index", 99))):
                quantity = _number(order.get("quantity"))
                product = str(order.get("product"))
                product_rule = (self.parameters.get("products") or {}).get(product, {})
                direct_cost = _number(product_rule.get("direct_cost_wan")) * quantity * cost_shock
                production_cost += direct_cost
                if scenario_default:
                    margin -= direct_cost + _number(order.get("total_price_wan")) * _number(self.parameters.get("default_penalty_rate"), 0.2)
                else:
                    margin += _number(order.get("total_price_wan")) - direct_cost
                    inventory = _number((state.get("product_inventory") or {}).get(product))
                    if inventory >= quantity:
                        delivery_step = 1
                    else:
                        durations = [
                            max(1, int(((self.parameters.get("production_lines") or {}).get(str(line.get("line_type")), {})).get("production_quarters", 1)))
                            for line in state.get("production_lines") or []
                            if line.get("line_type") == "柔性线" or line.get("product_id") in {None, product}
                        ]
                        delivery_step = (min(durations) if durations else self.config.horizon_quarters) + 1
                    receipt_step = delivery_step + int(order.get("receivable_term_quarters") or 0)
                    production_step = max(1, min(self.config.horizon_quarters, delivery_step - 1))
                    production_cash_schedule[production_step] = production_cash_schedule.get(production_step, 0.0) + direct_cost
                    if receipt_step <= self.config.horizon_quarters:
                        receipt_schedule[receipt_step] = receipt_schedule.get(receipt_step, 0.0) + _number(order.get("total_price_wan"))
            cash = current_cash - bid_fees
            minimum_cash = cash
            for step in range(1, self.config.horizon_quarters + 1):
                cash -= scheduled_outflows.get(step, 0.0) + production_cash_schedule.get(step, 0.0)
                cash += scheduled_inflows.get(step, 0.0) + receipt_schedule.get(step, 0.0)
                minimum_cash = min(minimum_cash, cash)
            terminal_equity = current_equity + margin - bid_fees
            scenario_bankrupt = minimum_cash < 0 or terminal_equity < 0
            bankruptcies += int(scenario_bankrupt)
            defaults += int(scenario_default)
            minimum_cash_values.append(minimum_cash)
            scores.append(0.0 if scenario_bankrupt else terminal_equity * (1 + potential / 100))
        scores.sort()
        tail_count = max(1, math.ceil(len(scores) * self.config.tail_fraction))
        average_score = mean(scores)
        downside = mean(scores[:tail_count])
        bankruptcy_probability = bankruptcies / self.config.scenario_count
        default_probability = defaults / self.config.scenario_count
        violations = []
        hard_violations = []
        if bankruptcy_probability > self.config.max_bankruptcy_probability:
            violations.append("bankruptcy_probability_above_limit")
            hard_violations.append("bankruptcy_probability_above_limit")
        if default_probability > self.config.max_default_probability:
            violations.append("default_probability_above_limit")
            hard_violations.append("default_probability_above_limit")
        if min(minimum_cash_values) < 0:
            hard_violations.append("negative_cash_in_stress_scenario")
        if min(minimum_cash_values) < self.config.minimum_cash_reserve_wan:
            violations.append("cash_reserve_below_target")
        objective = (
            average_score
            - self.config.downside_weight * max(0.0, average_score - downside)
            - self.config.bankruptcy_penalty * bankruptcy_probability
            - self.config.default_penalty * default_probability
        )
        # The empty bundle remains an admissible fallback even when inherited
        # commitments already violate a risk target.
        feasible = not hard_violations or not bundle
        return OrderBundleEvaluation(
            candidate_id=candidate_id,
            order_ids=tuple(str(row.get("order_id")) for row in bundle),
            feasible=feasible,
            objective=round(objective, 6),
            mean_terminal_score=round(average_score, 6),
            downside_terminal_score=round(downside, 6),
            bankruptcy_probability=round(bankruptcy_probability, 6),
            default_probability=round(default_probability, 6),
            minimum_cash_wan=round(min(minimum_cash_values), 6),
            expected_orders_won=round(wins / self.config.scenario_count, 6),
            scenario_count=self.config.scenario_count,
            violations=tuple(violations),
        )

    def plan(self, observation: AgentObservation, projected_state: Mapping[str, Any] | None = None) -> dict[str, Any]:
        state = dict(projected_state or observation.private_state)
        opponent = PartialOpponentModel(observation.public_state, observation.agent_id)
        orders = self._qualified_orders(observation, state)
        by_id = {str(row.get("order_id")): row for row in orders}
        evaluations = [self._evaluate_bundle(bundle, observation, state, opponent) for bundle in self._candidate_bundles(orders)]
        evaluations.sort(key=lambda row: (not row.feasible, -row.objective, row.candidate_id))
        selected = evaluations[0]
        return {
            "selected": selected,
            "selected_orders": [by_id[order_id] for order_id in selected.order_ids],
            "evaluations": evaluations,
            "opponent_model": {
                "input_scope": "released_public_order_results_only",
                "observed_decisions": opponent.observed_decisions,
                "own_public_win_rate": opponent.own_public_win_rate,
                "strongest_public_opponent": opponent.strongest_public_opponent(observation.agent_id),
            },
        }


@dataclass(frozen=True)
class ComplexBusinessPlanEvaluation:
    candidate_id: str
    strategy: str
    feasible: bool
    objective: float
    projected_cash_wan: float
    safe_cash_wan: float
    projected_equity_wan: float
    future_development_potential: float
    commitment_coverage: float
    demand_readiness: float
    action_domains: tuple[str, ...]
    accepted_actions: tuple[Mapping[str, Any], ...]
    rejected_actions: tuple[Mapping[str, Any], ...]
    violations: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "strategy": self.strategy,
            "feasible": self.feasible,
            "objective": self.objective,
            "projected_cash_wan": self.projected_cash_wan,
            "safe_cash_wan": self.safe_cash_wan,
            "projected_equity_wan": self.projected_equity_wan,
            "future_development_potential": self.future_development_potential,
            "commitment_coverage": self.commitment_coverage,
            "demand_readiness": self.demand_readiness,
            "action_domains": list(self.action_domains),
            "accepted_actions": [copy.deepcopy(dict(row)) for row in self.accepted_actions],
            "rejected_actions": [copy.deepcopy(dict(row)) for row in self.rejected_actions],
            "violations": list(self.violations),
        }


class ComplexBusinessPlanner:
    """Generate multi-domain operating portfolios from the current information set.

    The planner coordinates finance, qualifications, factories, several lines,
    materials, production, delivery and advertising in one quarterly decision.
    It does not read final order ownership, future orders or opponent private
    state.  VPD is deliberately absent from selection and remains an offline
    acceptance metric for comparing complete Agent and human trajectories.
    """

    ACTION_DOMAINS = {
        "short_loan_borrow": "finance", "long_loan_borrow": "finance", "receivable_discount": "finance",
        "develop_product": "qualification", "develop_market": "qualification", "develop_iso": "qualification",
        "buy_workshop": "capacity", "rent_workshop": "capacity", "buy_product_line": "capacity", "convert_product_line": "capacity",
        "material_order": "supply", "emergency_purchase": "supply", "emergency_product_purchase": "supply",
        "production": "production", "order_delivery": "fulfillment", "advertising": "market",
    }

    def __init__(self, rules: Mapping[str, Any], config: RobustAgentConfig, *, seed: int) -> None:
        self.rules = copy.deepcopy(dict(rules))
        self.parameters = dict(self.rules.get("parameters") or {})
        self.financial_rules = dict(self.rules.get("financial_rules") or {})
        self.config = config
        self.seed = seed
        self.dynamics = FullFinancialDynamics(self.rules)

    @staticmethod
    def _restore_state(payload: Mapping[str, Any]) -> FinancialSandboxState:
        names = {item.name for item in fields(FinancialSandboxState)}
        return FinancialSandboxState(**{name: copy.deepcopy(payload[name]) for name in names if name in payload})

    @staticmethod
    def _signature(actions: Sequence[Mapping[str, Any]]) -> str:
        return repr([(row.get("action_type"), sorted(dict(row.get("parameters") or {}).items())) for row in actions])

    def _demand_signals(self, observation: AgentObservation) -> dict[str, Any]:
        product_value: dict[str, float] = {}
        market_value: dict[str, float] = {}
        iso_value: dict[str, float] = {}
        pair_value: dict[tuple[str, str], float] = {}
        visible = list(observation.public_state.get("available_orders") or [])
        assigned = [row for row in observation.private_state.get("assigned_orders") or [] if row.get("status") not in {"已交", "违约"}]
        for order, weight in [*((row, 1.0) for row in visible), *((row, 2.5) for row in assigned)]:
            product = str(order.get("product"))
            market = str(order.get("market"))
            quantity = _number(order.get("quantity"))
            direct = _number((self.parameters.get("products") or {}).get(product, {}).get("direct_cost_wan")) * quantity
            value = max(1.0, _number(order.get("total_price_wan")) - direct) * weight
            product_value[product] = product_value.get(product, 0.0) + value
            market_value[market] = market_value.get(market, 0.0) + value
            pair_value[(market, product)] = pair_value.get((market, product), 0.0) + value
            iso = order.get("iso")
            if iso not in {None, "", "-"}:
                iso_value[str(iso)] = iso_value.get(str(iso), 0.0) + value
        planning_prior = not visible and not assigned
        if planning_prior:
            # Before the first yearly order release, a human team still knows
            # the rule universe and must establish a minimum operating loop.
            # These values are rule-based priors, never future order records.
            product_priors = (120.0, 90.0, 55.0)
            market_priors = (120.0, 80.0, 45.0)
            products = list((self.parameters.get("products") or {}).keys())[: len(product_priors)]
            markets = list((self.parameters.get("markets") or {}).keys())[: len(market_priors)]
            for product, value in zip(products, product_priors):
                product_value[product] = value
            for market, value in zip(markets, market_priors):
                market_value[market] = value
            for index, product in enumerate(products):
                if markets:
                    pair_value[(markets[min(index, len(markets) - 1)], product)] = product_priors[index]
        return {
            "visible": visible,
            "assigned": assigned,
            "product_value": product_value,
            "market_value": market_value,
            "iso_value": iso_value,
            "pair_value": pair_value,
            "planning_prior": planning_prior,
        }

    def _near_term_obligations(self, state: Mapping[str, Any]) -> float:
        now = int(state.get("period_index", 0))
        horizon = min(self.config.horizon_quarters, max(0, 20 - now))
        total = _number(self.parameters.get("management_fee_per_quarter_wan"), 14) * horizon
        total += sum(
            _number(row.get("installment_wan")) * min(int(row.get("remaining_installments", 0)), horizon)
            for row in state.get("pending_development") or []
        )
        total += sum(
            _number(row.get("total_cost_wan"))
            for row in state.get("pending_material_orders") or []
            if int(row.get("arrival_period_index", 99)) <= now + horizon
        )
        total += sum(_number(row.get("remaining_investment_wan")) for row in state.get("pending_lines") or [])
        total += sum(
            _number(row.get("principal_wan")) + _number(row.get("interest_wan"))
            for row in state.get("short_loans") or []
            if int(row.get("due_period_index", 99)) <= now + horizon
        )
        if horizon >= 4:
            total += sum(_number(row.get("maintenance_wan_per_year")) for row in state.get("production_lines") or [])
            total += sum(_number(row.get("annual_rent_wan")) for row in state.get("factories") or [] if row.get("ownership") == "rented")
            total += sum(_number(row.get("principal_wan")) * _number(row.get("rate")) for row in state.get("long_loans") or [])
        return total

    def _finance_actions(self, state: Mapping[str, Any], *, expansion: bool = False) -> list[Mapping[str, Any]]:
        actions: list[Mapping[str, Any]] = []
        cash = _number(state.get("cash_wan"))
        target = self.config.minimum_cash_reserve_wan + min(300.0, self._near_term_obligations(state) * 0.35)
        for receivable in sorted(state.get("receivables") or [], key=lambda row: (int(row.get("due_period_index", 99)), str(row.get("receivable_id")))):
            if cash >= target or len(actions) >= 2:
                break
            actions.append({"action_type": "receivable_discount", "parameters": {"receivable_id": receivable.get("receivable_id")}})
            cash += _number(receivable.get("amount_wan")) * 0.9
        if cash < target and not state.get("short_loans"):
            principal = max(100.0, math.ceil((target - cash + 40.0) / 10.0) * 10.0)
            actions.append({"action_type": "short_loan_borrow", "parameters": {"principal_wan": principal, "term_quarters": 4}})
            cash += principal
        if expansion and int(state.get("quarter", 1)) == 1 and not state.get("long_loans") and cash < self.config.growth_cash_reserve_wan + 450:
            principal = 200.0 if self.config.operating_profile != "growth" else 300.0
            actions.insert(0, {"action_type": "long_loan_borrow", "parameters": {"principal_wan": principal, "term_years": min(4, max(1, 5 - int(state.get("year", 1)) + 1))}})
        return actions

    def _fulfillment_actions(self, state: Mapping[str, Any]) -> list[Mapping[str, Any]]:
        assigned = sorted(
            [row for row in state.get("assigned_orders") or [] if row.get("status") not in {"已交", "违约"}],
            key=lambda row: (int(row.get("due_period_index", 99)), -_number(row.get("total_price_wan")), str(row.get("order_id"))),
        )
        if not assigned:
            return []
        inventory = {str(key): _number(value) for key, value in (state.get("product_inventory") or {}).items()}
        materials = {str(key): _number(value) for key, value in (state.get("material_inventory") or {}).items()}
        pending: dict[str, float] = {}
        for job in state.get("pending_production") or []:
            product = str(job.get("product_id"))
            pending[product] = pending.get(product, 0.0) + _number(job.get("quantity"))
        required: dict[str, float] = {}
        earliest_due: dict[str, int] = {}
        for order in assigned:
            product = str(order.get("product"))
            required[product] = required.get(product, 0.0) + _number(order.get("quantity"))
            earliest_due[product] = min(earliest_due.get(product, 99), int(order.get("due_period_index", 99)))
        ready_lines = [copy.deepcopy(row) for row in state.get("production_lines") or [] if row.get("status") == "ready"]
        actions: list[Mapping[str, Any]] = []
        production_count = 0
        now = int(state.get("period_index", 0))
        for product in sorted(required, key=lambda value: (earliest_due[value], -required[value], value)):
            shortage = max(0.0, required[product] - inventory.get(product, 0.0) - pending.get(product, 0.0))
            while shortage > 0 and production_count < self.config.max_production_actions_per_quarter:
                line_index = next((index for index, line in enumerate(ready_lines) if line.get("line_type") == "柔性线" or line.get("product_id") in {None, product}), None)
                if line_index is None:
                    break
                line = ready_lines.pop(line_index)
                product_rule = (self.parameters.get("products") or {}).get(product) or {}
                if not product_rule or product not in state.get("products", []):
                    break
                feasible = True
                for component, units in (product_rule.get("bom") or {}).items():
                    quantity = _number(units)
                    component = str(component)
                    if component.startswith("P"):
                        missing = max(0.0, quantity - inventory.get(component, 0.0))
                        if missing:
                            if earliest_due[product] <= now + 2 and component in state.get("products", []):
                                actions.append({"action_type": "emergency_product_purchase", "parameters": {"product_id": component, "quantity": missing}})
                                inventory[component] = inventory.get(component, 0.0) + missing
                            else:
                                feasible = False
                                break
                        inventory[component] -= quantity
                    else:
                        missing = max(0.0, quantity - materials.get(component, 0.0))
                        if missing:
                            actions.append({"action_type": "emergency_purchase", "parameters": {"material_id": component, "quantity": missing}})
                            materials[component] = materials.get(component, 0.0) + missing
                        materials[component] -= quantity
                if not feasible:
                    break
                actions.append({"action_type": "production", "parameters": {"product_id": product, "quantity": 1, "line_type": line.get("line_type")}})
                duration = int((self.parameters.get("production_lines") or {}).get(str(line.get("line_type")), {}).get("production_quarters", 1))
                if duration == 1:
                    inventory[product] = inventory.get(product, 0.0) + 1
                pending[product] = pending.get(product, 0.0) + 1
                shortage -= 1
                production_count += 1
        delivered = 0
        blocked_products: set[str] = set()
        for order in assigned:
            product, quantity = str(order.get("product")), _number(order.get("quantity"))
            if product in blocked_products:
                continue
            if inventory.get(product, 0.0) >= quantity and delivered < self.config.max_delivery_actions_per_quarter:
                actions.append({"action_type": "order_delivery", "parameters": {"order_id": order.get("order_id")}})
                inventory[product] -= quantity
                delivered += 1
            else:
                # Inventory for one product is reserved by earliest due date.
                # Do not consume a partial reserve on a smaller later order.
                blocked_products.add(product)
        return actions

    def _development_actions(self, state: Mapping[str, Any], demand: Mapping[str, Any]) -> list[Mapping[str, Any]]:
        pending = {(str(row.get("kind")), str(row.get("target"))) for row in state.get("pending_development") or []}
        remaining_slots = max(0, self.config.max_parallel_development - len(pending))
        choices: list[tuple[float, Mapping[str, Any]]] = []
        mappings = (
            ("product", "products", "develop_product", demand["product_value"]),
            ("market", "markets", "develop_market", demand["market_value"]),
            ("iso", "iso", "develop_iso", demand["iso_value"]),
        )
        for kind, collection, action_type, values in mappings:
            for target, value in values.items():
                if target in state.get(collection, []) or (kind, target) in pending or target not in (self.parameters.get(collection) or {}):
                    continue
                rule = (self.parameters.get(collection) or {}).get(target) or {}
                remaining = max(0, 20 - int(state.get("period_index", 0)))
                if kind == "product" and int(rule.get("quarters", 1)) > remaining:
                    continue
                if kind in {"market", "iso"}:
                    remaining_year_ends = max(0, 5 - int(state.get("year", 1)) + 1)
                    if int(rule.get("years", 1)) > remaining_year_ends:
                        continue
                choices.append((float(value), {"action_type": action_type, "parameters": {"target": target}}))
        choices.sort(key=lambda row: (-row[0], str(row[1])))
        return [action for _, action in choices[:remaining_slots]]

    def _capacity_actions(self, state: Mapping[str, Any], demand: Mapping[str, Any], *, aggressive: bool) -> list[Mapping[str, Any]]:
        lines = list(state.get("production_lines") or []) + list(state.get("pending_lines") or [])
        factories = list(state.get("factories") or [])
        capacity = sum(int(row.get("capacity", 0)) for row in factories)
        demand_units = sum(_number(row.get("quantity")) for row in demand["assigned"]) + 0.35 * sum(_number(row.get("quantity")) for row in demand["visible"])
        if demand.get("planning_prior"):
            desired_lines = 2 if aggressive else 1
        else:
            desired_lines = min(12 if aggressive else 9, max(1, math.ceil(demand_units / (6 if aggressive else 8))))
        needed = min(self.config.max_new_lines_per_quarter, max(0, desired_lines - len(lines)))
        actions: list[Mapping[str, Any]] = []
        if needed <= 0:
            return actions
        if capacity - len(lines) < needed:
            factory_rules = self.parameters.get("factories") or {}
            cash = _number(state.get("cash_wan"))
            candidates = sorted(
                factory_rules,
                key=lambda name: (
                    int(factory_rules[name].get("capacity", 0)) < needed,
                    -int(factory_rules[name].get("capacity", 0)) if aggressive else int(factory_rules[name].get("capacity", 0)),
                    _number(factory_rules[name].get("purchase_wan")),
                    name,
                ),
            )
            factory = candidates[0] if candidates else None
            if factory:
                action_type = "buy_workshop" if cash > _number(factory_rules[factory].get("purchase_wan")) + self.config.growth_cash_reserve_wan else "rent_workshop"
                actions.append({"action_type": action_type, "parameters": {"factory": factory}})
                capacity += int(factory_rules[factory].get("capacity", 0))
        available_slots = max(0, capacity - len(lines))
        needed = min(needed, available_slots)
        products = [product for product, _ in sorted(demand["product_value"].items(), key=lambda row: (-row[1], row[0])) if product in (self.parameters.get("products") or {})]
        if not products:
            products = list(state.get("products") or [])
        line_rules = self.parameters.get("production_lines") or {}
        remaining = max(0, 20 - int(state.get("period_index", 0)))
        for index in range(needed):
            product = products[index % len(products)] if products else None
            if remaining <= 4 and "租赁线" in line_rules:
                line_type = "租赁线"
            elif len(products) >= 3 and "柔性线" in line_rules:
                line_type = "柔性线"
            elif "自动线" in line_rules:
                line_type = "自动线"
            else:
                line_type = next(iter(line_rules), None)
            if line_type and product:
                actions.append({"action_type": "buy_product_line", "parameters": {"line_type": line_type, "product_id": product}})
        return actions

    def _advertising_actions(self, state: Mapping[str, Any], demand: Mapping[str, Any], *, aggressive: bool) -> list[Mapping[str, Any]]:
        actions = []
        for (market, product), value in sorted(demand["pair_value"].items(), key=lambda row: (-row[1], row[0])):
            if market not in state.get("markets", []) or product not in state.get("products", []):
                continue
            amount = min(40.0 if aggressive else 25.0, max(5.0, round(value / 35.0)))
            actions.append({"action_type": "advertising", "parameters": {"market": market, "product_id": product, "amount_wan": amount}})
            if len(actions) >= self.config.max_advertising_pairs:
                break
        return actions

    def _material_actions(self, state: Mapping[str, Any], demand: Mapping[str, Any]) -> list[Mapping[str, Any]]:
        required: dict[str, float] = {}
        top_products = [product for product, _ in sorted(demand["product_value"].items(), key=lambda row: (-row[1], row[0]))[:3]]
        for product in top_products:
            for component, units in ((self.parameters.get("products") or {}).get(product, {}).get("bom") or {}).items():
                if str(component).startswith("R"):
                    required[str(component)] = required.get(str(component), 0.0) + max(2.0, _number(units) * 3)
        inventory = {str(key): _number(value) for key, value in (state.get("material_inventory") or {}).items()}
        materials = {key: max(0.0, value - inventory.get(key, 0.0)) for key, value in required.items()}
        materials = {key: value for key, value in materials.items() if value > 0}
        return [{"action_type": "material_order", "parameters": {"materials": materials}}] if materials else []

    def _future_potential(self, state: FinancialSandboxState) -> float:
        products = list(state.products)
        markets = list(state.markets)
        iso = list(state.iso)
        for item in state.pending_development:
            collection = {"product": products, "market": markets, "iso": iso}.get(str(item.get("kind")))
            if collection is not None and item.get("target") not in collection:
                collection.append(str(item.get("target")))
        assets = {
            "products": products,
            "markets": markets,
            "iso": iso,
            "purchased_factories": [row.get("name") for row in state.factories if row.get("ownership") == "purchased"],
            "completed_lines": [row.get("line_type") for row in state.production_lines + state.pending_lines if int(row.get("completion_period_index", 99)) <= 19],
        }
        return development_potential(assets, self.rules)

    def _evaluate(self, strategy: str, actions: Sequence[Mapping[str, Any]], observation: AgentObservation, demand: Mapping[str, Any]) -> tuple[ComplexBusinessPlanEvaluation, FinancialSandboxState]:
        projected = self._restore_state(observation.private_state)
        accepted: list[Mapping[str, Any]] = []
        rejected: list[Mapping[str, Any]] = []
        for action in actions:
            transition = self.dynamics.apply(projected, action)
            if transition.status == "success":
                projected = transition.state
                accepted.append(copy.deepcopy(dict(action)))
            else:
                rejected.append({"action": copy.deepcopy(dict(action)), "violations": list(transition.violations)})
        future_potential = self._future_potential(projected)
        safe_cash = projected.cash_wan - self._near_term_obligations(projected.to_dict())
        outstanding = [row for row in projected.assigned_orders if row.get("status") not in {"已交", "违约"}]
        required = sum(_number(row.get("quantity")) for row in outstanding)
        inventory = sum(_number(value) for value in projected.product_inventory.values())
        capacity = inventory
        for line in projected.production_lines + projected.pending_lines:
            line_rule = (self.parameters.get("production_lines") or {}).get(str(line.get("line_type")), {})
            duration = max(1, int(line_rule.get("production_quarters", 1)))
            ready_after = max(0, int(line.get("completion_period_index", projected.period_index)) - projected.period_index)
            capacity += max(0, self.config.horizon_quarters - ready_after) // duration
        coverage = 1.0 if required <= 0 else min(1.0, capacity / required)
        ready_value = total_value = 0.0
        future_products = set(projected.products) | {str(row.get("target")) for row in projected.pending_development if row.get("kind") == "product"}
        future_markets = set(projected.markets) | {str(row.get("target")) for row in projected.pending_development if row.get("kind") == "market"}
        future_iso = set(projected.iso) | {str(row.get("target")) for row in projected.pending_development if row.get("kind") == "iso"}
        for order in demand["visible"]:
            value = max(1.0, _number(order.get("total_price_wan")))
            total_value += value
            if order.get("product") in future_products and order.get("market") in future_markets and order.get("iso") in {None, "", "-", *future_iso}:
                ready_value += value
        readiness = ready_value / total_value if total_value else 1.0
        projected_score = projected.owner_equity_wan * (1 + future_potential / 100)
        domain_count = len({self.ACTION_DOMAINS.get(str(row.get("action_type")), "other") for row in accepted})
        violations = []
        if projected.bankrupt or projected.cash_wan < 0 or projected.owner_equity_wan < 0:
            violations.append("projected_bankruptcy")
        if safe_cash < 0:
            violations.append("near_term_commitment_gap")
        if coverage < 0.85:
            violations.append("assigned_order_capacity_gap")
        if rejected:
            violations.append("contains_rejected_actions")
        risk_penalty = max(0.0, self.config.minimum_cash_reserve_wan - safe_cash) * 4
        objective = projected_score + coverage * 350 + readiness * 180 + domain_count * 12 - risk_penalty - len(rejected) * 120
        candidate_id = "business-" + hashlib.sha256(f"{strategy}|{self._signature(accepted)}".encode()).hexdigest()[:10]
        evaluation = ComplexBusinessPlanEvaluation(
            candidate_id=candidate_id,
            strategy=strategy,
            feasible=not violations,
            objective=round(objective, 6),
            projected_cash_wan=round(projected.cash_wan, 6),
            safe_cash_wan=round(safe_cash, 6),
            projected_equity_wan=round(projected.owner_equity_wan, 6),
            future_development_potential=round(future_potential, 6),
            commitment_coverage=round(coverage, 6),
            demand_readiness=round(readiness, 6),
            action_domains=tuple(sorted({self.ACTION_DOMAINS.get(str(row.get("action_type")), "other") for row in accepted})),
            accepted_actions=tuple(accepted),
            rejected_actions=tuple(rejected),
            violations=tuple(violations),
        )
        return evaluation, projected

    def plan(self, observation: AgentObservation) -> dict[str, Any]:
        state = observation.private_state
        demand = self._demand_signals(observation)
        fulfillment = self._fulfillment_actions(state)
        developments = self._development_actions(state, demand)
        materials = self._material_actions(state, demand)
        capacity = self._capacity_actions(state, demand, aggressive=False)
        aggressive_capacity = self._capacity_actions(state, demand, aggressive=True)
        advertising = self._advertising_actions(state, demand, aggressive=False)
        aggressive_advertising = self._advertising_actions(state, demand, aggressive=True)
        stable_finance = self._finance_actions(state, expansion=False)
        expansion_finance = self._finance_actions(state, expansion=True)
        startup = []
        bootstrap_needed = False
        if demand["planning_prior"]:
            top_product = next(iter(sorted(demand["product_value"], key=lambda key: (-demand["product_value"][key], key))), None)
            top_market = next(iter(sorted(demand["market_value"], key=lambda key: (-demand["market_value"][key], key))), None)
            startup_development = []
            if top_product and top_product not in state.get("products", []):
                startup_development.append({"action_type": "develop_product", "parameters": {"target": top_product}})
            if top_market and top_market not in state.get("markets", []):
                startup_development.append({"action_type": "develop_market", "parameters": {"target": top_market}})
            existing_lines = list(state.get("production_lines") or []) + list(state.get("pending_lines") or [])
            bootstrap_needed = not existing_lines or not state.get("products")
            startup_capacity: list[Mapping[str, Any]] = []
            if not existing_lines:
                factory_rules = self.parameters.get("factories") or {}
                line_rules = self.parameters.get("production_lines") or {}
                factory = "小厂房" if "小厂房" in factory_rules else next(iter(factory_rules), None)
                line_type = "手工线" if "手工线" in line_rules else next(iter(line_rules), None)
                if factory:
                    startup_capacity.append({"action_type": "buy_workshop", "parameters": {"factory": factory}})
                if line_type and top_product:
                    startup_capacity.append({"action_type": "buy_product_line", "parameters": {"line_type": line_type, "product_id": top_product}})
            startup_materials = []
            if top_product:
                bom = (self.parameters.get("products") or {}).get(top_product, {}).get("bom") or {}
                startup_material_quantities = {str(item): _number(units) * 3 for item, units in bom.items() if str(item).startswith("R")}
                if startup_material_quantities:
                    startup_materials.append({"action_type": "material_order", "parameters": {"materials": startup_material_quantities}})
            startup = [*stable_finance, *startup_development, *startup_capacity, *startup_materials]
        candidates = [
            ("stabilize", [*stable_finance, *fulfillment]),
            ("fulfillment_supply", [*stable_finance, *materials, *fulfillment]),
            ("capability_build", [*expansion_finance, *developments, *fulfillment]),
            ("capacity_build", [*expansion_finance, *capacity, *materials, *fulfillment]),
            ("market_capture", [*stable_finance, *advertising, *materials, *fulfillment]),
            ("balanced_portfolio", [*expansion_finance, *developments, *capacity, *materials, *advertising, *fulfillment]),
            ("growth_portfolio", [*expansion_finance, *developments, *aggressive_capacity, *materials, *aggressive_advertising, *fulfillment]),
        ]
        if demand["planning_prior"]:
            candidates.insert(1, ("startup_minimum", startup))
        unique: dict[str, tuple[str, list[Mapping[str, Any]]]] = {}
        for strategy, actions in candidates:
            signature = self._signature(actions)
            unique.setdefault(signature, (strategy, actions))
        evaluated = [self._evaluate(strategy, actions, observation, demand) for strategy, actions in unique.values()]
        feasible = [item for item in evaluated if item[0].feasible]
        if demand["planning_prior"]:
            preferred_strategy = "startup_minimum" if bootstrap_needed else "stabilize"
            preferred = next((item for item in evaluated if item[0].strategy == preferred_strategy), None)
            if preferred is not None and preferred[0].feasible:
                selected, projected = preferred
            else:
                selected, projected = next(item for item in evaluated if item[0].strategy == "stabilize")
        elif feasible:
            feasible.sort(key=lambda item: (-item[0].objective, item[0].candidate_id))
            selected, projected = feasible[0]
        else:
            # Once every growth portfolio violates a hard risk constraint, use
            # the least-commitment stabilizing candidate rather than selecting
            # an infeasible high-growth plan merely because its proxy score is
            # larger.
            selected, projected = next(item for item in evaluated if item[0].strategy == "stabilize")
        evaluated.sort(key=lambda item: (not item[0].feasible, -item[0].objective, item[0].candidate_id))
        return {
            "selected": selected,
            "selected_actions": [copy.deepcopy(dict(row)) for row in selected.accepted_actions],
            "projected_state": projected,
            "evaluations": [row for row, _ in evaluated],
            "demand_summary": {
                "visible_order_count": len(demand["visible"]),
                "outstanding_order_count": len(demand["assigned"]),
                "product_priorities": sorted(demand["product_value"].items(), key=lambda row: (-row[1], row[0]))[:5],
                "market_priorities": sorted(demand["market_value"].items(), key=lambda row: (-row[1], row[0]))[:5],
                "planning_prior_used": bool(demand["planning_prior"]),
            },
            "selection_basis": "hard_constraints_cash_downside_fulfillment_capacity_demand_readiness_and_formal_score_proxy",
            "vpd_role": "offline_acceptance_metric_for_agent_vs_human_complete_trajectory_not_action_selector",
        }


class OwnedEnterpriseRobustPolicy:
    """One deployable enterprise policy with rolling robust order planning."""

    def __init__(
        self,
        agent_id: str,
        seed: int = 0,
        *,
        rules: Mapping[str, Any],
        config: RobustAgentConfig | None = None,
    ) -> None:
        self.agent_id = agent_id
        self.seed = seed
        self.rules = copy.deepcopy(dict(rules))
        self.config = config or RobustAgentConfig()
        self.dynamics = FullFinancialDynamics(self.rules)
        self.business_planner = ComplexBusinessPlanner(self.rules, self.config, seed=seed)
        self.order_planner = RobustOrderPlanner(self.rules, self.config, seed=seed)
        self.decision_history: list[dict[str, Any]] = []
        self.feedback_history: list[dict[str, Any]] = []
        self.information_spend_wan = 0.0

    @staticmethod
    def _restore_state(payload: Mapping[str, Any]) -> FinancialSandboxState:
        names = {item.name for item in fields(FinancialSandboxState)}
        values = {name: copy.deepcopy(payload[name]) for name in names if name in payload}
        return FinancialSandboxState(**values)

    def _project_operating_actions(
        self,
        state: Mapping[str, Any],
        actions: Sequence[Mapping[str, Any]],
    ) -> tuple[FinancialSandboxState, list[Mapping[str, Any]]]:
        projected = self._restore_state(state)
        accepted: list[Mapping[str, Any]] = []
        for action in actions:
            if action.get("action_type") in {"select_order", "auction_bid", "spy_information_purchase"}:
                continue
            transition = self.dynamics.apply(projected, action)
            if transition.status == "success":
                projected = transition.state
                accepted.append(action)
        return projected, accepted

    def _committed_cash_outflow(self, state: Mapping[str, Any]) -> float:
        remaining = max(0, 20 - int(state.get("period_index", 0)))
        horizon = min(self.config.horizon_quarters, remaining)
        total = _number((self.rules.get("parameters") or {}).get("management_fee_per_quarter_wan"), 14) * horizon
        total += sum(
            _number(row.get("installment_wan")) * int(row.get("remaining_installments", 0))
            for row in state.get("pending_development") or []
        )
        for loan in state.get("short_loans") or []:
            if int(loan.get("due_period_index", 99)) <= int(state.get("period_index", 0)) + horizon:
                total += _number(loan.get("principal_wan")) + _number(loan.get("interest_wan"))
        if horizon >= 4:
            total += sum(_number(row.get("maintenance_wan_per_year")) for row in state.get("production_lines") or [])
            total += sum(_number(row.get("annual_rent_wan")) for row in state.get("factories") or [] if row.get("ownership") == "rented")
            total += sum(_number(row.get("principal_wan")) * _number(row.get("rate")) for row in state.get("long_loans") or [])
        return total

    def _prune_operating_actions(
        self,
        state: Mapping[str, Any],
        actions: Sequence[Mapping[str, Any]],
    ) -> tuple[FinancialSandboxState, list[Mapping[str, Any]]]:
        discretionary = {
            "develop_product",
            "develop_market",
            "develop_iso",
            "advertising",
            "buy_workshop",
            "rent_workshop",
            "buy_product_line",
            "convert_product_line",
            "material_order",
        }
        candidates = list(actions)
        while True:
            projected, accepted = self._project_operating_actions(state, candidates)
            safe_cash = projected.cash_wan - self._committed_cash_outflow(projected.to_dict())
            if not projected.bankrupt and safe_cash >= self.config.growth_cash_reserve_wan:
                return projected, accepted
            removable = next((index for index in range(len(candidates) - 1, -1, -1) if candidates[index].get("action_type") in discretionary), None)
            if removable is None:
                return projected, accepted
            candidates.pop(removable)

    def _fulfillment_actions(self, state: Mapping[str, Any]) -> list[Mapping[str, Any]]:
        """Prioritize already-awarded obligations before new discretionary growth."""

        assigned = sorted(
            [row for row in state.get("assigned_orders") or [] if row.get("status") not in {"已交", "违约"}],
            key=lambda row: (int(row.get("due_period_index", 99)), str(row.get("order_id"))),
        )
        if not assigned:
            return []
        actions: list[Mapping[str, Any]] = []
        planned_cash = _number(state.get("cash_wan"))
        if planned_cash < self.config.minimum_cash_reserve_wan + 100:
            receivables = list(state.get("receivables") or [])
            if receivables:
                receivable = min(receivables, key=lambda row: (int(row.get("due_period_index", 99)), str(row.get("receivable_id"))))
                actions.append({"action_type": "receivable_discount", "parameters": {"receivable_id": receivable["receivable_id"]}})
                planned_cash += _number(receivable.get("amount_wan")) * 0.9
            elif not state.get("short_loans"):
                period_index = int(state.get("period_index", 0))
                actions.append(
                    {
                        "action_type": "short_loan_borrow",
                        "parameters": {
                            "principal_wan": 120.0,
                            "term_quarters": max(4, 20 - period_index),
                        },
                    }
                )
                planned_cash += 120.0
        inventory = {key: _number(value) for key, value in (state.get("product_inventory") or {}).items()}
        for order in assigned:
            product, quantity = str(order.get("product")), _number(order.get("quantity"))
            if inventory.get(product, 0.0) >= quantity:
                actions.append({"action_type": "order_delivery", "parameters": {"order_id": order["order_id"]}})
                inventory[product] -= quantity
        pending = {}
        for job in state.get("pending_production") or []:
            product = str(job.get("product_id"))
            pending[product] = pending.get(product, 0.0) + _number(job.get("quantity"))
        required = {}
        for order in assigned:
            product = str(order.get("product"))
            required[product] = required.get(product, 0.0) + _number(order.get("quantity"))
        for product in sorted(required, key=lambda key: min(int(row.get("due_period_index", 99)) for row in assigned if str(row.get("product")) == key)):
            shortage = required[product] - inventory.get(product, 0.0) - pending.get(product, 0.0)
            if shortage <= 0:
                continue
            line = next(
                (
                    row
                    for row in state.get("production_lines") or []
                    if row.get("status") == "ready" and row.get("product_id") in {None, product}
                ),
                None,
            )
            if not line:
                continue
            quantity = min(1.0, shortage, self.config.production_batch_units)
            product_rule = ((self.rules.get("parameters") or {}).get("products") or {}).get(product, {})
            materials = {key: _number(value) for key, value in (state.get("material_inventory") or {}).items()}
            emergency: list[Mapping[str, Any]] = []
            cost = _number(product_rule.get("process_wan")) * quantity
            feasible = True
            for component, units in (product_rule.get("bom") or {}).items():
                required_units = _number(units) * quantity
                if str(component).startswith("P"):
                    if inventory.get(str(component), 0.0) < required_units:
                        feasible = False
                        break
                    continue
                missing = max(0.0, required_units - materials.get(str(component), 0.0))
                if missing:
                    material_rule = ((self.rules.get("parameters") or {}).get("materials") or {}).get(str(component), {})
                    emergency_multiplier = _number((self.rules.get("financial_rules") or {}).get("emergency_material_price_multiplier"), 2)
                    cost += missing * _number(material_rule.get("price_wan")) * emergency_multiplier
                    emergency.append({"action_type": "emergency_purchase", "parameters": {"material_id": component, "quantity": missing}})
            if feasible and planned_cash - cost >= self.config.minimum_cash_reserve_wan * 0.5:
                actions.extend(emergency)
                actions.append({"action_type": "production", "parameters": {"product_id": product, "quantity": quantity}})
            break
        return actions

    def _claim_action(self, order: Mapping[str, Any], state: Mapping[str, Any]) -> dict[str, Any]:
        advertising = state.get("advertising") or {}
        market, product = str(order.get("market")), str(order.get("product"))
        common = {
            "order_id": order["order_id"],
            "submitted_at": random.Random(int(hashlib.sha256(f"{self.seed}|{self.agent_id}|{order['order_id']}".encode()).hexdigest()[:16], 16)).random(),
            "market": market,
            "product": product,
        }
        if str(order.get("order_type")) == "竞单":
            return {"action_type": "auction_bid", "parameters": {**common, "bid_wan": round(_number(order.get("total_price_wan")) * 0.98, 2)}}
        return {
            "action_type": "select_order",
            "parameters": {
                **common,
                "product_advertising": _number(advertising.get(f"{market}:{product}")),
                "market_advertising": sum(_number(value) for key, value in advertising.items() if key.startswith(f"{market}:")),
                "total_advertising": sum(_number(value) for value in advertising.values()),
            },
        }

    def _information_action(self, observation: AgentObservation, opponent_model: Mapping[str, Any]) -> dict[str, Any] | None:
        config = dict((self.rules.get("financial_rules") or {}).get("information_purchase") or {})
        if not self.config.enable_information_purchase or not config.get("enabled"):
            return None
        fee = _number(config.get("fee_wan"), 5)
        if self.information_spend_wan + fee > self.config.information_budget_wan:
            return None
        target = opponent_model.get("strongest_public_opponent")
        if not target:
            return None
        current_year = observation.period_index // 4 + 1
        reports = observation.private_state.get("intelligence_reports") or []
        if any(row.get("target_team_id") == target and str(row.get("period", "")).startswith(f"Y{current_year}Q") for row in reports):
            return None
        self.information_spend_wan += fee
        return {"action_type": "spy_information_purchase", "parameters": {"target_team_id": target}}

    def act(self, observation: AgentObservation) -> Mapping[str, Any]:
        if observation.agent_id != self.agent_id:
            raise ValueError("owned policy received another enterprise's observation")
        if observation.private_state.get("bankrupt"):
            return {"action_type": "hold", "policy_metadata": {"policy": OWNED_AGENT_VERSION}}
        business_plan = self.business_planner.plan(observation)
        projected: FinancialSandboxState = business_plan["projected_state"]
        operating_actions = list(business_plan["selected_actions"])
        if projected.bankrupt:
            operating_actions = [{"action_type": "hold"}]
            projected = self._restore_state(observation.private_state)
        plan = self.order_planner.plan(observation, projected.to_dict())
        selected: OrderBundleEvaluation = plan["selected"]
        actions = list(operating_actions)
        information_action = self._information_action(observation, plan["opponent_model"])
        if information_action:
            actions.append(information_action)
        actions.extend(self._claim_action(order, projected.to_dict()) for order in plan["selected_orders"])
        audit = {
            "period": observation.period,
            "agent_id": self.agent_id,
            "selected_candidate": selected.to_dict(),
            "candidate_count": len(plan["evaluations"]),
            "top_candidates": [row.to_dict() for row in plan["evaluations"][:5]],
            "selected_business_plan": business_plan["selected"].to_dict(),
            "business_candidate_count": len(business_plan["evaluations"]),
            "business_candidates": [row.to_dict() for row in business_plan["evaluations"]],
            "business_demand_summary": business_plan["demand_summary"],
            "selection_basis": business_plan["selection_basis"],
            "vpd_role": business_plan["vpd_role"],
            "opponent_model": plan["opponent_model"],
            "information_scope": "own_private_state_plus_released_public_information_plus_legally_purchased_reports",
        }
        self.decision_history.append(copy.deepcopy(audit))
        return {
            "actions": actions or [{"action_type": "hold"}],
            "policy_metadata": {
                "policy": OWNED_AGENT_VERSION,
                "owned_enterprise_only": True,
                "rolling_horizon_quarters": self.config.horizon_quarters,
                "scenario_count": self.config.scenario_count,
                "planning_audit": audit,
            },
        }

    def observe_feedback(self, feedback: Mapping[str, Any], next_observation: AgentObservation) -> None:
        """Close the online loop without reading any referee-only state."""

        if str(feedback.get("agent_id")) != self.agent_id or next_observation.agent_id != self.agent_id:
            raise ValueError("owned policy received another enterprise's feedback")
        record = {
            "period": feedback.get("period"),
            "action_status": feedback.get("action_status"),
            "action_rejections": copy.deepcopy(list(feedback.get("action_rejections") or [])),
            "reward": feedback.get("reward"),
            "bankrupt": feedback.get("bankrupt"),
            "event_types": [str(row.get("event_type")) for row in feedback.get("events") or []],
            "next_period": next_observation.period,
            "information_scope": "owned_feedback_and_next_owned_observation_only",
        }
        self.feedback_history.append(record)
        if self.decision_history and self.decision_history[-1].get("period") == feedback.get("period"):
            self.decision_history[-1]["feedback"] = copy.deepcopy(record)
