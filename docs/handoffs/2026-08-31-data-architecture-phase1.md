# Data architecture phase 1 handoff

Date: 2026-08-31

## Delivered

- Adopted the four-layer data layout in `docs/architecture/data-layout.md`.
- Cataloged every persisted dataset identified by this audit in `catalog/datasets.toml`, including runtime calibration, code-defined corpora, result-bearing reports, visual evidence, and tile-face lookup data.
- Added `tests/test_dataset_catalog.py` to enforce catalog fields, unique identifiers, allowed layers, and existence of every non-optional path.
- Recorded reproducibility, staleness, schema-drift, generated-as-input, and unknown-provenance findings in `docs/architecture/reproducibility-findings.md`.
- Added ignored homes for future local raw inputs and scratch/generated work. No existing file was moved: no tracked path could be proven to be disposable scratch output, and phase 1 forbids risky provenance guesses.

## Contributor rules

1. Classify every new persisted data file before committing it, using the placement rule in `docs/architecture/data-layout.md`.
2. Update `catalog/datasets.toml` in the same commit. Never guess a producer; use `owner = "unknown"` and a precise `known_gap`.
3. A committed simulation result records exact command, code commit, input hashes, seed, sample size, configuration, schema, and primary key.
4. Do not use Markdown tables as computation inputs. Persist and catalog machine-readable upstream results first.
5. Treat `data/calibration.json`, embedded corpus names/order/schema, and tile-face exports as downstream interfaces.
6. Move or rename a cataloged artifact only with all code, test, server, README, and documentation references updated in the same commit.

## Deliberately not done

- No solver, expected-value engine, calibration formula, server API, or public function was changed.
- No simulation batch was run and no result value was recalculated.
- No calibration table was regenerated; the production table's missing prior-input bytes make byte reproduction impossible from the current repository alone.
- No legacy artifact was moved. The visual bundles and several Markdown reports have unknown producers, so relocation would add link churn without repairing provenance.
- The calibration format was not version-migrated, the incremental CLI writer was not changed, and the stale 2-case assessment was not rewritten. Those are follow-up implementation decisions, not low-risk phase-1 organization.
- The missing visual capture harness and incompatible tile-face generator were documented, not repaired.
