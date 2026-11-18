"""DecayWatch — how much of a shared/collected dataset still exists.

Two modes (core design choice):
- Snapshot comparison (start here, the default): the user uploads the original
  collection plus a fresh re-collection (one file, a column marking which
  snapshot each row belongs to). No platform access needed, no terms risk.
- Direct re-check (later, only if allowed): re-checking availability through
  permitted official means. NOT implemented: requesting it returns a warning
  explaining why, per platform-terms risk.

Core checks: survival rate (overall + by segment), metadata drift on matched
records, representativity (survivors vs original), purge list (vanished ids).
0.2.0 adds survival/decay curves, content drift (distinct from link rot), and
source-type risk stratification.
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any

from decaywatch.common import (
    ToolResult,
    as_naive,
    as_str,
    find_id,
    get,
    norm_key,
    opt_int,
    opt_list,
    opt_str,
    parse_date,
)
from decaywatch.stats import (
    chi_square_contingency,
    chi_square_sf,
    ks_statistic,
    min_expected_count,
    normalized_text_hash,
    wilson_interval,
)

DIRECT_RECHECK_WARNING = (
    "Direct re-checks are disabled: re-querying platforms can violate their terms. "
    "Upload a fresh re-collection instead and use snapshot comparison "
    "(set mode=snapshot, the default)."
)

# These columns describe the snapshot/bookkeeping, not the content of a record.
_STRUCTURAL_KEYS = {
    "id", "record_id", "post_id", "uuid", "row_id", "key",
    "snapshot", "collection", "wave", "round",
    "status", "availability", "present", "state",
    "segment", "source_type",
}
_HIGH_RISK_HINTS = ("com", "db-driven", "pdf")
_DURABLE_HINTS = ("gov", "edu", "news")
_SURVIVAL_DAYS = (0, 30, 90, 365)


class DecayWatchLogic:
    """Dataset-decay reporter over snapshot pairs."""

    def run(self, rows: list[dict], options: dict[str, Any]) -> ToolResult:
        opts = options if isinstance(options, dict) else {}
        mode = opt_str(opts, "mode", "snapshot").lower() or "snapshot"
        if mode == "direct":
            return ToolResult(
                status="success",
                findings=[],
                warnings=[DIRECT_RECHECK_WARNING, "Review each platform's rules before any direct re-check."],
                summary={
                    "checked": len(rows), "mode": "direct", "rechecks": "disabled",
                    "skipped": True, "skip_reason": "direct_recheck_disabled",
                },
            )

        id_col = opt_str(opts, "id_column")
        snap_col = opt_str(opts, "snapshot_column")
        status_col = opt_str(opts, "status_column")
        seg_col = opt_str(opts, "segment_column")
        date_col = opt_str(opts, "date_column")
        content_col = opt_str(opts, "content_column")
        source_type_col = opt_str(opts, "source_type_column")
        text_col_option = opt_str(opts, "text_column")
        drift_option = [name for name in opt_list(opts.get("drift_columns")) if name]
        max_examples = max(1, opt_int(opts, "max_examples", 5))

        findings: list[dict] = []
        warnings = ["Snapshot comparison only — no platforms were contacted by this run."]

        id_idx = self._resolve(rows, id_col) if id_col else None
        if id_idx is None:
            # Fall back to best-effort record ids.
            id_idx = self._resolve(rows, "id")

        snap_idx = self._resolve(rows, snap_col) if snap_col else self._guess(
            rows, ["snapshot", "collection", "wave", "round"])
        status_idx = self._resolve(rows, status_col) if status_col else self._guess(
            rows, ["status", "availability", "present", "state"])
        seg_idx = self._resolve(rows, seg_col) if seg_col else None
        date_idx = self._resolve(rows, date_col) if date_col else None
        content_idx = self._resolve(rows, content_col) if content_col else None
        source_idx = self._resolve(rows, source_type_col) if source_type_col else seg_idx

        if content_col and content_idx is None:
            warnings.append(f"content_column '{content_col}' not found — content drift check skipped.")
        if date_col and date_idx is None:
            warnings.append(f"date_column '{date_col}' not found — survival curve skipped.")
        if source_type_col and source_idx is None:
            warnings.append(f"source_type_column '{source_type_col}' not found — risk stratification skipped.")

        original_ids: set[str] = set()
        fresh_ids: set[str] = set()
        original_rows: dict[str, dict] = {}
        fresh_rows: dict[str, dict] = {}

        if snap_idx and status_idx:
            warnings.append(
                f"Both snapshot ('{snap_idx}') and status ('{status_idx}') markers found — "
                "comparing snapshots; the status column was ignored."
            )
        if snap_idx:
            snaps = sorted({as_str(get(r, [snap_idx])).lower() for r in rows} - {""})
            if len(snaps) < 2:
                warnings.append(
                    f"Snapshot column '{snap_idx}' has fewer than 2 distinct values "
                    f"({', '.join(snaps) or 'none'}). Need original + fresh markers."
                )
                return ToolResult(status="success", findings=[], warnings=warnings,
                                  summary=self._skipped_summary(len(rows), "single_snapshot_value"))
            user_old = opt_str(opts, "original_value")
            user_new = opt_str(opts, "fresh_value")
            old_val = user_old or self._guess_snapshot(snaps, "old")
            new_val = user_new or self._guess_snapshot(snaps, "new")
            if not user_old and not user_new and (
                old_val == new_val
                or not any(h in (old_val + new_val) for h in ("orig", "fresh", "old", "new"))
            ):
                warnings.append(
                    f"Snapshot markers {snaps} don't name original/fresh explicitly — "
                    f"assuming '{old_val}' is original and '{new_val}' is fresh. "
                    "Set 'original_value'/'fresh_value' options if that's wrong."
                )
            for r in rows:
                rid = self._rid(r, id_idx)
                if not rid:
                    continue
                mark = as_str(get(r, [snap_idx])).lower()
                if mark == old_val.lower():
                    original_ids.add(rid)
                    original_rows.setdefault(rid, r)
                elif mark == new_val.lower():
                    fresh_ids.add(rid)
                    fresh_rows.setdefault(rid, r)
            check_note = f"snapshots '{old_val}' vs '{new_val}'"
        elif status_idx:
            present = {
                s.lower()
                for s in (opt_list(opts.get("present_values")) or ["present", "alive", "found", "active"])
            }
            for r in rows:
                rid = self._rid(r, id_idx)
                if not rid:
                    continue
                original_ids.add(rid)
                original_rows.setdefault(rid, r)
                if as_str(get(r, [status_idx])).lower() in present:
                    fresh_ids.add(rid)
                    fresh_rows[rid] = r
            check_note = f"status column '{status_idx}'"
        else:
            warnings.append(
                "No snapshot markers found. Provide 'snapshot_column' (original vs fresh values) "
                "or 'status_column' (present vs removed values)."
            )
            return ToolResult(status="success", findings=[], warnings=warnings,
                              summary=self._skipped_summary(len(rows), "no_snapshot_markers"))

        if not original_ids:
            warnings.append("No original-snapshot records identified — check id/snapshot columns.")
            return ToolResult(status="success", findings=[], warnings=warnings,
                              summary=self._skipped_summary(len(rows), "no_original_records"))

        surviving = original_ids & fresh_ids
        vanished = sorted(original_ids - fresh_ids)
        fresh_only = sorted(fresh_ids - original_ids)
        survival = len(surviving) / len(original_ids)
        if fresh_only and len(fresh_only) > 0.2 * max(len(fresh_ids), 1):
            warnings.append(
                f"{len(fresh_only)} record(s) appear only in the fresh snapshot "
                "(new collection, not survivors) — survival is computed on "
                f"original ids only ({len(surviving)}/{len(original_ids)})."
            )

        seg_report: dict[str, dict] = {}
        seg_table: dict[str, list[int]] = {}
        if seg_idx:
            by_seg: dict[str, set[str]] = {}
            for rid in original_ids:
                seg = as_str(get(original_rows.get(rid, {}), [seg_idx])) or "(unknown)"
                by_seg.setdefault(seg, set()).add(rid)
            for seg, ids in sorted(by_seg.items()):
                survived_n = len(ids & fresh_ids)
                rate = survived_n / len(ids)
                seg_report[seg] = {"original": len(ids), "surviving": survived_n,
                                   "survival_rate": round(rate, 3)}
                seg_table[seg] = [survived_n, len(ids) - survived_n]
                if rate < 0.5:
                    findings.append(self._finding(
                        "high", seg_idx,
                        f"Segment '{seg}' decayed heavily: {rate:.0%} survival "
                        f"({survived_n}/{len(ids)}).",
                        None, {"check": "survival", "segment": seg, "survival_rate": round(rate, 3)},
                    ))
                elif rate < 0.8:
                    findings.append(self._finding(
                        "medium", seg_idx,
                        f"Segment '{seg}' survival is {rate:.0%} ({survived_n}/{len(ids)}).",
                        None, {"check": "survival", "segment": seg, "survival_rate": round(rate, 3)},
                    ))

        # Metadata drift on matched records. Never report bookkeeping columns.
        drift_fields: list[dict] = []
        matched = [rid for rid in surviving if rid in original_rows and rid in fresh_rows]
        if matched:
            structural = {norm_key(c) for c in (id_idx, snap_idx, status_idx, seg_idx, source_idx, date_idx) if c}
            structural.update(_STRUCTURAL_KEYS)
            if drift_option:
                cols: list[str] = []
                for requested in drift_option:
                    resolved = self._resolve(rows, requested)
                    if resolved and norm_key(resolved) not in structural and resolved not in cols:
                        cols.append(resolved)
            else:
                cols = [str(c) for c in (list(rows[0].keys()) if rows else [])
                        if norm_key(c) not in structural][:20]
            for col in cols:
                changed = sum(
                    1 for rid in matched
                    if as_str(get(original_rows[rid], [col])) != as_str(get(fresh_rows[rid], [col]))
                )
                if changed:
                    drift_fields.append({"field": str(col), "changed": changed,
                                         "of_matched": len(matched)})
            drift_fields.sort(key=lambda d: -d["changed"])
            for d in drift_fields[:max_examples]:
                share = d["changed"] / max(len(matched), 1)
                if share >= 0.2:
                    findings.append(self._finding(
                        "low", str(d["field"]),
                        f"Metadata drift: '{d['field']}' changed on {d['changed']}/{len(matched)} "
                        "surviving records between snapshots.",
                        None, {"check": "metadata_drift", **d},
                    ))

        # Representativity: survivors vs original on length + categorical mix.
        representativity = self._representativity(original_rows, surviving, text_col_option, warnings)

        # Is decay segment-dependent? Chi-square over the survived/vanished
        # contingency table (needs 2+ segments, 5+ originals each, and expected
        # cell counts >= 5 — otherwise the p-value is not trustworthy).
        heterogeneity = self._segment_heterogeneity(seg_table, warnings)

        # Reference/content rot is NOT link rot: these records are still here,
        # but their normalized content changed between snapshots.
        content_count, content_examples = self._content_drift(
            matched, original_rows, fresh_rows, content_idx)
        if content_idx and content_count:
            examples = ", ".join(content_examples[:max_examples])
            findings.append(self._finding(
                "low", content_idx,
                f"Content drift: normalized content changed on {content_count}/{len(matched)} "
                "surviving records. This is content drift, not link rot or disappearance — "
                "the records are still present."
                + (f" Examples: {examples}." if examples else ""),
                None, {"check": "content_drift", "changed": content_count,
                       "of_matched": len(matched), "examples": content_examples[:max_examples]},
            ))

        # Survival curve / decay rate from parsed snapshot dates.
        curve: dict[str, float] | None = None
        half_life: float | None = None
        annualized_loss: float | None = None
        if date_idx:
            old_date = self._snapshot_date([original_rows[rid] for rid in original_ids], date_idx)
            new_date = self._snapshot_date([fresh_rows[rid] for rid in fresh_ids], date_idx)
            curve, half_life, annualized_loss, date_warning = self._survival_metrics(
                old_date, new_date, survival)
            if date_warning:
                warnings.append(date_warning)

        # Source-type risk: which kinds of sources are we measuring decay on?
        source_risk = self._source_type_risk(original_rows, source_idx)
        if source_risk and source_risk["high_risk_share"] > 0.5:
            warnings.append(
                f"Source-type risk: {source_risk['high_risk']}/{len(original_rows)} originals "
                "come from high-risk sources (com, db-driven, pdf) — survival estimates "
                "may be optimistic."
            )

        # Purge list (capped in findings; every id ships in summary.purge_ids).
        for rid in vanished[:max_examples]:
            findings.append(self._finding(
                "medium", id_idx or "id",
                f"Purge candidate: record {rid} disappeared at the source and should "
                "probably leave the dataset too.",
                rid, {"check": "purge_list", "record_id": rid},
            ))
        if len(vanished) > max_examples:
            findings.append(self._finding(
                "medium", id_idx or "id",
                f"... and {len(vanished) - max_examples} more purge candidates — "
                "all ids are in summary.purge_ids.",
                None, {"check": "purge_list", "overflow": len(vanished) - max_examples},
            ))

        if survival < 0.5:
            findings.append(self._finding(
                "high", snap_idx or status_idx or "snapshot",
                f"Low survival: {survival:.0%} of {len(original_ids)} original records "
                "are still present. Document the loss; the dataset may no longer support "
                "its original claims.",
                None, {"check": "survival", "survival_rate": round(survival, 3)},
            ))

        wilson_lo, wilson_hi = wilson_interval(len(surviving), len(original_ids))
        summary: dict[str, Any] = {
            "checked": len(rows),
            "mode": "snapshot",
            "comparison": check_note,
            "original_records": len(original_ids),
            "surviving_records": len(surviving),
            "survival_rate": round(survival, 4),
            "survival_wilson_low": round(wilson_lo, 4),
            "survival_wilson_high": round(wilson_hi, 4),
            "by_segment": seg_report,
            "segment_heterogeneity": heterogeneity,
            "metadata_drift": drift_fields[:10],
            "representativity": representativity,
            "content_drift_count": content_count,
            "content_drift_examples": content_examples[:max_examples],
            "survival_curve": curve,
            "half_life_days": half_life,
            "annualized_loss_pct": annualized_loss,
            "source_type_risk": source_risk,
            "purge_count": len(vanished),
            "purge_preview": vanished[:50],
            "purge_ids": vanished[:10000],
            "fresh_only_count": len(fresh_only),
            "fresh_only_preview": fresh_only[:50],
        }
        return ToolResult(status="success", findings=findings, warnings=warnings, summary=summary)

    @staticmethod
    def _skipped_summary(checked: int, reason: str) -> dict[str, Any]:
        """Summary for a run that deliberately did not compare snapshots."""
        return {"checked": checked, "mode": "snapshot", "skipped": True, "skip_reason": reason}

    @staticmethod
    def _segment_heterogeneity(seg_table: dict[str, list[int]], warnings: list[str]) -> dict | None:
        """Chi-square test: does survival differ by segment?

        Needs 2+ segments with 5+ originals each and expected cell counts of at
        least 5; otherwise there is no power and the test stays silent.
        """
        eligible = {seg: counts for seg, counts in seg_table.items() if sum(counts) >= 5}
        if len(eligible) < 2:
            return None
        table = [[float(counts[0]), float(counts[1])] for counts in eligible.values()]
        if min_expected_count(table) < 5.0:
            warnings.append(
                "Chi-square segment test skipped: an expected cell count is below 5 — "
                "reporting a p-value here would be unreliable."
            )
            return None
        stat, dof = chi_square_contingency(table)
        p_value = chi_square_sf(stat, dof)
        return {
            "chi2": round(stat, 2),
            "dof": dof,
            "p_value": round(p_value, 4),
            "heterogeneous": p_value < 0.05,
            "segments": sorted(eligible),
        }

    @staticmethod
    def _snapshot_date(rows: list[dict], date_idx: str | None) -> datetime | None:
        """Representative date for a snapshot (median of parseable row dates)."""
        if date_idx is None:
            return None
        dates = [parsed for row in rows
                 if (parsed := as_naive(parse_date(get(row, [date_idx])))) is not None]
        if not dates:
            return None
        dates.sort()
        return dates[len(dates) // 2]

    @staticmethod
    def _survival_metrics(
        old_date: datetime | None, new_date: datetime | None, survival: float
    ) -> tuple[dict[str, float] | None, float | None, float | None, str | None]:
        """Step-function survival curve, log-linear half-life, annualized loss."""
        if old_date is None or new_date is None:
            return None, None, None, (
                "Survival curve skipped: date_column values are missing or could not be "
                "parsed in both snapshots."
            )
        days = (new_date - old_date).days
        if days < 30:
            return None, None, None, (
                f"Survival curve skipped: snapshot interval is {days} day(s) (<30) — "
                "too short for decay-rate estimates."
            )

        # Two observations: day 0 (everything present) and the fresh snapshot.
        # Carry the latest known survival forward for later target days.
        observations = ((0, 1.0), (days, survival))
        curve = {
            f"day_{target}": round(
                next((value for day, value in reversed(observations) if day <= target), 1.0), 4
            )
            for target in _SURVIVAL_DAYS
        }

        half_life = None
        if 0.0 < survival <= 0.5:
            half_life = round(days * math.log(0.5) / math.log(survival), 1)

        rate = min(max(survival, 0.0), 1.0)
        annualized = (1.0 - rate ** (365.0 / days)) * 100.0
        return curve, half_life, round(annualized, 2), None

    @staticmethod
    def _content_drift(
        matched: list[str], original_rows: dict, fresh_rows: dict, content_idx: str | None
    ) -> tuple[int, list[str]]:
        if not content_idx:
            return 0, []
        changed = [
            rid for rid in matched
            if normalized_text_hash(as_str(get(original_rows[rid], [content_idx])))
            != normalized_text_hash(as_str(get(fresh_rows[rid], [content_idx])))
        ]
        return len(changed), changed

    @staticmethod
    def _source_type_risk(original_rows: dict, source_idx: str | None) -> dict | None:
        """Classify source values as high-risk, durable, or unknown."""
        if not source_idx:
            return None
        counts = {"high_risk": 0, "durable": 0, "unknown": 0}
        by_type: dict[str, str] = {}
        for row in original_rows.values():
            value = as_str(get(row, [source_idx])) or "(unknown)"
            lowered = value.lower()
            if any(hint in lowered for hint in _HIGH_RISK_HINTS):
                risk = "high_risk"
            elif any(hint in lowered for hint in _DURABLE_HINTS):
                risk = "durable"
            else:
                risk = "unknown"
            counts[risk] += 1
            by_type[value] = risk
        total = sum(counts.values())
        share = counts["high_risk"] / total if total else 0.0
        return {
            "column": source_idx,
            "high_risk": counts["high_risk"],
            "durable": counts["durable"],
            "unknown": counts["unknown"],
            "high_risk_share": round(share, 4),
            "by_type": by_type,
        }

    def _representativity(
        self, original_rows: dict, surviving: set[str], text_col_option: str = "",
        warnings: list[str] | None = None,
    ) -> dict:
        # Compare on a text field, not the first column (usually an id).
        cols = list(next(iter(original_rows.values()), {}).keys()) if original_rows else []
        text_col: str | None = None
        if text_col_option:
            text_col = next((str(c) for c in cols if norm_key(c) == norm_key(text_col_option)), None)
            if text_col is None and warnings is not None:
                warnings.append(
                    f"Representativity: text_column '{text_col_option}' not found — "
                    "auto-selecting a field."
                )
        if text_col is None:
            best_avg = -1.0
            for col in cols:
                lens = [len(as_str(r.get(col))) for r in original_rows.values()]
                avg = sum(lens) / len(lens) if lens else 0.0
                if avg > best_avg:
                    best_avg, text_col = avg, str(col)
            if text_col is not None and warnings is not None:
                warnings.append(
                    f"Representativity: auto-selected '{text_col}' as the longest-average text "
                    "field — set text_column to choose explicitly."
                )

        def avg_len(ids, col: str | None) -> float:
            if col is None:
                return 0.0
            lens = [len(as_str(original_rows.get(rid, {}).get(col))) for rid in ids]
            return round(sum(lens) / len(lens), 1) if lens else 0.0

        survivor_ids = {r for r in surviving if r in original_rows}
        orig_lens = [len(as_str(original_rows[r].get(text_col))) for r in original_rows] if text_col else []
        surv_lens = [len(as_str(original_rows[r].get(text_col))) for r in survivor_ids] if text_col else []

        return {
            "original_count": len(original_rows),
            "surviving_count": len(surviving),
            "field": text_col,
            "note": "Text stays fairly representative as data decays — value here is "
                    "documentation and removal, not dramatic findings.",
            "avg_field_len_original": avg_len(original_rows, text_col),
            "avg_field_len_surviving": avg_len(survivor_ids, text_col),
            "ks_statistic": round(ks_statistic(orig_lens, surv_lens), 3),
        }

    @staticmethod
    def _rid(row: dict, id_idx: str | None) -> str | None:
        if id_idx:
            val = as_str(get(row, [id_idx]))
            return val or None
        return find_id(row)

    @staticmethod
    def _guess_snapshot(snaps: list[str], want: str) -> str:
        """Pick the original/fresh marker without trusting alphabetical order."""
        old_hints = ("orig", "old", "before", "first", "base", "v1")
        new_hints = ("fresh", "new", "after", "second", "current", "latest", "v2", "recollect")
        hints = old_hints if want == "old" else new_hints
        for snap in snaps:
            if any(h in snap for h in hints):
                return snap
        # Fall back to explicit order: original first, fresh second.
        return snaps[0] if want == "old" else snaps[-1]

    @staticmethod
    def _resolve(rows: list[dict], name: str) -> str | None:
        if not rows:
            return None
        lowered = name.strip().lower()
        for key in rows[0]:
            if str(key).strip().lower() == lowered:
                return str(key)
        return None

    @staticmethod
    def _guess(rows: list[dict], candidates: list[str]) -> str | None:
        for cand in candidates:
            found = DecayWatchLogic._resolve(rows, cand)
            if found:
                return found
        return None

    @staticmethod
    def _finding(severity: str, field: str, message: str, record_id: str | None, metadata: dict) -> dict:
        return {"severity": severity, "field": field, "message": message,
                "record_id": record_id, "metadata": metadata}


def run(rows: list[dict], options: dict[str, Any] | None = None) -> ToolResult:
    return DecayWatchLogic().run(rows, options or {})
