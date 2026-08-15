"""Clickable local competition platform for human and Agent XA matches.

The HTTP layer never computes finance itself.  It coordinates player sessions,
collects one action bundle per human team, asks configured bots for the other
bundles, and delegates the complete quarter to ``FullCompetitionArena``.
"""

from __future__ import annotations

import copy
import json
import mimetypes
import threading
import uuid
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.parse import parse_qs, quote, urlparse

from .collaborative_agent import CollaborativeEnterprisePolicy
from .competition_xlsx import build_competition_xlsx_archive
from .decision_system import AgentObservation
from .full_sandbox import (
    FixedXABaselinePolicy,
    FullCompetitionArena,
    FullFinancialDynamics,
    SeededHeuristicPolicy,
    generate_global_orders,
    generate_simulated_rule_pack,
)
from .global_rules import development_potential, ranking_score
from .xa_population import XALateAggressivePopulationPolicy, strategy_class_for_team


WEB_PLATFORM_VERSION = "enterprise_decision_arena_v0.8_annual_quarterly_single_submit"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MATCH_DIR = PROJECT_ROOT / "data" / "processed" / "v2" / "matches" / "LX_XA"
STATIC_DIR = Path(__file__).resolve().parent / "web_static"

STRATEGY_CLASS_LABELS = {
    "leader_growth": "增长领先型",
    "balanced_expansion": "平衡扩张型",
    "conservative_survivor": "稳健存续型",
    "aggressive_failed": "高风险扩张型",
}


def _display_value(value: Any) -> str:
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, Mapping):
        return "、".join(f"{key} {float(item):g}" if isinstance(item, (int, float)) else f"{key} {item}" for key, item in value.items()) or "无"
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return "、".join(str(item) for item in value) or "无"
    if isinstance(value, float):
        return f"{value:.1f}"
    return str(value)


def _evidence_summary(evidence: Mapping[str, Any]) -> str:
    evidence_names = {
        "observed_cash_wan": "当前现金", "effective_cash_wan": "扣除近期义务后现金", "reserve_wan": "目标安全垫",
        "products": "已有产品", "markets": "已有市场", "iso": "已有认证", "visible_orders": "公开订单数",
        "selected_orders": "拟申领订单数", "fallback_candidates": "回退候选数", "outstanding_orders": "在手订单数",
        "ready_line_count": "就绪产线数", "backlog_units": "待履约数量", "forecast_materials": "预测原料需求",
    }
    rows = [f"{evidence_names[key]}：{_display_value(value)}" for key, value in evidence.items() if key in evidence_names]
    return "；".join(rows[:4]) or "依据本企业当前可见状态计算"


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _generated_rule_pack(base_rules: Mapping[str, Any], *, match_id: str, team_count: int, seed: int, source_rule_path: str, first_year_has_orders: bool | None = None) -> dict[str, Any]:
    """Create one auditable rule pack from conservative multi-competition ranges.

    This web-only generator deliberately varies economic parameters while
    keeping accounting identities, action semantics and period timing stable.
    It is a simulation rule notice, not a claim about any official event.
    """

    rules = generate_simulated_rule_pack(
        base_rules,
        seed=seed,
        match_id=match_id,
        variability=0.08,
        team_count=team_count,
        source_match_id="internal_normalized_reference",
        source_rule_path=source_rule_path,
        complexity_profile="large",
    )
    # The current competition contract has no first-year orders.  The full
    # order catalogue is visible from the lobby, while each order opens for
    # advertising/claiming one quarter before its release period.
    rules["parameters"]["first_year_has_orders"] = False
    rules["parameters"]["order_claim_lead_quarters"] = 1
    rules["parameters"]["asset_limits"] = {
        "max_factories_total": 3,
        "max_factories_per_type": 1,
    }
    rules["rule_pack_id"] = f"SIM_RULE_{seed}"
    rules["binding_status"] = "simulated_generated"
    rules["provenance"] = {
        "source_kind": "multi_competition_range_synthesis",
        "public_label": "综合沙盘规则范围模拟生成",
        "official_rule_claim": False,
        "seed": seed,
    }
    rules.setdefault("generation", {})["mode"] = "generated_simulation_competition"
    return rules


def _rule_notice(rules: Mapping[str, Any], *, match_name: str) -> dict[str, Any]:
    p = rules.get("parameters") or {}
    products, markets, certificates = p.get("products") or {}, p.get("markets") or {}, p.get("iso") or {}
    financial = rules.get("financial_rules") or {}

    def number(value: Any) -> str:
        value = float(value or 0)
        return f"{value:g}"

    product_items = [
        [product_id, f"研发 {spec.get('quarters', 0)} 季度，每季 {number(spec.get('development_wan_per_quarter'))} 万元；直接成本 {number(spec.get('direct_cost_wan'))} 万元；BOM " +
         ("、".join(f"{component}x{number(quantity)}" for component, quantity in (spec.get('bom') or {}).items()) or "无") + f"；潜力 {number(spec.get('score'))}"]
        for product_id, spec in products.items()
    ]
    market_items = [
        [market_id, f"开拓 {spec.get('years', 0)} 年，每年 {number(spec.get('fee_wan_per_year'))} 万元；潜力 {number(spec.get('score'))}"]
        for market_id, spec in markets.items()
    ]
    certificate_items = [
        [certificate_id, f"认证 {spec.get('years', 0)} 年，每年 {number(spec.get('fee_wan_per_year'))} 万元；潜力 {number(spec.get('score'))}"]
        for certificate_id, spec in certificates.items()
    ]
    factory_items = [
        [factory_id, f"购买 {number(spec.get('purchase_wan'))} 万元，年租 {number(spec.get('rent_wan_per_year'))} 万元，容量 {number(spec.get('capacity'))}，残值 {number(spec.get('sale_wan'))} 万元；同类型最多 1 座"]
        for factory_id, spec in (p.get("factories") or {}).items()
    ]
    line_items = [
        [line_id, f"投资 {number(spec.get('investment_wan'))} 万元，安装 {spec.get('install_quarters', 0)} 季度，生产周期 {spec.get('production_quarters', 0)} 季度，年维护 {number(spec.get('maintenance_wan_per_year'))} 万元，残值 {number(spec.get('residual_value_wan'))} 万元，潜力 {number(spec.get('score'))}"]
        for line_id, spec in (p.get("production_lines") or {}).items()
    ]
    material_items = [
        [material_id, f"单价 {number(spec.get('price_wan'))} 万元，提前 {spec.get('lead_quarters', 0)} 季度订购"]
        for material_id, spec in (p.get("materials") or {}).items()
    ]
    return {
        "title": f"{match_name}比赛规则通知",
        "notice_id": f"RULE-{str(rules.get('match_id') or 'SIM').split('_')[-1]}",
        "status": "本场模拟赛生效",
        "provenance": "由多场企业经营沙盘的公开机制与合理参数范围生成；不代表任何单一赛事官方规则。",
        "sections": [
            {"name": "赛程与初始条件", "items": [
                ["经营周期", "5 年，共 20 个季度"], ["参赛企业", f"{len((rules.get('participants') or {}).get('team_ids') or [])} 家"],
                ["初始现金", f"{p.get('initial_cash_wan')} 万元"], ["首年订单", "第一年无订单收入；用于完成资格、厂房、产线和原料准备"],
                ["全局订单可见性", "全赛程订单从比赛开始即可查看；最终归属和对手私有动作不可见"],
            ]},
            {"name": "决策节奏与提前期", "items": [
                ["年度大规划", "每年第一季度形成当年资金、资格、产能、供应和订单目标；后续季度只做滚动修订"],
                ["季度提交", "每季度仅提交一次完整动作包；系统随后依次执行经营动作、竞单、交付、财务结算和反馈"],
                ["订单与广告", "订单释放前 1 个季度开放广告、选单或竞单；例如 Y2Q1 订单在 Y1Q4 申领"],
                ["产品研发", "必须至少提前对应产品规则中的研发季度数启动"],
                ["市场与认证", "必须至少提前对应规则中的年度数启动"],
                ["厂房与产线", f"厂房最多 {int((p.get('asset_limits') or {}).get('max_factories_total', 3))} 座、同类型最多 1 座；产线受厂房容量和安装季度限制"],
                ["原料与生产", "原料按各物料提前期订购；生产按所选产线生产周期倒排，必须在订单交期前完成"],
            ]},
            {"name": "融资与结算", "items": [
                ["短期贷款", f"利率 {float((p.get('short_loan') or {}).get('rate') or 0) * 100:.0f}%，到期还本付息"],
                ["长期贷款", f"年利率 {float((p.get('long_loan') or {}).get('annual_rate') or 0) * 100:.0f}%，最长 {(p.get('long_loan') or {}).get('max_years')} 年"],
                ["所得税率", f"{float(p.get('tax_rate') or 0) * 100:.0f}%"], ["季度管理费", f"{p.get('management_fee_per_quarter_wan')} 万元"],
                ["破产条件", "现金流断裂或所有者权益为负，由环境结算判定"],
            ]},
            {"name": "订单与履约", "items": [
                ["季度流程", "年度规划/季度修订 -> 一次提交 -> 环境执行经营动作与竞单 -> 交付和财务结算 -> 返回反馈"],
                ["信息发布边界", "全局订单从比赛开始可见；本企业获单单独显示；对手私有动作和最终归属不可提前查看"],
                ["普通选单冲突", "依次比较资格、广告、市场销售排序与提交顺序"],
                ["竞单冲突", "满足资格后比较有效报价；同价按规则优先级处理"],
                ["违约处罚", f"按订单金额的 {float(p.get('default_penalty_rate') or 0) * 100:.0f}% 计罚，并记录违约"],
            ]},
            {"name": "产品研发", "items": product_items},
            {"name": "市场开拓", "items": market_items},
            {"name": "认证投资", "items": certificate_items},
            {"name": "厂房参数", "items": factory_items},
            {"name": "生产线参数", "items": line_items},
            {"name": "原料参数", "items": material_items},
            {"name": "应急与资产调整", "items": [
                ["紧急购料", f"即时取得原料，按常规价格的 {number(p.get('emergency_material_price_multiplier', financial.get('emergency_material_price_multiplier', 2)))} 倍计价"],
                ["紧急购成品", f"即时取得成品，按直接成本的 {number(p.get('emergency_product_price_multiplier', financial.get('emergency_product_price_multiplier', 3)))} 倍计价"],
                ["产线转产与出售", "仅对本企业已建成且本阶段允许操作的产线开放，按对应产线成本、工期和残值结算"],
                ["商业情报", "仅在本场规则启用时付费购买有限字段，不提供目标企业全部私有状态或未来动作"],
            ]},
            {"name": "终局评价", "items": [
                ["评分公式", "最终评分 = 所有者权益 x (1 + 发展潜力 / 100)；破产企业不参与有效排名"], ["发展潜力", "由产品、市场、认证、自有厂房和已建成产线的规则分值累加形成"],
                ["可审计性", "规则种子、订单、动作、状态转移和年度报表随本场记录保存"],
            ]},
        ],
    }


def _safe_observation(observation: AgentObservation) -> dict[str, Any]:
    return {
        "match_id": observation.match_id,
        "team_id": observation.agent_id,
        "period": observation.period,
        "period_index": observation.period_index,
        "private_state": copy.deepcopy(dict(observation.private_state)),
        "public_state": copy.deepcopy(dict(observation.public_state)),
        "legal_actions": copy.deepcopy(list(observation.legal_actions)),
        "decision_phase": str(observation.public_state.get("decision_phase") or "operating"),
    }


@dataclass
class PlayerSeat:
    player_id: str
    player_name: str
    team_id: str
    token: str

    def public_dict(self) -> dict[str, str]:
        return {"player_id": self.player_id, "player_name": self.player_name, "team_id": self.team_id}


@dataclass
class CompetitionSession:
    match_id: str
    name: str
    seed: int
    rules: dict[str, Any]
    orders: list[dict[str, Any]]
    arena: FullCompetitionArena
    observations: dict[str, AgentObservation]
    human_team_ids: tuple[str, ...]
    bot_policy: str
    bots: dict[str, Any]
    status: str = "lobby"
    step: int = 0
    players: dict[str, PlayerSeat] = field(default_factory=dict)
    pending_actions: dict[str, Mapping[str, Any]] = field(default_factory=dict)
    last_feedback: dict[str, dict[str, Any]] = field(default_factory=dict)
    history: list[dict[str, Any]] = field(default_factory=list)
    recommendation_cache: dict[str, dict[str, Any]] = field(default_factory=dict)
    recommendation_revisions: list[dict[str, Any]] = field(default_factory=list)
    decision_comparisons: list[dict[str, Any]] = field(default_factory=list)
    annual_plans: dict[str, dict[int, dict[str, Any]]] = field(default_factory=dict)
    autopilot_log: list[dict[str, Any]] = field(default_factory=list)
    lock: threading.RLock = field(default_factory=threading.RLock)

    @property
    def unclaimed_human_teams(self) -> list[str]:
        claimed = {player.team_id for player in self.players.values()}
        return [team_id for team_id in self.human_team_ids if team_id not in claimed]

    def player_for_token(self, token: str | None) -> PlayerSeat | None:
        return next((player for player in self.players.values() if player.token == token), None)

    def join(self, player_name: str) -> PlayerSeat:
        with self.lock:
            if self.status != "lobby":
                raise ValueError("比赛已经开始，不能再加入")
            available = self.unclaimed_human_teams
            if not available:
                raise ValueError("人类玩家席位已满")
            player = PlayerSeat(uuid.uuid4().hex, player_name.strip() or f"玩家{len(self.players) + 1}", available[0], uuid.uuid4().hex)
            self.players[player.player_id] = player
            return player

    def start(self) -> None:
        with self.lock:
            if self.status != "lobby":
                return
            if self.unclaimed_human_teams:
                raise ValueError(f"还有 {len(self.unclaimed_human_teams)} 个人类席位未加入")
            self.status = "running"

    def _feedback_payload(self, team_id: str, result: Any, period: str) -> dict[str, Any]:
        info = copy.deepcopy(dict(result.infos[team_id]))
        state = self.arena.states[team_id]
        previous = self._pre_step_states.get(team_id, {})
        current = state.to_dict()
        cash_delta = float(current.get("cash_wan") or 0) - float(previous.get("cash_wan") or 0)
        equity_delta = float(current.get("owner_equity_wan") or 0) - float(previous.get("owner_equity_wan") or 0)
        awarded_delta = max(0, len(current.get("assigned_orders") or []) - len(previous.get("assigned_orders") or []))
        delivered_delta = max(0, len(current.get("delivered_orders") or []) - len(previous.get("delivered_orders") or []))
        defaulted_delta = max(0, len(current.get("defaulted_orders") or []) - len(previous.get("defaulted_orders") or []))
        suggestions: list[str] = []
        if info.get("action_rejections"):
            suggestions.append("先修正被裁判拒绝的动作，再安排新增投入。")
        if current.get("bankrupt"):
            suggestions.append("企业已触发破产，本局后续仅能复盘资金链断点。")
        elif float(current.get("cash_wan") or 0) < 50:
            suggestions.append("现金缓冲偏低，下一阶段优先检查到期贷款、应收贴现和最低履约资金。")
        if defaulted_delta:
            suggestions.append("本期发生订单违约，应减少超出资格、库存和可交付产能的申领。")
        elif awarded_delta and not delivered_delta:
            suggestions.append("已获得新订单，履约阶段应按交期倒排原料、产线和成品缺口。")
        elif delivered_delta:
            suggestions.append("本期交付已形成回款，下一期可比较扩产收益与保留现金的风险。")
        if not suggestions:
            suggestions.append("经营状态稳定，下一期继续比较订单边际收益、产能占用和现金安全垫。")
        return {
            "agent_id": team_id,
            "period": period,
            "reward": result.rewards[team_id],
            "events": info.get("events") or [],
            "action_status": info.get("action_status"),
            "action_rejections": info.get("action_rejections") or [],
            "bankrupt": info.get("bankrupt"),
            "balance_gap_wan": info.get("balance_gap_wan"),
            "terminated": result.terminated,
            "decision_phase": info.get("decision_phase"),
            "state_changes": {
                "cash_wan": round(cash_delta, 4),
                "owner_equity_wan": round(equity_delta, 4),
                "awarded_orders": awarded_delta,
                "delivered_orders": delivered_delta,
                "defaulted_orders": defaulted_delta,
            },
            "review_suggestions": suggestions,
        }

    def _advance(self) -> None:
        if self.status != "running":
            raise ValueError("比赛尚未开始")
        period = next(iter(self.observations.values())).period
        decision_phase = str(next(iter(self.observations.values())).public_state.get("decision_phase") or "operating")
        actions: dict[str, Mapping[str, Any]] = {}
        for team_id in self.arena.agent_ids:
            if team_id in self.human_team_ids:
                actions[team_id] = copy.deepcopy(dict(self.pending_actions.get(team_id) or {"action_type": "hold"}))
            else:
                actions[team_id] = self.bots[team_id].act(self.observations[team_id])
        self._pre_step_states = {team_id: copy.deepcopy(self.arena.states[team_id].to_dict()) for team_id in self.arena.agent_ids}
        result = self.arena.step(actions)
        self.step += 1
        feedback = {team_id: self._feedback_payload(team_id, result, period) for team_id in self.arena.agent_ids}
        for team_id, bot in self.bots.items():
            observer = getattr(bot, "observe_feedback", None)
            if callable(observer):
                observer(copy.deepcopy(feedback[team_id]), result.observations[team_id])
        self.history.append({"step": self.step, "period": period, "decision_phase": decision_phase, "actions": copy.deepcopy(actions), "feedback": copy.deepcopy(feedback)})
        self.last_feedback = feedback
        self.observations = dict(result.observations)
        self.pending_actions.clear()
        if result.terminated:
            self.status = "complete"

    def submit(self, token: str, action_bundle: Mapping[str, Any]) -> dict[str, Any]:
        with self.lock:
            player = self.player_for_token(token)
            if player is None:
                raise PermissionError("无效玩家令牌")
            if self.status != "running":
                raise ValueError("比赛当前不能提交决策")
            if self.observations[player.team_id].private_state.get("bankrupt"):
                action_bundle = {"action_type": "hold"}
            if not isinstance(action_bundle, Mapping):
                raise ValueError("action_bundle 必须是 JSON 对象")
            rows = action_bundle.get("actions") if isinstance(action_bundle, Mapping) else None
            if rows is not None and not isinstance(rows, list):
                raise ValueError("actions 必须是动作数组")
            action_rows = self.arena._action_list(action_bundle or {"action_type": "hold"})
            allowed = set(self.allowed_action_types())
            invalid = sorted({str(row.get("action_type") or "") for row in action_rows if str(row.get("action_type") or "") not in allowed})
            if invalid:
                raise ValueError(f"{self.decision_phase_name}阶段不允许动作：{', '.join(invalid)}")
            cached = self.recommendation_cache.get(player.team_id)
            if cached and cached.get("period") == self.observations[player.team_id].period and cached.get("decision_phase") == self.decision_phase_name:
                human_actions = [dict(row) for row in action_rows]
                agent_actions = [dict(row) for row in cached.get("actions") or []]
                human_types = {str(row.get("action_type")) for row in human_actions}
                agent_types = {str(row.get("action_type")) for row in agent_actions}
                union = human_types | agent_types
                overlap = human_types & agent_types
                exact_agent = {json.dumps(row, ensure_ascii=False, sort_keys=True) for row in agent_actions}
                exact_matches = sum(json.dumps(row, ensure_ascii=False, sort_keys=True) in exact_agent for row in human_actions)
                comparison = {
                    "team_id": player.team_id,
                    "period": self.observations[player.team_id].period,
                    "decision_phase": self.decision_phase_name,
                    "action_type_overlap_pct": round(100 * len(overlap) / len(union), 2) if union else 100.0,
                    "exact_action_pct": round(100 * exact_matches / max(len(human_actions), len(agent_actions), 1), 2),
                    "human_action_count": len(human_actions),
                    "agent_action_count": len(agent_actions),
                    "human_only_action_types": sorted(human_types - agent_types),
                    "agent_only_action_types": sorted(agent_types - human_types),
                    "interpretation": "该指标表示人机方案一致度，不等于决策正确率；正确性需结合后续结算或反事实分支评价。",
                }
                self.decision_comparisons.append(copy.deepcopy(comparison))
                self.recommendation_cache[player.team_id]["latest_comparison"] = comparison
            self.pending_actions[player.team_id] = copy.deepcopy(dict(action_bundle or {"action_type": "hold"}))
            waiting = [team_id for team_id in self.human_team_ids if team_id not in self.pending_actions]
            advanced = not waiting
            if advanced:
                self._advance()
            return {"accepted": True, "advanced": advanced, "waiting_for_team_ids": waiting, "step": self.step, "status": self.status}

    def advance_bots(self) -> None:
        with self.lock:
            if self.human_team_ids:
                raise ValueError("含有人类玩家的比赛必须等待玩家提交")
            self._advance()

    def run_bots_to_terminal(self) -> None:
        with self.lock:
            if self.human_team_ids:
                raise ValueError("含有人类玩家的比赛不能自动运行至终局")
            if self.status != "running":
                raise ValueError("比赛当前不能自动运行")
            while self.status == "running":
                self._advance()

    def autopilot_to_terminal(self, token: str, profile: str = "balanced") -> None:
        """Let the owned-enterprise Agent finish a one-human match.

        Every quarter is still a normal environment step.  The Agent cannot
        write referee state; it only submits the same action bundle a human
        could inspect and submit manually.
        """

        with self.lock:
            player = self.player_for_token(token)
            if player is None:
                raise PermissionError("无效玩家令牌")
            if len(self.human_team_ids) != 1:
                raise ValueError("一键 Agent 托管仅适用于单个人类席位；多人赛不能代替其他真实玩家")
            if self.status != "running":
                raise ValueError("比赛当前不能启动 Agent 托管")
            selected_profile = profile if profile in {"conservative", "balanced", "leader"} else "balanced"
            while self.status == "running":
                observation = self.observations[player.team_id]
                if observation.private_state.get("bankrupt"):
                    action_bundle: Mapping[str, Any] = {"action_type": "hold"}
                    explanation: Mapping[str, Any] = {"summary": "企业已破产，后续由环境完成剩余赛程以生成终局复盘。"}
                else:
                    recommendation = self.recommendation(token, selected_profile, "请按当前规则和本企业状态自动完成本季度决策。")
                    action_bundle = recommendation
                    explanation = recommendation.get("decision_explanation") or {}
                self.autopilot_log.append({
                    "period": observation.period,
                    "decision_scope": "annual" if int(observation.private_state.get("quarter", 1)) == 1 else "quarterly_revision",
                    "profile": selected_profile,
                    "action_count": len(self.arena._action_list(action_bundle)),
                    "summary": str(explanation.get("summary") or "保持经营"),
                })
                self.pending_actions[player.team_id] = copy.deepcopy(dict(action_bundle))
                self._advance()

    def finish_after_player_bankruptcy(self, token: str) -> None:
        """Finish a one-human match after that enterprise has gone bankrupt."""

        with self.lock:
            player = self.player_for_token(token)
            if player is None:
                raise PermissionError("无效玩家令牌")
            if len(self.human_team_ids) != 1:
                raise ValueError("多人比赛仍需等待其他真实玩家完成，不能自动代替他们决策")
            if not self.arena.states[player.team_id].bankrupt:
                raise ValueError("企业尚未破产，比赛应继续由玩家决策")
            while self.status == "running":
                self.pending_actions[player.team_id] = {"action_type": "hold"}
                self._advance()

    @property
    def decision_phase_name(self) -> str:
        state = next(iter(self.observations.values())).private_state
        return "年度规划与季度提交" if int(state.get("quarter", 1)) == 1 else "季度修订与提交"

    def allowed_action_types(self) -> tuple[str, ...]:
        return (*FullFinancialDynamics.ACTIONS, "select_order", "auction_bid", "order_portfolio")

    def recommendation(self, token: str, profile: str = "balanced", user_prompt: str = "") -> dict[str, Any]:
        with self.lock:
            player = self.player_for_token(token)
            if player is None:
                raise PermissionError("无效玩家令牌")
            observation = self.observations[player.team_id]
            requested_profile = profile if profile in {"conservative", "balanced", "leader"} else "balanced"
            prompt = user_prompt.strip()[:1000]
            unsafe_terms = ("查看对手私有", "泄露", "保证获单", "保证第一", "无视规则", "一定不破产")
            rejected_terms = [term for term in unsafe_terms if term in prompt]
            effective_profile = requested_profile
            prompt_status = "未提供反馈"
            prompt_response = "按所选风险风格生成初始建议。"
            state = observation.private_state
            cash = float(state.get("cash_wan") or 0)
            equity = float(state.get("owner_equity_wan") or 0)
            debt = float(state.get("debt_wan") or 0)
            outstanding = [row for row in state.get("assigned_orders") or [] if row.get("status") not in {"已交", "违约"}]
            defaults = len(state.get("defaulted_orders") or [])
            ready_lines = sum(row.get("status") == "ready" for row in state.get("production_lines") or [])
            visible_orders = len(observation.public_state.get("available_orders") or [])
            initial_cash = float((self.rules.get("parameters") or {}).get("initial_cash_wan") or 0)
            if cash < max(80.0, initial_cash * 0.18) or equity <= 0 or debt > max(equity, 1) * 1.5 or defaults:
                suggested_profile = "conservative"
                risk_reason = "现金、权益、负债或违约指标已经进入压力区，应先确保存续和履约。"
            elif cash > initial_cash * 0.65 and ready_lines >= 2 and not outstanding:
                suggested_profile = "leader"
                risk_reason = "现金缓冲和就绪产能较充足，可在硬约束内考虑增长，但不能连续无上限扩张。"
            else:
                suggested_profile = "balanced"
                risk_reason = "当前更适合在获单收益、能力建设和现金安全垫之间保持平衡。"
            profile_names = {"conservative": "稳健", "balanced": "平衡", "leader": "增长"}
            state_answer = (
                f"当前现金 {cash:.1f} 万元、权益 {equity:.1f} 万元、负债 {debt:.1f} 万元，"
                f"有 {len(outstanding)} 个待履约订单、{ready_lines} 条就绪产线，本阶段可见 {visible_orders} 条公开订单。"
                f"建议采用{profile_names[suggested_profile]}风险档位：{risk_reason}"
            )
            if prompt:
                prompt_status = "已采纳"
                if rejected_terms:
                    prompt_status = "部分拒绝"
                    prompt_response = f"无法满足“{'、'.join(rejected_terms)}”这类不可验证或越权要求；仍按合法可见信息生成方案。"
                elif any(term in prompt for term in ("保守", "现金", "安全", "少负债", "降低风险")):
                    effective_profile = "conservative"
                    prompt_response = "已将用户反馈解释为提高现金安全垫、收缩可选投入。"
                elif any(term in prompt for term in ("增长", "扩张", "提高获单", "增加产能", "进取")):
                    effective_profile = "leader"
                    prompt_response = f"已将反馈解释为提高能力覆盖与产能投入。{state_answer}若连续扩张导致现金低于安全垫，系统会移除相关动作。"
                elif any(term in prompt for term in ("怎么样", "状况", "状态", "分析", "风险", "多少", "为什么", "建议", "该怎么", "如何")):
                    effective_profile = suggested_profile
                    prompt_response = state_answer
                else:
                    prompt_response = f"已结合你的问题审阅本企业状态。{state_answer}"
            else:
                effective_profile = suggested_profile
                prompt_response = f"系统建议本轮采用{profile_names[suggested_profile]}风险档位。{risk_reason}"
            policy = CollaborativeEnterprisePolicy(
                player.team_id,
                self.seed + self.step,
                rules=self.rules,
                profile=effective_profile,
                allow_prospective_new_cell=True,
            )
            recommendation = copy.deepcopy(dict(policy.act(observation)))
            audit = (recommendation.get("policy_metadata") or {}).get("planning_audit") or {}
            specialist_names = {
                "treasury_agent": "资金模块", "capability_agent": "资格模块", "capacity_agent": "产能模块",
                "fulfillment_agent": "供应履约模块", "order_agent": "订单组合模块", "order_portfolio_agent": "订单组合模块", "risk_critic_agent": "风险审查模块",
            }
            specialist_reasons = {
                "treasury_agent": "覆盖本季度结算、到期义务和经营组合所需资金，同时保留现金安全垫。",
                "capability_agent": "根据当前产品、市场、认证和公开需求，安排能扩大可接订单范围的资格建设。",
                "capacity_agent": "根据在手订单、可执行批次和现有厂房产线，补足未来履约能力。",
                "fulfillment_agent": "按交期、库存、BOM、原料到货和产线占用联合安排采购、生产与交付。",
                "order_agent": "在资格、边际收益、交期、广告和容量约束下选择主订单及回退候选。",
                "order_portfolio_agent": "在资格、边际收益、交期、广告和容量约束下选择主订单及回退候选。",
            }
            reasons = []
            for proposal in audit.get("specialist_proposals") or []:
                evidence = proposal.get("evidence") or {}
                specialist_id = str(proposal.get("specialist_id"))
                reasons.append({
                    "module": specialist_names.get(specialist_id, "专业决策模块"),
                    "reason": specialist_reasons.get(specialist_id, "结合本企业当前可见状态提出候选动作，并交由风险模块联合审查。"),
                    "evidence_summary": _evidence_summary(evidence),
                    "action_count": len(proposal.get("actions") or []),
                })
            risk = audit.get("risk_review") or {}
            recommendation["decision_explanation"] = {
                "summary": f"{len(recommendation.get('actions') or [])} 个动作由资金、资格、产能、履约、订单与风险模块联合形成。",
                "reasons": reasons,
                "risk_check": f"预演现金 {float(risk.get('projected_cash_wan') or 0):.1f} 万元，预演权益 {float(risk.get('projected_equity_wan') or 0):.1f} 万元；移除 {len(risk.get('removed_actions') or [])} 个高风险或不可执行动作。",
                "suggested_profile": suggested_profile,
                "suggested_profile_label": profile_names[suggested_profile],
                "warnings": [
                    "不要把预计获单当成实际获单；本季度竞单结果要进入下一季度滚动修订。",
                    "不要连续投入研发、广告和资产而忽略到期贷款、管理费、原料与交付现金。",
                    "不要申领超过资格、库存和交期前可完成产能的订单组合。",
                ],
                "formulas": [
                    "可用现金缓冲 = 当前现金 + 可获得融资 + 可贴现回款 - 近期刚性支出",
                    "预计订单贡献 = 订单收入 - 直接材料成本 - 生产成本 - 广告或竞价成本 - 增量融资成本 - 预期违约损失",
                    "可交付数量 = 当前成品库存 + 交期前可完成批次 - 已承诺订单需求",
                    "预演权益 = 当前权益 + 预计收入 - 预计费用 - 利息 - 折旧 - 税费 - 违约损失",
                ],
                "limitations": "建议仅使用本企业私有状态、公开订单和规则允许的信息；最终获单、违约和破产由环境结算。",
            }
            decision_scope = "annual" if int(state.get("quarter", 1)) == 1 else "quarterly_revision"
            scope_label = "年度大规划" if decision_scope == "annual" else "季度滚动修订"
            future_orders = observation.public_state.get("global_orders") or []
            claimable_orders = observation.public_state.get("available_orders") or []
            recommendation["decision_explanation"]["decision_scope"] = decision_scope
            recommendation["decision_explanation"]["decision_scope_label"] = scope_label
            recommendation["decision_explanation"]["decision_basis"] = [
                f"当前节点：{observation.period} · {scope_label}",
                f"赛前可见全局订单 {len(future_orders)} 条，本季度进入申领窗口 {len(claimable_orders)} 条",
                f"当前现金 {cash:.1f} 万元、负债 {debt:.1f} 万元、待履约订单 {len(outstanding)} 个、就绪产线 {ready_lines} 条",
                "所有动作先经过资格、厂房数量、产线容量、现金安全和交期可执行性检查，再由环境统一结算",
            ]
            alternative_copy: dict[str, Mapping[str, Any]] = {effective_profile: recommendation}
            for candidate_profile in ("conservative", "balanced", "leader"):
                if candidate_profile not in alternative_copy:
                    candidate_policy = CollaborativeEnterprisePolicy(
                        player.team_id,
                        self.seed + self.step,
                        rules=self.rules,
                        profile=candidate_profile,
                        allow_prospective_new_cell=True,
                    )
                    alternative_copy[candidate_profile] = copy.deepcopy(dict(candidate_policy.act(observation)))
            alternative_text = {
                "conservative": {
                    "label": "稳健方案", "logic": "先覆盖刚性支出、到期义务和在手订单，只建设最必要的资格与产能。",
                    "benefits": ["破产与违约风险最低", "保留更高现金缓冲", "便于根据下一季度反馈修订"],
                    "risks": ["可能错过高收益订单窗口", "长期能力和发展速度偏慢"],
                },
                "balanced": {
                    "label": "平衡方案", "logic": "在现金安全线之上同步推进核心资格、可执行产能和利润较好的订单组合。",
                    "benefits": ["兼顾存续、获单和能力建设", "适合信息不完全时的滚动决策", "对对手变化更鲁棒"],
                    "risks": ["收益上限低于激进扩张", "需要每季度持续校正采购和产能"],
                },
                "leader": {
                    "label": "增长方案", "logic": "利用现金与融资提前覆盖更多产品市场和产能，争取更大的订单组合。",
                    "benefits": ["潜在订单覆盖和收入上限最高", "较早形成规模与资格优势"],
                    "risks": ["固定资产、研发和利息占用高", "需求或竞单不及预期时最容易出现现金链压力"],
                },
            }
            alternatives = []
            for candidate_profile in ("conservative", "balanced", "leader"):
                candidate = alternative_copy[candidate_profile]
                alternatives.append({
                    "profile": candidate_profile,
                    **alternative_text[candidate_profile],
                    "action_count": len(candidate.get("actions") or []),
                    "actions": copy.deepcopy(candidate.get("actions") or []),
                    "selected": candidate_profile == effective_profile,
                })
            recommendation["decision_explanation"]["alternatives"] = alternatives
            if decision_scope == "annual":
                self.annual_plans.setdefault(player.team_id, {})[int(state.get("year", 1))] = {
                    "period": observation.period,
                    "profile": effective_profile,
                    "basis": copy.deepcopy(recommendation["decision_explanation"]["decision_basis"]),
                    "alternatives": copy.deepcopy(alternatives),
                }
            recommendation["user_feedback_review"] = {
                "status": prompt_status, "original_profile": requested_profile, "effective_profile": effective_profile,
                "response": prompt_response, "prompt": prompt,
            }
            self.recommendation_cache[player.team_id] = {
                "period": observation.period, "decision_phase": self.decision_phase_name,
                "actions": copy.deepcopy(recommendation.get("actions") or []), "explanation": copy.deepcopy(recommendation["decision_explanation"]),
            }
            self.recommendation_revisions.append({
                "revision_id": f"REV-{len(self.recommendation_revisions) + 1:04d}", "team_id": player.team_id,
                "period": observation.period, "decision_phase": self.decision_phase_name,
                "user_feedback_review": copy.deepcopy(recommendation["user_feedback_review"]),
                "actions": copy.deepcopy(recommendation.get("actions") or []),
                "decision_explanation": copy.deepcopy(recommendation["decision_explanation"]),
            })
            return recommendation

    def _current_score(self, team_id: str) -> dict[str, Any]:
        state = self.arena.states[team_id]
        assets = {
            "markets": state.markets,
            "products": state.products,
            "iso": state.iso,
            "purchased_factories": [row["name"] for row in state.factories if row.get("ownership") == "purchased"],
            "completed_lines": [row["line_type"] for row in state.production_lines],
        }
        potential = development_potential(assets, self.rules)
        participant_type = "human" if team_id in self.human_team_ids else "agent"
        human_player = next((row for row in self.players.values() if row.team_id == team_id), None)
        position = list(self.arena.agent_ids).index(team_id) + 1
        if human_player is not None:
            display_name = f"{human_player.player_name}（人类）"
        elif participant_type == "human":
            display_name = f"人类席位 {position:02d}"
        else:
            display_name = f"Agent {position:02d}"
        bot = self.bots.get(team_id)
        if self.bot_policy in {"mixed", "late_failure"}:
            strategy_class = str(getattr(bot, "strategy_class", strategy_class_for_team(team_id, len(self.arena.agent_ids))))
            strategy_label = STRATEGY_CLASS_LABELS.get(strategy_class, "异质经营策略")
        elif self.bot_policy == "collaborative":
            strategy_label = {"leader": "增长协同型", "balanced": "平衡协同型", "conservative": "稳健协同型"}.get(str(getattr(bot, "profile", "balanced")), "协同决策型")
        elif self.bot_policy == "baseline":
            strategy_label = {"safe": "安全基线型", "balanced": "平衡基线型", "growth": "增长基线型"}.get(str(getattr(bot, "strategy", "safe")), "保守基线型")
        else:
            strategy_label = "随机启发式型"
        return {
            "team_id": team_id,
            "display_name": display_name,
            "participant_type": participant_type,
            "strategy_label": "人工决策" if participant_type == "human" else strategy_label,
            "bankrupt": state.bankrupt,
            "bankruptcy_period": state.bankruptcy_period,
            "development_potential": potential,
            "score": 0.0 if state.bankrupt else ranking_score(state.owner_equity_wan, potential, self.rules),
        }

    def snapshot(self, token: str | None = None) -> dict[str, Any]:
        with self.lock:
            player = self.player_for_token(token)
            team_status = [self._current_score(team_id) for team_id in self.arena.agent_ids]
            if not self.human_team_ids:
                match_mode = "纯 Agent 赛"
            elif len(self.human_team_ids) == len(self.arena.agent_ids):
                match_mode = "纯用户赛"
            else:
                match_mode = "人机对抗"
            payload: dict[str, Any] = {
                "platform_version": WEB_PLATFORM_VERSION,
                "match_id": self.match_id,
                "name": self.name,
                "display_name": f"{match_mode} · {self.name}",
                "match_mode": match_mode,
                "seed": self.seed,
                "status": self.status,
                "step": self.step,
                "period": next(iter(self.observations.values())).period,
                "decision_phase": str(next(iter(self.observations.values())).public_state.get("decision_phase") or "operating"),
                "decision_scope": "annual" if int(next(iter(self.observations.values())).private_state.get("quarter", 1)) == 1 else "quarterly_revision",
                "decision_label": self.decision_phase_name,
                "team_count": len(self.arena.agent_ids),
                "human_slots": len(self.human_team_ids),
                "joined_players": [player_row.public_dict() for player_row in self.players.values()],
                "open_human_slots": len(self.unclaimed_human_teams),
                "bot_policy": self.bot_policy,
                "allowed_action_types": list(self.allowed_action_types()),
                "information_purchase_enabled": bool((self.rules.get("financial_rules", {}).get("information_purchase") or {}).get("enabled")),
                "pending_team_ids": sorted(self.pending_actions),
                "team_status": team_status,
                "public_order_results": copy.deepcopy(self.arena._public_order_results()),
                "rule_notice": _rule_notice(self.rules, match_name=self.name),
                "decision_comparisons": copy.deepcopy([row for row in self.decision_comparisons if player is not None and row.get("team_id") == player.team_id]),
                "rules_catalog": {
                    "products": copy.deepcopy(self.rules.get("parameters", {}).get("products", {})),
                    "markets": copy.deepcopy(self.rules.get("parameters", {}).get("markets", {})),
                    "iso": copy.deepcopy(self.rules.get("parameters", {}).get("iso", {})),
                    "factories": copy.deepcopy(self.rules.get("parameters", {}).get("factories", {})),
                    "production_lines": copy.deepcopy(self.rules.get("parameters", {}).get("production_lines", {})),
                    "materials": copy.deepcopy(self.rules.get("parameters", {}).get("materials", {})),
                },
            }
            if player is not None:
                observation = self.observations[player.team_id]
                own = next(row for row in team_status if row["team_id"] == player.team_id)
                ranked = sorted((row for row in team_status if not row["bankrupt"]), key=lambda row: (-float(row["score"]), row["team_id"]))
                initial_config = self.rules.get("initial_state") or {}
                initial_equity = float(initial_config.get("owner_equity_wan") or (self.rules.get("parameters") or {}).get("initial_cash_wan") or 0)
                initial_assets = {
                    "markets": initial_config.get("markets") or ["本地"],
                    "products": initial_config.get("products") or ["P1"],
                    "iso": initial_config.get("iso") or [],
                    "purchased_factories": [row.get("name") for row in initial_config.get("factories") or [] if row.get("ownership") == "purchased"],
                    "completed_lines": [row.get("line_type") for row in initial_config.get("production_lines") or [] if row.get("status", "ready") == "ready"],
                }
                initial_score = ranking_score(initial_equity, development_potential(initial_assets, self.rules), self.rules)
                cash = float(observation.private_state.get("cash_wan") or 0)
                equity = float(observation.private_state.get("owner_equity_wan") or 0)
                safety_floor = max(80.0, initial_equity * 0.18)
                payload["player"] = player.public_dict()
                payload["observation"] = _safe_observation(observation)
                payload["agent_evaluation"] = {
                    "initial_equity_wan": initial_equity,
                    "equity_change_wan": equity - initial_equity,
                    "initial_score": initial_score,
                    "score_change": float(own["score"]) - initial_score,
                    "current_rank": next((index for index, row in enumerate(ranked, 1) if row["team_id"] == player.team_id), None),
                    "ranked_team_count": len(ranked),
                    "cash_safety_floor_wan": safety_floor,
                    "cash_status": "压力" if cash < safety_floor else "可控" if cash < safety_floor * 2 else "充足",
                    "hard_constraint_status": "通过" if not observation.private_state.get("bankrupt") else "失败",
                    "decision_count": sum(row.get("team_id") == player.team_id for row in self.recommendation_revisions),
                    "interpretation": "这里是 Agent 可靠性评估，不是比赛官方盘面。权益、过程评分和一致度仅用于审计建议，不能替代环境终局结果。",
                }
                payload["agent_decision_history"] = copy.deepcopy([row for row in self.recommendation_revisions if row.get("team_id") == player.team_id])
                payload["annual_plans"] = copy.deepcopy(self.annual_plans.get(player.team_id) or {})
                payload["autopilot_log"] = copy.deepcopy(self.autopilot_log)
                payload["submitted_this_period"] = player.team_id in self.pending_actions
                payload["last_feedback"] = copy.deepcopy(self.last_feedback.get(player.team_id))
                payload["latest_decision_comparison"] = copy.deepcopy((self.recommendation_cache.get(player.team_id) or {}).get("latest_comparison"))
                payload["recommendation_revision_count"] = sum(row.get("team_id") == player.team_id for row in self.recommendation_revisions)
            if self.status == "complete":
                payload["final_results"] = self.arena.final_results()
                if player is not None:
                    final_results = payload["final_results"]
                    final_rank = next((row for row in final_results.get("ranking") or [] if row.get("team_id") == player.team_id), None)
                    final_state = self.arena.states[player.team_id]
                    payload["final_review"] = {
                        "outcome": "破产出局" if final_state.bankrupt else (f"第 {final_rank['rank']} 名" if final_rank else "未进入有效排名"),
                        "summary": f"终局权益 {final_state.owner_equity_wan:.1f} 万元，累计交付 {len(final_state.delivered_orders)} 单，累计违约 {len(final_state.defaulted_orders)} 单。",
                        "suggestions": copy.deepcopy((self.last_feedback.get(player.team_id) or {}).get("review_suggestions") or ["结合完整轨迹复查资金、能力建设、获单和履约之间的因果链。"]),
                    }
            return payload

    def export_record(self) -> dict[str, Any]:
        """Export the complete auditable match after terminal settlement."""

        with self.lock:
            if self.status != "complete":
                raise ValueError("比赛结束后才能导出完整记录")
            return {
                "format_version": "goai_clickable_match_export_v1.0",
                "platform_version": WEB_PLATFORM_VERSION,
                "match_id": self.match_id,
                "name": self.name,
                "seed": self.seed,
                "rules": copy.deepcopy(self.rules),
                "global_orders": copy.deepcopy(self.orders),
                "quarter_history": copy.deepcopy(self.history),
                "decision_phase_history": copy.deepcopy(self.history),
                "annual_plans": copy.deepcopy(self.annual_plans),
                "autopilot_log": copy.deepcopy(self.autopilot_log),
                "order_allocation_log": copy.deepcopy(self.arena.order_log),
                "final_states": [copy.deepcopy(self.arena.states[team_id].to_dict()) for team_id in self.arena.agent_ids],
                "final_results": self.arena.final_results(),
                "provenance": "simulated_clickable_competition",
            }

    def export_xlsx_archive(self) -> bytes:
        """Export the terminal match in the same visible workbook family as a competition."""

        with self.lock:
            if self.status != "complete":
                raise ValueError("比赛结束后才能导出 XLSX 比赛资料")
            return build_competition_xlsx_archive(rules=self.rules, orders=self.orders, arena=self.arena)


class CompetitionService:
    def __init__(self, match_dir: Path = DEFAULT_MATCH_DIR) -> None:
        self.match_dir = Path(match_dir)
        self.base_rules = _read_json(self.match_dir / "rules.json")
        self.sessions: dict[str, CompetitionSession] = {}
        self.lock = threading.RLock()
        self.match_sequence = 0

    def catalog(self) -> dict[str, Any]:
        return {
            "platform_version": WEB_PLATFORM_VERSION,
            "team_count": {"minimum": 2, "maximum": 27, "default": 6},
            "human_slots": {"minimum": 0, "maximum": 27, "default": 1},
            "bot_policies": [
                {"id": "mixed", "name": "异质经营对手"},
                {"id": "late_failure", "name": "晚期扩张压力对手"},
                {"id": "collaborative", "name": "协同 Agent 对手"},
                {"id": "baseline", "name": "保守基线对手"},
                {"id": "heuristic", "name": "启发式对手"},
            ],
            "rule_pack": "综合企业经营沙盘规则范围",
            "periods": 20,
            "simulated_orders_per_match": 800,
        }

    def _bot(self, policy_id: str, team_id: str, seed: int, rules: Mapping[str, Any]) -> Any:
        if policy_id == "collaborative":
            index = list((rules.get("participants") or {}).get("team_ids") or []).index(team_id)
            profile = ("leader", "balanced", "conservative")[index % 3]
            return CollaborativeEnterprisePolicy(team_id, seed, rules=rules, profile=profile, allow_prospective_new_cell=True)
        if policy_id == "baseline":
            return FixedXABaselinePolicy(team_id, seed, rules=rules)
        if policy_id == "heuristic":
            return SeededHeuristicPolicy(team_id, seed, rules=rules, complexity_profile="large")
        strategy = strategy_class_for_team(team_id, len((rules.get("participants") or {}).get("team_ids") or []))
        if strategy == "aggressive_failed":
            return XALateAggressivePopulationPolicy(team_id, seed, rules=rules)
        profile = {"leader_growth": "leader", "balanced_expansion": "balanced", "conservative_survivor": "conservative"}[strategy]
        bot = CollaborativeEnterprisePolicy(team_id, seed, rules=rules, profile=profile, allow_prospective_new_cell=True)
        bot.strategy_class = strategy
        return bot

    def create(self, config: Mapping[str, Any]) -> tuple[CompetitionSession, PlayerSeat | None]:
        team_count = int(config.get("team_count", 6))
        human_slots = int(config.get("human_slots", 1))
        seed = int(config.get("seed", 20260811))
        if not 2 <= team_count <= 27:
            raise ValueError("企业数量必须在 2 到 27 之间")
        if not 0 <= human_slots <= team_count:
            raise ValueError("人类席位必须在 0 到企业数量之间")
        bot_policy = str(config.get("bot_policy", "mixed"))
        if bot_policy not in {"mixed", "late_failure", "collaborative", "baseline", "heuristic"}:
            raise ValueError("未知 Bot 策略")
        with self.lock:
            self.match_sequence += 1
            match_id = f"SIM-{self.match_sequence:04d}"
        rules = _generated_rule_pack(self.base_rules, match_id=match_id, team_count=team_count, seed=seed, source_rule_path=(self.match_dir / "rules.json").as_posix(), first_year_has_orders=False)
        order_years = (2, 3, 4, 5)
        orders = generate_global_orders(
            rules,
            seed=seed + 1,
            orders_per_year=800 // len(order_years),
            years=order_years,
            auction_ratio=0.10,
            complexity="large",
        )
        for order in orders:
            release_index = int(order.get("release_period_index", 0))
            claim_index = max(0, release_index - 1)
            order["claim_period_index"] = claim_index
            order["claim_period"] = f"Y{claim_index // 4 + 1}Q{claim_index % 4 + 1}"
            order["planning_lead_quarters"] = 1
        team_ids = tuple((rules.get("participants") or {}).get("team_ids") or [])
        arena = FullCompetitionArena(
            FullFinancialDynamics(rules), team_ids, orders,
            max_periods=20, stop_when_all_bankrupt=False,
            post_allocation_phase=False,
            full_order_catalog_visible=True,
            order_claim_lead_quarters=1,
        )
        observations = dict(arena.reset(seed=seed))
        human_team_ids = team_ids[:human_slots]
        bots = {team_id: self._bot(bot_policy, team_id, seed, rules) for team_id in team_ids if team_id not in human_team_ids}
        session = CompetitionSession(match_id, str(config.get("name") or f"企业经营模拟赛 {self.match_sequence:04d}"), seed, rules, orders, arena, observations, human_team_ids, bot_policy, bots)
        creator = session.join(str(config.get("creator_name") or "创建者")) if human_slots else None
        with self.lock:
            self.sessions[match_id] = session
        return session, creator

    def get(self, match_id: str) -> CompetitionSession:
        try:
            return self.sessions[match_id]
        except KeyError as exc:
            raise KeyError("比赛不存在或服务器已经重启") from exc


class EnterpriseDecisionRequestHandler(BaseHTTPRequestHandler):
    service: CompetitionService

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _json(self, status: int, payload: Mapping[str, Any]) -> None:
        data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _error(self, status: int, message: str) -> None:
        self._json(status, {"error": message, "status": status})

    def _binary(self, status: int, data: bytes, *, content_type: str, filename: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Content-Disposition", f"attachment; filename=competition.xlsx.zip; filename*=UTF-8''{quote(filename)}")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length <= 0:
            return {}
        value = json.loads(self.rfile.read(length).decode("utf-8"))
        if not isinstance(value, dict):
            raise ValueError("请求正文必须是 JSON 对象")
        return value

    def _token(self, query: Mapping[str, Sequence[str]], body: Mapping[str, Any] | None = None) -> str | None:
        authorization = self.headers.get("Authorization", "")
        if authorization.startswith("Bearer "):
            return authorization[7:]
        if body and body.get("token"):
            return str(body["token"])
        return next(iter(query.get("token", [])), None)

    def _static(self, path: str) -> None:
        relative = "index.html" if path in {"", "/"} else path.lstrip("/")
        if relative not in {"index.html", "app.js", "styles.css"}:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        target = STATIC_DIR / relative
        data = target.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", f"{mimetypes.guess_type(target.name)[0] or 'application/octet-stream'}; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        parts = [part for part in parsed.path.split("/") if part]
        query = parse_qs(parsed.query)
        try:
            if parsed.path == "/api/health":
                self._json(HTTPStatus.OK, {"status": "ok", "version": WEB_PLATFORM_VERSION})
            elif parsed.path == "/api/catalog":
                self._json(HTTPStatus.OK, self.service.catalog())
            elif len(parts) == 3 and parts[:2] == ["api", "matches"]:
                session = self.service.get(parts[2])
                self._json(HTTPStatus.OK, session.snapshot(self._token(query)))
            elif len(parts) == 4 and parts[:2] == ["api", "matches"] and parts[3] == "export":
                session = self.service.get(parts[2])
                self._json(HTTPStatus.OK, session.export_record())
            elif len(parts) == 4 and parts[:2] == ["api", "matches"] and parts[3] == "export-xlsx":
                session = self.service.get(parts[2])
                self._binary(
                    HTTPStatus.OK,
                    session.export_xlsx_archive(),
                    content_type="application/zip",
                    filename=f"{session.match_id}比赛完整资料.zip",
                )
            elif not parsed.path.startswith("/api/"):
                self._static(parsed.path)
            else:
                self._error(HTTPStatus.NOT_FOUND, "接口不存在")
        except KeyError as exc:
            self._error(HTTPStatus.NOT_FOUND, str(exc))
        except PermissionError as exc:
            self._error(HTTPStatus.FORBIDDEN, str(exc))
        except (ValueError, json.JSONDecodeError) as exc:
            self._error(HTTPStatus.BAD_REQUEST, str(exc))

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        parts = [part for part in parsed.path.split("/") if part]
        query = parse_qs(parsed.query)
        try:
            body = self._body()
            if parts == ["api", "matches"]:
                session, creator = self.service.create(body)
                payload = session.snapshot(creator.token if creator else None)
                payload["join_code"] = session.match_id
                if creator:
                    payload["credentials"] = {"player_id": creator.player_id, "team_id": creator.team_id, "token": creator.token}
                self._json(HTTPStatus.CREATED, payload)
                return
            if len(parts) != 4 or parts[:2] != ["api", "matches"]:
                self._error(HTTPStatus.NOT_FOUND, "接口不存在")
                return
            session = self.service.get(parts[2])
            operation = parts[3]
            token = self._token(query, body)
            if operation == "join":
                player = session.join(str(body.get("player_name") or "玩家"))
                self._json(HTTPStatus.CREATED, {"match": session.snapshot(player.token), "credentials": {"player_id": player.player_id, "team_id": player.team_id, "token": player.token}})
            elif operation == "start":
                session.start()
                self._json(HTTPStatus.OK, session.snapshot(token))
            elif operation == "submit":
                if not token:
                    raise PermissionError("缺少玩家令牌")
                result = session.submit(token, body.get("action_bundle") or {"action_type": "hold"})
                self._json(HTTPStatus.OK, {"submission": result, "match": session.snapshot(token)})
            elif operation == "recommend":
                if not token:
                    raise PermissionError("缺少玩家令牌")
                self._json(HTTPStatus.OK, {"recommendation": session.recommendation(token, str(body.get("profile") or "balanced"), str(body.get("user_prompt") or ""))})
            elif operation == "advance":
                session.advance_bots()
                self._json(HTTPStatus.OK, session.snapshot(token))
            elif operation == "run":
                session.run_bots_to_terminal()
                self._json(HTTPStatus.OK, session.snapshot(token))
            elif operation == "autopilot":
                if not token:
                    raise PermissionError("缺少玩家令牌")
                session.autopilot_to_terminal(token, str(body.get("profile") or "balanced"))
                self._json(HTTPStatus.OK, session.snapshot(token))
            elif operation == "finish-after-bankruptcy":
                if not token:
                    raise PermissionError("缺少玩家令牌")
                session.finish_after_player_bankruptcy(token)
                self._json(HTTPStatus.OK, session.snapshot(token))
            else:
                self._error(HTTPStatus.NOT_FOUND, "接口不存在")
        except KeyError as exc:
            self._error(HTTPStatus.NOT_FOUND, str(exc))
        except PermissionError as exc:
            self._error(HTTPStatus.FORBIDDEN, str(exc))
        except (ValueError, json.JSONDecodeError) as exc:
            self._error(HTTPStatus.BAD_REQUEST, str(exc))


def make_server(host: str = "127.0.0.1", port: int = 8765, *, match_dir: Path = DEFAULT_MATCH_DIR) -> ThreadingHTTPServer:
    service = CompetitionService(match_dir)
    handler = type("ConfiguredEnterpriseDecisionRequestHandler", (EnterpriseDecisionRequestHandler,), {"service": service})
    return ThreadingHTTPServer((host, port), handler)


def serve(host: str = "127.0.0.1", port: int = 8765, *, match_dir: Path = DEFAULT_MATCH_DIR) -> None:
    server = make_server(host, port, match_dir=match_dir)
    print(f"StratPilot比赛平台已启动：http://{host}:{server.server_port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
