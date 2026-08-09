import json
from pathlib import Path

from goai_data.agent_dataset import build_xa_agent_dataset


DATA = Path(__file__).resolve().parents[1] / "data"


def read_jsonl(path: Path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def test_xa_agent_dataset_separates_observation_from_offline_labels(tmp_path: Path) -> None:
    simulation = DATA / "simulations" / "large_20260808" / "SIM_LX_XA_seed_20270808"
    catalog = build_xa_agent_dataset(DATA, tmp_path / "xa", [simulation])
    assert catalog["baseline"] == "XA"
    assert catalog["metric_policy"]["vpd_required"] is False

    real_rows = read_jsonl(tmp_path / "xa" / "real" / "transitions.jsonl")
    assert len(real_rows) == 540
    assert {row["observation"]["agent_id"] for row in real_rows} == {f"XA{index:02d}" for index in range(1, 28)}
    assert all("terminal_result" not in row["observation"] for row in real_rows)
    assert all("other_teams_private_states_and_events" in row["excluded_from_observation"] for row in real_rows)
    assert all(row["offline_labels"]["terminal_result"] is not None for row in real_rows)

    simulated_rows = read_jsonl(tmp_path / "xa" / "simulated" / simulation.name / "transitions.jsonl")
    assert len(simulated_rows) == 540
    assert all(row["provenance"] == "simulated" for row in simulated_rows)
    assert all("action_bundle" in row["offline_labels"] for row in simulated_rows)
    assert all("terminal_result" not in row["observation"] for row in simulated_rows)


def test_real_xa_connection_points_preserve_temporal_cutoff(tmp_path: Path) -> None:
    simulation = DATA / "simulations" / "large_20260808" / "SIM_LX_XA_seed_20270808"
    build_xa_agent_dataset(DATA, tmp_path / "xa", [simulation])
    rows = [
        row
        for row in read_jsonl(tmp_path / "xa" / "real" / "transitions.jsonl")
        if row["episode_id"] == "xa_real_v1:XA01"
    ]
    assert [row["decision_index"] for row in rows] == list(range(20))
    assert rows[0]["observation"]["private_state"]["known_own_history_event_count"] == 0
    assert rows[-1]["observation"]["private_state"]["known_own_history_event_count"] > 0
    assert rows[0]["observation"]["public_state"]["completed_public_years"] == []
    assert rows[4]["observation"]["public_state"]["completed_public_years"] == [1]


def test_recorded_fixed_xa_uses_full_leakage_safe_observations(tmp_path: Path) -> None:
    simulation = DATA / "simulations" / "xa_fixed_v1" / "SIM_XA_FIXED_seed_20260809"
    catalog = build_xa_agent_dataset(DATA, tmp_path / "xa", [simulation])
    manifest = catalog["simulated"][0]
    assert manifest["observation_completeness"] == "full_decision_state_without_journal_report_blobs"
    rows = read_jsonl(tmp_path / "xa" / "simulated" / simulation.name / "transitions.jsonl")
    assert len(rows) == 540
    assert all(row["observation"]["legal_actions"] for row in rows)
    assert all("available_orders" not in row["observation"]["private_state"] for row in rows)
    assert all("unreleased_global_orders" in row["excluded_from_observation"] for row in rows)
