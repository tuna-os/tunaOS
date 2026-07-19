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
| 3 | **It renders** | grayscale stddev of each frame > 0.02 | blank window, crashed-on-start |
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
| KDE | _pending_ | _pending_ | _pending_ | _pending_ | _pending_ | _pending_ | _pending_ | _pending_ | _pending_ |
| COSMIC | _pending_ | _pending_ | _pending_ | _pending_ | _pending_ | _pending_ | _pending_ | _pending_ | _pending_ |
| Niri | _pending_ | _GPU_ | _GPU_ | _GPU_ | _GPU_ | _GPU_ | _GPU_ | _GPU_ | _GPU_ |
| XFCE | _pending_ | _GPU_ | _GPU_ | _GPU_ | _GPU_ | _GPU_ | _GPU_ | _GPU_ | _GPU_ |
| GNOME | _pending_ | _pending_ | _pending_ | _pending_ | _pending_ | _pending_ | _pending_ | _pending_ | _pending_ |

_GPU_ = needs a virgl-capable host to evaluate; blank on GPU-less CI is expected.

## Design review

The captured frames are the review surface: every run uploads the full
`walkthrough-<flavor>-NN.png` sequence, and the docs importer publishes them as a
per-desktop walkthrough. Reviewing those side by side is how we judge whether a
frontend is not just *working* but *coherent* — consistent wording, sane
defaults, no truncated labels — which no automated check can settle.
