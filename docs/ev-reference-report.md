# Batch B EV reference report

Command:

```bash
python3 scripts/ev_reference_report.py --sims 24
```

Recorded on 2026-07-23. Timings are wall-clock observations on this machine,
not service SLOs.

## MJ-006 current approximation vs exact small wall

- exact cases: 2 (`3-1` and `5-2`);
- candidate comparisons: 30;
- mean absolute actor-EV error: **2.3472 value units**;
- top-1 agreement: **50.0%**;
- non-tied ranking pairs: 13;
- ranking inversion rate: **100.0%**.

The deliberately tiny omniscient states expose the known missing outcomes in
the production approximation. These results are evidence to retain the exact
evaluator as an oracle; they are not a basis for silently replacing the
production model.

## MJ-008 fixed top-k vs confidence screening vs exhaustive

Pre-declared target: top-1 recall **>=99%**.

The six seeded cases cover early/mid/late wall, declared opponents, flush
states, dealer streak, and both payout schemes.

| selector | recall@1 | mean regret | worst regret | total latency |
|---|---:|---:|---:|---:|
| legacy fixed top-k | 83.33% | 0.00513 | 0.03076 | 3.81 s |
| two-stage confidence-bound | 100.00% | 0 | 0 | 6.71 s |
| exhaustive reference | 100.00% | 0 | 0 | 2.53 s |

The fixed selector missed `open-flush-opponent` (seed 8106): fixed top was
`1m`, exhaustive top was `2z`, regret 0.03076. Because 83.33% missed the 99%
bar, production selection now uses the required two-stage confidence-bound
screen. `exhaustive=True` remains opt-in and evaluates every legal discard at
the full requested budget.

On this small corpus the confidence screen is slower than exhaustive because it
runs a pilot before the full-budget finalists. That latency is an explicit
risk/tradeoff; it does not justify reverting to the selector that failed the
recall gate.
