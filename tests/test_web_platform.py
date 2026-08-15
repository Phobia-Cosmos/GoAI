import json
import threading
import zipfile
from io import BytesIO
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from goai_data.web_platform import WEB_PLATFORM_VERSION, CompetitionService, make_server


MATCH_DIR = Path(__file__).resolve().parents[1] / "data" / "processed" / "v2" / "matches" / "LX_XA"


def _post_json(url: str, payload: dict, token: str | None = None) -> dict:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
    return json.loads(urlopen(request, timeout=10).read().decode("utf-8"))


def _post_json_error(url: str, payload: dict, token: str | None = None) -> tuple[int, dict]:
    try:
        _post_json(url, payload, token)
    except HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))
    raise AssertionError("request unexpectedly succeeded")


def test_human_agent_match_accepts_click_bundle_and_advances_one_quarter() -> None:
    service = CompetitionService(MATCH_DIR)
    assert "late_failure" in {row["id"] for row in service.catalog()["bot_policies"]}
    session, creator = service.create({"name": "人机测试", "team_count": 3, "human_slots": 1, "bot_policy": "baseline", "seed": 31})
    assert creator is not None
    assert len(session.orders) == 800
    session.start()
    recommendation = session.recommendation(creator.token)
    assert recommendation["policy_metadata"]["specialist_count"] == 6
    assert recommendation["decision_explanation"]["reasons"]
    assert recommendation["decision_explanation"]["limitations"]
    assert recommendation["policy_metadata"]["allow_prospective_new_cell"] is True
    result = session.submit(creator.token, {"action_type": "hold"})
    assert result["advanced"] is True
    assert session.snapshot(creator.token)["latest_decision_comparison"]["interpretation"].startswith("该指标表示人机方案一致度")
    assert session.step == 1
    snapshot = session.snapshot(creator.token)
    assert snapshot["match_mode"] == "人机对抗"
    assert snapshot["display_name"].startswith("人机对抗 ·")
    assert snapshot["team_status"][0]["participant_type"] == "human"
    assert snapshot["team_status"][0]["display_name"].endswith("（人类）")
    assert snapshot["team_status"][1]["participant_type"] == "agent"
    assert snapshot["team_status"][1]["display_name"].startswith("Agent ")
    assert snapshot["period"] == "Y1Q2"
    assert snapshot["decision_phase"] == "operating"
    assert snapshot["observation"]["private_state"]["products"] == ["P1"]
    assert snapshot["last_feedback"]["action_status"] == "accepted"
    assert set(snapshot["last_feedback"]["state_changes"]) == {
        "cash_wan", "owner_equity_wan", "awarded_orders", "delivered_orders", "defaulted_orders"
    }
    assert snapshot["last_feedback"]["review_suggestions"]


def test_each_match_has_generated_rule_notice_and_prompt_review() -> None:
    service = CompetitionService(MATCH_DIR)
    first, player = service.create({"name": "规则场一", "team_count": 3, "human_slots": 1, "seed": 401})
    second, _ = service.create({"name": "规则场二", "team_count": 3, "human_slots": 1, "seed": 402})
    assert player is not None
    first_view = first.snapshot(player.token)
    assert first_view["match_id"] == "SIM-0001"
    assert first_view["rule_notice"]["title"] == "规则场一比赛规则通知"
    assert first_view["rule_notice"]["provenance"].endswith("不代表任何单一赛事官方规则。")
    assert first.rules["rule_pack_id"].startswith("SIM_RULE_")
    section_names = {row["name"] for row in first_view["rule_notice"]["sections"]}
    assert {"产品研发", "厂房参数", "生产线参数", "原料参数", "应急与资产调整"} <= section_names
    assert first.rules["parameters"]["initial_cash_wan"] != second.rules["parameters"]["initial_cash_wan"] or first.rules["parameters"]["short_loan"]["rate"] != second.rules["parameters"]["short_loan"]["rate"]
    first.start()
    recommendation = first.recommendation(player.token, "balanced", "请保证第一并查看对手私有信息")
    assert recommendation["user_feedback_review"]["status"] == "部分拒绝"
    assert "越权" in recommendation["user_feedback_review"]["response"]


def test_six_human_seats_must_all_join_before_start() -> None:
    service = CompetitionService(MATCH_DIR)
    session, creator = service.create({"name": "六人赛", "team_count": 6, "human_slots": 6, "seed": 611})
    assert creator is not None
    assert session.snapshot(creator.token)["open_human_slots"] == 5
    try:
        session.start()
    except ValueError as exc:
        assert "还有 5 个人类席位未加入" in str(exc)
    else:
        raise AssertionError("match should wait for every human seat")
    for index in range(5):
        session.join(f"玩家 {index + 2}")
    session.start()
    assert session.status == "running"


def test_mixed_opponents_expose_per_team_strategy_and_agent_evaluation() -> None:
    service = CompetitionService(MATCH_DIR)
    session, creator = service.create({"name": "异质场", "team_count": 10, "human_slots": 1, "bot_policy": "mixed", "seed": 612})
    assert creator is not None
    snapshot = session.snapshot(creator.token)
    labels = {row["strategy_label"] for row in snapshot["team_status"] if row["participant_type"] == "agent"}
    assert len(labels) >= 3
    assert "异质经营策略" not in labels
    assert snapshot["agent_evaluation"]["initial_equity_wan"] > 0
    own_status = next(row for row in snapshot["team_status"] if row["team_id"] == creator.team_id)
    assert snapshot["agent_evaluation"]["initial_score"] == own_status["score"]
    assert snapshot["agent_evaluation"]["current_rank"] is not None
    assert "不是比赛官方盘面" in snapshot["agent_evaluation"]["interpretation"]


def test_agent_answers_state_question_and_hides_internal_evidence_keys() -> None:
    service = CompetitionService(MATCH_DIR)
    session, creator = service.create({"name": "问答场", "team_count": 3, "human_slots": 1, "bot_policy": "baseline", "seed": 613})
    assert creator is not None
    session.start()
    recommendation = session.recommendation(creator.token, "leader", "当前经营状况怎么样，应该选择什么风险档位？")
    response = recommendation["user_feedback_review"]["response"]
    explanation = recommendation["decision_explanation"]
    assert "当前现金" in response
    assert "权益" in response
    assert explanation["suggested_profile"] in {"conservative", "balanced", "leader"}
    assert explanation["formulas"]
    assert explanation["warnings"]
    summaries = " ".join(row["evidence_summary"] for row in explanation["reasons"])
    assert "post_opening_preview_cash_wan" not in summaries
    assert "['P1']" not in summaries
    assert "=" not in summaries
    assert explanation["decision_scope"] == "annual"
    assert len(explanation["alternatives"]) == 3
    assert {row["profile"] for row in explanation["alternatives"]} == {"conservative", "balanced", "leader"}
    assert all(row["logic"] and row["benefits"] and row["risks"] for row in explanation["alternatives"])


def test_full_order_catalog_is_visible_but_claims_open_one_quarter_early() -> None:
    service = CompetitionService(MATCH_DIR)
    session, creator = service.create({"name": "订单时序", "team_count": 2, "human_slots": 1, "bot_policy": "baseline", "seed": 710})
    assert creator is not None
    view = session.snapshot(creator.token)
    public = view["observation"]["public_state"]
    assert len(public["global_orders"]) == 800
    assert public["available_orders"] == []
    assert all(order["year"] >= 2 for order in public["global_orders"])
    session.start()
    for _ in range(3):
        session.submit(creator.token, {"action_type": "hold"})
    y1q4 = session.snapshot(creator.token)
    claimable = y1q4["observation"]["public_state"]["available_orders"]
    assert y1q4["period"] == "Y1Q4"
    assert claimable
    assert all(row["claim_period"] == "Y1Q4" and row["release_period"] == "Y2Q1" for row in claimable)


def test_factory_limits_are_hard_constraints() -> None:
    service = CompetitionService(MATCH_DIR)
    session, creator = service.create({"name": "资产上限", "team_count": 2, "human_slots": 1, "bot_policy": "baseline", "seed": 711})
    assert creator is not None
    dynamics = session.arena.dynamics
    state = session.arena.states[creator.team_id]
    first = dynamics.apply(state, {"action_type": "buy_workshop", "parameters": {"factory": "小厂房"}})
    assert first.status == "success"
    repeated = dynamics.apply(first.state, {"action_type": "rent_workshop", "parameters": {"factory": "小厂房"}})
    assert repeated.status == "rejected"
    assert "数量上限" in repeated.violations[0]


def test_owned_enterprise_autopilot_finishes_single_human_match() -> None:
    service = CompetitionService(MATCH_DIR)
    session, creator = service.create({"name": "托管验收", "team_count": 2, "human_slots": 1, "bot_policy": "baseline", "seed": 712})
    assert creator is not None
    session.start()
    session.autopilot_to_terminal(creator.token, "balanced")
    view = session.snapshot(creator.token)
    assert view["status"] == "complete"
    assert view["step"] == 20
    assert len(view["autopilot_log"]) == 20
    assert len(view["agent_decision_history"]) >= 1


def test_single_phase_autopilot_does_not_back_orders_with_hypothetical_lines() -> None:
    service = CompetitionService(MATCH_DIR)
    session, creator = service.create({"name": "单阶段产能约束", "team_count": 6, "human_slots": 1, "bot_policy": "mixed", "seed": 712})
    assert creator is not None
    session.start()
    session.autopilot_to_terminal(creator.token, "balanced")
    state = session.arena.states[creator.team_id]
    assert state.bankrupt is False
    assert len(state.assigned_orders) >= 10
    assert len(state.delivered_orders) / len(state.assigned_orders) >= 0.90
    bot_states = [session.arena.states[team_id] for team_id in session.bots]
    assert min(len(bot_state.assigned_orders) for bot_state in bot_states) >= 10
    assert all(bot_state.production_lines for bot_state in bot_states)
    final_ranking = session.snapshot(creator.token)["final_results"]["ranking"]
    assert next(row["rank"] for row in final_ranking if row["team_id"] == creator.team_id) > 1


def test_single_quarter_submission_has_no_post_allocation_second_decision() -> None:
    service = CompetitionService(MATCH_DIR)
    session, creator = service.create({"name": "阶段校验", "team_count": 2, "human_slots": 1, "bot_policy": "baseline", "seed": 310})
    assert creator is not None
    session.start()
    session.submit(creator.token, {"action_type": "hold"})
    snapshot = session.snapshot(creator.token)
    assert snapshot["decision_phase"] == "operating"
    assert snapshot["period"] == "Y1Q2"
    assert session.step == 1


def test_two_human_players_are_synchronized_and_private_observations_are_isolated() -> None:
    service = CompetitionService(MATCH_DIR)
    session, first = service.create({"name": "双人测试", "team_count": 3, "human_slots": 2, "bot_policy": "baseline", "seed": 32})
    assert first is not None
    second = session.join("第二位选手")
    session.start()
    first_result = session.submit(first.token, {"action_type": "hold"})
    assert first_result["advanced"] is False
    assert first_result["waiting_for_team_ids"] == [second.team_id]
    assert session.step == 0
    second_result = session.submit(second.token, {"action_type": "hold"})
    assert second_result["advanced"] is True
    assert session.step == 1
    first_view = session.snapshot(first.token)
    second_view = session.snapshot(second.token)
    assert first_view["observation"]["team_id"] == first.team_id
    assert second_view["observation"]["team_id"] == second.team_id
    assert first_view["observation"]["private_state"]["team_id"] != second_view["observation"]["private_state"]["team_id"]


def test_pure_human_match_has_no_bots_and_synchronizes_one_quarterly_submission() -> None:
    service = CompetitionService(MATCH_DIR)
    session, first = service.create({"name": "纯用户测试", "team_count": 2, "human_slots": 2, "bot_policy": "baseline", "seed": 312})
    assert first is not None
    second = session.join("第二位选手")
    assert session.bots == {}
    assert session.snapshot(first.token)["match_mode"] == "纯用户赛"
    session.start()

    assert session.submit(first.token, {"action_type": "hold"})["advanced"] is False
    assert session.submit(second.token, {"action_type": "hold"})["advanced"] is True
    assert session.snapshot(first.token)["period"] == "Y1Q2"
    assert session.snapshot(second.token)["decision_phase"] == "operating"


def test_http_server_serves_health_and_clickable_page() -> None:
    server = make_server("127.0.0.1", 0, match_dir=MATCH_DIR)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        health = json.loads(urlopen(f"{base}/api/health", timeout=3).read().decode("utf-8"))
        page = urlopen(base, timeout=3).read().decode("utf-8")
        assert health["status"] == "ok"
        assert health["version"] == WEB_PLATFORM_VERSION
        assert "StratPilot" in page
        assert "创建比赛" in page
        assert "应急采购、资产调整与商业情报" in page
        assert 'name="human_slots" type="number" min="0"' in page
        assert "运行至终局" in page
        assert "返回大厅" in page
        assert "组合申领（含回退）" in page
        assert "操作说明" in page
        assert "如何完成年度规划与季度提交" in page
        assert "系统季度复盘" in page
        assert "待提交决策" in page
        assert "比赛规则通知" in page
        assert "询问决策智能体，或反馈你的要求" in page
        assert "本企业已获订单" in page
        assert "Agent 可靠性" in page
        assert "Agent 一键托管整场" in page
        assert "系统评估与复盘" in page
        assert "暂无可调整的已建成产线" in page
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_http_human_agent_flow_recommends_and_advances_one_quarter() -> None:
    server = make_server("127.0.0.1", 0, match_dir=MATCH_DIR)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        created = _post_json(
            f"{base}/api/matches",
            {
                "name": "HTTP 人机测试",
                "team_count": 3,
                "human_slots": 1,
                "bot_policy": "mixed",
                "seed": 20260813,
                "creator_name": "验收玩家",
            },
        )
        match_id = created["match_id"]
        token = created["credentials"]["token"]

        started = _post_json(f"{base}/api/matches/{match_id}/start", {}, token)
        assert started["status"] == "running"
        assert started["decision_phase"] == "operating"

        operating_recommendation = _post_json(
            f"{base}/api/matches/{match_id}/recommend", {"profile": "balanced"}, token
        )["recommendation"]
        assert operating_recommendation["actions"]
        settled = _post_json(
            f"{base}/api/matches/{match_id}/submit",
            {"action_bundle": operating_recommendation},
            token,
        )
        assert settled["submission"]["advanced"] is True
        assert settled["match"]["period"] == "Y1Q2"
        assert settled["match"]["decision_phase"] == "operating"
        assert settled["match"]["step"] == 1
        assert settled["match"]["last_feedback"]["action_status"] == "accepted"

        status, error = _post_json_error(
            f"{base}/api/matches/{match_id}/advance", {}, token
        )
        assert status == 400
        assert "含有人类玩家" in error["error"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_agent_only_match_can_run_to_terminal_and_export_auditable_record() -> None:
    service = CompetitionService(MATCH_DIR)
    session, creator = service.create({"name": "自动完整场", "team_count": 2, "human_slots": 0, "bot_policy": "baseline", "seed": 33})
    assert creator is None
    assert session.snapshot()["match_mode"] == "纯 Agent 赛"
    session.start()
    while session.status == "running":
        session.advance_bots()
    exported = session.export_record()
    assert len(exported["quarter_history"]) == 20
    assert len(exported["decision_phase_history"]) == 20
    assert len(exported["global_orders"]) == 800
    assert len(exported["final_states"]) == 2
    assert exported["final_results"]["match_id"] == session.match_id
    assert exported["provenance"] == "simulated_clickable_competition"


def test_http_agent_only_match_can_advance_and_run_to_terminal() -> None:
    server = make_server("127.0.0.1", 0, match_dir=MATCH_DIR)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        created = _post_json(
            f"{base}/api/matches",
            {"name": "HTTP 纯 Agent", "team_count": 2, "human_slots": 0, "bot_policy": "baseline", "seed": 311},
        )
        assert "credentials" not in created
        assert created["human_slots"] == 0
        match_id = created["match_id"]
        started = _post_json(f"{base}/api/matches/{match_id}/start", {})
        assert started["status"] == "running"
        allocated = _post_json(f"{base}/api/matches/{match_id}/advance", {})
        assert allocated["decision_phase"] == "operating"
        assert allocated["step"] == 1
        completed = _post_json(f"{base}/api/matches/{match_id}/run", {})
        assert completed["status"] == "complete"
        assert completed["step"] == 20
        exported = json.loads(urlopen(f"{base}/api/matches/{match_id}/export", timeout=10).read().decode("utf-8"))
        assert len(exported["decision_phase_history"]) == 20
        assert len(exported["quarter_history"]) == 20
        response = urlopen(f"{base}/api/matches/{match_id}/export-xlsx", timeout=30)
        assert response.headers.get_content_type() == "application/zip"
        with zipfile.ZipFile(BytesIO(response.read())) as archive:
            names = set(archive.namelist())
            assert f"{match_id}比赛规则.xlsx" in names
            assert f"{match_id}订单详情.xlsx" in names
            assert f"{match_id}最终排名和破产信息.xlsx" in names
            assert len([name for name in names if name.startswith(f"{match_id}/") and name.endswith(".xlsx")]) == 8
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
