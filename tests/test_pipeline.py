import json
import sqlite3
from pathlib import Path

import pandas as pd

from goai_data.pipeline import DataPipeline


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_pipeline_builds_traceable_dataset(tmp_path: Path) -> None:
    output = tmp_path / "processed"
    quality = DataPipeline(PROJECT_ROOT, output).build()

    assert quality["record_counts"]["order_catalog"] == 581
    assert quality["summary"]["active_teams"] == 15
    assert quality["summary"]["empty_team_exports"] == 3
    assert quality["record_counts"]["team_cash_flows"] > 1_000
    assert quality["record_counts"]["action_events"] == (
        quality["record_counts"]["team_cash_flows"] + quality["record_counts"]["test_cash_flow_events"]
    )
    assert quality["record_counts"]["rule_gaps"] > 0
    assert quality["summary"]["blocking_rule_gaps"] > 0
    assert quality["record_counts"]["workbook_cells"] > 10_000

    teams = pd.read_csv(output / "csv" / "teams.csv")
    assert set(teams.loc[teams["data_status"] == "empty_export", "team_id"]) == {"ZY01", "ZY12", "ZY18"}

    summary = json.loads((output / "reports" / "run_summary.json").read_text(encoding="utf-8"))
    issue_codes = {issue["code"] for issue in summary["issues"]}
    assert "cross_competition_initial_capital_conflict" in issue_codes

    rulepack = json.loads(
        (output / "metadata" / "rulepack_zhejiang_8th_rules_v1.json").read_text(encoding="utf-8")
    )
    assert rulepack["format_version"] == "rulepack_v0.1"
    assert rulepack["tables"]["rule_packs"][0]["simulation_ready"] == 0

    with sqlite3.connect(output / "goai.sqlite") as connection:
        count = connection.execute("SELECT COUNT(*) FROM order_catalog").fetchone()[0]
        unmapped = connection.execute(
            "SELECT COUNT(*) FROM action_events WHERE canonical_action IS NULL"
        ).fetchone()[0]
    assert count == 581
    assert unmapped == 0
