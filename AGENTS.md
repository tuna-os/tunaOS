# Agent Guidelines for TunaOS

> The authoritative agent guide lives at [`docs/AGENT_GUIDE.md`](docs/AGENT_GUIDE.md). Read that file for complete architecture, setup, and troubleshooting.

## Quick Reference

```bash
just fix && just check   # format + validate (mandatory before every commit)
just test                # bats + pytest (same as CI)
just ci                  # the whole PR gate locally: check + CI contract + test
just build yellowfin gnome  # build a single flavor
just --list              # show all available commands
```

## Architecture (July 2026)

The build system is **manifest-driven**:

```
manifests/desktops/*.yaml  →  install-desktop.sh  →  image
```

Key scripts:
- `scripts/resolve-flavor.sh` — flavor → build params (tested: 18 bats cases)
- `scripts/resolve-image.sh` — consolidated image ref lookups
- `scripts/build-image-inner.sh` — the build engine (env-var driven)
- `build_scripts/desktop/install-desktop.sh` — generic DE installer
- `build_scripts/lib.sh` — shared library (OS detection, pkg abstraction)
- `build_scripts/README.md` — naming scheme (dirs = code path, numbers = phase order)

Containerfiles:
- `Containerfile.el10` — RPM-family base + desktop stages
- `Containerfile.overlay` — HWE/nvidia parameterized layer
- `Containerfile.ubuntu` — Ubuntu bootcification
- `Containerfile.debian` — Debian bootcification
- `Containerfile.arch`, `.gentoo`, `.opensuse` — other base families

Build pipeline: [`docs/PIPELINE.md`](docs/PIPELINE.md)

### Know your base before reasoning about its packages

Variants do not all behave like the distro their version strings suggest.
The one that has burned the most time:

**hummingbird is NOT Fedora 43 and NOT EL10.** It is a rolling,
security-hardened fork tracking **Fedora Rawhide** (Red Hat's Project
Hummingbird, zero-CVE), on the ARK kernel, and it **ships no desktop
environment by design**. Its `.fc43` dist tags are Rawhide's numbering, not
evidence of Fedora 43 — a trap that has produced confidently wrong diagnoses
more than once, including attributing its empty desktop to a package loss in a
repository it does not even read.

Read [`docs/HUMMINGBIRD.md`](docs/HUMMINGBIRD.md) before filing a packaging
issue, blaming a build failure on a missing package, or assuming a Fedora
package set is available. Since 2026-09-02 `hummingbird:gnome` takes the GNOME
stack from `projectbluefin/utah-packages` (digest-pinned OCI repo, see
`image-versions.yaml`), and only the rest from `repo.tunaos.org/hummingbird`. **Measure the index rather than inferring it** —
repodata is public and small:

```bash
curl -s https://repo.tunaos.org/hummingbird/20251124-x86_64/repodata/repomd.xml
# then fetch the primary.xml.gz it names and grep for <name>PKG</name>
```

## Adding a Desktop

Write `manifests/desktops/<name>.yaml`. No shell script needed. See existing manifests for the format.

## PR quality contract

Six rules, each one written because a real agent PR broke it and the break
was measured. A PR that violates one of these gets closed, not reviewed.

1. **Run what you claim to fix, and paste the result.** A PR titled
   "restore green main" must contain the passing test output for the tests
   that were red. #1828 fixed some occurrences of an escaping bug, missed
   others, never ran the test suite it claimed to restore — the suite was
   still red with the patch applied, and the PR was closed as superseded.
2. **Verify the external claim in the PR body.** A one-line transport or
   pin change still needs its one line of evidence (the curl, the resolved
   URL, the closing run link). #1852 was a correct https switch that a
   reviewer had to re-derive from scratch because the body carried no
   verification.
3. **Derive status, never transcribe it.** Any table of current state
   (what's published, what passes, what's listed where) must be emitted by
   a script the repo runs on a schedule, or it is stale the day it merges.
   This is the repo's core convention: `MATRIX-STATUS.md`, the README
   matrix, and `matrix-provenance.json` are all generated. #1814 hand-copied
   a 40-row live-data table into a committed doc and had to end with
   "re-check the sources when a cell looks stale" — that sentence is the
   anti-pattern naming itself.
4. **Check main and open PRs before diagnosing or fixing.** This repo
   merges several PRs a day; the bug you measured yesterday may be fixed,
   moved, or being fixed. #1725's recommendation had already landed via
   another PR by the time it was filed; #1828 raced a fix that was already
   further along. `git log --oneline -20` and a PR-list search cost a
   minute; a stale PR costs a review cycle.
5. **Rebase before opening.** A PR based days behind main is reviewed
   against a repo that no longer exists. If the base moved under you while
   the PR was open, rebase and re-run rule 1 — the merge queue tests the
   merge result, and "it passed on my old base" is not evidence.
6. **Leave the docs better than you found them, in the same PR.** Every PR
   that diagnoses something writes what it learned down where the next
   person will hit it — a row in `docs/ci-troubleshooting.md` for anything
   that cost you a debugging cycle, and a line here when the lesson
   generalises past one bug. The row states the SYMPTOM someone would
   search for, the measured CAUSE, and the FIX; a row that only says what
   changed is a changelog entry, not a troubleshooting entry. Doing this
   later means not doing it: the detail that makes a row useful is the
   command output you had in front of you at the time, and it is gone by
   the next session.

Evidence style, for anything you write into the repo (comments, docs,
commit messages): state the constraint and the measured run/log that proves
it, not the narrative of how you found it. Every load-bearing comment in
`build_scripts/` follows this shape — match it.

Two further conventions, adopted from Hive (#2250):

- **An incident is fixed when a test proves it cannot silently recur.** A
  fix for a bug that shipped an unusable or wrongly-promoted image lands
  with a regression test in `tests/regressions/test_issue_<N>_*.py`
  (see that directory's README). "Fixed the script" without the test is
  half a PR.
- **A gate that is declared is a gate that runs.** If you move, rename, or
  add a job that asserts a green criterion, update its `gates` block in
  `.github/green-criteria.yml`; `tests/test_ci_contract.py` fails when the
  contract and the workflows disagree, and `just test-contract` runs it
  locally.

Six more, each measured while fixing the live-ISO and install path
(rows 33-40 of `docs/ci-troubleshooting.md` carry the evidence):

- **A permanently-red check is a dead gate, not a known issue.** A check
  that always says the same thing cannot report a regression. Three
  assertions in `build_scripts/checks/e2e-runtime-checks.sh` were red on
  every run, on every flavor, for reasons unrelated to what they claimed to
  test: `graphical.target is active` asserted from inside that target's own
  startup transaction, the unit-graph gate failed on upstream units we do
  not ship plus a man-page check on an image that strips man pages, and the
  SSH host-key assertion fired on images that deliberately ship sshd
  disabled. Each had been passed over as background noise for months. When
  you see a failure that "always fails", that is the bug.
- **Being invoked is not being reached.** A guard placed after an early
  `exit 0` runs on nothing. `40-services.sh` has three package-manager
  paths and the first two end in `exit 0`; a login-banner guard added at
  the end of the file therefore ran on dnf images ONLY — silently never on
  Arch, which is the variant the bug was measured on. A test asserted all
  six Containerfiles *invoke* the script, which was true and not
  sufficient. Assert the line number precedes the first `exit`, or assert
  the effect in a built image.
- **Verify a fix in the built artifact, not in the source tree.** The guard
  above was present in the script, committed, reviewed and merged, and
  absent from every image. `just build` then `podman run --rm <image>` to
  check the thing actually happened costs one command and is the only
  evidence that counts.
- **A test that fails only on developer machines is not automatically
  environment noise.** Ten `test_lib.bats` OS-detection cases failed
  locally and passed in CI. The cause was a real defect: `lib.sh` assigned
  `jq`'s `%_dbpath`-style lookup straight into `BASE_IMAGE`, so an
  `image-info.json` that exists without a `base-image` key set it to the
  empty string and destroyed the caller's value. CI never saw it because
  the file only exists on ublue-derived hosts. Dismissing those failures
  three times cost more than reading one of them would have.
- **Guard a path before you destroy it.** `readlink -f ""` does not fail —
  it returns `$PWD`. `rawhide_rpmdb_probe` resolved an empty `%_dbpath`
  that way and ran `cp -a "$PWD" ...` then `rm -rf "$PWD"`, with the delete
  NOT conditional on the copy succeeding. On a nearly full disk the copy
  failed, the delete did not, and a full `bats` run destroyed a checkout of
  this repository. Refuse empty and non-absolute paths before resolving
  them, refuse `/` and `$PWD` after, and never `rm -rf` on the strength of
  a `cp` you did not check.
- **A detection default is a silent fallback.** `customize-live.sh` defaults
  `DESKTOP=gnome`, so a Pantheon image matched no branch, was treated as
  GNOME, and received GDM autologin — into an image whose only display
  manager is LightDM. `liveuser` existed; nothing logged it in; the ISO
  booted to a black screen. An unrecognised input did not fail loudly, it
  became the default, and every downstream assumption followed from the
  wrong answer. When a default exists, test the unrecognised case
  explicitly.

## Agent Skills

### Issue tracker
GitHub Issues for `tuna-os/tunaos`, operated via `gh` CLI.

### Triage labels
`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`.
