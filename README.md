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

## M4a deal-in danger (single opponent)

`taimahjong.danger` is a deterministic, rule-based **uncalibrated** heuristic
for the danger of discarding one tile against one modeled opponent.  It does
not estimate a real probability yet; self-play calibration is a later
milestone.  It enumerates every ordinary tenpai shape that could win on the
candidate discard, tests whether its required held tiles still exist in the
unseen wall, then sums the feasible shape weights.

| Shape or rule | Constant | Default |
| --- | --- | --- |
| two-sided sequence | `RYANMEN_WEIGHT` | 4.0 |
| closed sequence | `KANCHAN_WEIGHT` | 2.0 |
| edge sequence | `PENCHAN_WEIGHT` | 2.0 |
| pair-pair | `SHANPON_WEIGHT` | 2.0 |
| single-tile pair | `TANKI_WEIGHT` | 1.0 |
| minimum numeric river for suit read | `MIN_RIVER_NUMERIC` | 6 |
| low numeric-suit river share | `LOW_SHARE` | 0.15 |
| scarce-suit multiplier | `SUIT_SCARCE` | 1.5 |
| absent-suit multiplier | `SUIT_VOID` | 2.0 |
| one-suit meld commitment | `MELD_FLUSH` | 2.0 |
| honor under that commitment | `MELD_FLUSH_HONOR` | 1.5 |
| river evidence per required tile kind | `SHAPE_RIVER_DISCOUNT` | 0.3 |

For tanki the opponent must still be able to hold one copy of the discard;
for shanpon, two copies; sequences require one copy of each of their two
neighbors.  Numeric suit inference uses plain river counts: after at least
six numeric discards, a suit below 15% gets the scarce multiplier and a suit
with no discards gets the void multiplier.  The flush read fires when every
declared meld is in one numeric suit and the newest rounded-up third of the
opponent river contains no tile in that suit; it boosts that suit and honors.
When the flush and scarce/void reads apply to the same suit, their **maximum**
is used rather than multiplying two correlated signals.

River evidence is shape-specific: each distinct tile kind needed in a shape
that appears in the opponent river multiplies that shape by 0.3.  A matching
discard in the newest rounded-up third applies 0.3; only earlier matches apply
the weaker `sqrt(0.3)`.  This is never absolute safety.  Taiwanese mahjong
has no permanent Japanese-riichi furiten (only temporary 過水), so neither
`genbutsu` nor riichi suji can be copied as a 100%-safe rule: a river tile
only discounts the corresponding shape.

Use the CLI with a post-draw, 17-tile-equivalent concealed hand:

```bash
python3 -m taimahjong "123m123p123s11122233z" --danger --opp-river "456m789p" \
  --tile "3z"
```

It prints the usual M2 discard order with a separate `Danger` column; it does
not combine efficiency and danger into a single rank.  `--tile` prints the
feasible-shape breakdown.  `--opp-river` is oldest to newest in the written
compact notation.  Supply called opponent melds as semicolon-separated groups,
for example `--opp-melds "123s;777s"`.  In danger CLI mode, `--visible`
means other public tiles; the opponent river and melds are automatically added.

For the Python API, `danger_score(tile, opponent, visible, own_hand)` instead
requires `visible` to already include the opponent river and melds (and every
other known public tile).  `own_hand` is the **post-discard** concealed hand,
so it excludes the one candidate copy of `tile`.  The function computes each
unseen count as `4 - visible - own_hand - discarded_copy`, validates that this
never exceeds four known copies, and therefore never double-counts the
discard.  `rank_discards(counts17, opponent, visible, melds_declared=0)` wraps
M2's existing ordering and attaches a separate assessment to each entry.

## M4a+ opponent state (tenpai, fold, and migi declaration)

The opponent-state estimates in `taimahjong.danger` are deterministic and **UNCALIBRATED**. They are directional hand-reading signals, not measured probabilities; self-play calibration is a later milestone. `RiverEntry(tile, origin)` records one river tile, where `origin` is `"tsumogiri"`, `"tedashi"`, or `"unknown"`. Plain integer river entries remain supported and mean unknown origin.

`parse_river()` and `format_river()` live in `taimahjong.danger`, alongside the opponent-specific schema. River notation permits `*` after a digit for tsumogiri and `.` for tedashi before the suit applies: `1*2.3m` is 1m tsumogiri, 2m tedashi, and 3m unknown. In a trailing tsumogiri scan, unknown entries are neutral: scanning newest to oldest, they neither add to nor stop the run; the first known tedashi stops it.

`tenpai_score(opponent, turn)` returns `TenpaiAssessment(score, signals, recent_wait_change)`. Its constants are `TENPAI_BASE_BY_MELDS` (the strongest signal, because calls shrink the concealed hand), `TENPAI_TURN_INCREMENT`, `TENPAI_TURN_CAP`, and `TSUMOGIRI_RUN_INCREMENT`. At `LATE_TURN` (9), a tedashi in the latest `RECENT_TEDASHI_WINDOW` (2) discards sets `recent_wait_change`; its `RECENT_TEDASHI_MULTIPLIER` weakens the prior river read. `rank_discards` retains raw `danger` and `tenpai`, adds `tenpai_score`, and exposes `expected_danger = danger.score * tenpai_score` as a convenience only.

`fold_score(opponent, others_discards)` reads the latest `FOLD_WINDOW` (4) opponent discards. It needs at least `MIN_FOLD_SAMPLE` (3), then averages the strongest safety shape per tile: another player's matching discard is 1.0, an honor is `HONOR_FOLD_WEIGHT` (0.6), and a terminal is `TERMINAL_FOLD_WEIGHT` (0.3). A tedashi middle tile (3--7) contributes zero. A folding opponent's win threat collapses and draw (流局) likelihood rises; numeric EV and draw-probability integration are later work.

The only declaration form in these rules is the house-rule **migi**. It may be declared only on the player's first or second discard (the table's first eight discards) and only before any chi, pon, or kang. `OpponentView` stores the declaration river index as `declared_at`, which must be 0 or 1. `DECLARED_TAI = 8` is reserved for a future scoring milestone. A declared opponent is certain tenpai (`1.0`), cannot fold (`0.0`), and has a locked hand: any tile kind discarded after `declared_at` is hard excluded from their wins and reports `declared_safe` with danger exactly zero. This is an absolute rule, unlike pre-declaration river evidence, which remains only a statistical discount because Taiwanese rules do not have permanent Japanese-riichi furiten.

In `--danger` mode, use `--opp-declared 0` or `--opp-declared 1` for migi and `--others "..."` as the fold safety reference. The output includes opponent tenpai and fold headers plus an `ExpDanger` column; a hard-excluded kind prints `SAFE(declared)`.

## M4b self-play calibration

`taimahjong.selfplay` runs four deterministic-policy players against the same
136 ordinary-tile universe used elsewhere in this package. It deals 16 tiles
to each player, lets the dealer draw first, checks self-draw and discard wins
with M1, and ends when a player wins or the live wall is empty (16 tiles are
held dead). Every discard retains an in-memory event record with observable
opponent-state inputs, true concealed-hand tenpai, deal-in status, and the
M4a danger score used for calibration.

The simulator intentionally omits flowers and flower replacement, kang, and
the temporary Taiwanese `guo shui` (過水) rule. It is a policy testbed, not a
complete rules implementation. Ron uses downstream priority; then greedy pon
and next-player chi are allowed only when the resulting best discard strictly
improves M1 shanten. The house-rule migi declaration is available on either of
a player's first two discards before any call; declared players must discard
their draw unless it wins. Calls on their locked discards are omitted so the
declaration river remains observable.

Seats default to two `attack` and two `cautious` bots. Attack uses the top M2
discard. Cautious uses that same choice, except at shanten 2+ against a
declared or four-meld opponent, where it picks the M2 candidate with the
lowest M4a danger. This deliberately produces observable folding windows.

Generate calibration data in bounded chunks; repeated commands append and
merge counts rather than raw game logs:

```bash
python3 -m taimahjong --selfplay --games 250 --seed 1 --out data/calibration.json
python3 -m taimahjong --selfplay --games 250 --seed 2 --out data/calibration.json
python3 -m taimahjong --selfplay-report data/calibration.json
```

The JSON stores mergeable `counts` plus derived tables: empirical
`P(tenpai | melds, turn bucket, trailing-tsumogiri bucket)`, raw empirical
deal-in fractions plus their weighted-isotonic monotone
`P(deal-in | danger bucket)` calibration, and cautious/attack fold-window
means. At lookup time a cell with fewer than 30 observations is unavailable;
danger lookups linearly interpolate between populated bucket midpoints. If
`data/calibration.json` exists, `--danger` labels both the uncalibrated
heuristic and calibrated `P(tenpai)` / `P(deal-in)` values.

These probabilities are calibrated **against these bots**, their greedy call
rule, and these simplifications—not against human Taiwanese-mahjong play.

## M5a tai scoring

`taimahjong/scoring.py` scores a complete winning hand with an itemized tai
(台) breakdown. House rules encoded as module constants: one 底 equals
`BASE_UNITS` (3) tai; the standard Taiwanese tai table (莊 1, 連N拉N 2N,
門清/自摸/獨聽 1, 平胡/全求人/三暗刻 2, 碰碰胡/混一色/小三元 4, 四暗刻 5,
清一色/大三元/小四喜/五暗刻 8, 字一色/大四喜 16, 圈風/門風/三元牌刻 1);
the migi declaration adds `DECLARED_TAI` (8); the confirmed house values for
heavenly/earthly hands are 16/8 tai. Flowers and kongs
are not modelled — `WinContext.extra` is the reserved pass-through slot.

Documented stacking choices: 小三元/大三元 replace their component 三元牌刻;
小四喜/大四喜 suppress 圈風/門風. A lone dragon triplet, and winds outside a
wind composite, still score normally. 字一色 stacks with 碰碰胡 and
concealed-triplet tai; only the highest 暗刻 tier counts; 平胡 requires all
runs, a non-honor pair and a multi-kind wait (self-draw allowed). All winning
decompositions are enumerated and the highest-tai reading is used. A triplet
completed by ron is not concealed; single wait (獨聽) means exactly one winning
kind.

```bash
python3 -m taimahjong "123m111555666777z22z" --score --win-tile 2z
python3 -m taimahjong "22z" --score --my-melds "123m;456p;789s;111z;555z" \
  --win-tile 2z --dealer --streak 2 --migi
```

Optional context flags: `--self-draw --dealer --streak N --migi --heavenly
--earthly --round-wind 1z --seat-wind 2z`.

## M5b tai-unit EV

`taimahjong.ev` ranks a small M2-efficient discard set with an approximate
tai-unit EV. A win value is `BASE_UNITS + M5a tai`, so the win and loss sides
share the same unit:

```
attack_ev = P(self-draw win) * E[value_units | self-draw win]
net_ev    = attack_ev - sum(E[deal-in loss per opponent])
E[loss]  = P(deal-in | danger) * opponent-state factor * visible-state value
```

The attack side is self-draw-only and does not include a draw (流局) term.
Deal-in calibration is a marginal probability over deterministic bot states,
not a conditional human-game model. Opponent value is likewise an
**UNCALIBRATED** visible-state heuristic: base, migi, visible dragon triplets,
flush-read, and all-triplets tendency. Without a usable calibration cell,
the fallback is 0.02 scaled by M4a danger; migi hard-excluded tiles remain
exactly zero.

`--ev` accepts a 17-tile-equivalent hand and one optional opponent, reusing
`--opp-river`, `--opp-melds`, `--opp-declared`, and `--visible`. It displays
discard, net EV, self-draw win probability, conditional win value, and loss.
The default is 400 simulations per candidate (normally under ten seconds):

```bash
python3 -m taimahjong "123m123p123s11122233z" --ev --opp-river "1m2m" \
  --opp-declared 0 --turns 3 --sims 400 --seed 7
```

`--declare` accepts a 16-tile tenpai hand. Its declared branch locks the
current waits and calculates the exact hypergeometric probability of drawing
one within `--turns`; its other branch simulates the normal greedy policy,
where upgrades remain possible. The declared score includes migi's 8 tai.

```bash
python3 -m taimahjong "123m123p123s1112223z" --declare --turns 3 --sims 400 --seed 7
```
