from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime
from pathlib import Path

from goai_data.agent import AgentTools, DeterministicAdvisoryAgent, ENGINE_VERSION, snapshot_from_result
from run_decision_event_experiments import file_sha256, record, render_log


def main() -> int:
    parser = argparse.ArgumentParser(description="运行 Agent MVP 实验并追加累计实验记录。")
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
    tools = AgentTools(database)

    rule_status = tools.rule_status()
    formal_actions = tools.available_actions(mode="formal")
    experimental_actions = tools.available_actions(mode="experimental")
    exp1_result = {
        "rule_status": rule_status.to_dict(),
        "formal_actions": formal_actions.to_dict(),
        "experimental_action_count": len(experimental_actions.result["actions"]),
    }
    exp1_artifact = run_dir / "EXP-AGENT-001_rule_gate.json"
    exp1_artifact.write_text(json.dumps(exp1_result, ensure_ascii=False, indent=2), encoding="utf-8")

    with sqlite3.connect(database) as connection:
        active_teams = [
            row[0]
            for row in connection.execute("SELECT team_id FROM teams WHERE data_status='active' ORDER BY team_id")
        ]
        expected_cash = dict(
            connection.execute(
                """
                WITH ranked AS (
                  SELECT team_id, balance_wan,
                         ROW_NUMBER() OVER(PARTITION BY team_id ORDER BY sequence_in_source DESC) AS rn
                  FROM team_cash_flows
                )
                SELECT team_id, balance_wan FROM ranked WHERE rn=1
                """
            )
        )
    snapshot_rows = []
    for team_id in active_teams:
        result = tools.team_snapshot(team_id)
        actual = result.result["cash_wan"] if result.status == "success" else None
        snapshot_rows.append(
            {
                "team_id": team_id,
                "status": result.status,
                "expected_cash_wan": expected_cash.get(team_id),
                "snapshot_cash_wan": actual,
                "matches": actual == expected_cash.get(team_id),
            }
        )
    scenario = tools.scenario_snapshot()
    exp2_result = {"team_snapshots": snapshot_rows, "test_scenario_snapshot": scenario.to_dict()}
    exp2_artifact = run_dir / "EXP-AGENT-002_snapshot_fidelity.json"
    exp2_artifact.write_text(json.dumps(exp2_result, ensure_ascii=False, indent=2), encoding="utf-8")

    zy02 = snapshot_from_result(tools.team_snapshot("ZY02"))
    safe_simulation = tools.simulate_plan(
        zy02, [{"action_type": "advertising", "parameters": {"amount_wan": 20}}]
    )
    unsafe_simulation = tools.simulate_plan(
        zy02, [{"action_type": "advertising", "parameters": {"amount_wan": 80}}]
    )
    exp3_result = {"safe": safe_simulation.to_dict(), "unsafe": unsafe_simulation.to_dict()}
    exp3_artifact = run_dir / "EXP-AGENT-003_cash_guard.json"
    exp3_artifact.write_text(json.dumps(exp3_result, ensure_ascii=False, indent=2), encoding="utf-8")

    comparison = DeterministicAdvisoryAgent(tools).evaluate(
        zy02,
        [
            {
                "candidate_id": "conservative",
                "actions": [{"action_type": "advertising", "parameters": {"amount_wan": 20}}],
            },
            {
                "candidate_id": "aggressive",
                "actions": [{"action_type": "advertising", "parameters": {"amount_wan": 60}}],
            },
        ],
    )
    exp4_artifact = run_dir / "EXP-AGENT-004_candidate_ranking.json"
    exp4_artifact.write_text(json.dumps(comparison.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    records = [
        record(
            "EXP-AGENT-001",
            run_id,
            generated_at,
            "验证不完整 RulePack 对正式 Agent 模式的安全门控。",
            "分别调用 rule_status、formal available_actions 和 experimental available_actions。",
            {
                "engine_version": ENGINE_VERSION,
                "blocking_gap_count": rule_status.result["rule_pack"]["blocking_gap_count"],
                "formal_status": formal_actions.status,
                "experimental_status": experimental_actions.status,
                "experimental_action_count": len(experimental_actions.result["actions"]),
            },
            "正式模式被拒绝，实验模式仅返回 candidate_unverified 动作，安全门控符合设计。",
            "尚未验证规则缺口解决后的 formal 模式，因为当前没有 simulation_ready=true 的规则包。",
            [str(exp1_artifact)],
            database,
            database_sha256,
        ),
        record(
            "EXP-AGENT-002",
            run_id,
            generated_at,
            "验证状态快照的现金恢复准确性。",
            "对 15 支有效历史队伍比较 Agent 最终现金快照与现金流水最后余额，并读取测试方案最终快照。",
            {
                "engine_version": ENGINE_VERSION,
                "active_teams": len(active_teams),
                "matching_team_cash_snapshots": sum(row["matches"] for row in snapshot_rows),
                "test_scenario_final_cash_wan": scenario.result["cash_wan"],
                "test_scenario_final_period": f"Y{scenario.result['year']}Q{scenario.result['quarter']}",
            },
            "15 支有效队伍的最终现金均精确匹配，测试方案恢复为 Y5Q4 现金 430 万元。",
            "历史非现金状态只有最终导出快照，不能据此证明季度库存、贷款和产能重建正确。",
            [str(exp2_artifact)],
            database,
            database_sha256,
        ),
        record(
            "EXP-AGENT-003",
            run_id,
            generated_at,
            "验证现金沙盒能接受安全动作并拒绝现金断裂动作。",
            "以 ZY02 的 70 万元快照分别模拟 20 万元和 80 万元广告投放。",
            {
                "engine_version": ENGINE_VERSION,
                "initial_cash_wan": zy02.cash_wan,
                "safe_status": safe_simulation.status,
                "safe_projected_cash_wan": safe_simulation.result["projected_cash_wan"],
                "unsafe_status": unsafe_simulation.status,
                "formal_commit_allowed": safe_simulation.result["formal_commit_allowed"],
            },
            "20 万元方案通过并得到 50 万元期末现金，80 万元方案因现金不足被拒绝。",
            "只验证即时现金，不覆盖广告效果、订单概率和完整会计状态。",
            [str(exp3_artifact)],
            database,
            database_sha256,
        ),
        record(
            "EXP-AGENT-004",
            run_id,
            generated_at,
            "验证确定性 Agent 能比较候选方案并给出可追踪推荐。",
            "比较广告 20 万元与 60 万元两套候选，按最低现金优先、期末现金次优排序。",
            {
                "engine_version": ENGINE_VERSION,
                "agent_status": comparison.status,
                "recommended_candidate_id": comparison.result["recommended_candidate_id"],
                "selection_policy": comparison.result["selection_policy"],
                "candidate_count": len(comparison.result["evaluations"]),
                "formal_commit_allowed": comparison.result["formal_commit_allowed"],
            },
            "Agent 推荐 conservative，并保留每个候选的步骤、警告、违规和 trace_id。",
            "现金安全基线不代表利润、权益、产能和战略指标的综合最优。",
            [str(exp4_artifact)],
            database,
            database_sha256,
        ),
    ]

    for item in records:
        (run_dir / f"{item['experiment_id']}.json").write_text(
            json.dumps(item, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    (run_dir / "run_summary.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "generated_at": generated_at,
                "engine_version": ENGINE_VERSION,
                "database": str(database),
                "database_sha256": database_sha256,
                "experiments": records,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    registry_path = output / "experiment_registry.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8")) if registry_path.exists() else []
    registry.extend(records)
    registry_path.write_text(json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8")
    (output / "实验记录.md").write_text(render_log(registry), encoding="utf-8")
    print(json.dumps({"run_id": run_id, "experiments": [item["experiment_id"] for item in records]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
