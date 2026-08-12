import json
import threading
from pathlib import Path
from urllib.request import urlopen

from goai_data.web_platform import CompetitionService, make_server


MATCH_DIR = Path(__file__).resolve().parents[1] / "data" / "processed" / "v2" / "matches" / "LX_XA"


def test_human_agent_match_accepts_click_bundle_and_advances_one_quarter() -> None:
    service = CompetitionService(MATCH_DIR)
    assert "late_failure" in {row["id"] for row in service.catalog()["bot_policies"]}
    session, creator = service.create({"name": "人机测试", "team_count": 3, "human_slots": 1, "bot_policy": "baseline", "seed": 31})
    assert creator is not None
    assert len(session.orders) == 796
    session.start()
    recommendation = session.recommendation(creator.token)
    assert recommendation["policy_metadata"]["specialist_count"] == 6
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
    assert snapshot["period"] == "Y1Q2"
    assert snapshot["decision_phase"] == "operating"
    assert snapshot["observation"]["private_state"]["products"] == ["P1"]
    assert snapshot["last_feedback"]["action_status"] == "accepted"


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


def test_http_server_serves_health_and_clickable_page() -> None:
    server = make_server("127.0.0.1", 0, match_dir=MATCH_DIR)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        health = json.loads(urlopen(f"{base}/api/health", timeout=3).read().decode("utf-8"))
        page = urlopen(base, timeout=3).read().decode("utf-8")
        assert health["status"] == "ok"
        assert "GoAI 经营竞技场" in page
        assert "创建比赛" in page
        assert "应急、资产处置与信息购买" in page
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_agent_only_match_can_run_to_terminal_and_export_auditable_record() -> None:
    service = CompetitionService(MATCH_DIR)
    session, creator = service.create({"name": "自动完整场", "team_count": 2, "human_slots": 0, "bot_policy": "baseline", "seed": 33})
    assert creator is None
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
