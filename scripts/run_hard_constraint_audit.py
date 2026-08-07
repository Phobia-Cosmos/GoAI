from __future__ import annotations

import argparse
import json
from pathlib import Path

from goai_data.hard_constraints import validate_dataset


def main() -> int:
    parser = argparse.ArgumentParser(description="运行 GoAI 统一数据集硬约束审计。")
    parser.add_argument("--dataset", type=Path, default=Path("/home/undefined/Disk/datasets/goai/processed/v2"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = validate_dataset(args.dataset.resolve())
    text = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
