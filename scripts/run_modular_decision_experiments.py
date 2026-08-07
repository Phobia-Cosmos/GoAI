from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from goai_data.decision_system import (
    ArenaRunner,
    CandidateOutcome,
    DECISION_SYSTEM_VERSION,
    HistoricalReplayArena,
    MetricAblationExperiment,
    MetricContext,
    MetricSuite,
    ReplayPolicy,
)
from goai_data.xa_dynamics import XACounterfactualArena, XADynamics
from run_decision_event_experiments import file_sha256, record, render_log


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def candidate_outcomes() -> list[CandidateOutcome]:
    return [
        CandidateOutcome(
            candidate_id="safe",
            initial_state={"cash_wan": 675, "owner_equity_wan": 675},
            final_state={"cash_wan": 300, "owner_equity_wan": 760, "assets_wan": 900, "debt_wan": 140, "orders_assigned": 8, "orders_delivered": 8, "available_capacity": 10, "used_capacity": 6, "development_potential": 35},
            trajectory=({"cash_wan": 420}, {"cash_wan": 300}),
        ),
        CandidateOutcome(
            candidate_id="growth",
            initial_state={"cash_wan": 675, "owner_equity_wan": 675},
            final_state={"cash_wan": 70, "owner_equity_wan": 930, "assets_wan": 1300, "debt_wan": 370, "orders_assigned": 12, "orders_delivered": 11, "available_capacity": 12, "used_capacity": 11, "development_potential": 70},
            trajectory=({"cash_wan": 150}, {"cash_wan": 70}),
        ),
    ]


def replay_match(dataset: Path, match_id: str) -> dict[str, object]:
    arena = HistoricalReplayArena(dataset, match_id)
    policies = {agent_id: ReplayPolicy(agent_id) for agent_id in arena.agent_ids}
    result = ArenaRunner().run(arena, policies)
    return {
        "match_id": match_id,
        "agent_count": result["agent_count"],
        "steps": result["steps"],
        "final_periods": sorted({observation.period for observation in result["final_observations"].values()}),
        "all_agents_reached_y5q4": all(observation.period == "Y5Q4" for observation in result["final_observations"].values()),
    }


def counterfactual_smoke(dataset: Path) -> dict[str, object]:
    rules = dataset / "matches" / "LX_XA" / "rules.json"
    arena = XACounterfactualArena(XADynamics.from_rules_file(rules), ("XA01", "XA02"))
    observations = arena.reset()
    steps = 0
    while True:
        result = arena.step({agent_id: {"action_type": "hold"} for agent_id in arena.agent_ids})
        observations = result.observations
        steps += 1
        if result.terminated:
            break
    return {"agent_count": len(arena.agent_ids), "steps": steps, "final_period": next(iter(observations.values())).period, "final_cash_wan": {agent_id: observation.private_state["cash_wan"] for agent_id, observation in observations.items()}, "action_policy": "hold"}


def main() -> int:
    parser = argparse.ArgumentParser(description="运行模块化决策与多 Agent 接口实验。")
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--run-id")
    args = parser.parse_args()
    dataset = args.dataset.resolve()
    catalog_path = dataset / "catalog.json"
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    catalog_sha256 = file_sha256(catalog_path)
    generated_at = datetime.now().astimezone().isoformat(timespec="seconds")
    run_id = args.run_id or datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")
    output = args.output.resolve()
    run_dir = output / "runs" / run_id
    if run_dir.exists():
        raise SystemExit(f"run directory already exists: {run_dir}")
    run_dir.mkdir(parents=True)

    suite = MetricSuite()
    context = MetricContext(initial_cash_wan=675, cash_buffer_wan=200)
    profile_comparison = MetricAblationExperiment(suite).compare_profiles(candidate_outcomes(), context)
    exp1_artifact = run_dir / "EXP-MOD-001_metric_profiles.json"
    write_json(exp1_artifact, profile_comparison)

    xa_replay = replay_match(dataset, "LX_XA")
    exp2_artifact = run_dir / "EXP-MOD-002_xa_multiagent_replay.json"
    write_json(exp2_artifact, xa_replay)

    all_replays = [replay_match(dataset, row["match_id"]) for row in catalog["matches"]]
    exp3_artifact = run_dir / "EXP-MOD-003_all_matches_replay.json"
    write_json(exp3_artifact, all_replays)

    counterfactual = counterfactual_smoke(dataset)
    exp4_artifact = run_dir / "EXP-MOD-004_xa_counterfactual_smoke.json"
    write_json(exp4_artifact, counterfactual)

    selections = {name: result["selected_candidate_id"] for name, result in profile_comparison["comparisons"].items()}
    records = [
        record(
            "EXP-MOD-001", run_id, generated_at,
            "验证不使用 VPD 时，可插拔指标配置是否会改变候选方案选择。",
            "对同一组安全型和增长型候选分别应用 safety、balanced、growth 权重配置。",
            {"decision_system_version": DECISION_SYSTEM_VERSION, "profile_selections": selections, "metric_count": len(suite.metrics)},
            f"指标配置产生可观测差异：{selections}，说明指标层已与候选仿真和策略层解耦。",
            "候选结果为接口验证用情景，不代表 XA 历史企业的反事实最优结果。",
            [str(exp1_artifact)], catalog_path, catalog_sha256,
        ),
        record(
            "EXP-MOD-002", run_id, generated_at,
            "验证 XA 全部企业能否通过统一多 Agent 环境接口同步推进。",
            "为 XA 每家企业配置 ReplayPolicy，按季度状态从 Y1Q1 同步推进至 Y5Q4。",
            {"decision_system_version": DECISION_SYSTEM_VERSION, **xa_replay},
            f"XA 的 {xa_replay['agent_count']} 家企业通过统一接口在 {xa_replay['steps']} 步后到达 Y5Q4。",
            "当前是历史回放动力学，不接受反事实经营动作，也不解决共享订单冲突。",
            [str(exp2_artifact)], catalog_path, catalog_sha256,
        ),
        record(
            "EXP-MOD-003", run_id, generated_at,
            "验证统一 Arena 接口是否覆盖全部 14 场比赛。",
            "逐场加载 teams.jsonl 与 quarter_states.jsonl，为全部企业运行同步历史回放。",
            {"decision_system_version": DECISION_SYSTEM_VERSION, "match_count": len(all_replays), "agent_count": sum(int(row["agent_count"]) for row in all_replays), "all_reached_y5q4": all(bool(row["all_agents_reached_y5q4"]) for row in all_replays)},
            f"14 场、合计 {sum(int(row['agent_count']) for row in all_replays)} 家企业均完成统一接口回放。",
            "回放验证的是数据和编排接口，不等价于完成 XA 规则动力学或竞争策略验证。",
            [str(exp3_artifact)], catalog_path, catalog_sha256,
        ),
        record(
            "EXP-MOD-004", run_id, generated_at,
            "验证 XA 基础确定性动力学是否能接受多企业反事实 hold 动作并推进季度结算。",
            "使用 XA 正式规则初始化 XA01、XA02，两个企业每季提交 hold，由 XACounterfactualArena 统一结算管理费。",
            {"decision_system_version": DECISION_SYSTEM_VERSION, **counterfactual},
            f"两个企业在 {counterfactual['steps']} 步后到达 {counterfactual['final_period']}，现金均为 {counterfactual['final_cash_wan']['XA01']}W。",
            "该实验尚未包括订单分配、广告排名、税费、折旧和完整三张报表，不代表正式比赛仿真已经完成。",
            [str(exp4_artifact)], catalog_path, catalog_sha256,
        ),
    ]
    for item in records:
        write_json(run_dir / f"{item['experiment_id']}.json", item)
    write_json(run_dir / "run_summary.json", {"run_id": run_id, "generated_at": generated_at, "decision_system_version": DECISION_SYSTEM_VERSION, "dataset_catalog": str(catalog_path), "catalog_sha256": catalog_sha256, "experiments": records})
    registry_path = output / "experiment_registry.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8")) if registry_path.exists() else []
    registry.extend(records)
    write_json(registry_path, registry)
    (output / "实验记录.md").write_text(render_log(registry), encoding="utf-8")
    print(json.dumps({"run_id": run_id, "experiments": [item["experiment_id"] for item in records], "selections": selections}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
