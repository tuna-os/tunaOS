# Install-pipeline screen checkpoints

Every e2e run this repo has ever done photographed the pipeline and then threw
the pictures at an artifact bucket. `scripts/install-checkpoints.py` reads
them: it OCRs the frames `scripts/iso-e2e.sh` captures and checks each one
against the contract in `tests/install-pipeline-screens.yaml`.

The point is the class of failure that photographs cleanly. A compositor that
never started, a black screen behind a running installer process, an installed
disk in an emergency shell, an installed disk still sitting at a LUKS prompt
after the passphrase was "accepted" — every one of those produces a valid PNG
and a serial log that can look fine. What distinguishes them is the text on the
screen.

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
record, and the crop is kept as `<frame>.region-<id>.png`. A region is
`blocked` when tesseract, Pillow or the SVG renderer is missing, OCR reads
nothing, or `{variant}` has no `--variant`. That is never a pass, and on a
required checkpoint it is an enforced failure. Regions are `not-run` when the
frame is missing, stale or blank. A failed region fails the checkpoint even
when other regions are blocked. Regions need Pillow on the host (`python3-pil`).
The corpus, with swapped-logo, swapped-wallpaper, wrong-name, stale-frame,
wrong-window and OCR-unavailable controls, is
`tests/fixtures/install-checkpoints-v1/regions/`, which
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
- **No product names.** The frontends are being branded from the variant's
  `distro_name`, so a keyword containing "tunaos" would stop matching the
  moment branding is fixed — the contract would punish the fix.

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
| `iso-e2e.sh` locally | whatever you point it at | advisory unless `E2E_CHECKPOINT_STRICT=1` |
