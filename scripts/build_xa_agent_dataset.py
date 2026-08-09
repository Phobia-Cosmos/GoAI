"""Build the real/simulated XA dataset view consumed by decision agents."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from goai_data.agent_dataset import build_xa_agent_dataset


def main() -> int:
    parser = argparse.ArgumentParser(description="整理 XA 真实历史与模拟比赛为同构 Agent 数据")
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    parser.add_argument("--output-root", type=Path, default=Path("data/agent_ready/v1/xa"))
    parser.add_argument(
        "--simulation",
        type=Path,
        action="append",
        default=None,
        help="可重复传入；默认使用当前高复杂度 XA 模拟比赛",
    )
    args = parser.parse_args()
    simulations = args.simulation or [
        args.data_root / "simulations" / "xa_fixed_v1" / "SIM_XA_FIXED_seed_20260809",
        args.data_root / "simulations" / "xa_initial_orders_v1" / "SIM_XA_INITIAL_seed_20260809",
    ]
    catalog = build_xa_agent_dataset(args.data_root, args.output_root, simulations)
    print(json.dumps(catalog, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
