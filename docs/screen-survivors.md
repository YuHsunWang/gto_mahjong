# How many candidates should survive the EV screen (DEV-121)

Measured 2026-09-23 with `scripts/screen_survivors_probe.py`.

## What the code actually does

`ev_rank` prices every legal discard on a 24-trial pilot, drops candidates
whose interval cannot reach the best lower bound, and then applies `top_k` as
both floor and cap. Because of that, exactly `min(top_k, legal)` candidates
survive (plus the fold entry), whatever the intervals say. With production
`EV_TOP_K = 5`, the interval screen only chooses *which* five survive, and even
that only when it cuts below five.

## Setup

- 46 cases: 40 distinct quiz positions (`generate_position` from seed 1) and
  the six `ev_benchmark.benchmark_corpus()` states. Committed calibration,
  default scheme for quiz positions.
- Reference: exhaustive `ev_rank`, 2,000 sims, on a seed salted away from the
  one the rules use, so no rule is graded on its own noise.
- Rules, each at production `REFINE_SIMS = 200`, each in a fresh process:

| rule | floor | cap |
|---|---|---|
| S0 (production) | 5 | 5 |
| S1 | 1 | none |
| S2 | 2 | none |
| S3 | 3 | 3 |
| S4 | 8 | 8 |
| EX | exhaustive | |

## Results

| rule | recall@1 | mean regret (tai) | worst regret | mean survivors | total seconds |
|---|---|---|---|---|---|
| S0 | 29/46 | 0.0718 | 0.8010 | 5.48 | 227.8 |
| S1 | 26/46 | 0.0947 | 0.8010 | 10.96 | 284.9 |
| S2 | 26/46 | 0.0947 | 0.8010 | 10.96 | 284.5 |
| S3 | 27/46 | 0.1621 | 3.0465 | 3.65 | 209.1 |
| S4 | 28/46 | 0.0747 | 0.8010 | 8.04 | 255.3 |
| EX | 26/46 | 0.0947 | 0.8010 | 11.22 | 261.3 |

Paired regret difference against S0 (mean, standard error over 46 cases,
cases where the pick differs):

| rule | mean | SE | cases differing |
|---|---|---|---|
| S1 | +0.0230 | 0.0144 | 4 |
| S3 | +0.0904 | 0.0684 | 4 |
| S4 | +0.0030 | 0.0023 | 2 |
| EX | +0.0230 | 0.0144 | 4 |

## What this shows

1. **The interval screen does almost nothing.** Without a cap (S1) it removed a
   candidate in only 7 of 46 cases and picked exactly what exhaustive picked in
   every case. All of the pruning comes from the cap.
2. **No rule is distinguishable from production on regret.** Every paired
   difference is within 1.6 SE of zero and rests on 2-4 cases. The reference
   itself cannot separate its own top two in 33 of 46 cases (gap inside
   1.96 SE; median per-candidate SE 0.111 tai), so recall@1 differences of a
   few cases are noise.
3. **Pruning saves little time.** Exhaustive costs 15% more than production
   (261 s vs 228 s). Where the rest goes was not profiled here.
4. **Cutting to three is the one visible risk.** S3 had the only large miss,
   3.05 tai on one case, where the true best discard was not among the three
   pilot leaders.

## Recommendation

Keep production at `top_k = 5`: nothing measured here justifies moving every
seeded baseline. The floor and cap are now separable (`_screen_floor`,
`_screen_cap`, private, used only by the probe), so a later change can move
one without the other. The `top_k=34` trap in the original ticket is real but
cheap: it turns the rank exhaustive, which costs about 15% time and no regret.
