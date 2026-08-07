"""Build inferred runtime rules and deterministic replay logs for all matches."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from goai_data.match_replay import build_replay_artifacts, infer_runtime_rules


def main() -> int:
    parser = argparse.ArgumentParser(description="为统一数据集的全部比赛生成逐场推断规则和重放日志")
    parser.add_argument("--dataset", type=Path, default=Path("/home/undefined/Disk/datasets/goai/processed/v2"))
    parser.add_argument("--seed", type=int, default=20260805)
    args = parser.parse_args()
    dataset = args.dataset.resolve()
    matches_root = dataset / "matches"
    xa_rules = json.loads((matches_root / "LX_XA" / "rules.json").read_text(encoding="utf-8"))
    summaries = []
    for match_dir in sorted(path for path in matches_root.iterdir() if path.is_dir()):
        rules, report = infer_runtime_rules(match_dir, xa_reference=xa_rules)
        summary = build_replay_artifacts(match_dir, rules, report, seed=args.seed)
        summaries.append(summary)
        print(json.dumps({"match_id": summary["match_id"], "hard_constraints_passed": summary["hard_constraints_passed"], "cash_identity_passed": summary["cash_identity_passed"], "rule_pack_id": summary["rule_pack_id"]}, ensure_ascii=False))
    output = {
        "run_version": "match_replay_v1.0",
        "dataset": str(dataset),
        "seed": args.seed,
        "match_count": len(summaries),
        "all_hard_constraints_passed": all(row["hard_constraints_passed"] for row in summaries),
        "all_cash_identities_passed": all(row["cash_identity_passed"] for row in summaries),
        "matches": summaries,
    }
    (dataset / "all_match_replay_summary.json").write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"match_count": len(summaries), "all_hard_constraints_passed": output["all_hard_constraints_passed"], "all_cash_identities_passed": output["all_cash_identities_passed"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
