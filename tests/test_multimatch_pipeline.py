import json
from pathlib import Path

from goai_data.multimatch_pipeline import MultiMatchDatasetBuilder, OUTPUT_FILES


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_builds_uniform_multimatch_dataset(tmp_path: Path) -> None:
    output = tmp_path / "v2"
    catalog = MultiMatchDatasetBuilder(PROJECT_ROOT, output).build()

    assert catalog["match_count"] == 14
    assert {row["match_id"] for row in catalog["matches"]} == {
        "AB", "AG", "CA", "CB", "CD", "CE", "EA", "EB", "EC", "EF", "OP", "ZY", "ZZ", "LX_XA"
    }
    for match in catalog["matches"]:
        match_dir = output / match["path"]
        assert all((match_dir / name).is_file() for name in OUTPUT_FILES)
        quality = json.loads((match_dir / "quality.json").read_text(encoding="utf-8"))
        assert quality["checks"]["cash_continuity"]["passed"]
        assert quality["checks"]["quarter_state_shape"]["passed"]
        assert quality["checks"]["operating_action_mapping"]["passed"]

    xa = next(row for row in catalog["matches"] if row["match_id"] == "LX_XA")
    assert xa["team_count"] == 27
    assert xa["operating_event_count"] == 3787
    assert xa["global_order_count"] == 796
    assert xa["simulated_order_count"] == 0
    rules = json.loads((output / "matches/LX_XA/rules.json").read_text(encoding="utf-8"))
    assert rules["parameters"]["initial_cash_wan"] == 675
    assert rules["parameters"]["management_fee_per_quarter_wan"] == 14
    results = json.loads((output / "matches/LX_XA/results.json").read_text(encoding="utf-8"))
    assert len(results["ranking"]) == 18
    assert all(row["official_score_matches"] for row in results["ranking"])

    ab_rules = json.loads((output / "matches/AB/rules.json").read_text(encoding="utf-8"))
    assert ab_rules["binding_status"] == "reconstructed_match_specific"
    assert ab_rules["candidate_rule_pack"]["binding_status"] == "unconfirmed_not_auto_bound_to_match"
    assert ab_rules["parameters"]["initial_cash_wan"] == 600
    assert ab_rules["parameters"]["management_fee_per_quarter_wan"] == 10
    assert next(row for row in catalog["matches"] if row["match_id"] == "AB")["simulated_order_count"] > 0

    ab_events = [json.loads(line) for line in (output / "matches/AB/events.jsonl").read_text(encoding="utf-8").splitlines()]
    assert all(row["action"] is not None for row in ab_events)

    xa_quality = json.loads((output / "matches/LX_XA/quality.json").read_text(encoding="utf-8"))
    assert xa_quality["record_counts"]["unassigned_global_orders"] == 235
