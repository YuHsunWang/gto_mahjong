# Hidden-world strata trade-off

Measured 2026-08-07 on the isolated `feat/strata-tradeoff` worktree. The
recommendation is to **retain `PRODUCTION_HIDDEN_WORLD_STRATA = 32` for now**.
At `sims=200`, a pool of 200 makes the reported intervals materially narrower,
but this sample showed no decision-resolution gain, costs about 8% more wall
time, and would invalidate a wide set of seeded product baselines. No production
constant was changed.

## Method

The reproducible probe is `scripts/hidden_world_strata_probe.py`. Every timed
configuration/repeat ran in a fresh foreground process; configurations never
shared a process, and no jobs ran in parallel. Timings cover the `ev_rank`
calls, excluding interpreter startup and calibration-file loading.

The historical reproduction used its original hand, opponent, `turns=8`,
`sims=200`, `seed=30`, `top_k=5`, and no calibration. Each pool setting had five
fresh-process repeats (10 processes total). The seed was intentionally held
fixed, so output spread should be zero while timing spread remains observable.

The main study was a 2x2:

- hidden pool 32 (reuse/clustering on) versus 200 (all worlds distinct);
- native Latin-hypercube sampling (LHS) versus deterministic IID latent-tenpai
  quantiles (stratification off).

It used the six committed `taimahjong.ev_benchmark.benchmark_corpus()` states,
committed calibration, `sims=200`, and production `top_k=5`. Five independent
seed batches were run per cell: 30 position-seed evaluations per cell, 120 in
all, in 20 fresh processes. A position contributes its mean across screened
real candidates, so positions—not candidate counts—receive equal weight.

The IID control replaces only effective latent-tenpai quantiles after native
LHS generation, preserving sampler RNG consumption. Each run asserted that:

- the requested pool and effective LHS/IID mode were active;
- pool 32 produced balanced clusters of 6–7 trials and object reuse, while pool
  200 produced 200 distinct determinizations;
- all 200 terminal seeds were distinct and candidates shared the same worlds;
- calibration and the production confidence screener were active, with more
  legal candidates than the returned 5–6 finalists;
- every finalist received 200 trials and its SE exactly recomputed with the
  cluster-robust estimator.

## Historical result: widths held, timing did not

| hidden pool | mean candidate 95% CI width, mean [range] | wall time, mean [range], SD |
|---|---:|---:|
| 32 | 2.990 [2.990, 2.990] | 5.194 s [5.177, 5.233], 0.022 s |
| 200 | 2.088 [2.088, 2.088] | 5.632 s [5.584, 5.705], 0.045 s |

The prior 2.957 versus 2.139 widths therefore hold in direction and approximate
magnitude: fresh distinct worlds narrowed the mean width by 30.2%. The prior
2.7% timing claim does **not** reproduce. The fresh paired slowdown was 8.4%
(repeat range 7.6–9.0%, SD 0.52 percentage points). Absolute time is not compared
to the old run because only the current tree and machine state were measured.

## Separating clustering from stratification

Values below are means across the five repeats; brackets are repeat ranges.
Resolution is a positive lower endpoint for the descriptive paired 95% interval.

| pool / latent draw | candidate CI width | top-1/top-2 CI width | resolved | six-case time |
|---|---:|---:|---:|---:|
| 32 / LHS (current) | 5.902 [5.739, 6.233] | 4.710 [4.324, 5.074] | 3/30 | 31.371 s [30.912, 32.464] |
| 32 / IID | 5.868 [5.722, 6.292] | 4.884 [4.490, 5.118] | 1/30 | 31.296 s [31.038, 31.498] |
| 200 / LHS (proposed) | 4.589 [4.529, 4.632] | 3.810 [3.304, 4.134] | 2/30 | 33.807 s [33.125, 34.332] |
| 200 / IID | 4.601 [4.534, 4.648] | 3.784 [3.285, 4.146] | 4/30 | 33.768 s [33.040, 34.259] |

Under IID, widening the pool reduced candidate width by 1.267 (repeat range
1.074–1.720). With LHS, the total reduction was 1.313 (1.107–1.682), or 22.2%
of the current width. Their difference-in-differences—the contribution of finer
LHS resolution—was only 0.046 (−0.038 to 0.142). Thus reduced clustering
accounts for 96.5% of the observed candidate-width point estimate; this study
does not support a positive stratification-resolution contribution.

The paired-gap result points the same way. Pool widening reduced its width by
1.100 under IID (0.521–1.759) but by 0.899 under LHS (0.257–1.602); the LHS
interaction was −0.201 (−0.363 to −0.037), offsetting part of the clustering
gain in this sample. LHS itself changed candidate width by just −0.034 at pool
32 and +0.012 at pool 200, with unstable repeat signs. These five repeats do
not establish an LHS main effect.

## Decision-level result

Current 32/LHS resolved 3/30 top-two comparisons (10.0%); 200/LHS resolved
2/30 (6.7%). Each configuration's repeat rate ranged from 0/6 to 1/6. In the
matched positions, 25 remained unresolved, two changed unresolved-to-resolved,
three changed resolved-to-unresolved, and none remained resolved. The proposed
interval was narrower in 25/30 cases, but it did not buy a net decision.

The sampled top discard changed in 17/30 cases, so the two configurations often
compare different selected pairs. These intervals are explicitly post-selection
and not selection-adjusted; resolution rates are descriptive, not coverage
guarantees. Six benchmark positions are also not a representative sample of
live or deliberately hard quiz decisions. The data therefore refute a decision
gain on this measured set, but cannot establish that the population gain is
zero.

The calibrated LHS slowdown was 7.8% (repeat range 5.0–10.1%, SD 2.16
percentage points). Runtime and memory at `sims=400`, 800, and 5,000 were not
measured. At 200 trials, raising the cap to 200 and removing it are identical;
this experiment cannot compare them at higher budgets.

## Revalidation inventory if the cap changes

The tracked direct-call and literal inventory below is exhaustive for this
tree. External dashboards, saved API responses, and uncommitted baselines are
unknown.

- `taimahjong/quiz.py`: revalidate `REFINE_SIMS=200`, `ESCALATE_SIMS=800`,
  `EV_GAP_MIN=0.8`, verdict boundaries 0/`GOOD_DELTA=0.3`/1.0,
  `ESCALATE_MARGIN=0.15`, `MARGINAL_BAND=0.10`,
  `EV_EFFECT_SIZE_MIN=0.10`, and the cost gate `ESCALATE_MAX_SHANTEN=1`.
  Re-measure the recorded 0.05–0.15 cross-seed delta noise and approximately
  70 s 800-trial estimate. Seeded quiz selection, displayed ranks, verdicts,
  marginal flags, and cached values all change.
- `taimahjong/trainer.py` inherits the same 200/800 budgets and thresholds for
  discard, pass, call, and kong grading. `taimahjong/ev.py`'s production-world
  defaults (`ev_rank`, `evaluate_pass`, and `evaluate_discard`: `sims=400`),
  `server/api.py`'s EV request default 400/seed 7/maximum 5,000, and
  `taimahjong/__main__.py`'s EV default 400 need output, latency, and resource
  revalidation.
- `tests/test_quiz.py`: seeded positions 1–3 and grading witnesses; the refined
  variance bound `refined < 0.7 * cheap`; and CLI records 60–70 s generation,
  approximately 1.5 s grading, and its 180 s timeout.
- `tests/test_calibration_wiring.py`: low/high risk sweep
  `50: 2.8800/2.8800`, `100: 2.9800/3.1700`,
  `150: 3.0267/3.5333`, `200: 3.1600/3.8250`,
  `300: 3.0300/3.7467`; 200-trial net values `-2.245/-3.825`;
  low candidate set `19/18/20/9/2/0`, high set `11/1/10/9/0`; and its
  200/201-trial qualitative calibration assertions.
- Seeded regression witnesses needing rerun are `tests/test_fold_policy.py`
  (40, seed 17), `tests/test_crn.py` (1,000, seed 47), `tests/test_ev.py`
  (40/80, seeds 17/19), `tests/test_scheme.py` (60, seed 11), and the real-budget
  paths in `tests/test_trainer.py` (200/default 200). The pre-existing fold
  failure remains a baseline, not an authorized fix.
- `scripts/review_validation.py` and
  `docs/codex-gpt-5.6-sol-full-review.md`: re-record the 96-trial cells at seeds
  3/13/23 and aggregate top choices `1m=4, 9m=2`; fold `net=0`, best real
  `1.75`, result `false`; and aggregate 15.18 s / 81,936 KiB resource record.

The following committed values are **not** invalidated by raising/removing the
cap: `SCREENING_EFFECT_MARGIN=0.10`, production `top_k=5`, and its 24-trial
pilot; `ENDGAME_EV_GAP_MIN=1.2` generation at `EV_SIMS=24`;
`PRUNING_RECALL_TARGET=0.99` and the 24-trial `docs/ev-reference-report.md`
numbers; `taimahjong/reference_ev.py`'s 26 injected oracle cases and thresholds
(1.0 MAE, 0.90 top-1, 0.05 inversions, 0.25 mean regret, 1.0 max regret, 0.90
correlation); `tests/test_symmetry.py`'s `TRIALS=1200`,
`BIAS_TOLERANCE=0.5`, and `MIN_ACTOR_WIN_SHARE=0.70`; and
`data/calibration.json`. They either use at most 32 trials, bypass production
hidden worlds, call the one-world sampler directly, or are generated by a
different simulation path. Endgame grading still inherits the affected
200/800-trial quiz path even though its generation threshold does not.

## Recommendation and cost

Keep 32 and retain all current baselines. Changing to 200 would buy a measured
22.2% candidate-width reduction, overwhelmingly from reduced clustering, at a
measured 7.8% calibrated runtime cost. It did not improve the measured decision
rate (3/30 to 2/30), and 25/30 decisions stayed unresolved. That is insufficient
benefit to pay both the runtime cost and the revalidation cost above.

A future change should require a predeclared, production-like corpus enriched
for currently unresolved decisions and must separately measure 200, 400, and
800-trial budgets plus peak memory. Thresholds must be judged against product
requirements, not tuned to make the current model pass. Until then, neither a
cap of 200 nor removal is supported by these data.
