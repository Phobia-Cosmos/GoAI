import pytest

from goai_data.decision_acceptance import TrajectoryAcceptanceMetrics, compare_agent_with_human


def metrics(source: str, *, vpd: float, oe: float, bankrupt: bool = False, defaults: int = 0):
    return TrajectoryAcceptanceMetrics(
        trajectory_id=source,
        decision_source=source,
        comparison_key="rules=XA|orders=17|opponents=A|join=Y2Q1|state=S1",
        vpd=vpd,
        oe=oe,
        official_score=100.0,
        rank=2,
        bankrupt=bankrupt,
        default_count=defaults,
        minimum_cash_wan=30.0,
        delivered_orders=5,
    )


def test_vpd_acceptance_is_paired_and_cannot_override_hard_failures() -> None:
    human = metrics("human", vpd=100.0, oe=100.0)
    accepted = compare_agent_with_human(metrics("agent", vpd=130.0, oe=100.0), human)
    assert accepted["accepted"] is True
    assert accepted["vpd_role"].startswith("offline_agent_vs_human")
    bankrupt = compare_agent_with_human(metrics("agent", vpd=300.0, oe=100.0, bankrupt=True), human)
    assert bankrupt["accepted"] is False
    assert bankrupt["hard_gate"]["bankruptcy_not_worse"] is False


def test_vpd_acceptance_rejects_unpaired_environment() -> None:
    human = metrics("human", vpd=100.0, oe=100.0)
    agent = metrics("agent", vpd=120.0, oe=100.0)
    object.__setattr__(agent, "comparison_key", "different-seed")
    with pytest.raises(ValueError, match="not paired"):
        compare_agent_with_human(agent, human)
