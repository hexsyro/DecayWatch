# Changelog

All notable changes to this project will be documented in this file.

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
