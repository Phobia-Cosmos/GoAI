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
from .full_sandbox import FinancialSandboxState, FullFinancialDynamics, SeededHeuristicPolicy
from .global_rules import development_potential


OWNED_AGENT_VERSION = "owned_enterprise_robust_agent_v0.2_xa_batch_capacity"


def _number(value: Any, default: float = 0.0) -> float:
    return float(value) if isinstance(value, (int, float)) else default


@dataclass(frozen=True)
class RobustAgentConfig:
    """Risk and search controls for one owned enterprise."""

    horizon_quarters: int = 8
    scenario_count: int = 64
    max_candidate_orders: int = 9
    max_order_claims_per_quarter: int = 2
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
                if row.get("product_id") in {None, product}
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
                if len({str(order.get("product")) for order in bundle}) == len(bundle)
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
            if line.get("product_id") not in {None, product}:
                continue
            line_rule = (self.parameters.get("production_lines") or {}).get(str(line.get("line_type")), {})
            duration = max(1, int(line_rule.get("production_quarters", 1)))
            capacity += (horizon // duration) * self.config.production_batch_units
        for line in state.get("pending_lines") or []:
            if line.get("product_id") not in {None, product}:
                continue
            ready_after = max(0, int(line.get("remaining_install_quarters", 0)))
            line_rule = (self.parameters.get("production_lines") or {}).get(str(line.get("line_type")), {})
            duration = max(1, int(line_rule.get("production_quarters", 1)))
            capacity += (max(0, horizon - ready_after) // duration) * self.config.production_batch_units
        return capacity

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
        outstanding_by_product: dict[str, float] = {}
        for row in assigned:
            product = str(row.get("product"))
            outstanding_by_product[product] = outstanding_by_product.get(product, 0.0) + _number(row.get("quantity"))
        advertising = sum(_number(value) for value in (state.get("advertising") or {}).values())
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
            scenario_default = False
            receipt_schedule: dict[int, float] = {}
            cumulative_by_product = dict(outstanding_by_product)
            for order in sorted(won, key=lambda row: int(row.get("due_period_index", 99))):
                quantity = _number(order.get("quantity"))
                product = str(order.get("product"))
                product_rule = (self.parameters.get("products") or {}).get(product, {})
                direct_cost = _number(product_rule.get("direct_cost_wan")) * quantity * cost_shock
                production_cost += direct_cost
                cumulative_by_product[product] = cumulative_by_product.get(product, 0.0) + quantity
                if cumulative_by_product[product] > self._capacity_before_due(state, product, int(order.get("due_period_index", 99)), observation.period_index):
                    scenario_default = True
                    margin -= _number(order.get("total_price_wan")) * _number(self.parameters.get("default_penalty_rate"), 0.2)
                else:
                    margin += _number(order.get("total_price_wan")) - direct_cost
                    inventory = _number((state.get("product_inventory") or {}).get(product))
                    if inventory >= quantity:
                        delivery_step = 1
                    else:
                        durations = [
                            max(1, int(((self.parameters.get("production_lines") or {}).get(str(line.get("line_type")), {})).get("production_quarters", 1)))
                            for line in state.get("production_lines") or []
                            if line.get("product_id") in {None, product}
                        ]
                        delivery_step = (min(durations) if durations else self.config.horizon_quarters) + 1
                    receipt_step = delivery_step + int(order.get("receivable_term_quarters") or 0)
                    if receipt_step <= self.config.horizon_quarters:
                        receipt_schedule[receipt_step] = receipt_schedule.get(receipt_step, 0.0) + _number(order.get("total_price_wan"))
            cash = current_cash - bid_fees - production_cost
            minimum_cash = cash
            pending_installments = [
                [_number(row.get("installment_wan")), int(row.get("remaining_installments", 0))]
                for row in state.get("pending_development") or []
            ]
            management_per_quarter = _number(self.parameters.get("management_fee_per_quarter_wan"), 14)
            for step in range(1, self.config.horizon_quarters + 1):
                cash -= management_per_quarter
                for installment in pending_installments:
                    if installment[1] > 0:
                        cash -= installment[0]
                        installment[1] -= 1
                cash += receipt_schedule.get(step, 0.0)
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
        if bankruptcy_probability > self.config.max_bankruptcy_probability:
            violations.append("bankruptcy_probability_above_limit")
        if default_probability > self.config.max_default_probability:
            violations.append("default_probability_above_limit")
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
        feasible = not violations or not bundle
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
        self.operating_policy = SeededHeuristicPolicy(agent_id, seed, rules=self.rules, complexity_profile="stress")
        self.operating_policy.strategy = self.config.operating_profile
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
        outstanding = [row for row in observation.private_state.get("assigned_orders") or [] if row.get("status") not in {"已交", "违约"}]
        if outstanding:
            operating_actions = self._fulfillment_actions(observation.private_state)
            projected, operating_actions = self._project_operating_actions(observation.private_state, operating_actions)
        else:
            operating_bundle = self.operating_policy.act(observation)
            proposed = [
                copy.deepcopy(action)
                for action in operating_bundle.get("actions", [operating_bundle])
                if action.get("action_type") not in {"select_order", "auction_bid"}
            ]
            if observation.period_index >= 12:
                proposed = [
                    action
                    for action in proposed
                    if action.get("action_type")
                    not in {
                        "develop_product",
                        "develop_market",
                        "develop_iso",
                        "buy_workshop",
                        "rent_workshop",
                        "buy_product_line",
                        "convert_product_line",
                        "advertising",
                    }
                ]
            projected, operating_actions = self._prune_operating_actions(observation.private_state, proposed)
        if projected.bankrupt:
            operating_actions = [{"action_type": "hold"}]
            projected = self._restore_state(observation.private_state)
        plan = self.order_planner.plan(observation, projected.to_dict())
        if outstanding:
            fallback = next(row for row in plan["evaluations"] if not row.order_ids)
            plan["selected"] = fallback
            plan["selected_orders"] = []
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
