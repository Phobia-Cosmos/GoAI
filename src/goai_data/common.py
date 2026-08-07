from __future__ import annotations

import hashlib
import math
import os
import re
from pathlib import Path
from typing import Any


PERIOD_RE = re.compile(r"第\s*(\d+)\s*年(?:\s*(\d+)\s*季)?")
YQ_RE = re.compile(r"Y\s*(\d+)\s*Q\s*(\d+)", re.IGNORECASE)
NUMBER_RE = re.compile(r"[-+]?\d+(?:\.\d+)?")


def is_blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and math.isnan(value):
        return True
    return isinstance(value, str) and not value.strip()


def clean_text(value: Any) -> str | None:
    if is_blank(value):
        return None
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def as_number(value: Any) -> float | None:
    if is_blank(value):
        return None
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)
    match = NUMBER_RE.search(str(value).replace(",", ""))
    return float(match.group()) if match else None


def as_int(value: Any) -> int | None:
    number = as_number(value)
    return int(number) if number is not None else None


def parse_money_wan(value: Any) -> float | None:
    """将样例中的 W/万元金额统一成万元数值。"""
    return as_number(value)


def parse_period(value: Any) -> tuple[int | None, int | None]:
    if is_blank(value):
        return None, None
    text = str(value).strip()
    if text == "初始元年":
        return 0, 0
    match = PERIOD_RE.search(text)
    if match:
        return int(match.group(1)), int(match.group(2)) if match.group(2) else None
    match = YQ_RE.search(text)
    if match:
        return int(match.group(1)), int(match.group(2))
    if re.fullmatch(r"\d+(?:\.0+)?", text):
        return int(float(text)), None
    return None, None


def parse_duration(value: Any) -> tuple[float | None, str | None, bool]:
    if is_blank(value):
        return None, None, False
    text = str(value).strip()
    if text == "-":
        return 0.0, None, True
    number = as_number(text)
    if "季" in text:
        return number, "quarter", False
    if "年" in text:
        return number, "year", False
    return number, None, False


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_id(path: Path, root: Path) -> str:
    resolved = path.resolve()
    try:
        rel = resolved.relative_to(root.resolve()).as_posix()
    except ValueError:
        rel = os.path.relpath(resolved, root.resolve()).replace(os.sep, "/")
    return "src_" + hashlib.sha1(rel.encode("utf-8"), usedforsecurity=False).hexdigest()[:12]


def cell_ref(row_index: int, col_index: int) -> str:
    col = col_index + 1
    letters = ""
    while col:
        col, remainder = divmod(col - 1, 26)
        letters = chr(65 + remainder) + letters
    return f"{letters}{row_index + 1}"


def stable_record_id(*parts: Any) -> str:
    payload = "|".join("" if part is None else str(part) for part in parts)
    return hashlib.sha1(payload.encode("utf-8"), usedforsecurity=False).hexdigest()[:16]
