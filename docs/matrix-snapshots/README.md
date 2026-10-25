# Retained matrix reconciliation (#3813)

This is a historical replay, not a new health measurement. Do not use its
October 23 evaluation date as evidence of a later run.

Merge `4912d39dcd47a110d035afb3dad4187d05936c9c` mixed the October 23 board
from parent `188f6c11` (refresh `94092878`) with the summary from parent
`76a68ca51f9eccb0202dff3e19c0004822251f73`. The board said 120 of 147; the
summary said 124 of 147. The per-cell evidence also included newer results.
Restoring the old pair would hide seven newer desktop failures.

`2026-10-23-reconciled.json` retains normalized source assertions selected by
the per-cell evidence at main `a6fcff42d2cf766bb30009e0d2ed0721516b3a88`.
Its source list identifies the 27 paginated job-list receipts and their hashes.
The original GitHub run is the number in each receipt filename. The two
baseline artifacts are identified by run, artifact ID, member and ZIP digest.
They preserve desktop failure/missing/error/lost and parity verdict distinctions.
No workflow was dispatched and no registry image was pulled for this repair.

The existing evaluator derives **120 of 147** from those retained assertions
at the explicit October 23 evaluation date, with the bound matrix and criteria.
Every retained per-cell verdict is preserved. Two untested build slots now
carry the failed Gate's source run/date: Hummingbird GNOME (`38660870261`)
and Wahoo Tuna (`38906627617`). Neither becomes a pass. Out-of-scope LUKS
and installer observations from the same recovered runs remain visible as
history; they do not enter current coverage counts.

## Known limits

- The original overlay registry tag inventory is absent. The overlay section
  is preserved verbatim from `94092878` and is labeled unverified historical
  data. No tags are invented from the headline count.
- The original per-axis full-sweep dates are absent. `last_full_sweep` is the
  empty string, meaning unknown. The old summary's `2026-09-01` is retained
  only as unverified context, not as a new full-sweep assertion.
- The input records selected historical assertions, not a newly enumerated
  workflow history. It makes no claim that no later runs exist.
- Configuration hashes bind this replay to its reviewed inputs. After a
  configuration change, `--inputs` replay refuses to run. A new replay needs a
  reviewed new input, not a hash edit. The committed pair stays valid: its
  recorded hashes are sealed into the snapshot identity, but
  `check-matrix-snapshot.py` does not compare them with the current checkout.
  The daily live refresh replaces this snapshot. `--check-structure` catches
  board-shape drift from a configuration change.

## Reproduce without network access

From the repository root, with the normal Python config dependencies:

```sh
python3 scripts/gen-matrix-status.py --inputs docs/matrix-snapshots/2026-10-23-reconciled.json
python3 scripts/check-matrix-snapshot.py
python3 scripts/gen-matrix-status.py --check --inputs docs/matrix-snapshots/2026-10-23-reconciled.json
```

The default generator still collects live evidence. The offline option reads
only the named input. It does not call GitHub or GHCR. The generated provenance
binds its retained-input hash and exact generated board block to one snapshot.
The Matrix Status workflow checks this identity and all axis headlines before
publication and on pull requests. A partial write or mixed merge must fail,
even when two snapshots have the same aggregate counts.

These digests detect a mixed merge or changed input; they are not source
authentication. The input is a reviewed historical reconciliation, not an
arbitrary user-supplied health claim. Job-list receipts were read through the
GitHub connector, paginated to their reported total, and compared with the
normalized assertions. Baseline ZIP digests were checked before extraction.
The loader rejects unmanifested source runs, future assertions, conflicting
evaluation dates and build results without per-cell source metadata. Malformed
input fails with one `ValueError` that names the problem. Configuration
identity uses parsed values, so comment-only edits do not change it. Exact
original configuration byte hashes remain in the receipt for audit.
