from __future__ import annotations

import argparse
import json
from pathlib import Path

from .agent import AgentTools, DeterministicAdvisoryAgent, ToolResult, snapshot_from_result
from .pre_agent import PreAgentKernel
from .state_engine import ExperimentalState, ExperimentalStateEngine


DEFAULT_DATABASE = Path("/home/undefined/Disk/datasets/goai/processed/v1/goai.sqlite")


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="GoAI 实验性 Agent MVP")
    root.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    commands = root.add_subparsers(dest="command", required=True)

    status = commands.add_parser("status", help="查看规则包和 Agent 可用状态")
    status.add_argument("--rule-version", default="zhejiang_8th_rules_v1")

    actions = commands.add_parser("actions", help="列出 Agent 候选动作")
    actions.add_argument("--rule-version", default="zhejiang_8th_rules_v1")
    actions.add_argument("--mode", choices=["experimental", "formal"], default="experimental")

    snapshot = commands.add_parser("snapshot", help="生成状态快照")
    source = snapshot.add_mutually_exclusive_group(required=True)
    source.add_argument("--team-id")
    source.add_argument("--scenario-id")
    snapshot.add_argument("--year", type=int)
    snapshot.add_argument("--quarter", type=int)

    simulate = commands.add_parser("simulate", help="运行实验性现金计划仿真")
    source = simulate.add_mutually_exclusive_group(required=True)
    source.add_argument("--team-id")
    source.add_argument("--scenario-id")
    simulate.add_argument("--actions-json", type=Path, required=True)
    simulate.add_argument("--year", type=int)
    simulate.add_argument("--quarter", type=int)

    advise = commands.add_parser("advise", help="比较多套候选方案")
    source = advise.add_mutually_exclusive_group(required=True)
    source.add_argument("--team-id")
    source.add_argument("--scenario-id")
    advise.add_argument("--candidates-json", type=Path, required=True)
    advise.add_argument("--year", type=int)
    advise.add_argument("--quarter", type=int)

    state = commands.add_parser("state-simulate", help="运行跨季度原料和短贷状态仿真")
    state.add_argument("--state-json", type=Path)
    state.add_argument("--timeline-json", type=Path, required=True)

    commands.add_parser("pre-agent-status", help="查看 Agent 前置决策内核完整性")

    metrics = commands.add_parser("state-metrics", help="计算实验状态指标与风险")
    metrics.add_argument("--state-json", type=Path)

    compare = commands.add_parser("compare-state-plans", help="比较多套跨季度状态方案")
    compare.add_argument("--state-json", type=Path)
    compare.add_argument("--candidates-json", type=Path, required=True)
    return root


def main() -> None:
    args = parser().parse_args()
    tools = AgentTools(args.database)
    if args.command == "status":
        result = tools.rule_status(args.rule_version)
    elif args.command == "actions":
        result = tools.available_actions(args.rule_version, args.mode)
    elif args.command == "state-simulate":
        engine = ExperimentalStateEngine(args.database)
        if args.state_json:
            state = ExperimentalState.from_dict(
                json.loads(args.state_json.read_text(encoding="utf-8"))
            )
        else:
            initial = engine.initial_state()
            if initial.status != "success":
                print(json.dumps(initial.to_dict(), ensure_ascii=False, indent=2))
                return
            state = ExperimentalState.from_dict(initial.result)
        timeline = json.loads(args.timeline_json.read_text(encoding="utf-8"))
        result = engine.simulate_timeline(state, timeline)
    elif args.command == "pre-agent-status":
        readiness = PreAgentKernel(args.database).readiness()
        result = ToolResult(
            status="success",
            result=readiness.to_dict(),
            warnings=[] if readiness.formal_ready else ["前置内核仅达到实验就绪，正式规则仍有外部 blocker"],
            suggested_next_tools=["state-metrics", "compare-state-plans"],
            rule_version="zhejiang_8th_rules_v1",
        )
    elif args.command in {"state-metrics", "compare-state-plans"}:
        engine = ExperimentalStateEngine(args.database)
        kernel = PreAgentKernel(args.database)
        if args.state_json:
            state = ExperimentalState.from_dict(json.loads(args.state_json.read_text(encoding="utf-8")))
        else:
            state = ExperimentalState.from_dict(engine.initial_state().result)
        if args.command == "state-metrics":
            result = kernel.metrics(state)
        else:
            candidates = json.loads(args.candidates_json.read_text(encoding="utf-8"))
            result = kernel.compare_plans(state, candidates)
    else:
        if args.team_id:
            snapshot_result = tools.team_snapshot(args.team_id, args.year, args.quarter)
        else:
            snapshot_result = tools.scenario_snapshot(args.scenario_id, args.year, args.quarter)
        if args.command == "snapshot" or snapshot_result.status != "success":
            result = snapshot_result
        else:
            snapshot = snapshot_from_result(snapshot_result)
            if args.command == "simulate":
                actions = json.loads(args.actions_json.read_text(encoding="utf-8"))
                result = tools.simulate_plan(snapshot, actions)
            else:
                candidates = json.loads(args.candidates_json.read_text(encoding="utf-8"))
                result = DeterministicAdvisoryAgent(tools).evaluate(snapshot, candidates)
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
