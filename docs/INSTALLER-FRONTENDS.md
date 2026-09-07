# Installer frontends — verification & parity

TunaOS ships **five independently-forked installer frontends**, one per desktop:

| Desktop | Flatpak app id | Upstream |
|---------|----------------|----------|
| KDE | `org.tunaos.InstallerKde` | fork of bootc-installer |
| COSMIC | `org.tunaos.InstallerCosmic` | fork of bootc-installer |
| Niri | `org.tunaos.InstallerNiri` | fork of bootc-installer |
| XFCE | `org.tunaos.InstallerXfce` | fork of bootc-installer |
| GNOME | `org.bootcinstaller.Installer` | upstream, unmodified |

The four TunaOS-forked frontends (KDE, COSMIC, Niri, XFCE) all drive the same
backend (**fisherman**, via `recipe.json`); GNOME is unmodified upstream
bootc-installer with its own disk backend (see §3–§5 below). The UIs are
separate codebases regardless. **Feature drift is therefore the default
failure mode**:
a screen or recipe field wired up in one fork silently never lands in the others.
Nothing about "it built" or "it launched" catches that — this page does.

## What CI verifies, and how

`installer-smoke.yml` runs per desktop and checks, in order:

| # | Check | How | Catches |
|---|-------|-----|---------|
| 1 | **Desktop is up** | `pgrep -x` the exact compositor binary | greeter loops, TTY fallback |
| 2 | **Frontend launched** | `flatpak ps` matches the desktop's app id | wrong/missing frontend, autostart broken |
| 2b | **A window reached the screen** | readiness stamp in `$XDG_RUNTIME_DIR` | **a frontend that runs and shows nothing** |
| 3 | **Screen is not blank** | grayscale stddev of each frame > 0.02 | black screen, no GL, dead compositor |
| 4 | **It advances** | consecutive frames differ > 500px | stuck on one screen, modal error |
| 5 | **Which screens** | OCR each frame vs `tests/installer-screens.yaml` | **feature drift between forks** |

Checks 3–5 come from `scripts/installer-walkthrough.py`, which drives the UI with
QEMU `sendkey` (compositor-agnostic — no ydotool/Wayland tooling in the guest),
screendumps each screen, and emits TAP plus `walkthrough-<flavor>.json`.

Checks 1–2b are also available as a reusable TAP script:
`scripts/e2e-installer-gui-checks.sh`. It runs inside the live guest over SSH
(same transport as `scripts/e2e-smoke-checks.sh`) and is called automatically
by `scripts/iso-e2e.sh --ssh-only` when `FLAVOR` is set.

> **Historical note.** Check 2 used to be `pgrep -af "Installer|…"` run through
> `bash -c` — the pattern matched its own command line, so it passed
> unconditionally and never verified anything. Assertions that can match
> themselves are worse than no assertion: they read as green forever.

### The readiness stamp (check 2b)

Check 2 answers *"is the process alive"*. That is not *"did the user get a
window"*, and the two have already diverged: the cosmic leg ran the installer
with no window ever appearing and check 2 stayed green. A human looking at a
screenshot was the only thing that caught it.

Checks 3–5 would have caught it too — but they need a compositor that renders,
and cosmic, niri, xfwl4 and kwin_wayland all require a DRM render node that
GitHub-hosted runners do not have. On exactly the runners where this matters
most, the rendering checks are the ones that cannot run.

So each frontend says it itself, in
`$XDG_RUNTIME_DIR/tuna-installer-ready` — readable over SSH with no GPU and no
OCR. Inside the Flatpak sandbox the host sees it at
`/run/user/<uid>/app/<app-id>/`.

```
app_id=org.tunaos.InstallerKde
window=ApplicationWindow
signal=frame-swapped
mapped_at=1786215232.825
page=welcome
```

| Field | Meaning |
|-------|---------|
| `app_id` | Must match the desktop's expected frontend. The wrong frontend autostarting is silent otherwise — each desktop's entry comes from a different `desktop-*.sh` adapter. |
| `window` | The class that mapped. Not decoration: `bootc-installer` can present `BootcRamWindow`/`BootcCpuWindow`/`BootcUnsupportedWindow` instead of the wizard, and `flatpak ps` reports all of them as a healthy install. |
| `signal` | **How the stamp was earned** — see below. |
| `mapped_at` | Unix seconds, 3dp. |
| `page` | Wizard page showing at map time. `unknown` if unavailable — never a bare `page=`, which would parse as a page named `""`. |

#### `signal` — the five toolkits cannot make the same claim

| Value | Proves | Frontends |
|-------|--------|-----------|
| `frame-swapped` | A frame actually reached the compositor (`QQuickWindow::frameSwapped`). Strongest. | kde, niri |
| `gtk-map` | The widget was mapped (GTK `map`). | gnome/bootc-installer, xfce |
| `first-frame` | The toolkit asked for a frame. Proves the event loop runs; **not** that a surface was presented. | cosmic |

cosmic is weaker because libcosmic is iced-on-wgpu and offers no `map`
equivalent — `first-frame` is the strongest claim it can honestly make. The
smoke test reports it rather than failing it: rejecting it would fail the one
frontend this check exists for. An **unrecognised** value does fail, because
that means a frontend invented a claim the workflow has not reasoned about.

Flattening these into one boolean would let the check believe a frame callback
proves a mapped window — on the very frontend whose window never appeared.

The stamp is best-effort in every frontend: one that cannot write it must still
install. Observability must not be able to take down the installer.

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

## Behavior contract

The screen contract above only covers *what renders*. Five more behaviors are
reimplemented — three of them (§3–§5) across the four TunaOS-forked frontends
only (Rust, C++, Go, Python — GNOME/bootc-installer does not participate, see
§3's note), two of them (§1–§2) across all five including upstream
bootc-installer — because the frontends share no code. These are the
contracts those implementations must agree on — they are what a parity
check (and a sixth frontend) should be written against. Filed as
[#1197](https://github.com/tuna-os/tunaOS/issues/1197).

### §1 Readiness stamp

A machine-readable record that the UI really came up, read by
`installer-smoke.yml` over SSH (no GPU, no OCR needed). Written once, on first
presentation, to `$XDG_RUNTIME_DIR/tuna-installer-ready` (a per-user tmpfs, so a
stale stamp cannot survive reboot). Write is best-effort: a frontend that
cannot write its stamp must still install.

Format — one `key=value` per line, atomically written via temp file + rename:

| Field | Meaning | Allowed values |
|-------|---------|----------------|
| `app_id` | Flatpak app id of the frontend | `org.tunaos.Installer*` / `org.bootcinstaller.Installer` |
| `window` | window class that mapped | e.g. `ApplicationWindow`, `InstallerWindow` |
| `signal` | HOW the stamp was earned — the five frontends cannot all make the same claim | `gtk-map` \| `first-frame` \| `frame-swapped` |
| `mapped_at` | unix epoch, seconds with ms precision (`%.3f`) | float |
| `page` | wizard page showing at map time; `unknown` when absent | slug |

Signal semantics (strictest claim first):

| Value | Claim | Frontends |
|-------|-------|-----------|
| `gtk-map` | widget was actually mapped by the compositor | bootc-installer, tuna-installer-xfce |
| `frame-swapped` | a frame was swapped to the compositor | tuna-installer-kde, tuna-installer-niri |
| `first-frame` | the toolkit asked for a frame; strictly weaker (proves event loop, not a mapped surface) | tuna-installer-cosmic (libcosmic is iced-on-wgpu, no `map` equivalent) |

Do **not** flatten these into one value: a smoke test that cannot distinguish
them would report the COSMIC frontend's `first-frame` as proof of a mapped
window — the exact failure mode it exists to catch.

### §2 Product-name resolution

Which product this ISO is, for the welcome screen. Per-variant branding bakes
the name into `PRETTY_NAME` (see `build_scripts/90-image-info.sh`); the GNOME
frontend reads it, so a Skipjack ISO must say "Welcome to Skipjack", never a
hardcoded "TunaOS".

Resolution order (host first — inside the flatpak sandbox `/etc/os-release`
describes the *runtime*, not the live ISO):

1. `/run/host/etc/os-release` → `PRETTY_NAME`
2. `/etc/os-release` → `PRETTY_NAME`
3. fallback constant `TunaOS` (developer checkout / CI / non-tunaOS host)

Resolved once and cached: the value cannot change while the installer runs.
A harness override may exist for screenshot capture, but must be explicit.

§3–§5 below describe the four TunaOS-forked frontends (KDE, COSMIC, Niri,
XFCE) — the ones that drive fisherman via `recipe.json`. GNOME
(`org.bootcinstaller.Installer`) is upstream bootc-installer, unmodified: a
repo search turns up zero references to `fisherman` or `recipe.json` anywhere
in its source. It owns its own disk-partitioning and encryption logic and is
out of scope for §3–§5's contracts; only §1 (readiness stamp) and §2
(product-name resolution) apply to it, and both already list it in their
tables above.

### §3 Privilege escalation

How the frontend runs **fisherman** (the backend that partitions a disk). The
live ISO symlinks the flatpak-bundled fisherman to `/usr/local/bin` and installs
the polkit policy for it (`customize-live.sh`); flatpak runtimes ship no
`pkexec`, so escalation happens host-side:

| Context | Command |
|---------|---------|
| inside flatpak sandbox | `flatpak-spawn --host pkexec /usr/local/bin/fisherman` |
| outside flatpak | `sudo /usr/local/bin/fisherman` |

Any host-side execution from inside the sandbox goes through
`flatpak-spawn --host`. The user must be able to distinguish an installer that
is about to touch a disk — no silent privilege drops.

### §4 Offline / live-ISO detection

- **In-sandbox detection**: presence of `/.flatpak-info`;
- **Offline store roots**: `$TUNA_OFFLINE_STORES` (colon-separated, when
  set) plus file `/etc/tuna-installer/offline-stores` (one path per line,
  `#` comments allowed) plus default `/usr/share/tuna-installer/oci-store`
  — deduplicated, existing dirs only (§4B conventions);
- **Available images**: `podman images --root <store>`; the frontend marks
  catalog entries whose imgref is present as `[available offline]`;
- **Live-ISO image**: `bootc status --json` → booted image ref, non-empty only
  when `/proc/cmdline` carries `rd.live.image` (or `/run/ostree-live` exists).
  When live, the recipe may omit `image` (bootc installs the running
  container).

### §5 Encryption / LUKS policy

The encryption modes are defined by the backend (fisherman recipe
`Validate()`), not by the frontends — frontends must present exactly these ids
and nothing else:

| id | Meaning |
|----|---------|
| `none` | no encryption |
| `luks-passphrase` | LUKS with user passphrase |
| `tpm2-luks` | LUKS keyed to TPM2 |
| `tpm2-luks-passphrase` | LUKS with TPM2 + passphrase |

Anything else (e.g. a bare `luks`) fails recipe validation. A frontend that
reads a recipe's `encryption` value must accept exactly these four ids and show
the matching UI — or explicitly omit the step and report it (KDE currently has
no encryption screen; that gap is visible in the parity matrix below).

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

### Screen parity from GPU-less capture

The matrix above is filled by `scripts/installer-walkthrough.py`, which needs a
virgl-capable host. That is why Niri and XFCE read `_GPU_`: they have **never
been evaluated**, and two crash-on-launch bugs plus a 93%-white screen survived
in that gap — because a blank cell and a passing cell look identical to a
reader.

Each frontend repo now also runs an offscreen screenshot capture on a stock
runner and emits the same `walkthrough-<flavor>.json`.
`scripts/import-frontend-parity.py` imports those into the table below.

**The two sources are not interchangeable, and are deliberately not merged.**
An offscreen capture drives the wizard's pages in-process, so it cannot observe
the three things the first columns above measure: that the flatpak launches
under the real desktop, that a GL-less compositor can draw it — precisely what
Niri and XFCE are suspected to fail — or that a keypress advances the wizard
(KDE's `enter` defect is invisible to it by construction). Folding a `✅ᶜ` into
a `✅` would claim coverage nobody has, which is a worse failure than the blank
cells it replaces. So the import fills the screen columns only, and tags them.

<!-- BEGIN GENERATED — scripts/import-frontend-parity.py -->

| Frontend | Source | welcome | disk | encryption | summary | install | done |
|----------|--------|---------|------|------------|---------|---------|------|
| KDE | [capture](https://github.com/tuna-os/tuna-installer-kde/actions/runs/33746041451) | ✅ᶜ | ✅ᶜ | ✅ᶜ | ✅ᶜ | ✅ᶜ | ✅ᶜ |
| COSMIC | — | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ |
| Niri | [capture](https://github.com/tuna-os/tuna-installer-niri/actions/runs/32732384359) | ✅ᶜ | ✅ᶜ | ✅ᶜ | ✅ᶜ | ✅ᶜ | ✅ᶜ |
| XFCE | [capture](https://github.com/tuna-os/tuna-installer-xfce/actions/runs/33726957852) | ✅ᶜ | ✅ᶜ | ⬜ᶜ | ✅ᶜ | ✅ᶜ | ✅ᶜ |

ᶜ = GPU-less offscreen capture in the frontend's own repo.
**It attests to screen parity only.** It drives pages in-process,
so it cannot observe whether the app launches under the real
desktop, whether a GL-less compositor can draw it, or whether a
keypress advances the wizard — the first three columns of the
matrix above remain the VM walkthrough's job, and a green row
here is not a substitute for one.

- **KDE** — 6 pages, 6 passed the pixel audit, 5 transitions. Text from `qml-item-tree`.
- **COSMIC** — no parity report imported (no run carried a parity report).
- **Niri** — 6 pages, 6 passed the pixel audit, 5 transitions. Text from `widget-tree`.
- **XFCE** — 8 pages, 8 passed the pixel audit, 7 transitions. Text from `widget-tree`.

<!-- END GENERATED — scripts/import-frontend-parity.py -->

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

**Status update (tuna-os/tunaOS#734).** Fixed since this run —
[tuna-installer-kde#6](https://github.com/tuna-os/tuna-installer-kde/pull/6)
adds a new `EncryptionPage` (the same four choices, wired between disk-select
and confirm) and is live on `main`. Left as ❌ above rather than flipped, for
the same reason as COSMIC's row: no walkthrough run has re-measured it since.

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

**Status update (tuna-os/tunaOS#734).** Two things have moved since this run,
neither of which changes the row above yet:

- The encryption picker itself is done —
  [tuna-installer-cosmic#20](https://github.com/tuna-os/tuna-installer-cosmic/pull/20)
  (merged) ports XFCE's four-choice `ENCRYPTION_CHOICES` value-for-value, with
  the same `/sys/class/tpm/tpm0` TPM gating and a Continue-button validation
  gate that XFCE doesn't even have. This was blocked on nothing except the
  window bug below actually letting anyone reach the Options page.
- A root-cause fix for the window bug is open —
  [tuna-installer-cosmic#25](https://github.com/tuna-os/tuna-installer-cosmic/pull/25):
  `init()` was calling `offline::live_iso_image()` synchronously, which shells
  out to the host over flatpak-spawn; iced/libcosmic only creates the window
  *after* `init()` returns, so a slow or hung host call there is
  indistinguishable from "no window ever appears" — exactly this run's
  symptom. The fix defers it to a `tokio::task::spawn_blocking` + `Task`,
  matching the pattern already used elsewhere in `main.rs`. Reviewed in
  detail; the diagnosis and fix both look correct on read-through.

**Why the parity matrix above still reads 0/8, not fixed.** #25's own CI
(`capture`/`screenshots`) is green, but that check runs the app's synthetic
capture-mode fixtures, which take a different branch and never call
`live_iso_image()` — so it cannot prove the real hang is gone. What actually
caught this bug was `scripts/installer-walkthrough.py` driving a real QEMU
boot of a `*:cosmic` ISO (this run). That is the check that needs to go green
before this row moves off 0/8 — per this doc's own rule above, a cell should
say what has genuinely been measured, not what a plausible-looking fix implies
should now be true.

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
