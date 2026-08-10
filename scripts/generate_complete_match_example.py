from __future__ import annotations

import argparse
import hashlib
import json
import math
from copy import deepcopy
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "goai.complete_match.v1"
DATASET_ID = "synthetic_cn_complete_match_v1"
MATCH_ID = "SYN-CN-001"
RULE_PACK_ID = "rule_family_cn_observed_v1"
RULE_VERSION = "0.1-provisional"
TARGET_TEAM_ID = "CN01"
GENERATED_AT = "2026-08-04T12:00:00+08:00"


def provenance(status: str, basis: list[str], note: str) -> dict[str, Any]:
    return {
        "status": status,
        "basis": basis,
        "note": note,
        "training_eligible": status in {"observed", "derived"},
    }


def stable_id(prefix: str, payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}_{digest}"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def period(index: int, phase: str = "quarter_end") -> dict[str, Any]:
    return {"year": index // 4 + 1, "quarter": index % 4 + 1, "phase": phase}


def make_rule_pack() -> dict[str, Any]:
    observed = "AB/CA/CB/CD/CE/EA/EB/EC/EF/OP 企业 XLS 重复字段"
    missing_note = "当前目录没有与中文十簇绑定的正式规则原文"
    return {
        "rule_pack_id": RULE_PACK_ID,
        "rule_version": RULE_VERSION,
        "status": "provisional_observed_rule_family",
        "simulation_ready": False,
        "formal_commit_allowed": False,
        "binding": {
            "match_id": MATCH_ID,
            "status": "synthetic_example_only",
            "evidence": ["样例基于中文十簇共同观察指纹，不代表任何真实比赛绑定"],
        },
        "currency": {"unit": "wan_cny", "display": "万元"},
        "timeline": {
            "years": 5,
            "quarters_per_year": 4,
            "decision_phases": None,
            "provenance": provenance("missing", [], missing_note),
        },
        "initial_state": {
            "cash_wan": 600,
            "share_capital_wan": 600,
            "other_assets": None,
            "provenance": provenance("observed", [observed], "现金流开局注资重复观察为 600W"),
        },
        "management_fee": {
            "amount_wan": 10,
            "frequency": "quarter",
            "settlement_phase": None,
            "provenance": provenance("observed", [observed], "金额可观察，自动扣费时点尚未确认"),
        },
        "workshops": [
            {"type": "large", "purchase_price_wan": 400, "capacity": 4, "annual_rent_wan": None},
            {"type": "medium", "purchase_price_wan": 300, "capacity": 3, "annual_rent_wan": None},
            {"type": "small", "purchase_price_wan": 180, "capacity": 2, "annual_rent_wan": None},
        ],
        "workshops_provenance": provenance("observed", [observed], "购价和容量可观察，租售及结算规则不完整"),
        "markets": [
            {"market_id": "local", "annual_development_fee_wan": 10, "development_years": 1},
            {"market_id": "regional", "annual_development_fee_wan": 10, "development_years": 1},
            {"market_id": "domestic", "annual_development_fee_wan": 10, "development_years": 2},
            {"market_id": "asia", "annual_development_fee_wan": 10, "development_years": 3},
            {"market_id": "international", "annual_development_fee_wan": 10, "development_years": 4},
        ],
        "markets_provenance": provenance("observed", [observed], "费用和周期来自重复观察"),
        "products": [
            {"product_id": "P1", "development_fee_per_quarter_wan": 10, "development_quarters": 2},
            {"product_id": "P2", "development_fee_per_quarter_wan": 10, "development_quarters": 3},
            {"product_id": "P3", "development_fee_per_quarter_wan": 10, "development_quarters": 4},
            {"product_id": "P4", "development_fee_per_quarter_wan": 10, "development_quarters": 5},
        ],
        "products_provenance": provenance("observed", [observed], "费用和周期来自重复观察"),
        "iso": [
            {"iso_id": "ISO9000", "annual_development_fee_wan": 10, "development_years": 2},
            {"iso_id": "ISO14000", "annual_development_fee_wan": 20, "development_years": 2},
        ],
        "iso_provenance": provenance("observed", [observed], "费用和周期来自重复观察"),
        "production_lines": [
            {"line_type": "automatic", "completed_investment_wan": 150, "installation_quarters": None, "annual_depreciation_wan": None},
            {"line_type": "flexible", "completed_investment_wan": 200, "installation_quarters": None, "annual_depreciation_wan": None},
        ],
        "production_lines_provenance": provenance("observed", [observed], "完工累计投资可观察，建设、折旧和转产语义不完整"),
        "materials_and_bom": {
            "materials": None,
            "bom": None,
            "provenance": provenance("missing", [], missing_note),
        },
        "financing": {"terms": None, "limits": None, "provenance": provenance("missing", [], missing_note)},
        "orders": {
            "allocation": None,
            "advertising_effect": None,
            "tie_break": None,
            "provenance": provenance("missing", [], "企业 XLS 只有已获得订单，没有赛前完整公共订单池"),
        },
        "settlement": {"order": None, "provenance": provenance("missing", [], missing_note)},
        "tax_bankruptcy_scoring": {"rules": None, "provenance": provenance("missing", [], missing_note)},
        "synthetic_assumptions": {
            "scope": "仅用于生成接口完整样例",
            "automatic_line_available_immediately": True,
            "automatic_line_annual_depreciation_wan": 20,
            "one_target_order_per_quarter": True,
            "cash_sale_on_delivery": True,
            "material_and_processing_costs_are_direct_cash_expenses": True,
            "no_loans_receivables_tax_or_inventory_balance": True,
            "provenance": provenance("simulated", [], "这些值不是中文十簇正式规则，不得进入训练事实"),
        },
        "blocking_gaps": [
            "formal_rule_manual",
            "initial_non_cash_assets",
            "phase_action_permissions",
            "global_order_pool_binding",
            "advertising_and_order_allocation",
            "materials_and_bom",
            "financing_limits_and_settlement",
            "production_and_delivery_timing",
            "depreciation_and_tax",
            "bankruptcy_and_penalties",
            "final_scoring",
        ],
    }


def add_cash_event(
    events: list[dict[str, Any]],
    cash: float,
    event_type: str,
    current_period: dict[str, Any],
    amount: float,
    payload: dict[str, Any],
) -> float:
    cash_after = round(cash + amount, 2)
    event_number = len(events) + 1
    events.append(
        {
            "event_id": f"EVT-{event_number:04d}",
            "source": "synthetic_generator",
            "period": current_period,
            "event_type": event_type,
            "payload": payload,
            "cash_delta_wan": amount,
            "cash_before_wan": cash,
            "cash_after_wan": cash_after,
            "provenance": provenance("simulated", [], "用于展示标准事件结构和现金连续性"),
        }
    )
    return cash_after


def make_enterprise_timeline() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    cash = 600.0
    line_book_value = 0.0
    events: list[dict[str, Any]] = []
    snapshots: list[dict[str, Any]] = []
    yearly_ledgers: dict[int, dict[str, float]] = {}
    qualifications = {"markets": [], "products": [], "iso": []}
    previous_state_id = stable_id("state", {"period": "initial", "cash": cash})

    initial_state = {
        "state_id": previous_state_id,
        "match_id": MATCH_ID,
        "team_id": TARGET_TEAM_ID,
        "rule_pack_id": RULE_PACK_ID,
        "rule_version": RULE_VERSION,
        "period": {"year": 1, "quarter": 1, "phase": "year_start"},
        "cash_wan": cash,
        "share_capital_wan": 600,
        "retained_earnings_wan": 0,
        "loans": [],
        "receivables": [],
        "workshops": [],
        "production_lines": [],
        "inventory": {"materials": {}, "products": {}, "work_in_process": []},
        "qualifications": deepcopy(qualifications),
        "orders": [],
        "provenance": provenance("simulated", ["600W observed initial-capital fingerprint"], "除初始资本外均为结构样例"),
    }

    for period_index in range(20):
        p = period(period_index, "during_quarter")
        year = p["year"]
        quarter = p["quarter"]
        ledger = yearly_ledgers.setdefault(
            year,
            {"sales": 0.0, "material": 0.0, "processing": 0.0, "management": 0.0, "advertising": 0.0, "market_development": 0.0, "product_development": 0.0, "depreciation": 0.0, "capital_expenditure": 0.0},
        )

        if period_index == 0:
            cash = add_cash_event(
                events,
                cash,
                "BUY_PRODUCT_LINE",
                p,
                -150.0,
                {"line_id": "LINE-01", "line_type": "automatic", "investment_wan": 150, "availability": "immediate_synthetic_assumption"},
            )
            line_book_value = 150.0
            ledger["capital_expenditure"] += 150.0

        if quarter == 1:
            ad_amount = float(8 + year)
            cash = add_cash_event(events, cash, "PAY_AD", p, -ad_amount, {"amount_wan": ad_amount, "market": "local", "product_id": "P1"})
            ledger["advertising"] += ad_amount

        if period_index == 0:
            cash = add_cash_event(events, cash, "DEVELOP_MARKET", p, -10.0, {"market_id": "local", "amount_wan": 10})
            ledger["market_development"] += 10.0
            qualifications["markets"].append("local")

        if period_index < 2:
            cash = add_cash_event(events, cash, "DEVELOP_PRODUCT", p, -10.0, {"product_id": "P1", "amount_wan": 10, "progress_quarters": period_index + 1})
            ledger["product_development"] += 10.0
            if period_index == 1:
                qualifications["products"].append("P1")

        cash = add_cash_event(events, cash, "PAY_MANAGEMENT_FEE", p, -10.0, {"amount_wan": 10})
        ledger["management"] += 10.0

        material_cost = float(18 + (period_index % 3) * 2)
        processing_cost = 5.0
        quantity = 2 + period_index % 2
        revenue = float(88 + period_index * 3 + quantity * 4)
        order_id = f"ORD-Y{year}Q{quarter}-A"

        cash = add_cash_event(
            events,
            cash,
            "PAY_MATERIAL",
            p,
            -material_cost,
            {"material_bundle_id": f"MAT-Y{year}Q{quarter}", "amount_wan": material_cost, "bom_status": "missing_rule_simulated_bundle"},
        )
        ledger["material"] += material_cost
        cash = add_cash_event(
            events,
            cash,
            "START_PRODUCTION",
            p,
            -processing_cost,
            {"line_id": "LINE-01", "product_id": "P1", "quantity": quantity, "processing_cost_wan": processing_cost},
        )
        ledger["processing"] += processing_cost
        cash = add_cash_event(events, cash, "ORDER_OBTAINED", p, 0.0, {"order_id": order_id, "product_id": "P1", "quantity": quantity, "market_id": "local"})
        cash = add_cash_event(
            events,
            cash,
            "SELL_PRODUCT",
            p,
            revenue,
            {"order_id": order_id, "product_id": "P1", "quantity": quantity, "revenue_wan": revenue, "payment_term_quarters": 0},
        )
        ledger["sales"] += revenue

        if quarter == 4:
            depreciation = min(20.0, line_book_value)
            line_book_value = round(line_book_value - depreciation, 2)
            ledger["depreciation"] += depreciation
            cash = add_cash_event(events, cash, "DEPRECIATE_LINES", {**p, "phase": "year_end"}, 0.0, {"line_id": "LINE-01", "amount_wan": depreciation, "book_value_after_wan": line_book_value})

        cumulative_profit = 0.0
        for annual in yearly_ledgers.values():
            cumulative_profit += annual["sales"] - sum(
                annual[key]
                for key in ("material", "processing", "management", "advertising", "market_development", "product_development", "depreciation")
            )
        assets = round(cash + line_book_value, 2)
        retained = round(assets - 600.0, 2)
        if not math.isclose(retained, cumulative_profit, abs_tol=1e-9):
            raise AssertionError("synthetic accounting identity failed")

        state_core = {
            "match_id": MATCH_ID,
            "team_id": TARGET_TEAM_ID,
            "rule_pack_id": RULE_PACK_ID,
            "rule_version": RULE_VERSION,
            "previous_state_id": previous_state_id,
            "period": {"year": year, "quarter": quarter, "phase": "quarter_end"},
            "cash_wan": cash,
            "share_capital_wan": 600.0,
            "retained_earnings_wan": retained,
            "assets_total_wan": assets,
            "liabilities_total_wan": 0.0,
            "loans": [],
            "receivables": [],
            "workshops": [],
            "production_lines": [{"line_id": "LINE-01", "line_type": "automatic", "product_id": "P1", "status": "operational", "book_value_wan": line_book_value}],
            "inventory": {"materials": {}, "products": {"P1": 0}, "work_in_process": []},
            "qualifications": deepcopy(qualifications),
            "orders": [{"order_id": order_id, "status": "delivered", "revenue_wan": revenue}],
            "annual_ledger_so_far": deepcopy(ledger),
        }
        state_id = stable_id("state", state_core)
        snapshots.append({"state_id": state_id, **state_core, "provenance": provenance("simulated", [], "由本样例事件确定性派生")})
        previous_state_id = state_id

    return (
        {
            "team_id": TARGET_TEAM_ID,
            "initial_state": initial_state,
            "events": events,
            "quarter_snapshots": snapshots,
            "provenance": provenance("simulated", ["部分规则字段参考中文十簇观察指纹"], "完整五年流程是接口样例，不是历史企业记录"),
        },
        [deepcopy(yearly_ledgers[year]) | {"year": year} for year in sorted(yearly_ledgers)],
    )


def make_reports(timeline: dict[str, Any], yearly_ledgers: list[dict[str, Any]]) -> dict[str, Any]:
    snapshots_by_year = {item["period"]["year"]: item for item in timeline["quarter_snapshots"] if item["period"]["quarter"] == 4}
    reports = []
    for ledger in yearly_ledgers:
        year = ledger["year"]
        snapshot = snapshots_by_year[year]
        direct_cost = ledger["material"] + ledger["processing"]
        period_cost = ledger["management"] + ledger["advertising"] + ledger["market_development"] + ledger["product_development"]
        net_profit = ledger["sales"] - direct_cost - period_cost - ledger["depreciation"]
        report_core = {
            "year": year,
            "input_state_id": snapshot["state_id"],
            "comprehensive_costs": {
                "management_wan": ledger["management"],
                "advertising_wan": ledger["advertising"],
                "market_development_wan": ledger["market_development"],
                "product_development_wan": ledger["product_development"],
                "material_wan": ledger["material"],
                "processing_wan": ledger["processing"],
                "depreciation_wan": ledger["depreciation"],
                "capital_expenditure_wan": ledger["capital_expenditure"],
            },
            "income_statement": {"sales_wan": ledger["sales"], "direct_cost_wan": direct_cost, "period_cost_wan": period_cost, "depreciation_wan": ledger["depreciation"], "finance_cost_wan": 0.0, "tax_wan": 0.0, "net_profit_wan": net_profit},
            "balance_sheet": {"cash_wan": snapshot["cash_wan"], "production_lines_wan": snapshot["production_lines"][0]["book_value_wan"], "inventory_wan": 0.0, "receivables_wan": 0.0, "assets_total_wan": snapshot["assets_total_wan"], "loans_wan": 0.0, "other_liabilities_wan": 0.0, "liabilities_total_wan": 0.0, "share_capital_wan": 600.0, "retained_earnings_wan": snapshot["retained_earnings_wan"], "equity_total_wan": snapshot["assets_total_wan"]},
        }
        reports.append({"report_id": stable_id("report", report_core), **report_core, "accounting_version": "synthetic_cash_accrual_demo_v1", "provenance": provenance("derived", [snapshot["state_id"]], "由模拟事件按声明口径确定性计算")})
    return {"team_id": TARGET_TEAM_ID, "reports": reports}


def make_global_context(timeline: dict[str, Any]) -> dict[str, Any]:
    teams = [{"team_id": f"CN{index:02d}", "display_name": f"示例企业{index:02d}", "data_status": "synthetic"} for index in range(1, 21)]
    orders = []
    allocations = []
    public_quarters = []
    for period_index, target_snapshot in enumerate(timeline["quarter_snapshots"]):
        p = period(period_index, "quarter_start")
        year, quarter = p["year"], p["quarter"]
        target_event = next(event for event in timeline["events"] if event["event_type"] == "SELL_PRODUCT" and event["period"]["year"] == year and event["period"]["quarter"] == quarter)
        target_order_id = target_event["payload"]["order_id"]
        for suffix, product_id, market_id, quantity, price in (
            ("A", "P1", "local", target_event["payload"]["quantity"], target_event["payload"]["revenue_wan"]),
            ("B", "P2", "regional", 2 + period_index % 3, 105 + period_index * 2),
            ("C", "P3", "domestic", 1 + period_index % 2, 125 + period_index * 2),
        ):
            order_id = f"ORD-Y{year}Q{quarter}-{suffix}"
            orders.append({"order_id": order_id, "available_period": p, "product_id": product_id, "market_id": market_id, "quantity": quantity, "price_wan": float(price), "qualification_requirements": [], "payment_term_quarters": 0, "source_visibility": "public_before_selection_synthetic", "provenance": provenance("simulated", [], "中文十簇缺少赛前全局订单池，此记录只展示目标格式")})
        allocations.append({"order_id": target_order_id, "team_id": TARGET_TEAM_ID, "allocated_period": p, "allocation_reason": "synthetic_balanced_candidate_selected", "provenance": provenance("simulated", [], "广告和选单规则尚缺失")})
        allocations.append({"order_id": f"ORD-Y{year}Q{quarter}-B", "team_id": f"CN{period_index % 19 + 2:02d}", "allocated_period": p, "allocation_reason": "synthetic_competitor_result", "provenance": provenance("simulated", [], "广告和选单规则尚缺失")})

        team_rows = []
        for team_index in range(1, 21):
            if team_index == 1:
                equity = target_snapshot["assets_total_wan"]
            else:
                equity = round(590 + period_index * (9 + team_index % 5) + team_index * 3.5, 2)
            team_rows.append({"team_id": f"CN{team_index:02d}", "equity_wan": equity, "cash_wan": round(max(80.0, equity * (0.43 + team_index % 4 * 0.03)), 2), "advertising_wan": float(7 + year + team_index % 5), "source_visibility": "public_after_quarter_synthetic"})
        ranked = sorted(team_rows, key=lambda item: (-item["equity_wan"], item["team_id"]))
        for rank, item in enumerate(ranked, start=1):
            item["rank"] = rank
        public_quarters.append({"period": {"year": year, "quarter": quarter, "phase": "quarter_end"}, "teams": sorted(ranked, key=lambda item: item["team_id"]), "provenance": provenance("simulated", [], "展示每季全局公开快照的目标结构")})

    return {
        "match": {"match_id": MATCH_ID, "name": "中文规则族完整结构示例", "rule_pack_id": RULE_PACK_ID, "rule_version": RULE_VERSION, "years": 5, "quarters_per_year": 4, "team_count": 20, "status": "synthetic_reference"},
        "teams": teams,
        "global_order_pool": orders,
        "order_allocations": allocations,
        "public_quarter_observations": public_quarters,
        "provenance": provenance("simulated", ["中文十簇每簇约 20 家企业和 5 年公共 XLS 的结构"], "团队数和时间跨度参考历史结构，记录值均为模拟"),
    }


def make_analytics(timeline: dict[str, Any]) -> dict[str, Any]:
    metric_bundles = []
    for snapshot in timeline["quarter_snapshots"]:
        ledger = snapshot["annual_ledger_so_far"]
        quarter_events = [event for event in timeline["events"] if event["period"]["year"] == snapshot["period"]["year"] and event["period"]["quarter"] == snapshot["period"]["quarter"]]
        revenue = sum(event["cash_delta_wan"] for event in quarter_events if event["event_type"] == "SELL_PRODUCT")
        oe = sum(-event["cash_delta_wan"] for event in quarter_events if event["event_type"] in {"PAY_AD", "DEVELOP_MARKET", "DEVELOP_PRODUCT", "PAY_MANAGEMENT_FEE", "PAY_MATERIAL", "START_PRODUCTION"})
        depreciation = sum(event["payload"].get("amount_wan", 0) for event in quarter_events if event["event_type"] == "DEPRECIATE_LINES")
        oe += depreciation
        ratio = round(revenue / oe, 6) if oe else None
        u1 = min(1.0, max(0.0, snapshot["assets_total_wan"] / 1600.0))
        u2 = min(1.0, 0.72 + snapshot["period"]["quarter"] * 0.04)
        u3 = min(1.0, 0.66 + snapshot["period"]["year"] * 0.03)
        denominator = ((u1 + u2 + u3) / 3) ** 3
        coupling_c = (u1 * u2 * u3 / denominator) ** (1 / 3) if denominator else 0.0
        development_f = (u1 + u2 + u3) / 3
        coordination_h = math.sqrt(coupling_c * development_f)
        metric_core = {
            "input_state_id": snapshot["state_id"],
            "period": snapshot["period"],
            "formula_version": "illustrative_vpd_oe_not_validated_v1",
            "pss_units": [{"pss_id": "P1_local_automatic_operational", "product_id": "P1", "market_id": "local", "line_type": "automatic", "line_ids": ["LINE-01"], "vpd_wan": revenue, "oe_wan": round(oe, 2), "vpd_oe_ratio": ratio}],
            "u_dimensions": {"u1_assets": round(u1, 6), "u2_efficiency": round(u2, 6), "u3_fairness": round(u3, 6)},
            "coupling": {"c": round(coupling_c, 6), "f": round(development_f, 6), "h": round(coordination_h, 6)},
            "warnings": ["VPD/OE 口径仅用于展示接口", "U1/U2/U3 为模拟指标", "不得用于评价真实企业"],
        }
        metric_bundles.append({"metric_bundle_id": stable_id("metric", metric_core), **metric_core, "provenance": provenance("simulated", [snapshot["state_id"]], "数值用于展示 VPD 与报表 Agent 的接口")})
    return {"team_id": TARGET_TEAM_ID, "metric_bundles": metric_bundles}


def make_decisions(timeline: dict[str, Any], analytics: dict[str, Any]) -> dict[str, Any]:
    decisions = []
    previous_state_id = timeline["initial_state"]["state_id"]
    for index, snapshot in enumerate(timeline["quarter_snapshots"]):
        year = snapshot["period"]["year"]
        quarter = snapshot["period"]["quarter"]
        period_events = [event for event in timeline["events"] if event["period"]["year"] == year and event["period"]["quarter"] == quarter]
        revenue = next(event["cash_delta_wan"] for event in period_events if event["event_type"] == "SELL_PRODUCT")
        metric = analytics["metric_bundles"][index]
        candidates = [
            {"candidate_id": f"DC-Y{year}Q{quarter}-C1", "strategy": "conservative", "planned_order_ids": [], "predicted_min_cash_wan": round(snapshot["cash_wan"] - 5, 2), "predicted_equity_wan": round(snapshot["assets_total_wan"] - revenue * 0.35, 2), "violations": []},
            {"candidate_id": f"DC-Y{year}Q{quarter}-C2", "strategy": "balanced", "planned_order_ids": [f"ORD-Y{year}Q{quarter}-A"], "predicted_min_cash_wan": round(min(event["cash_after_wan"] for event in period_events), 2), "predicted_equity_wan": snapshot["assets_total_wan"], "violations": []},
            {"candidate_id": f"DC-Y{year}Q{quarter}-C3", "strategy": "aggressive", "planned_order_ids": [f"ORD-Y{year}Q{quarter}-A", f"ORD-Y{year}Q{quarter}-B"], "predicted_min_cash_wan": round(min(event["cash_after_wan"] for event in period_events) - 55, 2), "predicted_equity_wan": round(snapshot["assets_total_wan"] + revenue * 0.18, 2), "violations": ["second_order_capacity_not_proven"]},
        ]
        decision_core = {
            "decision_period": {"year": year, "quarter": quarter, "phase": "quarter_start"},
            "base_state_id": previous_state_id,
            "information_set": {"rules": {"rule_pack_id": RULE_PACK_ID, "rule_version": RULE_VERSION}, "available_order_ids": [f"ORD-Y{year}Q{quarter}-{suffix}" for suffix in "ABC"], "public_data_cutoff": {"year": year, "quarter": quarter, "phase": "quarter_start"}, "metric_bundle_id": metric["metric_bundle_id"]},
            "objective": {"hard_constraints": ["cash_nonnegative", "rule_valid", "capacity_sufficient", "delivery_on_time"], "soft_objectives": ["maximize_min_cash", "maximize_equity", "maximize_delivery_rate", "control_risk"]},
            "candidates": candidates,
            "selected_candidate_id": candidates[1]["candidate_id"],
            "selection_reason": "平衡方案在样例中无违规且保持更高权益；这是模拟决策，不是训练标签",
            "human_confirmation": {"status": "approved_synthetic", "confirmed_by": "example_generator"},
            "submitted_event_ids": [event["event_id"] for event in period_events],
            "outcome": {"state_id": snapshot["state_id"], "cash_wan": snapshot["cash_wan"], "equity_wan": snapshot["assets_total_wan"], "validation": "passed_synthetic_checks"},
        }
        decisions.append({"decision_id": stable_id("decision", decision_core), **decision_core, "provenance": provenance("simulated", [], "展示候选生成、沙盒比较、人工确认、提交和结果记录闭环")})
        previous_state_id = snapshot["state_id"]
    return {"team_id": TARGET_TEAM_ID, "decision_cycles": decisions}


def validate_bundle(bundle: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    timeline = bundle["enterprise_timeline"]
    global_context = bundle["global_context"]
    reports = bundle["reports"]
    analytics = bundle["analytics"]
    decisions = bundle["decision_cycles"]

    if len(timeline["quarter_snapshots"]) != 20:
        errors.append("target enterprise must contain 20 quarterly snapshots")
    if len(global_context["teams"]) != 20:
        errors.append("match must contain 20 teams")
    if len(global_context["public_quarter_observations"]) != 20:
        errors.append("global context must contain 20 public quarters")
    if any(len(item["teams"]) != 20 for item in global_context["public_quarter_observations"]):
        errors.append("each public quarter must contain 20 teams")
    if len(global_context["global_order_pool"]) != 60:
        errors.append("synthetic global order pool must contain 60 orders")
    if len(reports["reports"]) != 5:
        errors.append("target enterprise must contain 5 annual reports")
    if len(analytics["metric_bundles"]) != 20:
        errors.append("target enterprise must contain 20 metric bundles")
    if len(decisions["decision_cycles"]) != 20:
        errors.append("target enterprise must contain 20 decision cycles")

    previous_cash = timeline["initial_state"]["cash_wan"]
    event_ids = set()
    for event in timeline["events"]:
        event_ids.add(event["event_id"])
        if not math.isclose(event["cash_before_wan"], previous_cash, abs_tol=1e-9):
            errors.append(f"cash discontinuity before {event['event_id']}")
        expected_after = event["cash_before_wan"] + event["cash_delta_wan"]
        if not math.isclose(event["cash_after_wan"], expected_after, abs_tol=1e-9):
            errors.append(f"cash arithmetic mismatch at {event['event_id']}")
        previous_cash = event["cash_after_wan"]

    order_ids = {item["order_id"] for item in global_context["global_order_pool"]}
    for allocation in global_context["order_allocations"]:
        if allocation["order_id"] not in order_ids:
            errors.append(f"allocation references missing order {allocation['order_id']}")
    for report in reports["reports"]:
        balance = report["balance_sheet"]
        if not math.isclose(balance["assets_total_wan"], balance["liabilities_total_wan"] + balance["equity_total_wan"], abs_tol=1e-9):
            errors.append(f"balance sheet identity failed for year {report['year']}")
    for decision in decisions["decision_cycles"]:
        missing_events = sorted(set(decision["submitted_event_ids"]) - event_ids)
        if missing_events:
            errors.append(f"decision {decision['decision_id']} references missing events: {missing_events}")

    if bundle["rule_pack"]["simulation_ready"]:
        errors.append("provisional observed rule pack must remain simulation_ready=false")
    warnings.extend(bundle["rule_pack"]["blocking_gaps"])
    return {
        "dataset_id": DATASET_ID,
        "schema_version": SCHEMA_VERSION,
        "status": "passed" if not errors else "failed",
        "checks": {
            "quarter_count": 20,
            "team_count": 20,
            "public_team_rows": 400,
            "global_order_count": 60,
            "annual_report_count": 5,
            "metric_bundle_count": 20,
            "decision_cycle_count": 20,
            "cash_continuity": "passed" if not any("cash" in error for error in errors) else "failed",
            "balance_sheet_identity": "passed" if not any("balance sheet" in error for error in errors) else "failed",
            "foreign_keys": "passed" if not any("references missing" in error for error in errors) else "failed",
        },
        "errors": errors,
        "expected_rule_gaps": warnings,
        "data_use_restriction": "synthetic reference only; never merge into observed historical training data",
    }


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def generate(output_dir: Path) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    rule_pack = make_rule_pack()
    enterprise_timeline, yearly_ledgers = make_enterprise_timeline()
    reports = make_reports(enterprise_timeline, yearly_ledgers)
    global_context = make_global_context(enterprise_timeline)
    analytics = make_analytics(enterprise_timeline)
    decision_cycles = make_decisions(enterprise_timeline, analytics)

    components = {
        "rule_pack.json": rule_pack,
        "global_context.json": global_context,
        "enterprise_timeline.json": enterprise_timeline,
        "reports.json": reports,
        "analytics.json": analytics,
        "decision_cycles.json": decision_cycles,
    }
    for file_name, payload in components.items():
        write_json(output_dir / file_name, payload)

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "dataset_id": DATASET_ID,
        "generated_at": GENERATED_AT,
        "data_class": "synthetic_reference",
        "language_priority": "zh-CN",
        "formal_training_eligible": False,
        "purpose": "展示完整比赛、企业时间线、报表、VPD 分析和决策闭环所需的数据形态",
        "source_basis": [
            {"dataset_group": "AB/CA/CB/CD/CE/EA/EB/EC/EF/OP", "use": "共同观察规则指纹和历史结构", "binding_status": "formal_rules_missing"},
            {"dataset_group": "GC rules", "use": "not_used", "binding_status": "unbound_conflicting_candidate"},
            {"dataset_group": "ZY/AG/ZZ", "use": "not_used", "binding_status": "separate_export_family"},
            {"dataset_group": "710W test bundle", "use": "not_used", "binding_status": "excluded_from_chinese_mainline"},
        ],
        "provenance_status_enum": ["observed", "derived", "inferred", "simulated", "missing"],
        "component_files": [
            {"file": file_name, "sha256": sha256_file(output_dir / file_name), "bytes": (output_dir / file_name).stat().st_size}
            for file_name in sorted(components)
        ],
        "not_training_data": True,
    }
    write_json(output_dir / "manifest.json", manifest)

    bundle = {
        "manifest": manifest,
        "rule_pack": rule_pack,
        "global_context": global_context,
        "enterprise_timeline": enterprise_timeline,
        "reports": reports,
        "analytics": analytics,
        "decision_cycles": decision_cycles,
    }
    validation = validate_bundle(bundle)
    write_json(output_dir / "validation_report.json", validation)
    write_json(output_dir / "complete_match.json", bundle | {"validation": validation})
    return validation


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a complete synthetic GoAI match data example")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "data" / "examples" / "complete_match_v1",
    )
    args = parser.parse_args()
    validation = generate(args.output.resolve())
    print(json.dumps(validation, ensure_ascii=False, indent=2))
    return 0 if validation["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
