# DecayWatch

Datasets rot. Links die, accounts get deleted, pages get rewritten, and the
collection you cited last year is quietly thinner today. DecayWatch measures
how much of it is still there.

## Why this exists

You collected a dataset. You shipped analysis on it. Six months later, nobody
knows what fraction of those records still resolves, or whether the parts that
vanished were representative or a biased sample. DecayWatch answers that with
arithmetic instead of a shrug.

## [0.2.0] - 2026-11-19

### Added

- Survival curve (`survival_curve`), log-linear `half_life_days`, and
  `annualized_loss_pct` from a `date_column` with two parseable snapshot dates.
- Content-drift detection via `content_column`: normalized text hashes for
  matched ids, a low-severity `content_drift` finding, and
  `summary["content_drift_count"]`. Clearly distinct from link rot/disappearance.
- Source-type risk stratification via `source_type_column` (or the segment
  column): high-risk (`com`, `db-driven`, `pdf`) vs durable (`gov`, `edu`,
  `news`), reported as `summary["source_type_risk"]` with a warning when more
  than half of originals are high-risk.
- `text_column` for explicit representativity field selection and
  `drift_columns` for explicit metadata-drift field selection.
- Shared result contract exported from the package: `RESULT_SCHEMA_VERSION`
  (`"1.1"`), `ToolResult`, and `summary["result_schema_version"]`,
  `summary["skipped"]`, `summary["skip_reason"]` on every run.

### Fixed

- Purge overflow findings now say all ids are in `summary.purge_ids` instead of
  claiming a Pro-only export.
- Chi-square segment heterogeneity now requires expected cell counts >= 5 and
  warns instead of reporting an unreliable p-value.
- Metadata drift ignores id/snapshot/status/segment bookkeeping columns.
- Representativity warns when it auto-selects the longest-average text field.
- Invalid config value types no longer escape `run()`; the CLI exits 2 with a
  clear stderr message. Removed the stale Python 3.9/flake8 CI workflow.

### Inspiration

- Pew Research Center, "When Online Content Disappears" — https://www.pewresearch.org/data-labs/2024/05/17/when-online-content-disappears
- "Link rot 2026 research" — https://broken-links-checker.com/blog/link-rot-2026-research
- "Reference rot" (PLOS) — https://pmc.ncbi.nlm.nih.gov/articles/PMC11152257

## How it works

DecayWatch compares **snapshots** — the original collection and a fresh
re-collection, in one file with a column marking which is which. No platform
access, no scraping, no terms risk.

- **Survival rate**, overall and by segment, with Wilson confidence bounds.
- **Segment heterogeneity** via a chi-square test, so you can tell "everything
  decayed a little" from "one slice collapsed."
- **Metadata drift** on records that survived both snapshots — the field that
  quietly changed on 40% of them.
- **Representativity** — do survivors still look like the original set? A
  KS statistic on field length.
- **Survival curve and decay rate** — survival at day 0/30/90/365, half-life,
  and annualized loss when both snapshots carry dates.
- **Content drift** — rewritten content on still-present records, deliberately
  reported separately from link rot/disappearance.
- **Source-type risk** — are the originals mostly commercial/db-driven/PDF, or
  durable gov/edu/news sources?
- **Purge list** — the ids that vanished, so you can decide what leaves your
  dataset too. Every id ships in `summary.purge_ids` (findings are capped).

It refuses to guess: rather than pretend to re-check a URL, it tells you why
direct re-checks are disabled and points you back at snapshot comparison.

## What it is not

It is not a scraper and it will not contact any platform for you. It reads two
files you already have.

## Install

Python 3.10+, no runtime dependencies.

```bash
git clone https://github.com/hexsyro/DecayWatch.git
cd DecayWatch
python -m pip install .
```

For development:

```bash
python -m pip install -e ".[dev]"
python -m pytest
```

## Usage

```bash
decaywatch examples/sample.csv --segment-column segment
```

Your file needs a column that marks original vs fresh rows (`snapshot`,
`collection`, `wave`, or `round`), or a status column (`status`, `availability`,
`present`, `state`) with present/removed values. Record ids come from `id` or a
recognized id column.

## Options

| Flag | What it does |
| --- | --- |
| `--mode {snapshot,direct}` | Snapshot comparison (default) or the disabled direct re-check |
| `--id-column COL` | Column holding the record id |
| `--snapshot-column COL` | Column marking original vs fresh rows |
| `--status-column COL` | Column marking present vs removed rows |
| `--segment-column COL` | Column to break survival down by |
| `--date-column COL` | Column holding per-row snapshot dates (survival curve / decay rate) |
| `--content-column COL` | Text column to hash and compare for content drift |
| `--source-type-column COL` | Column with source types for risk stratification (defaults to segment) |
| `--text-column COL` | Text column used by the representativity check |
| `--drift-columns COL [COL ...]` | Only compare these fields for metadata drift |
| `--original-value VAL` | Snapshot value that marks the original set |
| `--fresh-value VAL` | Snapshot value that marks the fresh re-collection |
| `--max-examples N` | Cap on purge-list examples in findings |
| `--config FILE` | JSON config; explicit flags win |
| `--format {table,json,csv,md}` | Output format (default `table`) |
| `--output FILE` | Write to file instead of stdout |
| `--fail-on {none,low,medium,high}` | Exit 1 if any finding is at or above this severity |
| `--version` | Print version and exit |

## Output (json)

```json
{
  "tool": "decaywatch",
  "version": "0.2.0",
  "status": "success",
  "findings": [
    {
      "severity": "medium",
      "field": "id",
      "message": "Purge candidate: record r004 disappeared at the source and should probably leave the dataset too.",
      "record_id": "r004",
      "metadata": {"check": "purge_list", "record_id": "r004"}
    }
  ],
  "summary": {
    "checked": 12,
    "mode": "snapshot",
    "comparison": "snapshots 'original' vs 'fresh'",
    "original_records": 6,
    "surviving_records": 5,
    "survival_rate": 0.8333,
    "survival_wilson_low": 0.4361,
    "survival_wilson_high": 0.97,
    "by_segment": {"blog": {"original": 3, "surviving": 2, "survival_rate": 0.667}},
    "segment_heterogeneity": {"chi2": 0.0, "dof": 1, "p_value": 1.0, "heterogeneous": false, "segments": ["blog", "news"]},
    "metadata_drift": [{"field": "author", "changed": 1, "of_matched": 5}],
    "content_drift_count": 0,
    "content_drift_examples": [],
    "survival_curve": {"day_0": 1.0, "day_30": 1.0, "day_90": 0.8333, "day_365": 0.8333},
    "half_life_days": null,
    "annualized_loss_pct": 48.1,
    "source_type_risk": {"column": "segment", "high_risk": 2, "durable": 4, "unknown": 0, "high_risk_share": 0.3333, "by_type": {"news": "durable", "blog": "unknown"}},
    "purge_count": 1,
    "purge_preview": ["r004"],
    "purge_ids": ["r004"],
    "result_schema_version": "1.1",
    "skipped": false,
    "skip_reason": null
  },
  "warnings": ["Snapshot comparison only — no platforms were contacted by this run."]
}
```

## Using it in CI

```bash
decaywatch snapshot.csv --segment-column segment --fail-on high || exit 1
```

Exit codes: `0` ran fine, `1` gate tripped, `2` input broken.

## Library use

```python
from decaywatch import RESULT_SCHEMA_VERSION, ToolResult, run

result: ToolResult = run(rows, {"segment_column": "segment"})
assert result.summary["result_schema_version"] == RESULT_SCHEMA_VERSION
result.summary["survival_rate"]
```

## Limitations, honestly

- **Snapshot comparison needs two snapshots.** If you never kept the original
  collection, this tool can't invent one. Status-column mode is a weaker
  fallback for files that only record present/removed.
- **Survival means "still in the re-collection."** It measures your collection
  pipeline, not the open web. If your re-collection is scoped differently, you
  are comparing scopes, not decay.
- **The chi-square test needs data.** Fewer than two segments with five or more
  originals, or any expected cell count below 5, and it stays silent (with a
  warning) rather than pretend to a p-value.
- **Drift is field-level.** It flags that `author` changed; it does not judge
  whether the change mattered. Content drift is reported separately from link
  rot: a rewritten body is not a disappeared record.
- **Decay curves need dates.** Without two parseable snapshot dates at least 30
  days apart, `survival_curve`, `half_life_days`, and `annualized_loss_pct` are
  `null` and a warning explains why.

## License

MIT. See [LICENSE](LICENSE).
