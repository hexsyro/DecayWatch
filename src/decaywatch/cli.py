"""Command-line interface for DecayWatch.

Exit codes:
  0 — ran successfully
  1 — findings at or above the --fail-on severity
  2 — usage or input error
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from decaywatch import __version__
from decaywatch.common import SEVERITY_RANK, load_rows
from decaywatch.logic import DecayWatchLogic
from decaywatch.output import render, worst_severity

TOOL = "decaywatch"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=TOOL,
        description="Measure how much of a collected dataset still exists by comparing snapshots.",
    )
    parser.add_argument("data", help="dataset file (.csv, .json, or .jsonl)")
    parser.add_argument(
        "--format",
        "-f",
        choices=["table", "json", "csv", "md", "markdown"],
        default="table",
        help="output format (default: table)",
    )
    parser.add_argument("--output", "-o", metavar="FILE", help="write the report to FILE instead of stdout")
    parser.add_argument(
        "--fail-on",
        choices=["none", "low", "medium", "high"],
        default="none",
        help="exit 1 if any finding is at or above this severity (default: none)",
    )
    parser.add_argument("--config", metavar="FILE", help="JSON file of options")
    parser.add_argument("--mode", choices=["snapshot", "direct"], help="comparison mode (default: snapshot)")
    parser.add_argument("--id-column", metavar="COL", help="column holding the record id")
    parser.add_argument("--snapshot-column", metavar="COL", help="column marking original vs fresh rows")
    parser.add_argument("--status-column", metavar="COL", help="column marking present vs removed rows")
    parser.add_argument("--segment-column", metavar="COL", help="column to break survival down by")
    parser.add_argument("--original-value", metavar="VAL", help="snapshot value that marks the original set")
    parser.add_argument("--fresh-value", metavar="VAL", help="snapshot value that marks the fresh re-collection")
    parser.add_argument("--max-examples", type=int, metavar="N", help="cap on purge-list examples in findings")
    parser.add_argument("--version", action="version", version=f"{TOOL} {__version__}")
    return parser


def _merge_options(args: argparse.Namespace) -> dict[str, Any]:
    options: dict[str, Any] = {}
    if args.config:
        parsed = json.loads(Path(args.config).read_text(encoding="utf-8"))
        if not isinstance(parsed, dict):
            raise ValueError(f"{args.config}: config must be a JSON object")
        options.update(parsed)
    for flag, key in (
        ("mode", "mode"),
        ("id_column", "id_column"),
        ("snapshot_column", "snapshot_column"),
        ("status_column", "status_column"),
        ("segment_column", "segment_column"),
        ("original_value", "original_value"),
        ("fresh_value", "fresh_value"),
        ("max_examples", "max_examples"),
    ):
        value = getattr(args, flag)
        if value is not None:
            options[key] = value
    return options


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        options = _merge_options(args)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"{TOOL}: {exc}", file=sys.stderr)
        return 2
    try:
        rows = load_rows(args.data)
    except FileNotFoundError:
        print(f"{TOOL}: file not found: {args.data}", file=sys.stderr)
        return 2
    except (OSError, ValueError) as exc:
        print(f"{TOOL}: {exc}", file=sys.stderr)
        return 2
    result = DecayWatchLogic().run(rows, options)
    text = render(result, args.format, tool=TOOL, version=__version__)
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    else:
        print(text, end="" if text.endswith("\n") else "\n")
    if args.fail_on != "none":
        worst = worst_severity(result)
        if worst and SEVERITY_RANK.get(worst, 0) >= SEVERITY_RANK[args.fail_on]:
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
