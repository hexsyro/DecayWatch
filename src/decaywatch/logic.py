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
"""

from __future__ import annotations

from typing import Any

from decaywatch.common import ToolResult, as_str, find_id, get, opt_int, opt_list
from decaywatch.stats import chi_square_contingency, chi_square_sf, ks_statistic, wilson_interval

DIRECT_RECHECK_WARNING = (
    "Direct re-checks are disabled: re-querying platforms can violate their terms. "
    "Upload a fresh re-collection instead and use snapshot comparison "
    "(set mode=snapshot, the default)."
)


class DecayWatchLogic:
    """Dataset-decay reporter over snapshot pairs."""

    def run(self, rows: list[dict], options: dict[str, Any]) -> ToolResult:
        mode = as_str(options.get("mode", "snapshot")).lower() or "snapshot"
        if mode == "direct":
            return ToolResult(
                status="success",
                findings=[],
                warnings=[DIRECT_RECHECK_WARNING, "Review each platform's rules before any direct re-check."],
                summary={"checked": len(rows), "mode": "direct", "rechecks": "disabled"},
            )

        id_col = options.get("id_column")
        snap_col = options.get("snapshot_column")
        status_col = options.get("status_column")
        seg_col = options.get("segment_column")
        max_examples = max(1, opt_int(options, "max_examples", 5))

        findings: list[dict] = []
        warnings = ["Snapshot comparison only — no platforms were contacted by this run."]

        id_idx = self._resolve(rows, str(id_col)) if id_col else None
        if id_idx is None:
            # Fall back to best-effort record ids.
            id_idx = self._resolve(rows, "id")

        snap_idx = self._resolve(rows, str(snap_col)) if snap_col else self._guess(
            rows, ["snapshot", "collection", "wave", "round"])
        status_idx = self._resolve(rows, str(status_col)) if status_col else self._guess(
            rows, ["status", "availability", "present", "state"])
        seg_idx = self._resolve(rows, str(seg_col)) if seg_col else None

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
                                  summary={"checked": len(rows), "mode": "snapshot"})
            user_old = options.get("original_value")
            user_new = options.get("fresh_value")
            old_val = str(user_old or self._guess_snapshot(snaps, "old"))
            new_val = str(user_new or self._guess_snapshot(snaps, "new"))
            if user_old is None and user_new is None and (
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
                for s in (opt_list(options.get("present_values")) or ["present", "alive", "found", "active"])
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
                              summary={"checked": len(rows), "mode": "snapshot"})

        if not original_ids:
            warnings.append("No original-snapshot records identified — check id/snapshot columns.")
            return ToolResult(status="success", findings=[], warnings=warnings,
                              summary={"checked": len(rows), "mode": "snapshot"})

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

        # Metadata drift on matched records.
        drift_fields: list[dict] = []
        matched = [rid for rid in surviving if rid in original_rows and rid in fresh_rows]
        if matched:
            sample_cols = [c for c in (list(rows[0].keys()) if rows else [])
                           if str(c) not in {str(snap_idx), str(status_idx)}][:20]
            for col in sample_cols:
                changed = sum(
                    1 for rid in matched
                    if as_str(original_rows[rid].get(col)) != as_str(fresh_rows[rid].get(col))
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
        representativity = self._representativity(original_rows, surviving)

        # Is decay segment-dependent? Chi-square over the survived/vanished
        # contingency table (needs 2+ segments with 5+ originals each).
        heterogeneity = self._segment_heterogeneity(seg_table)


        # Purge list (capped in findings; full count in summary; export is Pro).
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
                f"... and {len(vanished) - max_examples} more purge candidates "
                "(full list is a Pro export).",
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
            "purge_count": len(vanished),
            "purge_preview": vanished[:50],
            "purge_ids": vanished[:10000],
            "fresh_only_count": len(fresh_only),
            "fresh_only_preview": fresh_only[:50],
        }
        return ToolResult(status="success", findings=findings, warnings=warnings, summary=summary)

    @staticmethod
    def _segment_heterogeneity(seg_table: dict[str, list[int]]) -> dict | None:
        """Chi-square test: does survival differ by segment?

        Needs 2+ segments with 5+ originals each; otherwise there is no power
        and the test stays silent.
        """
        eligible = {seg: counts for seg, counts in seg_table.items() if sum(counts) >= 5}
        if len(eligible) < 2:
            return None
        table = [[float(counts[0]), float(counts[1])] for counts in eligible.values()]
        stat, dof = chi_square_contingency(table)
        p_value = chi_square_sf(stat, dof)
        return {
            "chi2": round(stat, 2),
            "dof": dof,
            "p_value": round(p_value, 4),
            "heterogeneous": p_value < 0.05,
            "segments": sorted(eligible),
        }

    def _representativity(self, original_rows: dict, surviving: set[str]) -> dict:
        # Compare on the longest-text field, not the first column (which is
        # usually an id and says nothing about content drift).
        cols = list(next(iter(original_rows.values()), {}).keys()) if original_rows else []
        text_col = None
        best_avg = -1.0
        for col in cols:
            lens = [len(as_str(r.get(col))) for r in original_rows.values()]
            avg = sum(lens) / len(lens) if lens else 0.0
            if avg > best_avg:
                best_avg, text_col = avg, str(col)

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
