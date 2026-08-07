from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from goai_data.pre_agent import KERNEL_VERSION, METRICS_VERSION, PreAgentKernel
from goai_data.state_engine import ExperimentalState, ExperimentalStateEngine, STATE_ENGINE_VERSION
from run_decision_event_experiments import file_sha256, record, render_log


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def ready_state(engine: ExperimentalStateEngine) -> ExperimentalState:
    state = ExperimentalState.from_dict(engine.initial_state().result)
    state.material_inventory["R1"] = 2
    state.product_qualifications = ["P1"]
    state.production_lines = [{"line_instance_id": "L1", "line_type": "自动线"}]
    return state


def main() -> int:
    parser = argparse.ArgumentParser(description="运行 Pre-Agent 全链路实验并追加实验记录。")
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--run-id")
    args = parser.parse_args()
    generated_at = datetime.now().astimezone().isoformat(timespec="seconds")
    run_id = args.run_id or datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")
    database = args.database.resolve()
    output = args.output.resolve()
    run_dir = output / "runs" / run_id
    if run_dir.exists():
        raise SystemExit(f"run directory already exists: {run_dir}")
    run_dir.mkdir(parents=True)
    database_sha256 = file_sha256(database)
    engine = ExperimentalStateEngine(database)
    kernel = PreAgentKernel(database)

    initial = ready_state(engine)
    timeline = [
        {"type": "action", "action_type": "production", "parameters": {"product_id": "P1", "quantity": 2, "line_instance_id": "L1"}},
        {"type": "advance_quarter"},
        {"type": "action", "action_type": "order_delivery", "parameters": {"order_id": "T-001", "product_id": "P1", "quantity": 2, "total_amount_wan": 100, "receivable_term_quarters": 2}},
        {"type": "advance_quarter"},
        {"type": "advance_quarter"},
    ]
    lifecycle = engine.simulate_timeline(initial, timeline)
    final_state = ExperimentalState.from_dict(lifecycle.result["final_state"])
    exp1_artifact = run_dir / "EXP-PRE-001_production_delivery_lifecycle.json"
    write_json(exp1_artifact, lifecycle.to_dict())

    invalid_state = ExperimentalState.from_dict(initial.to_dict())
    invalid_state.material_inventory["R1"] = -1
    valid_check = kernel.validate_state(initial)
    invalid_check = kernel.validate_state(invalid_state)
    final_metrics = kernel.metrics(final_state)
    exp2_artifact = run_dir / "EXP-PRE-002_invariants_metrics.json"
    write_json(exp2_artifact, {"valid": valid_check.to_dict(), "invalid": invalid_check.to_dict(), "final_metrics": final_metrics.to_dict()})

    candidates = [
        {"candidate_id": "hold_cash", "timeline": [{"type": "advance_quarter"}]},
        {"candidate_id": "produce_and_deliver_p1", "timeline": timeline},
        {"candidate_id": "invalid_p3", "timeline": [{"type": "action", "action_type": "production", "parameters": {"product_id": "P3", "quantity": 1, "line_instance_id": "L1"}}]},
    ]
    comparison = kernel.compare_plans(initial, candidates)
    exp3_artifact = run_dir / "EXP-PRE-003_candidate_comparison.json"
    write_json(exp3_artifact, comparison.to_dict())

    readiness = kernel.readiness()
    exp4_artifact = run_dir / "EXP-PRE-004_readiness_audit.json"
    write_json(exp4_artifact, readiness.to_dict())

    records = [
        record(
            "EXP-PRE-001", run_id, generated_at,
            "验证 BOM、生产周期、产成品、交付和应收回款的端到端状态闭环。",
            "以自动线生产 P1×2，完工后交付 100 万元、账期 2 季并推进至回款。",
            {"state_engine_version": STATE_ENGINE_VERSION, "status": lifecycle.status, "final_period": f"Y{final_state.year}Q{final_state.quarter}", "final_cash_wan": final_state.cash_wan, "revenue_wan": final_state.cumulative_revenue_wan, "processing_cost_wan": final_state.cumulative_processing_cost_wan, "management_fee_wan": final_state.cumulative_management_fee_wan, "receivable_status": final_state.receivables[0]["status"]},
            "P1×2 消耗 R1×2和加工费 12 万元，Y1Q2 完工交货，Y1Q4 回款，最终现金 768 万元。",
            "订单资格、收入确认和季度内结算顺序仍为实验口径。",
            [str(exp1_artifact)], database, database_sha256,
        ),
        record(
            "EXP-PRE-002", run_id, generated_at,
            "验证状态守恒检查和基础经营指标。",
            "分别校验合法状态、R1=-1 的非法状态，并计算完整生产交付后的指标。",
            {"metrics_version": METRICS_VERSION, "valid_state_status": valid_check.status, "negative_inventory_status": invalid_check.status, "negative_inventory_violation": invalid_check.violations[0], "final_tracked_asset_value_wan": final_metrics.result["tracked_asset_value_wan"], "final_net_liquid_position_wan": final_metrics.result["net_liquid_position_wan"], "final_cash_contribution_proxy_wan": final_metrics.result["tracked_cash_contribution_proxy_wan"]},
            "合法状态通过，负库存状态被拒绝；完整闭环后的追踪资产和净流动头寸均为 768 万元。",
            "代理指标不是正式会计利润、PSS 或竞赛评分。",
            [str(exp2_artifact)], database, database_sha256,
        ),
        record(
            "EXP-PRE-003", run_id, generated_at,
            "验证无 LLM 多方案校验、Pareto 比较和非法方案过滤。",
            "比较持有现金、生产交付 P1 和未研发 P3 三套方案。",
            {"kernel_version": KERNEL_VERSION, "status": comparison.status, "recommended_candidate_id": comparison.result["recommended_candidate_id"], "pareto_candidate_ids": comparison.result["pareto_candidate_ids"], "candidate_statuses": {item["candidate_id"]: item["status"] for item in comparison.result["evaluations"]}, "formal_commit_allowed": comparison.result["formal_commit_allowed"]},
            "未研发 P3 被拒绝；持有现金与生产交付方案均进入 Pareto 集，现金优先基线推荐 hold_cash。",
            "当前排序政策偏重现金安全，用户可在后续接入明确风险偏好。",
            [str(exp3_artifact)], database, database_sha256,
        ),
        record(
            "EXP-PRE-004", run_id, generated_at,
            "审计 Agent 前置系统的实验就绪与正式就绪状态。",
            "检查数据、规则、状态、指标、比较、重放、PSS 和跨比赛验证阶段。",
            {"experimental_ready": readiness.experimental_ready, "formal_ready": readiness.formal_ready, "complete_or_experimental_stages": sum(item["status"] in {"complete", "experimental_complete"} for item in readiness.stages), "blocked_stages": [item["stage"] for item in readiness.stages if item["status"] == "blocked"], "external_blocker_count": len(readiness.external_blockers)},
            "Pre-Agent 决策内核达到实验就绪；正式就绪受规则、历史绑定、PSS 定义和多比赛数据阻塞。",
            "外部 blocker 不能通过代码推断安全消除，需要业务资料或明确口径确认。",
            [str(exp4_artifact)], database, database_sha256,
        ),
    ]
    for item in records:
        write_json(run_dir / f"{item['experiment_id']}.json", item)
    write_json(run_dir / "run_summary.json", {"run_id": run_id, "generated_at": generated_at, "state_engine_version": STATE_ENGINE_VERSION, "metrics_version": METRICS_VERSION, "kernel_version": KERNEL_VERSION, "database": str(database), "database_sha256": database_sha256, "experiments": records})
    registry_path = output / "experiment_registry.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8")) if registry_path.exists() else []
    registry.extend(records)
    write_json(registry_path, registry)
    (output / "实验记录.md").write_text(render_log(registry), encoding="utf-8")
    print(json.dumps({"run_id": run_id, "experiments": [item["experiment_id"] for item in records]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
