from pathlib import Path

from goai_data.pre_agent import PreAgentKernel
from goai_data.state_engine import ExperimentalState, ExperimentalStateEngine


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATABASE = PROJECT_ROOT / "data" / "processed" / "v1" / "goai.sqlite"


def production_ready_state(engine: ExperimentalStateEngine) -> ExperimentalState:
    state = ExperimentalState.from_dict(engine.initial_state().result)
    state.material_inventory["R1"] = 2
    state.product_qualifications = ["P1"]
    state.production_lines = [{"line_instance_id": "L1", "line_type": "自动线"}]
    return state


def test_production_bom_completion_delivery_and_receivable_collection() -> None:
    engine = ExperimentalStateEngine(DATABASE)
    state = production_ready_state(engine)
    produced = engine.apply_action(
        state,
        {
            "action_type": "production",
            "parameters": {"product_id": "P1", "quantity": 2, "line_instance_id": "L1"},
        },
    )
    assert produced.status == "success"
    state = ExperimentalState.from_dict(produced.result["state"])
    assert state.material_inventory["R1"] == 0
    assert state.cash_wan == 698
    assert len(state.pending_production) == 1

    completed = engine.advance_quarter(state)
    assert completed.status == "success"
    state = ExperimentalState.from_dict(completed.result["state"])
    assert state.product_inventory["P1"] == 2
    assert state.cash_wan == 688

    delivered = engine.apply_action(
        state,
        {
            "action_type": "order_delivery",
            "parameters": {
                "order_id": "T-001",
                "product_id": "P1",
                "quantity": 2,
                "total_amount_wan": 100,
                "receivable_term_quarters": 2,
            },
        },
    )
    assert delivered.status == "success"
    state = ExperimentalState.from_dict(delivered.result["state"])
    assert state.product_inventory["P1"] == 0
    assert state.cash_wan == 688
    assert state.cumulative_revenue_wan == 100

    state = ExperimentalState.from_dict(engine.advance_quarter(state).result["state"])
    state = ExperimentalState.from_dict(engine.advance_quarter(state).result["state"])
    assert (state.year, state.quarter) == (1, 4)
    assert state.cash_wan == 768
    assert state.receivables[0]["status"] == "collected_experimental"


def test_pre_agent_metrics_invariants_and_readiness() -> None:
    engine = ExperimentalStateEngine(DATABASE)
    kernel = PreAgentKernel(DATABASE)
    state = production_ready_state(engine)
    metrics = kernel.metrics(state)
    assert metrics.status == "success"
    assert metrics.result["material_inventory_value_wan"] == 14
    assert metrics.result["tracked_asset_value_wan"] == 724

    invalid = ExperimentalState.from_dict(state.to_dict())
    invalid.material_inventory["R1"] = -1
    assert kernel.validate_state(invalid).status == "rejected"

    readiness = kernel.readiness()
    assert readiness.experimental_ready is True
    assert readiness.formal_ready is False
    assert any(item["stage"] == "rule_process_semantics" and item["status"] == "blocked" for item in readiness.stages)


def test_pre_agent_kernel_compares_feasible_and_invalid_plans() -> None:
    engine = ExperimentalStateEngine(DATABASE)
    kernel = PreAgentKernel(DATABASE)
    state = production_ready_state(engine)
    result = kernel.compare_plans(
        state,
        [
            {"candidate_id": "hold_cash", "timeline": [{"type": "advance_quarter"}]},
            {
                "candidate_id": "produce_p1",
                "timeline": [
                    {
                        "type": "action",
                        "action_type": "production",
                        "parameters": {"product_id": "P1", "quantity": 2, "line_instance_id": "L1"},
                    },
                    {"type": "advance_quarter"},
                ],
            },
            {
                "candidate_id": "impossible_p3",
                "timeline": [
                    {
                        "type": "action",
                        "action_type": "production",
                        "parameters": {"product_id": "P3", "quantity": 1, "line_instance_id": "L1"},
                    }
                ],
            },
        ],
    )
    assert result.status == "success"
    statuses = {item["candidate_id"]: item["status"] for item in result.result["evaluations"]}
    assert statuses["hold_cash"] == "success"
    assert statuses["produce_p1"] == "success"
    assert statuses["impossible_p3"] == "rejected"
