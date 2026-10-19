# Desktop contract package-owner evidence

The desktop checker can record which installed packages own each selected file.
It uses files from executed contract checks. This opt-in evidence can help with
future policy review. It cannot authorize a removal, replace the desktop
contract, or prove that a package is optional.

## Scope

The collector supports GNOME and XFCE build checks with `apt` or `dnf`.
Normal GNOME/XFCE builds do not load this collector or write its report.
The collector rejects `--runtime`, other desktops and other managers.

Choose a new output file in a directory that exists:

```sh
TUNAOS_CONTRACT_OWNER_MANAGER=apt \
TUNAOS_CONTRACT_OWNER_EVIDENCE=/tmp/gnome-owners.json \
  bash build_scripts/checks/verify-desktop-experience.sh gnome
```

Run this only inside the image whose contract you intend to check.
The contract retains its existing build-time writes. The collector uses
read-only queries. It never installs or removes packages.
The collector rejects an output path that exists or contains a symlink.

A write failure fails the opt-in run. The hook removes temporary files on exit.
Each invocation needs a new output path, including pre-removal and post-removal
checks. The optional-package adapter does not need to enable this collector.

## Report fields

The JSON report contains:

- The desktop, native manager, and SHA-256 hashes of the checker, hook and
  collector. These identify code, not an image digest or a complete source
  receipt. Keep the report with the build's image and source evidence.
- The checker's exit code, completion flag and waiver count. The terminal
  status is `passed`, `failed`, `waived` or `incomplete`. A failed run can
  contain observations from checks that passed before the failure.
- Selected command paths and glob matches from successful checks.
  For an `any` requirement, the hook records only the first successful option.
- Unit files from the load paths that `systemd-analyze unit-paths` reports.
  The collector selects the first file in that order. If no file exists,
  the report states that gap.
- Selected paths and their symlink targets. A wrapper and its target can
  belong to different packages. The collector queries both paths.
- Owner name, full version and architecture. The collector retains identities for each DPKG architecture and owner. A package must have the
  `installed` state. Diversions, mismatched results and failed queries do not
  produce an owner.
- Explicit `unowned`, `query_failed` or `unresolved` path observations.
  A generated file can have no owner and still be required. The collector
  marks a directory as `unresolved` and does not inspect its contents.

`authorizes_removal` and `coverage.complete` are always false.
`observed_owner_packages` lists positive observations, even if another
observation or the contract failed. An absent package name never proves
that the package is safe to remove.

## Coverage limits

These helpers provide evidence for selected files:

- `require_command`
- `require_glob` and `require_any_glob`
- `require_unit` and `require_any_unit`
- `require_user_unit` and `require_any_user_unit`

The hook also records each call to the checker's `waive` helper.
Its waiver count comes from the checker. The collector does not audit
exemptions in special checks independently.
The report excludes native dependencies, unit execution, unit dependency
graphs and directory contents. It excludes GNOME schema and version checks,
codec behavior, dconf, Flatpak declarations, artwork and greeter configuration.
It also excludes skipped conditions and runtime, boot and installer behavior.

A glob proves that a path exists. It does not prove usable contents.
A unit file does not identify every resource that the unit uses.
The collector queries ownership after the contract runs. It does not lock
package transactions.

The report states these gaps. Future policy must account for them before
owner evidence can expand removals. The first production policy for optional
packages remains separate. It needs its own pinned source, native preflight,
exact package delta, and post-removal contract. This collector does not widen
that policy.

## Bounds and diagnosis

The event stream allows at most 1 MiB, 256 checks and 512 selected paths.
Each native query has a 15-second timeout. The report has a 60-second query
budget. Query failures and exhausted time remain explicit unknown evidence.

The collector labels a path `unowned` only for an exact no-owner diagnostic
from the native tool. Other nonzero results become `query_failed`.
Absent tools never produce an empty successful owner set.

| Symptom | Cause to check | Next step |
| --- | --- | --- |
| A passed contract has no owner for a unit | The unit list passed, but systemd did not resolve a file | Inspect the selected unit and its load paths in that image. Do not infer an optional package. |
| An existing command is `unowned` | The exact database path may differ after usr-merge, or the file may be generated | Inspect native ownership and the recorded resolved path. Do not guess another package name. |
| A DPKG path is `query_failed` | The query failed, returned a diversion, or did not match the exact path and installed package identity | Inspect the recorded diagnostic and image database before using the evidence. |
| A contract reports `waived` | A requirement failed and the check's existing exemption allowed it | Fix the unmet requirement before treating the desktop contract as passed. |

Tests in `tests/test_contract_package_owners.py` check query failures and exact
owner identities. They cover multiple owners, multiarch, ambiguous paths,
unresolved files and units, symlinks, waivers, output safety and shell events.
Fixtures exercise the real check helpers and EXIT trap without image writes.
Mocked results test the parser and its error paths. These tests do not prove
native image, boot or installation behavior.
