# Installer frontends — verification & parity

TunaOS ships **five independently-forked installer frontends**, one per desktop:

| Desktop | Flatpak app id | Upstream |
|---------|----------------|----------|
| KDE | `org.tunaos.InstallerKde` | fork of bootc-installer |
| COSMIC | `org.tunaos.InstallerCosmic` | fork of bootc-installer |
| Niri | `org.tunaos.InstallerNiri` | fork of bootc-installer |
| XFCE | `org.tunaos.InstallerXfce` | fork of bootc-installer |
| GNOME | `org.bootcinstaller.Installer` | upstream, unmodified |

They all drive the same backend (**fisherman**, via `recipe.json`), but the UIs
are separate codebases. **Feature drift is therefore the default failure mode**:
a screen or recipe field wired up in one fork silently never lands in the others.
Nothing about "it built" or "it launched" catches that — this page does.

## What CI verifies, and how

`installer-smoke.yml` runs per desktop and checks, in order:

| # | Check | How | Catches |
|---|-------|-----|---------|
| 1 | **Desktop is up** | `pgrep -x` the exact compositor binary | greeter loops, TTY fallback |
| 2 | **Frontend launched** | `flatpak ps` matches the desktop's app id | wrong/missing frontend, autostart broken |
| 3 | **Screen is not blank** | grayscale stddev of each frame > 0.02 | black screen, no GL, dead compositor |
| 4 | **It advances** | consecutive frames differ > 500px | stuck on one screen, modal error |
| 5 | **Which screens** | OCR each frame vs `tests/installer-screens.yaml` | **feature drift between forks** |

Checks 3–5 come from `scripts/installer-walkthrough.py`, which drives the UI with
QEMU `sendkey` (compositor-agnostic — no ydotool/Wayland tooling in the guest),
screendumps each screen, and emits TAP plus `walkthrough-<flavor>.json`.

> **Historical note.** Check 2 used to be `pgrep -af "Installer|…"` run through
> `bash -c` — the pattern matched its own command line, so it passed
> unconditionally and never verified anything. Assertions that can match
> themselves are worse than no assertion: they read as green forever.

### Rendering caveat (why strictness differs per desktop)

**niri** and **xfwl4** are Smithay compositors that hard-require
`EGL_EXT_device_drm`; QEMU's plain `virtio-gpu` doesn't provide it, so on a
GPU-less CI runner they render *nothing* — legitimately blank (see
`docs/LUKS-TPM.md` and the virgl path in `scripts/iso-e2e.sh`). So checks 3–5
are **enforced** for kde/cosmic/gnome in CI and **recorded but not enforced**
for niri/xfce. Full-matrix enforcement runs on a host with a real GPU
(`TBOX_E2E_GPU=virgl`), where every frontend can actually draw.

## Screen contract

Defined once in [`tests/installer-screens.yaml`](../tests/installer-screens.yaml):

| Screen | Required | Meaning |
|--------|----------|---------|
| `welcome` | ✅ | entry point renders |
| `disk` | ✅ | target selection reachable |
| `encryption` | ⬜ | LUKS option exposed (see `docs/LUKS-TPM.md`) |
| `summary` | ✅ | confirm-before-install step |
| `install` | ⬜ | progress reporting |
| `done` | ⬜ | completion / reboot prompt |

Required screens fail the build for that frontend; optional ones are recorded so
drift is *visible* before we promote them to required.

## Parity matrix

Filled from each run's `walkthrough-<flavor>.json`.

| Frontend | Launches | Renders | Advances | welcome | disk | encryption | summary | install | done |
|----------|----------|---------|----------|---------|------|------------|---------|---------|------|
| KDE | ✅ | ✅ 9/9 | ⚠️ space only | ✅ | ✅ | ❌ none | ✅ | ⬜ | ⬜ |
| COSMIC | ✅ proc | ⚠️ desktop only | ❌ 0/8 | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Niri | _pending_ | _GPU_ | _GPU_ | _GPU_ | _GPU_ | _GPU_ | _GPU_ | _GPU_ | _GPU_ |
| XFCE | _pending_ | _GPU_ | _GPU_ | _GPU_ | _GPU_ | _GPU_ | _GPU_ | _GPU_ | _GPU_ |
| GNOME | _pending_ | _pending_ | _pending_ | _pending_ | _pending_ | _pending_ | _pending_ | _pending_ | _pending_ |

_GPU_ = needs a virgl-capable host to evaluate; blank on GPU-less CI is expected.

### KDE — run 29684495194 (yellowfin, strict) — PASSES

With the widened focus search the run reaches **6/8 transitions, 7 visual
states**, and satisfies every required screen: welcome, disk and summary.
Still space-only until tuna-os/tuna-installer-kde#5 lands.

**KDE has no encryption screen.** Its pages are welcome, diskselection,
confirm, progress, done — there is no LUKS step, even though fisherman
supports encryption. An earlier run reported `encryption: reached`, which was
the matcher hitting the string "Encryption: None" in the summary page's field
list. The keywords now match headings rather than bare nouns, so this shows as
the genuine feature gap it is. This is precisely the drift the matrix exists
to expose, and the matcher was concealing it.

`install` and `done` are unmeasured: the walkthrough stops before starting a
real install, by design.

### COSMIC — run 29684495194 (yellowfin, strict)

**The process runs but no window ever appears.** The compositor+frontend gate
passes (`flatpak ps` matches `org.tunaos.InstallerCosmic`), yet every frame is
the bare COSMIC desktop; between frame 00 and frame 08, six minutes apart, the
only thing that changes is the clock. 0/8 transitions, 1 visual state, and OCR
matched no screen at all — not even `welcome`. Filed as
tuna-os/tuna-installer-cosmic#4.

This exposed a flaw in check 3. It was called "installer renders actual
content" while measuring stddev over the **whole framebuffer**, so a booted
desktop with no installer window passes it — cosmic scored 9/9. It is now named
"screen is not blank", which is what it measures. Proving the installer window
specifically is mapped is what checks 4 and 5 do, and here they correctly
failed. The walkthrough now also prints an explicit diagnosis when the gate
passed but nothing advanced and no screen matched, rather than leaving six
identical "not reached" lines to interpret.

### KDE — run 29681255102 (yellowfin, strict)

First frontend measured end to end. It launches, and renders on all 9 frames.

**⚠️ Advances by space only.** Enter does nothing on any page: no button in
`tuna-installer-kde` is a Qt *default* button and nothing handles
`Qt::Key_Return`, so a focused `QPushButton` responds to space alone. That is a
real defect, not a harness artifact — a keyboard-only user cannot leave the
welcome screen. Filed as tuna-os/tuna-installer-kde#4. The walkthrough now
escalates `ret` → `spc` and reports which key worked, so this stays visible
instead of being papered over.

**Reached `welcome` and `disk` only.** The run stalled on Select Target Disk:
focus starts in the disk list, and a fixed two tabs never reached *Continue*, so
space just re-toggled the list. The driver now widens its focus search each time
a step produces no change. Until a run gets past that page, `encryption`,
`summary`, `install` and `done` are **unmeasured, not absent** — do not read the
❌ as "the frontend lacks these screens".

An earlier run (29675493401) reported `disk`, `encryption` and `install` as
reached while every frame was the welcome screen; the welcome copy mentions all
three. Screen matching is now per visual state, so prose can no longer
manufacture a row here.

## Design review

The captured frames are the review surface: every run uploads the full
`walkthrough-<flavor>-NN.png` sequence, and the docs importer publishes them as a
per-desktop walkthrough. Reviewing those side by side is how we judge whether a
frontend is not just *working* but *coherent* — consistent wording, sane
defaults, no truncated labels — which no automated check can settle.
