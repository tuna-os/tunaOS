# Matrix status — what is actually verified

**As of 2026-07-27.** Every cell below cites the run that proved it. Nothing
here is inferred: if a combination has never been exercised, it says so rather
than being left blank.

That distinction is the point of this document. Before it existed, "no result"
and "passing" looked identical from the outside, and three separate defects
survived for weeks because the absence of evidence read as evidence of absence.

| | Meaning |
|---|---|
| ✅ | A named run asserted it and passed |
| ❌ | A named run asserted it and failed |
| ⬜ | **Never tested.** Not a pass. Not a fail. No data at all. |

---

## 1. Scope: what each axis actually proves

Passing one axis says nothing about the others. This caught us out repeatedly,
so it is stated first.

| Workflow | Proves | Does **not** prove |
|---|---|---|
| **Build** | The image builds and pushes | That it boots |
| **LUKS E2E** | ISO boots, installs to an encrypted disk, the installed system boots and unlocks | That a desktop session starts, or that the installer GUI works — it drives fisherman over SSH |
| **Installer smoke** | The compositor starts, autologin works, the installer frontend is running | That the install completes |
| **Live overlay** | The live payload (installer flatpak, autologin, polkit) builds for that variant | That it works at runtime |

A variant can be green on LUKS E2E and still ship an ISO nobody can use, because
LUKS E2E never looks at the screen. `yellowfin:cosmic` was exactly that: LUKS
green on 2026-07-23, while the installer GUI had never once been observed.

---

## 2. LUKS E2E — 12 of 33 non-NVIDIA ISO cells green

Sources: run `29978067348` (2026-07-23, full sweep), run `30098218493`
(2026-07-24, sailfin), run `30198679407` (2026-07-26, `yellowfin:gnome`
re-confirmed on current `main`).

| Variant | gnome | kde | cosmic | niri | xfce |
|---|:--:|:--:|:--:|:--:|:--:|
| **yellowfin** | ✅ | ✅ | ✅ | ✅ | ✅ |
| **albacore** | ✅ | ✅ | ✅ | ✅ | ✅ |
| **bonito** | ❌ | ✅ | ❌ | ❌ | ✅ |
| **bonito-rawhide** | ❌ | ❌ | ❌ | ❌ | ❌ |
| **skipjack** | ❌ | ❌ | ❌ | ❌ | ❌ |
| **grouper** | ❌ | ❌ | — | ❌ | ❌ |
| **marlin** | ❌ | ❌ | — | — | — |
| **flounder** | ❌ | ❌ | — | — | — |
| **sailfin** | ❌ | ❌ | — | ❌ | ❌ |

`—` = no ISO built for that combination (`build_iso: false`).

**Every NVIDIA cell fails.** All 24 of them, across every variant. That is a
single systemic issue, not 24 issues, and it is the largest uniform block of red
in the matrix.

**Staleness warning:** apart from `yellowfin:gnome`, every result above predates
the 2026-07-26 fixes (#833, #836, #839, #844). They are the best available data,
not current data. A full sweep on `main` is the single highest-value thing that
could be run against this document.

---

## 3. Installer smoke — 4 of 57 cells have *ever* been tested

This is the sparsest axis and the one that matters most for a desktop ISO,
because it is the only workflow that checks a human could actually install.

Sources: run `29914643652` (2026-07-22), run `30191933429` (2026-07-26).

| Variant | gnome | kde | cosmic | niri | xfce |
|---|:--:|:--:|:--:|:--:|:--:|
| **yellowfin** | ⬜ | ❌ | ❌ \* | ✅ | ❌ |
| *all other variants* | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ |

`*` **cosmic is a CI artefact, not a product failure.** cosmic, niri and xfwl4
are Smithay compositors requiring `EGL_EXT_device_drm`, which GitHub runners
cannot provide and which has no software fallback. On a host with a DRM render
node the cosmic ISO boots, `cosmic-comp` runs, the full desktop comes up and the
installer launches — verified by hand on 2026-07-26 and photographed. CI cannot
reproduce that today; see §5.

**Coverage: 4/57 ≈ 7%.** Read the ⬜ column honestly — for 53 of 57 shipped ISO
combinations, nobody has ever confirmed the installer appears.

Current per-desktop state:

| Desktop | State | Blocker |
|---|---|---|
| niri | ✅ passes in CI | — |
| cosmic | ✅ works on GPU hardware | CI cannot host it (§5) |
| kde | ❌ | `plasmalogin.service` fails to start. #836 added the diagnostics; the reason is not yet known |
| xfce | ❌ | `xfwl4` panics: `Failed to find theme named Default` — missing xfwm4 theme data, `tunaos-packages#123` |

---

## 4. Live overlay — 37 tags published

Every non-NVIDIA ISO cell has an overlay except two:

| Missing | Cause |
|---|---|
| `albacore-xfce` | base image `ghcr.io/tuna-os/albacore:xfce` returns **404** — `build_image: true` but never published |
| `marlin-kde` | build fails with a registry blob read reset; retried twice, so no longer plausibly transient |

Resolved on 2026-07-26 (each was a distinct cause, not one bug):

| Cells | Was | Fixed by |
|---|---|---|
| `flounder`, `flounder-sid` | unguarded `glib-compile-schemas` (exit 127) | #833 |
| `grouper` ×4 | `useradd --uid 1000` collision (exit 4) | #833 |
| `sailfin` ×4 | `dbus-daemon` missing | #822 |
| `guppy` ×2 | flatpak missing from the Gentoo base | #839 — build-verified; **not yet confirmed against a published image** |

---

## 5. Known systemic gaps

**NVIDIA — 24 cells, all red.** Untouched. The single biggest uniform block.

**CI cannot test three of five desktops.** cosmic, niri and xfwl4 need a DRM
render node. GitHub runners have none, so on hosted CI the compositor never
starts — no configuration change alters this. `scripts/iso-e2e-gpu.sh` runs the
harness on a GPU host and is the intended answer; it currently has to be driven
by hand.

**Screenshots on the GPU path.** `screendump` returns `Error: no surface` once a
guest scans out through virgl, and attaching VNC does not rescue it — the VNC
*client* path does. `iso-e2e.sh` handles this as of #844; note that
`installer-walkthrough.py`, `run-walkthrough.sh` and the weekly screenshot
workflows still call `screendump` directly and will silently produce nothing on
a GPU host.

**Failures that look like successes.** Recurring shape, worth checking for in
any new harness code:

- `pgrep -f <pattern>` run via `bash -c` matches its **own** command line. The
  bracket trick (`[t]una-installer`) is the fix; `installer-smoke.yml` documents
  it and other call sites still do not use it.
- `gh pr checks` renders a **cancelled** run as `fail`. A superseded run is not
  a broken build.
- After a partial `workflow_dispatch`, a bare tag such as `guppy:base` may still
  point at the previous build. Check `org.opencontainers.image.version` before
  concluding anything from it.
- `install_available` skips unresolvable packages by design, so missing packages
  never fail a build. They surface only in
  `/usr/share/tunaos/missing-on-*.txt` inside the built image, which nothing
  reads on a schedule. Three package gaps were found this way in one morning:
  `tunaos-packages#120`, `#121`, `#122`.

---

## 6. Regenerating this document

None of it is automated; every table above was assembled from the API. To
refresh:

```bash
# LUKS E2E, per cell
gh run view <run-id> --repo tuna-os/tunaOS --json jobs \
  --jq '.jobs[] | select(.name|test("^LUKS ")) | "\(.conclusion)\t\(.name)"'

# Installer smoke, per flavor
gh run view <run-id> --repo tuna-os/tunaOS --json jobs \
  --jq '.jobs[] | select(.name|test(":")) | "\(.conclusion)\t\(.name)"'

# Published overlay tags
TOK=$(curl -s 'https://ghcr.io/token?scope=repository:tuna-os/live-overlay:pull' | jq -r .token)
curl -s -H "Authorization: Bearer $TOK" \
  https://ghcr.io/v2/tuna-os/live-overlay/tags/list \
  | jq -r '[.tags[] | select(test("^sha256-")|not)] | sort | .[]'

# The ISO matrix this is measured against
yq -r '.variants[] | .id as $v | .flavors[]
       | select(.build_iso == true) | "\($v)\t\(.id)"' .github/build-config.yml
```

A document assembled by hand goes stale the moment someone merges. Wiring these
queries into a scheduled job that rewrites the tables would be a better use of
an afternoon than updating them manually — and would remove the risk of this
page confidently asserting something that stopped being true a week ago.
