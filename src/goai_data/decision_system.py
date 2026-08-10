from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence


DECISION_SYSTEM_VERSION = "modular_decision_v0.1"


def _number(payload: Mapping[str, Any], *keys: str, default: float = 0.0) -> float:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, (int, float)):
            return float(value)
    return default


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return min(high, max(low, value))


def _period_label_index(period: Any) -> int | None:
    if not isinstance(period, str) or not period.startswith("Y") or "Q" not in period:
        return None
    try:
        year_text, quarter_text = period[1:].split("Q", 1)
        return (int(year_text) - 1) * 4 + int(quarter_text)
    except ValueError:
        return None


@dataclass(frozen=True)
class CandidateOutcome:
    candidate_id: str
    initial_state: Mapping[str, Any]
    final_state: Mapping[str, Any]
    trajectory: Sequence[Mapping[str, Any]] = ()
    violations: Sequence[str] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MetricContext:
    initial_cash_wan: float
    cash_buffer_wan: float | None = None
    normalization_scale_wan: float | None = None

    @property
    def cash_target(self) -> float:
        return self.cash_buffer_wan if self.cash_buffer_wan is not None else max(1.0, self.initial_cash_wan * 0.2)

    @property
    def scale(self) -> float:
        return self.normalization_scale_wan if self.normalization_scale_wan is not None else max(1.0, self.initial_cash_wan)


@dataclass(frozen=True)
class MetricResult:
    metric_id: str
    raw_value: float | None
    utility: float
    applicable: bool = True
    details: Mapping[str, Any] = field(default_factory=dict)


class DecisionMetric(Protocol):
    metric_id: str

    def evaluate(self, outcome: CandidateOutcome, context: MetricContext) -> MetricResult: ...


class CashSafetyMetric:
    metric_id = "cash_safety"

    def evaluate(self, outcome: CandidateOutcome, context: MetricContext) -> MetricResult:
        cash_values = [_number(outcome.initial_state, "cash_wan", "end_cash_wan")]
        cash_values.extend(_number(state, "cash_wan", "end_cash_wan") for state in outcome.trajectory)
        cash_values.append(_number(outcome.final_state, "cash_wan", "end_cash_wan"))
        minimum = min(cash_values)
        utility = 0.0 if minimum < 0 else _clamp(minimum / context.cash_target)
        return MetricResult(self.metric_id, minimum, utility, details={"cash_target_wan": context.cash_target})


class SolvencyMetric:
    metric_id = "solvency"

    def evaluate(self, outcome: CandidateOutcome, context: MetricContext) -> MetricResult:
        cash = _number(outcome.final_state, "cash_wan", "end_cash_wan")
        equity = _number(outcome.final_state, "owner_equity_wan", "equity_wan", default=cash)
        assets = _number(outcome.final_state, "assets_wan", default=max(equity, 0.0))
        debt = _number(outcome.final_state, "debt_wan", "liabilities_wan")
        if cash < 0 or equity < 0:
            utility = 0.0
        elif assets <= 0:
            utility = 0.5
        else:
            utility = _clamp(1.0 - debt / assets)
        return MetricResult(self.metric_id, equity, utility, details={"cash_wan": cash, "assets_wan": assets, "debt_wan": debt})


class ProfitabilityMetric:
    metric_id = "profitability"

    def evaluate(self, outcome: CandidateOutcome, context: MetricContext) -> MetricResult:
        initial = _number(outcome.initial_state, "owner_equity_wan", "equity_wan", default=context.initial_cash_wan)
        final = _number(outcome.final_state, "owner_equity_wan", "equity_wan", default=_number(outcome.final_state, "cash_wan"))
        delta = final - initial
        utility = _clamp(0.5 + delta / (2 * context.scale))
        return MetricResult(self.metric_id, delta, utility, details={"initial_equity_wan": initial, "final_equity_wan": final})


class FulfillmentMetric:
    metric_id = "order_fulfillment"

    def evaluate(self, outcome: CandidateOutcome, context: MetricContext) -> MetricResult:
        assigned = _number(outcome.final_state, "orders_assigned", "assigned_orders")
        delivered = _number(outcome.final_state, "orders_delivered", "delivered_orders")
        if assigned <= 0:
            return MetricResult(self.metric_id, None, 0.5, applicable=False, details={"reason": "no_assigned_orders"})
        ratio = delivered / assigned
        return MetricResult(self.metric_id, ratio, _clamp(ratio), details={"assigned": assigned, "delivered": delivered})


class CapacityUtilizationMetric:
    metric_id = "capacity_utilization"

    def evaluate(self, outcome: CandidateOutcome, context: MetricContext) -> MetricResult:
        capacity = _number(outcome.final_state, "available_capacity", "capacity")
        used = _number(outcome.final_state, "used_capacity", "production_volume")
        if capacity <= 0:
            return MetricResult(self.metric_id, None, 0.5, applicable=False, details={"reason": "capacity_not_available"})
        ratio = used / capacity
        return MetricResult(self.metric_id, ratio, _clamp(ratio), details={"capacity": capacity, "used": used})


class FinalScoreProxyMetric:
    metric_id = "final_score_proxy"

    def evaluate(self, outcome: CandidateOutcome, context: MetricContext) -> MetricResult:
        equity = _number(outcome.final_state, "owner_equity_wan", "equity_wan", default=_number(outcome.final_state, "cash_wan"))
        potential = _number(outcome.final_state, "development_potential")
        score = equity * (1.0 + potential / 100.0)
        utility = _clamp(score / (2.0 * context.scale))
        return MetricResult(self.metric_id, score, utility, details={"equity_wan": equity, "development_potential": potential})


DEFAULT_METRICS: tuple[DecisionMetric, ...] = (
    CashSafetyMetric(),
    SolvencyMetric(),
    ProfitabilityMetric(),
    FulfillmentMetric(),
    CapacityUtilizationMetric(),
    FinalScoreProxyMetric(),
)


DEFAULT_PROFILES: dict[str, dict[str, float]] = {
    "safety": {"cash_safety": 0.45, "solvency": 0.35, "order_fulfillment": 0.20},
    "balanced": {
        "cash_safety": 0.20,
        "solvency": 0.20,
        "profitability": 0.20,
        "order_fulfillment": 0.15,
        "capacity_utilization": 0.10,
        "final_score_proxy": 0.15,
    },
    "growth": {"profitability": 0.30, "final_score_proxy": 0.30, "capacity_utilization": 0.20, "cash_safety": 0.10, "solvency": 0.10},
}


class MetricSuite:
    def __init__(self, metrics: Sequence[DecisionMetric] = DEFAULT_METRICS) -> None:
        self.metrics = {metric.metric_id: metric for metric in metrics}

    def evaluate(self, outcome: CandidateOutcome, context: MetricContext, weights: Mapping[str, float]) -> dict[str, Any]:
        unknown = sorted(set(weights) - set(self.metrics))
        if unknown:
            raise ValueError(f"unknown metrics: {', '.join(unknown)}")
        if any(weight < 0 for weight in weights.values()) or sum(weights.values()) <= 0:
            raise ValueError("metric weights must be nonnegative with a positive sum")
        results = {metric_id: self.metrics[metric_id].evaluate(outcome, context) for metric_id in weights}
        denominator = sum(weights.values())
        weighted_score = sum(weights[metric_id] * result.utility for metric_id, result in results.items()) / denominator
        if outcome.violations:
            weighted_score = 0.0
        return {
            "candidate_id": outcome.candidate_id,
            "score": weighted_score,
            "feasible": not outcome.violations,
            "violations": list(outcome.violations),
            "metrics": {
                metric_id: {
                    "raw_value": result.raw_value,
                    "utility": result.utility,
                    "applicable": result.applicable,
                    "weight": weights[metric_id],
                    "details": dict(result.details),
                }
                for metric_id, result in results.items()
            },
        }


class WeightedDecisionStrategy:
    def __init__(self, suite: MetricSuite, profile_name: str = "balanced", profiles: Mapping[str, Mapping[str, float]] = DEFAULT_PROFILES) -> None:
        if profile_name not in profiles:
            raise ValueError(f"unknown profile: {profile_name}")
        self.suite = suite
        self.profile_name = profile_name
        self.weights = dict(profiles[profile_name])

    def rank(self, outcomes: Sequence[CandidateOutcome], context: MetricContext) -> list[dict[str, Any]]:
        evaluations = [self.suite.evaluate(outcome, context, self.weights) for outcome in outcomes]
        evaluations.sort(key=lambda row: (not row["feasible"], -row["score"], row["candidate_id"]))
        for rank, row in enumerate(evaluations, 1):
            row["rank"] = rank
            row["profile"] = self.profile_name
        return evaluations

    def select(self, outcomes: Sequence[CandidateOutcome], context: MetricContext) -> dict[str, Any]:
        ranked = self.rank(outcomes, context)
        if not ranked:
            raise ValueError("at least one candidate outcome is required")
        return {"selected_candidate_id": ranked[0]["candidate_id"] if ranked[0]["feasible"] else None, "profile": self.profile_name, "ranking": ranked}


class MetricAblationExperiment:
    def __init__(self, suite: MetricSuite) -> None:
        self.suite = suite

    def compare_profiles(self, outcomes: Sequence[CandidateOutcome], context: MetricContext, profiles: Mapping[str, Mapping[str, float]] = DEFAULT_PROFILES) -> dict[str, Any]:
        comparisons = {}
        for profile_name in profiles:
            comparisons[profile_name] = WeightedDecisionStrategy(self.suite, profile_name, profiles).select(outcomes, context)
        return {"experiment_type": "metric_profile_comparison", "comparisons": comparisons}

    def leave_one_metric_out(self, outcomes: Sequence[CandidateOutcome], context: MetricContext, base_weights: Mapping[str, float]) -> dict[str, Any]:
        comparisons = {}
        for removed in base_weights:
            weights = {metric_id: weight for metric_id, weight in base_weights.items() if metric_id != removed}
            evaluations = [self.suite.evaluate(outcome, context, weights) for outcome in outcomes]
            evaluations.sort(key=lambda row: (not row["feasible"], -row["score"], row["candidate_id"]))
            comparisons[removed] = {"selected_candidate_id": evaluations[0]["candidate_id"] if evaluations and evaluations[0]["feasible"] else None, "ranking": evaluations}
        return {"experiment_type": "leave_one_metric_out", "comparisons": comparisons}


@dataclass(frozen=True)
class AgentObservation:
    match_id: str
    agent_id: str
    period_index: int
    period: str
    private_state: Mapping[str, Any]
    public_state: Mapping[str, Any]
    legal_actions: Sequence[Mapping[str, Any]]


class AgentPolicy(Protocol):
    agent_id: str

    def act(self, observation: AgentObservation) -> Mapping[str, Any]: ...


@dataclass(frozen=True)
class ArenaStep:
    observations: Mapping[str, AgentObservation]
    rewards: Mapping[str, float]
    terminated: bool
    infos: Mapping[str, Mapping[str, Any]]


class MultiAgentEnvironment(Protocol):
    @property
    def agent_ids(self) -> tuple[str, ...]: ...

    def reset(self, seed: int | None = None) -> Mapping[str, AgentObservation]: ...

    def step(self, actions: Mapping[str, Mapping[str, Any]]) -> ArenaStep: ...


class HistoricalReplayArena:
    """A working multi-agent interface over observed quarterly trajectories.

    It validates orchestration and information boundaries but does not accept
    counterfactual business actions. A future XA dynamics plugin can implement
    the same MultiAgentEnvironment protocol without changing policies or metrics.
    """

    def __init__(self, dataset_root: Path, match_id: str) -> None:
        self.dataset_root = dataset_root.resolve()
        self.match_id = match_id
        match_root = self.dataset_root / "matches" / match_id
        if not match_root.is_dir():
            raise FileNotFoundError(match_root)
        teams = [json.loads(line) for line in (match_root / "teams.jsonl").read_text(encoding="utf-8").splitlines() if line]
        states = [json.loads(line) for line in (match_root / "quarter_states.jsonl").read_text(encoding="utf-8").splitlines() if line]
        final_states = [json.loads(line) for line in (match_root / "final_states.jsonl").read_text(encoding="utf-8").splitlines() if line]
        self._agent_ids = tuple(sorted(team["team_id"] for team in teams))
        self._states = {(state["team_id"], int(state["period_index"])): state for state in states}
        self._final_states = {state["team_id"]: state for state in final_states}
        self._results = json.loads((match_root / "results.json").read_text(encoding="utf-8"))
        self.current_period_index = 1
        self.terminated = False

    @property
    def agent_ids(self) -> tuple[str, ...]:
        return self._agent_ids

    def reset(self, seed: int | None = None) -> Mapping[str, AgentObservation]:
        self.current_period_index = 1
        self.terminated = False
        return self._observations()

    def _observation(self, agent_id: str) -> AgentObservation:
        state = dict(self._states[(agent_id, self.current_period_index)])
        final_state = self._final_states[agent_id]
        bankruptcy_period = final_state.get("bankruptcy_period")
        bankruptcy_index = _period_label_index(bankruptcy_period)
        bankruptcy_observed = bankruptcy_index is not None and self.current_period_index >= bankruptcy_index
        state["bankruptcy_period"] = bankruptcy_period if bankruptcy_observed else None
        state["bankrupt"] = bankruptcy_observed
        if self.current_period_index == 20:
            state["terminal_state"] = final_state
        public = {
            "match_id": self.match_id,
            "period": state["period"],
            "agent_count": len(self.agent_ids),
            "information_policy": "no_other_team_private_cash",
            "bankrupt_team_ids": sorted(
                team_id
                for team_id, row in self._final_states.items()
                if (_period_label_index(row.get("bankruptcy_period")) or 10**9) <= self.current_period_index
            ),
        }
        return AgentObservation(
            match_id=self.match_id,
            agent_id=agent_id,
            period_index=self.current_period_index,
            period=state["period"],
            private_state=state,
            public_state=public,
            legal_actions=({"action_type": "replay_observed_period"},),
        )

    def _observations(self) -> dict[str, AgentObservation]:
        return {agent_id: self._observation(agent_id) for agent_id in self.agent_ids}

    def step(self, actions: Mapping[str, Mapping[str, Any]]) -> ArenaStep:
        if self.terminated:
            raise RuntimeError("arena is terminated; call reset()")
        missing = sorted(set(self.agent_ids) - set(actions))
        extra = sorted(set(actions) - set(self.agent_ids))
        invalid = sorted(agent_id for agent_id, action in actions.items() if action.get("action_type") != "replay_observed_period")
        if missing or extra or invalid:
            raise ValueError(f"invalid joint action: missing={missing}, extra={extra}, invalid={invalid}")
        before = {agent_id: self._states[(agent_id, self.current_period_index)] for agent_id in self.agent_ids}
        if self.current_period_index < 20:
            self.current_period_index += 1
        self.terminated = self.current_period_index >= 20
        observations = self._observations()
        rewards = {}
        infos = {}
        for agent_id in self.agent_ids:
            start_cash = _number(before[agent_id], "end_cash_wan")
            end_cash = _number(observations[agent_id].private_state, "end_cash_wan")
            rewards[agent_id] = end_cash - start_cash
            infos[agent_id] = {"mode": "historical_replay", "provenance": "derived_from_observed_events", "counterfactual_actions_allowed": False}
        return ArenaStep(observations=observations, rewards=rewards, terminated=self.terminated, infos=infos)

    def terminal_results(self) -> Mapping[str, Any]:
        if not self.terminated:
            raise RuntimeError("terminal results are only available after replay reaches Y5Q4")
        return self._results


class ReplayPolicy:
    def __init__(self, agent_id: str) -> None:
        self.agent_id = agent_id

    def act(self, observation: AgentObservation) -> Mapping[str, Any]:
        return {"action_type": "replay_observed_period"}


class ArenaRunner:
    def run(self, environment: MultiAgentEnvironment, policies: Mapping[str, AgentPolicy], seed: int | None = None) -> dict[str, Any]:
        if set(environment.agent_ids) != set(policies):
            raise ValueError("one policy is required for every environment agent")
        observations = environment.reset(seed=seed)
        cumulative_rewards = {agent_id: 0.0 for agent_id in environment.agent_ids}
        steps = 0
        while True:
            actions = {agent_id: policies[agent_id].act(observations[agent_id]) for agent_id in environment.agent_ids}
            result = environment.step(actions)
            steps += 1
            for agent_id, reward in result.rewards.items():
                cumulative_rewards[agent_id] += reward
            observations = result.observations
            if result.terminated:
                break
        output = {
            "system_version": DECISION_SYSTEM_VERSION,
            "match_id": next(iter(observations.values())).match_id,
            "steps": steps,
            "agent_count": len(environment.agent_ids),
            "cumulative_rewards": cumulative_rewards,
            "final_observations": observations,
        }
        terminal_results = getattr(environment, "terminal_results", None)
        if callable(terminal_results):
            output["terminal_results"] = terminal_results()
        return output
