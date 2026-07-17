# Taiwanese Mahjong shanten and ukeire (M2)

This package calculates regular-hand shanten for Taiwanese 16-tile mahjong.
It supports the 34 ordinary tile kinds only; flowers and special hands are out
of scope.

Compact notation groups digits before a suit: `m` (characters), `p` (dots),
`s` (bamboo), and `z` (honors 1-7).  For example,
`123m456p789s1122334z` contains 16 tiles.

A win is five melds (sequences or triplets) plus one pair, or 17 tiles.  The
shanten convention is `-1` for a complete 17-tile hand and `0` for a 16-tile
tenpai hand.  Declared melds are supplied with `--melds`; each reduces the
expected concealed count by three.

Run the calculator:

```bash
python3 -m taimahjong "123m456p789s1122334z"
```

For a 16-tile-equivalent concealed hand, `--ukeire` lists every draw that
strictly reduces shanten and the total number of unseen acceptable tiles:

```bash
python3 -m taimahjong "123m123p123s1112223z" --ukeire
```

For a 17-tile-equivalent concealed hand, `--analyze` ranks each distinct
discard by resulting shanten and then total ukeire:

```bash
python3 -m taimahjong "123m123p123s11122233z" --analyze
```

The Python API provides `ukeire(counts, melds_declared=0, visible=None)` and
`discard_analysis(counts, melds_declared=0, visible=None)`.  `visible` is a
34-count array for tiles seen elsewhere and can also be supplied to the CLI
with `--visible "..."`.  For an accepted tile kind, its unseen count is
`4 - copies in hand - copies in visible`.  A kind whose unseen count is zero
is still listed when it would theoretically improve shanten, so unavailable
waits remain visible.  Hand plus visible copies may not exceed four for any
tile kind.

## M3 simulation

`win_probability(counts, turns, melds_declared=0, visible=None, sims=5000,
seed=None)` runs Monte Carlo trials against the 136-tile ordinary-tile
universe. The unseen pool contains four copies of each kind minus the
concealed hand and `visible`; flowers are not modeled. Each trial draws
without replacement, and a simulated discard is not returned to that pool.
After a non-winning draw, it uses the M2 top-ranked discard (minimum
resulting shanten, then maximum ukeire) and continues.

The result reports cumulative tenpai and win probabilities after every draw.
Starting tenpai is folded into the turn-one tenpai figure rather than exposed
as a separate turn-zero baseline. This is a **self-draw-only** estimate:
opponent discards, deal-ins, scoring, and opponent behavior are not modeled.

Run a reproducible simulation from the CLI:

```bash
python3 -m taimahjong "123m123p123s1112223z" --simulate --turns 10 --sims 5000 --seed 42
```

It prints cumulative tenpai and self-draw win percentages by turn, followed
by final totals and the self-draw-only reminder.

Run the tests (pytest is only a test dependency):

```bash
python3 -m pytest tests/ -q
```
