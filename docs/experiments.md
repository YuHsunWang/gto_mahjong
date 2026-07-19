# Self-play experiments: 連莊 defense and kong EV

Two reproducible self-play studies answer the strategy questions the scoring
rules alone cannot: how a 連莊 (streaking) dealer changes seat-relative defense,
and what each kong type is actually worth. Both use seed-paired batches — the
same seed is the same shuffle across every condition — so a difference between
conditions is the decision under study, not luck.

All point figures are in **value units** (1 底 = `BASE_UNITS` = 3 tai-units);
they are the same units as `GameResult.point_deltas`, and every game's four
deltas sum to zero. The bots are the deterministic self-play policies
(`attack`, `cautious`, `ev_aware`); this is a bot ecology, not human play.

## Honest scope

- **Attack-side 連莊 premium is under-counted.** A non-dealer's Monte-Carlo win
  value scores all three ron targets symmetrically, so it does not add the extra
  premium collected specifically when the win comes off the dealer. The bias is
  at most `P/3` of one win's value (`P = DEALER_TAI + STREAK_TAI_PER_WIN·streak`).
  The *defense* side (dealing into the dealer) is fully modelled.
- **Kong dead wall does not backfill.** Replacement tiles come from a fixed
  16-tile dead wall; it is not topped up from the live wall. Long kong-heavy
  games therefore draw the live wall down slightly faster than a real table.
- Deal-in probabilities are calibrated to *this* bot ecology (see the M4b
  calibration section in the README), not to human opponents.

## Experiment A — seat-relative defense vs a streaking dealer

`scripts/streak_defense.py`. The dealer (seat 0) plays `attack` and pushes;
seats 1–3 all play `cautious`, so any difference between them is purely their
turn-order position relative to the dealer:

| seat | relation | draws… |
|---|---|---|
| 1 | 莊的下家 (downstream) | right after the dealer |
| 2 | 莊的對家 (across) | — |
| 3 | 莊的上家 (upstream) | right before the dealer |

The `--dealer-aware` toggle zeroes the defensive dealer premium (ev's opponent
dealer tai and the cautious dealer weight), leaving the seat-blind baseline, so
the on/off contrast isolates what dealer-awareness buys.

```bash
# streak sweep, dealer-aware defense on
for st in 0 1 2 3; do
  python3 scripts/streak_defense.py --games 1000 --seed 30001 --streak $st --dealer-aware on
done
# aware on/off contrast at the extremes
python3 scripts/streak_defense.py --games 1000 --seed 30001 --streak 0 --dealer-aware off
python3 scripts/streak_defense.py --games 1000 --seed 30001 --streak 3 --dealer-aware off
# supplementary: ev_aware defenders (continuous dealer pricing), aware on vs off
python3 scripts/streak_defense.py --games 120 --seed 30001 --streak 3 --dealer-aware on  --defenders ev_aware
python3 scripts/streak_defense.py --games 120 --seed 30001 --streak 3 --dealer-aware off --defenders ev_aware
```

### Results (cautious defenders, 1000 games/cell, seed base 30001)

| streak | dealer point EV | defender point EV — 下家 / 對家 / 上家 |
|---|---|---|
| 0 | +0.22 | −0.06 / **+0.23** / **−0.39** |
| 1 | +0.29 | −0.08 / +0.24 / −0.45 |
| 2 | +0.36 | −0.10 / +0.25 / −0.51 |
| 3 | +0.43 | −0.12 / +0.27 / −0.57 |

Deal-in-to-dealer rate (下家 0.074 / 對家 0.062 / 上家 0.068) is identical across
every streak and across the dealer-aware on/off toggle.

Two things move, one does not:

- **The 連莊 premium is the dominant effect.** The dealer's point EV rises about
  +0.07 units per streak step — pure payment, since the deal-in *rate* does not
  change. Dealing into a connecting dealer is simply worth more.
- **Seat geometry decides who suffers.** 莊的上家 (upstream — draws right before
  the dealer, and whose discards the dealer can 吃) has the worst EV by a wide
  margin, and it worsens with every streak step; 莊的對家 is the only seat that
  nets positive. This is the seat-relative answer: the upstream player is the
  one who must defend the dealer hardest, the more so as the streak grows.
- **The cautious dealer-weight does not bind here.** Turning dealer-awareness off
  (or even scaling the weight 10×) leaves the deal-in rates byte-identical,
  because cautious only applies the weight inside a deep-fold branch that rarely
  decides the discards that feed the dealer. The mechanism is real (unit-tested)
  but this bot ecology seldom exercises it.

**ev_aware defenders do respond.** The `ev_aware` policy prices the dealer on
*every* discard through `opponent_value_estimate` (the M2 channel), not only when
folding. A smaller supplementary run (`--defenders ev_aware --games 120 --streak
3`) shows dealer-awareness cutting deal-ins to the dealer materially:

| dealer-aware | deal-in-to-dealer — 下家 / 對家 / 上家 |
|---|---|
| on | 0.092 / 0.100 / 0.217 |
| off | 0.142 / 0.142 / 0.258 |

So the prescriptive "defend the dealer harder, especially as 上家" is realized by
continuous-EV defenders (~16–35 % fewer deal-ins to the dealer at streak 3), not
by the fold-only cautious policy. (120 games — directional, not a tight CI; the
Monte-Carlo `ev_aware` policy is too slow for a full battery.)

## Experiment B — kong marginal EV by type

`scripts/kong_ev.py`. Seat 0 is given the tested kong policy while seats 1–3
never kong (all four play `attack`), so seat 0's mean point delta is its kong
lift against otherwise identical opponents. Comparing the three policies on the
same seeds isolates each kong family:

- `concealed_added − none` = the value of 暗槓 / 加槓 (shanten-safe self-draw kongs).
- `all − concealed_added` = the marginal value of adding 大明槓.

```bash
for kp in none concealed_added all; do
  python3 scripts/kong_ev.py --games 1000 --seed 40001 --kong-policy $kp
done
```

### Results (1000 games/cell, seed base 40001)

| policy | seat-0 point EV | games with a seat-0 kong | 大明槓 offered? |
|---|---|---|---|
| none | +0.346 | 0 % | — |
| concealed_added | +0.333 | 6.0 % | no |
| all | +0.221 | 13.4 % | yes |

- **暗槓 / 加槓 ≈ neutral:** `concealed_added − none = −0.013` units/game — within
  sampling noise. Taking a shanten-safe concealed or added kong neither helps nor
  hurts materially; it keeps 門清 (concealed) and only trades flexibility.
- **大明槓 is clearly negative:** `all − concealed_added = −0.112` units/game. The
  extra open kongs in `all` are 大明槓, and enabling them lowers the actor's EV.
  This is exactly what the house rule predicts — a 大明槓 scores 0 tai, breaks
  nothing extra, forfeits 槓上開花, and locks four tiles into a fixed set — so it
  can only cost tempo and flexibility. Pinned by
  `test_daiminkan_is_not_positive_ev_under_house_rule`.

槓上開花 did not occur in either kong batch (the replacement tile completing the
hand is rare with attack bots), and 搶槓 cannot occur when only seat 0 kongs and
no opponent is left to rob — both are exercised instead by the dedicated
selfplay/trainer tests.

**Answer to "明槓效益如何":** an open 大明槓 is a losing play under these rules
(≈ −0.11 units/game); concealed and added kongs are roughly break-even. Kong to
complete a hand shape (a concealed triplet you need, a 槓上開花 draw), never for
its own sake — and never a 大明槓.

## Reproducing

Each script prints one JSON line. The numbers above are pinned in spirit by
`tests/test_selfplay.py::test_daiminkan_is_not_positive_ev_under_house_rule`
(大明槓 is not positive-EV) and
`test_per_seat_kong_policy_restricts_kongs_to_enabled_seats`. Larger batches
tighten the confidence intervals but do not change the direction of any result.
