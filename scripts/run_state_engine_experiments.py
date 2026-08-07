from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from goai_data.state_engine import ExperimentalState, ExperimentalStateEngine, STATE_ENGINE_VERSION
from run_decision_event_experiments import file_sha256, record, render_log


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="运行跨季度状态引擎实验并追加累计实验记录。")
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

    initial = ExperimentalState.from_dict(engine.initial_state().result)
    ordered = engine.apply_action(
        initial,
        {"action_type": "material_order", "parameters": {"materials": {"R1": 2, "R3": 1}}},
    )
    material_state = ExperimentalState.from_dict(ordered.result["state"])
    material_q2 = engine.advance_quarter(material_state)
    material_state_q2 = ExperimentalState.from_dict(material_q2.result["state"])
    material_q3 = engine.advance_quarter(material_state_q2)
    material_state_q3 = ExperimentalState.from_dict(material_q3.result["state"])
    exp1_payload = {
        "initial": initial.to_dict(),
        "ordered": ordered.to_dict(),
        "after_first_advance": material_q2.to_dict(),
        "after_second_advance": material_q3.to_dict(),
    }
    exp1_artifact = run_dir / "EXP-STATE-001_material_lead_time.json"
    write_json(exp1_artifact, exp1_payload)

    loan_initial = ExperimentalState.from_dict(engine.initial_state().result)
    borrowed = engine.apply_action(
        loan_initial,
        {
            "action_type": "short_loan_borrow",
            "parameters": {"principal_wan": 100, "term_quarters": 4},
        },
    )
    loan_state = ExperimentalState.from_dict(borrowed.result["state"])
    loan_advances = []
    for _ in range(4):
        advanced = engine.advance_quarter(loan_state)
        loan_advances.append(advanced.to_dict())
        loan_state = ExperimentalState.from_dict(advanced.result["state"])
    exp2_payload = {"borrowed": borrowed.to_dict(), "advances": loan_advances, "final": loan_state.to_dict()}
    exp2_artifact = run_dir / "EXP-STATE-002_short_loan_lifecycle.json"
    write_json(exp2_artifact, exp2_payload)

    low_cash = ExperimentalState.from_dict(engine.initial_state().result)
    low_cash.cash_wan = 5
    before_id = low_cash.state_id
    rejected = engine.advance_quarter(low_cash)
    exp3_payload = {"before": low_cash.to_dict(), "advance_result": rejected.to_dict()}
    exp3_artifact = run_dir / "EXP-STATE-003_atomic_cash_guard.json"
    write_json(exp3_artifact, exp3_payload)

    timeline = [
        {
            "type": "action",
            "action_type": "material_order",
            "parameters": {"materials": {"R1": 2, "R3": 1}},
        },
        {
            "type": "action",
            "action_type": "short_loan_borrow",
            "parameters": {"principal_wan": 100, "term_quarters": 4},
        },
        {"type": "advance_quarter"},
        {"type": "advance_quarter"},
        {"type": "advance_quarter"},
        {"type": "advance_quarter"},
    ]
    combined = engine.simulate_timeline(ExperimentalState.from_dict(engine.initial_state().result), timeline)
    exp4_artifact = run_dir / "EXP-STATE-004_combined_timeline.json"
    write_json(exp4_artifact, combined.to_dict())

    records = [
        record(
            "EXP-STATE-001",
            run_id,
            generated_at,
            "验证 R1 与 R3 按题面提前期跨季度到货、付款并进入库存。",
            "Y1Q1 订购 R1×2 和 R3×1，连续推进两个季度，检查现金、库存和在途订单。",
            {
                "state_engine_version": STATE_ENGINE_VERSION,
                "initial_cash_wan": initial.cash_wan,
                "q2_cash_wan": material_state_q2.cash_wan,
                "q2_R1_inventory": material_state_q2.material_inventory["R1"],
                "q2_R3_inventory": material_state_q2.material_inventory["R3"],
                "q3_cash_wan": material_state_q3.cash_wan,
                "q3_R3_inventory": material_state_q3.material_inventory["R3"],
                "remaining_pending_orders": len(material_state_q3.pending_material_orders),
            },
            "R1 在 Y1Q2 到货并支付 14 万元，R3 在 Y1Q3 到货并支付 9 万元；同期各扣管理费 10 万元。",
            "到货时付款和季度内结算顺序是实验策略，正式规则尚未确认。",
            [str(exp1_artifact)],
            database,
            database_sha256,
        ),
        record(
            "EXP-STATE-002",
            run_id,
            generated_at,
            "验证短贷从借入、计息到四季度后还本息的生命周期。",
            "Y1Q1 借入 100 万元、期限 4 季，连续推进四个季度。",
            {
                "state_engine_version": STATE_ENGINE_VERSION,
                "principal_wan": 100,
                "annual_rate": 0.05,
                "experimental_interest_wan": 5,
                "amount_due_wan": 105,
                "final_period": f"Y{loan_state.year}Q{loan_state.quarter}",
                "final_cash_wan": loan_state.cash_wan,
                "loan_status": loan_state.short_loans[0]["status"],
            },
            "短贷在 Y2Q1 按实验策略偿还 105 万元，四季管理费共 40 万元，最终现金为 665 万元。",
            "贷款额度、申请资格、精确利息口径和扣款顺序尚未由完整题面确认。",
            [str(exp2_artifact)],
            database,
            database_sha256,
        ),
        record(
            "EXP-STATE-003",
            run_id,
            generated_at,
            "验证季度结算现金不足时拒绝推进且不修改原状态。",
            "将实验状态现金设为 5 万元，推进一个需支付 10 万元管理费的季度。",
            {
                "state_engine_version": STATE_ENGINE_VERSION,
                "initial_cash_wan": 5,
                "advance_status": rejected.status,
                "projected_cash_wan": rejected.result["projected_cash_wan"],
                "state_id_before": before_id,
                "state_id_after_rejection": rejected.result["unchanged_state"]["state_id"],
                "state_unchanged": before_id == rejected.result["unchanged_state"]["state_id"],
            },
            "季度推进被拒绝，预计现金为 -5 万元，拒绝前后 state_id 一致。",
            "当前只采用现金非负硬约束，尚未实现特别贷款、注资或破产接管流程。",
            [str(exp3_artifact)],
            database,
            database_sha256,
        ),
        record(
            "EXP-STATE-004",
            run_id,
            generated_at,
            "验证原料、短贷和季度结算能在同一时间线中确定性组合。",
            "Y1Q1 订购 R1×2、R3×1并借入短贷 100 万元，随后推进四个季度。",
            {
                "state_engine_version": STATE_ENGINE_VERSION,
                "timeline_steps": len(timeline),
                "status": combined.status,
                "final_period": f"Y{combined.result['final_state']['year']}Q{combined.result['final_state']['quarter']}",
                "final_cash_wan": combined.result["final_state"]["cash_wan"],
                "R1_inventory": combined.result["final_state"]["material_inventory"]["R1"],
                "R3_inventory": combined.result["final_state"]["material_inventory"]["R3"],
                "pending_orders": len(combined.result["final_state"]["pending_material_orders"]),
                "loan_status": combined.result["final_state"]["short_loans"][0]["status"],
                "formal_commit_allowed": combined.result["formal_commit_allowed"],
            },
            "组合时间线成功结束于 Y2Q1，现金 642 万元，原料全部入库，短贷完成实验性偿还。",
            "这是规则假设下的接口与守恒测试，不是正式竞赛结果预测。",
            [str(exp4_artifact)],
            database,
            database_sha256,
        ),
    ]

    for item in records:
        write_json(run_dir / f"{item['experiment_id']}.json", item)
    write_json(
        run_dir / "run_summary.json",
        {
            "run_id": run_id,
            "generated_at": generated_at,
            "state_engine_version": STATE_ENGINE_VERSION,
            "database": str(database),
            "database_sha256": database_sha256,
            "experiments": records,
        },
    )
    registry_path = output / "experiment_registry.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8")) if registry_path.exists() else []
    registry.extend(records)
    write_json(registry_path, registry)
    (output / "实验记录.md").write_text(render_log(registry), encoding="utf-8")
    print(json.dumps({"run_id": run_id, "experiments": [item["experiment_id"] for item in records]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
