> 🌐 [繁體中文](README.md) ｜ **English**

# Taiwanese Mahjong GTO Trainer

A tool for practicing Taiwanese 16-tile mahjong. It works out your hand efficiency,
estimates deal-in danger, scores winning hands, and uses EV (expected value — roughly
"how many tai this move is worth on average") to tell you which tile to discard. You can
play through a web UI that scores you live, or call any single feature from the command
line.

Scope first: it only handles the 34 ordinary tile kinds (characters, dots, bamboo,
honors) — no flowers, no special hands. And one important caveat: every probability in
the tool is calibrated by playing its own built-in bots against each other for thousands
of games, not against real human play. So it is good for training judgment and feel, but
don't treat those numbers as exact win rates at a real table.

Tiles use a compact notation: digits before a suit — `m` characters, `p` dots,
`s` bamboo, `z` honors (1–7). For example `123m456p789s1122334z` is 16 tiles.

## Quick start

**Web UI (recommended):**

```bash
pip install -r requirements.txt
uvicorn server.api:app
# open http://127.0.0.1:8000/
```

**Command line:** each feature runs on its own; examples are in the sections below.

**Tests (for developers):**

```bash
python3 -m pytest tests/ -q
```

---

## Features

### Hand efficiency: shanten and ukeire

Tells you how far a hand is from winning and which draws improve it.

"Shanten" is how many useful tiles you are away from tenpai — 0 means you're already
waiting. "Ukeire" (acceptance) is the set of tiles that bring you closer to a win. Give
it a 16-tile hand and it lists every acceptance tile plus how many of each are still
unseen (the math is simple: `4 − copies in hand − copies seen elsewhere`). Give it a
17-tile hand (drawn, not yet discarded) and it ranks every discard: lowest resulting
shanten first, then most acceptance.

If you've already called tiles, tell it with `--melds` (each call removes 3 concealed
tiles). Use `--visible` to factor in tiles you've seen elsewhere.

```bash
python3 -m taimahjong "123m123p123s1112223z" --ukeire     # list acceptance
python3 -m taimahjong "123m123p123s11122233z" --analyze   # rank discards
```

### Win-rate simulation

Estimates how soon you'll win using the "deal many hands" method (Monte Carlo).

It randomly deals many games against the 136-tile set, drawing without replacement, and
whenever it draws a non-winning tile it discards optimally and continues. It then reports
your cumulative tenpai and self-draw win rates after each turn. This counts your own
self-draw only — it ignores what opponents do and ignores deal-ins.

```bash
python3 -m taimahjong "123m123p123s1112223z" --simulate --turns 10 --sims 5000 --seed 42
```

### Deal-in danger and hand reading

Estimates how risky it is to discard a tile against an opponent, and reads their state.

It lists the tenpai shapes that could win on that tile, checks whether the tiles the
opponent would need still exist in the wall, and sums the feasible ones. It reads the
opponent's river: a suit they've discarded a lot of is treated as one they don't need, a
suit they've never discarded as one they might be waiting on; it also notices calls
concentrated in a single suit (going for a flush). Shape weights look like this:

| Shape | Weight |
| --- | --- |
| two-sided sequence | 4.0 |
| closed / edge sequence, pair-pair | 2.0 |
| single-tile wait | 1.0 |

Note: this is **not** a safety guarantee. Taiwanese mahjong has no permanent Japanese
riichi furiten, only temporary 過水, so a tile seen in the river only *discounts* the
danger — it never becomes 100% safe.

It also reads the opponent: `tenpai_score` estimates how close they are to waiting (more
calls means more likely tenpai), and `fold_score` judges whether they're folding
(bailing out, discarding only safe tiles). It also supports the house-rule **migi
declaration** — once an opponent declares, any tile kind they discard afterward cannot be
part of their win, which is a hard rule that marks it safe.

```bash
python3 -m taimahjong "123m123p123s11122233z" --danger --opp-river "456m789p" --tile "3z"
```

It prints the discard order with a separate `Danger` column, but does **not** merge
efficiency and danger into one score — you weigh them yourself.

### Scoring (tai)

Give it a winning hand and it scores it, item by item.

The tai table follows standard Taiwanese house rules, baked into the code: dealer 1,
連N拉N is 2N, 門清/自摸/獨聽 1, 平胡/全求人/三暗刻 2, 碰碰胡/混一色/小三元 4, 四暗刻 5,
清一色/大三元/小四喜/五暗刻 8, 字一色/大四喜 16, 圈風/門風/三元牌刻 1. One 底 equals
3 tai. 天胡/地胡 are 16/8 tai. It enumerates every way to read the hand and takes the
highest-scoring one.

A few documented house-rule calls:

- A **kong** scores no tai by itself. Only winning on a kong's replacement tile
  (槓上開花) and robbing a kong (搶槓) score, 1 tai each. A 大明槓 is actually bad here
  (no tai, breaks 門清, and forfeits 槓上開花).
- **全求人** uses the mainstream Taiwanese reading: a 大明槓 counts as a set completed
  from others' tiles and qualifies, but any 暗槓 disqualifies it. **Change this if your
  table rules differently.**
- The **連莊** premium applies to every payment leg between the dealer and the winner;
  even at streak 0, the leg paid to the dealer is one unit dearer than a peer's.

```bash
python3 -m taimahjong "22z" --score --my-melds "123m;456p;789s;111z;555z" \
  --win-tile 2z --dealer --streak 2 --migi
```

### EV-based decisions

Turns "which discard is best" into a number you can compare.

EV is expected value. It takes a win's value (in tai) times the chance of winning as the
"attack" side, subtracts each opponent's deal-in loss, and gives a net EV per discard —
the highest is the theoretically best play. It also accounts for defense: an opponent
may win before your next draw, so it discounts the attack side by "the chance you survive
to your next turn," and it can value a draw (流局) too.

```bash
python3 -m taimahjong "123m123p123s11122233z" --ev --opp-river "1m2m" --opp-declared 0 --turns 3
```

There's also a "should I declare migi?" feature (`--declare`): it computes the exact
probability of the locked wait after declaring versus a simulation of the normal style
(where you can still upgrade to a bigger hand), and compares which has higher EV.

### Teaching quiz

Turns games into one discard problem at a time.

It picks discriminating positions from self-play (not too easy; best and second-best must
differ by enough tai) and shows you only what your seat can see. You pick a tile and it
grades you immediately — best / good / inaccuracy / mistake — and uses an EV table to
explain why, whether it was the win-EV gap or the deal-in-loss gap. The same seed always
gives the same problem, handy for re-drilling or checking answers.

```bash
python3 -m taimahjong --quiz --seed 1 --answer 9s
python3 -m taimahjong --quiz-batch 5 --seed 1
```

### Live trainer

Plays a whole hand start to finish with you, scoring every move live.

It pauses when it's your turn, grades your discard by EV as you go, and tallies your
best-rate and total EV loss until a win / deal-in / draw, then summarizes. In this phase
you play 門清 (self-draw or ron; no chi/pon yet) while opponents call normally. You can
pick a seat and streak at the start to feel different positions relative to the dealer —
a streak raises both the value of the dealer's win and the cost of dealing into them.

### Web teaching UI

If you'd rather not use the command line, use the web page.

A single-page app (no build step, just open it) that bundles the features into an easy
interface: full game (play to the end with live EV grading), single hand (one discard
problem), endgame (high-pressure spots as the wall runs low, auto-tagged attack/defense),
a lessons area (hand-written efficiency problems backed by pure acceptance), discard
analysis, and scoring. The table is drawn as a Mahjong-Soul-style cross-shaped river,
with GTO-Wizard-style feedback (verdict badge, EV delta, best-answer marker, expandable
ranking table). Answer history is stored in your browser, and the home page charts each
mode's best-rate trend.

The page can also switch the **底/台 scheme** (底3台1 ⇄ 底5台2). The 底:台 ratio changes
the trade-off between "win first" and "go for a big hand," so it can change the best
discard — switching re-scores instantly.

### Under the hood: how the engine got accurate

Many of the probabilities above aren't set by hand — they're calibrated from self-play.

`taimahjong.selfplay` plays four bots against each other for thousands of games, records
the state and deal-in outcome of each discard, and builds probability tables from it (for
example, a "higher danger score → higher actual deal-in rate" lookup). Danger started as
just a relative score; this step turns it into a readable percentage. The calibration
data lives in `data/calibration.json` and you can rebuild or extend it:

```bash
python3 -m taimahjong --selfplay --games 250 --seed 10001 --out data/calibration.json
python3 -m taimahjong --selfplay-report data/calibration.json
```

Again: these numbers are calibrated against *these bots*, not against humans.

### Research experiments

Two small research scripts use paired-seed self-play to answer strategy questions:
seat-by-seat defense against a streaking dealer (`scripts/streak_defense.py`) and whether
each kong type is worth declaring (`scripts/kong_ev.py`). Method and data are in
[docs/experiments.md](docs/experiments.md).

---

## Honest scope and limits

- **Ordinary tiles only**: no flowers, no special hands.
- **Probabilities are calibrated against bots**, not human play; the defensive-side
  opponent value isn't even calibrated — it's a directional estimate.
- **Danger is not a safety guarantee**: Taiwan has no permanent furiten, so river
  evidence only discounts.
- **House rules are adjustable**: how 全求人 counts, kong tai, whether a draw is
  penalized (`DRAW_VALUE`), and the 底/台 scheme are all constants or options you can
  change for your table.

Technical details (parameters, full calibration data, tai-stacking rules) live in each
module's docstrings and in [docs/experiments.md](docs/experiments.md).
