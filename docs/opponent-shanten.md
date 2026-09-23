# Where the sampled opponents sit (DEV-120)

Date: 2026-09-01, extended 2026-09-02

## The defect

`taimahjong/ev.py`'s `_sample_production_world` decides each opponent's hand
in two steps: draw against `tenpai_score` to see whether they are waiting, and
if they are, build a tenpai hand. Commit `d03bf1c` fixed the first step so the
tenpai rate scales with the public state. The second step had no counterpart:
an opponent who failed the tenpai draw was filled by `_draw_pool_tiles`, a
uniform draw from the unseen pool.

Uniform draws from 34 tile kinds almost never land on a hand two tiles from
tenpai. Measured over 400 sampled worlds and three opponent seats (one on an
eight-turn tsumogiri run, two discarding from hand, all at turn 8):

| shanten | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| uniform draw | 231 | **0** | **24** | 188 | 359 | 257 | 123 | 15 | 3 |

Shanten 1 and 2 together carried 2.0% of 1,200 sampled hands. The opponents
were either waiting or nearly hopeless, and the hands that actually apply
pressure — a player one tile from tenpai with turns left — were absent.

## What was measured

`taimahjong/selfplay.py` already computed each discarder's shanten to decide
`true_tenpai`; it now records the whole number as `true_shanten` rather than
only whether it is zero, at no extra cost.

`scripts/generate_opponent_shanten.py` tallies those observations against the
public state a reader would have had at that moment, keyed exactly as the
calibrated tenpai table is: `melds|turn_bucket|run_bucket`.

```bash
python scripts/generate_opponent_shanten.py \
    --games 4000 --seed-start 60001 --workers 4 --verify-games 12 \
    --out data/opponent-shanten.json
```

4,000 games at seeds 60001–64000, split 3,200 fit / 800 holdout by the same
every-fifth-game rule the calibration build uses. 149,363 observations across
49 cells. The marginal:

| shanten | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 |
|---|--:|--:|--:|--:|--:|--:|--:|--:|
| share | 0.121 | 0.251 | 0.292 | 0.193 | 0.108 | 0.029 | 0.005 | 0.000 |

On the 800 untouched holdout games, across the 38 cells with at least 30
non-tenpai observations, the mean total-variation distance between the fitted
and holdout distributions is 0.0451 and the worst cell is 0.1892. The pooled
marginal differs by 0.0046.

## How it is used

`taimahjong/opponent_shanten.py` reports the distribution **conditional on not
being tenpai**. The tenpai mass stays where `tenpai_score` puts it, so
`d03bf1c`'s fix is untouched and only the previously uniform remainder
changes. Cells under the lookup minimum back off through `melds|turn|*`, then
`*|turn|*`, then the pooled marginal; a cell with no non-tenpai observation at
all returns nothing and the caller falls through to the old uniform draw
rather than inventing a shape.

Two example cells at turn 8, no melds:

| cell | 1 | 2 | 3 | 4 | 5 |
|---|--:|--:|--:|--:|--:|
| `0\|7-12\|3+` (eight-turn tsumogiri run) | 52.7% | 37.9% | 8.0% | 1.5% | — |
| `0\|7-12\|0` (every discard from hand) | 32.2% | 42.2% | 20.0% | 5.3% | 0.3% |

The shanten draw is stratified per opponent the same way the tenpai draw is,
so the bounded hidden-world layer represents the distribution rather than
sampling it 800 times independently.

`_construct_shanten_hand` builds a hand at the drawn distance. Rejection
sampling cannot do this — landing on 1-shanten by uniform draw is the very
event that is missing — so the hand is built at tenpai and walked outward one
verified step at a time, each step swapping one tile for a pool tile and
keeping the swap only if shanten rose by exactly one.

## Result

Same 400 worlds, same three seats:

| shanten | 0 | 1 | 2 | 3 | 4 | 5 |
|---|--:|--:|--:|--:|--:|--:|
| uniform draw | 231 | 0 | 24 | 188 | 359 | 257 |
| observed distribution | 215 | 390 | 398 | 152 | 43 | 2 |

Shanten 1 and 2 go from 2.0% to 65.7% of sampled hands. The sampled mix
matches what the model predicts for these three seats (39.0% and 40.8%
expected against 39.0% and 41.0% observed).

Effect on the first three benchmark cases, 256 simulations each:

| case | before top | net | attack | risk | after top | net | attack | risk |
|---|--:|--:|--:|--:|--:|--:|--:|--:|
| `early-default` | 0 | 11.322 | 12.087 | 0.765 | 0 | 8.087 | 9.500 | 1.413 |
| `mid-declared` | 9 | 1.937 | 6.370 | 4.433 | 9 | 1.821 | 6.309 | 4.488 |
| `late-pressure` | 9 | −0.834 | 3.188 | 4.022 | 28 | −1.991 | 2.038 | 4.029 |

The direction is the one the ticket predicted: priced risk rises where the
opponents are undeclared and mid-hand (`early-default` nearly doubles), and
barely moves where an opponent has already declared tenpai and
`tenpai_score` already returned 1.0 for them (`mid-declared`). One of the
three top choices changes. Wall clock over the three cases was 0.97x, so
there is no material cost: hands with closer opponents terminate earlier,
which offsets the more expensive hand construction.

## What the change moved elsewhere

Two slow tests failed on the new sampler. Neither turned out to be a defect in
it, but both are worth recording because the next change to the opponent model
will hit the same two places.

**`test_symmetry.py` — the probe's own premise broke.** That file builds a
position where the answer is known by symmetry: it draws the acting seat's
hand from "the very distribution the sampler uses for opponents", so the four
seats are exchangeable and a correct model must pay the actor zero. It drew
that hand with `_draw_pool_tiles`, which was the same distribution until this
change and is not any more. Against the observed fill a uniform sixteen tiles
is about one full shanten behind:

| shanten | 1 | 2 | 3 | 4 | 5 |
|---|--:|--:|--:|--:|--:|
| observed, empty public state (`0\|1-6\|0`, n=36,819) | 4.4% | 20.2% | 34.7% | 29.5% | 9.3% |
| uniform sixteen tiles | 0.1% | 3.2% | 21.0% | 37.4% | 28.2% |

so the probe reported a −1.031 mean payment (se 0.112, n=1200, actor win share
0.80) for a model that had not become less symmetric. `_exchangeable_hand` now
mirrors `_sample_production_world`'s branch order, and the layer switches reach
the actor's draw as well as the opponents'. `BIAS_TOLERANCE` and
`MIN_ACTOR_WIN_SHARE` were not touched. Every arm now sits near zero:

| arm | mean payment | actor win share |
|---|--:|--:|
| all three layers on | +0.308 (se 0.170) | 1.08 |
| shanten layer off, both sides | +0.012 (se 0.099) | 1.00 |
| tenpai prior off, both sides | −0.037 (se 0.166) | 1.00 |
| all layers off | +0.049 (se 0.155) | 1.02 |

The probe keeps its power: put the actor back on the uniform seventeen-tile
draw and it returns −1.031 at a win share of 0.80 and fails.

**`test_empirical_game.py` — the headline regret moved to another role.** The
claim survives: the all-efficiency profile is still shown not to be an
equilibrium, `low > 0`. What changed is which role gains most by deviating to
safety, from role 0 (the actor) at +0.259 tai, 95% CI [+0.100, +0.555], to
role 3 at +0.153 tai, 95% CI [+0.075, +0.423]. The test was re-baselined to
the new role rather than loosened to stop naming one, so the next shift in
role attribution will be caught the same way this one was.

## Limits

**The shanten is observed; the shape at that shanten is constructed.** A hand
walked outward from tenpai is not distributed like a real hand at the same
distance. Counting lone tiles — a tile with no copy and no neighbour within
two ranks — over 300 constructed hands against self-play hands at the same
shanten:

| shanten | self-play | constructed |
|---|--:|--:|
| 1 | 0.27 | 0.70 |
| 2 | 0.92 | 1.60 |
| 3 | 1.81 | 2.59 |

Constructed hands hold roughly 0.7 lone tiles too many. Two earlier orderings
of the walk were worse in opposite directions: preferring isolated incoming
tiles gave 1.22 / 2.43 / 3.66, and preferring connected ones gave
0.19 / 0.51 / 1.06. The committed walk imposes no preference — it shuffles the
whole pool and takes the first swap that lands — so the residual gap comes
from the absence of a discard policy, not from an authored heuristic. Real
hands are shaped by a player who throws lone tiles away; a hand built by
walking outward has never discarded anything.

Closing that gap means sampling opponent hands from played-out trajectories
rather than constructing them, which is a much larger piece of work than this
ticket.

**The distribution is bot ecology, not human play.** It comes from the same
`attack, cautious, ev_aware, ev_aware` self-play mix as the calibration table,
and the `ev_aware` seats read `data/calibration.json` while they play. That is
not the DEV-119 feedback loop — this document is not an input to its own
generation — but it does mean the shanten distribution describes how these
bots develop hands.

**Regenerate when the engine moves.** The distribution is a property of the
self-play policies and the shanten engine. It is a separate document from
`data/calibration.json` precisely so that either can be rebuilt without
invalidating the other's evidence.
