# Git history rewrite runbook

**Status:** proposed; no history has been rewritten

**Tracks:** [#2290](https://github.com/tuna-os/tunaos/issues/2290)

This runbook turns the large-blob inventory into a repeatable, auditable
rewrite procedure. A rewrite changes commit and tag IDs, invalidates open pull
request bases, and requires existing contributors to re-clone. It must be run
by a maintainer with permission to coordinate a freeze and temporarily change
branch protection; it is not routine repository maintenance.

## Measure the same thing everywhere

`scripts/audit-git-blobs.py` reports each unique reachable blob once. The
threshold is strictly greater than 5 MiB by default.

```bash
# What a normal clone of the default branch inherits
python3 scripts/audit-git-blobs.py HEAD

# Forensics across every ref available in an existing clone
python3 scripts/audit-git-blobs.py --all --format json >large-blobs.json

# Fail a policy job if a branch introduces an oversized blob anywhere in its
# new history. Use a range: HEAD alone also reports inherited, approved blobs.
git fetch origin main
python3 scripts/audit-git-blobs.py --fail-if-found origin/main..HEAD
```

Do not use an old working clone for the final inventory: its fork remotes and
locally retained refs change what `--all` means. Make a fresh mirror and record
its object database size before doing anything else:

```bash
git clone --mirror https://github.com/tuna-os/tunaos.git tunaos-before.git
git -C tunaos-before.git count-objects -vH
(cd tunaos-before.git && python3 /path/to/audit-git-blobs.py --all \
  --format json) >tunaos-before.json
```

GitHub pull-request refs can retain objects even after every branch and tag is
rewritten. Report these separately from the refs maintainers can update:

```bash
cd tunaos-before.git
mapfile -t PUBLISHED_REFS < <(
  git for-each-ref --format='%(refname)' refs/heads refs/tags
)
python3 /path/to/audit-git-blobs.py "${PUBLISHED_REFS[@]}"
python3 /path/to/audit-git-blobs.py --all
```

The first result is the rewrite target. The second is a forensic upper bound,
not a promise about immediate server-side garbage collection.

## TunaOS decision record

The 2026-09-02 mirror scan in #2290 found 16 blobs totaling 244.94 MiB:

| Paths | Blobs | Size | Disposition |
|---|---:|---:|---|
| `prototype/iso-builder/app/public/initramfs-sailfin-tbox.img` | 1 | 68.69 MiB | remove; generated initramfs |
| `prototype/iso-builder/app/public/tbox.wasm`, `prototype/iso-builder/app/tbox.wasm` | 9 | 109.77 MiB | remove; compiled output now owned by `iso-builder` |
| `system_files/usr/share/backgrounds/bluefin/12-bluefin-{day,night}.{png,jxl}` | 6 | 66.48 MiB | policy gate; retired but deliberate artwork |

The first two rows are the unambiguous rewrite set (178.46 MiB). Do not add
the wallpaper paths unless maintainers explicitly decide that their historical
source value is lower than the additional reclaim. Generate the object-level
list with the audit script rather than copying IDs from this dated summary.

## Rewrite window

### 1. Prepare and announce

1. Assign one rewrite owner and a second maintainer to verify the result.
2. Resolve the path policy for every repository. Keep runtime media and
   deliberately vendored source unless its owner approves removal.
3. Drain or close open pull requests. Record any commit that must be recreated.
4. Announce the UTC freeze and require a fresh clone after the all-clear.
5. Pause bots and scheduled writers. Disable automatic merges.
6. Export branch protection/ruleset settings and identify signed release tags.
   Rewriting a signed tag invalidates its signature; issue a replacement tag
   only under the release policy.
7. Make two fresh mirrors. Mark one read-only and retain `*-before.json` plus
   `git count-objects -vH` output as the rollback evidence.

Do not start while an active branch, tag, submodule pointer, deployment, or
release consumer is unaccounted for. Repositories that pin another affected
repository must be updated after that dependency is rewritten.

### 2. Rehearse offline

Use `git-filter-repo` from the distribution package or a version-pinned tool.
The TunaOS generated-artifact rehearsal is:

```bash
cp -a tunaos-before.git tunaos-rehearsal.git
cd tunaos-rehearsal.git
git filter-repo --force --invert-paths \
  --path prototype/iso-builder/app/public/initramfs-sailfin-tbox.img \
  --path prototype/iso-builder/app/public/tbox.wasm \
  --path prototype/iso-builder/app/tbox.wasm
```

`git filter-repo` writes commit and ref maps; retain them with the maintenance
record. Before publishing, the second maintainer must verify:

```bash
# Removed paths must not occur in any rewritten published ref.
git log --all --name-only --format= -- \
  prototype/iso-builder/app/public/initramfs-sailfin-tbox.img \
  prototype/iso-builder/app/public/tbox.wasm \
  prototype/iso-builder/app/tbox.wasm

python3 /path/to/audit-git-blobs.py --all

git fsck --full
git count-objects -vH
```

Also check out the default branch, run the repository's normal test suite, and
compare all expected branch and tag names with the backup. A smaller pack file
alone is not proof of a correct rewrite.

### 3. Publish or roll back

1. Reconfirm the writer freeze and backup readability.
2. Temporarily allow the rewrite owner to force-update the approved branches
   and tags. Delete stale branches instead of preserving their old objects.
3. Push the exact reviewed ref set from the rehearsal mirror. Avoid a blind
   `--mirror` push: it includes provider-managed pull-request refs and can
   delete refs that were not part of the approved plan.
4. Fetch a brand-new mirror from GitHub and repeat ref, `fsck`, checkout, and
   test verification against that server-fetched copy. Run the path and blob
   audits against its published branch/tag ref list; audit `--all` separately
   because provider-managed pull refs may retain the pre-rewrite objects.
5. If any required ref or content is wrong, keep the freeze in place and
   restore the reviewed refs from the read-only mirror. Otherwise restore
   rulesets and bots, then announce the new commit IDs and re-clone command.
6. Update downstream submodule pins and automation that stores commit IDs.
   Re-open work by recreating branches on the new history, not by merging an
   old local branch.

Git hosting garbage collection is asynchronous. Acceptance is that the
published refs no longer reach the removed objects and a fresh ordinary clone
is correct; the hosting UI or storage total may lag.

## Contributor recovery

The supported recovery is a fresh clone:

```bash
mv tunaos tunaos.pre-rewrite
git clone https://github.com/tuna-os/tunaos.git tunaos
```

Copy uncommitted files selectively. Do not pull, merge, or push an old branch
into the rewritten repository: doing so reconnects the removed history. A
maintainer can help recreate a small change by applying its patch to a branch
created from the new default branch.

## Org sequencing

Run one repository at a time: `corral`, `tacklebox`, `iso-builder`, and
`bluefin-cli` are the low-ambiguity pilots; then `tromso` and `xfce-linux`;
TunaOS and `tunaos-packages` come last because they have the widest blast
radius and packaging policy questions. For `bootc-installer`, retain the
runtime installer video and remove only approved generated objects. Each
repository gets its own before/after reports, freeze, ref map, verification,
and all-clear; never use one org-wide force-push window.
