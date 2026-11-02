# Portable add plan v1 conformance corpus

Shared fixtures that #3475 asks every frontend (CLI, GUI, web) to consume for
the portable add plan, `schema_version` 1 (`PLAN_SCHEMA` in
`scripts/lib/portable_add.py`). `tests/test_portable_add_conformance.py` runs
each case through the public CLI, `scripts/config-packages.py`. It replaces
only the container runner and the signed APT fetch, so no network or image is used.

Each directory is one case:

- `case.json`: `command` (`verify-transaction` or `plan`), `package` (the
  intent), and either `image_target`, `image` and `simulation` (the apt
  simulation's `returncode`/`stdout`/`stderr`), or `variants`/`flavors`/
  `platforms` plus `offline_source` (the error every signed-metadata fetch raises).
  An optional `xfail` field records a rule #3475 requires that the validator
  does not enforce today. Remove it once the rule is enforced.
- `plan.json`: the plan bytes given to `--plan`. These are exact bytes, and
  `plan_sha256` in expected output depends on them.
- `expected.json`: either the exact normalized JSON printed on success, or
  `{"rejected": "<stable substring of the ERROR line>"}`.

To add a case, create a new directory with these files. Write the expected
result by hand from the rule, not by copying current output. If the current
behaviour differs, add `xfail` with a `GAP:` reason. Changing the meaning of
an existing case requires a new schema version and a new corpus directory.

## Known gaps

`load_plan` rejects non-object plans, unknown top-level fields, unknown
target-record fields and target records missing `target`, `status` or
`index_availability`. Two cases remain `xfail` pending a design decision on
authenticating images against plan targets:

- `image-variant-mismatch`: any `@sha256` image is accepted for any target.
- `image-platform-mismatch`: the image platform is never checked against the target.
