import json
import threading
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
    assert len(session.orders) == 796
    session.start()
    recommendation = session.recommendation(creator.token)
    assert recommendation["policy_metadata"]["specialist_count"] == 6
    assert recommendation["policy_metadata"]["allow_prospective_new_cell"] is True
    result = session.submit(creator.token, {"actions": [{"action_type": "develop_product", "parameters": {"target": "P1"}}]})
    assert result["advanced"] is True
    assert session.step == 0
    allocation_snapshot = session.snapshot(creator.token)
    assert allocation_snapshot["period"] == "Y1Q1"
    assert allocation_snapshot["decision_phase"] == "post_allocation"
    result = session.submit(creator.token, {"action_type": "hold"})
    assert result["advanced"] is True
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


def test_post_allocation_submission_rejects_disallowed_actions_before_advancing() -> None:
    service = CompetitionService(MATCH_DIR)
    session, creator = service.create({"name": "阶段校验", "team_count": 2, "human_slots": 1, "bot_policy": "baseline", "seed": 310})
    assert creator is not None
    session.start()
    session.submit(creator.token, {"action_type": "hold"})
    assert session.snapshot(creator.token)["decision_phase"] == "post_allocation"

    try:
        session.submit(creator.token, {"action_type": "advertising", "parameters": {"amount_wan": 1}})
    except ValueError as exc:
        assert "获单后履约阶段不允许动作" in str(exc)
    else:
        raise AssertionError("post-allocation advertising should be rejected")
    assert session.step == 0
    assert session.snapshot(creator.token)["decision_phase"] == "post_allocation"


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
    assert session.step == 0
    assert session.snapshot(first.token)["decision_phase"] == "post_allocation"
    session.submit(first.token, {"action_type": "hold"})
    settled = session.submit(second.token, {"action_type": "hold"})
    assert settled["advanced"] is True
    assert session.step == 1
    first_view = session.snapshot(first.token)
    second_view = session.snapshot(second.token)
    assert first_view["observation"]["team_id"] == first.team_id
    assert second_view["observation"]["team_id"] == second.team_id
    assert first_view["observation"]["private_state"]["team_id"] != second_view["observation"]["private_state"]["team_id"]


def test_pure_human_match_has_no_bots_and_synchronizes_both_phases() -> None:
    service = CompetitionService(MATCH_DIR)
    session, first = service.create({"name": "纯用户测试", "team_count": 2, "human_slots": 2, "bot_policy": "baseline", "seed": 312})
    assert first is not None
    second = session.join("第二位选手")
    assert session.bots == {}
    assert session.snapshot(first.token)["match_mode"] == "纯用户赛"
    session.start()

    assert session.submit(first.token, {"action_type": "hold"})["advanced"] is False
    assert session.submit(second.token, {"action_type": "hold"})["advanced"] is True
    assert session.snapshot(first.token)["decision_phase"] == "post_allocation"
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
        assert "GoAI 经营竞技场" in page
        assert "创建比赛" in page
        assert "应急、资产处置与信息购买" in page
        assert 'name="human_slots" type="number" min="0"' in page
        assert "运行至终局" in page
        assert "返回大厅" in page
        assert "组合申领（含回退）" in page
        assert "操作说明" in page
        assert "如何完成一个季度" in page
        assert "本季度复盘建议" in page
        assert "待提交决策" in page
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_http_human_agent_flow_recommends_both_phases_and_advances() -> None:
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
        allocated = _post_json(
            f"{base}/api/matches/{match_id}/submit",
            {"action_bundle": operating_recommendation},
            token,
        )
        assert allocated["submission"]["advanced"] is True
        assert allocated["match"]["decision_phase"] == "post_allocation"
        assert allocated["match"]["period"] == "Y1Q1"

        fulfillment_recommendation = _post_json(
            f"{base}/api/matches/{match_id}/recommend", {"profile": "balanced"}, token
        )["recommendation"]
        assert fulfillment_recommendation["actions"]
        settled = _post_json(
            f"{base}/api/matches/{match_id}/submit",
            {"action_bundle": fulfillment_recommendation},
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
    assert len(exported["decision_phase_history"]) == 40
    assert len(exported["global_orders"]) == 796
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
        assert allocated["decision_phase"] == "post_allocation"
        assert allocated["step"] == 0
        completed = _post_json(f"{base}/api/matches/{match_id}/run", {})
        assert completed["status"] == "complete"
        assert completed["step"] == 20
        exported = json.loads(urlopen(f"{base}/api/matches/{match_id}/export", timeout=10).read().decode("utf-8"))
        assert len(exported["decision_phase_history"]) == 40
        assert len(exported["quarter_history"]) == 20
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
