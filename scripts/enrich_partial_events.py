#!/usr/bin/env python3
"""Conservatively enrich normalized event records with evidence-backed fields."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from goai_data.rulepack import infer_partial_events


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("events", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    rows = [json.loads(line) for line in args.events.read_text(encoding="utf-8").splitlines() if line.strip()]
    enriched = infer_partial_events(rows)
    output = args.output or args.events.with_name("events_inferred.jsonl")
    output.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in enriched), encoding="utf-8")
    summary = Counter((row.get("parameter_parse_status"), row.get("inference_provenance")) for row in enriched)
    summary_path = output.with_suffix(".summary.json")
    summary_path.write_text(json.dumps({"input": str(args.events), "output": str(output), "counts": {f"{key[0]}|{key[1]}": value for key, value in summary.items()}}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "summary": str(summary_path), "events": len(enriched)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
