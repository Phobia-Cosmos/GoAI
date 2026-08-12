"""XA enterprise strategy profiles reconstructed from observable decision paths.

These policies are calibration actors, not online agents.  They may consume an
enterprise's full historical path and observed order ownership, so their output
must never be presented as a leakage-free decision benchmark.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from .decision_system import AgentObservation
from .full_sandbox import order_is_qualified


HISTORICAL_STRATEGY_VERSION = "xa_historical_strategy_profiles_v1.0"


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _number(value: Any, default: float = 0.0) -> float:
    return float(value) if isinstance(value, (int, float)) else default


def _term(value: Any, default: int = 1) -> int:
    match = re.search(r"\d+", str(value or ""))
    return int(match.group()) if match else default


@dataclass(frozen=True)
class HistoricalStrategyProfile:
    team_id: str
    strategy_class: str
    official_rank: int | None
    bankrupt: bool
    bankruptcy_period: str | None
    owner_equity_wan: float | None
    development_potential: float
    official_score: float | None
    delivered_order_count: int
    defaulted_order_count: int
    action_counts: Mapping[str, int]
    final_assets: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "team_id": self.team_id, "strategy_class": self.strategy_class,
            "official_rank": self.official_rank, "bankrupt": self.bankrupt,
            "bankruptcy_period": self.bankruptcy_period, "owner_equity_wan": self.owner_equity_wan,
            "development_potential": self.development_potential, "official_score": self.official_score,
            "delivered_order_count": self.delivered_order_count, "defaulted_order_count": self.defaulted_order_count,
            "action_counts": dict(self.action_counts), "final_assets": copy.deepcopy(dict(self.final_assets)),
            "provenance": "derived_historical_strategy_profile",
        }


def build_historical_xa_profiles(match_dir: Path) -> tuple[dict[str, HistoricalStrategyProfile], list[dict[str, Any]], list[dict[str, Any]]]:
    """Return profiles, augmented orders and all inverse actions."""

    match_dir = match_dir.resolve()
    actions = _jsonl(match_dir / "inverse_actions.jsonl")
    final_states = {row["team_id"]: row for row in _jsonl(match_dir / "final_states.jsonl")}
    results = json.loads((match_dir / "results.json").read_text(encoding="utf-8"))
    ranking = {row["team_id"]: row for row in results.get("ranking") or []}
    bankruptcies = {row["team_id"]: row["period"] for row in results.get("bankruptcies") or []}
    cash_actions: dict[str, Counter[str]] = defaultdict(Counter)
    team_orders: dict[str, list[dict[str, Any]]] = defaultdict(list)
    delivery_by_order: dict[str, dict[str, Any]] = {}
    for row in actions:
        team_id = str(row.get("team_id") or "")
        if row.get("record_type") == "observed_cash_event":
            cash_actions[team_id][str(row.get("action_type"))] += 1
        elif row.get("record_type") == "order_history_reconstruction":
            team_orders[team_id].append(row)
            delivery_by_order[str(row["order_id"])] = row

    surviving_potentials = sorted(float(row["development_potential"]) for row in ranking.values())
    median_potential = surviving_potentials[len(surviving_potentials) // 2]
    profiles = {}
    for team_id, state in sorted(final_states.items()):
        rank_row = ranking.get(team_id)
        bankrupt = team_id in bankruptcies
        if bankrupt:
            strategy_class = "aggressive_failed"
        elif int(rank_row["rank"]) <= 6:
            strategy_class = "leader_growth"
        elif float(state.get("development_potential", 0)) >= median_potential:
            strategy_class = "balanced_expansion"
        else:
            strategy_class = "conservative_survivor"
        orders = team_orders.get(team_id, [])
        profiles[team_id] = HistoricalStrategyProfile(
            team_id=team_id, strategy_class=strategy_class,
            official_rank=int(rank_row["rank"]) if rank_row else None, bankrupt=bankrupt,
            bankruptcy_period=bankruptcies.get(team_id),
            owner_equity_wan=float(state["owner_equity_wan"]) if isinstance(state.get("owner_equity_wan"), (int, float)) else None,
            development_potential=float(state.get("development_potential", 0)),
            official_score=float(rank_row["official_score"]) if rank_row else None,
            delivered_order_count=sum(row.get("action_type") == "order_delivery" for row in orders),
            defaulted_order_count=sum(row.get("action_type") == "order_default" for row in orders),
            action_counts=dict(cash_actions.get(team_id, {})), final_assets=state.get("assets") or {},
        )

    orders = []
    for source in _jsonl(match_dir / "global_orders.jsonl"):
        row = copy.deepcopy(source)
        year = int(row.get("year") or 1)
        release = (year - 1) * 4
        delivery_terms = int(row.get("delivery_term_quarters") or 1)
        row["release_period_index"] = release
        row["due_period_index"] = min(19, release + delivery_terms - 1)
        history = delivery_by_order.get(str(row["order_id"]))
        row["delivered_period"] = history.get("delivered_period") if history else None
        row["delivered_period_index"] = history.get("delivered_period_index") if history else None
        row["calibration_owner_team_id"] = row.get("final_owner_team_id", row.get("owner_team_id"))
        row["owner_team_id"] = None
        row["status"] = "未分配"
        orders.append(row)
    return profiles, orders, actions


class HistoricalXAProfilePolicy:
    """Replay identifiable historical decisions for one XA enterprise.

    ``conditioned`` uses observed order ownership supplied by the environment.
    ``competitive`` removes ownership and uses the historical annual order
    volume plus market/product preferences to compete again.
    """

    def __init__(
        self,
        team_id: str,
        *,
        rules: Mapping[str, Any],
        profile: HistoricalStrategyProfile,
        inverse_actions: Sequence[Mapping[str, Any]],
        historical_orders: Sequence[Mapping[str, Any]],
        historical_line_types: Mapping[int, str] | None = None,
        mode: str = "conditioned",
        seed: int = 0,
    ) -> None:
        if mode not in {"conditioned", "competitive"}:
            raise ValueError(f"unknown historical policy mode: {mode}")
        self.team_id = team_id
        self.rules = copy.deepcopy(dict(rules))
        self.parameters = dict(self.rules.get("parameters") or {})
        self.profile = profile
        self.mode = mode
        self.seed = seed
        self.schedule: dict[int, list[dict[str, Any]]] = defaultdict(list)
        self.delivery_period = {}
        self.year_order_targets: Counter[int] = Counter()
        self.preference_counts: Counter[tuple[str, str]] = Counter()
        for row in inverse_actions:
            if str(row.get("team_id")) != team_id:
                continue
            if str(row.get("action_type", "")).startswith("develop_") and isinstance(row.get("start_period_index"), int):
                self.schedule[int(row["start_period_index"])].append(copy.deepcopy(dict(row)))
            elif row.get("record_type") == "observed_cash_event" and isinstance(row.get("period_index"), int):
                self.schedule[int(row["period_index"])].append(copy.deepcopy(dict(row)))
            elif row.get("record_type") == "order_history_reconstruction":
                if isinstance(row.get("delivered_period_index"), int):
                    self.delivery_period[str(row["order_id"])] = int(row["delivered_period_index"])
                if isinstance(row.get("award_year"), int):
                    self.year_order_targets[int(row["award_year"])] += 1
                    self.preference_counts[(str(row.get("market")), str(row.get("product")))] += 1
        self.historical_orders = [copy.deepcopy(dict(row)) for row in historical_orders]
        self.historical_line_types = {int(key): str(value) for key, value in (historical_line_types or {}).items()}

    def _conversion_line(self, state: Mapping[str, Any], target: Any, observed_cash_effect_wan: Any) -> Mapping[str, Any] | None:
        """Choose the line most consistent with a partially observed conversion.

        XA cash exports preserve a conversion's charge even when they omit the
        concrete line ID.  A zero-charge conversion is strongest evidence for a
        flexible line, whose formal conversion fee is zero.
        """

        target = str(target or "")
        candidates = [item for item in state.get("production_lines", []) if item.get("status") == "ready" and item.get("product_id") != target]
        if not candidates:
            return None
        observed_fee = abs(_number(observed_cash_effect_wan))
        line_rules = self.parameters.get("production_lines") or {}
        def key(item: Mapping[str, Any]) -> tuple[float, int, str]:
            configured_fee = _number((line_rules.get(str(item.get("line_type"))) or {}).get("conversion_wan_per_quarter"))
            return (abs(configured_fee - observed_fee), 0 if str(item.get("line_type")) == "柔性线" else 1, str(item.get("line_id")))
        return min(candidates, key=key)

    def _advertising_pair(self, state: Mapping[str, Any]) -> tuple[str, str]:
        qualified = [pair for pair, _ in self.preference_counts.most_common() if pair[0] in state.get("markets", []) and pair[1] in state.get("products", [])]
        if qualified:
            return qualified[0]
        return (next(iter(state.get("markets", [])), "本地"), next(iter(state.get("products", [])), "P1"))

    def _translate_historical_actions(self, observation: AgentObservation) -> list[dict[str, Any]]:
        state = observation.private_state
        actions: list[dict[str, Any]] = []
        reserved_receivables: set[str] = set()
        period_rows = self.schedule.get(observation.period_index, [])
        priority = {
            "long_loan_borrow": 0, "short_loan_borrow": 1,
            "develop_product": 2, "develop_market": 2, "develop_iso": 2,
            "factory_rent": 3, "factory_purchase": 3, "production_line_order": 4,
            "material_order": 5, "emergency_material_purchase": 6, "advertising": 7,
            "production_line_conversion": 8, "production": 9,
        }
        for row in sorted(period_rows, key=lambda item: priority.get(str(item.get("action_type")), 99)):
            action_type = str(row.get("action_type"))
            params = row.get("parameters") or {}
            if action_type in {"develop_product", "develop_market", "develop_iso"}:
                actions.append({"action_type": action_type, "parameters": {"target": row.get("target")}})
            elif action_type == "long_loan_borrow":
                actions.append({"action_type": "long_loan_borrow", "parameters": {"principal_wan": params.get("principal_wan"), "term_years": params.get("term", 4)}})
            elif action_type == "short_loan_borrow":
                actions.append({"action_type": "short_loan_borrow", "parameters": {"principal_wan": params.get("principal_wan"), "term_quarters": params.get("term", 4)}})
            elif action_type == "receivable_discount":
                targets = []
                for term_number in range(1, 5):
                    amount = _number(params.get(f"term_{term_number}_wan"))
                    if amount > 0:
                        targets.append((term_number, amount))
                unused = [item for item in state.get("receivables", []) if str(item.get("receivable_id")) not in reserved_receivables]
                for term_number, amount in targets:
                    candidates = sorted(unused, key=lambda item: (abs(max(0, int(item.get("due_period_index", observation.period_index)) - observation.period_index) - term_number), abs(_number(item.get("amount_wan")) - amount)))
                    selected_total = 0.0
                    for candidate in candidates:
                        if selected_total >= amount:
                            break
                        actions.append({"action_type": "receivable_discount", "parameters": {"receivable_id": candidate.get("receivable_id")}})
                        reserved_receivables.add(str(candidate.get("receivable_id")))
                        selected_total += _number(candidate.get("amount_wan"))
                        unused.remove(candidate)
            elif action_type == "factory_purchase":
                actions.append({"action_type": "buy_workshop", "parameters": {"factory": params.get("factory_type")}})
            elif action_type == "factory_rent":
                actions.append({"action_type": "rent_workshop", "parameters": {"factory": params.get("factory_type")}})
            elif action_type == "production_line_order":
                actions.append({"action_type": "buy_product_line", "parameters": {"line_type": params.get("line_type"), "product_id": params.get("product_id")}})
            elif action_type == "material_order" and params.get("materials"):
                actions.append({"action_type": "material_order", "parameters": {"materials": params["materials"]}})
            elif action_type == "emergency_material_purchase":
                for material_id, quantity in (params.get("quantities") or {}).items():
                    if _number(quantity) > 0:
                        actions.append({"action_type": "emergency_purchase", "parameters": {"material_id": material_id, "quantity": quantity}})
            elif action_type == "emergency_product_purchase":
                for product_id, quantity in (params.get("quantities") or {}).items():
                    if _number(quantity) > 0:
                        actions.append({"action_type": "emergency_product_purchase", "parameters": {"product_id": product_id, "quantity": quantity}})
            elif action_type == "advertising" and _number(row.get("cash_effect_wan")) < 0:
                market, product = self._advertising_pair(state)
                actions.append({"action_type": "advertising", "parameters": {"market": market, "product_id": product, "amount_wan": abs(_number(row.get("cash_effect_wan")))}})
            elif action_type == "production_line_conversion":
                target = params.get("target_product_id")
                line = self._conversion_line(state, target, row.get("cash_effect_wan"))
                if line and target in state.get("products", []):
                    actions.append({"action_type": "convert_product_line", "parameters": {"line_id": line.get("line_id"), "product_id": target}})
            elif action_type == "production":
                ready = [item for item in state.get("production_lines", []) if item.get("status") == "ready"]
                for assignment in (params.get("line_assignments") or [])[: len(ready)]:
                    product = str(assignment.get("product_id"))
                    if product in state.get("products", []):
                        line_type = self.historical_line_types.get(int(assignment["line_instance_id"])) if isinstance(assignment.get("line_instance_id"), int) else None
                        values = {"product_id": product, "quantity": 1}
                        if line_type:
                            values["line_type"] = line_type
                        actions.append({"action_type": "production", "parameters": values})
        return actions

    def _deliveries(self, observation: AgentObservation) -> list[dict[str, Any]]:
        state = observation.private_state
        candidates = [row for row in state.get("assigned_orders", []) if row.get("status") not in {"已交", "违约"}]
        candidates.sort(key=lambda row: (self.delivery_period.get(str(row.get("order_id")), int(row.get("due_period_index", 99))), int(row.get("due_period_index", 99)), str(row.get("order_id"))))
        output = []
        for order in candidates:
            planned = self.delivery_period.get(str(order.get("order_id")), int(order.get("due_period_index", 99)))
            if observation.period_index < planned:
                continue
            output.append({"action_type": "order_delivery", "parameters": {"order_id": order["order_id"]}})
        return output

    def _competitive_claims(self, observation: AgentObservation) -> list[dict[str, Any]]:
        if self.mode != "competitive" or observation.period_index % 4 != 0:
            return []
        state = observation.private_state
        year = observation.period_index // 4 + 1
        target = self.year_order_targets.get(year, 0)
        visible = list((observation.public_state or {}).get("available_orders") or [])
        qualified = [row for row in visible if order_is_qualified(row, markets=state.get("markets", []), products=state.get("products", []), iso=state.get("iso", []))]
        def value(order: Mapping[str, Any]) -> tuple[float, str]:
            pair = (str(order.get("market")), str(order.get("product")))
            preference = self.preference_counts.get(pair, 0) * 25
            direct = _number((self.parameters.get("products") or {}).get(pair[1], {}).get("direct_cost_wan")) * _number(order.get("quantity"))
            noise = int(hashlib.sha256(f"{self.seed}|{self.team_id}|{order.get('order_id')}".encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
            return (_number(order.get("total_price_wan")) - direct + preference + noise * 20, str(order.get("order_id")))
        qualified.sort(key=value, reverse=True)
        market, product = self._advertising_pair(state)
        claims = []
        for order in qualified[:target]:
            common = {"order_id": order["order_id"], "submitted_at": int(hashlib.sha256(f"{self.seed}|{self.team_id}|{order['order_id']}".encode()).hexdigest()[:8], 16) / 0xFFFFFFFF, "market": order.get("market"), "product": order.get("product")}
            if str(order.get("order_type")) == "竞单":
                claims.append({"action_type": "auction_bid", "parameters": {**common, "bid_wan": _number(order.get("total_price_wan")) * 0.95}})
            else:
                claims.append({"action_type": "select_order", "parameters": {**common, "product_advertising": self.preference_counts.get((str(order.get("market")), str(order.get("product"))), 0), "market_advertising": self.preference_counts.get((str(order.get("market")), product), 0), "total_advertising": sum(self.preference_counts.values())}})
        return claims

    def act(self, observation: AgentObservation) -> Mapping[str, Any]:
        if observation.private_state.get("bankrupt"):
            return {"action_type": "hold", "policy_metadata": {"policy": HISTORICAL_STRATEGY_VERSION, "strategy_class": self.profile.strategy_class}}
        actions = [*self._translate_historical_actions(observation), *self._deliveries(observation), *self._competitive_claims(observation)]
        return {
            "actions": actions or [{"action_type": "hold"}],
            "policy_metadata": {
                "policy": HISTORICAL_STRATEGY_VERSION, "strategy_class": self.profile.strategy_class,
                "calibration_mode": self.mode, "uses_future_historical_path": True,
                "online_agent_eligible": False,
            },
        }
