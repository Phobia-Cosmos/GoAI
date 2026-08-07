from __future__ import annotations

import re
from typing import Any


ACTION_DEFINITIONS: dict[str, dict[str, str]] = {
    "capital_injection": {"category": "finance", "description": "股东注资"},
    "administrative_fee": {"category": "period_close", "description": "支付行政管理费"},
    "material_order": {"category": "procurement", "description": "订购原材料"},
    "material_receipt_payment": {"category": "procurement", "description": "原材料到货并付款"},
    "production": {"category": "production", "description": "投入加工费并开始或完成生产"},
    "production_line_order": {"category": "capacity", "description": "订购生产线"},
    "production_line_investment": {"category": "capacity", "description": "支付在建生产线投资"},
    "production_line_conversion": {"category": "capacity", "description": "生产线转产"},
    "product_development": {"category": "qualification", "description": "产品研发投入"},
    "market_development": {"category": "qualification", "description": "市场开拓投入"},
    "iso_development": {"category": "qualification", "description": "ISO 认证投入"},
    "short_loan_borrow": {"category": "finance", "description": "取得短期贷款"},
    "short_loan_repayment": {"category": "finance", "description": "偿还短贷本息（历史合并事件）"},
    "short_loan_principal_payment": {"category": "finance", "description": "偿还短贷本金"},
    "short_loan_interest_payment": {"category": "finance", "description": "支付短贷利息"},
    "long_loan_borrow": {"category": "finance", "description": "取得长期贷款"},
    "long_loan_repayment": {"category": "finance", "description": "偿还长贷本息"},
    "receivable_maturity": {"category": "receivable", "description": "应收账款到期更新"},
    "receivable_discount": {"category": "receivable", "description": "应收账款贴现"},
    "advertising": {"category": "sales", "description": "广告投放"},
    "maintenance": {"category": "period_close", "description": "生产线维护费"},
    "factory_rent": {"category": "capacity", "description": "租赁厂房"},
    "factory_rent_renewal": {"category": "capacity", "description": "厂房续租"},
    "factory_purchase": {"category": "capacity", "description": "购买厂房"},
    "factory_rent_to_buy": {"category": "capacity", "description": "厂房租转买"},
    "factory_buy_to_rent": {"category": "capacity", "description": "厂房买转租"},
    "order_award": {"category": "sales", "description": "竞单成功取得订单"},
    "order_delivery": {"category": "sales", "description": "按订单交货"},
    "inventory_product_sale": {"category": "sales", "description": "出售库存产品"},
    "emergency_material_purchase": {"category": "procurement", "description": "紧急采购原料"},
    "emergency_product_purchase": {"category": "procurement", "description": "紧急采购产品"},
    "tax_payment": {"category": "period_close", "description": "支付税金"},
    "penalty_payment": {"category": "risk", "description": "支付违约处罚"},
}


ACTION_CONTROL_TYPES = {
    "capital_injection": "exception_intervention",
    "administrative_fee": "automatic_settlement",
    "material_order": "direct_decision",
    "material_receipt_payment": "committed_settlement",
    "production": "direct_decision",
    "production_line_order": "direct_decision",
    "production_line_investment": "committed_settlement",
    "production_line_conversion": "direct_decision",
    "product_development": "direct_decision",
    "market_development": "direct_decision",
    "iso_development": "direct_decision",
    "short_loan_borrow": "conditional_decision",
    "short_loan_repayment": "committed_settlement",
    "short_loan_principal_payment": "committed_settlement",
    "short_loan_interest_payment": "committed_settlement",
    "long_loan_borrow": "conditional_decision",
    "long_loan_repayment": "committed_settlement",
    "receivable_maturity": "automatic_settlement",
    "receivable_discount": "conditional_decision",
    "advertising": "direct_decision",
    "maintenance": "automatic_settlement",
    "factory_rent": "direct_decision",
    "factory_rent_renewal": "conditional_decision",
    "factory_purchase": "direct_decision",
    "factory_rent_to_buy": "conditional_decision",
    "factory_buy_to_rent": "conditional_decision",
    "order_award": "external_outcome",
    "order_delivery": "conditional_decision",
    "inventory_product_sale": "conditional_decision",
    "emergency_material_purchase": "exception_intervention",
    "emergency_product_purchase": "exception_intervention",
    "tax_payment": "automatic_settlement",
    "penalty_payment": "automatic_settlement",
}


DECISION_CONTROL_TYPES = {
    "direct_decision",
    "conditional_decision",
    "exception_intervention",
}


AGENT_CANDIDATE_ACTIONS = {
    action
    for action, control_type in ACTION_CONTROL_TYPES.items()
    if control_type in {"direct_decision", "conditional_decision"}
} | {"emergency_material_purchase", "emergency_product_purchase"}


HISTORICAL_ACTION_ALIASES = {
    "Pay_Capital": "capital_injection",
    "Pay_Overhaul": "administrative_fee",
    "Buy_Material": "material_order",
    "Pay_Material": "material_receipt_payment",
    "Product_Produce": "production",
    "Buy_ProductLine": "production_line_order",
    "Invest_ProductLine": "production_line_investment",
    "Transfer": "production_line_conversion",
    "Develop_Product": "product_development",
    "Develop_Market": "market_development",
    "Develop_ISO": "iso_development",
    "Short_Loan": "short_loan_borrow",
    "Pay_Short_Loan": "short_loan_repayment",
    "Long_Loan": "long_loan_borrow",
    "Pay_Long_Loan": "long_loan_repayment",
    "Update_Receivable": "receivable_maturity",
    "Discount": "receivable_discount",
    "Pay_AD": "advertising",
    "Pay_Maintenance": "maintenance",
    "Rent_Workshop": "factory_rent",
    "Renew_Workshop": "factory_rent_renewal",
    "Buy_Workshop": "factory_purchase",
    "RentTOBuy_Workshop": "factory_rent_to_buy",
    "Auction_Win": "order_award",
    "Sell_Product": "order_delivery",
    "Sell_Inventory_Product": "inventory_product_sale",
    "Emergency_Buy_Material": "emergency_material_purchase",
    "Emergency_Buy_Product": "emergency_product_purchase",
    "Pay_Tax": "tax_payment",
    "Pay_Punish": "penalty_payment",
}


TEST_ACTION_ALIASES = {
    "管理费": "administrative_fee",
    "申请短贷": "short_loan_borrow",
    "短贷还款": "short_loan_principal_payment",
    "短贷利息": "short_loan_interest_payment",
    "应收账款更新": "receivable_maturity",
    "加工费": "production",
    "更新原料": "material_receipt_payment",
    "维护费": "maintenance",
    "厂房续租": "factory_rent_renewal",
    "厂房租转买": "factory_rent_to_buy",
    "产品研发": "product_development",
    "生产线购买": "production_line_order",
    "市场开拓": "market_development",
    "厂房租赁": "factory_rent",
    "ISO认证": "iso_development",
    "紧急采购原料": "emergency_material_purchase",
    "紧急采购产品": "emergency_product_purchase",
    "厂房买转租": "factory_buy_to_rent",
}


RULE_GAPS = [
    ("phase_sequence", "流程", "经营阶段和季度结算顺序", "题面只有参数表，没有定义动作开放阶段及季度结算先后关系。", "blocker"),
    ("loan_limit", "融资", "贷款额度与申请资格", "缺少长短贷额度上限、申请时点、续贷及特别贷款条件。", "blocker"),
    ("loan_settlement", "融资", "贷款计息与到期结算", "缺少本金、利息的精确扣款时点和逾期处理。", "blocker"),
    ("discount_semantics", "融资", "贴现计算语义", "已知 1–2 季为 8%、3–4 季为 11%，但缺少计费基数和入账时点说明。", "blocker"),
    ("advertising_order", "销售", "广告、询单、选单和竞单机制", "缺少广告排名、订单分配、竞单费用及平局处理规则。", "blocker"),
    ("material_receipt", "采购", "原料下单、到货与付款顺序", "提前期参数已知，但付款和库存入账时点未由题面确认。", "blocker"),
    ("production_transition", "生产", "生产与转产状态转移", "缺少开工、完工、停工、转产和在制品入账的完整状态机。", "blocker"),
    ("delivery_receivable", "销售", "交货与应收账款转移", "缺少交货期、账期、收入确认和到账的完整时点规则。", "blocker"),
    ("emergency_purchase", "采购", "紧急采购价格和限制", "历史中存在紧急采购，但题面未给出价格倍率与使用约束。", "major"),
    ("default_penalty", "风险", "违约判定和处罚", "历史中存在违约处罚，但题面未给出触发条件与公式。", "blocker"),
    ("accounting_close", "会计", "折旧、税费和年末结转", "参数表不能确定会计确认顺序、所得税口径和损失处理。", "blocker"),
    ("bankruptcy_injection", "风险", "现金不足、注资和破产", "缺少现金断裂后的特别贷款、注资、破产及排名处理规则。", "blocker"),
    ("final_scoring", "评价", "最终评分和排名", "题面包含部分资产分值，但缺少完整综合评分公式。", "major"),
    ("order_binding", "数据", "订单目录比赛归属", "581 条订单尚未确认属于 710 万元题面还是历史 600 万元比赛。", "blocker"),
]


def canonicalize_action(raw_action: str, source_scope: str) -> str | None:
    if source_scope == "historical":
        return HISTORICAL_ACTION_ALIASES.get(raw_action)
    if raw_action.startswith("按订单交货"):
        return "order_delivery"
    if raw_action.startswith("贴现"):
        return "receivable_discount"
    return TEST_ACTION_ALIASES.get(raw_action)


def parse_action_parameters(raw_action: str, note: str | None, source_scope: str) -> tuple[dict[str, Any], str]:
    text = note or raw_action
    canonical = canonicalize_action(raw_action, source_scope)
    if canonical is None:
        return {}, "unparsed"

    if canonical in {"material_order", "material_receipt_payment"}:
        quantities = {name: int(value) for name, value in re.findall(r"(R\d+)\s*:\s*(\d+)", text)}
        return ({"materials": quantities}, "complete") if quantities else ({}, "partial")

    if canonical == "production_line_order":
        match = re.search(r"订购\[([^]]+)]生产\[(P\d+)]", text)
        if match:
            return {"line_type": match.group(1), "product_id": match.group(2)}, "complete"
        return {}, "partial"

    if canonical == "production":
        assignments = [
            {"line_instance_id": int(line_id), "product_id": product_id}
            for line_id, product_id in re.findall(r"(\d+)\s*:\s*(P\d+)", text)
        ]
        return ({"line_assignments": assignments}, "complete") if assignments else ({}, "partial")

    if canonical in {"short_loan_borrow", "long_loan_borrow"}:
        match = re.search(r"申请\s*:\s*(\d+)\s*(年|季)\s*(\d+)W", text)
        if match:
            return {
                "term": int(match.group(1)),
                "term_unit": "year" if match.group(2) == "年" else "quarter",
                "principal_wan": int(match.group(3)),
            }, "complete"
        return {}, "partial"

    if canonical == "receivable_discount":
        amounts = {f"term_{term}_wan": int(value) for term, value in re.findall(r"([1-4])期贴现\s*:\s*(\d+)W", text)}
        if amounts:
            return amounts, "complete"
        compact_terms = re.search(r"贴现([1-4]+)q", raw_action)
        if compact_terms:
            return {"receivable_terms": [int(term) for term in compact_terms.group(1)]}, "partial"
        return {}, "partial"

    if canonical == "product_development":
        products = sorted(set(re.findall(r"P\d+", text)))
        return ({"products": products}, "complete") if products else ({}, "partial")

    if canonical == "market_development":
        markets = [name for name in ("本地", "区域", "国内", "亚洲", "国际") if name in text]
        return ({"markets": markets}, "complete") if markets else ({}, "partial")

    if canonical == "iso_development":
        certifications = sorted(set(re.findall(r"ISO\d+", text)))
        return ({"certifications": certifications}, "complete") if certifications else ({}, "partial")

    if canonical in {"factory_rent", "factory_purchase"}:
        match = re.search(r"\[([^]]+)]", text)
        return ({"factory_type": match.group(1)}, "complete") if match else ({}, "partial")

    if canonical == "factory_rent_to_buy":
        match = re.search(r"([^()]+)\((\d+)\)租转买", text)
        if match:
            return {"factory_type": match.group(1), "factory_instance_id": int(match.group(2))}, "complete"
        return {}, "partial"

    if canonical == "order_award":
        match = re.search(r"获得订单\s*:\s*([A-Za-z0-9-]+)", text)
        return ({"order_id": match.group(1)}, "complete") if match else ({}, "partial")

    if canonical == "production_line_conversion":
        match = re.search(r"转产成\s*(P\d+)", text)
        return ({"target_product_id": match.group(1)}, "partial") if match else ({}, "partial")

    if canonical in {"emergency_material_purchase", "emergency_product_purchase"}:
        match = re.search(r"：\s*([\d,，\s]+)", text)
        if match:
            values = [int(value) for value in re.findall(r"\d+", match.group(1))]
            prefix = "R" if canonical == "emergency_material_purchase" else "P"
            return {"quantities": {f"{prefix}{index}": value for index, value in enumerate(values, 1)}}, "complete"
        return {}, "partial"

    if canonical == "inventory_product_sale":
        match = re.search(r"直接成本\s*:\s*(\d+)W", text)
        return ({"direct_cost_wan": int(match.group(1))}, "partial") if match else ({}, "partial")

    if canonical == "order_delivery":
        term = re.search(r"\((\d+)q\)", raw_action)
        return ({"receivable_term_quarters": int(term.group(1))}, "partial") if term else ({}, "partial")

    no_parameter_actions = {
        "capital_injection",
        "administrative_fee",
        "receivable_maturity",
        "maintenance",
        "factory_rent_renewal",
        "tax_payment",
        "penalty_payment",
        "short_loan_principal_payment",
        "short_loan_interest_payment",
        "factory_buy_to_rent",
    }
    if canonical in no_parameter_actions:
        return {}, "not_applicable"
    return {}, "partial"


def infer_partial_event_parameters(event: dict[str, Any]) -> dict[str, Any]:
    """Fill only parameters supported by the complete event evidence.

    This function is intentionally conservative: it never invents a loan
    term, order id, line id, or market/product binding.  It is suitable for
    upgrading a ``partial`` event to ``inferred_partial`` while preserving
    missing fields for later replay or human review.
    """

    row = dict(event)
    action = row.get("canonical_action") or row.get("action") or ""
    raw = str(row.get("raw_action") or row.get("action") or "")
    note = row.get("note")
    source_scope = str(row.get("source_scope") or "historical")
    parsed, parse_status = parse_action_parameters(raw, note, source_scope)
    existing = dict(row.get("parameters") or {})
    inferred = dict(parsed)
    provenance: dict[str, str] = {}
    for key, value in inferred.items():
        if key not in existing or existing[key] in (None, "", [], {}):
            provenance[key] = "text_or_structured_evidence"
    merged = {**inferred, **existing}

    amount = row.get("cash_effect_wan", row.get("amount_wan"))
    if action in {"short_loan_borrow", "long_loan_borrow"} and "principal_wan" not in merged:
        if isinstance(amount, (int, float)) and float(amount) > 0:
            merged["principal_wan"] = float(amount)
            provenance["principal_wan"] = "cash_effect_evidence"
    if action in {"order_delivery", "order_award"} and isinstance(amount, (int, float)) and "amount_wan" not in merged:
        merged["amount_wan"] = abs(float(amount))
        provenance["amount_wan"] = "cash_effect_evidence"
    if action == "order_delivery" and "receivable_term_quarters" not in merged:
        match = re.search(r"(?:账期|交货期|账)\s*[:：]?\s*(\d+)\s*(?:期|q)?", str(note or raw), flags=re.IGNORECASE)
        if match:
            merged["receivable_term_quarters"] = int(match.group(1))
            provenance["receivable_term_quarters"] = "text_evidence"

    complete_fields = {
        "material_order": ("materials",),
        "production": ("line_assignments", "product_id", "quantity"),
        "production_line_order": ("line_type",),
        "order_delivery": ("order_id", "quantity", "amount_wan"),
        "short_loan_borrow": ("principal_wan", ("term", "term_quarters")),
        "long_loan_borrow": ("principal_wan", ("term", "term_quarters")),
    }.get(action, ())
    missing = []
    for field in complete_fields:
        if isinstance(field, tuple):
            if not any(option in merged and merged[option] not in (None, "", [], {}) for option in field):
                missing.append("/".join(field))
        elif field not in merged or merged[field] in (None, "", [], {}):
            missing.append(field)
    if parse_status == "not_applicable":
        status = "not_applicable"
    elif missing:
        status = "inferred_partial" if merged else "partial"
    else:
        status = "inferred_complete" if provenance else "complete"
    return {
        **row,
        "parameters": merged,
        "parameter_parse_status": status,
        "inferred_fields": provenance,
        "missing_parameter_fields": missing,
        "inference_provenance": "derived_from_event_evidence" if provenance else row.get("inference_provenance", "observed_or_unparsed"),
    }


def infer_partial_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [infer_partial_event_parameters(event) for event in events]
