# Retained matrix reconciliation (#3813)

This is a historical replay, not a new health measurement. Do not use its
October 23 evaluation date as evidence of a later run.

Merge `4912d39dcd47a110d035afb3dad4187d05936c9c` mixed the October 23 board
from parent `188f6c11` (refresh `94092878`) with the summary from parent
`76a68ca51f9eccb0202dff3e19c0004822251f73`. The board said 120 of 147; the
summary said 124 of 147. The per-cell evidence also included newer results.
A restore of the old pair would hide seven newer desktop failures.

`2026-10-23-reconciled.json` keeps the normalized source assertions that the
per-cell evidence selected at main `a6fcff42d2cf766bb30009e0d2ed0721516b3a88`.
Its source list identifies the 27 paginated job-list receipts and their hashes.
The original GitHub run is the number in each receipt filename. The record for
each of the two baseline artifacts has the run, artifact ID, member and ZIP
digest. They preserve desktop failure/missing/error/lost and parity verdict
distinctions. This repair dispatched no workflow and pulled no registry image.

The existing evaluator derives **120 of 147** from those retained assertions
at the explicit October 23 evaluation date, with the bound matrix and criteria.
The replay keeps every retained per-cell verdict. Two untested build slots now
carry the failed Gate's source run/date: Hummingbird GNOME (`38660870261`)
and Wahoo Tuna (`38906627617`). Neither becomes a pass. Out-of-scope LUKS
and installer observations from the same recovered runs remain visible as
history; they do not enter current coverage counts.

## Known limits

- The inventory of the registry tags for the original overlay is absent. The overlay
  section keeps the text of `94092878` verbatim and carries a label that says
  the data has no verification and is historical. The headline count does not invent
  any tags.
- The original full-sweep dates for each axis are absent. `last_full_sweep` is
  the empty string, meaning unknown. The old summary's `2026-09-01` stays only
  as unverified context, not as a new full-sweep assertion.
- The input has historical assertions that a reviewer selected. It is not a
  new enumeration of the workflow history. It makes no claim that no later runs
  exist.
- Configuration hashes bind this replay to its reviewed inputs. After a
  configuration change, `--inputs` replay refuses to run. A new replay needs a
  reviewed new input, not a hash edit. The committed pair stays valid. The
  snapshot identity seals its recorded hashes, and `check-matrix-snapshot.py`
  does not compare them with the current checkout.
  The daily live refresh replaces this snapshot. `--check-structure` catches
  board-shape drift from a configuration change.

## Reproduce without network access

From the repository root, with the usual Python dependencies for the configuration:

```sh
python3 scripts/gen-matrix-status.py --inputs docs/matrix-snapshots/2026-10-23-reconciled.json
python3 scripts/check-matrix-snapshot.py
python3 scripts/gen-matrix-status.py --check --inputs docs/matrix-snapshots/2026-10-23-reconciled.json
```

The default generator still collects live evidence. The offline option reads
only the named input. It does not call GitHub or GHCR. The generated provenance
binds the hash of its retained input and the exact block of the generated board
to one snapshot. The Matrix Status workflow runs a check of this identity and all
axis headlines before publication and on pull requests. A partial write or
mixed merge must fail, even when two snapshots have the same aggregate counts.

These digests detect a mixed merge or changed input; they are not source
authentication. The input is a reviewed historical reconciliation, not a health
claim that a user supplied without review. The GitHub connector read the
job-list receipts, paginated them to their reported total, and compared them
with the normalized assertions. The replay checked the ZIP digests of the
baselines before extraction.

The loader rejects source runs without a manifest, future assertions,
evaluation dates that conflict, and build results without per-cell source
metadata. Malformed input fails with one `ValueError` that names the problem.
Configuration identity uses parsed values, so edits to comments only do not
change it. The receipt keeps the exact hashes of the original configuration
bytes for audit.
