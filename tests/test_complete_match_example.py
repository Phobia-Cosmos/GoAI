from __future__ import annotations

import importlib.util
import json
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "generate_complete_match_example.py"
SPEC = importlib.util.spec_from_file_location("generate_complete_match_example", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
generate = MODULE.generate


def test_complete_match_example_is_structurally_complete(tmp_path):
    validation = generate(tmp_path)

    assert validation["status"] == "passed"
    assert validation["checks"]["quarter_count"] == 20
    assert validation["checks"]["team_count"] == 20
    assert validation["checks"]["public_team_rows"] == 400
    assert validation["checks"]["cash_continuity"] == "passed"
    assert validation["checks"]["balance_sheet_identity"] == "passed"
    assert validation["checks"]["foreign_keys"] == "passed"

    bundle = json.loads((tmp_path / "complete_match.json").read_text(encoding="utf-8"))
    assert bundle["manifest"]["formal_training_eligible"] is False
    assert bundle["manifest"]["not_training_data"] is True
    assert bundle["rule_pack"]["simulation_ready"] is False
    assert bundle["rule_pack"]["formal_commit_allowed"] is False
    assert len(bundle["enterprise_timeline"]["quarter_snapshots"]) == 20
    assert len(bundle["decision_cycles"]["decision_cycles"]) == 20


def test_complete_match_simulated_records_are_not_training_eligible(tmp_path):
    generate(tmp_path)
    bundle = json.loads((tmp_path / "complete_match.json").read_text(encoding="utf-8"))

    simulated_objects = [
        bundle["enterprise_timeline"],
        *bundle["global_context"]["global_order_pool"],
        *bundle["analytics"]["metric_bundles"],
        *bundle["decision_cycles"]["decision_cycles"],
    ]
    for item in simulated_objects:
        assert item["provenance"]["status"] == "simulated"
        assert item["provenance"]["training_eligible"] is False
