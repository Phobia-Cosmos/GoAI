#!/usr/bin/env python3
"""Build audited XA intermediate-state and missing-parameter estimates."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from goai_data.xa_inverse import build_xa_inverse_artifacts


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--match-dir", type=Path, default=Path("data/processed/v2/matches/LX_XA"))
    args = parser.parse_args()
    report = build_xa_inverse_artifacts(args.match_dir)
    print(json.dumps({"status": report["status"], "initial_state": report["initial_state"]["passed"], "short_loans": report["loan_reconstruction"]["short_loan"], "long_loans": report["loan_reconstruction"]["long_loan"], "depreciation": {key: report["depreciation_reconstruction"][key] for key in ("passed_on_identifiable_histories", "matched", "total")}}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
