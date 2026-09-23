# Reproducibility findings

Audit date: 2026-08-31. Findings are ordered by severity. “Regenerable” means the repository records the seed, sample size, code version, inputs, and an exact artifact-producing command; merely being able to rerun a related script is not enough.

## Critical

### R1 — The documented incremental calibration command destroys required provenance and schema

Evidence: `README.md:294-295` directs contributors to append self-play into `data/calibration.json`. `taimahjong/calibration.py:234-258` rebuilds only `version`, `metadata`, `counts`, and `tables`; it does not carry forward the committed `quality` block. `tests/test_selfplay.py:304-316` requires committed holdout metadata and quality metrics. The committed file also says generation consumed the prior calibration table by hash (`data/calibration.json:243-271`), but those prior bytes are no longer present.

Failure scenario: a contributor follows the README command against the committed path. The file becomes a mixture of old and new counts, loses `quality`, and cannot reproduce the current artifact because the prior hashed input was overwritten. Runtime may still load it while the committed-data test fails or, worse, downstream results silently use a differently calibrated table.

Coverage: seed range and sample sizes are recorded, and a producer commit is recorded, but the shipped result is not regenerable from the recorded seed because its prior calibration input is unavailable.

### R2 — The named tile-face generator and the runtime reader have incompatible schemas

Evidence: `scripts/gen_tile_faces.py:79-98` writes `TILE_FACE_FONT` and `TILE_GLYPHS` to `server/static/js/tile-faces.js`. The committed file instead exports `FACE_TOKENS`, `NUMERAL_FACES`, `HONOR_FACES`, layout tables, and renderer functions (`server/static/js/tile-faces.js:1-34`). `server/static/js/tiles.js:3` imports the latter interface.

Failure scenario: a contributor runs the script's documented command. It overwrites the runtime module with a different export schema, and the browser fails to import `HONOR_FACES`, `NUMERAL_FACES`, `tileBackSvg`, or `tileFaceSvg`. The committed file's actual producer is therefore recorded as unknown.

## High

### R3 — Historical EV replacement evidence is stale relative to the current corpus

Evidence: `docs/ev-replacement-assessment.md:17-26` reports 2 exact cases and 30 candidate comparisons. `docs/ev-reference-report.md:9-24` explicitly says that 2-case version is stale and reports the current 26-case corpus. `taimahjong/reference_ev.py:180-186` now gates on at least 26 cases.

Failure scenario: a design decision cites the older 50% top-1 agreement and 100% inversion rate as current evidence even though those values describe 2 deliberately selected cases, not the current 26-case reference corpus.

### R4 — Report artifacts generally omit an exact artifact-producing command or code version

Evidence: `docs/batch-a-simulation-report.md:3-7` records 30 positions and the 32-trial budget but no command or code commit. `docs/hidden-world-strata.md:20-40` identifies the probe and experimental design but not the full command matrix or producing commits. `docs/ev-reference-report.md:3-7` gives a metric command, but `scripts/ev_reference_report.py:20-32` prints JSON and does not produce the Markdown file.

Failure scenario: a contributor reruns a plausible command on current code and overwrites a report with changed numbers, unable to determine whether the change is caused by code, environment, inputs, formatting, or a different command.

Coverage: the committed simulation-result reports in `catalog/datasets.toml` state individually whether seed and sample information is present. None of the Markdown simulation reports records all of seed, sample size, code version, and an exact Markdown-producing command; each is therefore marked non-reproducible from its recorded seed.

### R5 — Generated report numbers are used to motivate later computation without a machine-readable upstream artifact

Evidence: `docs/equilibrium-plan.md:1078-1088` records a 26-position × 60-world measurement and compares it to a prior recorded value. `docs/hidden-world-strata.md:153-163` uses the 24-trial EV report and calibration file to delimit affected consumers. The result-bearing reports persist only Markdown tables; their raw per-case or per-trial outputs are absent.

Failure scenario: later analysis copies rounded values from Markdown, losing precision and row-level uncertainty. A changed corpus or aggregation cannot be detected through a stable input hash, so a downstream conclusion can appear reproducible while depending on an undocumented report snapshot.

## Medium

### R6 — The strategy experiment report is explicitly stale relative to its writers

Evidence: `docs/experiments.md:18-21` says its tables predate paired second-moment fields and that only point estimates and sample sizes were saved. Current scripts emit paired contrast summaries (`scripts/streak_defense.py:132-154`, `scripts/kong_ev.py:83-100`).

Failure scenario: a reader treats the historical point estimates as uncertainty-supported comparisons even though the report itself says the paired moments needed to reconstruct intervals were never saved.

### R7 — Calibration writer and reader tolerate undocumented extensions, masking drift

Evidence: `scripts/generate_calibration.py:672-703` adds `quality` and, for the independent artifact, `audit`. `taimahjong/calibration.py:262-283` consumes `metadata`, `tables`, and `counts` but validates neither a schema version nor the extra blocks.

Failure scenario: a generator changes or drops audit/quality fields and runtime continues successfully, while audit tooling or tests later interpret the file as if those fields retained their old semantics.

### R8 — Visual evidence has unknown provenance

Evidence: `docs/ui-redesign-plan.md:92-95` requires a 63-image baseline and `docs/ui-redesign-plan.md:123-176` gives a capture fragment with deterministic `Math.random`, but no runnable capture harness exists in the tracked file list. The two README screenshots have only link references (`README.md:11`, `README.md:239`).

Failure scenario: screenshots are refreshed with a different viewport, seed, browser, or application commit and still look plausible. Pixel changes cannot be attributed or reproduced. The catalog therefore uses `owner = "unknown"` for all three visual bundles.

## Dataset regeneration summary

| Dataset class | Seed recorded? | Sample size recorded? | Code version recorded? | Regenerable? |
|---|---|---|---|---|
| `data/calibration.json` | Yes | Yes | Yes | No: prior calibration input bytes are missing. |
| `data/calibration-independent.json` | Yes | Yes | Yes | Yes, numerically, with the recorded command and commit. |
| Three code-defined corpora | Yes where stochastic evaluation uses one | Fixed row counts | Git supplies version | Yes as source-defined records; results still need their own run metadata. |
| Markdown simulation/research reports | Partial, per catalog entry | Partial, per catalog entry | Generally no | No complete report is fully regenerable. |
| Visual evidence bundles | Seed fragment only for one bundle | Viewport matrix described for one bundle | No | No. |
| Tile-face vector data | Not stochastic | 34 tile indices | Git supplies version | No: current producer is unknown and the legacy generator is incompatible. |
