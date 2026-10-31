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
| `failed` | an assertion ran and did not hold | `frame-missing`, `frame-blank`, `keyword-missing`, `forbidden-text` |
| `blocked` | the frame exists but OCR produced no text (tesseract failed, timed out or read nothing) | `ocr-empty` |
| `not-run` | an assertion was skipped because tesseract or ImageMagick is missing | `ocr-unavailable`, `render-unmeasured` |
| `unsupported` | blank or unreadable frame of a `needs_virgl` desktop on a host without virgl | `no-virgl` |

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
- an unknown key at the top level or in a checkpoint
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
