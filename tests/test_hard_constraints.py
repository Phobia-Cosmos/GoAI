import json
from pathlib import Path

from goai_data.hard_constraints import validate_dataset, validate_match


DATASET_ROOT = Path("/home/undefined/Disk/datasets/goai/processed/v2")


def test_all_fourteen_matches_pass_hard_constraints() -> None:
    result = validate_dataset(DATASET_ROOT)
    assert result["passed"] is True
    assert result["match_count"] == 14
    assert all(match["passed"] for match in result["matches"])


def test_xa_hard_constraints_include_order_pool_and_official_score_checks() -> None:
    result = validate_match(DATASET_ROOT / "matches/LX_XA")
    assert result.passed is True
    assert result.checks["xa_order_pool_counts"]["assigned"] == 561
    assert result.checks["xa_order_pool_counts"]["unassigned"] == 235
    assert result.checks["xa_official_scores"]["ranked_team_count"] == 18
    assert result.checks["xa_exact_rank_order"]["ranked_team_count"] == 18
    assert result.checks["xa_exact_bankruptcies"]["bankrupt_team_count"] == 9
    assert result.checks["xa_exact_development_potential"]["team_count"] == 27
    assert result.checks["xa_exact_terminal_cash"]["team_count"] == 27
    assert result.checks["xa_inverse_calibration"]["quarter_state_count"] == 540
    assert all(result.checks["xa_inverse_calibration"]["checks"].values())
    assert result.checks["report_accounting_identities"]["passed"] is True


def test_constraint_report_is_json_serializable() -> None:
    result = validate_match(DATASET_ROOT / "matches/AG")
    json.dumps(result.to_dict(), ensure_ascii=False)
