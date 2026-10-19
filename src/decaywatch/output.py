"""Render a ToolResult as text: table (default), json, csv, or markdown."""

from __future__ import annotations

import csv
import io
import json
import textwrap

from decaywatch.common import SEVERITY_RANK, ToolResult


def render(result: ToolResult, fmt: str, *, tool: str, version: str) -> str:
    """Render ``result`` in the requested format."""
    if fmt == "json":
        return _json(result, tool, version)
    if fmt == "csv":
        return _csv(result)
    if fmt in {"md", "markdown"}:
        return _markdown(result, tool, version)
    return _table(result, tool, version)


def worst_severity(result: ToolResult) -> str | None:
    """Highest severity present in the findings (or None when clean)."""
    best = None
    best_rank = 0
    for finding in result.findings:
        sev = str(finding.get("severity", "low"))
        rank = SEVERITY_RANK.get(sev, 0)
        if rank > best_rank:
            best, best_rank = sev, rank
    return best


def _json(result: ToolResult, tool: str, version: str) -> str:
    envelope = {
        "tool": tool,
        "version": version,
        "status": result.status,
        "findings": result.findings,
        "warnings": result.warnings,
        "summary": result.summary,
    }
    return json.dumps(envelope, indent=2, ensure_ascii=False, default=str)


def _csv(result: ToolResult) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["severity", "field", "record_id", "message", "metadata"])
    for finding in result.findings:
        writer.writerow(
            [
                finding.get("severity", ""),
                finding.get("field", ""),
                finding.get("record_id") or "",
                finding.get("message", ""),
                json.dumps(finding.get("metadata") or {}, ensure_ascii=False, default=str),
            ]
        )
    return buffer.getvalue()


def _markdown(result: ToolResult, tool: str, version: str) -> str:
    checked = result.summary.get("checked")
    lines = [
        f"# {tool} report",
        "",
        f"**Version:** {version} — **Status:** {result.status} — "
        f"**Findings:** {len(result.findings)}"
        + (f" — **Rows checked:** {checked}" if checked is not None else ""),
        "",
    ]
    if result.findings:
        lines += [
            "| Severity | Field | Record | Message |",
            "| --- | --- | --- | --- |",
        ]
        for finding in result.findings:
            message = str(finding.get("message", "")).replace("|", "\\|")
            record = str(finding.get("record_id") or "-")
            field = str(finding.get("field") or "-")
            lines.append(f"| {finding.get('severity', '')} | {field} | {record} | {message} |")
    else:
        lines.append("No findings.")
    lines.append("")
    if result.warnings:
        lines.append("## Warnings")
        lines.append("")
        lines.extend(f"- {w}" for w in result.warnings)
        lines.append("")
    if result.summary:
        lines.append("## Summary")
        lines.append("")
        for key, value in result.summary.items():
            if isinstance(value, (dict, list)):
                value = json.dumps(value, ensure_ascii=False, default=str)
            lines.append(f"- **{key}:** {value}")
        lines.append("")
    return "\n".join(lines)


def _table(result: ToolResult, tool: str, version: str) -> str:
    checked = result.summary.get("checked")
    header = f"{tool} {version} — {len(result.findings)} finding(s)"
    if checked is not None:
        header += f", {checked} row(s) checked"
    lines = [header, ""]

    if not result.findings:
        lines.append("  No findings.")

    for finding in result.findings:
        sev = str(finding.get("severity", "low"))
        record = str(finding.get("record_id") or "-")
        field = str(finding.get("field") or "-")
        lines.append(f"  [{sev:<6}] {record[:14]:<14} {field}")
        message = str(finding.get("message", ""))
        wrapped = textwrap.wrap(message, width=88)
        for part in wrapped or [""]:
            lines.append(f"           {part}")
        lines.append("")

    if result.warnings:
        lines.append("Warnings:")
        for warning in result.warnings:
            lines.append(f"  - {warning}")
        lines.append("")

    counts = result.summary.get("rule_counts")
    if counts:
        rendered = ", ".join(f"{name}={n}" for name, n in sorted(counts.items()))
        lines.append(f"Rules: {rendered}")

    return "\n".join(lines).rstrip() + "\n"
