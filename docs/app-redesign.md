# App redesign: everything happens on the table

Status: approved direction (owner, 2026-11-15). Implemented in three rounds on
branch `feat/app-redesign`, stacked on #117 → #119 → #120.

Mockup (four screens, hard-coded data): https://claude.ai/artifact/LJneR8rCX9rdbyAdtwVG64

## Porcelain studio — palette refresh (2026-11-18)

This owner-approved direction supersedes the dark surface and display-font
specifications below. Geometry, tile artwork, tile pigments and verdict colours
stay unchanged. The table uses matte blue-grey fabric, a visually thin ceramic
rail and soft blue-grey shadows. Headings and body use sans; only seat/wind
marks use serif. Existing CSS token names remain for compatibility.

Palette: page `#F3F5F7`, workspace `#E7EDF1`, felt `#B8CAD5` / `#CCDCE5` /
`#DDE8EE`, rail `#A9BBC8` / `#D4DFE7` / `#A9BBC8`, coaching `#FFFFFF`,
panels `#F8FAFC`, ink/rail ink `#203344`, accent `#B77A08`.
The felt gradient uses the three felt tokens. Gold text uses the darker edge.

WCAG AA corrections for normal text on the darkest felt (`#B8CAD5`):
dim `#465B6B` → `#3E5261`, faint `#526777` → `#425664`,
gold edge `#805400` → `#724A00`, focus `#245D89` → `#205580`.
These are the only approved palette values adjusted for contrast.

## Table styles — round 4 (2026-11-18)

The lobby's `牌桌風格` select sits beside `底台`: 瓷白 (A, default), 茶室
(B), 夜藍 (C), 聯名風 (D). The native select supports keyboard navigation
and fits beside the scheme pills at 390px. `index.html` reads
`mj-table-theme` before loading CSS; invalid or unavailable storage uses A.
Writes are guarded too and restore A if they fail. Switching the root
`data-table-theme` updates existing tiles and all app surfaces immediately.

`style.css` overrides tokens only for B/C/D. Page, felt and rail colours match
the material studies in `TILE_THEMES`; tile faces and backs keep their existing
attribute-selected palettes. B adds the woven texture, D the approved pink
confetti colours. C uses dark panels and light text throughout.

Minimum contrast ratios across each text token's surfaces (gradient endpoints
included), recomputed by `tests/check_theme_switch_browser.py`:

| Theme | Body/accent | Rail | Lobby tile/tool text | Verdict/score badges | Actions | Bold result numbers |
|---|---:|---:|---:|---:|---:|---:|
| A | 4.53 | 6.57 | 5.83 | 5.24 | 4.67 | 3.16 |
| B | 4.57 | 6.15 | 6.23 | 5.24 | 4.67 | 3.15 |
| C | 6.44 | 6.96 | 5.85 | 5.24 | 7.58 | 5.35 |
| D | 5.52 | 4.75 | 4.76 | 5.24 | 4.67 | 3.77 |

Normal text meets 4.5:1; bold result numbers meet 3:1. Decorative SVG pigments
remain the approved artwork. B uses darker secondary text `#60503e`; C uses
`#d0ddf0` secondary text and light accent/result text. D's footer ink is
`#613849` (the original `#673e50` gave 4.33:1 on the pink rail). Its lobby
lettering uses `#5e70af` / `#bd2c4c`, and tool discs use `#bd2c4c` / `#285d88`,
so decorative pigments do not become low-contrast interface text.
Verdict colours remain unchanged; their text and the EV leader/tag-chip
backgrounds keep dark pigments independently of C's light body ink.

## Why

The in-game table already reads as a mahjong table. Every other screen reads as
a web form or a report: the home page is a list of text cards, 開局 is a row of
form fields, the result page and the review rail are stat tiles and bars. The
owner's words: the app "feels far from a mahjong app's format".

The fix is one rule: **every screen is the same wood-framed felt table**. Menus
are tiles on the felt, settings sit on the wooden rail, analysis sits on a dark
panel beside the felt.

This document replaces the layout parts of `docs/frontend-redesign.md` §3 and
§5 where they differ. The honesty rules of that document stay in force:
`net_ev` is the only ranking, an unresolved ranking is never called "best",
colour always has a text partner, and model-scope disclosure stays reachable.

## Design system

Three surfaces, used the same way on every screen:

| Surface | Meaning | Look |
|---|---|---|
| Wood | The table rail. Navigation and settings. | `linear-gradient(#60412a, #3a2515)`, radius 30px, inner top highlight |
| Felt | The game. Tiles, seats, menus made of tiles. | `radial-gradient(ellipse at 50% 30%, #20705f, #124b41 60%, #0c3730)`, inset shadow, radius 18px |
| Lacquer | Analysis and coaching. | `#07231f`, 1px light inner ring, radius 18px |

Page background behind the table: `#0b1f1c`.

Keep the existing tile art (`tiles.js`, `tile-faces.js`), tile colours, verdict
colours (`--q-*`), gold accent `#e0a300`, and fonts (`--serif` for display,
`--sans` for text). Update `--wood` and add tokens for the surfaces above; do
not rename existing tokens that other rules use.

Shared parts:

- **Table shell.** Wood frame around the whole screen. A header on the wood:
  back pill (`‹ 大廳`, min 44px tall), serif screen title, and a right-aligned
  context line. Below 700px the frame thins (padding ≤ 6px, radius ≤ 16px) so
  it does not eat the screen.
- **Primary action.** Gold slab button, serif, with a darker gold bottom edge
  (`box-shadow: 0 5px 0 #8a6400`).
- **Seat plate.** Small dark pill: wind character in serif gold, seat name,
  tile count.
- **Verdict seal.** A 66px rounded square in the verdict colour, serif label,
  rotated −4°. Text is the existing `VERDICT_LABELS` value (or `≈` for an
  unresolved pick). It replaces the pill badge as the headline of a graded
  decision; the pill stays for dense lists.
- **Token.** A 40px round disc with one serif character, for a decision that
  has no tile: `過` (pass), `吃`, `碰`, `槓`.

Rules:

- No chains of middle dots (`A · B · C`) in new copy. Write a short sentence.
- Do not add emoji. Use the drawn tiles and inline SVG.
- Touch targets ≥ 44px. Visible keyboard focus on every control.
- `prefers-reduced-motion` turns off the tile lift.
- Every screen fits 1280, 390 and 320px wide with no sideways page scroll
  (the table itself may scroll inside its own box, as it does today).

## Screens

### 1. 大廳 (home, `main.js`)

- Title `台灣麻將教室` with the 中 crest moves onto the wood header.
- The 底台 toggle (`schemeToggle`) and the `打牌免確認` checkbox move onto the
  wood header, right side. Same behaviour, same storage keys.
- On the felt: heading `今天練哪一種？`, then the five modes as **big tiles**
  (about 104×143px, bone face, two stacked serif characters like a 萬 tile:
  first character ink, second cinnabar): 整場, 單手, 殘局, 攻守, 教學.
  Each tile is a link. Hover and keyboard focus lift the tile 12px.
  整場 carries the gold outline the table uses for the drawn tile.
- Under each tile: one short line saying what the mode is, then the stats line
  from `summary()` (`已答 N，品質 X%`; 攻守 keeps its 正確率 wording) or
  `還沒練過`. The sparkline is dropped.
- Under the tiles: 算台 and 打牌分析 as two pill links, each with a round
  token (台 on cinnabar, 析 on tile blue).
- The long footnote moves into a closed `<details>` on the wood footer,
  summary `分數是怎麼算的`. **Keep the existing disclosure text verbatim**,
  including the legacy-stats sentence; `tests/test_claims.py` guards it.
- Tiles wrap on narrow screens (two or three per row at phone width).

### 2. 開局 (trainer setup, `trainer.js` `setupScreen`)

- Heading on the felt: `這一局誰做莊？`
- A 3×3 grid replaces the `你的座位` select. Four seat buttons sit at top
  (對家), left (上家), right (下家) and bottom (你). Pressing one makes that
  seat the dealer: gold ring, a gold `莊` chip, and the four wind characters
  rotate so the dealer is 東 (counter-clockwise: you → 下家 → 對家 → 上家).
  The buttons carry `aria-pressed`. They submit the same seat value the
  select submits today.
- Centre cell: the deal number. Keep an editable `input#tr-seed` (deterministic
  seeds are a product feature and the browser checks fill it), styled as a
  large number, labelled `這副牌的編號`, plus a `換一副` button that rolls a
  new random seed.
- `初始連莊數` becomes a − / number / + stepper labelled `已經連莊 N 次`,
  with the same limits as today. Keep `#tr-streak` on the control that holds
  the value.
- The 底台 toggle stays reachable on this screen (wood header).
- Primary action keeps its accessible name `開始新局`.
- A row of 16 face-down tiles (`tileBackEl`) along the bottom of the felt,
  decorative (`aria-hidden`).

### 3. 對局與教練 (table + review rail, `feedback.js` `reviewRailEl`)

The table does not change. The rail stops being a dashboard.

Top to bottom on the lacquer panel:

1. Verdict seal + serif title (`第 N 手，你打二筒` when the move number is
   known, else the existing choice text) + one line with the gap to the model
   leader.
2. The ranking banner (`rankingBannerEl`), unchanged in meaning.
3. **Option list**: one row per candidate, best first: small tile, tile name,
   gap to the leader, verdict pill. The chosen row is tinted and says it is
   yours. Rows inside an unresolved top pair show `≈`, never a number that
   implies an order. Use the same thresholds the tile badges use
   (`tileScores` / `verdict_thresholds`).
4. `詳細數字` — a closed `<details>` holding what the rail shows today as
   metric tiles and the 選項格 table (`evTableEl`). Nothing is deleted; it is
   one click away. The 摘要 / 選項格 tabs go.
5. `這次練習的統計` — a closed `<details>` holding `qualitySummaryEl`
   unchanged (issue #118 still decides its formula).
6. `分數是怎麼算的` — a closed `<details>` holding `modelScopeEl`.

The rail is shared by 整場, 單手 and 殘局; all three get the new layout. 攻守
builds its own rail in `attack-defense.js` (its grade is right/wrong per tap,
with no net-EV options), so it gets the lacquer panel but keeps its content.

### 4. 結算與牌譜 (trainer result, `trainer.js` `outcomeScreen` + `handReviewEl`)

Felt:

- Serif headline for the result (`放槍`, `自摸`, `流局`, …) with the player's
  net points beside it, then one sentence saying who won on which tile.
- Winner's hand and melds as today (#120 wrapping stays).
- One sentence for 台數 and the dealer change. Then `再來一局` (primary) and
  `結束`.

Lacquer panel below, titled `這一局的牌譜`:

- One sentence instead of stat tiles, built from `handSummary()`:
  `你做了 15 個決定。13 個排名分得出來，其中 10 個是模型領先或正確，品質
  77%。整局一共少拿 4.30 分。` When nothing is separable the score reads `—`
  as today.
- A legend that is also the tally: one pill per verdict with its count
  (模型領先, 正確, 小失誤, 失誤, ≈ 無法區分).
- **The river**: every graded decision in play order, six per row like a
  discard river. A discard is drawn as its tile. A pass or a call is a token.
  Above each: the move number. Below each: the verdict pill (`≈` for an
  unresolved pick).
- Each move is a `<button>` with a full `aria-label`
  (`第 6 手，你打二筒，失誤`). Pressing it opens that move's full feedback,
  exactly as the #119 rows do, and `‹ 回結果` returns focus to the same move.
  Keep the `data-review` index attribute.
- The grading rule is the #119 one: a pick inside an unresolved top pair is
  left out; every other move counts by the pill the player sees.

## Not in this redesign

- A tile keypad for 算台 and 打牌分析 (they keep typed input; new behaviour,
  not approved). They get the table shell only.
- Any engine, API or grading change. This is front-end only.
- The review rail's quality formula (issue #118).

## Rounds

1. Table shell on every route, 大廳, 開局.
2. 教練 rail.
3. 結算與牌譜.

Each round ends green on:

```
PYTHONPATH=. python -m pytest -m "not slow" -q
PYTHONPATH=. python scripts/check_phone_layout.py
PYTHONPATH=. python tests/check_tile_score_browser.py
PYTHONPATH=. python tests/check_hand_review_browser.py
```
