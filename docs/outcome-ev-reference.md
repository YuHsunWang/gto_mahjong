# Outcome/payment reference specification

This is the Batch B measurement contract. It does **not** replace the
production EV approximation.

## Terminal outcomes

The acting seat is called `self`; the other seats are `opponents`.

| outcome | winner | payer/target | four-player payment |
|---|---|---|---|
| `self_tsumo` | self | all three opponents | each opponent pays one hand-value leg; only the dealer leg receives the bilateral dealer/streak premium when self is not dealer |
| `self_ron` | self | the opponent that discarded the winning tile | target pays one hand-value leg, plus the bilateral dealer/streak premium only when the target is dealer |
| `opponent_ron` | an opponent | the actual discarder (self or another opponent) | actual discarder alone pays; target-specific dealer/streak premium follows the same rule |
| `opponent_tsumo` | an opponent | the other three seats, including self | each loser pays one leg; only the dealer leg receives the bilateral premium when the winner is not dealer |
| `draw` | none | none | `(0, 0, 0, 0)` in the current house model |

Every terminal delta vector must have four entries and sum to zero under both
supported schemes (`3-1` and `5-2`). `terminal_payment()` applies this contract
through the same house settlement used by self-play, while the exact evaluator
independently decides which terminal outcome occurred.

## Small-wall exact oracle

`taimahjong.reference_ev` accepts four known concealed hands and a deliberately
short live-wall multiset. The acting player begins with 17 tiles and supplies a
legal first discard. The evaluator then:

1. resolves immediate ron in seat order;
2. branches exactly on each physical next-tile probability;
3. resolves tsumo, otherwise makes a deterministic shanten/remaining-copy
   discard;
4. resolves ron in seat order after every discard;
5. returns draw only when the short wall is exhausted.

Duplicate wall tiles are weighted by their physical multiplicity using exact
`Fraction` probabilities. Therefore the terminal probability mass is exactly
one, not a Monte Carlo estimate. The state is intentionally small and
omniscient; it is suitable for payment/outcome regression and approximation
error measurement, not interactive production analysis.

## Comparison metrics

`compare_reference_corpus()` evaluates every legal first discard in the small
states and reports:

- mean absolute actor-EV error;
- top-1 agreement;
- pairwise ranking-inversion rate.

The production estimator remains labeled as a self-draw/heuristic
approximation. A future model replacement requires a larger, versioned
reference corpus and may not be inferred from this small oracle alone.
