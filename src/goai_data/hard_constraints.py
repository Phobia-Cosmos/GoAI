from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .global_rules import development_potential, rank_final_states


HARD_CONSTRAINTS_VERSION = "hard_constraints_v0.2"


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _close(left: float | None, right: float | None, tolerance: float = 1e-6) -> bool:
    return left is not None and right is not None and abs(left - right) <= tolerance


@dataclass
class ConstraintReport:
    match_id: str
    passed: bool = True
    violations: list[dict[str, Any]] = field(default_factory=list)
    checks: dict[str, dict[str, Any]] = field(default_factory=dict)

    def fail(self, check: str, message: str, **details: Any) -> None:
        self.passed = False
        self.violations.append({"check": check, "message": message, **details})
        self.checks.setdefault(check, {"passed": True, "violations": []})
        self.checks[check]["passed"] = False
        self.checks[check]["violations"].append({"message": message, **details})

    def pass_check(self, check: str, **details: Any) -> None:
        self.checks.setdefault(check, {"passed": True, "violations": []})
        self.checks[check].update(details)

    def to_dict(self) -> dict[str, Any]:
        return {"version": HARD_CONSTRAINTS_VERSION, "match_id": self.match_id, "passed": self.passed, "checks": self.checks, "violations": self.violations}


def _check_reports(reports: list[dict[str, Any]], result: ConstraintReport) -> None:
    values: dict[tuple[str, int, str], dict[str, float]] = {}
    for row in reports:
        if row.get("report_variant") not in {"system", "系统"}:
            continue
        team_id = row.get("team_id")
        year = row.get("year")
        statement = row.get("statement")
        metric = row.get("metric")
        value = row.get("value_wan")
        # Historical AB-family workbooks contain an "初始元年" export column
        # whose layout is not the same as operating-year statements. The hard
        # accounting constraints target the formal Y1–Y5 operating period.
        if not team_id or not isinstance(year, int) or year < 1 or not statement or not metric or not isinstance(value, (int, float)):
            continue
        values.setdefault((team_id, year, statement), {})[metric] = float(value)

    checked = 0
    for (team_id, year, statement), row in values.items():
        if statement == "balance_sheet":
            current_assets = row.get("流动资产合计")
            components = [row.get(name) for name in ("现金", "应收款", "在制品", "产成品", "原材料")]
            if current_assets is not None and all(value is not None for value in components):
                checked += 1
                if not _close(current_assets, sum(components)):
                    result.fail("report_current_assets_identity", "流动资产合计不等于组成项", team_id=team_id, year=year, actual=current_assets, expected=sum(components))
            fixed_assets = row.get("固定资产合计")
            fixed_components = [row.get(name) for name in ("厂房", "机器设备", "在建工程")]
            if fixed_assets is not None and all(value is not None for value in fixed_components):
                checked += 1
                if not _close(fixed_assets, sum(fixed_components)):
                    result.fail("report_fixed_assets_identity", "固定资产合计不等于组成项", team_id=team_id, year=year, actual=fixed_assets, expected=sum(fixed_components))
            assets = row.get("资产总计")
            if assets is not None and current_assets is not None and fixed_assets is not None:
                checked += 1
                if not _close(assets, current_assets + fixed_assets):
                    result.fail("report_assets_identity", "资产总计不等于流动资产与固定资产之和", team_id=team_id, year=year, actual=assets, expected=current_assets + fixed_assets)
            liabilities = row.get("负债合计")
            equity = row.get("所有者权益合计")
            total = row.get("负债和所有者权益总计")
            if total is not None and liabilities is not None and equity is not None:
                checked += 1
                if not _close(total, liabilities + equity):
                    result.fail("report_liabilities_equity_identity", "负债和所有者权益总计不平衡", team_id=team_id, year=year, actual=total, expected=liabilities + equity)
    result.pass_check("report_accounting_identities", checked_rows=checked)


def validate_match(match_dir: Path) -> ConstraintReport:
    match_dir = match_dir.resolve()
    manifest = json.loads((match_dir / "manifest.json").read_text(encoding="utf-8"))
    match_id = manifest["match_id"]
    report = ConstraintReport(match_id)
    teams = _jsonl(match_dir / "teams.jsonl")
    events = _jsonl(match_dir / "events.jsonl")
    orders = _jsonl(match_dir / "global_orders.jsonl")
    reports = _jsonl(match_dir / "reports.jsonl")
    quarter_states = _jsonl(match_dir / "quarter_states.jsonl")
    team_ids = {row["team_id"] for row in teams}

    required_files = manifest.get("files", [])
    missing_files = [name for name in required_files if not (match_dir / name).is_file()]
    if missing_files:
        report.fail("schema_files", "统一数据集缺少必需文件", missing_files=missing_files)
    else:
        report.pass_check("schema_files", file_count=len(required_files))

    if len(team_ids) != len(teams):
        report.fail("unique_team_ids", "企业 team_id 重复")
    else:
        report.pass_check("unique_team_ids", team_count=len(teams))

    event_ids = [row["event_id"] for row in events]
    if len(event_ids) != len(set(event_ids)):
        report.fail("unique_event_ids", "事件 ID 重复")
    else:
        report.pass_check("unique_event_ids", event_count=len(event_ids))

    by_team: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        by_team.setdefault(event["team_id"], []).append(event)
        year, quarter = event.get("year"), event.get("quarter")
        if event.get("included_in_match"):
            if event.get("action") is None:
                report.fail("operating_action_mapping", "比赛期事件没有标准动作", event_id=event["event_id"])
            if not (isinstance(year, int) and 1 <= year <= 5 and isinstance(quarter, int) and 1 <= quarter <= 4):
                report.fail("operating_period", "比赛期事件不在 Y1Q1–Y5Q4", event_id=event["event_id"], period=event.get("period"))
            if not isinstance(event.get("amount_wan"), (int, float)) or not isinstance(event.get("balance_wan"), (int, float)):
                report.fail("event_numeric_cash", "比赛期事件缺少数值资金和余额", event_id=event["event_id"])
        elif event.get("exclusion_reason") is None:
            report.fail("excluded_event_reason", "被排除事件没有排除原因", event_id=event["event_id"])
    report.pass_check("operating_action_mapping", operating_event_count=sum(bool(row.get("included_in_match")) for row in events))
    report.pass_check("operating_period")

    continuity_count = 0
    for team_id, team_events in by_team.items():
        previous_balance = None
        for event in sorted((row for row in team_events if row.get("included_in_match")), key=lambda row: row["sequence_in_source"]):
            balance = float(event["balance_wan"])
            amount = float(event["amount_wan"])
            if previous_balance is not None:
                continuity_count += 1
                expected = previous_balance + amount
                if not _close(balance, expected):
                    report.fail("cash_continuity", "余额不等于上期余额加资金变化", event_id=event["event_id"], actual=balance, expected=expected)
            previous_balance = balance
    report.pass_check("cash_continuity", transition_count=continuity_count)

    order_ids = [row["order_id"] for row in orders]
    if len(order_ids) != len(set(order_ids)):
        report.fail("unique_order_ids", "全局订单 ID 重复")
    else:
        report.pass_check("unique_order_ids", order_count=len(order_ids))
    for order in orders:
        quantity = order.get("quantity")
        price = order.get("total_price_wan")
        owner = order.get("owner_team_id")
        if not isinstance(quantity, (int, float)) or quantity <= 0:
            report.fail("order_quantity", "订单数量必须为正数", order_id=order["order_id"], quantity=quantity)
        if not isinstance(price, (int, float)) or price < 0:
            report.fail("order_price", "订单总价不能为负数", order_id=order["order_id"], total_price_wan=price)
        if owner is not None and owner not in team_ids:
            report.fail("order_owner_exists", "订单所属企业不存在", order_id=order["order_id"], owner_team_id=owner)
    report.pass_check("order_fields", order_count=len(orders))

    states_by_team: dict[str, list[dict[str, Any]]] = {}
    for state in quarter_states:
        states_by_team.setdefault(state["team_id"], []).append(state)
        if not (1 <= int(state["period_index"]) <= 20):
            report.fail("quarter_period_range", "季度索引不在 1–20", state_id=state["state_id"])
    for team_id in team_ids:
        states = states_by_team.get(team_id, [])
        periods = [int(row["period_index"]) for row in states]
        if len(states) != 20 or periods != list(range(1, 21)):
            report.fail("quarter_state_shape", "企业没有完整的 20 个季度切片", team_id=team_id, actual_periods=periods)
    report.pass_check("quarter_state_shape", team_count=len(team_ids), state_count=len(quarter_states))

    if match_id == "LX_XA":
        simulated = [row["order_id"] for row in orders if row.get("provenance") == "simulated"]
        if simulated:
            report.fail("xa_no_extra_simulated_orders", "XA 已有完整订单池，不应额外生成模拟订单", simulated_count=len(simulated))
        assigned_count = sum(row.get("owner_team_id") is not None for row in orders)
        unassigned_count = sum(row.get("owner_team_id") is None for row in orders)
        if len(orders) != 796 or assigned_count != 561 or unassigned_count != 235:
            report.fail("xa_order_pool_counts", "XA 全局订单池数量与已审计结果不符", total=len(orders), assigned=assigned_count, unassigned=unassigned_count)
        else:
            report.pass_check("xa_order_pool_counts", total=len(orders), assigned=assigned_count, unassigned=unassigned_count)
        rules = json.loads((match_dir / "rules.json").read_text(encoding="utf-8"))
        if rules.get("parameters", {}).get("initial_cash_wan") != 675:
            report.fail("xa_initial_cash_rule", "XA 初始现金规则不是 675W")
        else:
            report.pass_check("xa_initial_cash_rule", initial_cash_wan=675)
        results = json.loads((match_dir / "results.json").read_text(encoding="utf-8"))
        final_states = _jsonl(match_dir / "final_states.jsonl")
        recomputed = rank_final_states(final_states, rules)
        official = results.get("ranking", [])
        official_by_team = {row.get("team_id"): row for row in official}
        score_mismatches = [
            {
                "team_id": row.get("team_id"),
                "official_score": official_by_team.get(row.get("team_id"), {}).get("official_score"),
                "recomputed_score": row.get("rounded_score"),
            }
            for row in recomputed
            if official_by_team.get(row.get("team_id"), {}).get("official_score") != row.get("rounded_score")
        ]
        if score_mismatches:
            report.fail("xa_official_scores", "XA 终局状态重算分数与官方分数不一致", mismatches=score_mismatches)
        else:
            report.pass_check("xa_official_scores", ranked_team_count=len(recomputed))
        official_order = [row.get("team_id") for row in official]
        recomputed_order = [row.get("team_id") for row in recomputed]
        if official_order != recomputed_order:
            report.fail("xa_exact_rank_order", "XA 终局状态重算排名与官方排名不一致", official=official_order, recomputed=recomputed_order)
        else:
            report.pass_check("xa_exact_rank_order", ranked_team_count=len(recomputed))
        official_bankruptcies = {row.get("team_id"): row.get("period") for row in results.get("bankruptcies", [])}
        replayed_bankruptcies = {row.get("team_id"): row.get("bankruptcy_period") for row in final_states if row.get("bankruptcy_period")}
        if official_bankruptcies != replayed_bankruptcies:
            report.fail("xa_exact_bankruptcies", "XA 终局状态中的破产企业或时期与官方结果不一致", official=official_bankruptcies, replayed=replayed_bankruptcies)
        else:
            report.pass_check("xa_exact_bankruptcies", bankrupt_team_count=len(replayed_bankruptcies))
        potential_mismatches = [
            {"team_id": row.get("team_id"), "recorded": row.get("development_potential"), "recomputed": development_potential(row.get("assets") or {}, rules)}
            for row in final_states
            if float(row.get("development_potential", 0)) != development_potential(row.get("assets") or {}, rules)
        ]
        if potential_mismatches:
            report.fail("xa_exact_development_potential", "XA 资产重算发展潜力不一致", mismatches=potential_mismatches)
        else:
            report.pass_check("xa_exact_development_potential", team_count=len(final_states))
        final_cash = {row.get("team_id"): row.get("end_cash_wan") for row in quarter_states if int(row.get("period_index", 0)) == 20}
        cash_mismatches = [row.get("team_id") for row in final_states if final_cash.get(row.get("team_id")) != row.get("final_cash_wan")]
        if cash_mismatches:
            report.fail("xa_exact_terminal_cash", "XA 季度现金回放终值与终局状态不一致", team_ids=cash_mismatches)
        else:
            report.pass_check("xa_exact_terminal_cash", team_count=len(final_states))

    _check_reports(reports, report)
    quality = json.loads((match_dir / "quality.json").read_text(encoding="utf-8"))
    failed_quality_checks = [name for name, value in quality.get("checks", {}).items() if not value.get("passed")]
    if failed_quality_checks:
        report.fail("dataset_quality", "统一数据集内部质量检查未通过", failed_checks=failed_quality_checks)
    else:
        report.pass_check("dataset_quality", source_quality_checks="all_passed")
    return report


def validate_dataset(dataset_root: Path) -> dict[str, Any]:
    catalog = json.loads((dataset_root / "catalog.json").read_text(encoding="utf-8"))
    reports = [validate_match(dataset_root / row["path"]) for row in catalog["matches"]]
    return {
        "version": HARD_CONSTRAINTS_VERSION,
        "dataset_root": str(dataset_root.resolve()),
        "passed": all(report.passed for report in reports),
        "match_count": len(reports),
        "matches": [report.to_dict() for report in reports],
    }
