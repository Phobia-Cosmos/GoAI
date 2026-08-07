from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_csv(frame: pd.DataFrame, path: Path) -> None:
    frame.to_csv(path, index=False, encoding="utf-8-sig")


def record(
    experiment_id: str,
    run_id: str,
    generated_at: str,
    objective: str,
    method: str,
    metrics: dict[str, Any],
    conclusion: str,
    limitations: str,
    artifacts: list[str],
    database: Path,
    database_sha256: str,
) -> dict[str, Any]:
    return {
        "experiment_id": experiment_id,
        "run_id": run_id,
        "generated_at": generated_at,
        "objective": objective,
        "input": {
            "database": str(database.resolve()),
            "database_sha256": database_sha256,
        },
        "method": method,
        "metrics": metrics,
        "conclusion": conclusion,
        "limitations": limitations,
        "artifacts": artifacts,
    }


def render_log(records: list[dict[str, Any]]) -> str:
    lines = [
        "# GoAI 实验记录",
        "",
        "本文件由实验脚本自动维护。每次实验均保留运行编号、时间、输入指纹、方法、指标、结论、限制和产物，不用后续结果覆盖历史记录。",
        "",
    ]
    for item in records:
        lines.extend(
            [
                f"## {item['experiment_id']} · {item['run_id']}",
                "",
                f"- 时间：{item['generated_at']}",
                f"- 目标：{item['objective']}",
                f"- 输入：`{item['input']['database']}`",
                f"- 输入 SHA-256：`{item['input']['database_sha256']}`",
                f"- 方法：{item['method']}",
                f"- 结论：{item['conclusion']}",
                f"- 限制：{item['limitations']}",
                "- 指标：",
                "",
                "```json",
                json.dumps(item["metrics"], ensure_ascii=False, indent=2),
                "```",
                "",
                "- 产物：",
                "",
            ]
        )
        lines.extend(f"  - `{artifact}`" for artifact in item["artifacts"])
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="运行 GoAI 决策事件实验并写入累计实验记录。")
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

    with sqlite3.connect(database) as connection:
        events = pd.read_sql_query("SELECT * FROM action_events", connection)
        definitions = pd.read_sql_query("SELECT * FROM action_definitions", connection)

    decisions = events[events["is_agent_candidate"] == 1].copy()
    historical_decisions = decisions[decisions["event_source"] == "historical_cash_flow"].copy()

    inventory = definitions.copy()
    inventory["total_observation_count"] = (
        inventory["historical_observation_count"] + inventory["test_observation_count"]
    )
    inventory = inventory.sort_values(
        ["is_agent_candidate", "category", "canonical_action"], ascending=[False, True, True]
    )
    exp1_name = "EXP-DEC-001_action_inventory.csv"
    write_csv(inventory, run_dir / exp1_name)

    exp1_metrics = {
        "standard_action_types": int(len(definitions)),
        "agent_candidate_action_types": int(definitions["is_agent_candidate"].sum()),
        "direct_decision_types": int((definitions["control_type"] == "direct_decision").sum()),
        "conditional_decision_types": int((definitions["control_type"] == "conditional_decision").sum()),
        "exception_intervention_types": int((definitions["control_type"] == "exception_intervention").sum()),
        "external_outcome_types": int((definitions["control_type"] == "external_outcome").sum()),
        "non_agent_action_types": int((definitions["is_agent_candidate"] == 0).sum()),
        "classification_version": "decision_control_v2",
        "all_events": int(len(events)),
        "decision_candidate_events": int(len(decisions)),
        "historical_decision_candidate_events": int(len(historical_decisions)),
    }

    parameter_coverage = (
        decisions.groupby(["canonical_action", "category", "control_type"], dropna=False)
        .agg(
            event_count=("event_id", "count"),
            complete_count=("parameter_parse_status", lambda x: int((x == "complete").sum())),
            partial_count=("parameter_parse_status", lambda x: int((x == "partial").sum())),
            not_applicable_count=("parameter_parse_status", lambda x: int((x == "not_applicable").sum())),
        )
        .reset_index()
    )
    parameter_coverage["complete_rate"] = (
        parameter_coverage["complete_count"] / parameter_coverage["event_count"]
    ).round(6)
    parameter_coverage["partial_rate"] = (
        parameter_coverage["partial_count"] / parameter_coverage["event_count"]
    ).round(6)
    parameter_coverage = parameter_coverage.sort_values(
        ["partial_rate", "event_count"], ascending=[False, False]
    )
    exp2_name = "EXP-DEC-002_parameter_recovery.csv"
    write_csv(parameter_coverage, run_dir / exp2_name)
    decision_complete = int((decisions["parameter_parse_status"] == "complete").sum())
    decision_partial = int((decisions["parameter_parse_status"] == "partial").sum())
    decision_not_applicable = int((decisions["parameter_parse_status"] == "not_applicable").sum())
    exp2_metrics = {
        "decision_events": int(len(decisions)),
        "complete": decision_complete,
        "partial": decision_partial,
        "not_applicable": decision_not_applicable,
        "complete_rate_all_decisions": round(decision_complete / len(decisions), 6),
        "complete_or_not_applicable_rate": round(
            (decision_complete + decision_not_applicable) / len(decisions), 6
        ),
        "actions_with_partial_events": int((parameter_coverage["partial_count"] > 0).sum()),
    }

    timing = (
        historical_decisions.groupby(
            ["canonical_action", "category", "control_type", "year", "quarter"], dropna=False
        )
        .agg(event_count=("event_id", "count"), distinct_teams=("team_id", "nunique"))
        .reset_index()
        .sort_values(["canonical_action", "year", "quarter"])
    )
    exp3_name = "EXP-DEC-003_observed_timing.csv"
    write_csv(timing, run_dir / exp3_name)
    exp3_metrics = {
        "historical_decision_events": int(len(historical_decisions)),
        "distinct_teams": int(historical_decisions["team_id"].nunique()),
        "observed_year_min": int(historical_decisions["year"].min()),
        "observed_year_max": int(historical_decisions["year"].max()),
        "action_period_combinations": int(len(timing)),
        "actions_observed_in_all_four_quarters": int(
            (timing.groupby("canonical_action")["quarter"].nunique() == 4).sum()
        ),
    }

    sequence_rows: list[dict[str, Any]] = []
    ordered = historical_decisions.sort_values(["team_id", "sequence"])
    for team_id, group in ordered.groupby("team_id", sort=False):
        actions = group["canonical_action"].tolist()
        for left, right in zip(actions, actions[1:]):
            sequence_rows.append({"team_id": team_id, "from_action": left, "to_action": right})
    transitions = pd.DataFrame(sequence_rows)
    transitions = (
        transitions.groupby(["from_action", "to_action"])
        .agg(transition_count=("team_id", "count"), distinct_teams=("team_id", "nunique"))
        .reset_index()
        .sort_values(["transition_count", "distinct_teams"], ascending=False)
    )
    exp4_name = "EXP-DEC-004_action_transitions.csv"
    write_csv(transitions, run_dir / exp4_name)
    exp4_metrics = {
        "transition_instances": int(len(sequence_rows)),
        "distinct_transition_types": int(len(transitions)),
        "top_transition": (
            f"{transitions.iloc[0]['from_action']} -> {transitions.iloc[0]['to_action']}"
            if not transitions.empty
            else None
        ),
        "top_transition_count": int(transitions.iloc[0]["transition_count"]) if not transitions.empty else 0,
    }

    artifact_prefix = str(run_dir)
    new_records = [
        record(
            "EXP-DEC-001",
            run_id,
            generated_at,
            "区分 Agent 候选决策动作与系统结算动作，并统计类型和事件覆盖。",
            "基于 action_definitions.control_type 分类并汇总 action_events。",
            exp1_metrics,
            "标准动作必须先区分控制权，结算事件不得进入 Agent 动作空间。",
            "控制属性来自当前业务分析，仍需在正式流程规则取得后复核。",
            [f"{artifact_prefix}/{exp1_name}"],
            database,
            database_sha256,
        ),
        record(
            "EXP-DEC-002",
            run_id,
            generated_at,
            "评估 Agent 候选决策事件的动作参数可恢复程度。",
            "按 canonical_action 汇总 complete、partial 和 not_applicable 参数解析状态。",
            exp2_metrics,
            "可完整恢复的事件可进入后续状态重建；partial 事件需要结合其他业务表或规则补全。",
            "参数完整表示从现有文本成功抽取，不代表动作规则已经得到题面确认。",
            [f"{artifact_prefix}/{exp2_name}"],
            database,
            database_sha256,
        ),
        record(
            "EXP-DEC-003",
            run_id,
            generated_at,
            "观察历史决策动作在年度和季度中的实际出现时点。",
            "对历史 Agent 候选事件按动作、年度、季度和队伍聚合。",
            exp3_metrics,
            "观察分布可用于设计候选检查点，但不能直接升级为允许动作阶段规则。",
            "历史数据属于未知 600W 规则，只能作为规则发现证据。",
            [f"{artifact_prefix}/{exp3_name}"],
            database,
            database_sha256,
        ),
        record(
            "EXP-DEC-004",
            run_id,
            generated_at,
            "发现历史决策动作之间的常见相邻关系。",
            "剔除结算事件后，按队伍源序列统计相邻标准决策动作转移。",
            exp4_metrics,
            "常见转移可以作为工作流候选和案例检索特征，不能解释为因果或强制流程。",
            "剔除结算事件会压缩真实时间间隔，且未知规则下的行为可能包含低质量决策。",
            [f"{artifact_prefix}/{exp4_name}"],
            database,
            database_sha256,
        ),
    ]

    for item in new_records:
        (run_dir / f"{item['experiment_id']}.json").write_text(
            json.dumps(item, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    (run_dir / "run_summary.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "generated_at": generated_at,
                "database": str(database),
                "database_sha256": database_sha256,
                "experiments": new_records,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    registry_path = output / "experiment_registry.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8")) if registry_path.exists() else []
    registry.extend(new_records)
    registry_path.write_text(json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8")
    (output / "实验记录.md").write_text(render_log(registry), encoding="utf-8")
    print(json.dumps({"run_id": run_id, "experiments": [x["experiment_id"] for x in new_records]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
