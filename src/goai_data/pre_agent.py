from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .agent import ToolResult
from .state_engine import ExperimentalState, ExperimentalStateEngine, STATE_ENGINE_VERSION


METRICS_VERSION = "pre_agent_metrics_v0.1"
KERNEL_VERSION = "pre_agent_kernel_v0.1"


@dataclass(frozen=True)
class PreAgentReadiness:
    experimental_ready: bool
    formal_ready: bool
    stages: list[dict[str, Any]]
    external_blockers: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "experimental_ready": self.experimental_ready,
            "formal_ready": self.formal_ready,
            "stages": self.stages,
            "external_blockers": self.external_blockers,
        }


class PreAgentKernel:
    def __init__(self, database: Path) -> None:
        self.database = database.resolve()
        self.engine = ExperimentalStateEngine(self.database)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database)
        connection.row_factory = sqlite3.Row
        return connection

    def readiness(self) -> PreAgentReadiness:
        with self._connect() as connection:
            blocker_count = connection.execute(
                "SELECT COUNT(*) FROM rule_gaps WHERE severity='blocker' AND status='unresolved'"
            ).fetchone()[0]
            source_files = connection.execute("SELECT COUNT(*) FROM source_manifest").fetchone()[0]
            action_events = connection.execute("SELECT COUNT(*) FROM action_events").fetchone()[0]
        stages = [
            {"stage": "data_inventory", "status": "complete", "evidence": f"{source_files} source files"},
            {"stage": "normalized_dataset", "status": "complete", "evidence": f"{action_events} action events"},
            {"stage": "rule_parameters", "status": "complete", "evidence": "RulePack v0.1 explicit parameter tables"},
            {"stage": "rule_process_semantics", "status": "blocked", "evidence": f"{blocker_count} unresolved blockers"},
            {"stage": "state_transition", "status": "experimental_complete", "evidence": STATE_ENGINE_VERSION},
            {"stage": "state_invariants", "status": "complete", "evidence": METRICS_VERSION},
            {"stage": "baseline_metrics", "status": "complete", "evidence": METRICS_VERSION},
            {"stage": "candidate_comparison", "status": "complete", "evidence": KERNEL_VERSION},
            {"stage": "historical_cash_replay", "status": "complete", "evidence": "15/15 final cash snapshots match"},
            {"stage": "historical_operational_replay", "status": "blocked", "evidence": "historical rule version and quarterly non-cash snapshots missing"},
            {"stage": "paper_pss_epss_metrics", "status": "blocked", "evidence": "formal definitions and accounting allocation rules missing"},
            {"stage": "cross_competition_prediction", "status": "blocked", "evidence": "only one historical competition"},
        ]
        external_blockers = [
            "确认历史 600W 数据对应的正式规则版本",
            "确认 581 条订单目录的比赛归属",
            "补齐广告/选单、会计结转、违约破产和结算时点规则",
            "确认 PSS/EPSS/H 的正式定义与会计分配口径",
            "提供至少另一场完整比赛用于跨比赛验证",
        ]
        return PreAgentReadiness(
            experimental_ready=True,
            formal_ready=blocker_count == 0,
            stages=stages,
            external_blockers=external_blockers,
        )

    def validate_state(self, state: ExperimentalState) -> ToolResult:
        violations = []
        warnings = []
        if state.cash_wan < 0:
            violations.append("现金为负")
        for name, value in {**state.material_inventory, **state.product_inventory}.items():
            if value < -1e-9:
                violations.append(f"库存为负：{name}={value}")
        busy_lines = [job["line_instance_id"] for job in state.pending_production]
        if len(busy_lines) != len(set(busy_lines)):
            violations.append("同一生产线存在多个并行在制任务")
        if any(order["arrival_period_index"] <= state.period_index for order in state.pending_material_orders):
            violations.append("存在已到期但未结算的原料订单")
        if any(job["completion_period_index"] <= state.period_index for job in state.pending_production):
            violations.append("存在已完工但未入库的生产任务")
        if any(item["status"] == "outstanding" and item["due_period_index"] <= state.period_index for item in state.receivables):
            violations.append("存在已到期但未回收的应收账款")
        if any(item["status"] == "outstanding" and item["due_period_index"] <= state.period_index for item in state.short_loans):
            violations.append("存在已到期但未偿还的短贷")
        known_lines = {line.get("line_instance_id") for line in state.production_lines}
        if any(line_id not in known_lines for line_id in busy_lines):
            violations.append("在制任务引用了不存在的生产线")
        if state.policy_version.startswith("experimental"):
            warnings.append("状态使用实验性结算策略")
        return ToolResult(
            status="success" if not violations else "rejected",
            result={"state_id": state.state_id, "valid": not violations},
            violations=violations,
            warnings=warnings,
            input_snapshot_id=state.state_id,
            rule_version=state.rule_version,
        )

    def metrics(self, state: ExperimentalState) -> ToolResult:
        validation = self.validate_state(state)
        with self._connect() as connection:
            material_prices = dict(
                connection.execute(
                    "SELECT material_name, unit_purchase_price_wan FROM rule_materials WHERE rule_version=?",
                    (state.rule_version,),
                )
            )
            product_costs = dict(
                connection.execute(
                    "SELECT product_name, direct_cost_wan FROM rule_products WHERE rule_version=?",
                    (state.rule_version,),
                )
            )
            management_fee = connection.execute(
                "SELECT management_fee_per_quarter_wan FROM competition_rules WHERE rule_version=?",
                (state.rule_version,),
            ).fetchone()
        material_value = sum(state.material_inventory.get(key, 0.0) * float(value) for key, value in material_prices.items())
        product_value = sum(state.product_inventory.get(key, 0.0) * float(value) for key, value in product_costs.items())
        wip_value = sum(float(job["quantity"]) * float(product_costs.get(job["product_id"], 0.0)) for job in state.pending_production)
        receivables = sum(float(item["amount_wan"]) for item in state.receivables if item["status"] == "outstanding")
        debt = sum(float(item["amount_due_wan"]) for item in state.short_loans if item["status"] == "outstanding")
        next_index = state.period_index + 1
        next_commitments = float(management_fee[0]) if management_fee else 0.0
        next_commitments += sum(float(item["total_cost_wan"]) for item in state.pending_material_orders if item["arrival_period_index"] <= next_index)
        next_commitments += sum(float(item["amount_due_wan"]) for item in state.short_loans if item["status"] == "outstanding" and item["due_period_index"] <= next_index)
        next_collections = sum(float(item["amount_wan"]) for item in state.receivables if item["status"] == "outstanding" and item["due_period_index"] <= next_index)
        tracked_expense = (
            state.cumulative_material_purchase_wan
            + state.cumulative_processing_cost_wan
            + state.cumulative_management_fee_wan
            + state.cumulative_interest_expense_wan
        )
        metrics = {
            "metrics_version": METRICS_VERSION,
            "state_id": state.state_id,
            "cash_wan": state.cash_wan,
            "material_inventory_value_wan": material_value,
            "product_inventory_value_wan": product_value,
            "wip_direct_cost_proxy_wan": wip_value,
            "receivables_outstanding_wan": receivables,
            "short_debt_due_wan": debt,
            "tracked_asset_value_wan": state.cash_wan + material_value + product_value + wip_value + receivables,
            "net_liquid_position_wan": state.cash_wan + receivables - debt,
            "next_quarter_commitments_wan": next_commitments,
            "next_quarter_collections_wan": next_collections,
            "next_quarter_cash_buffer_wan": state.cash_wan + next_collections - next_commitments,
            "cumulative_revenue_wan": state.cumulative_revenue_wan,
            "tracked_cash_contribution_proxy_wan": state.cumulative_revenue_wan - tracked_expense,
            "pending_material_order_count": len(state.pending_material_orders),
            "pending_production_count": len(state.pending_production),
            "outstanding_receivable_count": sum(item["status"] == "outstanding" for item in state.receivables),
            "outstanding_short_loan_count": sum(item["status"] == "outstanding" for item in state.short_loans),
            "risk_flags": [
                flag
                for flag, active in (
                    ("negative_cash", state.cash_wan < 0),
                    ("next_quarter_cash_shortfall", state.cash_wan + next_collections < next_commitments),
                    ("outstanding_debt", debt > 0),
                    ("state_invariant_violation", validation.status != "success"),
                )
                if active
            ],
        }
        return ToolResult(
            status="success" if validation.status == "success" else "rejected",
            result=metrics,
            violations=validation.violations,
            warnings=validation.warnings + ["库存和在制品按题面直接成本估值，仅作为实验代理指标"],
            input_snapshot_id=state.state_id,
            rule_version=state.rule_version,
        )

    def compare_plans(self, initial_state: ExperimentalState, candidates: list[dict[str, Any]]) -> ToolResult:
        evaluations = []
        for index, candidate in enumerate(candidates, start=1):
            candidate_id = candidate.get("candidate_id") or f"candidate_{index}"
            simulation = self.engine.simulate_timeline(initial_state, candidate.get("timeline") or [])
            item: dict[str, Any] = {
                "candidate_id": candidate_id,
                "status": simulation.status,
                "violations": simulation.violations,
                "warnings": simulation.warnings,
                "trace_id": simulation.trace_id,
            }
            if simulation.status == "success":
                final_state = ExperimentalState.from_dict(simulation.result["final_state"])
                metrics = self.metrics(final_state)
                step_cash = [float(step["cash_wan"]) for step in simulation.result["steps"]]
                item.update(
                    {
                        "final_state_id": final_state.state_id,
                        "minimum_cash_wan": min([initial_state.cash_wan] + step_cash),
                        "metrics": metrics.result,
                        "timeline_steps": len(simulation.result["steps"]),
                    }
                )
            evaluations.append(item)
        feasible = [item for item in evaluations if item["status"] == "success"]
        for item in feasible:
            item["pareto_dominated"] = any(
                other is not item
                and other["minimum_cash_wan"] >= item["minimum_cash_wan"]
                and other["metrics"]["net_liquid_position_wan"] >= item["metrics"]["net_liquid_position_wan"]
                and other["metrics"]["cumulative_revenue_wan"] >= item["metrics"]["cumulative_revenue_wan"]
                and (
                    other["minimum_cash_wan"] > item["minimum_cash_wan"]
                    or other["metrics"]["net_liquid_position_wan"] > item["metrics"]["net_liquid_position_wan"]
                    or other["metrics"]["cumulative_revenue_wan"] > item["metrics"]["cumulative_revenue_wan"]
                )
                for other in feasible
            )
        pareto = [item["candidate_id"] for item in feasible if not item["pareto_dominated"]]
        recommended = None
        if feasible:
            recommended = max(
                feasible,
                key=lambda item: (
                    not item["pareto_dominated"],
                    item["minimum_cash_wan"],
                    item["metrics"]["net_liquid_position_wan"],
                    item["metrics"]["cumulative_revenue_wan"],
                ),
            )["candidate_id"]
        return ToolResult(
            status="success" if recommended else "rejected",
            result={
                "kernel_version": KERNEL_VERSION,
                "selection_policy": "pareto_then_cash_safety_then_net_liquid_then_revenue",
                "recommended_candidate_id": recommended,
                "pareto_candidate_ids": pareto,
                "evaluations": evaluations,
                "formal_commit_allowed": False,
            },
            violations=[] if recommended else ["没有可行候选方案"],
            warnings=["多目标比较使用实验状态与代理指标，不代表正式比赛最优解"],
            suggested_next_tools=["human_review"],
            input_snapshot_id=initial_state.state_id,
            rule_version=initial_state.rule_version,
        )
