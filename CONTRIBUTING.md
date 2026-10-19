# Contributing

Thanks for considering a contribution. DecayWatch is deliberately narrow, and
that's worth protecting.

## Ground rules

- **Keep it stdlib-only at runtime.** No third-party dependencies in
  `src/decaywatch/`. Statistics live in `stats.py`.
- **Never add automatic platform queries.** The direct re-check mode is
  disabled on purpose. A change that quietly reaches out to a platform will be
  rejected.
- **A statistic must decline to fire without enough data.** The chi-square test
  and Wilson bounds should stay silent or wide rather than overstate certainty.
  Add a test for the too-little-data path, not just the happy one.
- **No silent behavior changes.** If a threshold, default, or summary field
  changes, that goes in the changelog.

## Workflow

1. Open an issue describing the problem before starting work on anything
   bigger than a typo fix.
2. Fork, branch, make the change, add tests.
3. Run `python -m pytest` and make sure it's green.
4. Open a pull request that says what changed and why, in plain language.
