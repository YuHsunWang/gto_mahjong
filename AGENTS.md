# Repository agent rules

- Keep `catalog/datasets.toml` in the same commit as any data-file move; see
  `README.md` under the repository data-layout rules.
- Run `tests/test_claims.py` for user-visible copy. Its banned-claim list also
  applies to both READMEs, `docs/ui-plan.md`, and the named JavaScript modules.
- Do not run tests marked `slow` as part of routine checks. Use targeted tests
  while developing and `pytest -m "not slow"` for the fast suite.
- Commit messages use a lowercase scope prefix and end with a `Verification:`
  line containing the exact command and result actually observed.
