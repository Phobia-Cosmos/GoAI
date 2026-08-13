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
from urllib.parse import parse_qs, urlparse

from .collaborative_agent import CollaborativeEnterprisePolicy
from .decision_system import AgentObservation
from .full_sandbox import (
    FixedXABaselinePolicy,
    FullCompetitionArena,
    FullFinancialDynamics,
    SeededHeuristicPolicy,
    build_fixed_xa_rule_pack,
    generate_xa_empirical_global_orders,
)
from .global_rules import development_potential, ranking_score
from .xa_population import XALateAggressivePopulationPolicy, XARealisticPopulationPolicy, strategy_class_for_team


WEB_PLATFORM_VERSION = "goai_clickable_competition_v0.5_guided_human_agent"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MATCH_DIR = PROJECT_ROOT / "data" / "processed" / "v2" / "matches" / "LX_XA"
STATIC_DIR = Path(__file__).resolve().parent / "web_static"


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


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
        if decision_phase == "post_allocation":
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

    @property
    def decision_phase_name(self) -> str:
        phase = str(next(iter(self.observations.values())).public_state.get("decision_phase") or "operating")
        return "获单后履约" if phase == "post_allocation" else "经营与申领"

    def allowed_action_types(self) -> tuple[str, ...]:
        phase = str(next(iter(self.observations.values())).public_state.get("decision_phase") or "operating")
        if phase == "post_allocation":
            return (
                "hold", "short_loan_borrow", "long_loan_borrow", "receivable_discount",
                "rent_workshop", "buy_workshop", "buy_product_line", "convert_product_line",
                "material_order", "emergency_purchase", "emergency_product_purchase",
                "production", "order_delivery",
            )
        return (*FullFinancialDynamics.ACTIONS, "select_order", "auction_bid", "order_portfolio")

    def recommendation(self, token: str, profile: str = "balanced") -> dict[str, Any]:
        with self.lock:
            player = self.player_for_token(token)
            if player is None:
                raise PermissionError("无效玩家令牌")
            observation = self.observations[player.team_id]
            policy = CollaborativeEnterprisePolicy(
                player.team_id,
                self.seed + self.step,
                rules=self.rules,
                profile=profile,
                allow_prospective_new_cell=True,
            )
            return copy.deepcopy(dict(policy.act(observation)))

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
        strategy_labels = {
            "mixed": "异质经营策略",
            "late_failure": "扩张压力策略",
            "collaborative": "协同决策策略",
            "baseline": "保守基线策略",
            "heuristic": "启发式策略",
        }
        return {
            "team_id": team_id,
            "display_name": display_name,
            "participant_type": participant_type,
            "strategy_label": "人工决策" if participant_type == "human" else strategy_labels.get(self.bot_policy, "Agent 策略"),
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
                payload["player"] = player.public_dict()
                payload["observation"] = _safe_observation(observation)
                payload["submitted_this_period"] = player.team_id in self.pending_actions
                payload["last_feedback"] = copy.deepcopy(self.last_feedback.get(player.team_id))
            if self.status == "complete":
                payload["final_results"] = self.arena.final_results()
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
                "quarter_history": copy.deepcopy([row for row in self.history if row.get("decision_phase") == "post_allocation"]),
                "decision_phase_history": copy.deepcopy(self.history),
                "order_allocation_log": copy.deepcopy(self.arena.order_log),
                "final_states": [copy.deepcopy(self.arena.states[team_id].to_dict()) for team_id in self.arena.agent_ids],
                "final_results": self.arena.final_results(),
                "provenance": "simulated_clickable_competition",
            }


class CompetitionService:
    def __init__(self, match_dir: Path = DEFAULT_MATCH_DIR) -> None:
        self.match_dir = Path(match_dir)
        self.base_rules = _read_json(self.match_dir / "rules.json")
        self.order_templates = _read_jsonl(self.match_dir / "global_orders.jsonl")
        self.sessions: dict[str, CompetitionSession] = {}
        self.lock = threading.RLock()

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
            "rule_pack": self.base_rules.get("rule_pack_id", "LX_XA"),
            "periods": 20,
            "empirical_order_count": len(self.order_templates),
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
        if policy_id == "late_failure":
            if strategy == "aggressive_failed":
                return XALateAggressivePopulationPolicy(team_id, seed, rules=rules)
            profile = {"leader_growth": "leader", "balanced_expansion": "balanced", "conservative_survivor": "conservative"}[strategy]
            return CollaborativeEnterprisePolicy(team_id, seed, rules=rules, profile=profile, allow_prospective_new_cell=True)
        return XARealisticPopulationPolicy(team_id, seed, rules=rules, strategy_class=strategy)

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
        suffix = uuid.uuid4().hex[:8].upper()
        match_id = f"WEB_XA_{seed}_{suffix}"
        rules = build_fixed_xa_rule_pack(self.base_rules, match_id=match_id, team_count=team_count, seed=seed, source_rule_path=(self.match_dir / "rules.json").as_posix())
        rules["generation"]["mode"] = "clickable_human_agent_competition"
        orders = generate_xa_empirical_global_orders(rules, self.order_templates, seed=seed + 1, price_jitter=0.03, due_grace_quarters=2)
        team_ids = tuple((rules.get("participants") or {}).get("team_ids") or [])
        arena = FullCompetitionArena(FullFinancialDynamics(rules), team_ids, orders, max_periods=20, stop_when_all_bankrupt=False, post_allocation_phase=True)
        observations = dict(arena.reset(seed=seed))
        human_team_ids = team_ids[:human_slots]
        bots = {team_id: self._bot(bot_policy, team_id, seed, rules) for team_id in team_ids if team_id not in human_team_ids}
        session = CompetitionSession(match_id, str(config.get("name") or f"XA 点击比赛 {suffix}"), seed, rules, orders, arena, observations, human_team_ids, bot_policy, bots)
        creator = session.join(str(config.get("creator_name") or "创建者")) if human_slots else None
        with self.lock:
            self.sessions[match_id] = session
        return session, creator

    def get(self, match_id: str) -> CompetitionSession:
        try:
            return self.sessions[match_id]
        except KeyError as exc:
            raise KeyError("比赛不存在或服务器已经重启") from exc


class GoAIRequestHandler(BaseHTTPRequestHandler):
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
                self._json(HTTPStatus.OK, {"recommendation": session.recommendation(token, str(body.get("profile") or "balanced"))})
            elif operation == "advance":
                session.advance_bots()
                self._json(HTTPStatus.OK, session.snapshot(token))
            elif operation == "run":
                session.run_bots_to_terminal()
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
    handler = type("ConfiguredGoAIRequestHandler", (GoAIRequestHandler,), {"service": service})
    return ThreadingHTTPServer((host, port), handler)


def serve(host: str = "127.0.0.1", port: int = 8765, *, match_dir: Path = DEFAULT_MATCH_DIR) -> None:
    server = make_server(host, port, match_dir=match_dir)
    print(f"GoAI 点击比赛平台已启动：http://{host}:{server.server_port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
