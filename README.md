# DecayWatch

Datasets rot. Links die, accounts get deleted, pages get rewritten, and the
collection you cited last year is quietly thinner today. DecayWatch measures
how much of it is still there.

## Why this exists

You collected a dataset. You shipped analysis on it. Six months later, nobody
knows what fraction of those records still resolves, or whether the parts that
vanished were representative or a biased sample. DecayWatch answers that with
arithmetic instead of a shrug.

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
- **Purge list** — the ids that vanished, so you can decide what leaves your
  dataset too.

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
  "version": "0.1.0",
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
    "purge_count": 1,
    "purge_preview": ["r004"]
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
from decaywatch import run

result = run(rows, {"segment_column": "segment"})
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
  originals and it stays silent rather than pretend to a p-value.
- **Drift is field-level.** It flags that `author` changed; it does not judge
  whether the change mattered.

## License

MIT. See [LICENSE](LICENSE).
