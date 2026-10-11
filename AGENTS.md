# Repository agent rules

- Keep `catalog/datasets.toml` in the same commit as any data-file move; see
  `README.md` under the repository data-layout rules.
- Run `tests/test_claims.py` for user-visible copy. Its banned-claim list also
  applies to both READMEs, `docs/ui-plan.md`, and the named JavaScript modules.
- Do not run tests marked `slow` as part of routine checks. Use targeted tests
  while developing and `pytest -m "not slow"` for the fast suite.
- Commit messages use a lowercase scope prefix and end with a `Verification:`
  line containing the exact command and result actually observed.

## Public-release work

- Treat the application as a local prototype until release gates have evidence.
  See `docs/release-readiness-review.md` for the dated review and priorities;
  recheck those findings against the current commit rather than treating them as permanent facts.
- Preserve the model boundaries: bot-domain calibration, heuristic hidden-state
  assumptions, sampling uncertainty, and explicit fallback reporting. Do not
  present a small endgame reference corpus as validation of full-game human play.
- When changing an engine helper signature, search all callers, including slow
  tests and research scripts. Keep routine checks fast; before a release, inspect
  the slow CI result for the exact release SHA and run affected slow tests or the
  full slow workflow when needed. Report unrun checks explicitly.
- Do not widen statistical regression thresholds merely to make CI pass.
  Investigate implementation, corpus, seeds and budgets; document justified
  baseline changes with measured evidence and preserve independent checks.
- Trainer sessions currently contain live Python generators in process memory.
  Do not assume multiple workers/replicas or restarts preserve them, and do not
  propose Redis alone as a serialization fix. Any lifecycle change must cover
  capacity, expiry, lost responses, stale steps, and user-visible recovery.
- Public compute endpoints need bounded admission and request budgets. Verify
  rate/concurrency limits, queue overflow, request-size limits and worker-side
  deadlines under real simulation budgets; browser cancellation alone does not
  stop CPU work. Keep liveness responsive while expensive requests are running.
- API validation tests use reduced simulation budgets: they are not latency or
  capacity evidence. Record environment, cold/warm latency, concurrency, memory
  and failures separately when making performance claims.
- Changes to browser flows need browser-level verification of the affected
  journey, including failed requests and recovery. Existing layout checks are
  useful but do not replace a complete play/grade/resume flow.
- Release evidence must identify the commit, dependency versions, calibration
  identity, deployment topology, readiness checks and rollback procedure.
  Distinguish observed results from proposed acceptance criteria.
- Public-beta configuration and commands are in `docs/beta-operations.md`.
  Maintain engine budget checkpoints and never release admission while work is
  still running. Lifecycle/limit changes require `tests/test_server_limits.py`;
  trainer recovery changes also require the opt-in browser recovery suite.
  Keep unresolved model gates visible in `docs/p0-implementation.md`.
