# Fix Report

## Summary

- Confirmed: 17; Partially correct: 1 (BUG-018). All 18 findings classified below.
- Fixed: 17 code/documentation findings, including the five inherited fixes in 868078d. BUG-006 is resolved by an explicit unsupported-operation guard, not a new merge algorithm.
- Rejected findings: 0. The partially incorrect BUG-018 reproduction is qualified below.
- Remaining: BUG-016 requires the owner. Browser behavioral coverage, owner wording approval and remote CI enforcement are explicitly limited below.
- Slow suite (run by the reviewer after the delegated round): 18 passed, 1 failed. The failure is **pre-existing** — present at the baseline `94451d1` before any fix here, bisected to `ba7fb20` (DEV-180 part 1). Not caused by this batch; see "Independent verification".

Reviewed on branch `dev-205-python-floor`, starting at `868078d2ac581536a177958d5ca1e82c6552ab45`, whose sole parent above baseline is `94451d13b6cbc141d64d3da021b8cc993edf16fe`. Initial `git diff --stat` independently matched **16 files, +269/-49**, plus untracked AGENTS.md and AUDIT.md. The filename-to-bug mapping in the brief was checked against all diff hunks. tests/test_claims.py additionally covered BUG-011/018. No source change was discarded wholesale.

The round-1 commit was inspected, and its tests are included in this session's verification. Its historical test timing is not claimed as newly measured. No issue, remote, PR, branch checkout, other worktree, dependency or tool configuration was changed.

## Implemented

### BUG-001

- Status: Confirmed; fixed locally. Evidence: `server/static/js/feedback.js:12`; `taimahjong/ev.py:88`.
- Files changed: server/static/js/feedback.js; taimahjong/ev.py; tests/test_claims.py.
- Root cause: The emitted defense principle was absent from the UI lookup.
- Fix: Retained round-1 translation and shared backend key tuple, guarded by cross-language key-set equality.
- Tests added: test_frontend_fold_principles_cover_backend_contract.
- Tests executed: full fast suite F2 below; see targeted coverage T2 where applicable.
- Linear: DEV-117; recommendations only below.
- GitHub: no issue/PR created or updated; no new GitHub mapping.
- Risks: Display only; no engine-value change.

### BUG-002

- Status: Confirmed; fixed locally. Evidence: `taimahjong/quiz.py:353`; `taimahjong/ev.py:235`.
- Files changed: taimahjong/quiz.py; tests/test_quiz.py.
- Root cause: Quiz used ceil for a post-draw seat whose next draw is four tiles away.
- Fix: Retained delegation to remaining_draws; strengthened the inherited test to assert wall // 4 independently, preventing both implementations drifting together. Committed before BUG-007.
- Tests added: test_post_draw_quiz_horizon_matches_shared_actor_turn_order (walls 0..16).
- Tests executed: full fast suite F2 below; T1 also covers this engine path.
- Linear: None; recommendations only below.
- GitHub: no issue/PR created or updated; no new GitHub mapping.
- Risks: Seeded quiz/endgame/trainer EVs and possibly rankings change. The 12/16 wall-state discrepancy is measured below; it is not evidence that 75% of generated positions change.

### BUG-003

- Status: Confirmed; fixed locally. Evidence: `scripts/gen_tile_faces.py:34`; `tests/test_claims.py:84`.
- Files changed: scripts/gen_tile_faces.py; tests/test_claims.py.
- Root cause: Legacy glyph extraction overwrote the runtime module with incompatible exports.
- Fix: Retained round-1 output retargeting to scripts/tile-face-glyphs.js and export/import compatibility guard. No existing data file moved.
- Tests added: test_tile_face_module_exports_cover_imports_and_no_generator_overwrites_it.
- Tests executed: full fast suite F2 below; see targeted coverage T2 where applicable.
- Linear: None; recommendations only below.
- GitHub: no issue/PR created or updated; no new GitHub mapping.
- Risks: Legacy output destination changes intentionally; the optional font generator itself was not executed.

### BUG-004

- Status: Confirmed; fixed locally. Evidence: `taimahjong/ev.py:1202`; `server/static/js/feedback.js:76`; `server/static/js/main.js:125`.
- Files changed: server/static/js/feedback.js; server/static/js/main.js; tests/test_claims.py.
- Root cause: p_win includes own ron as well as self-draw, but labels named only self-draw.
- Fix: Retained round-1 P(和牌) wording and copy regression guard.
- Tests added: test_p_win_is_not_labeled_as_self_draw.
- Tests executed: full fast suite F2 below; see targeted coverage T2 where applicable.
- Linear: DEV-117; recommendations only below.
- GitHub: no issue/PR created or updated; no new GitHub mapping.
- Risks: Final wording is the owner's call; the payload field remains p_win.

### BUG-005

- Status: Confirmed; fixed locally. Evidence: `.github/workflows/tests.yml:5`.
- Files changed: .github/workflows/tests.yml.
- Root cause: Push CI covered main but omitted feat integration tips.
- Fix: Retained round-1 feat/** push coverage. Confirmed the baseline and final local workflow diff; external historical CI/PR claims were not re-queried.
- Tests added: None; workflow trigger inspected directly.
- Tests executed: full fast suite F2 below; see targeted coverage T2 where applicable. Workflow behavior was inspected, not exercised by GitHub Actions.
- Linear: DEV-205; DEV-149 / DEV-151 (related); recommendations only below.
- GitHub: no issue/PR created or updated; PR #4/#5 are historical audit context only.
- Risks: Future CI execution and branch-protection enforcement remain outside local verification.

### BUG-006

- Status: Confirmed; fixed locally. Evidence: `taimahjong/moments.py:37`; `taimahjong/moments.py:141`.
- Files changed: taimahjong/moments.py; tests/test_uncertainty.py.
- Root cause: Inherited merge constructed plain moments and silently discarded clustering.
- Fix: Retained explicit refusal for clustered receivers; corrected the uncovered plain.merge(clustered) direction to refuse too. Full cluster-aware merging needs sufficient per-cluster totals and is not implemented.
- Tests added: test_clustered_merge_refuses_to_silently_assume_independence.
- Tests executed: full fast suite F2 below; see targeted coverage T2 where applicable.
- Linear: DEV-182; recommendations only below.
- GitHub: no issue/PR created or updated; no new GitHub mapping.
- Risks: Unsupported clustered merges now raise NotImplementedError, intentionally replacing incorrect intervals. Plain merges retain their behavior.

### BUG-007

- Status: Confirmed; fixed locally. Evidence: `taimahjong/ev.py:279`; `server/api.py:678`; `taimahjong/selfplay.py:280`.
- Files changed: taimahjong/ev.py; server/api.py; tests/test_ev.py; tests/test_api.py.
- Root cause: Derived live-wall horizon omitted kong backfill.
- Fix: Retained optional total-table kongs argument and API field. Corrected the inherited literal subtraction to use selfplay.KONG_DEAD_WALL_BACKFILL_TILES via a local import (selfplay already imports ev). Explicit wall counts are authoritative.
- Tests added: test_derived_live_wall_retires_one_tile_per_declared_kong; test_explicit_live_wall_does_not_double_count_kongs; test_ev_rank_auto_turns_account_for_declared_kongs.
- Tests executed: full fast suite F2 below; T1 also covers this engine path.
- Linear: DEV-181; recommendations only below.
- GitHub: no issue/PR created or updated; no new GitHub mapping.
- Risks: Clients must supply kongs when deriving the horizon; default zero preserves old callers. This remains an approximation of holdings, not a reconstruction of the entire table. Explicit wall_remaining avoids that approximation.

### BUG-008

- Status: Confirmed; fixed locally. Evidence: `README.md:6`; `README.en.md:6`; `tests/test_claims.py:59`.
- Files changed: README.md; README.en.md; tests/test_claims.py.
- Root cause: The Python floor and pinned test-count prose drifted from project configuration.
- Fix: Retained round-1 Python 3.11 badges/CI prose and removed brittle hardcoded test counts.
- Tests added: test_readme_python_badges_match_declared_floor.
- Tests executed: full fast suite F2 below; see targeted coverage T2 where applicable.
- Linear: DEV-205; recommendations only below.
- GitHub: no issue/PR created or updated; PR #4/#5 are historical audit context only.
- Risks: No tooling or dependency added; README timings remain illustrative, not sandbox measurements.

### BUG-009

- Status: Confirmed; fixed locally. Evidence: `server/api.py:434`; `server/api.py:510`; `tests/test_api.py:246`.
- Files changed: server/api.py; tests/test_api.py.
- Root cause: Insertion-order eviction ignored recent access; store mutations lacked one shared lock.
- Fix: Retained locked insert/eviction and move-to-end on lookup. Regression touches A after B exists, then inserts C at capacity two.
- Tests added: test_trainer_session_eviction_uses_recent_access.
- Tests executed: full fast suite F2 below; see targeted coverage T2 where applicable.
- Linear: None; recommendations only below.
- GitHub: no issue/PR created or updated; no new GitHub mapping.
- Risks: LRU cannot preserve A indefinitely without continued access: AUDIT's suggested create-64-after-one-touch test would still correctly evict A. No concurrency stress test added.

### BUG-010

- Status: Confirmed; fixed locally. Evidence: `server/api.py:564`; `server/api.py:643`; `tests/test_api.py:259`.
- Files changed: server/api.py; tests/test_api.py.
- Root cause: Score/feedback mutated before generator advancement, and send errors bypassed engine error mapping.
- Fix: Retained local computation and commit-after-send. Corrected the misleading recoverable fake-generator test: a real Python generator closes on exception. Mark failed sessions unusable, preserve score/current/feedback/step, map ValueError/RuntimeError to 422, and return 404 on subsequent GET/act so clients can start a new hand.
- Tests added: test_trainer_send_failure_does_not_commit_score_or_feedback (real failing generator, retry and GET rejection).
- Tests executed: full fast suite F2 below; see targeted coverage T2 where applicable.
- Linear: None; recommendations only below.
- GitHub: no issue/PR created or updated; no new GitHub mapping.
- Risks: An engine failure ends that in-memory session; it is not rolled back or resurrected. The initial failure is still reported; unexpected exception types remain server errors. Normal validation is performed before send.

### BUG-011

- Status: Confirmed; fixed locally. Evidence: `server/static/js/stats.js:23`; `tests/test_claims.py:102`.
- Files changed: server/static/js/stats.js; tests/test_claims.py.
- Root cause: setItem could throw into grading's request catch and suppress feedback.
- Fix: Retained try/catch around persistence. record already lives outside rendering in quiz/trainer, so no render-path relocation was needed.
- Tests added: test_stats_persistence_failure_is_contained (Python source guard only).
- Tests executed: full fast suite F2 below; see targeted coverage T2 where applicable.
- Linear: None; recommendations only below.
- GitHub: no issue/PR created or updated; no new GitHub mapping.
- Risks: Browser behavior is UNVERIFIED in-session. Source matching is not an executable storage-failure regression; see proposed JS coverage below.

### BUG-012

- Status: Confirmed; fixed locally. Evidence: `taimahjong/analysis.py:64`; `tests/test_calibration_wiring.py:185`.
- Files changed: taimahjong/analysis.py; tests/test_calibration_wiring.py.
- Root cause: Missing tables fell back, but parse/binning failures escaped loading.
- Fix: Retained warning plus heuristic fallback; expanded coverage to mismatched binning, non-object JSON and null counts. Parse the exact bytes hashed instead of reopening the file, and handle structural TypeError/AttributeError as malformed data. Generator/Calibration direct callers still fail loudly.
- Tests added: test_malformed_table_warns_and_uses_heuristic_fallback; test_malformed_table_api_reports_fallback.
- Tests executed: full fast suite F2 below; see targeted coverage T2 where applicable.
- Linear: None; recommendations only below.
- GitHub: no issue/PR created or updated; no new GitHub mapping.
- Risks: This is load-time parse/structure failure handling, not a comprehensive semantic schema validator. Unrelated filesystem permission errors are not suppressed.

### BUG-013

- Status: Confirmed; fixed locally. Evidence: `taimahjong/calibration.py:18`; `taimahjong/calibration.py:217`; `taimahjong/calibration.py:242`; `taimahjong/calibration.py:337`.
- Files changed: taimahjong/calibration.py; scripts/generate_calibration.py; tests/test_selfplay.py.
- Root cause: Generation defaults retained the retired seven-bin tail, separate from shipped metadata.
- Fix: Retained canonical split-tail defaults and explicit legacy read defaults. Corrected inherited incomplete wiring: table_document must write matching metadata or new split counts read back as legacy; merge and report must also respect legacy metadata-free tables. Added round-trip, merge and report coverage.
- Tests added: test_default_danger_binning_matches_the_committed_table; test_new_default_table_round_trips_split_tail; test_metadata_free_legacy_table_still_loads_and_merges.
- Tests executed: full fast suite F2 below; see targeted coverage T2 where applicable.
- Linear: DEV-119; DEV-122 (adjacent); recommendations only below.
- GitHub: no issue/PR created or updated; no new GitHub mapping.
- Risks: New tables use eight bins; legacy seven-bin documents still load/merge/report. Custom bucket layouts now require explicit binning metadata. No calibration data file was regenerated or moved.

### BUG-014

- Status: Confirmed; fixed locally. Evidence: `server/api.py:250`; `tests/test_uncertainty.py:84`; `tests/test_uncertainty.py:105`.
- Files changed: server/api.py; tests/test_uncertainty.py.
- Root cause: API duplicated both effect threshold and wording ladder.
- Fix: Retained shared EV_EFFECT_SIZE_MIN and moments.payload(threshold), with the post-selection invariant documented/tested.
- Tests added: test_boundary_top_gap_whose_paired_ci_crosses_zero_is_uncertain; test_all_paired_delta_paths_remain_marked_post_selection.
- Tests executed: full fast suite F2 below; see targeted coverage T2 where applicable.
- Linear: None; recommendations only below.
- GitHub: no issue/PR created or updated; no new GitHub mapping.
- Risks: No intended behavior change while the threshold remains the same.

### BUG-015

- Status: Confirmed; fixed locally. Evidence: `server/api.py:654`; `tests/test_api.py:439`.
- Files changed: server/api.py; tests/test_api.py.
- Root cause: Nested opponent model inherited permissive BaseModel instead of strict ApiRequest.
- Fix: Retained ApiRequest inheritance; inherited regression verifies nested Pydantic validation rejects unknown fields.
- Tests added: test_ev_rank_rejects_unknown_nested_opponent_fields.
- Tests executed: full fast suite F2 below; see targeted coverage T2 where applicable.
- Linear: None; recommendations only below.
- GitHub: no issue/PR created or updated; no new GitHub mapping.
- Risks: Previously ignored nested keys now cause validation errors (HTTP 422 through FastAPI), intentionally rejecting typo-dependent clients.

### BUG-017

- Status: Confirmed; fixed locally. Evidence: `AGENTS.md:1`; `README.md:81`; `tests/test_claims.py:21`.
- Files changed: AGENTS.md.
- Root cause: Repository-specific agent rules were not versioned.
- Fix: Retained the inherited concise rule file covering catalog, claims, slow-test discipline and verification commit footers.
- Tests added: None; file contents reviewed against repository rules.
- Tests executed: full fast suite F2 below; see targeted coverage T2 where applicable.
- Linear: None; recommendations only below.
- GitHub: no issue/PR created or updated; no new GitHub mapping.
- Risks: Empty .agents/ and .codex/ directories are sandbox read-only mounts and were left intact; they contain no tracked source.

### BUG-018

- Status: Partially correct; fixed locally. Evidence: `server/static/js/quiz.js:19`; `server/static/js/quiz.js:44`; `server/static/js/quiz.js:69`; `server/static/js/quiz.js:132`; `server/static/js/quiz.js:137`.
- Files changed: server/static/js/quiz.js; tests/test_claims.py.
- Root cause: Async handlers lacked request identity. The audit's specific next-then-retry click recipe overlooks synchronous removal of controls during generating. Scheme changes during grading still expose overlapping request paths.
- Fix: Retained monotonic identity shared by generate and grade, checking success and failure before updating state or recording statistics.
- Tests added: test_quiz_async_responses_are_guarded_by_request_identity (Python source guard only).
- Tests executed: full fast suite F2 below; see targeted coverage T2 where applicable.
- Linear: None; recommendations only below.
- GitHub: no issue/PR created or updated; no new GitHub mapping.
- Risks: Out-of-order browser promise behavior is UNVERIFIED in-session; structural guard covers both handlers and catches only. No JS runner installed.

## Rejected / Not Reproducible

No complete finding was rejected as Incorrect or Not reproducible.

- BUG-018's exact click reproduction is only partially correct. Reason: generate renders synchronously, and the generating branch returns before controls are rendered. Evidence: `server/static/js/quiz.js:44`, `:132`; the scheme toggle remains in the grading branch at `:137`, so request identity is still a justified fix.
- BUG-009's proposed regression sequence is not an LRU specification. Reason: one touch followed by a full capacity of newer sessions makes that session least recent again. Evidence: the access-order implementation at `server/api.py:510` and the bounded A/B/touch-A/C regression at `tests/test_api.py:246`.
- The audit's four ruled-out suspicions were not reopened. They are not additional findings or counted rejections.

## Remaining issues

- **BUG-016 — Confirmed; deferred to owner.** Evidence: local `git config --get remote.origin.url` returned `git@github.com:YuHsunWang/gto_mahjong.git`; `tests/test_claims.py:21` and `:38` explain/enforce the claim restriction. Either rename the repository or explicitly grandfather the name. Neither decision was made here; no remote was contacted. Linear mapping: DEV-138, recommend leaving Backlog pending owner decision.
- BUG-004 final Chinese wording remains the owner's call; this round preserves the already committed P(和牌).
- BUG-011/018 have Python source guards, not executable browser regressions. Proposed follow-up: owner-approved JS testing using native Node test facilities or a browser harness, covering blocked setItem and reversed success/error response ordering. No JS runner/dependency was added.
- BUG-005 local trigger coverage is fixed; historical red-check merging, branch protection, and future Actions execution are UNVERIFIED here. No remote queries or changes were performed.
- The two empty agent directories remain because this environment mounts them read-only; AGENTS.md is the substantive versioned fix.
- Slow suite: skipped inside the delegated round by instruction, then **run by the reviewer after the round** — see "Independent verification" under Verification. Result: 18 of 19 passed. Four of the five horizon-sensitive tests named here passed. The fifth, `tests/test_calibration_wiring.py::test_extreme_calibration_moves_stateless_quiz_and_trainer_risk_together`, fails — but it **already failed before this batch** (at 94451d1) and was bisected to `ba7fb20` (DEV-180 part 1). It is a pre-existing regression, not caused by these fixes; it is proposed below as a new Linear issue.
- No large corpus rerun or calibration regeneration was attempted. The fixed-wall reference path explicitly supplies its own horizon (`taimahjong/reference_ev.py:910`), and the strata probe supplies `case.turns` (`scripts/hidden_world_strata_probe.py:251`). `docs/ev-reference-report.md:9` is dated historical evidence; `docs/batch-a-simulation-report.md:3` documents a separate capped-draw experiment; `docs/hidden-world-strata.md:25` records explicit turns=8. Their existing numbers are not claimed as remeasured. `docs/equilibrium-plan.md` was read for scope, not rewritten. Fresh quiz-derived benchmark numbers require a separate measurement run.

## Verification

**F2 full fast suite: `382 passed, 19 deselected in 200.08s (0:03:20)`, exit 0, outside the sandbox.**

This is 43 more passing tests than the caller-provided baseline of 339; that baseline run was not repeated. No failures occurred.

Exact full-suite wrapper used twice (first sandbox, second outside it), with output files only in /tmp:

```bash
set -o pipefail
PYTHONDONTWRITEBYTECODE=1 timeout --signal=TERM --kill-after=10s 900s python3 -m pytest -m "not slow" -p no:cacheprovider --durations=10 2>&1 | tee /tmp/mahjong-round3-fast-outside.log | tail -40
```

F1 used `/tmp/mahjong-round3-fast.log`. It collected 401 tests / 19 deselected / 382 selected, then stalled entering the first TestClient fixture. It was interrupted (exit 130), not passed. The first API-inclusive targeted run was likewise interrupted (exit 130), with no result claimed. A minimal empty FastAPI app entered TestClient outside the sandbox (exit 0) but timed out inside (exit 124 after 10 seconds), isolating an infrastructure restriction independently of repository code. Automatic review allowed the outside-sandbox verification; no tests were weakened to address this.

Minimal diagnostic actually executed in both environments:

```bash
timeout --kill-after=2s 10s python3 -u - <<'PYTESTCLIENT'
from fastapi import FastAPI
from fastapi.testclient import TestClient
app = FastAPI()
print('before TestClient context')
with TestClient(app):
    print('TestClient context entered')
PYTESTCLIENT
```

- T1: `rtk proxy python3 -m pytest -q tests/test_ev.py tests/test_quiz.py` → **71 passed, 3 deselected in 38.72s**, exit 0.
- T2: `rtk proxy python3 -m pytest -q tests/test_selfplay.py tests/test_uncertainty.py tests/test_claims.py tests/test_calibration_wiring.py -k 'not malformed_table_api_reports_fallback'` → **52 passed, 4 deselected in 53.13s**, exit 0. This was a targeted non-TestClient run during sandbox diagnosis; the excluded new API fallback test is included in F2.
- `python3 --version` → **Python 3.14.4**.
- `git diff --check` → exit 0 at review checkpoints; final post-commit checks recorded below.
- `pyproject.toml` read directly: only `[project]`, its optional dependency table, and `[tool.pytest.ini_options]`; no formatter/linter/type-checker configuration. No such tool was added or run; the stale ignored .ruff_cache is not configuration.

Horizon measurement actually executed (24-trial diagnostic, not a new production baseline):

```bash
PYTHONDONTWRITEBYTECODE=1 python3 - <<'PYHORIZON'
from math import ceil
from taimahjong.ev import remaining_draws, evaluate_discard
from taimahjong.tiles import parse_tiles
hand = parse_tiles('123m123p123s11122233z')
print('BUG-002 disagreement wall 1..16:', sum(ceil(w/4) != w//4 for w in range(1,17)))
print('BUG-007 horizons k=0..4:', [remaining_draws(hand, kongs=k) for k in range(5)])
for turns in (1, 0):
    entry = evaluate_discard(hand, 0, (), (0,)*34, turns=turns, sims=24, seed=7)
    print('wall=3 turns=', turns, 'net_ev=', entry.net_ev, 'p_win=', entry.p_win)
PYHORIZON
```

Result (exit 0): 12 differing wall states; k=0..4 gives `[14, 14, 13, 13, 13]`; hypothetical wall=3 old turns=1 gives net_ev `3.2916666666666665`, p_win `0.6666666666666666`; corrected turns=0 gives both `0.0`. This compares explicit horizons on a fixed hand, not the physical hidden-wall distribution of a generated quiz. BUG-002 is committed before BUG-007; inherited uncommitted changes had no historical ordering to verify.

Final review/checkpoint:

- Re-read the complete baseline-to-HEAD diff in bounded file groups using `rtk proxy git diff 94451d13b6cbc141d64d3da021b8cc993edf16fe..HEAD -- <paths>`; also re-read AGENTS.md and the whole report. No source edits followed F2.
- `rtk proxy git diff --check 94451d13b6cbc141d64d3da021b8cc993edf16fe..HEAD` returned exit 0.
- Removed only untracked Python bytecode, pytest and stale ruff cache directories after checking they contain no tracked files. Logs/temporary review scripts stayed under /tmp.
- Acceptance audit: required report sections and fields present; all 18 findings classified with evidence; 17 implemented blocks; BUG-016 deferred; F2 result quoted; source commits grouped by BUG IDs; BUG-002 precedes BUG-007; no push/remote changes. Final status check is required after the documentation commit.

Round-3 source commit subjects:

```text
bfa98be quiz: unify post-draw horizon (BUG-002)
c4effb9 ev: account for kong backfill in derived horizons (BUG-007)
a394aaa uncertainty: reject lossy merges and share ranking wording (BUG-006, BUG-014)
2d3a393 calibration: handle malformed tables and preserve binning identity (BUG-012, BUG-013)
c904789 api: protect trainer state and validate opponents (BUG-009, BUG-010, BUG-015)
72edf07 ui: contain storage errors and ignore stale responses (BUG-011, BUG-018)
```

### Independent verification (reviewer, after the delegated round)

The delegated round's own summary (`final.md`) was lost: the reviewer stopped
the round with SIGTERM to save credits after it had committed everything, so the
claims above were re-checked independently rather than trusted. All runs below
are outside the Codex sandbox, on Python 3.14.4, against `84b0911`.

| Run | Command | Result |
|---|---|---|
| Fast suite | `python3 -m pytest -m "not slow" -p no:cacheprovider --durations=10` | **382 passed, 19 deselected in 245.96s, exit 0** — matches F2 |
| Slow suite | `python3 -m pytest -m slow -p no:cacheprovider --durations=19` | **1 failed, 18 passed, 382 deselected in 2188.77s, exit 1** |

Timings are longer than F2 because another session's test run shared the CPU.

**The one slow failure is pre-existing, not caused by this batch.**

```
tests/test_calibration_wiring.py:109
assert high_quiz["grade"]["chosen"]["risk_ev"] > low_quiz["grade"]["chosen"]["risk_ev"]
E       assert 4.022259140844048 > 4.128835005499143
```

Raising the calibrated deal-in probability 200x lowered the quiz path's
`risk_ev` for the chosen discard, where the test expects it to rise.

Evidence that it predates the batch — the same single test, each tree exported
with `git archive` so HEAD and the working tree were never moved:

| Tree | Result |
|---|---|
| `origin/main` `628048e` | **1 passed** in 24.21s |
| baseline `94451d1` (before any fix in this report) | **1 failed** — `assert 4.022554106799213 > 4.244216356944337` |
| `84b0911` (this batch) | **1 failed** — `assert 4.022259140844048 > 4.128835005499143` |

Bisect over the 30 first-parent commits `origin/main..94451d1`
(read-only; `git archive` per probe, not `git bisect`):

```
[14] 6020879 PASS
[21] b6e7952 FAIL
[17] 869eb26 PASS
[19] 999d76c PASS   <- last good
[20] ba7fb20 FAIL   <- first bad
```

**First bad commit: `ba7fb20` "ev: reserve a 7-dun dead wall, not the with-flower
8 dun (DEV-180 part 1)."** It shrank the dead wall from 16 to 14 tiles, so the
live wall — and every derived horizon — grew by two tiles. BUG-002's horizon
change in this batch only moved the low-calibration value (4.244 -> 4.129); the
inversion exists either way.

Why nobody saw it: the test is marked `slow`, and CI runs the slow job only on
`main` (`.github/workflows/tests.yml`). `ba7fb20` never reached `main`, so the
nightly job has been green while testing code 30 commits older than the branch.
That is exactly GitHub discrepancy 3 in AUDIT.md.

Root cause: **UNVERIFIED.** A hypothesis, labelled as such: the test's own
comment says the *stateless* half was made exhaustive because "a 200x swing in
deal-in probability legitimately returns different top-k sets", so comparing one
discard across calibrations "depends on the sets happening to overlap". The
*quiz* half — the assertion that fails — still uses the `EV_TOP_K = 5` screened
ranking, so it may carry the same brittleness, exposed by the wall change. Two
readings remain open and need a separate investigation: (a) a brittle test whose
quiz half needs the same treatment as its stateless half, or (b) a real
monotonicity violation in the calibrated risk model. They call for different
fixes, so this report does not pick one.

Neighbor-path check that turned out clean: the reviewer suspected
`trainer_get` of skipping the BUG-010 failed-session guard. It does not —
`_session_payload` calls `_check_session` on its first line (`server/api.py:496`),
so every endpoint that returns session state is guarded in one place, and
`test_trainer_send_failure_does_not_commit_score_or_feedback` asserts the GET
404. Re-run on its own: 1 passed in 1.26s. No change was needed.

## Proposed Linear updates

Recommendations only; statuses below are from AUDIT.md, not live service verification.

| Findings | Existing issue(s) | Recommended update |
|---|---|---|
| BUG-001, BUG-004 | DEV-117 (Backlog) | Move to Review for the label fixes and key-set guard; keep browser coverage and final wording as explicit follow-ups. |
| BUG-005, BUG-008 | DEV-205 (Done) | Attach README-floor and integration-trigger evidence; keep Done for Python-floor work after review. Do not claim branch-protection work complete. |
| BUG-005 | DEV-149 / DEV-151 (Done) | Leave numerical-estimator tickets Done; note CI-trigger follow-up without reopening their unrelated implementation. |
| BUG-006 | DEV-182 (Backlog) | Move guard fix to Review; if full clustered merging is still required, retain that as a separate backlog scope. |
| BUG-007 | DEV-181 (Backlog) | Move to Review with explicit-kongs API contract, horizon tests and measurement. |
| BUG-013 | DEV-119 (Done), DEV-122 (Backlog) | Attach default/legacy compatibility evidence to DEV-119; keep DEV-122 Backlog because its calibrated-RON approximation is unrelated and unchanged. |
| BUG-016 | DEV-138 (Backlog) | Leave Backlog, awaiting owner rename/grandfather decision. |

For confirmed findings without an issue, draft the following (do not file):

- **BUG-002: Unify post-draw EV horizons**
  - Problem: Quiz used ceil for a post-draw seat whose next draw is four tiles away.
  - Reproduction: Construct a post-draw DecisionSnapshot with wall_remaining=3; compare _position_from(...).draws_remaining with remaining_draws(..., wall_remaining=3). Both must be zero.
  - Expected: Unify post-draw EV horizons.
  - Root cause: Quiz used ceil for a post-draw seat whose next draw is four tiles away.
  - Implementation: Retained delegation to remaining_draws; strengthened the inherited test to assert wall // 4 independently, preventing both implementations drifting together. Committed before BUG-007.
  - Test coverage: test_post_draw_quiz_horizon_matches_shared_actor_turn_order (walls 0..16). Recommend **Review**, with limitations above.

- **BUG-003: Keep legacy tile generator away from runtime exports**
  - Problem: Legacy glyph extraction overwrote the runtime module with incompatible exports.
  - Reproduction: Inspect OUTPUT_PATH in the legacy glyph generator and compare its exported names with the names imported by tiles.js; on the baseline the incompatible output targets the runtime module.
  - Expected: Keep legacy tile generator away from runtime exports.
  - Root cause: Legacy glyph extraction overwrote the runtime module with incompatible exports.
  - Implementation: Retained round-1 output retargeting to scripts/tile-face-glyphs.js and export/import compatibility guard. No existing data file moved.
  - Test coverage: test_tile_face_module_exports_cover_imports_and_no_generator_overwrites_it. Recommend **Review**, with limitations above.

- **BUG-009: Evict trainer sessions by recent use**
  - Problem: Insertion-order eviction ignored recent access; store mutations lacked one shared lock.
  - Reproduction: At capacity two, store A then B, retrieve A, then store C. B must be evicted and A retained.
  - Expected: Evict trainer sessions by recent use.
  - Root cause: Insertion-order eviction ignored recent access; store mutations lacked one shared lock.
  - Implementation: Retained locked insert/eviction and move-to-end on lookup. Regression touches A after B exists, then inserts C at capacity two.
  - Test coverage: test_trainer_session_eviction_uses_recent_access. Recommend **Review**, with limitations above.

- **BUG-010: Avoid partial trainer score commits on engine failure**
  - Problem: Score/feedback mutated before generator advancement, and send errors bypassed engine error mapping.
  - Reproduction: Attach a generator that yields a discard decision then raises RuntimeError on send; submit that step twice and GET the session. Score stays unchanged and the failed session is rejected.
  - Expected: Avoid partial trainer score commits on engine failure.
  - Root cause: Score/feedback mutated before generator advancement, and send errors bypassed engine error mapping.
  - Implementation: Retained local computation and commit-after-send. Corrected the misleading recoverable fake-generator test: a real Python generator closes on exception. Mark failed sessions unusable, preserve score/current/feedback/step, map ValueError/RuntimeError to 422, and return 404 on subsequent GET/act so clients can start a new hand.
  - Test coverage: test_trainer_send_failure_does_not_commit_score_or_feedback (real failing generator, retry and GET rejection). Recommend **Review**, with limitations above.

- **BUG-011: Preserve feedback when local stats cannot be saved**
  - Problem: setItem could throw into grading's request catch and suppress feedback.
  - Reproduction: Proposed browser reproduction (not executed here): block localStorage.setItem, then grade one quiz/trainer discard. Feedback should still render.
  - Expected: Preserve feedback when local stats cannot be saved.
  - Root cause: setItem could throw into grading's request catch and suppress feedback.
  - Implementation: Retained try/catch around persistence. record already lives outside rendering in quiz/trainer, so no render-path relocation was needed.
  - Test coverage: test_stats_persistence_failure_is_contained (Python source guard only). Recommend **Review**, with limitations above.

- **BUG-012: Fall back on malformed calibration input**
  - Problem: Missing tables fell back, but parse/binning failures escaped loading.
  - Reproduction: Load a temporary JSON file with two danger edges and one bucket via CalibrationProvider; the provider must warn and return heuristic-fallback.
  - Expected: Fall back on malformed calibration input.
  - Root cause: Missing tables fell back, but parse/binning failures escaped loading.
  - Implementation: Retained warning plus heuristic fallback; expanded coverage to mismatched binning, non-object JSON and null counts. Parse the exact bytes hashed instead of reopening the file, and handle structural TypeError/AttributeError as malformed data. Generator/Calibration direct callers still fail loudly.
  - Test coverage: test_malformed_table_warns_and_uses_heuristic_fallback; test_malformed_table_api_reports_fallback. Recommend **Review**, with limitations above.

- **BUG-014: Share EV effect threshold and wording**
  - Problem: API duplicated both effect threshold and wording ladder.
  - Reproduction: Compare _top_gap_payload(entries).effect_threshold with quiz.EV_EFFECT_SIZE_MIN and inspect that payload wording is delegated, including missing-interval paths.
  - Expected: Share EV effect threshold and wording.
  - Root cause: API duplicated both effect threshold and wording ladder.
  - Implementation: Retained shared EV_EFFECT_SIZE_MIN and moments.payload(threshold), with the post-selection invariant documented/tested.
  - Test coverage: test_boundary_top_gap_whose_paired_ci_crosses_zero_is_uncertain; test_all_paired_delta_paths_remain_marked_post_selection. Recommend **Review**, with limitations above.

- **BUG-015: Reject unknown nested opponent fields**
  - Problem: Nested opponent model inherited permissive BaseModel instead of strict ApiRequest.
  - Reproduction: Construct EvRankRequest with opponents=[{"river":"9m","unexpected":true}] (JSON form). Nested validation must reject the unknown key.
  - Expected: Reject unknown nested opponent fields.
  - Root cause: Nested opponent model inherited permissive BaseModel instead of strict ApiRequest.
  - Implementation: Retained ApiRequest inheritance; inherited regression verifies nested Pydantic validation rejects unknown fields.
  - Test coverage: test_ev_rank_rejects_unknown_nested_opponent_fields. Recommend **Review**, with limitations above.

- **BUG-017: Version repository agent rules**
  - Problem: Repository-specific agent rules were not versioned.
  - Reproduction: Inspect git ls-tree 94451d1 AGENTS.md: the baseline has no repository rule file; the final tree must contain the four project rules.
  - Expected: Version repository agent rules.
  - Root cause: Repository-specific agent rules were not versioned.
  - Implementation: Retained the inherited concise rule file covering catalog, claims, slow-test discipline and verification commit footers.
  - Test coverage: None; file contents reviewed against repository rules. Recommend **Review**, with limitations above.

- **BUG-018: Ignore stale quiz responses**
  - Problem: Async handlers lacked request identity. The audit's specific next-then-retry click recipe overlooks synchronous removal of controls during generating. Scheme changes during grading still expose overlapping request paths.
  - Reproduction: Resolve a grade request after a newer scheme-triggered generate request.
  - Expected: Ignore stale quiz responses.
  - Root cause: Async handlers lacked request identity. The audit's specific next-then-retry click recipe overlooks synchronous removal of controls during generating. Scheme changes during grading still expose overlapping request paths.
  - Implementation: Retained monotonic identity shared by generate and grade, checking success and failure before updating state or recording statistics.
  - Test coverage: test_quiz_async_responses_are_guarded_by_request_identity (Python source guard only). Recommend **Review**, with limitations above.

- **NEW (pre-existing, not one of the 18): calibration-wiring monotonicity test red since `ba7fb20`**
  - Title: `test_extreme_calibration_moves_stateless_quiz_and_trainer_risk_together` has failed since the 7-dun dead wall (DEV-180 part 1)
  - Problem: Under a 200x higher calibrated deal-in probability, the quiz path reports a *lower* `risk_ev` for the chosen discard (4.022 vs 4.129 at `84b0911`). The slow-marked test that guards this direction has been red on the integration line since `ba7fb20`, unseen because CI runs slow tests on `main` only.
  - Reproduction: `python3 -m pytest -p no:cacheprovider -m slow "tests/test_calibration_wiring.py::test_extreme_calibration_moves_stateless_quiz_and_trainer_risk_together"` — fails at `94451d1` and `84b0911`, passes at `origin/main` `628048e`. Bisect: last good `999d76c`, first bad `ba7fb20`.
  - Expected: raising calibrated deal-in risk raises the quiz path's `risk_ev`, as it already does for the stateless path.
  - Root cause: UNVERIFIED. Either the quiz half of the test compares one discard across two differently-screened top-k sets — the brittleness the test's own comment already removed from its stateless half — or the calibrated risk model is genuinely non-monotone in this position.
  - Implementation: first decide which of the two it is. If brittle: make the quiz half compare over a well-defined candidate set, the way the stateless half does. If real: fix the model, not the test.
  - Test coverage: the existing test is the regression test once the cause is settled. Separately, AUDIT.md BUG-005's CI trigger fix means slow tests on `feat/**` would still not run on push — only the fast job does — so this class of failure stays invisible until the slow job also runs off `main`.
  - Linear mapping: related to **DEV-180** (Done). Recommend a **new issue** rather than reopening DEV-180: DEV-180's own acceptance (the flowerless 7-dun rule) holds; what broke is a downstream test it never ran.

## Pull request description

### Summary

Align quiz horizons with post-discard turn order, account for kong backfill in derived horizons, and finish the audit's API/calibration/frontend consistency fixes. Preserve legacy calibration readers while making new tables use the canonical split tail.

### Bugs fixed

BUG-001 through BUG-015, BUG-017 and BUG-018 (17 findings; BUG-018's original click recipe is only partially correct). BUG-016 remains an owner decision. Five fixes were already present in 868078d; this round reviewed them and completed the inherited working tree.

### Root causes

Duplicated horizon/wording rules, stale frontend contracts and generator output targets, clustered-statistic type loss, partial session updates, permissive nested validation, and calibration metadata/default drift.

### Testing

Fast suite: **382 passed, 19 deselected**, exit 0 — measured twice, once by the delegated round (200.08s) and once independently by the reviewer (245.96s). T1: 71 passed / 3 deselected. T2: 52 passed / 4 deselected. First full attempt stalled in sandbox TestClient setup; the isolated empty-app reproduction passed outside the sandbox.

Slow suite (reviewer, after the round): **18 passed, 1 failed**. The failure, `tests/test_calibration_wiring.py::test_extreme_calibration_moves_stateless_quiz_and_trainer_risk_together`, is **pre-existing** — it also fails at the baseline `94451d1` before any fix here, passes at `origin/main`, and bisects to `ba7fb20` (DEV-180 part 1). Not introduced by this PR; proposed as a separate Linear issue in the report.

Python source guards cover the JS changes; browser behavior was not executed.

### Linear

Recommend reviews/evidence updates as listed above. No Linear or GitHub object changed; no push or PR created.

### Risks

Quiz-derived EVs and rankings can change; kongs must be supplied for derived horizons. Failed trainer generators now require a new hand instead of retrying a dead session. Clustered merge refuses unsupported combinations. Unknown opponent fields now reject requests. New calibration tables use eight bins; legacy tables retain seven-bin semantics. Final P(和牌) wording and repository naming remain owner decisions. Remote CI and browser checks are not locally certified. **Merging this PR does not turn the slow suite green**: the pre-existing `test_calibration_wiring` failure from `ba7fb20` stays red until its own issue is resolved, and it will surface on `main` the first night after this line of work lands there.
