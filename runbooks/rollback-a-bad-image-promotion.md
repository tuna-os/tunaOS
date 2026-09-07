# Rollback a bad container image promotion

## Scope

`reusable-build-image.yml`'s `tag-image` (Promote) job is the only place the
bare `:<flavor>` tag is written (see the comment at the top of its "Pull
Image and Apply Tags" step). It only runs after `manifest`, `sign`,
`verify_desktop`, `verify_boot`, and `verify_asahi` all report
success-or-skipped, so a promoted image has passed every gate CI knows about.

That gate set cannot catch everything: a regression outside
`verify-desktop-experience.sh`'s coverage, a hardware-specific fault the boot
gate's QEMU profile doesn't reproduce, or a security issue found after
release. When one of those slips through, the bare tag — and its
`:<flavor>-<arch>`, `:<flavor>-<arch>-<date>`, and alias tags — is what every
new install and every `bootc upgrade`/`rpm-ostree upgrade` on an existing
host pulls next. There is no separate "stable" gate between promotion and
that exposure.

## Detection signals

- `bootc-lifecycle.yml`'s weekly sweep (or a manual dispatch of it) failing
  on a specific `variant:flavor` cell.
- `desktop-contract-sweep.yml` failing post-promotion.
- A user-filed issue describing breakage on a specific flavor/date.

## Why rollback needs a manual step

`MIGRATION.md`'s `sudo rpm-ostree rollback` / `bootc rollback` already
recovers a host that has *already deployed* the bad image — it swaps back to
the previous local deployment and needs no network. That protects hosts that
already updated. It does nothing for hosts that haven't updated yet: they
will still pull the bad bare tag until it is repointed. Containment is about
that second group.

## Containment: repoint the bare tag to the last-known-good digest

Every successful promotion writes a dated tag
(`<flavor>-<YYYYMMDD>` and `<flavor>-<arch>-<YYYYMMDD>`) alongside the bare
tag, in the same step, from the same source manifest. Nothing in this repo's
CI prunes GHCR image tags (`prune-r2.yml` only prunes R2-hosted ISOs and
screenshots), so those dated tags stay available as rollback anchors.

1. Find the last good dated tag for the affected `variant:flavor`. List
   available tags for the image:

   ```bash
   skopeo list-tags docker://ghcr.io/tuna-os/<variant> \
     | jq -r '.Tags[] | select(startswith("<flavor>-"))' | sort -r
   ```

   Cross-check the candidate date against the run history of
   `build-variant.yml` / `build-flavor.yml` for the last run that finished
   green before the bad promotion.

2. Repoint the bare tag (and any arch-specific / alias tags affected) to
   that digest:

   ```bash
   GOOD_TAG="<flavor>-<YYYYMMDD>"   # last known-good dated tag
   skopeo copy --all \
     "docker://ghcr.io/tuna-os/<variant>:${GOOD_TAG}" \
     "docker://ghcr.io/tuna-os/<variant>:<flavor>"

   # Repeat per affected arch tag, and per alias image name from
   # build-config.yml's `aliases:` field for this variant, e.g.:
   skopeo copy --all \
     "docker://ghcr.io/tuna-os/<variant>:${GOOD_TAG}" \
     "docker://ghcr.io/tuna-os/<alias-name>:<flavor>"
   ```

3. Verify the repoint landed on the intended digest:

   ```bash
   skopeo inspect --format '{{.Digest}}' docker://ghcr.io/tuna-os/<variant>:<flavor>
   skopeo inspect --format '{{.Digest}}' "docker://ghcr.io/tuna-os/<variant>:${GOOD_TAG}"
   # the two digests must match
   ```

4. File (or update) an issue naming the bad dated tag, the digest it was
   pulling, and the good tag it was repointed to, so a later promotion
   doesn't silently re-introduce the same digest.

## Recovery

Root-cause the regression before re-promoting. If the gap is something
`verify-desktop-experience.sh` or the boot gate should have caught, extend
that check first — otherwise the same class of bad image can reach the bare
tag again on the very next promotion. Only merge a fix and let a normal
`build-variant.yml` run re-promote once its boot gate and desktop
verification pass on the corrected image.
