# Infrastructure release gates

The [org roadmap](../ROADMAP.md) includes prerequisites for releases (#2915).
A shipped tool with a P0/Q3 release goal must have a row in the org roadmap.
Carry unmet gates into the next quarter before dependent features count as complete.

Each row names an owner, source tracker, downstream dependency and acceptance evidence.
The maintainer of each repository publishes its releases. Strategist maintains the org links.
At each quarterly review, compare source priorities with the org rows in both directions.
A release needs immutable artifacts, checksums where applicable, test evidence, compatibility notes,
a rollback path and a review of consumer pins.

Record upgrade results and install/use feedback in the source tracker, linked to org metrics #1174.
Tacklebox specifies a 30-day review.

Live status belongs in source trackers or generated reports. Each row defines a gate.

## Source contracts

- [finupdate ROADMAP](https://github.com/tuna-os/finupdate/blob/main/ROADMAP.md):
  first tagged release and Q4 cadence. The issue's #66 reference names the PR
  for its roadmap, merged 2026-08-25. GitHub records closure of its historical tracker #65.
  That closure alone does not prove a release exists.
- [tacklebox ROADMAP](https://github.com/tuna-os/tacklebox/blob/main/ROADMAP.md):
  #237 defines the baseline for binaries and containers, plus the 30-day review.
  Coordinate pins with tunaos #1192; boot evidence must precede changes.
- [Identity assets roadmap](https://github.com/tuna-os/branding/blob/main/ROADMAP.md):
  #7 defines the versioned contract for consumers. A manifest alone does not prove consumers match it.
- [remora ROADMAP](https://github.com/tuna-os/remora/blob/main/ROADMAP.md):
  #44/#55 distinguish a release from a successful package install.
  This gate qualifies builds, not the first version.

## Additional-tool audit

The audit on 2026-10-22 covered the four roadmaps above and the two other repositories named in #2915.

- [flatpak-index ROADMAP](https://github.com/tuna-os/flatpak-index/blob/main/ROADMAP.md):
  choose an owner and consolidate publication first. It names
  `tuna-os/docs/static/flatpak/` as the production source.
  A tag on the historical index does not prove the served remote works.
  Q4 acceptance needs a source/owner decision and immutable inputs from publishers.
  It also needs checks for drift at the served index and a tested rollback path.
  Check finupdate discovery against that served source.
- `gh api repos/tuna-os/debian-copr/contents/ROADMAP.md` returned HTTP 404.
  A missing roadmap does not establish a commitment to a first release.
  For Q4, inventory references from shipped consumers. Identify its source plan and owner.
  Define immutable references for packages or snapshots, verification and rollback before dependent work counts as complete.

Continue the audit from actual build/install references and the org inventory.
Inspect each tool's source roadmap and release contract.
Add each P0/Q3 prerequisite to the org table with an owner and tracker.
Each dependency needs a linked gate or a reason why a tagged software release does not apply.
For an index, immutable inputs and checks against its served endpoint can supply that contract.
These rules do not authorize changes to service ownership or publication of releases.
