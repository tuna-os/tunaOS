# Workflow, Fork, Package and Matrix Failures

Back to the [index](README.md).

## Fork source pin changes after tests

Symptom: the fork review tool reports a catalog pin mismatch after Python tests.
Cause: imports create untracked bytecode under `system_files/usr/libexec`.
The receipt must select only Git-tracked source files. The test for the fork contract
checks that temporary bytecode leaves the pin intact and a source edit changes it.
Do not refresh a source pin to accept temporary files.

### Countme clean install rejects a missing overridden dependency

**Symptom:** The `Test countme collector with D1` step fails with
`Missing: undici@8.12.2 from lock file` before tests start. Observed in
[Unit Tests run 39146505460](https://github.com/tuna-os/tunaOS/actions/runs/39146505460).

**Measured cause:** At `fe228c4`, `services/countme/package.json` overrides
Miniflare's `undici` to `8.12.2`, but the lockfile has no matching package entry.
Node 24.19.0 / npm 11.9.0 reproduces the failure with
`npm ci --ignore-scripts --prefix services/countme`.

**Fix:** Regenerate with `npm install --package-lock-only --ignore-scripts
--prefix services/countme` using Node 24 / npm 11. Preserve metadata for other platforms and commit the missing resolved package and integrity. Verify with a
clean `npm ci --ignore-scripts`, `npm test`, and `npm run build` in that directory.
Check each override edit with `npm ci`. The same npm major alone does not
prove that the manifest and lockfile agree.

### Matrix drift check fails when old results enter or leave the window

**Symptom:** The check reports a change between `—` and a pass or fail glyph.
Run [39161613161](https://github.com/tuna-os/tunaOS/actions/runs/39161613161) shows this for removed desktop cells.

**Cause:** These tables show results for cells outside the current schedule.
The check treated each `—` as a config change, even for those cells.

**Fix:** Use each table's source matrix to mask only old pass and fail results outside its schedule.
Keep scheduled cells and `⬜` distinct from `—`. Preserve the results and their dates in the output.
## Fork preview reuses stock packages/art or rejects a changed checkout

**Cause:** The key for the cache had only a hash of shell scripts.
Thus, two forks could use the same key. Pins include hashes of source files.
An edit to those inputs makes a config stale. A frozen stock example also failed
after each dependency update, even when the build contract did not change.

**Fix:** The preview adds a hash of the manifest and assets to the cache key.
`test_real_build_engine_receives_fork_cell_and_cache_identity` runs the build driver
with a stub builder. Different bytes make the keys different.
This test does not prove container-cache behavior or image acceptance.

Create new configs from templates; do not refresh a real fork's pin automatically.
If sources change during a copy, review the receipt. Then prepare a new output
directory from a stable checkout.

Fork previews also disable layer reuse with `--no-cache`. Some legacy stages
declare the cache argument after their base hooks. Gentoo has a separate branch
for desktop builds. Tests must prove each stage before fork builds can reuse layers.

### Anime wallpaper disappears after desktop setup

**Symptom:** The selector chooses anime or a desktop override, but the final
wallpaper is the vector fallback (PR #3465).

**Cause:** RPM and Gentoo run `90-image-info.sh` after desktop setup. Overlays
copy `system_files` again and then run it. It copied the vector over the
selected art. Selector-only tests did not cover this final writer.

**Fix:** Use the shared selector from the identity writer too, with
`TUNAOS_IMAGE_FLAVOR` to identify the desktop in overlay builds.
Apply artwork from the fork afterward. Run `pytest tests/test_anime_finalization.py`.

The fixtures execute the complete identity writer in those orders.
They check all 14 real JPEGs across six desktops.
They preserve desktop overrides, custom fork art and URLs.
A variant without a wallpaper now stops the build; the vector fallback is gone.
Fork overlay input remains unsupported and fails closed.
These are source-level tests, not built-image or boot acceptance.

### README build-status refresh stops on a GitHub API 502

**Symptom:** `Update README build status` fails in `Refresh build status table`
with `gh: Server Error (HTTP 502)` before it opens a refresh PR.

**Measured cause:** [run 39310599051](https://github.com/tuna-os/tunaOS/actions/runs/39310599051)
(job 118258852799, 2026-10-19) installed yq successfully, then an unretried
read in `update-build-status.sh` aborted the generator. This was not a rejected
push to protected `main`; the workflow already publishes through a PR.

**Fix:** Use `gh_read_retry` for the run-list and paginated job reads.
Try at most three times. Wait 5/10 seconds for transient network or HTTP 5xx
errors. Rate limits retain their original diagnostic: `gh run list` does not
expose reset headers, so do not guess when GitHub allows another request.
Authentication, authorization and other errors fail immediately.

Buffer the output of each try. If a page fails, discard all output from that
try. After three failures, retain the command's exit status and diagnostic.
Keep README unchanged; do not publish a partial table.
See `tests/test_readme_status_api_retries.py` for regression tests.


### Hardware inventory reports firmware present when only a backup exists

**Symptom:** `hardware-<id>.txt` (formerly `x13s-inspection.txt`) reports `PRESENT` for an absent firmware payload.

**Cause:** The W1 inspector matched `basename.*`. A fixture with only
`amss.bin.bak` reproduced the false result. Signature files and compound suffixes
such as `.xz.bak` also matched.

**Fix:** Match the exact filename, `.xz`, or `.zst`. Follow symlinks to shared payloads. Reject links without a target. Run
`python3 -m pytest -q tests/test_hardware_profiles.py` to check those cases.
The report lists files; it does not prove firmware validity or
hardware operation.

### ISO Builder presentation export drift

Symptom: `check-builder-config` reports drift in the generated builder configuration.
Cause: `docs/iso-builder.config.json` differs from `[iso_builder]` in primary
`tunaos.toml`. The regression test compares the complete deterministic export.
Fix: edit TOML, run `python3 scripts/config.py generate-builder-config`, then
run `python3 scripts/config.py check-builder-config`. Do not edit the JSON copy.

### Fork preparation reports changed sources with a desktop override

Symptom: the test for source receipts rejects a tracked desktop adapter, or preparation
reports `sources changed during preparation` before a build starts.
Cause: commit `aa9810e9` added `manifests/desktops/tuna-arch.yaml` after
TOML became the primary owner of desktop policy. The source index includes this ignored
path, but `git add --all` in the prepared context omits it.

Fix: `[desktops.tuna-arch]` owns the override for GDM on Marlin in `tunaos.toml`.
The compiler emits its ignored adapter. Regression tests exercise native GDM and
session-hook ordering, plus regeneration after an ignored adapter is corrupted;
they do not freeze a copied historical dependency list. No package pin changes
are part of this repair.

**Config-only image qualification:** run `41207825611` stopped first in the
RPM `modifiedBase` build: `verify-plymouth-initramfs.sh` rejected
`config-proof.script` with `declares no FRAME_COUNT`. The comment-only fixture
was not a usable splash. The later APT builds never ran; this is not an APT
failure.

The qualification fixture now draws one centered static image with
`FRAME_COUNT = 1;` and `Image.New("config-proof-0001.png")`. Its owned asset
contract copies and hashes the PNG alongside the theme definition and script;
the source and image evidence gates require all three exact files. Keep the
strict initramfs guard: it must find the physical `*-0001.png` frame and verify
image/initramfs byte parity. A zero frame count would bypass that check rather
than repair the splash. Source tests alone do not qualify a rebuilt image.

### `Test` fails after a `tomli` dependency update

**Symptom:** The `Test` workflow fails in `tests/test_primary_config.py` on
Python 3.10. `test_parser_keeps_the_shared_toml10_grammar` reports
`Failed: DID NOT RAISE TOMLDecodeError` for TOML 1.1-only fixtures, and the
smoke test for Renovate-only changes fails because it runs the same suite.

**Measured cause:** `tomli==2.5.0` accepts trailing commas in inline tables and
`\xNN` escapes. The repository's Python 3.10/3.11 compatibility contract still
needs TOML 1.0 grammar; Python 3.11's stdlib `tomllib` rejects both inputs.
[Run 39421110868](https://github.com/tuna-os/tunaos/actions/runs/39421110868)
shows the failure after `tomli` 2.5.0 merged.

**Fix:** Use the bundled Tomli 2.3.2 source on every host.
Tomli 2.4.0 first added TOML 1.1, so a `<2.5.0` cap did not hold the grammar.
The 2.3.2 release keeps TOML 1.0 and includes the key and nesting limit fixes.
Review grammar changes with the same tests on all supported hosts.

### Config works on one Python host but fails on another

**Symptom:** Python 3.15 accepts a config that Python 3.10 rejects.

**Cause:** The old loader used the host's standard library when present.
Python 3.15's parser accepts TOML 1.1. The config contract still uses TOML 1.0.
The test `test_parser_keeps_the_shared_toml10_grammar` covers this split.

**Fix:** Use the bundled Tomli parser on every host, with no standard library fallback.
Restore the reviewed source checkout if its parser files are absent.
Config reads need no pip install or special sudo environment.
Run `python3 scripts/check-vendored-parser.py` to check the file hashes.

## Package authoring refuses an add or asks for an editor dependency

**Symptom:** `config-packages.py add` reports a missing/ambiguous native package,
a stale index, a receipt hash mismatch, or a missing `tomlkit` dependency.

**Cause:** The offline editor needs native names for every selected policy before
it writes. `tests/test_package_authoring.py` tests additions for apt and Gentoo.
An ambiguous Gentoo category or a failed index leaves the TOML file unchanged.
Read-only config validation does not need the optional editor dependency.

**Fix:** Install `requirements-package-authoring.txt` explicitly to edit files.
Refresh the native index and its receipt together, or use `search` followed by an
explicit `--native TARGET=exact-name` for a verified mapping. Do not remove a
failed target to imply all-base coverage. See the [package command guide](PACKAGE-AUTHORING.md)
for policy scope, provenance and native formats.

## Package addition conflicts with a DNF exclusion or exceeds the size limit

**Symptom:** An added package matches a DNF exclusion such as `htop*`, or a
config near 8 MiB cannot pass the next read after an addition.

**Cause:** The check used equality. It did not support globs. The input-size guard did
not cover serialized output. The regression cases in
`tests/test_package_authoring.py` cover direct and inherited exclusion patterns,
negative matches, and the no-write size boundary.

**Fix:** Check name globs for DNF after package-group expansion and reject oversized
output before replacement. For DNF, the installer passes exclusions through `-x`.
The [DNF rules](https://dnf5.readthedocs.io/en/latest/misc/specs.7.html#globs)
define this syntax. This check does not replace native transaction resolution.

### Retained browser candidate fails the v2 media join

A manifest in R2 is not a member of a GitHub ZIP archive.
Diagnostic observations from its producer are not a browser v2 receipt.
A false `artifact.mediaPath` misstates the location of the media.
An absent receipt anchor in GitHub loses the producer association.

Use the explicit branch for retained media. Preserve the run, artifact ID, and
archive hash. Verify the exact receipt member and its hash.
Pin the manifest hash independently before any chunk read.

The tiny fixtures in `tests/test_iso_retained_media_transport.py` reject wrong
origins, runs, and `runAttempt` values. They reject replay, changed manifests,
absent chunks, wrong whole-ISO identity, and unsafe members in ZIP archives.
These tests check consistency. They do not prove a real producer or installation.

### Removed Flatpak IDs stay in the hook file

**Symptom:** A cut-down ID stays in `tunaos-<desktop>.preinstall`.

**Cause:** The hook adds new IDs but it never deletes old IDs.

**Fix:** Delete the owned file at the start of each run. Keep files from other sources. Reject a linked file before you change files.

## Workflow inherits repository token defaults (#2916)

**Symptom:** `check-workflow-permissions.py` reports `missing top-level permissions`,
even when a job has its own map.

**Cause:** A job map covers only that job. Other jobs inherit the repository
or organization defaults. The regression fixture with only a job map fails
the checker; the fixture with a workflow map and a job that inherits it passes.

**Fix:** Declare `permissions: {}` or `contents: read` at workflow scope,
then grant write access only to the job that uses it. Check reusable callers
too. Run `python3 scripts/check-workflow-permissions.py` and
`python3 -m pytest -q tests/test_workflow_permissions.py`.

### A fork's image records the tuna-os vendor

**Symptom:** CI pushes a fork's image to `ghcr.io/<fork owner>`, but its
`image-info.json` names `tuna-os` as the vendor and `ghcr.io/tuna-os/...` as
its image reference.

**Cause:** The build step runs `just build` under `sudo`, and `sudo` resets
the environment. `GITHUB_REPOSITORY_OWNER` did not reach the build, so the
namespace fell back to `tuna-os`. The push steps run without `sudo`, so they
used the correct owner.

**Fix:** The build step keeps `IMAGE_REGISTRY` (`ghcr.io/<owner>`) through
`sudo`, and `scripts/lib/publish-destination.sh` splits it into host and
namespace. `tests/test_publish_destination.py` checks the precedence and the
split.

### A publish job fails with `publish credential: <code>`

**Symptom:** A fork with `[build.publish]` or `vars.IMAGE_REGISTRY` set to
something other than `ghcr.io/<owner>` fails in `Resolve publish credential`
with `missing-credentials`, `partial-credentials`, `missing-scope`,
`scope-mismatch` or `untrusted-event`.

**Cause:** `GITHUB_TOKEN` can write only `ghcr.io/<owner>`. Any other
destination needs the `TUNAOS_PUBLISH_USERNAME` and `TUNAOS_PUBLISH_PASSWORD`
secrets of the `publish` environment, and a repository variable
`TUNAOS_PUBLISH_SCOPE` that is exactly the destination. CI never falls back to
`ghcr.io/<owner>`.

**Fix:** Make the three values agree with the destination that
`scripts/publish-destination.sh` prints. `untrusted-event` means a pull
request, merge queue or comment run tried to publish; such runs never do.
`tests/test_publish_credentials.py` runs every code against stubs. See
[RFC 016](rfc/rfc016-publish-credentials.md).

## Content PR fails with `STE budget exceeded` (#2912)

**Symptom:** a CFP abstract or design contribution adds Markdown and the
`ste / Simplified Technical English` check fails with `STE budget exceeded`.

**Cause:** the shared linter counts findings across the repository, against
`.ste-budget`. Content directories have no automatic exemption. The pinned
linter supports lowercase `ste-disable-file: reason` and paired
`ste-disable: reason` / `ste-enable` comments; `<!-- STE-DISABLE -->` does not
match those directives.

**Fix:** run `just ste` and fix new findings in technical instructions. For
outreach copy or creative briefs, use the reasoned region or file opt-out in
[the contributor prose policy](../CONTRIBUTING.md#prose-checks-ste). Keep
technical steps checked on mixed pages. Run `just ste` again; do not increase
`.ste-budget` or exclude a whole directory to pass one content change.

### Opt-in OCI RPM consumer refuses a repository before DNF runs

**Symptom:** `install-oci-rpm-repository.py` reports an absent transport, a checksum mismatch,
a mutable reference or a controlled R2 URL in a repo/key field.

**Cause:** The candidate needs an explicit path to the reviewed producer transport.
It accepts only immutable snapshots with signatures and scope labels.
RPM configuration can retain URLs for keys over HTTP, even when the repository is disabled.
The offline cases in `tests/test_oci_rpm_consumer.py` reproduce these refusals without network access.

**Fix:** Supply the reviewed tool, key and a real qualified snapshot.
Remove the replaced persistent feed only through a reviewed migration of image stages.
Keep the signature, scope and URL guards. See `docs/OCI-RPM-CONSUMER.md`.
This helper does not switch production configuration. An absent snapshot remains a blocker.

### Image build stops with `identity.env is missing` or an identity drift error

**Symptom:** `90-image-info.sh` exits with `build_scripts/lib/identity.env is
missing`, or `just check` reports `generated identity drift` or
`generated variant-identity drift`.

**Cause:** The project name, URLs, CPE, variant codenames and variant accent
colours come from `tunaos.toml`, through `build_scripts/lib/identity.env` and
`build_scripts/lib/variant-identity.tsv`. The image build reads only those
generated files and has no built-in fallback, so a fork never gets TunaOS
identity by accident. A changed `tunaos.toml` without regenerated files, or a
hand edit to either file, makes them disagree.

**Fix:** Run `python3 scripts/config.py generate-identity` and
`python3 scripts/config.py generate-variant-identity`, then commit them with
`tunaos.toml`. A new variant also needs a `codename` and a `branding` table;
the generators name any variant without one.

### Primary identity and publish changes conflict during integration

**Symptom:** The identity and publish branches conflict in
`scripts/lib/tunaos_config.py` and `tests/test_fork_branding.py`.

**Cause:** Both changes add validators at the same locations. The identity
change removes the codename table check. The publish change replaces the
fixed vendor check with the resolved namespace check.

**Fix:** Keep both sets of validators and the resolved vendor check. Do not
restore the codename table assertion. Run
`tests/test_identity_publish_integration.py` with the identity and publish
suites. It checks a single config through the real writer and verifier on
a test filesystem, without a legacy fork manifest. This is not image build,
registry push, boot or install proof.

## Matrix board and provenance disagree after a merge (#3813)

**Symptom:** the committed-snapshot test reports 124 versus 120 green cells.

**Cause:** merge `4912d39d` retained the newer board but an older summary.
Identity PR #3681, Test run `40042245544`, failed only this pytest assertion
(5,234 passed). The per-cell evidence had seven newer desktop failures; a restore
of the older matching pair would hide those failures.

**Fix:** replay the reviewed [retained assertions](matrix-snapshots/README.md)
and check the board/provenance identity before publication. Preserve the
historical date and unknown overlay/full-sweep inputs. Do not hand-edit counts,
roll back newer failures, or label the reconciliation as a fresh health run.

**Symptom:** `check-matrix-snapshot.py` reports `snapshot configuration
changed: tunaos.toml` on a PR that edits only a `tunaos.toml` description.

**Cause:** an early #3839 draft compared the committed pair's recorded
configuration hash with the checkout. One edited `description` string made
the check exit 1 on otherwise valid files. On 2026-10-24, 16 open PRs touched
`tunaos.toml`.

**Fix:** the recorded hashes stay sealed in the snapshot identity. Only
`--inputs` replay compares them with the checkout. `--check-structure`
catches board-shape drift from configuration.

**Symptom:** the check of Matrix Status on a PR ends `cancelled` with no jobs, even
though no newer push was made to that PR.

**Cause:** `matrix-status.yml` used one concurrency group, `matrix-status`,
for every event. GitHub keeps only the newest queued run in a group. A push
to any PR cancelled every other queued PR run, and could cancel a queued daily
refresh. 41 of the last 98 `pull_request` runs ended cancelled on 2026-10-24,
including run `40065011718` for #3839.

**Fix:** PR runs group by `github.ref` and cancel only their own superseded
runs. Schedule and dispatch runs still serialize in one `publish` group,
because they force-push `automation/matrix-status`.

### The beta lifecycle snapshot test fails after a nightly refresh (#3932)

**Symptom:** after the 2026-10-25 refresh (#3931), the committed-snapshot
test for beta lifecycle fails. All eight `bonito-rawhide` and
`flounder-sid` lifecycle cells read `fail` from run `38713238238`.

**Cause:** these results are not `BETA` probes. In that run, the jobs have no
prefix and failed in the stable-lane validation step. Before #3720, the beta
filter in `bootc-lifecycle.yml` had an inverted test, so rawhide and sid cells
ran the real check. #3720 also made the generator score those old checks. The
test still expected that each beta cell reads untested. It stayed green until
the first live refresh merged.

**Fix:** the test now accepts a beta lifecycle verdict only if it reads
untested or has a date before the lane fix (2026-10-23). Do not edit the
generated files, and do not add a filter that hides the old failures.

### Package catalog tests fail with `effective package-source configuration changed; refresh observation`

**Symptom:** six tests in `tests/test_package_catalogs.py` and
`tests/test_search_base_packages.py` fail on `main`. Every test that reads the
real `tunaos.toml` fails the same way, including `tests/test_portable_add.py`
in #3856.

**Cause:** `config/package-observations/flounder-target-amd64.json` pinned the
SHA-256 of all of `image-versions.yaml` and `scripts/build-image-inner.sh`. On
2026-10-25 `build-image-inner.sh` differed from the pin by one cache-key line
(7a0a3898). `image-versions.yaml` differed by a removed `shfmt` pin, and Renovate
had edited it 197 times since 2026-09-01. Neither change touches an apt source.
A whole-file hash on a Renovate file turns the check red on every merge.

**Fix:** the observation (schema 2) pins the `common` image entry of
`image-versions.yaml` and the part of `build-image-inner.sh` before its rechunk
pass. A test fails when a new file reads `image-versions.yaml`.
A Renovate bump of an unrelated key now passes. A bump of the `common` digest
still fails, which is correct, because that image supplies files that the build
copies into the target.

### Package catalog tests fail again after a change to a pinned build file

**Symptom:** the same `effective package-source configuration changed; refresh
observation` error returns on `main`, in 12 tests of
`tests/test_package_catalogs.py` and in `tests/test_search_base_packages.py`.
It followed #3739 (F4, image-wide package additions).

**Cause:** #3739 made `Containerfile.debian` run the new
`build_scripts/30-image-packages.sh` in the `20-packages.sh` step, so the
pinned hash of `Containerfile.debian` was stale and the new script and its
`build_scripts/lib/image-packages.sh` were not bound. Measured: the other five
pinned files, both extracts and the copied-source inventory still matched. The
new scripts add no apt source on this target. Apt rejects `repository` rows at
generation and at run time. An apt name cannot start with `-` or hold `/`, `=`
or `:`.

**Fix:** bind both new scripts by file hash and run
`python3 scripts/refresh-package-observation.py --catalog debian-trixie --write`.
Binding also refuses any repository row or unsafe name for the target, so a
later fork edit of the generated `image-packages.tsv` cannot add a source
unnoticed. Adding a plain package name needs no refresh.

### Package catalog tests fail after a Renovate bump of the Debian base image

**Symptom:** on `main`, `tests/test_package_catalogs.py` fails with
`effective package-source configuration changed; refresh observation`, and
`tests/test_portable_add.py` reports `source-error` for every flounder target.
The first error is `base image changed; refresh the reviewed source
observation before lookup`.

**Cause:** Renovate changed the `debian:trixie` digest in
`variants.flounder.base_image` and in `Containerfile.debian`. Commit 8127ffb1
moved it from `4c252754…` to `2dc419c6…`. Renovate does not change
`observed_base_image` (its regex matches only `base_image` at line start), so
the base and target observations still name the old image.

**Fix:** run these commands, in this order, and review the diff:

```sh
python3 scripts/observe-package-base.py --catalog debian-trixie --write
python3 scripts/refresh-package-observation.py --catalog debian-trixie --write
```

The first command reads the new image index, manifest and layer from the
registry by digest. It records the APT source, the os-release file and the
archive key file. It does not execute code from the image. Then it checks the
result with the search binding. The binding refuses a new source file, source
set or archive key, so those need a separate review.

Run on the old digest, the command gives the committed observation byte for
byte. For `2dc419c6…`, only the snapshot comments in `debian.sources` changed.

### Gentoo desktop fails branding with unrendered identity tokens (#3980)

**Symptom:** the package proof for modified GNOME stops after install with
`unrendered @TUNAOS_*@ identity token` and `TUNAOS_BRANDING_FAIL`.
Both base proofs pass, with stock and modified configurations (run `40251865603`, `861a871f`).

**Cause:** `desktop-build` ran `90-image-info.sh` before the two asset copies.
Absent files receive no tokens from the renderer. The copies then left tokens
in seven paths: Plasma and wallpaper metadata, the live-ready unit, both Count
Me units and the installer recipe. A later copy can restore those tokens too.

**Fix:** copy the assets before the identity writer and `verify-branding.sh`.
Render all seven paths. Run the writer again after the final copy.
The #3980 regression fixture runs the full writer and verifier with redirected
paths for stock and fork TOML, including empty metrics settings.
It checks each late-copy failure and `install-countme.sh`, which must preserve
`/etc` opt-outs. Keep `verify-branding.sh` enabled.

These source tests do not
qualify an image. After source delivery, repeat acceptance for fresh Gentoo
images and packages (#3802).

### Native backend candidate selected from a bootloader heuristic

**Symptom:** A proposed v1.17.1 image is called native because it contains
systemd-boot or enables composefs in OSTree's `prepare-root.conf`.

**Cause:** v1.17.1 `crates/lib/src/bootc_composefs/image.rs` selects the native
default from `usr/lib/composefs/setup-root-conf.toml` only when OSTree configuration is absent
from both the vendor directory and `/etc`. The existing TunaOS probes
use older bootloader/config heuristics; those do not prove this contract.

**Next step:** Use the read-only [candidate contract](BOOTC-CANDIDATE.md) to expose
conflicts. Its inert tests cover all eight marker combinations and always refuse
runtime admission. Update the layout, dracut and installer consumers together
before a runtime trial. One marker change is not a complete fix.

### KVM tools cannot download after the image build (#3812)

**Symptom:** #3431 job 121823081846 built grouper, then `Enable KVM` failed
with APT exit 100. QEMU, OVMF and dependencies could not connect to
`azure.archive.ubuntu.com:80`. Boot verification did not run. This failure
provides no evidence about GDM or the guest image.

**Cause:** The PR verification step used a separate, unbounded APT install
through the default source on the runner. The earlier Podman setup in #3998
does not own this later acquisition.

**Fix:** `setup-kvm-tools.py` keeps `qemu-system-x86 qemu-utils ovmf ffmpeg`.
It replaces exact Azure/archive URI tokens with the official HTTPS archive
in temporary source files. It preserves suites, components and trust settings.
It uses #3998’s APT primitives: a 600-second budget, up to three tries
for downloads, SHA256 checks, and installation with downloads disabled.
The helper verifies versions after installation and cleans its restart override.

It does not change KVM rules, boot gates, or evidence collection.
SIGKILL and the outer job timeout remain outside its cleanup guarantees.

### Runner mirror-list indirection still selects Azure (#3812)

**Symptom:** At #3999 head `ac0c2bbc`, run 40404587905 jobs 121861626115
and 121861640934 reached the 600-second acquisition limit before installation.
Logs showed `file:/etc/apt/apt-mirrors.txt Mirrorlist` and Azure HTTP requests.

**Cause:** The [runner image configuration](https://github.com/actions/runner-images/blob/main/images/ubuntu/scripts/build/configure-apt-sources.sh)
uses `mirror+file:/etc/apt/apt-mirrors.txt` in Ubuntu sources. Azure has first priority in that list. A direct-URL replacement does not affect this indirection.
[APT’s mirror transport](https://manpages.ubuntu.com/manpages/jammy/man1/apt-transport-mirror.1.html)
selects the endpoint from that list, so the private source still reached Azure.

**Fix:** The KVM helper recognizes only that URI for the local mirror list.
It validates the file against the runner’s official Ubuntu endpoints and optional
priorities, then uses the HTTPS archive in private sources.
Unknown mirror forms, unknown entries, unsupported metadata, and missing, empty,
symlinked or oversized lists fail before APT. The helper preserves suites,
components, Signed-By, comments and unrelated direct sources. Host files remain
unchanged. The 600-second limit still applies; no trust override is necessary.

The Albacore job on the same head installed its tools, then reached the
separate GDM/Mutter 49.4 crash in #3969. That crash is not a mirror parser failure.

The owner temporarily deferred **only `albacore:tuna` graphical admission**
until the external Mesa fix
([decision](https://github.com/tuna-os/tuna-desktop/issues/577#issuecomment-6550264429)).
PR image CI still builds that image and validates its non-graphical inputs;
the boot step records `owner-deferred.json` with `qualified:false` instead of
attempting another known-broken graphical boot. The other ten Tuna variants
and all four canaries, including `albacore:gnome`, remain enforced. This does
not change publication policy or turn historical failed runs green:
run 41245697250 job 124674905339 remains failed, with retained
[artifact 13060743055](https://github.com/tuna-os/tunaOS/actions/runs/41245697250/artifacts/13060743055).

### Runner mirror list names an EC2 archive mirror

**Symptom:** `ValueError: Unsupported runner Ubuntu mirror entry` from
`setup-kvm-tools.py` on ubuntu-24.04 image 20261111.127.1, for example
`sailfin:tuna / linux-amd64` in run 43226745971 (job 131220723046). A rerun on
image 20261101.360.1 passed.

**Cause:** That job ran on AWS-hosted compute (`Cloud: AWS` in the runner
provisioner group). Its `file:/etc/apt/apt-mirrors.txt Mirrorlist` was 152 B,
not 144 B, and APT fetched from `http://us-east-2.ec2.archive.ubuntu.com/ubuntu`.
The first entry was the archive mirror of the EC2 region, not
`http://azure.archive.ubuntu.com/ubuntu/`, so the allowlist refused it.

**Fix:** The helper also accepts `http://<region>.ec2.archive.ubuntu.com/ubuntu`
entries. It still uses the HTTPS archive in private sources and still refuses
other hosts, user info, other paths and unknown metadata.

### Runner package acquisition limits (#3812)

The helper uses [Ubuntu’s documented archive](https://ubuntu.com/server/docs/how-to/software/package-management/)
and the [official ports archive](https://ports.ubuntu.com/ubuntu-ports/) over HTTPS.
It adds `resolute universe main` to a temporary copy of the source directory.
Host source files and trust keys stay intact. Temporary metadata lists prevent
use of stale indexes after a signature failure. Existing sources supply dependencies
under their existing trust policy.

The budget is 600 seconds for metadata, resolution and downloads.
Each of three download tries gets at most 200 seconds from that budget.
APT can retry each request twice, with a 30-second socket timeout.
There is no mirror fallback or suite change. After installation, the helper verifies each version in the transaction. All four packages must be installed, with Podman 5 or newer.

Ubuntu 26.04 only checks Podman, as the pinned action does.
For each cached package, the helper verifies its authenticated SHA256 value.
It removes corrupt entries and downloads them again. The workflow keeps the
original keys for the weekly cache, separated by architecture, and pinned restore/save actions.
The cache contains only package archives. Each run authenticates fresh metadata.

Installation has no helper timeout and no downloads.
The helper defers SIGINT/SIGTERM until dpkg and needrestart cleanup finish.
It cannot defer SIGKILL or the outer job timeout. Logs show separate durations
for acquisition and installation, on success or failure.

### Fresh GDM login starts Tuna but creates no AccountsService record

**Symptom:** After desktop PR #931 (`cba3cdbd`), native run
[41215443626](https://github.com/tuna-os/tuna-desktop/actions/runs/41215443626)
failed both VM jobs. A real, manual first login for record-free `tunastd`
started Tuna. Sudo denial and logout passed, but its AccountsService file
was absent. The admin, second-login and reboot checks did not run.
The guest had GDM `51.1.1-1` and AccountsService `26.27.3-1`.

**Cause:** The template supplied `Session=tuna` before login.
[AccountsService 26.27.3](https://gitlab.freedesktop.org/accountsservice/accountsservice/-/raw/26.27.3/src/user.c)
changes and saves the session only when its value differs
(`user_set_session_authorized_cb`, lines 2283–2309).
Thus a stock `SetSession("tuna")` on inherited `tuna` does not save a file.
This source mechanism explains the observed missing file; it is not proof
that a new image passes.

**Fix:** For installed GDM 51 or newer with the compiled
`daemon/FallbackSession` key, set explicit empty `[User] Session=` in both
account-type templates. Keep `[daemon] FallbackSession=tuna`.

Empty `Session` overrides legacy `XSession` and vendor defaults.
[GDM 51.1.1](https://raw.githubusercontent.com/GNOME/gdm/51.1.1/daemon/gdm-session.c)
uses that fallback before GNOME (lines 616–650). The
[session settings of GDM](https://raw.githubusercontent.com/GNOME/gdm/51.1.1/daemon/gdm-session-settings.c)
ignore an empty inherited value. They save the selected session through stock
AccountsService (lines 294–323 and 374–420).
**Inference:** empty-to-`tuna` now causes a real save.

On GDM 47, 48 and 50, keep `Session=tuna`.
[GDM 48](https://raw.githubusercontent.com/GNOME/gdm/48.0/daemon/gdm-session.c)
prefers a launchable GNOME session, even with `NoDisplay=true` (lines 627–633).
The helper reads the installed `gdm` or `gdm3` binary, not a version override.
Missing or unreadable versions cannot select empty templates or pass the
image guard. No per-user records change.

**Acceptance still held:** Run the unchanged native journey on the candidate
image. Both accounts must lack records before login. The journey must show a
manual login into Tuna. It must show `Session=tuna` records that stock
AccountsService creates, and correct sudo results.

The journey must also show a second login, a reboot, stable identities and
exact image, package and source evidence. Keep the old-version and
saved-user-choice checks. No cache calls, fake records, delays or weaker guards
can replace this evidence.

## Rustup version changed but installer hashes stayed old

**Symptom:** merge-queue [run 41473711091](https://github.com/tuna-os/tunaOS/actions/runs/41473711091)
failed Unit Tests with `unexpected RUSTUP_VERSION: 1.29.2`.

**Cause:** `toolchain/Containerfile.debian` selected Rustup 1.29.2 but kept
the 1.28.2 hashes for both architectures. A source-only test also duplicated
the old version and hashes. Updating that test alone would leave the real
download guard rejecting the new installers.

**Fix:** update both pins from the release's official
[x86_64 checksum](https://static.rust-lang.org/rustup/archive/1.29.2/x86_64-unknown-linux-gnu/rustup-init.sha256)
and [aarch64 checksum](https://static.rust-lang.org/rustup/archive/1.29.2/aarch64-unknown-linux-gnu/rustup-init.sha256).
Keep the versioned HTTPS URLs, strict checksum check and unsupported-architecture refusal.
Remove tests that pin source text rather than copying new literals into them.

**Verification:** both actual installer streams hashed to their matching
upstream checksums. Neither installer was executed; no toolchain image was built.

## Daily verification failure appears on a passing cell's issue

**Symptom:** #1734 received a recurrence comment for
[run 37453199979](https://github.com/tuna-os/tunaOS/actions/runs/37453199979),
although `Verify hummingbird:cosmic` (job `112234466278`) passed both bootc
labels and `bootc install print-configuration`; `hummingbird:gnome` failed.

**Cause:** `daily-verify.yml` selected the first result from a full-text search
of issues. A matching cell name in an issue's comments could redirect another
cell's failure report to it.

**Fix:** search titles, then compare each title with the expected title before
you post a comment.
Create a new issue when no exact match exists. The #1734 regression executes
the reporter with the wrong cell ranked first, both with and without an exact
match. Check the individual `Verify variant:flavor` job to diagnose an
image regression from a recurrence comment.
