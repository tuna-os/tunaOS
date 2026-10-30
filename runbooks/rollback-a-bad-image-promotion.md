# Rollback a bad container image promotion

## Scope

Each flavor has two rings ([RFC 018](../docs/rfc/rfc018-testing-stable-rings.md)):

- `:<flavor>-testing`: `reusable-build-image.yml`'s `tag-image` (Promote) job
  writes it, with the dated tags `<flavor>-<YYYYMMDD>` and
  `<flavor>-<arch>-<YYYYMMDD>`. Promote runs only after `manifest`, `sign`,
  `verify_desktop`, `verify_boot` and `verify_asahi` all report success or
  skipped.
- `:<flavor>` (stable, the default): after the soak and the promotion gates,
  `promote-stable.yml` moves the stable tags to a dated tag. The stable tags
  are the bare tag, the `:<flavor>-<arch>` tags and the alias tags. Promote
  writes the stable tags only for a new flavor that has no bare tag yet.

The gates cannot find all problems. Some examples:

- a regression that `verify-desktop-experience.sh` does not check
- a hardware fault that the QEMU boot gate does not show
- a security issue found after the release

A bad image gets to `:testing` users first. If nobody finds the problem
during the soak, it gets to `:stable` users also.

## Detection signals

- A failed job for a `variant:flavor` cell in the weekly `bootc-lifecycle.yml`
  run. This also holds the next promotion of that cell.
- A `desktop-contract-sweep.yml` failure after the promotion.
- An issue from a user about a specific flavor or date.

## Contain a bad `:testing` image

Before the bad image gets to `:stable`:

1. Open an issue with the `release-blocker` label. Put the cell in the title,
   for example `albacore:gnome: boot loop on 20261027`. `promote-stable.yml`
   holds that cell until you close the issue.
2. Users on `:testing` who updated run `sudo bootc rollback` (or
   `sudo rpm-ostree rollback`) and reboot. This returns to the previous local
   deployment and needs no network.
3. Merge a fix. The next build that passes the gates replaces the
   `:testing` image.

## Contain a bad `:stable` image

`sudo bootc rollback` recovers a host that deployed the bad image. Hosts that
did not update yet pull the bad bare tag until it moves. To protect them,
repoint the stable tags of the cell to the last good dated tag.

The dated tags are the rollback anchors. The CI of this repository does not
prune the image tags in GHCR. (`prune-r2.yml` prunes only ISOs and
screenshots on R2.)

1. Find the last good dated tag of the cell. List the tags of the image:

   ```bash
   skopeo list-tags docker://ghcr.io/tuna-os/<variant> \
     | jq -r '.Tags[] | select(test("^<flavor>-[0-9]{8}$"))' | sort -r
   ```

   The summary of the previous `promote-stable.yml` runs shows which dated
   tag each promotion copied.

2. Run `promote-stable.yml` manually with these inputs:

   - `mode`: `rollback`
   - `cell`: the cell, for example `albacore:gnome`
   - `rollback_to`: the dated tag, for example `gnome-20261024`
   - `reason`: why, with the issue number. The run fails if the reason is
     empty.

   Run it first with `mode` `dry-run` to see the tags that the rollback
   writes. The `Write stable tags` job copies the dated tag by digest to the
   bare tag, to each `<flavor>-<arch>` tag (from `<flavor>-<arch>-<YYYYMMDD>`)
   and to each alias image of the variant (`aliases:` in `build-config.yml`).
   Then it reads every written tag and fails if a digest is not the source
   digest.

3. Make sure that the run passes. Its summary has the cell, the old and new
   digests, and the tags written. A `SKIPPED` cell means that the bare tag
   moved after the job read it. Run the workflow again.

4. Open or update a `release-blocker` issue for the cell. Until you close
   it, the daily promotion does not move the cell forward to a bad image.

### Manual fallback

If the workflow cannot run, copy the tags by hand with a token that can write
packages:

```bash
GOOD_TAG="<flavor>-<YYYYMMDD>"   # last good dated tag
skopeo copy --all --preserve-digests \
  "docker://ghcr.io/tuna-os/<variant>:${GOOD_TAG}" \
  "docker://ghcr.io/tuna-os/<variant>:<flavor>"
# Do the same for each <flavor>-<arch> tag (source <flavor>-<arch>-<YYYYMMDD>)
# and for each alias image: ghcr.io/tuna-os/<alias-name>:<flavor>.

skopeo inspect --format '{{.Digest}}' docker://ghcr.io/tuna-os/<variant>:<flavor>
skopeo inspect --format '{{.Digest}}' "docker://ghcr.io/tuna-os/<variant>:${GOOD_TAG}"
# the two digests must be the same
```

## Recovery

Find the root cause before the next promotion. If
`verify-desktop-experience.sh` or the boot gate must find this problem,
extend that check first. Then merge the fix. The fixed image goes to
`:testing` when it passes the gates.

Close the `release-blocker` issue only after the fixed image has soaked. The
promotion selects the newest soaked `:testing` image. If you close the issue
before the fixed image soaks, the bad image can be that image. The summary of
a `dry-run` of `promote-stable.yml` for the cell shows the candidate tag.
