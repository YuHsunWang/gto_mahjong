# DEV-116 — UI redesign plan for the static EV trainer

## Scope and guardrails

This is a frontend redesign plan, not a proposal to replace the SPA architecture. Keep the no-build-step runtime: static `index.html`, one stylesheet, and vanilla ES modules. Keep the original product boundaries: no flowers other than the visible no-flower notice, no multiplayer, no timers, and no accounts (`docs/ui-plan.md:69-76`). Keep the existing three training modes and the analysis-tool character of the product (`docs/ui-plan.md:15-35`).

The objective is to sharpen the existing Taiwanese-mahjong table identity and make it work deliberately from a narrow portrait phone through desktop. It is **not** to turn the application into a generic dashboard.

## 1. Current-state audit

### What is actually shipped

- The document is a minimal Traditional-Chinese shell: it declares a viewport, supplies `#app`, and loads `js/main.js` as an ES module (`server/static/index.html:2-21`). The hash router replaces that one app root and exposes home, trainer, quiz, endgame, lessons, analyse, and scoring screens (`server/static/js/main.js:11-12`, `server/static/js/main.js:134-152`).
- The present content column is deliberately phone-width: `.app` is capped at 520 px with a 10 px gutter and safe-area bottom padding (`server/static/style.css:43-47`). Home cards are a single vertical flex stack (`server/static/style.css:600-612`).
- The play surface is a true square grid (`aspect-ratio: 1 / 1`), with four player zones converging on a centre box; top/left/right zones are rotated to create a table reading (`server/static/style.css:159-180`). Rivers use six columns (`server/static/style.css:182-187`). The renderer puts opponent melds and rivers in those zones, the own river at the bottom, and upright seat lamps over the felt (`server/static/js/table.js:58-66`, `server/static/js/table.js:102-136`).
- The hand is a separate tray below the felt. A drawn tile is removed from its normal position, reinserted after a gap, and given the `drawn` class; declared melds occupy a separated right-side rack (`server/static/js/table.js:143-202`). The interactive discard flow is confirm-tap by default, with an existing local one-tap setting (`server/static/js/table.js:154-185`; `server/static/js/main.js:114-121`).
- The centre box explicitly renders the required `本桌無花牌` notice (`server/static/js/table.js:69-98`). This must remain visible after the redesign.

### Identity to preserve and sharpen

The stylesheet itself says that its identity came from the retired Streamlit UI: plum felt, bone tiles, a gold drawn-tile frame, and Noto Serif TC tile faces (`server/static/style.css:1-3`). These are the design primitives, not incidental colours:

| Primitive | Existing implementation | Redesign rule |
| --- | --- | --- |
| Plum table / depth | `--felt-0`, `--felt-1`, `--felt-2`, `--wood`, `--bg`, and translucent `--panel` define the field, rim, page, and panels (`server/static/style.css:5-18`). | Preserve the plum-to-violet felt gradient and wood rim. Improve hierarchy with spacing, surface contrast, and restrained texture only; do not substitute a white/gray dashboard surface. |
| Bone tile material | `--bone`, `--bone-edge`, and `--bone-shadow` create the tile face, edge, and physical shadow (`server/static/style.css:15-17`, `server/static/style.css:113-131`). | Retain warm bone faces and physical edges at every breakpoint; scale tokens, not a bitmap or emoji substitute. |
| Gold as “current / actionable” | `--gold` frames a drawn tile and a lifted selection (`server/static/style.css:139-143`, `server/static/style.css:261-273`), and also identifies the selected scoring scheme and primary actions (`server/static/style.css:316-323`, `server/static/style.css:477-482`). | Keep gold reserved for focus, the drawn tile, selected controls, and the primary next action. Do not spend it on decorative chrome. |
| Tile typography and faces | Tiles use `--serif` (`server/static/style.css:113-128`); client code builds graphic suit and honour faces rather than relying on emoji (`server/static/js/tiles.js:40-122`, `server/static/js/tiles.js:137-151`). | Preserve the Noto Serif TC / PMingLiU fallback stack and the generated SVG faces. Maintain legibility before making tiles more ornamental. |
| EV feedback semantics | Verdicts map best/good/inaccuracy/mistake to the four `--v-*` colours (`server/static/style.css:354-384`), and the renderer reports the verdict plus EV delta (`server/static/js/feedback.js:12-25`). | Retain this semantic colour system and tabular numerals; never communicate analysis quality by colour alone. |

The existing visual language already extends beyond the table: panels, cards, and lesson trays reuse plum gradients and gold hover/focus affordances (`server/static/style.css:602-619`, `server/static/style.css:651-660`, `server/static/style.css:500-504`). The refresh should make those pieces feel like one table-side instrument panel.

### Responsive and information-density findings

- Aside from reduced-motion rules (`server/static/style.css:152-155`, `server/static/style.css:413-414`, `server/static/style.css:561-563`), there is no width breakpoint. Short landscape phones are intentionally refused: at landscape and 560 px-or-less height, the rotate prompt replaces `.app` and `.toast` (`server/static/style.css:533-568`).
- The ranked EV renderer creates all eight headers and all eight numeric values for every non-fold entry (`server/static/js/feedback.js:35-58`). The same open EV-details component is used after quiz feedback (`server/static/js/quiz.js:134-158`), after trainer discard feedback (`server/static/js/trainer.js:313-331`), and as the expanded output of the analysis tool (`server/static/js/tools.js:101-129`).
- Its current visual contract is a full-width, 12.5 px, no-wrap table inside an `overflow-x: auto` wrapper (`server/static/style.css:424-444`). Thus the narrow-screen problem is shared by practice feedback and the standalone analysis tool, not one isolated screen.
- The EV details are intentionally an analysis disclosure: they also append a fold plan, paired top-two uncertainty, and textual explanation when the payload has them (`server/static/js/feedback.js:83-112`). The redesign must retain those facts rather than compressing them into a decorative “score.”

## 2. Responsive strategy

### Proposed breakpoint set

Use CSS custom properties plus four width ranges, with one height/orientation override:

| Range | Layout contract |
| --- | --- |
| `0–359px` (compact portrait) | One column; preserve the square felt at full available width, reduce only board rim/gaps/seat-label detail through component variables, and keep the hand horizontally complete. Use the narrow EV-card presentation. |
| `360–599px` (phone portrait) | One column; felt, hand tray, feedback, and controls remain vertically ordered. The felt is `width: 100%` with a sensible maximum, never stretched into a rectangle. Use EV cards. |
| `600–899px` (tablet / large phone) | Give the app a larger capped content width. Keep the felt square and retain a vertical board-then-analysis reading order. Use EV cards until the full table’s 720 px minimum is available. |
| `900–1279px` (small desktop / landscape tablet) | Use desktop density and a wider capped content column, but keep board and full-width analysis vertically ordered so the eight-column table has its 720 px minimum. Home mode cards can become a two-column grid while preserving their felt-card treatment. |
| `1280px+` (wide desktop) | Use a bounded two-column workspace only after a square board column and a 720 px minimum analysis rail can coexist. Full eight-column table is the default in that rail. |
| `landscape and max-height: 560px` | Subject to Decision 2, either retain the explicit orientation prompt or use a compact landscape workspace. This is separate from width because a 844×390 phone and a 1024×768 tablet need different treatment. |

For all ranges, define named scale variables for board rim, in-felt tile size, tray tile size, gaps, and panel padding. The felt remains `aspect-ratio: 1`; it should be centred in its column with `width: min(100%, <range cap>)`. Do not use CSS transforms to shrink the entire board: that produces blurred text and poor touch geometry. At compact width, shorten/stack secondary seat metadata and allow the centre box to be concise, but retain turn, wall, declared state, offered tile when applicable, and `本桌無花牌` because the renderer currently makes each of these game-state elements available (`server/static/js/table.js:26-55`, `server/static/js/table.js:69-98`).

### Landscape decision and cost

**Recommendation, pending Decision 2:** support short landscape as a compact, scrollable analysis workspace rather than a full-screen refusal. At 568 px-or-wider landscape, place a capped square felt and hand/action rail side by side; use the EV cards under or beside them. At narrower landscape widths, retain the orientation prompt because neither 44 px-class touch targets nor the square board can fit safely.

Cost: **medium**. It needs a board-density variant, a short-height hand/action layout, a visual regression matrix, and keyboard/touch checks. It does not require a new renderer or a dependency. The present refusal is intentional and documented in CSS, so changing it must be an owner decision, not an accidental side effect (`server/static/style.css:533-568`).

## 3. The EV-table problem

### Recommendation: responsive ranked cards on narrow screens; full table when space permits

For viewports narrower than 720 px, replace only the *presentation* of the ranked eight-value dataset with a ranked list of semantic cards. Keep the existing sort order, chosen-row and best-row signals, numerical precision, and every value. A card should have:

1. A fixed header: rank, cut tile, `淨EV`, and its chosen/best status.
2. A primary comparison strip, always visible: `淨EV`, `95% CI`, and `P(自摸)`.
3. A compact “more metrics” disclosure in each card: `存活P(和)`, `P(流局)`, `E[和牌值]`, and `E[放銃]`, with the same decimal formatting as today.
4. An “expand all metrics” control above the list, plus the existing fold policy, top-two uncertainty, and explanation below the ranked entries.

This is better than a horizontally scrolling eight-column table on a phone because the analysis comparison starts with the decision and its uncertainty, while the rest remains one tap away in the same ranked row. It does **not** hide or round data. Use repeated labels, tabular numerals, and aligned metric cells so players can compare two expanded cards without mental remapping.

Essential at first glance: `切牌`, `淨EV`, `95% CI`, and `P(自摸)`. Progressive disclosure: `存活P(和)`, `P(流局)`, `E[和牌值]`, and `E[放銃]`. The distinction is a screen-density decision, not a claim that secondary metrics are unimportant: `E[放銃]` and survival probability are particularly relevant to defensive choices, and all eight are presently emitted by the renderer (`server/static/js/feedback.js:41-54`). At 720 px and above, retain the semantic eight-column `<table>` for scan-across comparison. Avoid a permanent “mobile table” toggle: automatic cards below 720 px and tables at/above 720 px make the analysis mode predictable. Decision 3 asks the owner to confirm that default.

## 4. Phase 0 — screenshot baseline before any UI change

Do not run this during planning. Add Playwright as **development-only** tooling in its own preparatory change; it is not a runtime dependency and does not alter the no-build-step SPA. The exact future setup commands are:

```bash
npm install --save-dev @playwright/test
npx playwright install chromium
```

Start the existing server in terminal A, then run the baseline in terminal B:

```bash
uvicorn server.api:app --port 8000
UI_BASE_URL=http://127.0.0.1:8000 npx playwright test tests/ui/baseline.spec.mjs --workers=1
find docs/ui-baseline/before -type f -name '*.png' | sort
```

The server command is consistent with the documented local entrypoint (`README.md:20-26`) and the app mounts `server/static/` after API routes (`server/api.py:755-764`). The final `find` must list 63 images. Store them at `docs/ui-baseline/before/<screen>/<viewport>.png`; create the matching `docs/ui-baseline/after/` tree for the post-change capture. Keep both sets together for direct review.

Create `tests/ui/baseline.spec.mjs` with this exact script (only in the future Phase 0 tooling change):

```js
import { test, expect } from '@playwright/test';

const baseURL = process.env.UI_BASE_URL || 'http://127.0.0.1:8000';
const viewports = [
  { name: 'phone-compact-320x568', width: 320, height: 568 },
  { name: 'phone-375x812', width: 375, height: 812 },
  { name: 'phone-390x844', width: 390, height: 844 },
  { name: 'phone-landscape-844x390', width: 844, height: 390 },
  { name: 'tablet-portrait-768x1024', width: 768, height: 1024 },
  { name: 'tablet-landscape-1024x768', width: 1024, height: 768 },
  { name: 'desktop-1440x900', width: 1440, height: 900 },
];

async function gradeFirstTile(page) {
  const tile = page.locator('.handrow button.tile').first();
  await expect(tile).toBeVisible({ timeout: 120_000 });
  await tile.click();
  await tile.click();
  await expect(page.locator('details.evwrap')).toBeVisible({ timeout: 120_000 });
}

const screens = [
  { id: 'home', hash: '', ready: '.home-title' },
  { id: 'trainer-setup', hash: '#/trainer', ready: '#tr-seed' },
  { id: 'quiz-awaiting', hash: '#/quiz', ready: '.felt' },
  { id: 'quiz-feedback', hash: '#/quiz', ready: 'details.evwrap', prepare: gradeFirstTile },
  { id: 'endgame-awaiting', hash: '#/endgame', ready: '.felt' },
  { id: 'endgame-feedback', hash: '#/endgame', ready: 'details.evwrap', prepare: gradeFirstTile },
  {
    id: 'lessons-detail', hash: '#/lessons', ready: '.lesson-answer',
    prepare: async (page) => {
      await page.locator('.lesson-card').first().click();
      await expect(page.locator('.evtable')).toBeVisible({ timeout: 30_000 });
    },
  },
  {
    id: 'analyze-results', hash: '#/analyze', ready: 'details.evwrap',
    prepare: async (page) => {
      await page.getByRole('button', { name: '分析 EV' }).click();
      await expect(page.locator('details.evwrap')).toBeVisible({ timeout: 120_000 });
    },
  },
  {
    id: 'score-results', hash: '#/score', ready: '.score-total',
    prepare: async (page) => {
      await page.getByRole('button', { name: '計算台數' }).click();
      await expect(page.locator('.score-total')).toBeVisible({ timeout: 30_000 });
    },
  },
];

test.describe.configure({ mode: 'serial' });
for (const screen of screens) {
  for (const viewport of viewports) {
    test(`${screen.id} — ${viewport.name}`, async ({ page }) => {
      await page.addInitScript(() => {
        localStorage.clear();
        sessionStorage.clear();
        Math.random = () => 0.000006; // all randomSeed() calls become seed 1
      });
      await page.setViewportSize(viewport);
      await page.goto(`${baseURL}/${screen.hash}`, { waitUntil: 'networkidle' });
      const isBlockedLandscape = viewport.width > viewport.height && viewport.height <= 560;
      if (!isBlockedLandscape && screen.prepare) await screen.prepare(page);
      await expect(page.locator(isBlockedLandscape ? '.rotate-hint' : screen.ready))
        .toBeVisible({ timeout: 120_000 });
      await page.screenshot({
        path: `docs/ui-baseline/before/${screen.id}/${viewport.name}.png`,
        fullPage: true,
        animations: 'disabled',
      });
    });
  }
}
```

Exact matrix: the nine named screen states above × all seven named viewports = **63 screenshots**. The 844×390 row intentionally records today’s rotate prompt as a before-state; it is evidence for the later landscape decision, not a test failure. The deterministic `Math.random` override is valid because the application’s current seed helper uses `Math.random` (`server/static/js/api.js:50-52`).

## 5. Phased work plan

Each phase is independently shippable. Do not start a later phase without preserving the preceding baseline and acceptance evidence.

| Phase | Relative size | Deliverable | Acceptance check |
| --- | --- | --- | --- |
| 0. Visual baseline | S | Add the dev-only Playwright harness and capture the 63-image before-set specified above. No production UI change. | All 63 paths exist under `docs/ui-baseline/before/`; the run exits 0; the landscape images visibly show the existing orientation prompt. |
| 1. Foundations and identity guardrails | M | Refactor CSS into named layout/scale variables; establish the four width ranges; widen the app/workspace only where the range allows; apply consistent panel, type, focus, and touch-target rules. Preserve all identity tokens listed in the audit. | At every viewport, the board remains square, tile faces stay bone/serif, the drawn tile and focus use gold, `本桌無花牌` remains visible, and no horizontal page overflow occurs outside intentionally scrollable text/code. Compare before/after screenshots side by side. |
| 2. Board, hand, and action layout | L | Implement responsive board-density rules, a desktop/tablet workspace, and the owner-selected landscape treatment. Keep existing renderer payloads and interaction semantics; this is layout/CSS first. | Portrait phone retains a complete actionable hand with accessible taps; tablet/desktop show a square board plus readable feedback rail; chosen/best/drawn/cut states remain distinguishable; the selected landscape behaviour passes the 844×390 capture. |
| 3. Ranked EV responsive presentation | M | Refactor the EV display into a shared data-to-view component that renders cards below 720 px and the current semantic table at/above 720 px; retain fold plan, uncertainty, and explanation. Apply it to quiz, trainer, and analysis because they all call the same details component. | For the same response, all eight values, their current decimal precision, the best/chosen state, the fold plan, and uncertainty are available in both presentations. Phone screenshots require no horizontal scroll to compare rank, net EV, CI, and self-draw probability. |
| 4. Non-table screens and polish | M | Bring home, lesson, analysis form, score form/result, loading, empty/error, and mode controls into the same refined hierarchy; preserve the existing no-flower/model-scope copy. | All nine baseline screen states have an intentional after-state at all seven viewports; forms and controls are readable without clipping; keyboard focus is visible in gold. |
| 5. Browser regression coverage | M | Keep Playwright as dev-only coverage: baseline recapture plus deterministic interaction smoke tests for route rendering, a quiz feedback path, analyzer results, and score results. Add screenshot review instructions, not pixel-perfect assertions until owners approve tolerances. | Chromium run exits 0; before/after matrix is reviewable; interaction tests demonstrate that responsive presentation did not change the scored data or make primary actions unreachable. |

No phase introduces a runtime dependency, a build step, a new game mode, flowers, accounts, timers, or multiplayer. The existing UI explicitly exposes the model’s self-draw/heuristic limitation, so that disclosure should be retained during polish (`server/static/js/feedback.js:122-135`; `server/static/js/main.js:124-130`).

## 6. Open decisions for the repository owner

1. **Visual-refresh depth:** (A) sharpen existing plum/bone/gold components through spacing, hierarchy, and material detail **(RECOMMENDED)**; (B) broader revisit of card, panel, and typography composition while retaining the same plum/bone/gold/tile-face system; (C) new visual language with only token remnants — largest novelty, but conflicts with the stated identity-preservation goal.
2. **Short-phone landscape:** (A) retain the current rotate prompt — lowest implementation and QA cost; (B) support a compact landscape workspace above 568 px wide and retain the prompt below that **(RECOMMENDED)** — medium layout/QA cost with materially better utility; (C) support every landscape phone width — most flexible, but likely compromises board/touch geometry.
3. **Narrow EV default:** (A) automatic ranked cards below 720 px and full table at/above it **(RECOMMENDED)** — best phone scanability while preserving every metric; (B) keep the horizontal table everywhere — least code but repeats the current usability problem; (C) add a user toggle — explicit control, but adds state and decision overhead to an already dense analysis screen.
4. **Baseline artefacts:** (A) commit `docs/ui-baseline/before/` and `after/` images for durable review **(RECOMMENDED)**; (B) store them only as CI/build artefacts — smaller repository, but makes future local visual comparison less accessible.
