"""Shared helpers for DecayWatch: row coercion, dataset loading, result shape.

The rules in ``logic.py`` receive the rows of a dataset (a list of dicts) plus
an options dict and return a :class:`ToolResult`. The helpers here normalize
the messy real-world columns pipelines actually export — mixed casing,
trailing spaces, ``-`` vs ``_`` — so the rules can be defensive about field
presence without repeating lookup code.
"""

from __future__ import annotations

import csv
import io
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

SEVERITY_RANK = {"low": 1, "medium": 2, "high": 3}


@dataclass
class ToolResult:
    status: str = "success"
    findings: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Column lookup
# ---------------------------------------------------------------------------

_SEP_RE = re.compile(r"[^0-9a-z]+")


def norm_key(key: Any) -> str:
    """Normalize a column name for lookup: lowercase, strip, dashes -> underscore."""
    return _SEP_RE.sub("_", str(key).strip().lower())


def index_row(row: dict) -> dict[str, Any]:
    """Return a row indexed by normalized column name (first occurrence wins)."""
    indexed: dict[str, Any] = {}
    for key, value in row.items():
        normalized = norm_key(key)
        if normalized and normalized not in indexed:
            indexed[normalized] = value
    return indexed


def get(row: dict, keys: list[str], default: Any = None) -> Any:
    """Case-insensitive lookup for the first present non-null column among ``keys``."""
    indexed = index_row(row)
    for key in keys:
        value = indexed.get(norm_key(key))
        if value is not None:
            return value
    return default


def as_str(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return str(value)
    return str(value).strip()


def as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    text = as_str(value).lower()
    if text in {"1", "true", "yes", "y", "on", "found", "present", "success"}:
        return True
    if text in {"0", "false", "no", "n", "off", "missing", "absent", "failed"}:
        return False
    parsed = to_float(value)
    return parsed is not None and parsed != 0


def to_float(value: Any, default: float | None = None) -> float | None:
    """Parse a number from a messy cell (percent signs, commas, ``k``/``M`` suffixes).

    Rejects date-like or ambiguous strings instead of silently grabbing the
    first number group.
    """
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return float(value)
    text = as_str(value).replace(",", "").strip()
    if not text:
        return default
    multiplier = 1.0
    if text.endswith(("k", "K")):
        multiplier = 1_000.0
        text = text[:-1]
    elif text.endswith(("m", "M")):
        multiplier = 1_000_000.0
        text = text[:-1]
    elif text.endswith(("b", "B")):
        multiplier = 1_000_000_000.0
        text = text[:-1]
    groups = re.findall(r"-?\d+(?:\.\d+)?", text)
    if len(groups) != 1:
        return default
    try:
        return float(groups[0]) * multiplier
    except ValueError:
        return default


def to_int(value: Any, default: int | None = None) -> int | None:
    number = to_float(value)
    if number is None:
        return default
    return round(number)


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def find_id(row: dict) -> str | None:
    """Best-effort record id for a row."""
    value = get(row, ["id", "record_id", "post_id", "uuid", "row_id", "key"])
    if value is None:
        return None
    text = as_str(value)
    return text or None


# ---------------------------------------------------------------------------
# Dates
# ---------------------------------------------------------------------------

_DATE_FORMATS = (
    "%Y-%m-%d",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%dT%H:%M:%S.%f",
    "%Y/%m/%d",
    "%Y/%m/%d %H:%M:%S",
    "%m/%d/%Y",
    "%m/%d/%Y %H:%M:%S",
    "%d/%m/%Y",
    "%d/%m/%Y %H:%M:%S",
    "%b %d, %Y",
    "%d %b %Y",
    "%Y-%m-%d %H:%M",
)


def parse_date(value: Any) -> datetime | None:
    """Parse a date-ish cell into a datetime (tz-aware values are kept aware)."""
    if isinstance(value, datetime):
        return value
    if value is None:
        return None
    text = as_str(value).strip()
    if not text:
        return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def as_naive(value: datetime | None) -> datetime | None:
    """Drop tzinfo so aware and naive timestamps compare safely."""
    if value is None:
        return None
    return value.replace(tzinfo=None) if value.tzinfo is not None else value


def opt_float(options: dict, key: str, default: float) -> float:
    try:
        return float(options.get(key, default))
    except (TypeError, ValueError):
        return default


def opt_int(options: dict, key: str, default: int) -> int:
    try:
        return int(options.get(key, default))
    except (TypeError, ValueError):
        return default


def opt_list(value: Any) -> list[str]:
    """Normalize a list-ish option: a bare string becomes one item, not chars."""
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple, set)):
        return [str(v) for v in value]
    return [str(value)]


# ---------------------------------------------------------------------------
# Dataset loading
# ---------------------------------------------------------------------------


def load_rows(path: str | Path) -> list[dict]:
    """Load rows from a CSV, JSON, or JSONL file.

    CSV needs a header row. JSON must be a list of objects (or an object with
    a ``rows`` or ``data`` list). Each JSONL line must be one object.
    """
    p = Path(path)
    text = p.read_text(encoding="utf-8-sig")
    suffix = p.suffix.lower()

    if suffix in {".jsonl", ".ndjson"}:
        rows: list[dict] = []
        for lineno, line in enumerate(text.splitlines(), start=1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{p}:{lineno}: invalid JSON line: {exc.msg}") from exc
            if isinstance(obj, dict):
                rows.append(obj)
            else:
                raise ValueError(f"{p}:{lineno}: each JSONL line must be a JSON object")
        return rows

    if suffix == ".json":
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{p}: invalid JSON: {exc.msg}") from exc
        if isinstance(data, dict):
            data = data.get("rows", data.get("data"))
        if not isinstance(data, list):
            raise ValueError(f"{p}: expected a JSON list of objects (or an object with 'rows'/'data')")
        return [row for row in data if isinstance(row, dict)]

    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        raise ValueError(f"{p}: CSV file has no header row")
    return [dict(row) for row in reader]


# ---------------------------------------------------------------------------
# Text
# ---------------------------------------------------------------------------


def tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", text.lower())


def tokens(text: str) -> set[str]:
    return {t for t in tokenize(text) if len(t) > 1}


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)
