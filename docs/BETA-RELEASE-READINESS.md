# BETA product release readiness

This is the delivery plan for [#2935](https://github.com/tuna-os/tunaos/issues/2935),
with a target of 2026-12-31. It defines evidence to collect, not current release
status. Strategist coordinates the review; each source repository's maintainer
owns its release. This plan does not declare the products ready.

## Delivery gates

| Workstream | Responsible role | Prerequisite | Acceptance evidence |
|------------|------------------|--------------|---------------------|
| Branding release | branding maintainer | [branding#7](https://github.com/tuna-os/branding/issues/7) consumer contract | Versioned GitHub Release, canonical SVG archive, manifest naming every asset with SHA-256 and source revision, verification and installation instructions |
| Installer consumption | fisherman maintainer | Branding release above | Reviewable sync against an immutable release/revision; all manifest assets present, hashes match, freshness check fails for missing or modified marks; consumer pin and update procedure documented |
| Mariner release | mariner maintainer | Record upstream-follow versus TunaOS identity policy in the source repository; validate sync and both build architectures | Versioned GitHub Release with checksums, installation instructions, immutable Flatpak build reference, and evidence the intended fixes are included |
| Consumer instructions | docs maintainer with product maintainers | Verified artifacts from the preceding gates | An “Installing BETA tools” page in tuna-os/docs with exact versions, verification, install, upgrade and rollback instructions; test installation from the served Flatpak remote |
| Remaining BETA audit | strategist | Inventory procedure below | Every candidate has a source tracker, responsible role and release gate, or a documented exclusion |

Use v0.1.0 for `branding` and v1.0.0 for Mariner as the issue's proposed release
names, subject to the source maintainer's version policy. Source owners must authorize release publication, identity changes and credential grants.
A manifest alone does not satisfy the installer gate; a tag alone does not
satisfy the Flatpak installation gate.

## Sequence and review

1. At the next weekly contributor triage, assign named owners to the roles above in #2935.
   Link their source delivery trackers. Record the Mariner identity
   decision there before changes to application IDs, remotes or upstream-sync policy.
2. Complete and validate the source release contracts. Reuse the asset release work
   in roadmap PRs [#3622](https://github.com/tuna-os/tunaos/pull/3622) and
   [#3623](https://github.com/tuna-os/tunaos/pull/3623). Those plans do not replace Mariner's delivery gate.
3. Publish through the source repositories' authorized release paths, then update
   consumers through separately reviewed pins. Test from a clean consumer environment.
4. At weekly triage through December, record evidence links or the exact unresolved
   dependency in the source tracker. Escalate any gate without an owner or delivery
   path; do not treat elapsed time as approval. At the 2026-12-31 review, carry each unmet gate into the next quarter.

## Reproduce the audit

Collect live evidence at review time; do not commit a hand-maintained availability
table. The following commands inspect the initial candidates and reference product:

```bash
gh api --paginate 'orgs/tuna-os/repos?per_page=100' \
  --jq '.[] | select(.archived == false) | [.name, .description]'
for product in branding mariner remora; do
    gh api "repos/tuna-os/$product/releases" \
      --jq '.[] | {tag_name, draft, prerelease, html_url, assets: [.assets[] | {name, digest, browser_download_url}]}'
    gh api "repos/tuna-os/$product/tags" --jq '.[] | {name, commit: .commit.sha}'
done
```

Inspect each candidate's README and roadmap for lifecycle declarations; descriptions
alone are not a complete BETA census. Follow actual build/install consumers and
include BETA tools discovered there. Record exclusions for libraries, archived
repos and OS variants governed by [VARIANT-LIFECYCLE.md](../VARIANT-LIFECYCLE.md).
For each included product, inspect release automation, successful release runs,
checksums and install instructions. Remora is a reference for release automation,
not proof that another tool's pipeline works. A checksum verifies the bytes;
it does not establish producer authenticity by itself.

On 2026-10-22, GitHub reported the issue's Mariner references
[#3](https://github.com/tuna-os/mariner/pull/3) and
[#5](https://github.com/tuna-os/mariner/pull/5) as closed PRs about
PR build validation and upstream sync respectively. Their closure does not prove
a versioned release or settle fork identity. Recheck the source workflow and its
runs before you attribute a present failure to either historical reference.

## Installing BETA tools: documentation handoff

The user-facing page belongs in [tuna-os/docs](https://github.com/tuna-os/docs),
not this maintainer-reference folder. For each product, publish the release URL,
exact version and source revision, checksum verification command, supported
architecture, and tested installation commands. For Mariner include the served
remote URL, application ID and immutable Flatpak commit; verify the installed
commit and launch the application. For `branding` include the manifest pin,
consumer destination and freshness-check command. Record upgrade and rollback
results alongside the release evidence. Do not invent install commands or use
`latest` before the release contract exists.
