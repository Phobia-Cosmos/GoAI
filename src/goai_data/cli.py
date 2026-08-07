from __future__ import annotations

import argparse
import json
from pathlib import Path

from .pipeline import DataPipeline


DEFAULT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = Path("/home/undefined/Disk/datasets/goai/processed/v1")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="将 GoAI 原始资料转换为可追溯的标准数据集")
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT, help="GoAI 原始资料根目录")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="标准数据集输出目录")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    quality = DataPipeline(args.root, args.output).build()
    print(json.dumps(quality["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
