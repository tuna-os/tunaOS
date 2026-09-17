# Installer frontends — verification & parity

TunaOS ships **five installer frontends**, forked independently, one per desktop:

| Desktop | Flatpak app id | Upstream |
|---------|----------------|----------|
| KDE | `org.tunaos.InstallerKde` | fork of bootc-installer |
| COSMIC | `org.tunaos.InstallerCosmic` | fork of bootc-installer |
| Niri | `org.tunaos.InstallerNiri` | fork of bootc-installer |
| XFCE | `org.tunaos.InstallerXfce` | fork of bootc-installer |
| GNOME | `org.bootcinstaller.Installer` | upstream, unmodified |

The four TunaOS-forked frontends (KDE, COSMIC, Niri, XFCE) all drive the same
backend (**fisherman**, via `recipe.json`). GNOME uses upstream
bootc-installer without modifications, and it has its own disk backend
(see §3–§5 below). The UIs are
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

Checks 3–5 come from `scripts/installer-walkthrough.py`. It drives the UI with
QEMU `sendkey` (compositor-agnostic — no ydotool/Wayland tooling in the guest).
It screendumps each screen, and emits TAP plus `walkthrough-<flavor>.json`.

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
window"*, and the two have already diverged. On the cosmic leg, the installer
ran but no window ever appeared, and check 2 stayed green. Only a human who
looked at a screenshot caught it.

Checks 3–5 would have caught it too, but they need a compositor that renders.
Also, cosmic, niri, xfwl4 and kwin_wayland all need a DRM render node that
GitHub-hosted runners do not have. On exactly the runners where this matters
most, the checks that depend on a drawn frame cannot run.

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

cosmic is weaker because libcosmic builds on iced-on-wgpu and offers no `map`
equivalent — `first-frame` is the strongest claim it can honestly make. The
smoke test reports it instead of a failure. If the test rejected it, the test
would fail the one frontend this check exists for. An **unrecognised** value
does fail, because that means a frontend invented a claim the workflow has not
reasoned about.

If the workflow flattens these into one boolean, the check can believe that a
frame callback proves a mapped window. That happens on the frontend whose
window never appeared.

The stamp is best-effort in every frontend: one that cannot write it must still
install. Observability must not be able to take down the installer.

### Rendering caveat (why strictness differs per desktop)

**niri** and **xfwl4** are Smithay compositors that strictly need
`EGL_EXT_device_drm`. QEMU's plain `virtio-gpu` does not provide it, so on a
GPU-less CI runner they render *nothing* — legitimately blank (see
`docs/LUKS-TPM.md` and the virgl path in `scripts/iso-e2e.sh`). So checks 3–5
are **enforced** for kde/cosmic/gnome in CI and **recorded but not enforced**
for niri/xfce. Full-matrix enforcement runs on a host with a real GPU
(`TBOX_E2E_GPU=virgl`), where every frontend can draw.

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

Required screens fail the build for that frontend. The workflow records the
optional ones, so drift is *visible* before we promote them to required.

## Behavior contract

The screen contract above only covers *what renders*. Because the frontends
share no code, each frontend reimplements five more behaviors. Three of them
(§3–§5) apply to the four TunaOS-forked frontends only (Rust, C++, Go, Python
— GNOME/bootc-installer does not participate, see §3's note). The other two
(§1–§2) apply to all five frontends, and that count includes upstream
bootc-installer. These are the contracts those implementations must agree on,
and a parity check (and a sixth frontend) must follow them. Filed as
[#1197](https://github.com/tuna-os/tunaOS/issues/1197).

### §1 Readiness stamp

A machine-readable record that the UI came up, read by
`installer-smoke.yml` over SSH (no GPU, no OCR needed). Written once, on first
presentation, to `$XDG_RUNTIME_DIR/tuna-installer-ready` (a per-user tmpfs, so a
reboot always clears a stale stamp). Write is best-effort: a frontend that
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

Do **not** flatten these into one value. A smoke test that cannot distinguish
them would report the COSMIC frontend's `first-frame` as proof of a mapped
window. That is the exact failure mode the test exists to catch.

### §2 Product-name resolution

Which product this ISO is, for the welcome screen. Each variant bakes its
name into `PRETTY_NAME` (see `build_scripts/90-image-info.sh`); the GNOME
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
in its source. It owns its own logic for disk partitions and encryption, and it
is out of scope for §3–§5's contracts. Only §1 (readiness stamp) and §2
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
  `#` comments allowed) plus default `/usr/share/tuna-installer/oci-store`.
  The frontend removes duplicates and keeps only the dirs that exist
  (§4B conventions);
- **Available images**: `podman images --root <store>`; the frontend marks
  each catalog entry whose imgref is present as `[available offline]`;
- **Live-ISO image**: `bootc status --json` → booted image ref, non-empty only
  when `/proc/cmdline` carries `rd.live.image` (or `/run/ostree-live` exists).
  When live, the recipe may omit `image` (bootc installs the container that
  runs now).

### §5 Encryption / LUKS policy

The backend defines the encryption modes (fisherman recipe
`Validate()`), not the frontends — frontends must present exactly these ids
and nothing else:

| id | Meaning |
|----|---------|
| `none` | no encryption |
| `luks-passphrase` | LUKS with user passphrase |
| `tpm2-luks` | LUKS keyed to TPM2 |
| `tpm2-luks-passphrase` | LUKS with TPM2 + passphrase |

Anything else (e.g. a bare `luks`) fails recipe validation. A frontend that
reads a recipe's `encryption` value must accept exactly these four ids. It must
then show the matching UI, or omit the step explicitly and report it. KDE now
has no encryption screen; that gap is visible in the parity matrix below.

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

`scripts/installer-walkthrough.py` fills the matrix above, and it needs a
virgl-capable host. That is why Niri and XFCE read `_GPU_`: nobody has **ever
evaluated them**. Two crash-on-launch bugs, plus a 93%-white screen, survived
in that gap. A blank cell and a cell that passes look identical to a
reader.

Each frontend repo now also runs an offscreen screenshot capture on a stock
runner and emits the same `walkthrough-<flavor>.json`.
`scripts/import-frontend-parity.py` imports those into the table below.

**The two sources are not interchangeable, and are deliberately not merged.**
An offscreen capture drives the wizard's pages in-process. So it cannot observe
the three things that the first columns above measure.

First, that the flatpak launches under the real desktop. Second, that a GL-less
compositor can draw it — precisely where we suspect Niri and XFCE fail. Third,
that a keypress advances the wizard (KDE's `enter` defect is invisible to it by
construction). To fold a `✅ᶜ` into a `✅` would claim coverage nobody has, which
is a worse failure than the blank cells it replaces. So the import fills the
screen columns only, and tags them.

<!-- BEGIN GENERATED — scripts/import-frontend-parity.py -->

| Frontend | Source | welcome | disk | encryption | summary | install | done |
|----------|--------|---------|------|------------|---------|---------|------|
| KDE | [capture](https://github.com/tuna-os/tuna-installer-kde/actions/runs/33746041451) | ✅ᶜ | ✅ᶜ | ✅ᶜ | ✅ᶜ | ✅ᶜ | ✅ᶜ |
| COSMIC | — | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ |
| Niri | [capture](https://github.com/tuna-os/tuna-installer-niri/actions/runs/32732384359) | ✅ᶜ | ✅ᶜ | ✅ᶜ | ✅ᶜ | ✅ᶜ | ✅ᶜ |
| XFCE | [capture](https://github.com/tuna-os/tuna-installer-xfce/actions/runs/33726957852) | ✅ᶜ | ✅ᶜ | ⬜ᶜ | ✅ᶜ | ✅ᶜ | ✅ᶜ |

ᶜ = GPU-less offscreen capture in the frontend's own repo.
**It attests to screen parity only.** It drives pages in-process.
So it cannot observe three things: whether the app launches under
the real desktop, whether a compositor without GL can draw it, or
whether a keypress advances the wizard. The first three columns of
the matrix above stay the job of the VM walkthrough, and a green
row here does not replace one.

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
supports encryption. An earlier run reported `encryption: reached`, because the
matcher hit the string "Encryption: None" in the summary page's field
list. The keywords now match headings instead of bare nouns, so this shows as
the genuine feature gap it is. This is precisely the drift the matrix exists
to expose, and the matcher hid it.

**Status update (tuna-os/tunaOS#734).** Fixed since this run.
[tuna-installer-kde#6](https://github.com/tuna-os/tuna-installer-kde/pull/6)
adds a new `EncryptionPage` (the same four choices, wired between disk-select
and confirm), and it is live on `main`. Left as ❌ above, and not flipped, for
the same reason as COSMIC's row: no walkthrough run has re-measured it since.

Nobody has measured `install` and `done`: the walkthrough stops before it
starts a real install, by design.

### COSMIC — run 29684495194 (yellowfin, strict)

**The process runs but no window ever appears.** The compositor+frontend gate
passes (`flatpak ps` matches `org.tunaos.InstallerCosmic`), yet every frame is
the bare COSMIC desktop. Between frame 00 and frame 08, six minutes apart, the
only thing that changes is the clock. 0/8 transitions, 1 visual state, and OCR
matched no screen at all — not even `welcome`. Filed as
tuna-os/tuna-installer-cosmic#4.

This exposed a flaw in check 3. It was called "installer renders actual
content", but it measured stddev over the **whole framebuffer**. So a booted
desktop with no installer window passes it — cosmic scored 9/9. It is now named
"screen is not blank", which is what it measures. Checks 4 and 5 are the ones
that prove the compositor mapped the installer window, and here they correctly
failed.

The walkthrough now also prints an explicit diagnosis when the gate
passed but nothing advanced and no screen matched. Before, it left six
identical "not reached" lines to interpret.

**Status update (tuna-os/tunaOS#734).** Two things have moved since this run,
neither of which changes the row above yet:

- The encryption picker itself is done.
  [tuna-installer-cosmic#20](https://github.com/tuna-os/tuna-installer-cosmic/pull/20)
  (merged) ports XFCE's four-choice `ENCRYPTION_CHOICES` value-for-value. It
  uses the same `/sys/class/tpm/tpm0` TPM gate, and adds a Continue-button
  validation gate that XFCE does not even have. Nothing blocked this work
  except the window bug below, which had to let someone reach the Options page.
- A root-cause fix for the window bug is now open —
  [tuna-installer-cosmic#25](https://github.com/tuna-os/tuna-installer-cosmic/pull/25).
  `init()` called `offline::live_iso_image()` synchronously, which shells
  out to the host over flatpak-spawn. iced/libcosmic only creates the window
  *after* `init()` returns. So a slow or hung host call there is
  indistinguishable from "no window ever appears" — exactly this run's
  symptom. The fix defers it to a `tokio::task::spawn_blocking` + `Task`,
  matching the pattern already used elsewhere in `main.rs`. Reviewed in
  detail; the diagnosis and fix both look correct on read-through.

**Why the parity matrix above still reads 0/8, not fixed.** #25's own CI
(`capture`/`screenshots`) passes. But that check runs the app's synthetic
capture-mode fixtures, which take a different branch and never call
`live_iso_image()`. So it cannot prove the real hang is gone.

One check caught this bug: `scripts/installer-walkthrough.py` drove a real QEMU
boot of a `*:cosmic` ISO (this run). That is the check that must go green
before this row moves off 0/8. Per this doc's own rule above, a cell should
say what someone genuinely measured. It must not say what a plausible fix
implies should now be true.

### KDE — run 29681255102 (yellowfin, strict)

First frontend measured end to end. It launches, and renders on all 9 frames.

**⚠️ Advances by space only.** Enter does nothing on any page. No button in
`tuna-installer-kde` is a Qt *default* button, and nothing handles
`Qt::Key_Return`, so a focused `QPushButton` responds to space alone. That is a
real defect, not a harness artifact — a user with only a keyboard cannot leave
the welcome screen. Filed as tuna-os/tuna-installer-kde#4. The walkthrough now
escalates `ret` → `spc` and reports which key worked, so this stays visible
and nobody can paper over it.

**Reached `welcome` and `disk` only.** The run stalled on Select Target Disk.
Focus starts in the disk list, and a fixed two tabs never reached *Continue*, so
space re-toggled the list. The driver now widens its focus search each time
a step produces no change. Until a run gets past that page, `encryption`,
`summary`, `install` and `done` are **unmeasured, not absent** — do not read the
❌ as "the frontend lacks these screens".

An earlier run (29675493401) reported `disk`, `encryption` and `install` as
reached while every frame was the welcome screen; the welcome copy mentions all
three. Screen matching is now per visual state, so prose can no longer
manufacture a row here.

## Design review

The captured frames are the review surface: every run uploads the full
`walkthrough-<flavor>-NN.png` sequence, and the docs importer then publishes
them as a per-desktop walkthrough. We review those side by side to judge
whether a frontend not only *works* but is also *coherent*. That means
consistent words, sane defaults, and no truncated labels — which no automated
check can settle.
