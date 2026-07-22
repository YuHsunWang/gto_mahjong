> 🌐 **English** ｜ [繁體中文](README.zh-TW.md)

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

`fold_score(opponent, others_discards)` reads the latest `FOLD_WINDOW` (4) opponent discards. It needs at least `MIN_FOLD_SAMPLE` (3), then averages the strongest safety shape per tile: another player's matching discard is 1.0, an honor is `HONOR_FOLD_WEIGHT` (0.6), and a terminal is `TERMINAL_FOLD_WEIGHT` (0.3). A tedashi middle tile (3--7) contributes zero. A folding opponent's win threat collapses and draw (流局) likelihood rises; M7 uses the fold score to zero that opponent's survival hazard.

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

M8 changed the deal-in exposure reference after diagnosing a top-bucket
failure.  The old committed 3,751-game table used the maximum score across
the three opponents for a non-deal-in discard, but the actual winner's score
for a deal-in.  Its raw bucket rates were 0.0000, 0.0013, 0.0043, 0.0166,
0.0322, 0.0306, and 0.0228, so its top buckets inverted.  A fresh 400-game
diagnostic (seeds 9001--9004) kept the current suit/flush modifiers
(`SUIT_VOID=2.0`, `SUIT_SCARCE=1.5`, `MELD_FLUSH=2.0`) and compared both
references:

| bucket | max-across-opponents | per-opponent |
| --- | ---: | ---: |
| [0,1) | 0/549 (0.0000) | 0/3,832 (0.0000) |
| [1,2) | 2/941 (0.0021) | 2/2,126 (0.0009) |
| [2,4) | 16/2,657 (0.0060) | 16/9,793 (0.0016) |
| [4,6) | 28/1,938 (0.0144) | 28/4,967 (0.0056) |
| [6,9) | 73/2,708 (0.0270) | 73/9,616 (0.0076) |
| [9,13) | 104/3,136 (0.0332) | 104/8,972 (0.0116) |
| [13,+) | 69/3,167 (0.0218) | 69/5,982 (0.0115) |

The per-opponent reference restores weak monotonicity without changing any
modifier: every discard contributes one exposure row per live opponent, and
a ron is credited only to its actual winner's row.  This keeps numerator and
denominator on the same score definition.  A raw curve matters because
danger is useful as a ranking only when a higher score means more deal-in,
before the isotonic fit smooths sampling noise.

The committed rebuild contains 2,000 games (seeds 10001--10008) and has:

| danger bucket | raw deal-ins / observations | raw P(deal-in) |
| --- | ---: | ---: |
| [0,1) | 1 / 19,061 | 0.0001 |
| [1,2) | 3 / 10,321 | 0.0003 |
| [2,4) | 90 / 48,783 | 0.0018 |
| [4,6) | 142 / 24,533 | 0.0058 |
| [6,9) | 398 / 47,615 | 0.0084 |
| [9,13) | 514 / 43,952 | 0.0117 |
| [13,+) | 347 / 30,117 | 0.0115 |

The final 9--13 to 13+ decrease is one adjacent inversion smaller than 1.5
standard errors of the pooled rate, so it meets the committed weak-monotonic
test.  The JSON metadata records the seeds, per-opponent semantics, and
modifier constants.  Rebuild from scratch before appending chunks; never
merge a pre-M8 max-reference table:

```bash
rm data/calibration.json
python3 -m taimahjong --selfplay --games 250 --seed 10001 --out data/calibration.json
python3 -m taimahjong --selfplay --games 250 --seed 10002 --out data/calibration.json
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
heavenly/earthly hands are 16/8 tai. Flowers are not modelled —
`WinContext.extra` is the reserved pass-through slot.

**Kong house rule (2026-07-18):** an open or concealed kong scores no tai on its
own (`OPEN_KONG_TAI` / `CONCEALED_KONG_TAI` = 0); only winning on a kong's
replacement tile (槓上開花) and robbing a kong (搶槓) score, 1 tai each. 槓上開花
requires the fourth tile to have been self-drawn (暗槓 / 加槓) — a 大明槓 (fourth
tile taken from a discard) never qualifies. A concealed kong keeps 門清 and
counts toward concealed-triplet tai; an open kong breaks 門清. Consequently a
大明槓 is strictly bad here (0 tai, breaks nothing extra, forfeits 槓上開花); the
self-play experiment in [docs/experiments.md](docs/experiments.md) confirms it.
For 全求人, this project follows the mainstream Taiwanese interpretation: a
大明槓 counts as an exposed set, while any 暗槓 disqualifies 全求人 because that
set was not completed from another player's tile. This rule-dependent choice
should be changed if your table uses a different convention.

**連莊 bilateral premium:** the dealer premium (莊 `DEALER_TAI` 1 + 連N拉N
`STREAK_TAI_PER_WIN`·streak) applies to every payment leg between the dealer and
a winner. A dealer winner bakes it into the scored hand value (every leg pays
it); when a non-dealer wins, `selfplay._dealer_leg_premium` adds it to the
dealer's leg only — ron off the dealer, or the dealer's share of a tsumo. Even
at streak 0 the dealer's paying leg is one unit dearer than a peer's. 流局連莊:
a draw or dealer win keeps the dealer on seat 0 and grows the streak.

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

The attack side is self-draw-only.  M7 below adds survival discounting and a
configurable draw (流局) term.
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

## M5c point-accounted self-play

Self-play terminal results now include balanced point deltas. A ron makes the
actual discarder pay the winner the full scored value; on tsumo each of the
other three seats pays that full value; a draw is zero. The new `ev_aware`
policy is a deterministic closed-form ranking: M2's top five candidates plus
the minimum-danger candidate trade shanten/ukeire attack value against the
calibrated per-opponent deal-in loss. It does not run Monte Carlo per decision.

The committed v2 calibration is a 2,000-game mixed population with policies
`attack,cautious,ev_aware,ev_aware`, continuing seeds 30001--30037 and using
per-opponent danger exposure. Run a matching chunk with:

```bash
python3 -m taimahjong --selfplay --games 25 --seed 30038 \
  --policies attack,cautious,ev_aware,ev_aware --out data/calibration.json
```

Head-to-head results use two bots per policy, alternating which policy owns
dealer seat every game, with fixed consecutive seeds 41000--42199:

| games | ev_aware points/seat/game | attack points/seat/game | ev_aware - attack | SE |
| ---: | ---: | ---: | ---: | ---: |
| 1,200 | -1.911 | 1.911 | -3.823 | 0.119 |

This sample favors attack (about 32 standard errors by this game-level
estimate); no policy constants were retuned after observing it. On the same
100-game fixed-seed benchmark, ev_aware took 88.32 s and attack 48.96 s
(1.804x). Use `scripts/head_to_head.py --games N --seed S` for a reproducible
batch summary.

## M7 survival-discounted EV and draw path

M7 prices the chance that another player wins before our next draw.  It is an
explicitly **UNCALIBRATED** independent-per-turn approximation, intended to
make defensive discards and folding visible rather than to claim calibrated
human-game equity.  For each modeled opponent, per-turn hazard is:

```
BASE_OPPONENT_HAZARD (0.03)
* clamp(tenpai_score / BASELINE_TENPAI_RATE (0.25), 0.25, 3.0)
* 0 when fold_score >= FOLD_HAZARD_CUTOFF (0.60), otherwise 1
```

A declared migi opponent uses tenpai score 1.0.  The engine sums those
hazards, applies survival `S(t) = product(1 - total_hazard)` through each of
our draws, and weights each simulation's first-win increment by `S(t)`.  The
CLI reports both raw `P(win)` and survival-adjusted `P(win)`.

There is also an explicit draw path:

```
P(draw) = S(T) * (1 - P(win within T))
net_ev  = discounted_attack_ev - risk_ev + P(draw) * DRAW_VALUE
```

`DRAW_VALUE` defaults to `0.0`, matching the house assumption of no noten
penalty.  It remains a module constant so house rules can set another value.
Dealer-continuation and repeat effects on a draw are out of scope.

For `--ev` and `--declare`, omitting `--turns` derives our remaining draws
from the table: `ceil((136 - 16 dead-wall - visible tiles - concealed hand) /
4)`.  An explicit `--turns` still overrides this approximation.  `--ev` also
renders a final synthetic `fold` row.  It is advice, not a tile to discard:
it sets attack EV to zero, uses the lowest immediately achievable deal-in EV
among the shown discards, and keeps only the survival-weighted draw term.

Example with automatic turns and one threatening opponent:

```bash
python3 -m taimahjong "123m123p123s11122233z" --ev --opp-river "123456789m" --sims 400 --seed 7
```

The hazard constants, their per-turn independence, and combining a marginal
deal-in estimate with this survival model are all approximations.  They are
not calibrated win probabilities and should not be treated as such.

## M6 teaching quiz

`--quiz` turns deterministic self-play into a discard drill. It captures one
seat immediately after its draw, retaining only what that seat can see: its
hand, own river and melds, every opponent's river (including tsumogiri/tedashi
origin), called melds, declaration state, and aggregate visible tile counts.
Opponent concealed hands never leave self-play.

Starting at the requested seed, the generator tries that game seed and then
successive seeds, up to `MAX_ATTEMPTS = 80`. A position must have shanten at
most `SHANTEN_MAX = 2`, be at least `MIN_TURN = 5`, contain an opponent with
two melds, a declaration, or tenpai estimate at least 0.40, and have an EV
spread of at least `EV_GAP_MIN = 0.8` tai between the best and worst evaluated
candidates. The table is first ranked with 24 simulations per candidate, then
the rank-best and chosen discards are re-estimated with 200 simulations under
the same CRN seed. A result close to a verdict boundary and near tenpai is
re-estimated once more at 800 simulations. `QuizGrade.refined_sims` records
which verdict budget decided the result; `marginal` (UI: 「邊緣」) discloses a
final result that still hugs a boundary. A seed derived from the position seed
fully reproduces the position, budgets, and grade.

Use a supplied answer for a scriptable check, or omit it to answer one prompt
interactively:

```bash
python3 -m taimahjong --quiz --seed 1 --answer 9s
python3 -m taimahjong --quiz --seed 1
python3 -m taimahjong --quiz-batch 5 --seed 1
```

Verdicts are `best` (zero EV loss), `good` (under `GOOD_DELTA = 0.3` tai),
`inaccuracy` (under 1.0 tai), and `mistake` (1.0 tai or more). CLI EV output
uses one decimal place. The explanation uses the same EV table as `--ev`, then
identifies the actual win-EV or opponent-loss component that mattered most.

Example transcript:

```text
$ python3 -m taimahjong --quiz --seed 1 --answer 9s
Quiz seed: 1  Seat: 1  Turn: 5
Draw: 9m
Hand: 456789m8899p44599s55z
Own river: 2.z
Own melds: -
Opponent 0: river 2.s2.z1.p4*s4.z | melds 222p;666z | declared no | tenpai 0.52 | fold 0.57
Opponent 2: river 1.z | melds - | declared no | tenpai 0.17 | fold 0.00
Opponent 3: river 2.4.z | melds 666p | declared no | tenpai 0.33 | fold 0.00
Visible counts: 456789m12226668899p2444599s12224455666z
Verdict: best
EV delta: 0.0 tai
Discard  Net EV  P(win)  E[win value]  E[loss]
9s          0.8   0.208           5.2      0.3
5z          0.5   0.125           5.0      0.1
4s          0.3   0.125           5.7      0.4
8p          0.1   0.125           5.0      0.5
9p         -0.1   0.042           6.0      0.4
Best 9s: higher win EV by 0.46 tai than the next-ranked choice.
Chosen 9s: matches the best's higher win-EV component.
```

## M9 web teaching UI (W1–W3: FastAPI + SPA)

After installing dependencies, start the API and web page from the project root:

```bash
pip install -r requirements.txt
uvicorn server.api:app
# open http://127.0.0.1:8000/
```

The single-page app (`server/static/`, native ES modules with no build step) offers
three training modes, a lessons area, and two tools: full game (play one hand to the
end, every discard/call/kong decision scored by EV in real time), single hand (draw
one discard problem), endgame (high-pressure spots as the wall runs low, auto-tagged
attack/defense), lessons, discard analysis, and scoring. The table is a
Mahjong-Soul-style cross-shaped river (all four rivers converge toward the center,
your hand at the near edge); feedback is GTO-Wizard-style (verdict badge, EV delta,
best-answer marker, expandable EV ranking table). Each mode's answer history is kept in
browser localStorage, and the home page shows each mode's best-rate trend. The table
permanently notes "no flowers at this table." The JSON API is in `server/api.py`
(`/api/quiz`, `/api/endgame`, `/api/trainer`, `/api/ev/rank`, `/api/score`,
`/api/ukeire`).

**底/台 scoring scheme (`taimahjong.scoring.ScoringScheme`):** the practice table can
switch 底3台1 ⇄ 底5台2. The 底:台 ratio changes the trade-off between "win first" and
"go for a big hand," so it can change the best discard — switching re-scores immediately
(the same seed yields the same position; only scoring honors the chosen scheme). 底3台1
is the house default and equals the old `BASE_UNITS` model; self-play, calibration, and
the CLI always keep the default and are unaffected. Honest scope: the defensive-side
opponent value is still an uncalibrated heuristic, so most decisions change little after
a scheme switch — the effect concentrates on marginal spots.

**Lessons (`server/static/js/lessons.js`):** a few hand-written basic-efficiency
problems (lone-tile to tenpai, choosing the wider of equal waits, urgent-tenpai vs wide
shape, keeping 門清 on a call), each backed live by `/api/ukeire` (pure acceptance,
deterministic, no Monte Carlo). Discard problems show per-discard shanten/acceptance
ranking with the answer marked; call problems compare the acceptance of both choices
side by side.

The core engine has no web dependency; the API layer only calls the existing Python API
directly. The old Streamlit version (`webapp/app.py`) was retired on 2026-07-20 once the
SPA reached feature parity.

### Live trainer (M10, Phase 1)

The "live" tab uses the `taimahjong.trainer.play_trainer` generator to advance one hand
a move at a time: it pauses when it is your turn to discard, and once you choose,
`quiz.grade` gives an EV verdict (best / good / inaccuracy / mistake), accumulating your
best-rate and total EV loss, then summarizes at a win / deal-in / draw. In Phase 1 you
play 門清 (self-draw or ron allowed; no chi/pon yet) while opponents call normally; your
own call decisions and call EV are Phase 2. All probabilities are still calibrated
against bots, not real human play.

When starting a new hand you can pick a seat (dealer / dealer's right / across / dealer's
left) and an initial dealer streak. The dealer is fixed at seat 0; when the dealership
passes, the engine "rotates your seat" instead, so you experience sitting in different
positions relative to the dealer. A streak raises the value of the dealer's win and the
cost of dealing into the dealer (see the M5a bilateral-streak rule above). "Play again"
updates the streak and seat automatically based on a dealer win / draw (dealer keeps) or
a non-dealer win (dealership passes).

This tool is meant for single-player local use (trainer game state lives in the API
process memory).

## M11 self-play experiments: streak defense and kong EV

`scripts/streak_defense.py` and `scripts/kong_ev.py` use paired-seed self-play to
quantify two strategy questions: seat-by-seat defense against a streaking dealer, and the
marginal EV of each kong type (roughly how many tai declaring a given kong gains or
loses). Method, commands, and data are in [docs/experiments.md](docs/experiments.md).
Honest scope: the attack side's Monte Carlo win value is scored symmetrically across the
three opponents and does not specially add the "extra streak premium a dealer collects"
(under-counting a non-dealer by at most about P/3 of one win); a kong's dead-wall tile is
not refilled from the live wall.
