# Changelog

All notable changes to this project will be documented in this file.

## [0.2.0] - 2026-11-19

### Added

- Survival curve (`survival_curve`) at day 0/30/90/365, log-linear
  `half_life_days`, and `annualized_loss_pct` from a `date_column` with two
  parseable snapshot dates. Warns when dates are missing or the interval is
  under 30 days.
- Content-drift detection via `content_column`: normalized text hashes on
  matched ids, a low-severity `content_drift` finding with examples, and
  `summary["content_drift_count"]`. Explicitly distinct from link rot/disappearance.
- Source-type risk stratification via `source_type_column` (or the segment
  column): high-risk (`com`, `db-driven`, `pdf`) vs durable (`gov`, `edu`,
  `news`), emitted as `summary["source_type_risk"]` with a warning when more
  than 50% of originals are high-risk.
- `text_column` option for representativity field selection; warns when it
  auto-selects the longest-average column.
- `drift_columns` option to select metadata fields explicitly.
- Shared result contract: `RESULT_SCHEMA_VERSION = "1.1"` and `ToolResult`
  exported from the package; every `run()` summary carries
  `result_schema_version`, `skipped`, and `skip_reason` (status values unchanged).

### Fixed

- Purge overflow findings now say all ids are in `summary.purge_ids` instead of
  claiming the full list is a Pro export.
- Chi-square segment heterogeneity now requires expected cell counts >= 5;
  otherwise the test is skipped with a warning instead of reporting an
  unreliable p-value.
- Metadata drift excludes id/snapshot/status/segment (and date/source) columns.
- Malformed config value types no longer raise out of `run()`; the CLI exits 2
  with a clear stderr message.
- Removed the broken template `.github/workflows/python-package.yml` (Python 3.9,
  nonexistent requirements.txt, flake8); the maintained CI/CD workflows remain.

### Inspiration

- Pew Research Center, "When Online Content Disappears" — https://www.pewresearch.org/data-labs/2024/05/17/when-online-content-disappears
- "Link rot 2026 research" — https://broken-links-checker.com/blog/link-rot-2026-research
- "Reference rot" (PLOS) — https://pmc.ncbi.nlm.nih.gov/articles/PMC11152257

## [0.1.0] - 2026-10-19

### Added

- Initial release.
- Snapshot comparison: survival rate overall and by segment, with Wilson confidence bounds.
- Status-column fallback for files that only mark present/removed rows.
- Segment heterogeneity via a chi-square test over the survived/vanished table.
- Metadata drift detection on records surviving both snapshots.
- Representativity report comparing survivors to the original set (KS statistic on field length).
- Purge list of vanished ids.
- Direct re-check mode intentionally disabled, with a warning explaining the terms risk.
- CLI with table/json/csv/md, --fail-on exit codes, JSON config.
- Importable library API: decaywatch.run(rows, options).
