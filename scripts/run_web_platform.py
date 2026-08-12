#!/usr/bin/env python3
"""Start the clickable GoAI human/Agent competition platform."""

from __future__ import annotations

import argparse
from pathlib import Path

from goai_data.web_platform import DEFAULT_MATCH_DIR, serve


def main() -> int:
    parser = argparse.ArgumentParser(description="启动 GoAI 可点击的人机/多人比赛平台")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址；局域网访问使用 0.0.0.0")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--match-dir", type=Path, default=DEFAULT_MATCH_DIR)
    args = parser.parse_args()
    serve(args.host, args.port, match_dir=args.match_dir.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
