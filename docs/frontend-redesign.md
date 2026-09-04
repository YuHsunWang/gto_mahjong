# Taiwanese 16-tile mahjong front-end redesign

Status: design proposal only. This round does not change the engine, API, or shipped front end. The clickable, hard-coded companion is `docs/prototype/index.html`.

## 1. Product direction

Evolve the current no-build vanilla SPA into a landscape table plus an analysis rail. Preserve its plum felt, warm bone tiles, gold interaction accent, Traditional Chinese copy, deterministic seeded training, and explicit model-scope disclosure. “GTO Wizard style” means fast comparative review, not a claim that this engine solves a game-theoretic equilibrium.

The primary desktop composition is a bounded 16:10 table at left and a 380–420 px review rail at right. The table owns the four seats, four discard rivers, melds, live hand, and centre status. The rail owns the current decision, session summary, move-quality distribution, and per-option grid. At 900–1199 px the rail moves below the table. Below 700 px the board becomes a horizontally scrollable minimum-width landscape canvas; this redesign removes the current short-landscape refusal because landscape is now the intended play orientation.

Design principles:

- `net_ev` is the only decision comparison. No attack/defence split, danger dial, or bar made from `attack_ev` and `risk_ev`.
- Unresolvable order is an outcome, not a caveat. Indistinguishable candidates share a neutral violet treatment and no tile is called “best.”
- Colour always has a text/icon partner. Quality colours are not used for raw danger.
- The analysis rail is dense but inspectable: headline first, evidence one click away.
- All model claims retain scheme, simulation budget, calibration/fallback, and bot-domain disclosure.

## 2. Existing implementation audit

The current UI is already a static SPA (`server/static/index.html`) using one stylesheet and vanilla ES modules. `table.js` renders a square 3×3 felt; opponents are rotated around it, while the player hand is a separate tray below. `tiles.js` constructs SVG faces using pip/stick primitives plus generated Noto Serif outlines from `tile-faces.js`. `feedback.js` renders one verdict, an eight-column EV table, a fold plan, and a top-two uncertainty note. `stats.js` persists only `{best flag, EV loss}` per decision. `quiz.js` and `trainer.js` still use “estimated best” language even when the top-two payload is uncertain.

The relevant engine/API facts are:

- `taimahjong/quiz.py::verdict_for_delta` emits only `best`, `good`, `inaccuracy`, and `mistake`, at EV-loss boundaries 0, 0.3, and 1.0.
- `taimahjong/quiz.py::grade` computes `ranking_uncertain` when paired top-two moments cross zero or the absolute mean is below `EV_EFFECT_SIZE_MIN=0.10`, but only exposes that indirectly through `marginal`; `server/api.py::_top_gap_payload` separately exposes `wording`, `crosses_zero`, `mean`, and `descriptive_interval95`.
- `server/api.py::_entry_payload` exposes `net_ev`, `p_win`, `p_draw`, `mean_win_value`, sample/interval fields and diagnostic slices. Only `net_ev` ranks decisions.
- `survival_adjusted_p_win` equals `p_win` on the terminal rollout (`taimahjong/ev.py::_rollout_entry`) and must disappear from presentation.
- `FoldActionPlan.safe_inventory` is conditional and often empty. A fold plan is rendered only when `action_plan` exists; an empty inventory gets explanatory copy, never a permanent empty rack.
- Current score state is `server/api.py::_TrainerSession.score`: `decisions`, `best`, and cumulative `loss`. The engine has hand outcomes (`TrainerOutcome`) but no multi-hand session counter or seat-score array.

## 3. Landscape table

### Structure

Use one `.table-workspace` grid with a `.mahjong-table` at a 16:10 aspect ratio:

```text
┌─────────────────────────────────────────────────────────┐
│ top identity        top melds       top river           │
│ left melds/river    centre status   right river/melds    │
│ own river              live hand + own melds            │
└─────────────────────────────────────────────────────────┘  review rail
```

Each seat is an explicit grid area, not a rotated copy of one generic zone. Top and bottom rivers are 6-column grids; side rivers use six-tile columns flowing toward the centre. Tile faces may rotate toward their owner, but seat names, scores, provenance labels, and accessibility text stay upright. Melds sit between each seat’s river and outer edge. The live 16/17-tile hand is embedded along the bottom rim with the drawn tile separated by a 10–14 px gap. Minimum interactive tile target remains 44 px even if the drawn face is smaller.

Centre status uses fields already emitted by `_position_payload`: `position.turn`, `position.wall_remaining`, `position.draws_remaining`, `position.seat`, `position.is_dealer`, and `position.dealer_streak`. “本桌無花牌” remains visible. Four score cells are reserved, but marked unavailable until an optional `position.seat_scores` API field exists; do not substitute EV, tenpai estimate, or hand count for score.

### `table.js` changes

- Replace the square `feltEl` DOM order with semantic `<section class="seat seat--top|right|bottom|left">` regions inside a landscape table.
- Split `opponentZone` into seat identity, `riverEl`, and `meldRackEl` so each orientation has deliberate DOM placement instead of rotating the whole zone.
- Move `handEl` into the bottom seat region for play screens; retain a standalone variant for lessons/tools.
- Make river numbering explicit in DOM (`data-discard-number=index+1`) for inspection and provenance anchors.
- Add `meldRackEl(melds, meldDetails, ownerSeat)`; prefer additive detail payloads and fall back to bare meld arrays.
- Add accessible labels such as “西家第八張棄牌所鳴” and keep arrows `aria-hidden`.
- Replace `marks.best` with `marks.modelLeader` and `marks.indistinguishable`; never apply a green leader frame when `top1_vs_top2.wording !== 'clear'`.

### CSS changes

- Widen `.app` from 520 px to a workspace cap around 1480 px and add the board/review grid.
- Change `.felt` from `aspect-ratio:1/1` and the current 3×3 areas to a bounded `aspect-ratio:16/10` grid with explicit seat bands.
- Remove rotation from whole `.zone` nodes; orient river/meld contents only.
- Move `.handrow` into the felt bottom area, use size custom properties, and retain gold focus/drawn states.
- Replace the `orientation:landscape` rotate overlay with a compact landscape density rule; at narrow widths, allow the board wrapper—not the page—to scroll horizontally.
- Add semantic tokens for `--q-best`, `--q-correct`, `--q-inaccuracy`, `--q-wrong`, `--q-blunder`, and `--q-unresolved`, with patterned borders for unresolved and high-contrast/non-colour labels.

## 4. Upgraded self-drawn SVG tile system

No third-party game art is used. `tile-faces.js` becomes a vector-definition module rather than a generated glyph dump:

- `FACE_TOKENS`: theme-aware ink colours (`wind`, `red`, `blue`, `green`), bone highlight, engraved shadow, and stroke widths.
- `NUMERAL_PATHS` and `HONOR_PATHS`: our own simplified, grid-fitted vector glyphs with consistent optical weight. The existing licensed Noto-derived paths may remain during migration, but the target system contains newly drawn paths and its own authorship note.
- `DOT_LAYOUTS`: concentric rings, petal marks, and a distinctive one-dot rosette; five-dot keeps a red centre.
- `BAMBOO_LAYOUTS`: paired leaf/stalk motifs, with a stylised bird-like abstract one-bamboo made only from geometric leaves (not copied character art).
- `FACE_BUILDERS`: `man`, `dot`, `bamboo`, `honor`, `whiteDragon`, and `back`, all sharing one viewBox.

`tiles.js::tileEl` keeps the existing 0–33 index contract but composes three layers: body SVG (top highlight, side edge, bottom bevel/shadow), face SVG, and state overlay. States are CSS/SVG-token driven: `drawn`, `selected`, `dimmed`, `model-leader`, `indistinguishable`, `cut`, and `tile-back`. Dimmed tiles retain at least 55% opacity and readable outlines. Dark/light table themes change CSS variables, not face markup. `tiles-demo.html` becomes the visual QA sheet for all 34 faces, both themes, both sizes, and every state.

## 5. Feedback surface and real-field mapping

The session review rail has two views: **Summary** and **Options**. It borrows the rapid hierarchy of poker analysis tools without using “GTO” in product claims.

| Surface element | Display | Source and computation |
| --- | --- | --- |
| Hands | completed hands | UI session aggregation: increment on each `TrainerOutcome` from `server/api.py::_decision_payload`; current API has no multi-hand count. Persist in `stats.js`. |
| Moves | all graded decisions | `scorecard.decisions` for the current server session; cross-hand history is the count of recorded grade events. |
| Headline percentage | “Quality score” | UI-derived `(best + good) / separable_moves × 100`, where categories come from `grade.verdict`; exclude `top1_vs_top2.wording !== 'clear'` from the denominator and show the excluded count beside it. This avoids rewarding/punishing an unresolved rank. |
| Best move | count | `grade.verdict === 'best'`, only for separable decisions. UI wording is “Model leader” in detailed views. |
| Correct move | count | `grade.verdict === 'good'`. |
| Inaccuracy | count | `grade.verdict === 'inaccuracy'`. |
| Wrong move | count | `grade.verdict === 'mistake'`. |
| Blunder | unavailable, shown as `—` | No such grade exists in `quiz.py`; do not infer it from a new arbitrary EV threshold. A future fifth verdict needs an engine/product threshold and migration of historical stats. |
| Unresolved | separate first-class count | `top1_vs_top2.wording === 'uncertain'` (or `crosses_zero === true`). This is not folded into Correct/Best. |
| Avg EV loss/hand | signed-unit loss per completed hand | `sum(grade.ev_loss) / hands_completed`; `ev_loss` comes from `_grade_payload`, hands from outcomes. Also show units/scheme. Do not reuse current “loss / decisions,” which is per move. |
| Per-option grid | coloured option cells | Tile/action plus `entry.net_ev`; gap is `max(net_ev)-entry.net_ev`. Apply existing `verdict_for_delta` bands only as estimated quality bands. For the top two, override both with unresolved styling when paired `top1_vs_top2.wording` is not `clear`. |
| Current-choice evidence | chosen value and delta | `grade.chosen.net_ev`, `grade.ev_delta`, `grade.ev_loss`, `grade.refined_sims`, and `grade.rank_position`. |
| Uncertainty banner | “模型無法區分” | `top1_vs_top2.top_discard`, `runner_up_discard`, `mean`, `descriptive_interval95`, `crosses_zero`, `effect_small`, and `wording` from `_top_gap_payload`. |
| Other expandable evidence | probability/value context | `p_win`, `p_draw`, `mean_win_value`, `sample_count`, `se`, `ci95`; never show `survival_adjusted_p_win`. |

Do not render `attack_ev` or `risk_ev` as competing qualities. They are positive/negative slices of the same signed terminal payments, not attack power and danger. If retained for audit at all, they belong in a developer-only raw-payload view with that exact warning. Do not build a high-resolution danger heat map: the current calibration has no meaningful separation above score 9 and a very low model-wide ceiling.

Fold advice is conditional. Render a “multi-turn defence plan” card only when `entry.action_plan` exists. Render `safe_inventory` only when non-empty; otherwise say that no declared-hand safe inventory is available. Never reserve an always-empty panel.

## 6. First-class unresolvable-ranking state

Trigger when `top1_vs_top2.wording` is `uncertain` or `marginal`; use stronger copy for `uncertain`:

> 模型無法區分這兩個選項  
> 九萬與五條的 paired EV 差為 +0.03；描述區間跨過 0。兩者在目前模擬預算下視為同等可選。

Visual treatment:

- A full-width violet, diagonally patterned banner directly below the decision—not inside `<details>`.
- Both candidates receive the same `≈` badge, violet outline, and “無法區分” label in the hand and option grid.
- Suppress green “best” framing, ordinal #1/#2 emphasis, “最佳打牌,” and any score penalty/reward for choosing either top candidate.
- Keep the point estimates visible, labelled “estimate,” without implying the order is established.
- The expandable evidence shows paired mean, descriptive interval, samples, and the existing post-selection interval note.
- `marginal` with an interval wholly on one side of zero uses “差異很小” and a softer paired highlight; `clear` alone permits “模型領先選項.”

API improvement: add explicit `ranking_uncertain: bool` and `ranking_state: 'clear'|'marginal'|'uncertain'` to `_grade_payload`. They duplicate the derived top-gap state intentionally so clients do not confuse verdict-boundary `marginal` with ranking uncertainty. Keep `marginal` for backward compatibility.

## 7. Meld provenance: required cross-layer change

### Domain model

Add a value type in the engine’s shared public-state layer (recommended location: `taimahjong/danger.py`, or a new focused model module if approved):

```python
MeldTiles = tuple[int, int, int]

@dataclass(frozen=True)
class DeclaredMeld:
    tiles: MeldTiles
    called_tile: int | None = None
    called_from_seat: int | None = None
    called_from_discard_number: int | None = None  # 1-based within source river
```

All three call fields are null together for unknown/legacy provenance. `called_tile` is the tile index of the claimed discard (necessary because a sorted chi triple cannot reveal it). `called_from_seat` is absolute table seat 0–3; the UI derives arrow direction relative to the meld owner. `called_from_discard_number` is the source player’s 1-based discard ordinal before the claimed tile is removed from their river. Validate tile/seat range, positive discard number, three-tile shape, and that `called_tile` occurs in `tiles` when provenance is known.

Define `MeldLike = MeldTiles | DeclaredMeld` and one `meld_tiles(value)` normalizer. Public scoring, danger, EV, quiz, and CLI functions accept `MeldLike`; their internal shape/count logic always calls the normalizer. Thus existing callers passing bare triples—including `_parse_opponent_melds` in `taimahjong/__main__.py`, `_parse_melds` in `server/api.py`, and `score_hand` callers—continue to work unchanged and receive unknown provenance.

### Capture and propagation

In `taimahjong/selfplay.py` and `taimahjong/trainer.py`, capture provenance when resolving a successful chi/pon call:

1. The discarder has already appended the `RiverEntry` and incremented `player.discards`.
2. Before `river.pop()`, create `DeclaredMeld(tiles=meld, called_tile=tile, called_from_seat=current, called_from_discard_number=players[current].discards)`.
3. Append that object to the caller’s meld list.
4. In the same dependency phase, add `DeclaredKong(tile, concealed, called_from_seat=None, called_from_discard_number=None)` as the tuple-compatible equivalent of the existing `(tile, concealed)` representation. Big open kongs capture the discarder and ordinal before `river.pop()`; concealed/added kongs keep null call provenance. Add `kong_tiles(value)` for legacy compatibility and additive `own_kong_details` JSON rather than pretending a four-tile kong is a triple.
5. `_position_from`/`_trainer_position` carry `DeclaredMeld` objects into `QuizPosition.own_melds` and `QuizOpponent.melds`; scoring/danger receive normalized tiles.

This is necessary because the current successful-call branches remove the source discard and append only a tuple, permanently losing both facts.

### Additive API response

Preserve current fields exactly:

```json
"own_melds": [[3,4,5]],
"opponents": [{"melds": [[18,18,18]]}]
```

Add parallel detail fields so old clients remain valid:

```json
"own_meld_details": [
  {"tiles":[3,4,5], "called_tile":5, "called_from_seat":3, "called_from_discard_number":8}
],
"opponents": [{
  "meld_details":[
    {"tiles":[18,18,18], "called_tile":18, "called_from_seat":1, "called_from_discard_number":6}
  ]
}]
```

Unknown legacy provenance serializes both values as `null`; array order matches `*_melds`. `table.js` uses details when present and falls back to arrays. For a known call, the meld rack adds an upright label such as `← 8` (arrow points toward source seat, number is the source discard ordinal) plus accessible text. The source river need not still contain the claimed tile.

## 8. Existing files: concrete change map

| File | Planned change |
| --- | --- |
| `server/static/index.html` | Replace the portrait rotate notice with a workspace shell/skip link; keep the same ES-module entry point. |
| `server/static/style.css` | New wide workspace, 16:10 seat grid, integrated bottom hand, review rail, responsive fallback, provenance badges, uncertainty patterns, and expanded tile states/tokens. |
| `server/static/js/table.js` | Semantic seat renderer, orientation-specific rivers, integrated hand, meld-detail fallback, provenance arrow/number, score placeholders, and uncertainty marks. |
| `server/static/js/tiles.js` | Keep index/text/parsing API; compose body/face/state SVG layers and add `md`, back, selected, dimmed, and indistinguishable options. |
| `server/static/js/tile-faces.js` | Replace/augment generated glyph-only data with our coherent face tokens, layouts, and original paths/builders; document authorship and licensing. |
| `server/static/js/feedback.js` | Add summary/options views, quality aggregation renderer, option grid, primary uncertainty banner, honest labels, remove stale survival column, and avoid always-present safe inventory. |
| `server/static/js/stats.js` | Version storage; retain verdict, `ev_loss`, ranking state, decision kind, hand/session ID, scheme, and outcome events; migrate v2 records as limited legacy data. |
| `server/static/js/quiz.js` | Use ranking state before applying leader wording/marks; send complete grade event to stats; compose board plus review rail. |
| `server/static/js/trainer.js` | Same feedback rules; record outcomes/hands; maintain a cross-hand client session summary; consume meld details and optional scores. |
| `server/static/js/lessons.js` | Use upgraded tiles and shared standalone tray only; no session feedback surface. Also separately correct audited teaching copy before release. |
| `server/static/js/tools.js` | Use the option-grid/table comparison and uncertainty banner for analysis output; never show stale survival probability or attack/risk gauges. |
| `server/static/tiles-demo.html` | Become the all-faces/all-states/light-dark visual QA page. |
| `server/static/js/main.js` | Remove any “GTO best solution” language and host the responsive workspace routes. |
| `server/static/js/api.js`, `scheme.js` | No structural change expected; pass through additive response fields. |
| `server/api.py` | Future phase only: serialize meld details, explicit ranking state, and optional seat scores; keep existing array fields. |
| `taimahjong/danger.py`, `quiz.py`, `selfplay.py`, `trainer.py`, `scoring.py`, `ev.py` | Future provenance phase only: introduce/accept `MeldLike`, capture calls, propagate public state, and normalize before all tile logic. |
| `taimahjong/__main__.py` | Parser continues returning bare triples; optional richer CLI syntax is deferred, proving backward compatibility. |

## 9. Dependency-ordered delivery plan

1. **Provenance contract and compatibility tests.** Add `DeclaredMeld`/normalizer, tuple compatibility tests, capture metadata before river removal, and additive serialization. This must land before provenance UI.
2. **Honest response semantics.** Add explicit ranking state; confirm session event schema and whether seat scores will be tracked. No visual “best” rewrite should ship before this state is unambiguous.
3. **SVG tile foundation.** Build the 34-face visual QA sheet, theme tokens, and states while retaining `tileEl` callers.
4. **Landscape table.** Refactor `table.js` and CSS, consume optional meld details, embed the hand, and add centre score empty/optional states.
5. **Feedback and stats.** Add event history, session aggregation, summary/options panels, uncertainty override, and responsive comparison views.
6. **Screen integration.** Update quiz, trainer, tools, lessons, and home wording/layout; migrate legacy local stats conservatively.
7. **Accessibility and visual regression.** Keyboard/touch flows, screen-reader labels, contrast, reduced motion, 1366×768/1440×900/tablet/phone-landscape captures, and direct-file prototype parity review.

## 10. Open questions

1. Should a fifth `blunder` verdict be added? Recommendation: no until model owners define and validate a scheme-aware EV-loss threshold; show unavailable meanwhile.
2. Does “Hands” mean completed trainer rounds only, or should quiz/endgame questions also count as hands? Recommendation: completed trainer `TrainerOutcome` only; call the others “questions.”
3. Should seat scores become authoritative cumulative table balances, or remain absent because trainer sessions currently model one hand at a time? Recommendation: add optional `seat_scores` only with a defined reset/carry policy.
4. Should added kongs preserve the original pon call provenance as well as the later added-kong event? Recommendation: preserve the original call fields and add a separate optional `upgraded_at_own_draw_number` only if replay/audit needs it.
5. Is discard number the original ordinal including claimed/disappeared discards (recommended), or the tile’s current visual slot in the remaining river? The former is stable and auditable.
6. Should unresolved choices be excluded from the headline denominator (recommended) or counted as correct? Exclusion is statistically cleaner but needs explicit explanatory copy.
7. May the existing Noto-derived honour paths remain during the original-path migration, or must the first production release contain only newly drawn glyphs?
