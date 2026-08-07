#!/usr/bin/env python3
"""Freeze the formal XA rule source plus auditable outcome checks."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from goai_data.global_rules import infer_xa_global_rules


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("match_dir", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    match_dir = args.match_dir.resolve()
    rules = json.loads((match_dir / "rules.json").read_text(encoding="utf-8"))
    results = json.loads((match_dir / "results.json").read_text(encoding="utf-8"))
    final_states = read_jsonl(match_dir / "final_states.jsonl")
    orders = read_jsonl(match_dir / "global_orders.jsonl")
    report = infer_xa_global_rules(
        rules,
        final_states=final_states,
        official_ranking=results.get("ranking", []),
        bankruptcies=results.get("bankruptcies", []),
        global_orders=orders,
    )
    payload = {
        "format_version": "goai_frozen_rule_pack_v1",
        "match_id": rules.get("match_id"),
        "rule_pack_id": rules.get("rule_pack_id"),
        "parent_source": "rules.json",
        "source_provenance": rules.get("provenance"),
        "formal_parameters": rules.get("parameters", {}),
        "global_rule_services": {
            "bankruptcy": {"predicates": report.confirmed["bankruptcy_predicates"], "excluded_from_ranking": True},
            "ranking": {"formula": report.confirmed["score_formula"], "rounding": report.confirmed["rounding"], "tie_breaker": report.inferred["ranking_tie_breaker"]},
            "order_pool": {"first_year_has_orders": report.confirmed["first_year_has_orders"], "observed_years": report.confirmed["order_pool_years_observed"], "unassigned_allowed": True, "selection_priority": report.confirmed["selection_priority"]},
            "counterfactual": {"recompute_scope": report.inferred["counterfactual_recompute_scope"]},
        },
        "inference_report": report.to_dict(),
        "customization": {"allowed_overrides": ["parameters", "global_rule_services.order_pool", "initial_state", "participants"]},
        "truth_policy": "confirmed rules remain observed; inferred and unresolved fields cannot be promoted automatically",
    }
    output = args.output or (match_dir / "rules_frozen.json")
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
