from __future__ import annotations

import copy
import hashlib
import json
import sqlite3
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .agent import ToolResult


STATE_ENGINE_VERSION = "experimental_state_v0.3"


@dataclass(frozen=True)
class SimulationPolicy:
    policy_version: str = STATE_ENGINE_VERSION
    material_payment_timing: str = "on_arrival"
    short_loan_interest_method: str = "simple_annual_prorated_at_maturity"
    management_fee_timing: str = "quarter_end_on_advance"
    settlement_order: tuple[str, ...] = ("management_fee", "material_arrival", "short_loan_maturity")
    enforce_nonnegative_cash: bool = True
    formal_commit_allowed: bool = False


@dataclass
class ExperimentalState:
    competition_id: str
    rule_version: str
    year: int
    quarter: int
    cash_wan: float
    material_inventory: dict[str, float] = field(default_factory=dict)
    product_inventory: dict[str, float] = field(default_factory=dict)
    pending_material_orders: list[dict[str, Any]] = field(default_factory=list)
    pending_production: list[dict[str, Any]] = field(default_factory=list)
    receivables: list[dict[str, Any]] = field(default_factory=list)
    short_loans: list[dict[str, Any]] = field(default_factory=list)
    production_lines: list[dict[str, Any]] = field(default_factory=list)
    product_qualifications: list[str] = field(default_factory=list)
    delivered_orders: list[dict[str, Any]] = field(default_factory=list)
    cumulative_revenue_wan: float = 0.0
    cumulative_material_purchase_wan: float = 0.0
    cumulative_processing_cost_wan: float = 0.0
    cumulative_management_fee_wan: float = 0.0
    cumulative_interest_expense_wan: float = 0.0
    event_log: list[dict[str, Any]] = field(default_factory=list)
    policy_version: str = STATE_ENGINE_VERSION
    formal_commit_allowed: bool = False

    @property
    def period_index(self) -> int:
        return (self.year - 1) * 4 + (self.quarter - 1)

    @property
    def state_id(self) -> str:
        payload = asdict(self)
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return "state_" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]

    def to_dict(self) -> dict[str, Any]:
        return {"state_id": self.state_id, **asdict(self)}

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ExperimentalState":
        values = dict(payload)
        values.pop("state_id", None)
        return cls(**values)


def period_from_index(index: int) -> tuple[int, int]:
    return index // 4 + 1, index % 4 + 1


class ExperimentalStateEngine:
    def __init__(self, database: Path, policy: SimulationPolicy | None = None) -> None:
        self.database = database.resolve()
        self.policy = policy or SimulationPolicy()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database)
        connection.row_factory = sqlite3.Row
        return connection

    @property
    def warnings(self) -> list[str]:
        return [
            "实验策略：原料按题面提前期到货，并假定到货时付款",
            "实验策略：短贷采用年利率按季度简单折算，到期一次还本息",
            "实验策略：季度推进时扣除当季管理费",
            "结算时点和顺序尚未由完整题面确认，结果不得正式提交",
        ]

    def initial_state(self, year: int = 1, quarter: int = 1) -> ToolResult:
        with self._connect() as connection:
            rule = connection.execute(
                "SELECT * FROM competition_rules WHERE rule_version='zhejiang_8th_rules_v1'"
            ).fetchone()
        if rule is None:
            return ToolResult(
                status="needs_input",
                violations=["缺少 zhejiang_8th_rules_v1 比赛初始参数"],
                required_preconditions=["加载 competition_rules"],
                rule_version="zhejiang_8th_rules_v1",
            )
        state = ExperimentalState(
            competition_id=rule["competition_id"],
            rule_version=rule["rule_version"],
            year=year,
            quarter=quarter,
            cash_wan=float(rule["initial_capital_wan"]),
            material_inventory={f"R{index}": 0.0 for index in range(1, 5)},
            product_inventory={f"P{index}": 0.0 for index in range(1, 6)},
            policy_version=self.policy.policy_version,
            formal_commit_allowed=False,
        )
        return ToolResult(
            status="success",
            result=state.to_dict(),
            warnings=self.warnings,
            suggested_next_tools=["state_apply_action", "state_advance_quarter"],
            input_snapshot_id=state.state_id,
            rule_version=state.rule_version,
        )

    def apply_action(self, state: ExperimentalState, action: dict[str, Any]) -> ToolResult:
        action_type = action.get("action_type")
        parameters = action.get("parameters") or {}
        if action_type == "material_order":
            return self._order_materials(state, parameters)
        if action_type == "short_loan_borrow":
            return self._borrow_short(state, parameters)
        if action_type == "production":
            return self._start_production(state, parameters)
        if action_type == "order_delivery":
            return self._deliver_order(state, parameters)
        return ToolResult(
            status="needs_input",
            violations=[f"State Engine v0.2 尚未实现动作：{action_type}"],
            required_preconditions=["使用 material_order、short_loan_borrow、production 或 order_delivery，或实现对应状态转移"],
            suggested_next_tools=["available_actions"],
            input_snapshot_id=state.state_id,
            rule_version=state.rule_version,
        )

    def _order_materials(self, state: ExperimentalState, parameters: dict[str, Any]) -> ToolResult:
        materials = parameters.get("materials")
        if not isinstance(materials, dict) or not materials:
            return ToolResult(
                status="needs_input",
                violations=["material_order 需要非空 parameters.materials"],
                required_preconditions=["提供如 {\"R1\": 2, \"R3\": 1} 的订购量"],
                input_snapshot_id=state.state_id,
                rule_version=state.rule_version,
            )
        with self._connect() as connection:
            rules = {
                row["material_name"]: dict(row)
                for row in connection.execute(
                    "SELECT material_name, unit_purchase_price_wan, lead_time_quarters FROM rule_materials WHERE rule_version=?",
                    (state.rule_version,),
                )
            }
        unknown = sorted(set(materials) - set(rules))
        invalid = sorted(name for name, quantity in materials.items() if not isinstance(quantity, (int, float)) or quantity <= 0)
        if unknown or invalid:
            violations = []
            if unknown:
                violations.append(f"未知原料：{', '.join(unknown)}")
            if invalid:
                violations.append(f"订购量必须为正数：{', '.join(invalid)}")
            return ToolResult(
                status="rejected",
                violations=violations,
                input_snapshot_id=state.state_id,
                rule_version=state.rule_version,
            )
        next_state = copy.deepcopy(state)
        created_orders = []
        for material_id, quantity in sorted(materials.items()):
            rule = rules[material_id]
            lead_time = int(rule["lead_time_quarters"])
            arrival_index = state.period_index + lead_time
            arrival_year, arrival_quarter = period_from_index(arrival_index)
            order = {
                "order_id": f"mo_{len(next_state.pending_material_orders) + 1}_{state.state_id[-6:]}",
                "material_id": material_id,
                "quantity": float(quantity),
                "unit_price_wan": float(rule["unit_purchase_price_wan"]),
                "total_cost_wan": float(quantity) * float(rule["unit_purchase_price_wan"]),
                "ordered_year": state.year,
                "ordered_quarter": state.quarter,
                "arrival_year": arrival_year,
                "arrival_quarter": arrival_quarter,
                "arrival_period_index": arrival_index,
                "payment_status": "due_on_arrival_experimental",
            }
            next_state.pending_material_orders.append(order)
            created_orders.append(order)
        next_state.event_log.append(
            {
                "event_type": "material_ordered",
                "year": state.year,
                "quarter": state.quarter,
                "orders": created_orders,
                "cash_effect_wan": 0.0,
            }
        )
        return ToolResult(
            status="success",
            result={"state": next_state.to_dict(), "created_orders": created_orders},
            warnings=self.warnings,
            suggested_next_tools=["state_advance_quarter"],
            input_snapshot_id=state.state_id,
            rule_version=state.rule_version,
        )

    def _borrow_short(self, state: ExperimentalState, parameters: dict[str, Any]) -> ToolResult:
        principal = parameters.get("principal_wan")
        term = parameters.get("term_quarters", parameters.get("term"))
        if not isinstance(principal, (int, float)) or principal <= 0:
            return ToolResult(
                status="needs_input",
                violations=["short_loan_borrow 需要正数 principal_wan"],
                required_preconditions=["提供 principal_wan"],
                input_snapshot_id=state.state_id,
                rule_version=state.rule_version,
            )
        if not isinstance(term, int) or term <= 0:
            return ToolResult(
                status="needs_input",
                violations=["short_loan_borrow 需要正整数 term_quarters"],
                required_preconditions=["提供 term_quarters"],
                input_snapshot_id=state.state_id,
                rule_version=state.rule_version,
            )
        with self._connect() as connection:
            row = connection.execute(
                "SELECT rate FROM rule_financing_terms WHERE rule_version=? AND term_id='short_loan'",
                (state.rule_version,),
            ).fetchone()
        if row is None:
            return ToolResult(
                status="needs_input",
                violations=["缺少短贷利率规则"],
                required_preconditions=["加载 rule_financing_terms.short_loan"],
                input_snapshot_id=state.state_id,
                rule_version=state.rule_version,
            )
        annual_rate = float(row["rate"])
        interest = float(principal) * annual_rate * term / 4
        due_index = state.period_index + term
        due_year, due_quarter = period_from_index(due_index)
        next_state = copy.deepcopy(state)
        loan = {
            "loan_id": f"sl_{len(next_state.short_loans) + 1}_{state.state_id[-6:]}",
            "principal_wan": float(principal),
            "annual_rate": annual_rate,
            "term_quarters": term,
            "interest_wan": interest,
            "amount_due_wan": float(principal) + interest,
            "borrowed_year": state.year,
            "borrowed_quarter": state.quarter,
            "due_year": due_year,
            "due_quarter": due_quarter,
            "due_period_index": due_index,
            "status": "outstanding",
            "interest_policy": self.policy.short_loan_interest_method,
        }
        next_state.short_loans.append(loan)
        next_state.cash_wan += float(principal)
        next_state.event_log.append(
            {
                "event_type": "short_loan_borrowed",
                "year": state.year,
                "quarter": state.quarter,
                "loan_id": loan["loan_id"],
                "cash_effect_wan": float(principal),
            }
        )
        return ToolResult(
            status="success",
            result={"state": next_state.to_dict(), "loan": loan},
            warnings=self.warnings + ["贷款额度与资格尚未校验"],
            suggested_next_tools=["state_advance_quarter"],
            input_snapshot_id=state.state_id,
            rule_version=state.rule_version,
        )

    def _start_production(self, state: ExperimentalState, parameters: dict[str, Any]) -> ToolResult:
        product_id = parameters.get("product_id")
        line_instance_id = parameters.get("line_instance_id")
        quantity = parameters.get("quantity", 1)
        if not isinstance(quantity, (int, float)) or quantity <= 0:
            return ToolResult(
                status="needs_input",
                violations=["production 需要正数 quantity"],
                required_preconditions=["提供 quantity"],
                input_snapshot_id=state.state_id,
                rule_version=state.rule_version,
            )
        if product_id not in state.product_qualifications:
            return ToolResult(
                status="rejected",
                violations=[f"产品 {product_id} 尚未取得研发资格"],
                required_preconditions=["在状态中提供已完成的 product_qualifications"],
                input_snapshot_id=state.state_id,
                rule_version=state.rule_version,
            )
        line = next(
            (item for item in state.production_lines if item.get("line_instance_id") == line_instance_id),
            None,
        )
        if line is None:
            return ToolResult(
                status="rejected",
                violations=[f"不存在生产线实例：{line_instance_id}"],
                required_preconditions=["提供 production_lines 中的 line_instance_id"],
                input_snapshot_id=state.state_id,
                rule_version=state.rule_version,
            )
        if any(job["line_instance_id"] == line_instance_id for job in state.pending_production):
            return ToolResult(
                status="rejected",
                violations=[f"生产线 {line_instance_id} 已被在制任务占用"],
                input_snapshot_id=state.state_id,
                rule_version=state.rule_version,
            )
        with self._connect() as connection:
            product = connection.execute(
                "SELECT * FROM rule_products WHERE rule_version=? AND product_name=?",
                (state.rule_version, product_id),
            ).fetchone()
            line_rule = connection.execute(
                "SELECT * FROM rule_production_lines WHERE rule_version=? AND line_type_name=?",
                (state.rule_version, line.get("line_type")),
            ).fetchone()
            bom_rows = list(
                connection.execute(
                    "SELECT material_name, component_product_name, quantity FROM rule_bom WHERE rule_version=? AND product_name=?",
                    (state.rule_version, product_id),
                )
            )
        if product is None or line_rule is None or not bom_rows:
            return ToolResult(
                status="needs_input",
                violations=["缺少产品、产线或 BOM 规则"],
                required_preconditions=["确认 product_id、line_type 与 rule_version"],
                input_snapshot_id=state.state_id,
                rule_version=state.rule_version,
            )
        required_materials: dict[str, float] = {}
        required_components: dict[str, float] = {}
        for row in bom_rows:
            needed = float(row["quantity"]) * float(quantity)
            if row["material_name"]:
                required_materials[row["material_name"]] = needed
            if row["component_product_name"]:
                required_components[row["component_product_name"]] = needed
        shortages = []
        for material_id, needed in required_materials.items():
            available = state.material_inventory.get(material_id, 0.0)
            if available < needed:
                shortages.append(f"{material_id} 需要 {needed}，现有 {available}")
        for component_id, needed in required_components.items():
            available = state.product_inventory.get(component_id, 0.0)
            if available < needed:
                shortages.append(f"{component_id} 半成品需要 {needed}，现有 {available}")
        processing_cost = float(product["processing_fee_wan"]) * float(quantity)
        if state.cash_wan < processing_cost:
            shortages.append(f"加工费需要 {processing_cost} 万元，现金 {state.cash_wan} 万元")
        if shortages:
            return ToolResult(
                status="rejected",
                violations=shortages,
                input_snapshot_id=state.state_id,
                rule_version=state.rule_version,
            )
        next_state = copy.deepcopy(state)
        for material_id, needed in required_materials.items():
            next_state.material_inventory[material_id] -= needed
        for component_id, needed in required_components.items():
            next_state.product_inventory[component_id] -= needed
        next_state.cash_wan -= processing_cost
        next_state.cumulative_processing_cost_wan += processing_cost
        cycle = int(line_rule["production_cycle_quarters"])
        completion_index = state.period_index + cycle
        completion_year, completion_quarter = period_from_index(completion_index)
        job = {
            "job_id": f"pj_{len(next_state.pending_production) + 1}_{state.state_id[-6:]}",
            "line_instance_id": line_instance_id,
            "line_type": line["line_type"],
            "product_id": product_id,
            "quantity": float(quantity),
            "start_year": state.year,
            "start_quarter": state.quarter,
            "completion_year": completion_year,
            "completion_quarter": completion_quarter,
            "completion_period_index": completion_index,
            "processing_cost_wan": processing_cost,
            "status": "in_progress",
        }
        next_state.pending_production.append(job)
        next_state.event_log.append(
            {
                "event_type": "production_started",
                "year": state.year,
                "quarter": state.quarter,
                "job_id": job["job_id"],
                "cash_effect_wan": -processing_cost,
                "materials_consumed": required_materials,
                "components_consumed": required_components,
            }
        )
        return ToolResult(
            status="success",
            result={"state": next_state.to_dict(), "production_job": job},
            warnings=self.warnings + ["尚未校验产线产品兼容性、维护费和转产规则"],
            suggested_next_tools=["state_advance_quarter"],
            input_snapshot_id=state.state_id,
            rule_version=state.rule_version,
        )

    def _deliver_order(self, state: ExperimentalState, parameters: dict[str, Any]) -> ToolResult:
        product_id = parameters.get("product_id")
        quantity = parameters.get("quantity")
        amount = parameters.get("total_amount_wan")
        term = parameters.get("receivable_term_quarters", 0)
        order_id = parameters.get("order_id") or f"experimental_order_{len(state.delivered_orders) + 1}"
        if not isinstance(quantity, (int, float)) or quantity <= 0:
            return ToolResult(status="needs_input", violations=["order_delivery 需要正数 quantity"], input_snapshot_id=state.state_id, rule_version=state.rule_version)
        if not isinstance(amount, (int, float)) or amount <= 0:
            return ToolResult(status="needs_input", violations=["order_delivery 需要正数 total_amount_wan"], input_snapshot_id=state.state_id, rule_version=state.rule_version)
        if not isinstance(term, int) or term < 0:
            return ToolResult(status="needs_input", violations=["receivable_term_quarters 必须是非负整数"], input_snapshot_id=state.state_id, rule_version=state.rule_version)
        available = state.product_inventory.get(product_id, 0.0)
        if available < quantity:
            return ToolResult(
                status="rejected",
                violations=[f"产品库存不足：{product_id} 需要 {quantity}，现有 {available}"],
                input_snapshot_id=state.state_id,
                rule_version=state.rule_version,
            )
        next_state = copy.deepcopy(state)
        next_state.product_inventory[product_id] -= float(quantity)
        next_state.cumulative_revenue_wan += float(amount)
        delivery = {
            "order_id": order_id,
            "product_id": product_id,
            "quantity": float(quantity),
            "total_amount_wan": float(amount),
            "delivery_year": state.year,
            "delivery_quarter": state.quarter,
            "receivable_term_quarters": term,
        }
        if term == 0:
            next_state.cash_wan += float(amount)
            delivery["settlement_status"] = "cash_received"
        else:
            due_index = state.period_index + term
            due_year, due_quarter = period_from_index(due_index)
            receivable = {
                "receivable_id": f"ar_{len(next_state.receivables) + 1}_{state.state_id[-6:]}",
                "order_id": order_id,
                "amount_wan": float(amount),
                "due_year": due_year,
                "due_quarter": due_quarter,
                "due_period_index": due_index,
                "status": "outstanding",
            }
            next_state.receivables.append(receivable)
            delivery["settlement_status"] = "receivable_created"
            delivery["receivable_id"] = receivable["receivable_id"]
        next_state.delivered_orders.append(delivery)
        next_state.event_log.append(
            {
                "event_type": "order_delivered",
                "year": state.year,
                "quarter": state.quarter,
                "order_id": order_id,
                "cash_effect_wan": float(amount) if term == 0 else 0.0,
                "revenue_wan": float(amount),
            }
        )
        return ToolResult(
            status="success",
            result={"state": next_state.to_dict(), "delivery": delivery},
            warnings=self.warnings + ["订单归属、交期资格和收入确认口径尚未正式绑定"],
            suggested_next_tools=["state_advance_quarter"],
            input_snapshot_id=state.state_id,
            rule_version=state.rule_version,
        )

    def advance_quarter(self, state: ExperimentalState) -> ToolResult:
        target_index = state.period_index + 1
        target_year, target_quarter = period_from_index(target_index)
        with self._connect() as connection:
            row = connection.execute(
                "SELECT management_fee_per_quarter_wan FROM competition_rules WHERE rule_version=?",
                (state.rule_version,),
            ).fetchone()
        if row is None:
            return ToolResult(
                status="needs_input",
                violations=["缺少季度管理费规则"],
                required_preconditions=["加载 competition_rules"],
                input_snapshot_id=state.state_id,
                rule_version=state.rule_version,
            )
        management_fee = float(row["management_fee_per_quarter_wan"])
        arriving = [order for order in state.pending_material_orders if order["arrival_period_index"] <= target_index]
        completing = [job for job in state.pending_production if job["completion_period_index"] <= target_index]
        collecting = [
            receivable
            for receivable in state.receivables
            if receivable["status"] == "outstanding" and receivable["due_period_index"] <= target_index
        ]
        maturing = [loan for loan in state.short_loans if loan["status"] == "outstanding" and loan["due_period_index"] <= target_index]
        material_payment = sum(float(order["total_cost_wan"]) for order in arriving)
        receivable_collection = sum(float(item["amount_wan"]) for item in collecting)
        loan_payment = sum(float(loan["amount_due_wan"]) for loan in maturing)
        total_deduction = management_fee + material_payment + loan_payment
        projected_cash = state.cash_wan + receivable_collection - total_deduction
        due_summary = {
            "receivable_collection_wan": receivable_collection,
            "management_fee_wan": management_fee,
            "material_payment_wan": material_payment,
            "short_loan_payment_wan": loan_payment,
            "total_deduction_wan": total_deduction,
        }
        if self.policy.enforce_nonnegative_cash and projected_cash < 0:
            return ToolResult(
                status="rejected",
                result={
                    "unchanged_state": state.to_dict(),
                    "target_year": target_year,
                    "target_quarter": target_quarter,
                    "due_summary": due_summary,
                    "projected_cash_wan": projected_cash,
                },
                violations=[f"季度结算现金不足：需要 {total_deduction} 万元，当前 {state.cash_wan} 万元"],
                warnings=self.warnings,
                suggested_next_tools=["state_apply_action", "human_review"],
                input_snapshot_id=state.state_id,
                rule_version=state.rule_version,
            )
        next_state = copy.deepcopy(state)
        next_state.year = target_year
        next_state.quarter = target_quarter
        next_state.cash_wan = projected_cash
        next_state.cumulative_material_purchase_wan += material_payment
        next_state.cumulative_management_fee_wan += management_fee
        next_state.cumulative_interest_expense_wan += sum(float(loan["interest_wan"]) for loan in maturing)
        next_state.pending_material_orders = [
            order for order in next_state.pending_material_orders if order["arrival_period_index"] > target_index
        ]
        for order in arriving:
            material_id = order["material_id"]
            next_state.material_inventory[material_id] = (
                next_state.material_inventory.get(material_id, 0.0) + float(order["quantity"])
            )
        next_state.pending_production = [
            job for job in next_state.pending_production if job["completion_period_index"] > target_index
        ]
        for job in completing:
            product_id = job["product_id"]
            next_state.product_inventory[product_id] = (
                next_state.product_inventory.get(product_id, 0.0) + float(job["quantity"])
            )
        collected_ids = {item["receivable_id"] for item in collecting}
        for receivable in next_state.receivables:
            if receivable["receivable_id"] in collected_ids:
                receivable["status"] = "collected_experimental"
                receivable["collected_year"] = target_year
                receivable["collected_quarter"] = target_quarter
        matured_ids = {loan["loan_id"] for loan in maturing}
        for loan in next_state.short_loans:
            if loan["loan_id"] in matured_ids:
                loan["status"] = "repaid_experimental"
                loan["repaid_year"] = target_year
                loan["repaid_quarter"] = target_quarter
        next_state.event_log.append(
            {
                "event_type": "quarter_advanced",
                "from_year": state.year,
                "from_quarter": state.quarter,
                "to_year": target_year,
                "to_quarter": target_quarter,
                "arrived_material_order_ids": [order["order_id"] for order in arriving],
                "completed_production_job_ids": [job["job_id"] for job in completing],
                "collected_receivable_ids": sorted(collected_ids),
                "repaid_short_loan_ids": sorted(matured_ids),
                "cash_effect_wan": receivable_collection - total_deduction,
                "due_summary": due_summary,
            }
        )
        return ToolResult(
            status="success",
            result={"state": next_state.to_dict(), "settlement": due_summary},
            warnings=self.warnings,
            suggested_next_tools=["state_apply_action", "state_advance_quarter"],
            input_snapshot_id=state.state_id,
            rule_version=state.rule_version,
        )

    def simulate_timeline(self, state: ExperimentalState, timeline: list[dict[str, Any]]) -> ToolResult:
        current = copy.deepcopy(state)
        steps = []
        for index, item in enumerate(timeline, start=1):
            item_type = item.get("type")
            if item_type == "action":
                result = self.apply_action(current, item)
            elif item_type == "advance_quarter":
                result = self.advance_quarter(current)
            else:
                return ToolResult(
                    status="needs_input",
                    result={"completed_steps": steps, "failed_step": index},
                    violations=[f"未知 timeline type：{item_type}"],
                    required_preconditions=["使用 action 或 advance_quarter"],
                    input_snapshot_id=state.state_id,
                    rule_version=state.rule_version,
                )
            if result.status != "success":
                return ToolResult(
                    status=result.status,
                    result={
                        "completed_steps": steps,
                        "failed_step": index,
                        "failed_item": item,
                        "failure": result.to_dict(),
                        "last_state": current.to_dict(),
                    },
                    violations=result.violations,
                    warnings=result.warnings,
                    required_preconditions=result.required_preconditions,
                    suggested_next_tools=result.suggested_next_tools,
                    input_snapshot_id=state.state_id,
                    rule_version=state.rule_version,
                )
            current = ExperimentalState.from_dict(result.result["state"])
            steps.append(
                {
                    "step": index,
                    "item": item,
                    "result_state_id": current.state_id,
                    "year": current.year,
                    "quarter": current.quarter,
                    "cash_wan": current.cash_wan,
                }
            )
        return ToolResult(
            status="success",
            result={
                "mode": STATE_ENGINE_VERSION,
                "policy": asdict(self.policy),
                "initial_state_id": state.state_id,
                "final_state": current.to_dict(),
                "steps": steps,
                "formal_commit_allowed": False,
            },
            warnings=self.warnings,
            suggested_next_tools=["compare_state_plans", "human_review"],
            input_snapshot_id=state.state_id,
            rule_version=state.rule_version,
        )
