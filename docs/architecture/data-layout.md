# Data layout

Adopted: 2026-08-31

This repository treats persisted observations, simulation measurements, calibration tables, fixed evaluation corpora, and visual evidence as data. Ordinary source code and prose-only design documents are not datasets. Code-defined corpora and generated JavaScript lookup data are cataloged because tests or the server consume them at runtime.

## Lifecycle layers

| Layer | Purpose | Physical paths in this repository | Downstream contract |
|---|---|---|---|
| Raw inputs | Externally acquired, append-only source material before normalization. | None committed today. Future committed inputs belong under `data/raw/<source>/`; local or restricted inputs belong under `data/raw/local/` and are ignored. | Once consumed by a recorded build, bytes and source identifiers are immutable. Corrections are new versions, not in-place rewrites. |
| Generated simulation output | Seeded engine output, intermediate counts, checkpoints, and working caches. | No committed standalone raw simulation dump today. Temporary output belongs under `data/generated/work/` or `artifacts/work/`, both ignored. | No downstream code may depend on a working path. A promoted output must record seed, sample size, configuration, source-data identity, and code commit. |
| Curated reference tables | Reviewed data that tests, command-line tools, or the server may consume as an input. | `data/calibration.json`; `data/calibration-independent.json`; the fixed corpora in `taimahjong/reference_ev.py`, `taimahjong/ev_benchmark.py`, and `taimahjong/empirical_corpus.py`; `server/static/js/tile-faces.js`. | Paths, primary keys, units, and reader-visible columns are frozen. A schema or path change requires a compatibility reader or coordinated updates to every reader and test. Values may change only through a documented regeneration and review. |
| Report artifacts | Human-readable summaries and visual evidence derived from code, curated tables, or recorded runs. | Cataloged result-bearing Markdown files in `docs/`, `docs/screenshots/`, and `docs/ui-baseline/`. | Reports are not runtime inputs. Their path may move only with all links updated. Every numerical claim must retain its command, seed/sample budget, source dataset identity, and code version, or be marked as a provenance gap. |

The authoritative inventory is `catalog/datasets.toml`. A path's catalog entry, not its filename alone, decides its lifecycle layer.

## Immutable downstream interfaces

- `data/calibration.json` is the production calibration location used by the CLI, self-play, tests, and server. Its calibration cell keys and probability/count fields are a runtime interface.
- The names, seeds, state fields, and ordering of committed reference corpora are test interfaces. Existing cases must not be silently edited; extend or version a corpus and update its tests deliberately.
- `server/static/js/tile-faces.js` must continue exporting the symbols imported by `server/static/js/tiles.js`.
- Report artifacts must never become implicit computation inputs. If a later calculation needs report data, persist the machine-readable upstream result separately and catalog that result.

## Placement rule for a new data file

1. If bytes originate outside this repository and have not been transformed, place them in `data/raw/<source>/` and record source identity and licensing.
2. If a simulation or analysis can be regenerated and is not yet reviewed for downstream use, write it to `data/generated/<study>/`. Use `data/generated/work/` only for ignored checkpoints and scratch output.
3. If runtime code or tests intentionally consume it as a stable lookup/reference, promote it to `data/reference/<dataset>/` unless an existing public path such as `data/calibration.json` is frozen. Add compatibility before changing a frozen path.
4. If it exists only to communicate results, put machine-readable output under `artifacts/reports/<study>/` and link a concise narrative from `docs/`. Visual review evidence belongs under `artifacts/visual/<study>/`. Existing `docs/` artifacts remain in place in phase 1 because their producers or exact provenance are not always known.
5. In the same commit, add or update `catalog/datasets.toml`, regeneration documentation, consumers, tests, and `.gitignore`. A committed generated result must record code commit, exact command, input identities, seed, and sample size. If any are unavailable, use `owner = "unknown"` and `known_gap`; do not infer them.

## Migration log

| Date | Decision | Paths affected | Compatibility action |
|---|---|---|---|
| 2026-08-31 | Adopt four lifecycle layers and `catalog/datasets.toml` as the inventory. | Repository-wide | Added a catalog contract test; no runtime behavior changed. |
| 2026-08-31 | Freeze current runtime paths for calibration, embedded corpora, and tile-face data. | `data/calibration.json`, `taimahjong/*corpus*.py`, `taimahjong/reference_ev.py`, `taimahjong/ev_benchmark.py`, `server/static/js/tile-faces.js` | Documented current reader contracts; no file was renamed. |
| 2026-08-31 | Establish ignored homes for future local raw data and working output. | `data/raw/local/`, `data/generated/work/`, `artifacts/work/` | Updated `.gitignore`; no existing file was deleted or moved. |
| 2026-08-31 | Defer moving legacy report artifacts until provenance is repaired. | Cataloged result-bearing files under `docs/` | Avoided link churn and accidental reclassification; future moves must update every reference in the same commit. |
