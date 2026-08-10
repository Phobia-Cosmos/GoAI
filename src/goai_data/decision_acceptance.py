"""Offline acceptance metrics for paired Agent-versus-human trajectories.

VPD is a terminal/trajectory evaluation signal.  It is intentionally kept out
of the online action selector so that a proxy metric cannot override cash,
delivery, bankruptcy or the competition environment's accounting state.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from statistics import mean
from typing import Any, Mapping, Sequence


DECISION_ACCEPTANCE_VERSION = "paired_vpd_acceptance_v1.0"


@dataclass(frozen=True)
class TrajectoryAcceptanceMetrics:
    trajectory_id: str
    decision_source: str
    comparison_key: str
    vpd: float
    oe: float
    official_score: float
    rank: int | None
    bankrupt: bool
    default_count: int
    minimum_cash_wan: float
    delivered_orders: int
    metadata: Mapping[str, Any] | None = None

    @property
    def vpd_oe(self) -> float | None:
        return self.vpd / self.oe if self.oe > 0 else None

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["vpd_oe"] = self.vpd_oe
        return value


def compare_agent_with_human(
    agent: TrajectoryAcceptanceMetrics,
    human: TrajectoryAcceptanceMetrics,
    *,
    minimum_vpd_delta: float = 0.0,
    minimum_vpd_oe_delta: float = 0.0,
) -> dict[str, Any]:
    """Compare paired trajectories produced under the same environment.

    ``comparison_key`` must bind the rule pack, order seed, opponent set,
    connection point and initial owned-enterprise state.  This prevents an
    easier simulation from being reported as an Agent improvement.
    """

    if agent.comparison_key != human.comparison_key:
        raise ValueError("Agent and human trajectories are not paired to the same environment")
    agent_ratio, human_ratio = agent.vpd_oe, human.vpd_oe
    ratio_delta = None if agent_ratio is None or human_ratio is None else agent_ratio - human_ratio
    hard_gate = {
        "bankruptcy_not_worse": not agent.bankrupt or human.bankrupt,
        "default_count_not_worse": agent.default_count <= human.default_count,
        "minimum_cash_nonnegative": agent.minimum_cash_wan >= 0,
    }
    metric_gate = {
        "vpd_delta_meets_target": agent.vpd - human.vpd >= minimum_vpd_delta,
        "vpd_oe_delta_meets_target": ratio_delta is not None and ratio_delta >= minimum_vpd_oe_delta,
    }
    accepted = all(hard_gate.values()) and all(metric_gate.values())
    return {
        "acceptance_version": DECISION_ACCEPTANCE_VERSION,
        "comparison_key": agent.comparison_key,
        "accepted": accepted,
        "primary_acceptance_metric": "VPD_and_VPD_over_OE",
        "metric_binding_status": "candidate_until_XA_accounting_allocation_is_validated",
        "vpd_role": "offline_agent_vs_human_acceptance_not_online_action_selector",
        "hard_gate": hard_gate,
        "metric_gate": metric_gate,
        "deltas": {
            "vpd": agent.vpd - human.vpd,
            "oe": agent.oe - human.oe,
            "vpd_oe": ratio_delta,
            "official_score": agent.official_score - human.official_score,
            "rank": None if agent.rank is None or human.rank is None else human.rank - agent.rank,
            "delivered_orders": agent.delivered_orders - human.delivered_orders,
            "minimum_cash_wan": agent.minimum_cash_wan - human.minimum_cash_wan,
        },
        "agent": agent.to_dict(),
        "human": human.to_dict(),
    }


def aggregate_paired_acceptance(comparisons: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if not comparisons:
        raise ValueError("at least one paired comparison is required")
    ratio_deltas = [
        float((row.get("deltas") or {}).get("vpd_oe"))
        for row in comparisons
        if (row.get("deltas") or {}).get("vpd_oe") is not None
    ]
    return {
        "acceptance_version": DECISION_ACCEPTANCE_VERSION,
        "pair_count": len(comparisons),
        "acceptance_rate": mean(float(row.get("accepted", False)) for row in comparisons),
        "mean_vpd_delta": mean(float((row.get("deltas") or {}).get("vpd", 0.0)) for row in comparisons),
        "mean_vpd_oe_delta": mean(ratio_deltas) if ratio_deltas else None,
        "bankruptcy_gate_pass_rate": mean(float((row.get("hard_gate") or {}).get("bankruptcy_not_worse", False)) for row in comparisons),
        "default_gate_pass_rate": mean(float((row.get("hard_gate") or {}).get("default_count_not_worse", False)) for row in comparisons),
    }
