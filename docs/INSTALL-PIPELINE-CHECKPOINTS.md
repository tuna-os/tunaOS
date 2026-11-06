# Install-pipeline screen checkpoints

Every e2e run this repo has ever done photographed the pipeline and then threw
the pictures at an artifact bucket. `scripts/install-checkpoints.py` reads
them: it OCRs the frames `scripts/iso-e2e.sh` captures and checks each one
against the contract in `tests/install-pipeline-screens.yaml`.

The point is to detect failures that produce valid photographs. A compositor
may never start, or an installer process may run behind a black screen. An
installed disk may reach an emergency shell. It may stay at a LUKS prompt
after it "accepted" the passphrase.

Each failure produces a valid PNG and a serial log that can look fine. The
screen text distinguishes them.

## What is asserted

Per checkpoint, in TAP:

| Assertion | Catches |
|---|---|
| **PRESENT** — the stage's frame exists | a stage that never got as far as being photographed |
| **RENDERS** — grayscale stddev above `0.02` | a black or one-colour screen |
| **SAYS** — OCR text matches the checkpoint's keywords | the *wrong* screen: a greeter where a desktop was due, an installer that never drew its first page |
| **CLEAN** — OCR text contains none of the forbidden strings | panics, emergency shells, a leftover passphrase prompt |
| **FRESH** (`distinct_from`) — the frame is not pixel-identical to an earlier stage's | a hung guest or stale framebuffer photographed again under a new stage name |
| **IDENTITY** (`regions`) — a crop of the frame says its keywords and/or matches shipped artwork by perceptual hash | the right screen with the wrong name, logo or wallpaper; another app's window where the expected one should be |

Outputs go next to the frames, so CI uploads them with the other evidence.
They are: TAP on stdout, `install-checkpoints-<desktop>.json`, a labelled
contact sheet `install-checkpoints-<desktop>.png`, and one `<frame>.ocr.txt`
per frame. With the transcript, you can diagnose a keyword failure. You do not
have to run an hour of QEMU again.

Each checkpoint in the JSON summary also carries an `outcome`, a stable
`reason` token and a human `detail` (and TAP prints
`# [<id>] outcome: <outcome> (<reason>)`):

| Outcome | Meaning | Reasons |
|---|---|---|
| `passed` | every assertion that applies ran and held | `checks-held` |
| `failed` | an assertion ran and did not hold | `frame-missing`, `frame-stale`, `frame-blank`, `keyword-missing`, `forbidden-text`, `region-keyword-missing`, `artwork-mismatch`, `artwork-asset-missing`, `artwork-asset-unreadable` |
| `blocked` | the frame exists but could not be judged: OCR produced no text, or a region could not be judged | `ocr-empty`, `region-ocr-unavailable`, `region-ocr-empty`, `pillow-unavailable`, `artwork-renderer-unavailable`, `variant-unknown`, `frame-unreadable` |
| `not-run` | an assertion was skipped because tesseract or ImageMagick is missing | `ocr-unavailable`, `render-unmeasured` |
| `unsupported` | blank or unreadable frame of a `needs_virgl` desktop on a host without virgl | `no-virgl` |

### Regions and artwork identity

Whole-frame keywords say which screen was reached, not whose. A checkpoint can
declare `regions`: boxes given as `[x, y, w, h]` fractions of the frame. Each
region can assert:

- `keywords`, OCR'd off the crop alone. A display name elsewhere on the screen
  cannot satisfy it.
- `artwork`, the 64-bit dHash of the crop against a file this repo ships
  (`asset`, repo-relative, `{variant}` substituted from `--variant`; PNG/JPEG
  through Pillow, SVG through `rsvg-convert`). The check passes when at most
  `max_distance` bits differ (0..31). `asset_box` crops the asset too, and
  `background` flattens a transparent mark.

Each region gets its own `outcome`/`reason` under `regions` in the checkpoint
record. The tool keeps its crop as `<frame>.region-<id>.png`. A region gets
`blocked` if tesseract, Pillow or the SVG renderer is missing. Empty OCR or
`{variant}` without `--variant` also gives this outcome. That never counts as
a pass. A required checkpoint enforces it as a failure.

Regions get `not-run` if the frame is missing, stale or blank. A failed region
fails the checkpoint even if other regions have outcome `blocked`. Regions
need Pillow on the host (`python3-pil`). The corpus, with swapped-logo,
swapped-wallpaper, wrong-name, stale-frame, wrong-window and OCR-unavailable
controls, is `tests/fixtures/install-checkpoints-v1/regions/`, which
`tests/test_install_checkpoints_regions.py` runs.

A required checkpoint never looks like a pass:

- `failed` and `blocked` are always enforced failures.
- A forbid-only checkpoint can hold its CLEAN assertion on an empty
  transcript. It then gets a `required checkpoint judged` failure.
- A required `not-run` with no other failure exits 77, not 0.
- `unsupported` keeps the existing no-virgl policy: the script reports it but
  does not enforce it.

The installer's own pages are **not** asserted here. That is
`scripts/installer-walkthrough.py` against `tests/installer-screens.yaml`,
which drives the frontend with `sendkey` and OCRs each page as it steps
through. If the walkthrough ran in the same evidence directory, this summary
includes its `walkthrough-<desktop>.json`. Thus one artifact reports the whole
pipeline.

## Contract version

`tests/install-pipeline-screens.yaml` declares `schema_version: 1`. The script
reads only that version. On load, it rejects these errors with exit 78:

- a different version or no version
- an unknown key at the top level, in a checkpoint, in a region or in an
  artwork block
- a region box outside the frame, a region with neither keywords nor artwork,
  a duplicate region id, an artwork `max_distance` outside 0..31, or an asset
  that is absolute, leaves the repo or uses a placeholder other than
  `{variant}`
- a `distinct_from` id that is not an earlier checkpoint
- a desktop outside kde/gnome/cosmic/niri/xfce
- a phase or match mode that the script does not support
- a `required` value that is not a boolean
- a keyword or forbid entry that is not a non-blank string
- an empty per-desktop override
- a duplicate checkpoint id

For each error, it prints a
`Bail out! invalid checkpoint contract <file>: <path>: <problem>` line.
Before, each of those errors loaded and silently changed the assertions. For
example, a misspelt `keyword:` key removed the keyword assertion fully.

`regions` and `distinct_from` are optional keys added to version 1 without a
bump. A reader that predates them refuses any document that uses them, with
an unknown-key exit 78, so no consumer can silently skip them.

MEASURED/DERIVED provenance stays in YAML comments. The checked shape does not
include it. The positive and negative corpus is
`tests/fixtures/install-checkpoints-v1/`.
`tests/test_install_checkpoints_corpus.py` runs it.

## Running it

`iso-e2e.sh` calls it automatically at the end of its `ready`, `ssh`,
`install` and `kickstart` (`--luks`) modes — advisory by default, a gate
(exit 9) with `E2E_CHECKPOINT_STRICT=1`. On any directory of evidence you
already have:

```bash
python3 scripts/install-checkpoints.py luks-out --variant marlin --flavor kde
```

It needs `tesseract` and ImageMagick. Without them, it does only presence and
render checks and says so. If a required checkpoint stays `not-run`, it exits
77. With `--strict`, it stops with 77 before it starts. Exit 78 means that the
contract is not valid.

## Opt-in one-image GNOME journey (#4103 / #4105)

This is a separate capability, not another prerequisite for plain installation
(#3797), fresh-account routing (#4092), or encrypted prompt qualification (#4090).
The existing `luks-e2e.yml` workflow exposes `visual_journey`, with an explicit
single `variant`, `flavor=gnome`, and exact `visual_index_digest` /
`visual_platform_digest` inputs. It rejects broad sweeps and an extra TPM boot
in this mode. The ordinary monthly/reusable lane keeps its existing scope.

The bounded source-backed starting profile is `yellowfin:gnome`: its canonical
Plymouth `tropical-fish.script` declares `FRAME_COUNT = 1`. A static splash is
therefore valid; animation is required only when the selected script declares
multiple frames. Other GNOME cells are individual runs, not inherited passes.
No published candidate has been qualified merely by adding this source path.
Supply the chosen published index/platform digests, rather than a moving tag:

```bash
VARIANT=yellowfin FLAVOR=gnome \
TUNAOS_E2E_VISUAL_JOURNEY=1 \
TUNAOS_VISUAL_IMAGE_REPOSITORY=ghcr.io/tuna-os/yellowfin \
TUNAOS_VISUAL_INDEX_DIGEST="$INDEX_DIGEST" \
TUNAOS_VISUAL_PLATFORM_DIGEST="$PLATFORM_DIGEST" \
scripts/iso-e2e.sh "$ISO_PATH" --luks --output "$FRESH_PRIVATE_OUTPUT"
```

The output directory must be empty, is made private, and gets an exclusive
ownership marker. The installed account is created by the existing installation
recipe; the journey never injects a compositor, enables SSH, changes sudo rules,
or writes wallpaper preferences. Existing-user preference behavior is explicitly
`not-run`, rather than inferred from this fresh account.

Sequence and evidence boundaries:

1. Disable and refuse bash tracing (`-x`) before any credential expansion,
   refusing execution if tracing is active with a caller password override, and
   protecting any configured `BASH_XTRACEFD`. Freeze and terminate the existing
   timelapse recorder **and its owned capture descendants**, checking the
   recorder PID/start identity and a monotonic termination deadline. A surviving
   observer blocks credential entry. Observers remain stopped for the rest of
   the run; no background recorder is resumed into a password screen. Arm the
   secret-entry capture guard before the LUKS helper runs; retain it on all
   failures so `screenshot installed-desktop-failed` cannot photograph the
   prompt. Require the helper's successful exit and its existing
   `NO_POWEROFF` success event (emitted only after passphrase/userspace checks),
   then keep the guard armed until logind proves the active graphical GDM
   session before pre-auth capture. No host-generated marker is injected into
   guest serial. The QEMU VNC server itself does not record frames; existing
   foreground VNC/screendump helpers are synchronous, not recording services.
2. Sample only actual QEMU early-boot frames, with bounded retries against the
   canonical centered artwork. Missing/unsupported capture stays required
   `not-run`/`blocked`, never a reused desktop or generated splash. For a declared
   animation, retain a second canonical frame and require different pixels.
   Read back the selected theme and exact booted-kernel initramfs hash, compare
   theme/script/artwork bytes in that initramfs to canonical sources, and compare
   its selected script plugin bytes to the installed image's plugin.
3. Observe logind's active graphical `Class=greeter` session, GDM account/UID,
   absence of an authenticated graphical user session, and the installed account's
   actual display name (`getent passwd` GECOS field), then retain the first
   pre-auth frame. The GDM central user card region asserts this observed user
   display name (the recipe normally sets `"TunaOS End To End"`); missing GECOS
   is blocked, not replaced with that default. Preserve the variant lettermark
   separately in the bottom region without inventing an OS label. Read the
   compiled GDM profile unprivileged with an isolated, temporary user config;
   this is **compiled-default evidence**, not a claim to have read GDM's private
   per-user overrides. Actual wordmark consumption additionally requires the
   separate rendered canonical-lettermark region.
4. Establish the actual **empty** password field through a final pre-secret
   readiness capture, then authenticate through the existing hardware-key path.
   Arm the foreground capture guard before the first credential key; unsupported
   keys abort without printing any credential character. The recipe containing
   both test secrets is kept outside the artifact directory and removed by the
   exit trap. Only after logind proves the intended active GNOME account/UID,
   `LockedHint=no`, and an unchanged boot ID may the adapter clear that guard
   and resume foreground captures. Authentication timeout/abort keeps the guard
   armed and does not take a failure screenshot of the secret-entry surface.
5. Read both fresh-session light/dark wallpaper keys and compare the consumed
   alias bytes with the selector's actual canonical winner:
   `<key>-gnome.jpg`, then `<key>-anime.jpg`, then `<key>.jpg`. Dismiss overview
   without changing settings and require matching pixels with GNOME's zoom
   geometry, not merely an installed file.
6. Open the installed **real** `gnome-control-center` About UI on the existing
   user's bus (`system about`, or the installed older `info-overview` panel).
   Trace `LOGO=tunaos` icon resolution: query and verify the actual consumed
   installed icon files (`/usr/share/icons/hicolor/scalable/apps/tunaos.svg` and
   `/usr/share/pixmaps/tunaos.svg`) by comparing their SHA256 hashes against
   the repo canonical About asset (`system_files/usr/share/tunaos/logos/{variant}.svg`).
   Both installed paths are required byte bindings, not alternative fallbacks.
   Missing `LOGO` or unavailable icons remain `blocked`; unsafe/noncanonical
   icon names and altered bytes fail. No missing identity defaults to `tunaos`.
   Require the owned Settings
   process to remain active while the actual product/version/mark regions are
   captured. No synthetic window, file viewer, new graphical session, fixture
   image, or security relaxation substitutes for the application. Stop the
   owned Settings unit and record any cleanup failure.

`--visual-journey` enables required `phase: visual` assertions in the existing
schema-1 screen contract; ordinary invocations exclude that phase. The
`visual_journey` field in `install-checkpoints-gnome.json` carries the operation
receipt (also retained as `visual-journey.json`), canonical/config/asset hashes,
actual installed `os-release`, canonical installed identity, boot/session
identity, exact ISO hash, installed platform digest and published index
membership, source/harness/schema/QEMU identities, run/attempt, retries, first
failure and cleanup. Final capture hashes must match this run's receipt.
Required missing, blocked, unsupported, stale or mismatched evidence cannot
finalize success. Cleanup updates the same summary after owned-process teardown;
a video sidecar or an empty failure list is not a success criterion.

The current workflow builds a dev ISO and uses an under-test installer, so its
receipt is explicitly `modified-canary`, **not published-image acceptance**.
The installed manifest must still equal the requested platform digest, and that
digest must belong to the requested published index. Record that exact slice,
not all variants, in #3381.

Runtime prerequisites remain real requirements: the installed image must expose
the harness's existing SSH transport, logind read properties, compiled GDM
profile and its assets, the authenticated user's graphical bus/systemd manager,
and an installed Settings About panel. The installed booted-kernel initramfs
must be readable with `lsinitrd`; private/missing initramfs or unavailable tools
remain blocked without a permission bypass. A missing display bus, unsupported
About panel, early application exit, or missing final paint is reported, never
replaced with a mock screenshot.

Host dependencies add Pillow, `rsvg-convert`, and `skopeo` to the existing
OCR/ImageMagick/PyYAML tools. The fixed GNOME greeter/About region boxes are
conservative layout assertions, **not a claim of captured calibration**: retain
real positive/negative frames for the chosen layout before declaring the
published-image acceptance criteria satisfied. The existing
`test_install_checkpoints_regions.py` corpus covers artwork/region negatives;
its additional journey tests cover operation ordering, missing evidence,
authentication timeout, wrong consumed wallpaper, observer child termination,
and first-failure/cleanup preservation. `.github/workflows/test.yml` selects
these through its existing affected-path `tests/` pytest job. Those source
tests do not establish published-image runtime acceptance; the VM leg remains
separately dispatchable.


## Adding a desktop — the calibration procedure

Each desktop has its own keyword lists. The five installer frontends are
independent forks. The five display managers show almost no common text. Each
list in the contract has one of two labels:

- **MEASURED**: read off a real captured frame, with the run named.
- **DERIVED**: from headings measured against the frontends' source in
  `tests/installer-screens.yaml`, but not yet confirmed against a frame of that
  desktop.

To calibrate a list, change it from DERIVED to MEASURED:

1. Get frames for the desktop. Any run that captures them works:
   ```bash
   just iso marlin niri local niri 1          # dev ISO (ENABLE_SSHD=1)
   sudo ./scripts/iso-e2e.sh <iso> --ssh-only --output niri-out
   ```
   For the installed-system checkpoints you need a full `--luks` run.
2. Read what tesseract sees, not what the UI "says":
   ```bash
   tesseract niri-out/10-ready.png stdout --psm 6
   tesseract niri-out/10-ready.png stdout --psm 11   # sparse-text layout
   ```
3. Rewrite that desktop's list from the transcript, and record the measurement
   in the comment above it — variant, flavor, date, and which frame.
4. Only ever calibrate **down** to what a frame shows. Adding a keyword you
   have not seen on a frame makes the contract weaker in the one way that
   matters: it can then pass on a screen nobody has looked at.

Two rules the contract enforces (and `tests/pytest/test_install_checkpoints.py`
holds it to):

- **No bare short tokens.** Keywords are at least five characters and should be
  headings or prompts. `"next"` matches a button on nearly every page and OCR
  noise hits four-character strings by accident; `"install"` matches the word
  "Installer" in a titlebar, so it passes on a crashed installer whose window
  decoration is still drawn.
- **No product names.** The frontends use the variant's `distro_name` for their
  names. A keyword with "tunaos" would no longer match once the frontends use
  the correct names. The contract would then punish the fix.

## Promoting a desktop to a gate

`required: true` in the contract makes a checkpoint fatal *when the harness is
run in strict mode*; `checkpoint_strict` on `luks-e2e.yml` (and
`post-build-luks-e2e.yml`, which sets it for its cells) is what turns strict
mode on. The intended order for a new desktop:

1. DERIVED list, checkpoint advisory — the run reports what it saw.
2. One real frame per checkpoint; rewrite the list MEASURED.
3. Turn the cell strict, one desktop at a time, and leave it there.

`installed-desktop` is `required: false` for every desktop today for exactly
this reason: no captured frame has confirmed those word lists yet.

## Where it runs

| Workflow | Cells | Checkpoints |
|---|---|---|
| `post-build-luks-e2e.yml` (chained on Build Marlin) | `marlin:kde` per nightly build; all five desktops weekly | gate |
| `luks-e2e.yml` (monthly sweep, dispatch) | every variant x desktop | advisory unless `checkpoint_strict` |
| `luks-e2e.yml` with `visual_journey` | one explicitly named GNOME image/index/platform | required visual and state assertions; missing evidence fails |
| `iso-e2e.sh` locally | whatever you point it at | advisory unless `E2E_CHECKPOINT_STRICT=1` |
