# Agent Guidelines for TunaOS

> The authoritative agent guide lives at [`docs/AGENT_GUIDE.md`](docs/AGENT_GUIDE.md). Read that file for complete architecture, setup, and troubleshooting.

## Quick Reference

```bash
just fix && just check   # format + validate (mandatory before every commit)
just test                # bats + pytest (same as CI)
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
- `Containerfile` — main (base + all DE stages)
- `Containerfile.overlay` — HWE/nvidia parameterized layer
- `Containerfile.ubuntu` — Ubuntu/Debian bootcification

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
package set is available. **Measure the index rather than inferring it** —
repodata is public and small:

```bash
curl -s https://repo.tunaos.org/hummingbird/20251124-x86_64/repodata/repomd.xml
# then fetch the primary.xml.gz it names and grep for <name>PKG</name>
```

## Adding a Desktop

Write `manifests/desktops/<name>.yaml`. No shell script needed. See existing manifests for the format.

## PR quality contract

Five rules, each one written because a real agent PR broke it and the break
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

Evidence style, for anything you write into the repo (comments, docs,
commit messages): state the constraint and the measured run/log that proves
it, not the narrative of how you found it. Every load-bearing comment in
`build_scripts/` follows this shape — match it.

## Agent Skills

### Issue tracker
GitHub Issues for `tuna-os/tunaos`, operated via `gh` CLI.

### Triage labels
`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`.
