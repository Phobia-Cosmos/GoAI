from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


ENGINE_VERSION = "agent_mvp_v0.3"


@dataclass(frozen=True)
class StateSnapshot:
    snapshot_id: str
    competition_id: str
    rule_version: str
    year: int
    quarter: int
    cash_wan: float
    team_id: str | None = None
    scenario_id: str | None = None
    source_kind: str = "unknown"
    completeness: str = "cash_only"
    state: dict[str, Any] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["warnings"] = list(self.warnings)
        return payload


@dataclass
class ToolResult:
    status: str
    result: Any = None
    violations: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    required_preconditions: list[str] = field(default_factory=list)
    suggested_next_tools: list[str] = field(default_factory=list)
    input_snapshot_id: str | None = None
    rule_version: str | None = None
    engine_version: str = ENGINE_VERSION
    trace_id: str = field(default_factory=lambda: uuid.uuid4().hex)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _snapshot_id(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "snap_" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]


class AgentTools:
    def __init__(self, database: Path) -> None:
        self.database = database.resolve()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database)
        connection.row_factory = sqlite3.Row
        return connection

    def rule_status(self, rule_version: str = "zhejiang_8th_rules_v1") -> ToolResult:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM rule_packs WHERE rule_version = ?", (rule_version,)
            ).fetchone()
            if row is None:
                return ToolResult(
                    status="needs_input",
                    violations=[f"未找到规则包：{rule_version}"],
                    required_preconditions=["绑定有效 rule_version"],
                    suggested_next_tools=["rule_status"],
                    rule_version=rule_version,
                )
            gaps = [
                dict(item)
                for item in connection.execute(
                    "SELECT gap_id, domain, title, severity, status FROM rule_gaps WHERE rule_version = ? ORDER BY severity, gap_id",
                    (rule_version,),
                )
            ]
        return ToolResult(
            status="success",
            result={"rule_pack": dict(row), "unresolved_gaps": gaps},
            warnings=["规则包不可用于正式完整仿真"] if not row["simulation_ready"] else [],
            suggested_next_tools=["available_actions"],
            rule_version=rule_version,
        )

    def available_actions(
        self,
        rule_version: str = "zhejiang_8th_rules_v1",
        mode: str = "experimental",
    ) -> ToolResult:
        rule = self.rule_status(rule_version)
        if rule.status != "success":
            return rule
        pack = rule.result["rule_pack"]
        if mode == "formal" and not pack["simulation_ready"]:
            return ToolResult(
                status="rejected",
                violations=["规则包 simulation_ready=false，禁止正式决策"],
                required_preconditions=["解决所有 blocker 级规则缺口并通过历史重放"],
                suggested_next_tools=["rule_status"],
                rule_version=rule_version,
            )
        with self._connect() as connection:
            actions = [
                dict(row)
                for row in connection.execute(
                    """
                    SELECT canonical_action, category, description, control_type,
                           semantic_status, executable_status
                    FROM action_definitions
                    WHERE is_agent_candidate = 1
                    ORDER BY category, canonical_action
                    """
                )
            ]
        for action in actions:
            action["availability"] = "candidate_unverified" if not pack["simulation_ready"] else "available"
        return ToolResult(
            status="success",
            result={"mode": mode, "actions": actions},
            warnings=rule.warnings if mode == "experimental" else [],
            suggested_next_tools=["validate_action", "simulate_plan"],
            rule_version=rule_version,
        )

    def team_snapshot(
        self,
        team_id: str,
        year: int | None = None,
        quarter: int | None = None,
    ) -> ToolResult:
        with self._connect() as connection:
            team = connection.execute("SELECT * FROM teams WHERE team_id = ?", (team_id,)).fetchone()
            if team is None:
                return ToolResult(
                    status="needs_input",
                    violations=[f"未知队伍：{team_id}"],
                    required_preconditions=["提供 teams 表中的 team_id"],
                    suggested_next_tools=["team_snapshot"],
                    rule_version="unknown",
                )
            params: list[Any] = [team_id]
            predicate = "team_id = ?"
            if year is not None:
                predicate += " AND (year < ? OR (year = ? AND quarter <= ?))"
                params.extend([year, year, quarter or 4])
            cash = connection.execute(
                f"SELECT * FROM team_cash_flows WHERE {predicate} ORDER BY sequence_in_source DESC LIMIT 1",
                params,
            ).fetchone()
            if cash is None:
                return ToolResult(
                    status="needs_input",
                    violations=[f"队伍 {team_id} 在指定时点没有现金流水"],
                    required_preconditions=["选择有经营流水的队伍和时点"],
                    suggested_next_tools=["team_snapshot"],
                    rule_version="unknown",
                )
            counts = {}
            for table, key in (
                ("team_material_inventory", "material_inventory_rows"),
                ("team_product_inventory", "product_inventory_rows"),
                ("team_loans", "loan_rows"),
                ("team_receivables", "receivable_rows"),
                ("team_factories", "factory_rows"),
                ("team_production_lines", "production_line_rows"),
                ("team_qualifications", "qualification_rows"),
                ("team_orders", "order_rows"),
            ):
                counts[key] = connection.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE team_id = ?", (team_id,)
                ).fetchone()[0]
        snapshot_payload = {
            "competition_id": team["competition_id"],
            "rule_version": team["rule_version"],
            "team_id": team_id,
            "year": int(cash["year"]),
            "quarter": int(cash["quarter"]),
            "cash_wan": float(cash["balance_wan"]),
            "sequence": int(cash["sequence_in_source"]),
        }
        warnings = (
            "历史规则版本未知，仅允许实验性分析",
            "除现金外的库存、贷款和产能表是导出时最终快照，不能用于历史时点重放",
        )
        snapshot = StateSnapshot(
            snapshot_id=_snapshot_id(snapshot_payload),
            competition_id=team["competition_id"],
            rule_version=team["rule_version"],
            team_id=team_id,
            scenario_id=None,
            year=int(cash["year"]),
            quarter=int(cash["quarter"]),
            cash_wan=float(cash["balance_wan"]),
            source_kind="historical_team",
            completeness="cash_at_time_plus_final_entity_counts",
            state={"cash_event_sequence": int(cash["sequence_in_source"]), **counts},
            warnings=warnings,
        )
        return ToolResult(
            status="success",
            result=snapshot.to_dict(),
            warnings=list(warnings),
            suggested_next_tools=["available_actions", "simulate_plan"],
            input_snapshot_id=snapshot.snapshot_id,
            rule_version=snapshot.rule_version,
        )

    def scenario_snapshot(
        self,
        scenario_id: str = "9line_p1_p4_2937",
        year: int | None = None,
        quarter: int | None = None,
    ) -> ToolResult:
        params: list[Any] = [scenario_id]
        predicate = "scenario_id = ?"
        if year is not None:
            predicate += " AND (year < ? OR (year = ? AND quarter <= ?))"
            params.extend([year, year, quarter or 4])
        with self._connect() as connection:
            event = connection.execute(
                f"SELECT * FROM test_cash_flow_events WHERE {predicate} ORDER BY sequence DESC LIMIT 1",
                params,
            ).fetchone()
        if event is None:
            return ToolResult(
                status="needs_input",
                violations=[f"未知或无数据的测试场景：{scenario_id}"],
                required_preconditions=["提供 test_cash_flow_events 中的 scenario_id"],
                suggested_next_tools=["scenario_snapshot"],
                rule_version="zhejiang_8th_rules_v1",
            )
        snapshot_payload = {
            "competition_id": event["competition_id"],
            "rule_version": event["rule_version"],
            "scenario_id": scenario_id,
            "year": int(event["year"]),
            "quarter": int(event["quarter"]),
            "cash_wan": float(event["balance_wan"]),
            "sequence": int(event["sequence"]),
        }
        warnings = ("测试方案目前只能可靠重建现金状态",)
        snapshot = StateSnapshot(
            snapshot_id=_snapshot_id(snapshot_payload),
            competition_id=event["competition_id"],
            rule_version=event["rule_version"],
            year=int(event["year"]),
            quarter=int(event["quarter"]),
            cash_wan=float(event["balance_wan"]),
            scenario_id=scenario_id,
            source_kind="curated_test_scenario",
            completeness="cash_only",
            state={"cash_event_sequence": int(event["sequence"])},
            warnings=warnings,
        )
        return ToolResult(
            status="success",
            result=snapshot.to_dict(),
            warnings=list(warnings),
            suggested_next_tools=["available_actions", "simulate_plan"],
            input_snapshot_id=snapshot.snapshot_id,
            rule_version=snapshot.rule_version,
        )

    def validate_action(self, snapshot: StateSnapshot, action: dict[str, Any]) -> ToolResult:
        action_type = action.get("action_type")
        parameters = action.get("parameters") or {}
        with self._connect() as connection:
            definition = connection.execute(
                "SELECT * FROM action_definitions WHERE canonical_action = ?", (action_type,)
            ).fetchone()
        if definition is None:
            return ToolResult(
                status="rejected",
                violations=[f"未知标准动作：{action_type}"],
                required_preconditions=["使用 action_definitions.canonical_action"],
                suggested_next_tools=["available_actions"],
                input_snapshot_id=snapshot.snapshot_id,
                rule_version=snapshot.rule_version,
            )
        if not definition["is_agent_candidate"]:
            return ToolResult(
                status="rejected",
                violations=[f"{action_type} 是结算、外部结果或人工事件，不是 Agent 候选动作"],
                suggested_next_tools=["available_actions"],
                input_snapshot_id=snapshot.snapshot_id,
                rule_version=snapshot.rule_version,
            )
        effect = self._cash_effect(action_type, parameters)
        if effect.status != "success":
            effect.input_snapshot_id = snapshot.snapshot_id
            effect.rule_version = snapshot.rule_version
            return effect
        cash_effect = float(effect.result["cash_effect_wan"])
        projected_cash = snapshot.cash_wan + cash_effect
        if projected_cash < 0:
            return ToolResult(
                status="rejected",
                violations=[f"现金不足：当前 {snapshot.cash_wan} 万元，动作影响 {cash_effect} 万元"],
                suggested_next_tools=["available_actions", "simulate_plan"],
                input_snapshot_id=snapshot.snapshot_id,
                rule_version=snapshot.rule_version,
            )
        return ToolResult(
            status="success",
            result={
                "action_type": action_type,
                "parameters": parameters,
                "cash_effect_wan": cash_effect,
                "projected_cash_wan": projected_cash,
            },
            warnings=[
                "仅验证动作类型、必要参数和即时现金；资格、产能、时点及会计规则尚未完整验证"
            ] + effect.warnings,
            suggested_next_tools=["simulate_plan"],
            input_snapshot_id=snapshot.snapshot_id,
            rule_version=snapshot.rule_version,
        )

    def _cash_effect(self, action_type: str, parameters: dict[str, Any]) -> ToolResult:
        explicit_amount_actions = {
            "advertising": -1,
            "emergency_material_purchase": -1,
            "emergency_product_purchase": -1,
            "inventory_product_sale": 1,
        }
        if action_type in explicit_amount_actions:
            amount = parameters.get("amount_wan")
            if not isinstance(amount, (int, float)) or amount <= 0:
                return ToolResult(
                    status="needs_input",
                    violations=[f"{action_type} 需要正数 parameters.amount_wan"],
                    required_preconditions=["提供 amount_wan"],
                )
            return ToolResult(
                status="success",
                result={"cash_effect_wan": explicit_amount_actions[action_type] * float(amount)},
            )
        if action_type in {"short_loan_borrow", "long_loan_borrow"}:
            principal = parameters.get("principal_wan")
            term = parameters.get("term")
            if not isinstance(principal, (int, float)) or principal <= 0 or not isinstance(term, (int, float)):
                return ToolResult(
                    status="needs_input",
                    violations=[f"{action_type} 需要 principal_wan 和 term"],
                    required_preconditions=["提供正数 principal_wan", "提供 term"],
                )
            return ToolResult(
                status="success",
                result={"cash_effect_wan": float(principal)},
                warnings=["贷款额度、资格和精确期限规则尚未确认"],
            )
        if action_type == "receivable_discount":
            face = parameters.get("face_amount_wan")
            term = parameters.get("receivable_term_quarters")
            if not isinstance(face, (int, float)) or face <= 0 or term not in {1, 2, 3, 4}:
                return ToolResult(
                    status="needs_input",
                    violations=["贴现需要正数 face_amount_wan 和 1–4 的 receivable_term_quarters"],
                    required_preconditions=["提供贴现面值和账期"],
                )
            rate = 0.08 if term in {1, 2} else 0.11
            return ToolResult(
                status="success",
                result={"cash_effect_wan": float(face) * (1 - rate)},
                warnings=["已使用题面分档利率，但应收扣减和计费语义仍待确认"],
            )
        if action_type in {"material_order", "production_line_order", "production_line_conversion", "order_delivery"}:
            return ToolResult(
                status="needs_input",
                violations=[f"{action_type} 的完整状态转移规则尚未确认"],
                required_preconditions=["提供实验用 cash_effect_wan，或补齐对应规则后实现专用模拟器"],
            )
        explicit_effect = parameters.get("cash_effect_wan")
        if isinstance(explicit_effect, (int, float)):
            return ToolResult(
                status="success",
                result={"cash_effect_wan": float(explicit_effect)},
                warnings=["现金影响由实验输入显式提供，不是规则引擎推导值"],
            )
        return ToolResult(
            status="needs_input",
            violations=[f"尚不能从现有规则推导 {action_type} 的现金影响"],
            required_preconditions=["提供 parameters.cash_effect_wan 或补齐动作规则"],
        )

    def simulate_plan(self, snapshot: StateSnapshot, actions: list[dict[str, Any]]) -> ToolResult:
        if not actions:
            return ToolResult(
                status="needs_input",
                violations=["计划至少需要一个动作"],
                required_preconditions=["提供 actions[]"],
                suggested_next_tools=["available_actions"],
                input_snapshot_id=snapshot.snapshot_id,
                rule_version=snapshot.rule_version,
            )
        cash = snapshot.cash_wan
        steps: list[dict[str, Any]] = []
        warnings: list[str] = []
        for index, action in enumerate(actions, start=1):
            step_snapshot = StateSnapshot(
                **{**snapshot.to_dict(), "cash_wan": cash, "warnings": tuple(snapshot.warnings)}
            )
            validation = self.validate_action(step_snapshot, action)
            if validation.status != "success":
                return ToolResult(
                    status="rejected" if validation.status == "rejected" else "needs_input",
                    result={"completed_steps": steps, "failed_step": index, "failed_action": action},
                    violations=validation.violations,
                    warnings=warnings + validation.warnings,
                    required_preconditions=validation.required_preconditions,
                    suggested_next_tools=validation.suggested_next_tools,
                    input_snapshot_id=snapshot.snapshot_id,
                    rule_version=snapshot.rule_version,
                )
            cash = float(validation.result["projected_cash_wan"])
            steps.append({"step": index, **validation.result})
            warnings.extend(validation.warnings)
        return ToolResult(
            status="success",
            result={
                "mode": "experimental_cash_only",
                "initial_cash_wan": snapshot.cash_wan,
                "projected_cash_wan": cash,
                "minimum_cash_wan": min([snapshot.cash_wan] + [step["projected_cash_wan"] for step in steps]),
                "steps": steps,
                "formal_commit_allowed": False,
            },
            warnings=sorted(set(warnings + ["实验沙盒结果不得提交为正式经营状态"])),
            suggested_next_tools=["compare_plans", "human_review"],
            input_snapshot_id=snapshot.snapshot_id,
            rule_version=snapshot.rule_version,
        )


class DeterministicAdvisoryAgent:
    def __init__(self, tools: AgentTools) -> None:
        self.tools = tools

    def evaluate(self, snapshot: StateSnapshot, candidate_plans: list[dict[str, Any]]) -> ToolResult:
        if not candidate_plans:
            return ToolResult(
                status="needs_input",
                violations=["没有候选方案"],
                required_preconditions=["至少提供一套 candidate_plans"],
                input_snapshot_id=snapshot.snapshot_id,
                rule_version=snapshot.rule_version,
            )
        evaluations = []
        for index, plan in enumerate(candidate_plans, start=1):
            result = self.tools.simulate_plan(snapshot, plan.get("actions") or [])
            evaluations.append(
                {
                    "candidate_id": plan.get("candidate_id") or f"candidate_{index}",
                    "status": result.status,
                    "simulation": result.result,
                    "violations": result.violations,
                    "warnings": result.warnings,
                    "trace_id": result.trace_id,
                }
            )
        feasible = [item for item in evaluations if item["status"] == "success"]
        recommended = None
        if feasible:
            recommended = max(
                feasible,
                key=lambda item: (
                    item["simulation"]["minimum_cash_wan"],
                    item["simulation"]["projected_cash_wan"],
                ),
            )["candidate_id"]
        return ToolResult(
            status="success" if recommended else "rejected",
            result={
                "agent_mode": "deterministic_advisory",
                "selection_policy": "maximize_minimum_cash_then_ending_cash",
                "recommended_candidate_id": recommended,
                "evaluations": evaluations,
                "formal_commit_allowed": False,
            },
            violations=[] if recommended else ["没有通过实验性现金校验的候选方案"],
            warnings=["当前排序只考虑现金安全，不代表完整经营最优方案"],
            suggested_next_tools=["human_review"],
            input_snapshot_id=snapshot.snapshot_id,
            rule_version=snapshot.rule_version,
        )


def snapshot_from_result(result: ToolResult) -> StateSnapshot:
    if result.status != "success" or not isinstance(result.result, dict):
        raise ValueError("tool result does not contain a successful snapshot")
    payload = dict(result.result)
    payload["warnings"] = tuple(payload.get("warnings") or [])
    return StateSnapshot(**payload)
