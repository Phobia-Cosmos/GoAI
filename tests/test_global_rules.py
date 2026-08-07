import json
from pathlib import Path

from goai_data.global_rules import infer_xa_global_rules, is_bankrupt, merge_rule_overrides, rank_final_states
from goai_data.rulepack import infer_partial_event_parameters


ROOT = Path("/home/undefined/Disk/datasets/goai/processed/v2/matches/LX_XA")


def test_xa_frozen_rule_evidence_matches_official_scores() -> None:
    rules = json.loads((ROOT / "rules.json").read_text(encoding="utf-8"))
    results = json.loads((ROOT / "results.json").read_text(encoding="utf-8"))
    final_states = [json.loads(line) for line in (ROOT / "final_states.jsonl").read_text(encoding="utf-8").splitlines()]
    orders = [json.loads(line) for line in (ROOT / "global_orders.jsonl").read_text(encoding="utf-8").splitlines()]
    report = infer_xa_global_rules(rules, final_states=final_states, official_ranking=results["ranking"], bankruptcies=results["bankruptcies"], global_orders=orders)
    assert report.evidence["official_score_match_count"] == 18
    assert report.confirmed["order_pool_years_observed"] == [2, 3, 4, 5]
    assert "auction_tie_break_and_bid_payment" in report.unresolved


def test_xa_ranking_and_bankruptcy_are_replaceable_services() -> None:
    rules = json.loads((ROOT / "rules.json").read_text(encoding="utf-8"))
    assert is_bankrupt(-1, 100, rules) == (True, ("cash_flow_break",))
    assert is_bankrupt(100, -1, rules) == (True, ("negative_equity",))
    rows = rank_final_states([
        {"team_id": "B", "owner_equity_wan": 100, "development_potential": 0},
        {"team_id": "A", "owner_equity_wan": 100, "development_potential": 0},
        {"team_id": "C", "owner_equity_wan": 1, "development_potential": 0, "bankruptcy_period": "Y1Q1"},
    ], rules)
    assert [row["team_id"] for row in rows] == ["A", "B"]
    overridden = merge_rule_overrides(rules, {"parameters": {"initial_cash_wan": 700}, "participants": {"team_ids": ["A", "B"]}})
    assert overridden["parameters"]["initial_cash_wan"] == 700
    assert overridden["parent_rule_pack_id"] == rules["rule_pack_id"]


def test_partial_event_inference_is_conservative() -> None:
    result = infer_partial_event_parameters({
        "canonical_action": "short_loan_borrow",
        "raw_action": "Short_Loan",
        "amount_wan": 100,
        "parameters": {},
    })
    assert result["parameters"]["principal_wan"] == 100
    assert result["parameter_parse_status"] == "inferred_partial"
    assert "term/term_quarters" in result["missing_parameter_fields"] or result["missing_parameter_fields"] == []
    assert result["inference_provenance"] == "derived_from_event_evidence"
