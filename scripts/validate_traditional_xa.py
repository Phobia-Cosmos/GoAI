#!/usr/bin/env python3
"""Validate traditional sandbox defaults against the complete XA bundle."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from goai_data.traditional_rules import apply_traditional_defaults, validate_traditional_xa


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("match_dir", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    root = args.match_dir.resolve()
    rules = json.loads((root / "rules.json").read_text(encoding="utf-8"))
    results = json.loads((root / "results.json").read_text(encoding="utf-8"))
    report = validate_traditional_xa(
        teams=read_jsonl(root / "teams.jsonl"),
        global_orders=read_jsonl(root / "global_orders.jsonl"),
        results=results,
        rules=rules,
        events=read_jsonl(root / "events.jsonl"),
    )
    report["effective_rules"] = apply_traditional_defaults(rules)["global_rule_services"]
    output = args.output or (root / "traditional_validation.json")
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
