# Web UI plan — Mahjong-Soul-style table, GTO-Wizard-style training

Decisions (2026-07-20, user-confirmed):

- **Stack: FastAPI backend wrapping `taimahjong` + single-page frontend.**
  The Streamlit app stays as-is during the transition and is retired once the
  SPA reaches feature parity.
- **Flowers stay out of scope.** The UI must show a visible "本桌無花牌"
  (no-flower table) note; flower modelling is a separate future milestone.
- Engine model limits carried into the UI copy (already documented in
  README/experiments): attack EV is self-draw only; deal-in calibration is
  bot-ecology, not human.

## Training modes (GTO-Wizard mapping)

| Mode | Engine source | Status |
|---|---|---|
| 整場 (Play a full hand) | `trainer.play_trainer` generator: discard + call + kong decisions, per-decision EV feedback, running scorecard | engine done; needs API + UI |
| 單手 (Spot drill) | `quiz.generate_position` / `grade` | engine done; needs API + UI |
| 殘局 (Endgame drill) | **new**: filter self-play `DecisionSnapshot`s by late-game pressure | to build (small: a filtered generator on top of quiz) |

Endgame position filter (initial definition, tune later):

- `wall_remaining <= 20`, and
- own hand shanten <= 1 **or** at least one opponent has declared, and
- the position is "interesting" per the existing quiz gap criterion
  (EV gap between best and second candidate above threshold — reuse
  `quiz._interesting` logic with a stricter gap).
- Tag each drill as attack (push) or defense (fold pressure) from whether the
  fold entry ranks near the top of `ev_rank`.

## Phases

### W1 — API layer (no UI change)

FastAPI app (`server/api.py`), serving JSON + the static SPA:

- `POST /api/quiz/new {seed}` → position (hand, rivers, melds, wall, turn, …)
- `POST /api/quiz/grade {seed, tile}` → verdict, ranked EV table, explain text
- `POST /api/endgame/new {seed}` → same shape as quiz, filtered late-game
- `POST /api/trainer/new {seed, human_seat, dealer_streak}` → `session_id` +
  first decision. The generator lives in an in-memory session store keyed by
  `session_id` (single-user local tool; no persistence needed, but sessions
  must survive page reload via `GET /api/trainer/{id}`).
- `POST /api/trainer/{id}/act {decision}` → feedback + next decision/outcome
- `POST /api/ev/rank`, `POST /api/score` → wrap `ev_rank` / `score_hand`
- Long computations (EV grading) stay synchronous but the UI must render the
  frozen position + "計算 EV 中" state first (same 3-state flow the Streamlit
  app already uses).

### W2 — table SPA (the Mahjong-Soul-style screen)

Static, no build step: vanilla ES modules + one CSS file, served by FastAPI.

- **Tile art:** SVG per tile kind (34 kinds + back). Either an open-source
  riichi tile set (license must be verified before vendoring) or self-drawn
  SVGs generated from the current CSS design (Noto Serif TC faces). Taiwanese
  faces are identical to riichi minus red fives; no flower tiles needed.
- **Layout (mobile-first portrait, square felt):**
  - Bottom edge: own hand as large tiles, drawn tile separated with a gap and
    gold highlight; melds to the right corner, own river above the hand.
  - Top/left/right: opponents — 6-per-row river facing centre (rotated),
    melds in the corner, hidden hands as tile backs, seat wind + declared
    (宣告) lamp.
  - Centre box: wall remaining, turn number, round/seat wind, dealer +
    streak marker, "無花牌" note.
- **Interaction (Mahjong-Soul conventions):**
  - Tap/click a hand tile to discard it (hover/first-tap lifts the tile;
    setting toggles one-tap vs confirm-tap).
  - Call prompts (吃/碰/槓/胡/過) appear as a floating button row above the
    hand, with the candidate meld previewed; auto-pass timer OFF (this is a
    trainer, not a timed game).
  - Discards animate to the river; the just-cut tile stays highlighted.
- **Feedback layer (GTO-Wizard conventions):**
  - After each decision: verdict badge (best/good/inaccuracy/mistake in
    green/blue/amber/red, "邊緣" suffix preserved), EV delta, best action
    marked on the hand/buttons, expandable ranked-EV table and explain text.
  - Persistent top bar: decisions, best-rate, cumulative EV loss (the
    existing trainer scorecard).

### W3 — mode home + stats

- Landing screen with the three mode cards (整場 / 單手 / 殘局) and a
  session-history accuracy line per mode.
- Stats persisted client-side (localStorage) first; sqlite behind the API
  only if cross-device history is ever wanted.
- Retire the Streamlit app after parity check.

### Backlog (explicitly deferred)

- Flower tiles (deal-in flow, 花台, EV awareness) — largest realism gap.
- Ron modelling in attack EV (biggest model gap; currently self-draw only).
- Calibration against human-game data instead of the bot ecology.

## Non-goals

- No multiplayer, no timers, no accounts.
- No flower rules anywhere in W1–W3 beyond the visible no-flower note.
