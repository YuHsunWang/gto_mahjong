# EV reference report

Command:

```bash
python3 scripts/ev_reference_report.py --sims 24
```

Re-recorded on 2026-08-11 against the current 26-case corpus. The previous
version of this file reported a 2-case corpus from 2026-07-23 and was stale.
Timings are wall-clock observations on this machine, not service SLOs.

## MJ-006 current approximation vs exact small wall

At the script's default budget (`--sims 24`):

- exact cases: **26**;
- candidate comparisons: **336**;
- mean absolute actor-EV error: **0.0 value units**;
- top-1 agreement: **100.0%**;
- non-tied ranking pairs: 688;
- ranking inversion rate: **0.0%**;
- mean / max top-1 regret: **0 / 0**;
- rank correlation: **1.0**.

### Why the error is exactly zero, and why more sims makes it worse

These numbers are not "the Monte Carlo happened to be very accurate." For the
shallow states in this corpus the production path does not sample the wall at
all. When an injected wall has four or fewer tiles, `ev_rank` enumerates its
permutations and cycles through them deterministically
([`taimahjong/ev.py:1348`](../taimahjong/ev.py)):

```python
orders = tuple(permutations(wall)) if len(wall) <= 4 else ()
```

A four-tile wall has `4! = 24` orderings, so a budget of 24 visits each ordering
exactly once. That is the exact expectation, not an estimate of it — hence
0.0 error.

It follows that the residual error is a function of how evenly `sims` divides
24, not of sample size. Measured on the same corpus:

| `sims` | relation to 24 | mean absolute EV error |
|---:|---|---:|
| 24 | 1 x 24 | **0.0** |
| 48 | 2 x 24 | **0.0** |
| 25 | 24 + 1 | 0.1291 |
| 1000 | 41 x 24 + 16 | 0.0126 |

At `sims = 1000`, 16 orderings are visited 42 times and 8 are visited 41, so the
orderings are weighted unequally. The resulting 0.0126 is **permutation-weighting
imbalance, not sampling noise** — which is why raising the budget 40x moves the
error away from zero rather than toward it. Top-1 agreement, inversion rate and
rank correlation are unaffected at every budget tested.

### What this does and does not certify

Passing this gate is necessary, not sufficient. The comparison injects the
oracle's own discard policy, so it certifies terminal classification,
settlement, and aggregation — **not** the realism of the production opponent
model, and not mid-game EV, where `ev_rank` can run as many as 24 turns against
a wall far too large to enumerate. The corpus is limited to walls of at most
four tiles and states with no declared melds
([`taimahjong/reference_ev.py:303`](../taimahjong/reference_ev.py)).

## MJ-008 fixed top-k vs confidence screening vs exhaustive

Pre-declared target: top-1 recall **>=99%**.

The six seeded cases cover early/mid/late wall, declared opponents, flush
states, dealer streak, and both payout schemes.

| selector | recall@1 | mean regret | worst regret | total latency |
|---|---:|---:|---:|---:|
| legacy fixed top-k | 83.33% | 0.25 | 1.5 | 2.94 s |
| two-stage confidence-bound | 100.00% | 0 | 0 | 1.61 s |
| exhaustive reference | 100.00% | 0 | 0 | 1.25 s |

The fixed selector missed `flush-hand`: fixed top was tile 6, exhaustive top was
tile 7, regret 1.5. Because 83.33% missed the 99% bar, production selection uses
the two-stage confidence-bound screen. `exhaustive=True` remains opt-in and
evaluates every legal discard at the full requested budget.

On this small corpus exhaustive is still the fastest of the three, because the
confidence screen runs a pilot before the full-budget finalists and the corpus is
too small for pruning to pay for that pilot. That is an explicit tradeoff, and it
does not justify reverting to the selector that failed the recall gate.
