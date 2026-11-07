# Confirmed Gate Failures

Back to the [index](README.md).

## Confirmed Gate Failures (2026-07-15)

All gates that fail share the same root cause — images built before the
`graphical.target` fix (commit `0c36e46`, pushed ~12:00 UTC):

| Workflow | Variant:Flavor | Mode | Error |
|----------|---------------|------|-------|
| Build Yellowfin | yellowfin:gnome | disk | `TUNAOS_DESKTOP_CONTRACT_OK` not emitted |
| Build Grouper | grouper:niri | disk | `TUNAOS_DESKTOP_CONTRACT_OK` not emitted |
| Publish Grouped ISOs | yellowfin (flagship) | ISO ready | `TUNAOS_LIVE_READY` not emitted + blank screen |
| LUKS E2E | yellowfin:kde | ISO → install | `flatpak: command not found` (separate root cause, see §1) |

Once we publish new images with the `graphical.target` fix, all three boot-gate
timeouts should resolve, if no NVIDIA-driver interaction from the §2 caveat occurs.

---

### 9. GHCR `permission_denied: write_package` on experimental variants

**Affected workflows:** `Build Flounder-sid` (`flounder-sid`), `Build Guppy` (`guppy`), `Build Sailfin` (`sailfin`), `Build Marlin` (`marlin`), `Build Flounder` (`flounder`), `Build Grouper` (`grouper`).

**Symptom:**
```
Error: writing blob: initiating layer upload to /v2/tuna-os/flounder-sid/blobs/uploads/ in ghcr.io: denied: permission_denied: write_package
```

**Root cause:**
A workflow pushes new container images for an experimental variant to GitHub Container Registry (`ghcr.io/tuna-os/<variant>`) for the first time. GitHub then automatically creates the package under the organization namespace. By default, a GHCR package that GitHub creates does NOT inherit write permissions for the repository's `GITHUB_TOKEN` from GitHub Actions workflows.

Even though `reusable-build-image.yml` declares `permissions: packages: write`, GitHub Container Registry applies its own access controls for each package. If the `tuna-os/<variant>` package settings do not explicitly grant access for Actions to `tuna-os/tunaOS`, `podman push` fails with `permission_denied: write_package`.

**Resolution (GitHub Org Admin / Package Owner Settings):**
For each variant package published to `ghcr.io/tuna-os/<package>`:
1. Navigate to **GitHub Org (`tuna-os`) → Packages → `<variant>`** (or `https://github.com/orgs/tuna-os/packages/container/<variant>/settings`).
2. Scroll to **Manage Actions access**.
3. Click **Add repository**, search for `tuna-os/tunaOS`, and set role to **Write**.
4. Save changes.

Applies to all experimental variant packages: `flounder-sid`, `flounder`, `guppy`, `sailfin`, `marlin`, `grouper`.

---

### 10. `bonito-rawhide` build failures (Quay CDN flakes & desktop contract gate failures)

**Affected workflows:** `Build Bonito Rawhide` (`bonito-rawhide`).

**Symptom 1 (EOF during the base image pull):**
```
Error: pulling image quay.io/fedora/fedora-bootc:rawhide: unexpected EOF / CDN blob transfer dropped mid-pull
```
**Symptom 2 (failure of the desktop contract gate):**
```
ERROR: desktop experience contract marker was not emitted
==> Screenshot 10-ready stddev=0
```

**Root cause & Mitigations:**
1. **Blob drop at the Quay CDN:** `reusable-build-image.yml` includes an explicit retry loop of 4 tries with exponential backoff (`sudo podman pull --platform "${PLATFORM}" "$BASE"`) before it calls `just build`. If `quay.io` drops a blob transfer, local podman retries the pull, and the job does not fail.
2. **Desktop contract gate / Rawhide desktop breakage:** Rawhide packages the development builds of Fedora as they roll. Desktop packages in Rawhide break temporarily, the defaults of the display manager change, or systemd target initialization changes. The boot gate in `reusable-build-image.yml` then times out as it waits for `TUNAOS_DESKTOP_CONTRACT_OK`.
   - Gate artifacts (`serial.log`, `10-ready.png`) go to the Actions run. They provide the evidence to identify the cause: display manager startup (`gdm`, `greetd`, `sddm`), missing systemd units (`graphical.target`), or package breakage.
   - The published ISO matrix (`publish-iso-groups.yml`) automatically skips `bonito-rawhide` tags that fail or never publish, via `#674`. A broken Rawhide build therefore does not block the release of stable ISOs.

---

### 11. Podman/crun cache mount options rejected (`rw + bind conflict`)

**Affected workflows:** `LUKS E2E`, Containerfile builds that use `--mount=type=cache,rw,...` options.

**Symptom:**
```
resolving mountpoints: invalid options "rw, shared, rw, bind", can only specify 1 'rw' or 'ro' option
```

**Root cause:**
Older versions of `crun` / `podman` on certain runner environments (e.g. third-party or legacy GitHub runners) have a bug in how they parse mounts. The bug appears when a build passes explicit `rw` options to `--mount=type=cache,rw,...`. Because `type=cache` mounts default to read-write (`rw`) mode automatically, an explicit `rw` flag makes `crun` concatenate duplicate `rw` flags (`rw, shared, rw, bind`), and `crun` then rejects the mount initialization.

**Fix & Prevention:**
1. **Omit explicit `rw` in cache mounts**: In Containerfiles or build scripts, omit the redundant `rw` modifier from buildah/podman cache mounts. For example, use `--mount=type=cache,id=...` instead of `--mount=type=cache,rw,id=...`.
2. **Runner `crun` version alignment**: Make sure that the runner environments for GitHub Actions update `crun` to `v1.14.1+`. In that version, the parser for mount options removes duplicates from the default access modes.

---

### 12. Installer Walkthrough Automation & Frontend Drivers (#577)

**Affected workflows:** `Installer Walkthrough / Screenshots` (`installer-screenshots.yml`), `Installer Smoke` (`installer-smoke.yml`).

**Symptom:**
```
Drift in fixed-sleep sendkey choreography (ret/tab/tab/ret) causing screenshot capture drift or installer navigation failure across different desktop frontends.
```

**Root cause & Modernized Driver Design:**
1. **Drift in the blind sendkey choreography**: GUI installers change screen layouts or load times. Fixed sleeps (`sleep 45/60/60`s) and a fixed count of keys then break. The installers here are `bootc-installer` and the per-desktop `org.tunaos.Installer*` forks.
2. **State-aware step driver**: Replaced blind choreography in `scripts/run-walkthrough.sh` with the state-aware driver in `scripts/installer-walkthrough.py`. It polls QEMU screendumps, detects framebuffer stabilization (hash/stddev delta), does OCR matching against `tests/installer-screens.yaml`, and advances screens dynamically (`welcome -> disk -> encryption -> summary -> install -> done`).
3. **Per-desktop frontend keymaps & assertions**: Frontends (`org.bootcinstaller.Installer`, `org.tunaos.InstallerKde`, etc.) declare per-desktop keymaps and screen contracts. The driver enforces assertions on framebuffer stddev for compositors that render with GL (GNOME, KDE, COSMIC). For virgl-dependent compositors (Niri, XFCE) it only records them.
4. **Hardened installed-disk gate**: After UI installation completes, `iso-e2e.sh --disk` boots `install-disk.qcow2` and injects the test passphrase. It then verifies both LUKS encryption and the desktop experience contract (`TUNAOS_DESKTOP_CONTRACT_OK`), and a failure stops the job.

---

### 13. Debian COSMIC Desktop Package Gap (`flounder:cosmic` & `flounder-sid:cosmic`) (#924)

**Affected variants:** `flounder:cosmic`, `flounder-sid:cosmic`.

**Symptom:**
```
flounder:cosmic exit=1 missing required command: cosmic-comp
flounder-sid:cosmic exit=1 missing required command: cosmic-comp
```

**Root cause:**
Debian 13 (Trixie), Sid (unstable), and experimental repos do not ship COSMIC desktop packages (`cosmic-comp`, `cosmic-session`, etc.) natively in Debian archives. The `manifests/desktops/cosmic.yaml` PPA declaration `ppa:hepp3n/cosmic-epoch` specifies `condition: ubuntu`, so Debian builds skip it and do not install Ubuntu binary packages with a skewed ABI. As a result, apt soft-fails missing package names, and the published container images have no compositor.

**Resolution Strategy & Upstream Packages:**
1. **Track for upstream DEB packages**: `tuna-os/tunaos-packages#152` is the original Debian-specific ask. `tuna-os/tunaos#964` tracks the comprehensive plan: widen every COSMIC recipe to Debian *and* Ubuntu, then publish them to our own apt repo. The plan then retires `ppa:hepp3n/cosmic-epoch` entirely, the same third-party dependency that also causes grouper:cosmic's failures.
2. **Concrete progress, verified 2026-08-09**: of the 14 COSMIC recipes, 5 are gate-proven for both the `ubuntu` and `debian` Tideforge targets. They are `pop-icon-theme`, `cosmic-icon-theme`, `cosmic-randr`, `cosmic-panel` and `cosmic-comp` (`tunaos-packages` issues #204, #210, #214, #216). 4 of those 5 already reach `repo.tunaos.org/tideforge/<distro>/` through `tunaos-packages` `.github/workflows/publish-tideforge-debs.yml`, a matrix that we dispatch by hand and widen step by step. `cosmic-comp`'s publish entry hasn't landed yet, even though its gate has. The other 9 have no widened gate yet. They include `cosmic-session`, which must land last because it `Requires` the other ten. `manifests/desktops/cosmic.yaml`'s `apt:` block still points at the PPA and must stay that way until all 14 reach the repo. `cosmic-session`'s own recipe now ships with an intentionally empty `ubuntu`/`debian` runtime-`Depends` list for exactly this reason. To point `flounder`/`grouper` at that repo today would trade a PPA build that works for an apt failure on unsatisfiable `Depends`.
3. **Matrix Visibility**: The flavor remains declared in `.github/build-config.yml`, and post-publish contract sweeps (`desktop-contract-sweep.yml` / #921) report it as red. That keeps the state visible, instead of a silent reduction of matrix coverage. A rebuild after package updates will replace existing tags cleanly, with no destructive registry actions.

---

### 14. Promotion Criteria for Experimental Variants to Nightly Build Schedule (#641)

**Affected variants:** `grouper`, `marlin`, `flounder-sid`, `guppy`, `sailfin`, `flounder`.

**Policy & Criteria:**
An experimental variant (`experimental: true`) is eligible for promotion to the nightly build schedule (`schedule: cron: "0 1 * * *"`) once it meets the following criteria:
1. **Clean Image Build**: All declared DE/flavor stages build green without failures.
2. **ISO & Disk Boot Gate**: Some variants have `build_iso: true` (e.g. `grouper`, `marlin`). For those, the ISO build and QEMU disk boot gate (`iso-e2e.sh --disk`) complete cleanly and emit `TUNAOS_DESKTOP_CONTRACT_OK`.
3. **No Soft Failures / Missing Compositors**: The post-publish sweep of the desktop contract looks for essential commands (e.g. `niri`, `cosmic-comp`, `nautilus`, `sddm`). They must be present and functional.

**Variant Status & Promotion Record:**
- `grouper` (Ubuntu 26.04): Promoted once image and ISO e2e boot gates pass cleanly.
- `marlin` (Arch): Promoted once it passes image and ISO e2e gates.
- `flounder-sid` (Debian Sid): Promoted upon green image builds (no ISOs).
- `guppy` (Gentoo) & `sailfin` (openSUSE TW): Promoted upon green image builds following target-stage fixes.
- `flounder` (Debian Trixie): Stays experimental until ostree base requirements (`≥ 2025.3`) land.

---

### 15. Post-Publish Desktop Contract Sweep & Published Artifact Verification (#925)

**Affected workflows:** `Post-Publish Desktop Contract Sweep` (`desktop-contract-sweep.yml` / #921).

**Symptom & Defect Class:**
Published container images built green in CI but shipped missing essential desktop components:
- `flounder:niri`: Missing `niri` compositor (no apt branch).
- `sailfin:gnome`: Missing `nautilus`, file manager, keyring (minimal pattern skeleton).
- `flounder:cosmic` & `flounder-sid:cosmic`: Missing `cosmic-comp` (Debian skips the Ubuntu PPA condition).
- `grouper:gnome`: Missing `gnome-keyring` (absent from apt list).
- `KDE on PlasmaLogin`: The build skipped enablement of the display manager unit, because of a hardcoded DM name or base-stage timing.

**Root cause:**
1. **Gating of build-time checks against published artifacts**: Build-time checks run only during initial image assembly. They do not run against published registry tags on GHCR (`ghcr.io/tuna-os/*`). We could publish stale tags or un-gated apt builds despite missing binaries.
2. **Apt Soft Failures**: Package managers on apt paths didn't hard-fail on missing optional packages. They soft-skipped missing compositors or desktop utilities.

**Solution Architecture:**
1. **Scheduled Post-Publish Sweep (`desktop-contract-sweep.yml`)**: Executes `build_scripts/checks/verify-desktop-experience.sh` nightly against all 47 published matrix cells.
2. **Four explicit verdicts per cell**:
   - `pass`: Image pulled, verified, and satisfies the full desktop contract.
   - `fail`: Image pulled but fails required binary or unit assertions.
   - `missing`: No published image tag in registry.
   - `error`: Network or registry pull failure.
3. **Assertion on display manager enablement**: Verifies that the display manager units (`gdm`, `sddm`, `plasmalogin`, `greetd`) are actively enabled in the image layer. Presence as installed unit files is not enough.

---

### 16. A red LUKS E2E cell can be stale evidence, not a live bug (#979, 2026-08-09)

**Affected cells (as measured):** `yellowfin:gnome/kde/niri/cosmic`, `albacore:gnome/kde/cosmic` — all four/three shown red in `docs/MATRIX-STATUS.md` as of its 2026-08-08 snapshot.

**Symptom (identical across all six jobs checked):**
```
TUNAOS_LUKS_E2E_PASS encrypted=1 passphrase_unlock=1 installed_boot=1
TUNAOS_LUKS_E2E_DESKTOP_CONTRACT desktop_contract=ok fatal=0
TUNAOS_LUKS_E2E_PIXEL_GATE result=absent frames=<200-400> stddev=na fatal=1
ERROR: pixel gate FAILED — the encrypted install unlocked and reached
       login, but nothing provably rendered (...).
##[error]Process completed with exit code 6.
```
Encryption, unlock, boot and the in-guest desktop contract all genuinely passed — the *only* signal that fails is `scripts/lib/pixel-gate.sh`'s pixel gate, and specifically its `shot=absent` path.

**Root cause — not a new defect, a timing gap:** `scripts/lib/pixel-gate.sh` commit `e20fd037` (#1102, merged 2026-08-08T02:42 UTC) added exactly this case — `shot=absent` *and* `contract=ok` — as an advisory `absent_contract_ok` verdict (`fatal=0`). The evidence was `gurnard:pantheon` and `grouper:xfce`, which hit the identical pattern. Every one of the six job logs that fail here (`yellowfin:gnome` run 31226672079, `yellowfin:kde`/`niri`/`cosmic` same run, `albacore:gnome`/`kde`/`cosmic` runs 31224487929/31224494825) carries a timestamp **before** `e20fd037` landed. They ran the *old* pixel-gate logic, which had no `contract=ok` carve-out and fell through to the fatal `absent` branch instead. Nobody has re-dispatched these cells since the fix merged. So `MATRIX-STATUS.md`'s "35/52 green" — sourced from the newest available run per cell — reports genuinely stale verdicts for these six, not current ones.

**Lesson:** before you treat a red cell of LUKS E2E as an open bug to diagnose, check the evidence lines of the job that failed. Compare them against `git log` for `scripts/lib/pixel-gate.sh`, or for whatever check failed. `fatal=1` on an old run doesn't mean the current tree would still produce it. A cell only needs new investigation once it fails again on a run that started *after* the relevant fix.

**Action taken:** re-dispatched `LUKS E2E` (`workflow_dispatch`) for `variant=yellowfin,flavor=all` (run [31286843546](https://github.com/tuna-os/tunaOS/actions/runs/31286843546)) and `variant=albacore,flavor=all` (run [31286849405](https://github.com/tuna-os/tunaOS/actions/runs/31286849405)) to get fresh, post-fix verdicts. Not yet observed to completion — a multi-cell LUKS sweep runs well past a single investigation session. Check those runs' own conclusions before you decide that the cells are already green.

**Separate, still-open, NOT covered by the above:** `yellowfin:xfce` (same run, job 93022287474) fails during the **image build** itself — `dracut-install: ERROR: installing '/root'` plus `error: Linting: Checks failed: 2`, retried 3 times. It never reached the LUKS/pixel-gate stage at all. `albacore:gnome/kde/cosmic` log the identical `dracut-install`/lint messages during their own builds, but the build still *succeeds* there. Those messages are non-fatal, and they match the warn-only default that `bootc container lint` documents — see #10 above. So this is not "the same bug, sometimes fatal": `yellowfin:xfce`'s build genuinely dies and needs its own root-cause pass, not a re-dispatch.

---

### 17. A failing gate took its own evidence with it (`no_silent_omissions`, 2026-09-13)

**Affected workflow:** `Desktop Contract Sweep` (`desktop-contract-sweep.yml`), and every desktop cell in `docs/MATRIX-STATUS.md`.

**Symptom:** the silent-omissions section read `**0 of 51** cells clean (0 read, 51 never read)`. `.github/green-criteria.yml` marks `no_silent_omissions` as a blocker. A cell it cannot score never reaches green. So the composite table rendered every desktop cell ⬜, and the header undercounted by up to 51 cells.

**What made it hard to see:** the sweep measured everything. In run [34692178123](https://github.com/tuna-os/tunaOS/actions/runs/34692178123), 52 of 53 jobs succeeded. All 51 cell jobs pulled their published image, ran `verify-package-wishlist.sh`, and wrote a verdict. The status page said "never read" about images it had already read.

**Root cause — two couplings, and either one alone does it:**

1. The `Baseline` job ended with a completeness gate. That gate fails on any cell short of a pass. `upload-artifact` sat after it with no `if:`. When the gate went red, it skipped that upload, and `all.json` never reached the artifact.
2. `scripts/gen-matrix-status.py` accepted artifacts only from runs whose conclusion was `success`.

The gate trips whenever a cell goes red. That is the ordinary state of a matrix under repair. It had tripped nightly since 2026-09-09, on 28 desktop-contract cells that fail. Between the two couplings, the axis went dark for exactly the period that most deserved a reader.

**Fix (#2495):** the verdict and the evidence are separate things.

- The completeness gate is its own step, after the upload. It still fails on `fail + miss + err + lost > 0`, so the sweep goes red as often as before.
- The upload runs `if: always()`.
- The reader accepts `failure` beside `success`. It still refuses cancelled, skipped, timed-out and in-flight runs.

Trust is per artifact, not per conclusion. The table is built as `reconciled.json`. It becomes `all.json` only once the sweep's reconciliation accounts for every dispatched cell. So the file's presence in the artifact asserts that the totals add up. An unreconciled run publishes `baseline.md` alone, and the reader's existing `exists()` check skips it. The fix leaves the classification of each cell alone: missing, error and lost still score untested, never clean (#1730).

**Lesson:** when a status page says an axis has no measurement, ask whether the measurement ran and then went in the bin. A gate that publishes nothing on failure hides its own inputs. Keep the artifact upload ahead of the gate that judges it, and let the run's conclusion carry the verdict on its own.

---

### 18. A self-check that balances on both sides cannot see a doubling (2026-09-13)

**Affected workflow:** `Desktop Contract Sweep` (`desktop-contract-sweep.yml`), the `Baseline` job.

**Symptom:** the baseline printed totals for twice as many cells as the sweep has.

```
DESKTOP CONTRACT BASELINE: 80/102 pass, 20 fail, 2 no image, 0 error, 0 lost
```

The sweep dispatches 51 cells. Every count in that line, and every row count in `baseline.md`, was twice its true value for as long as the job has existed.

**Root cause:** each cell artifact carries `result.json` twice. One copy sits at the artifact root; `scripts/evidence-bundle.sh` writes the second into `evidence/<variant>/<flavor>/amd64/`. The collate step ran `find results -name result.json`, which matched both, so every cell entered the table twice.

**Why the job's own guard missed it.** That job already asserts its arithmetic:

```
if (( pass + fail + miss + err + lost != total )); then
  echo "::error::baseline does not reconcile: ..."
```

Double both sides and they still balance. `102 == 102` held on every run, and the check reported a healthy table while every number in it was wrong. The guard targets a real defect — cells that went missing, per the reconciliation comment in that step — and it catches that one. It cannot catch a cell counted twice, because two of a cell is not a shortfall.

**Fix (#2497):** exclude the evidence copy from the tally, and assert what the arithmetic structurally cannot.

```
find results -name result.json -not -path '*/evidence/*'
dupes=$(jq -r 'group_by(.cell)[] | select(length > 1) | .[0].cell' found.json)
```

A cell reported twice now fails the step by name. The evidence bundle still uploads: this changes what the tally reads, not what the artifact carries.

**How it surfaced.** Only #2495 made it visible. The baseline artifact had never reached a red run, so nobody could compare the published table against the 51 cell artifacts beside it. The first fix exposed the second defect.

**Lesson:** a check for internal consistency proves the parts agree with each other. It does not prove they agree with the world. So pin at least one number to something outside the computation — here, that a cell appears once. Otherwise a proportional error stays invisible for as long as it stays proportional.

---

### 19. versionlock hides a package, and no exclude probe will show it (`bonito:gnome-t2`, 2026-09-13)

**Affected script:** `build_scripts/overlay/hardware-profile.sh` (dnf kernel swap, formerly `t2.sh`), and any future kernel swap that installs packages under their stock names.

**Symptom:** four builds of `bonito:gnome-t2` died on the same line, with a message that names the wrong thing.

```
Failed to resolve the transaction:
No match for argument 'kernel' in repositories 'copr:…:sharpenedblade:t2linux'
```

**Root cause:** `build_scripts/10-base-packages.sh` runs `dnf versionlock add kernel kernel-core …` against the **installed** Fedora kernel. That pins `7.2.4-200.fc44` and excludes every other version, the COPR's `7.1.9-200.t2.fc44` among them. dnf says so plainly, but only once the transaction stops naming a repo:

```
Argument 'kernel-7.1.9-200.t2.fc44' matches only packages excluded by versionlock.
```

**Three traps, and each one cost a build.**

1. **A repo-scoped install reports the lock as an empty repo.** Under `--from-repo`, the only candidates come from that one repo. The lock excludes all of them, so dnf words the emptiness in terms of the pin. The pin is not the problem, and neither is the repo.
2. **`repoquery` and `install` disagree, honestly.** `repoquery --repo=<id> 'kernel*'` lists all 18 packages while `install --from-repo=<id> kernel` finds none — same id, same options, seconds apart in one job. `repoquery` does not apply versionlock's excludes. That gap reads like a broken flag and is not one.
3. **An exclude probe answers "(none)" and is right.** `grep -E '^(exclude|excludepkgs)=' /etc/dnf/dnf.conf /etc/yum.repos.d/` finds nothing, because versionlock keeps a list of its own. Run `dnf versionlock list` too, or the probe misses the filter in force.

**Why no earlier swap hit it.** This repo holds two other kernel swaps, and each one evades the lock by accident. `overrides/nvidia/10-kernel-swap.sh` bypasses dnf entirely with `rpm -ivh`. `overlay/asahi.sh` installs `kernel-16k`, a name the lock list does not carry. `t2` installs packages named exactly `kernel`, so it is the first swap the lock bites.

**Fix (#2498):** release the lock, swap, then re-apply it to the kernel that was installed. Release every name `10-base-packages.sh` locks, or a straggler holds one package and the transaction fails on that alone. Re-application matters as much as release. `10-kernel-swap.sh` gives the reason after its own swap: a later transaction that pulls a different kernel would undo the whole point of the script.

**Lesson:** "no match for argument" means the solver had no candidate. It does not mean the repo lacks the package. So before you doubt the repo, the id, or the flag, ask what filters the candidate set — `dnf.conf`, the `.repo` files, **and** `dnf versionlock list`. Two dnf subcommands can also disagree about the contents of a repo. When they do, suspect a difference in the filters that each of them applies. Call either of them broken only after that.

---

### 20. A scriptlet can fail without failing the transaction (`bonito:gnome-t2`, 2026-09-13)

**Affected script:** `build_scripts/overlay/hardware-profile.sh` (dnf kernel swap, formerly `t2.sh`), and any overlay that installs a kernel with dnf.

**Symptom:** the image built, signed, and passed the desktop contract. Two jobs later the boot gate panicked.

```
Kernel panic - not syncing: VFS: Unable to mount root fs on unknown-block(0,0)
CPU: 2 UID: 0 PID: 1 Comm: swapper/0 Not tainted 7.1.9-200.t2.fc44.x86_64
```

**Root cause:** the image carried no initramfs. `kernel-core`'s `%posttrans` runs `rpm-ostree kernel-install`, which calls dracut. `/boot` is a tmpfs mount in `Containerfile.overlay`, dracut stages its output in the default tmpdir, and the rename into `/boot` crosses a filesystem boundary:

```
>>> Generating initramfs
>>> error: rpm-ostree kernel-install: Adding kernel: Running dracut:
    Invalid cross-device link (os error 18)
```

**The part that cost the cycle:** dnf called that transaction a success. The scriptlet failed, the message went to the log, and the exit status stayed 0. So the build went green with a kernel and no way to mount root. The first sign of trouble arrived at the boot gate: a different job, a different log, and a symptom that points at the kernel. The install that produced it looks innocent.

**Fix (#2500):** `TMPDIR=/boot` on the install, so dracut's rename stays on one filesystem. Then build the initramfs again, explicitly, into `/lib/modules/<kver>/`, which is part of the image; `/boot` is a tmpfs and does not survive the build. `overrides/nvidia/10-kernel-swap.sh` met the identical EXDEV and its comment is where both halves come from.

Then assert the result. A missing initramfs, or one too small to hold the root storage drivers, now fails the build at the step that creates it:

```
ERROR: no initramfs at /lib/modules/<kver>/initramfs.img after the swap
```

**Lesson:** a green dnf transaction means dnf resolved and installed. It does not mean every scriptlet succeeded. When a package's `%post` or `%posttrans` builds something the image needs, check for that artefact yourself. Otherwise the first report you get is the symptom, in a later job, and it points somewhere else.

---

### 21. An unbounded wait makes every check below it unreachable (2026-09-13)

**Affected script:** `build_scripts/checks/verify-base-contract.sh`, and any gate that waits on a machine before it judges the machine.

**Symptom:** the boot gate reports a timeout and the serial log carries no verdict at all.

```
Starting tunaos-base-contract.service - Verify TunaOS base boot contract...
[ 314.604325] tunaos-base-contract.service: start operation timed out. Terminating.
[ 314.635751] Failed to start tunaos-base-contract.service
```

Between those two lines the contract printed nothing. It had run for the unit's whole `TimeoutStartSec` and died mid-call.

**Root cause:** the contract opened with `systemctl is-system-running --wait`. That call returns when startup reaches a terminal state, and a machine whose startup never settles never reaches one. The wait had no bound, so the unit's timeout became the bound.

**The expensive part:** every check after that line was unreachable on exactly the images those checks exist to judge. The contract asserts `bootc status`. It also asserts that the system message bus is alive. #2484 added that check for `skipjack`, whose dbus-broker dies on an SELinux denial and takes the bus down with it. That is the same class of machine whose startup never settles, so the assertion written for the failure could never run on it. The gate said `timeout`; the defect had a name, and nobody heard it.

**First fix (#2501, #2506), now withdrawn:** bound the wait at 120s, then at 240s, and ask again without `--wait` when the bound expires. That turned a silent kill into a named verdict. It did not make the checks below reachable.

**The real cause (#2514):** the wait was on the unit's own job, so no bound can be correct. Three facts close the loop:

- `systemctl is-system-running --wait` returns when the manager leaves `starting`.
- The manager leaves `starting` when the initial boot transaction completes.
- `tunaos-base-contract.service` is `Type=oneshot` and `WantedBy=multi-user.target`, so its job is in that transaction until the script exits.

The contract waited for a state that the contract itself held back. The serial log shows it. On `hummingbird:gnome`, `Startup finished` came 10-14 ms after the wait gave up, at both bounds:

| bound | wait gave up | `Startup finished` | userspace |
|---|---|---|---|
| 120s | `133.320660` | `133.334844` | 2min 7.074s |
| 240s | `252.338862` | `252.351227` | 4min 7.191s |

The userspace time tracked the bound, not the image. The value "2min 7s" looked like a slow image, and it caused the move to 240s. That move doubled the value.

Desktop cells lost the verdict in a different way. `scripts/iso-e2e.sh` sees `TUNAOS_DESKTOP_CONTRACT_OK` and stops the VM while the base contract is still in the wait:

```
[ 30.170663] systemd[1]: tunaos-base-contract.service: Main process exited, code=killed, status=15/TERM
```

That is `bonito:gnome-t2`, run 34768771243. So no cell ran `bootc status` or the system-bus check.

**Fix (#2514):** take one sample of the state and do not wait. `checks/e2e-runtime-checks.sh` already samples this way.

| state | verdict |
|---|---|
| `maintenance`, `stopping`, `offline`, no answer | fail |
| `initializing`, `starting` | pass; the unit starts after `multi-user.target`, so multi-user was reached |
| `running`, `degraded` | pass |

The contract also prints the names of the failed units in a `TUNAOS_BASE_CONTRACT_NOTE` line. That line is evidence, not a verdict. `TUNAOS_SETTLE_WAIT_SECONDS` and its bound tests are gone. `tests/bats/test_no_settle_wait_inside_boot_transaction.bats` finds each script that a boot unit starts, and fails if one of them waits on `is-system-running`.

**Lesson:** a gate that waits must bound the wait, and #2501 was correct about that. But first make sure that the wait can end. A check that runs as a job in the boot transaction cannot wait for that transaction to complete. If a measured duration moves when you change the bound, the bound is the thing you measure.

### 22. Two reports that both mistook silence for a verdict (2026-09-13)

**Affected scripts:** `.github/scripts/update-build-status.sh`, `scripts/gen-matrix-status.py`.

**Symptom:** the README snapshot gave `bonito` **1/16**. All sixteen bonito cells had promoted that day. All sixteen tags were live.

```
| 🎣 `bonito` | **1/16** | [✅ 2026-09-13](.../34768771243) | — | base,base-hwe,base-nvidia,
  gnome,cosmic,kde,niri,xfce,gnome-hwe,gnome-asahi,gnome-nvidia,cosmic-nvidia,
  kde-nvidia,niri-nvidia,xfce-nvidia |
```

**Root cause:** both scorers read one run per variant. Then they scored every cell from that run. `gen-matrix-status.py` stated the premise outright:

> a build run asserts its whole matrix at once, so the newest conclusive run IS the current state of every cell it scheduled

`build-<variant>.yml` accepts a flavor-filtered `workflow_dispatch`. One rebuild of one flavor breaks that premise. Run 34768771243 built `gnome-t2` alone. It then became the newest conclusive run. The fifteen cells it never scheduled scored "not reached".

The `Failing` column stayed empty. That was the tell. Nothing had failed. The table never mentioned those cells, and it read the silence as doubt.

**Fix:** score each cell from the newest conclusive run that asserted *that cell*. Walk runs newest first. Let the first conclusive Promote win, so a fresh failure beats an older success. Only a cell that no run asserted reaches further back. Read the Gate from the same run as the Promote, so one cell's `builds` and `boots` describe one image.

The walk stops once every flavor has a verdict. The ordinary case still costs one fetch.

Measured: `bonito` 1/16 → 16/16, `skipjack` 12/17 → 13/17, totals 112/139 → 128/138. No row lost a cell.

**That same day the drift gate on the same document failed from the other end.** `--check-structure` masks live content. It then compares a committed `MATRIX-STATUS.md` against a fresh one. CI churn must never fail a pull request. The gate failed #2512 on this line:

```
+N cell(s) in the most recent sweep are missing (no published image), errored
+(registry/runner trouble), or lost (job produced no result)...
```

A sweep finished between the commit and the check. It returned one `missing` cell. The generator then emitted a caveat paragraph that no committed copy could hold.

**The mask works line by line. A rewrite of a line cannot hide a line that one side lacks.** Every other live readout there is a line that always exists. Only its numbers move, so the mask covers it. Name a conditional paragraph in `VOLATILE_LINE` instead.

**Lesson:** a report claims what someone measured, and silence measures nothing. Ask two questions of every line you print. Did a run look at this cell? Might this line not print at all? A comparison that normalises what both sides hold will still fail on what one side alone holds.

### 23. A gate broke on prose that no diff ever showed (2026-09-14)

**Affected files:** `.github/scripts/update-build-status.sh`, `scripts/gen-matrix-status.py`, and the two documents they write.

**Symptom:** the STE ratchet failed on `main`, and on every pull request that touched a `.md` file. It stayed red for three days. The change behind it had passed that same gate.

```
2026-09-14T18:54 push         main                        failure
2026-09-15T11:08 pull_request automation/matrix-status    failure
2026-09-16T10:57 pull_request automation/matrix-status    failure
2026-09-17T01:58 pull_request strategy/q3-close-q4-...    failure
```

**Root cause:** STE lints `README.md` and `docs/MATRIX-STATUS.md`. Nobody writes either by hand. tunaOS#2512 edited the README paragraph inside `update-build-status.sh`, and the local STE run read 3048 — correctly, because the committed README still held the old sentence. Automation regenerated it two days later. The fresh sentence carried a filler word and a passive clause, so the total reached 3052 against a budget of 3050.

So the prose that STE reads had moved, and the diff behind it showed nothing. The gate had nothing to catch. The author had nothing to see.

The second cause needs no author at all. `gen-matrix-status.py` prints a caveat paragraph only while the newest sweep holds a cell with no clean verdict. One sweep result makes that paragraph appear, and the repo total moves on its own. That same paragraph had already broken the drift gate in §22, for the same reason from the other side.

**Fix.** Edit the generator and the committed file in one commit, so the linted bytes land in the diff. Keep a conditional paragraph short and active, because its cost falls on whoever opens the next pull request. `tests/test_generated_prose_is_visible_in_the_diff.py` holds the two in step.

**Never raise the budget to clear this.** It looks like a fix and it discards the ratchet. The prose was wrong. The number was right.

**Lesson:** ask what reads a file, not who writes it. A generator's output is source for every gate that measures it, and a generator's prose is prose. When a gate reads something your diff never showed, your green describes the old bytes.

### 24. Our own fix ran after the thing that needed it (`flounder:kde`, 2026-09-17)

`flounder:kde` and `flounder:kde-nvidia` produced no ISO on any run for two
weeks. The job died in tacklebox's embedded live baseline:

```
>>> [customize] (1/2) baseline.sh
useradd: cannot create directory /home
Error: live customize for flounder-kde: ... exit status 12
```

**Root cause.** Two scripts in this repo disagree, and neither is wrong alone.
`ostree-layout.sh` makes `/home` a symlink to `var/home`, then creates
`/var/home`, and says why: the targets must exist at build time, because later
layers probe the aliases. `99-cleanup.sh` then runs `find /var -mindepth 1
-maxdepth 1 -delete`, which removes it. It restores the dpkg and apt paths and
nothing else. So `/home` in the published image points at nothing.

**Who it hits.** Only the bases where cleanup runs after layout:
`Containerfile.arch`, `.debian` and `.gentoo`. The bases with no layout step
take their layout from the parent and never show it. The list identified the
failed cells exactly and confirmed the mechanism.

**Why nothing caught it.** tunaOS already carries this fix. `customize-live.sh`
holds `mkdir -p "$(readlink -f /home)"`, under a comment that describes this
exact failure. It is script 2/2. The baseline that needs it is script 1/2, and
tacklebox puts every `--script` after its embedded baseline. So the fix sat in
this repo and never ran before the code it protects.

**Fix.** Restore the `/var` alias targets in `99-cleanup.sh`, beside the dpkg
restore and for the same stated reason. The wipe stays. The `tmpfiles.d` entries
still own the runtime side.

**Lesson:** a fix has a position, not only a body. When a script fixes something
for its own callers, ask what runs before it. Ours was correct, tested and
inert, and the symptom pointed at another repository the whole time.

### 25. The same fix, written once, for one base out of two (`marlin:gnome` arm64, 2026-09-17)

`marlin:gnome` built an ISO on amd64 and died on arm64, in the same tacklebox
baseline as §24 but for a different reason:

```
>>> [customize] (1/2) baseline.sh
useradd: UID 1000 is not unique
Error: live customize for marlin-gnome: ... exit status 4
```

**Root cause.** tacklebox's baseline asks for `--uid 1000` and does not check.
marlin's arm64 legs build from `ghcr.io/tuna-os/archlinuxarm`, because
`docker.io/archlinux` is x86_64 only, and Arch Linux ARM ships its own account
there. Read from the published layer, not assumed:

```
alarm:x:1000:1000::/home/alarm:/bin/bash
```

`build-archlinuxarm-base.yml` keeps it on purpose, which suits a base image and
not an ISO built from one. The x86_64 Arch base has no such account, so one
architecture failed and the other did not.

**Why nothing caught it.** This repo had already solved it. A block in
`01-workarounds.sh` removes the cloud account that `docker.io/library/ubuntu`
ships at the same UID, and its comment states the reason: the real error lands
"an hour downstream, in another repo's code, with no mention of this image".
The guard was `IS_UBUNTU`. The diagnostic that block prints for this failure
sat inside the same branch, so Arch ARM hit the identical bug in silence.

**Fix.** Remove the `alarm` account on the same terms as the Ubuntu one: only
when it is still named `alarm` and still at exactly 1000. Move the warning out
of the per-base branch, so the next base to ship an account at 1000 reports
itself in the build that causes it.

**Lesson:** when a workaround names one base, ask which other bases have the
same shape. A guard is a claim about who is affected, and this one was a guess
that nobody revisited when a second base arrived.

### 26. The fix the build never ran (`marlin:gnome` arm64, 2026-09-17)

The next `marlin` run failed on the same line as §25, with the same message:

```
>>> [customize] (1/2) baseline.sh
useradd: UID 1000 is not unique
Error: live customize for marlin-gnome: ... exit status 4
```

**Root cause.** `Containerfile.arch` does not run `01-workarounds.sh`. Only
`Containerfile.el10` and `Containerfile.ubuntu` run that script. The §25 fix
went into it, so the Arch branch could never execute. The Containerfile even
says so, ten lines above the spot where the call belongs: this base leaves out
the numbered base scripts. That comment was already correct and nobody read
it.

**Why nothing caught it.** The test asserted that the removal existed in
`01-workarounds.sh`, and it did, so the test passed. Presence in a file is not
reach from a build. No test checked the call in `Containerfile.arch`, and the
run conclusion for §25 looked like a fix that worked.

**Fix.** The removal now lives in `build_scripts/free-uid-1000.sh`. That script
reads no distro flags and needs no build context, so any Containerfile calls it
in one line. `Containerfile.arch` calls it directly. `01-workarounds.sh` calls
the same script, so one copy serves every base. The test now asserts that each
Containerfile which builds ISOs reaches the script, on a line that is not a
comment.

**Lesson:** prove that the build reaches the fix. A test that finds code in a
file proves only that the file holds the code. This is the fourth entry in this
document where the repository already held the correct fix and the fix did not
reach the failure.

### 27. A volume label two characters too long (`bonito-rawhide` nvidia ISOs, 2026-09-17)

bonito-rawhide built one nvidia ISO and failed the other four:

```
xorriso : FAILURE : -volid: Text too long (34 > 32)
Error: xorriso: ... -commit: exit status 5
```

**Root cause.** ISO 9660 caps the volume ID at 32 characters. xorriso rejects
the whole build instead of a quiet truncation. The media name was
`tunaos-<variant>-<flavor>`, and `bonito-rawhide` is a long variant name:

| media name | length | result |
| --- | --- | --- |
| `tunaos-bonito-rawhide-cosmic-nvidia` | 35 | failed |
| `tunaos-bonito-rawhide-gnome-nvidia` | 34 | failed |
| `tunaos-bonito-rawhide-niri-nvidia` | 33 | failed |
| `tunaos-bonito-rawhide-xfce-nvidia` | 33 | failed |
| `tunaos-bonito-rawhide-kde-nvidia` | 32 | built |

**Why the pattern misleads.** Every cell that died was an nvidia cell, so the
column reads as an NVIDIA fault. It is not. `kde-nvidia` sits exactly on the
limit and built. The nvidia flavors carry the longest names in the
group. The same overflow reaches `flounder-sid-cosmic-nvidia` at 33
characters. Nothing is wrong with those images.

**Fix.** `tunaos_iso_media_name` in `scripts/lib/common.sh` caps the name, and
both ISO builders call it. A name that already fits stays exactly as it was,
because the boot path depends on the label. tacklebox puts the same string on the
kernel cmdline as `root=tbox:CDLABEL=...`. Both sides read `media_name`, so a
shorter name moves them together. The cap drops the `tunaos-` prefix first:
every ISO in the matrix carries that prefix, and `<variant>-<flavor>` is what
identifies the media.

**Lesson:** when a tool enforces a limit, put the real names in a test. This
one held for years, because no variant name was long enough. One new variant
with a longer name then broke four cells at once. Test the boundary: the
`kde-nvidia` row at exactly 32 is what proves the rule. An off-by-one there
would rename the one label that the kernel cmdline depends on.

### 28. The kernel was there; the index was not (`marlin:gnome` arm64, 2026-09-17)

§26 cleared the UID 1000 failure on this cell. The next build reached much
further and stopped here:

```
no kernel found under /usr/lib/modules (looked for modules.dep):
7.2.6-1-aarch64-ARCH
```

**Root cause.** tacklebox selects the kernel by the index, not the kernel:
`[ -f "$d/modules.dep" ] || continue`. The image had the directory and
`initramfs.img`, and only `modules.dep` was absent from it.

This entry first said the image also had `vmlinuz` and booted. It had neither.
§30 has the correction and the second fault behind the same message.

`depmod` lives in `build_scripts/26-packages-post.sh`, which
`Containerfile.arch` does not run. On x86_64 that cost nothing: the base is
`docker.io/archlinux`, `pacman -S linux` installs a kernel, and pacman's
depmod hook writes the index. On aarch64 the base is
`ghcr.io/tuna-os/archlinuxarm`, whose rootfs already carries
`linux-aarch64`, so `pacman -S --needed` does nothing, the hook never fires,
and nothing indexes the tree.

**Why it stayed hidden.** Two covers. The image boots without the index, so
every runtime gate passed. The ISO job also died sooner, at UID 1000, and did so
for weeks. One fix exposed the next.

**Fix.** `Containerfile.arch` runs `depmod` on the kernel that step already
resolved, before dracut. The tests assert reach on a line that is not a
comment, the shared `KVER`, the order against dracut, and the absence of
`|| true`.

**Lesson:** an early failure hides every later one, so a fix that works will
often reveal a second fault instead of a green cell. Read the new error as
progress and check what it says. A still-red cell is not proof that the fix
failed. The scope note in the test file matters as much.
Four other bases never call `depmod` and are right not to, because their
package managers index the tree themselves. An assertion that demanded it
everywhere would fail code that already works.

### 30. One error message, two faults (`marlin:gnome` arm64, 2026-09-17)

§28 ran `depmod` on this cell. The next build printed the same words:

```
no kernel found under /usr/lib/modules (looked for modules.dep):
7.2.6-1-aarch64-ARCH
```

The obvious read is that the fix did not reach the build. It did. The build
log shows `depmod` at step 25 of 37, and the module index is in the published
image.

**Root cause.** tacklebox has one message for a loop with two requirements:

```sh
for d in /usr/lib/modules/*/; do
  [ -f "$d/modules.dep" ] || continue
  if [ -f "$d/vmlinuz" ] && [ -f "$d/initramfs.img" ]; then
```

Past the first line, an absent `vmlinuz` ends at the same `exit 1` with the
same text about `modules.dep`. The kernel binary was the missing file.

Arch Linux ARM's `linux-aarch64` ships the kernel as `/boot/Image` alone,
where Arch's x86_64 `linux` owns `/usr/lib/modules/<kver>/vmlinuz`.
`build_scripts/bootc/ostree-layout.sh` runs `rm -rf /boot`, so on aarch64 it
deleted the only copy. The arm64 images shipped with no kernel.

`Containerfile.debian` and `Containerfile.gentoo` (twice) copy the kernel
across by hand, one step before they call that script. Gentoo's comment says why:
"Both must happen BEFORE the ostree layout below, which deletes /boot". Arch
was a fourth copy that nobody wrote.

**The evidence.** This session had no container runtime, so it read the
published image straight from the registry. Fetch the manifest with a ghcr pull
token, stream each layer through `zstd -dc | tar -t`, then grep the names.
`modules.dep` sits in layer 55. Neither `vmlinuz` nor `Image` appears in any of
the 65 layers. The section above on a published image without a container
runtime holds the recipe.

**Why it stayed hidden.** No Gate runs on arm64, so nothing booted the image
and nothing reported that it could not boot. The ISO job was the first reader
of `/usr/lib/modules/<kver>/vmlinuz`, an hour downstream and in another
repository.

**Fix.** `ostree-layout.sh` rescues the kernel into the module directory before
it clears `/boot`, which is a no-op on every variant that already has one.
`Containerfile.arch` now stops the build when `vmlinuz` is absent. It no longer
builds an initramfs for a kernel that is not there.

**Lesson:** an error message names the check that failed, not always the file
that is missing. Read the code that prints it before you conclude a fix did not
land. Where two causes share a message, the second cause reads as proof that the
first one is still there. The control that settled it was the amd64
cell of the same run, which built, booted and published from the same
Containerfile.

### 31. The ISO builds and cannot boot (`marlin:gnome` arm64, 2026-09-18)

§30 gave this cell its kernel back. `Build Live ISO` then SUCCEEDED for the
first time and produced a 6.16 GB arm64 ISO. One step later the job was still
red, at `Boot gate: verify ISO readiness`: no readiness marker in 900 seconds,
and a blank framebuffer.

**Root cause.** The live root filesystem uses a compressor the kernel cannot
read. From the guest serial console, about 648 times until the timeout:

```
mount: /run/rootfsbase: fsconfig() failed:
       Filesystem uses "zstd" compression. This is not supported.
Warning: Tacklebox: cannot loop-mount /LiveOS/marlin-gnome.rootfs.sfs
```

tacklebox squashes the live rootfs with zstd. Arch Linux ARM's `linux-aarch64`
has no zstd support in its squashfs driver, and the kernel itself says so. That
makes this a measurement, not a guess. Arch's x86_64 `linux` does support zstd,
so the amd64 cell of the same run boots and publishes. The same fault predicts
skipjack's `iso:cosmic (linux-arm64)`, which builds and then fails its gate the
same way.

**Where the fix is not.** `scripts/build-iso-tacklebox.sh` writes the recipe,
and the recipe has no compressor field. tacklebox chooses zstd. So the change
belongs upstream in tuna-os/tacklebox, or in the ARM kernel config. Do not
reach for a workaround in this repository.

**Two things this also exposed.**

The failure never stops. `/sbin/tbox-live-root` line 135 runs `return` outside
a function, so the error path aborts and dracut tries again under `A start job
is running for dracut initqueue hook (no limit)`. A mount failure with no
recovery costs a full gate timeout on each arm64 cell, in place of seconds.

The gate measures less than it reports. On the arm64 runner it prints
`tesseract not installed` and `requires Pillow and requests`, so its keyword and
forbidden-text assertions SKIP. Its verdict here was still right, because the
frame-difference check caught the blank screen on its own. Read which assertions
ran before you trust a pass from this gate on arm64.

**Lesson:** a cell that builds is not a cell that works. Three fixes in a row
can each be correct while the cell stays red. Check which STEP failed, not
whether the job did. The serial log holds the evidence, and the job log does
not carry it: pull the e2e artifact.

### 29. A gate that asked the wrong question (`Audit NVIDIA release assets`, 2026-09-17)

This job showed red on all 15 runs it ever had. It never passed once, so it
never reported anything.

**Root cause.** It checked GitHub Releases for a per-flavor tag with at least
one asset. This repository does not publish ISOs that way:

- `attach-release` in `reusable-build-artifacts.yml` defaults to `false`, so
  every cell skips "Attach ISO to GitHub Release". In a green ISO job for nvidia, that step still reads
  skipped. "Upload ISO to Cloudflare R2" succeeds next to it.
- The releases that exist are per desktop (`gnome-20260916`), not per flavor,
  so no tag ever started with `gnome-nvidia-`.
- Those releases carry no assets at all.

The audit also asked about `gnome50-nvidia`, which is in no variant of
`.github/build-config.yml`. Someone hardcoded its flavor list, and the list
then drifted.

**Why nothing caught it.** A check that stays red looks the same on day 15 as
on day 1. Nobody could tell a real fault from a broken question, so the row
carried no information.

**Fix.** The audit now lists `live-isos/<variant>-<flavor>-latest.iso` in R2,
which is where the upload step puts each ISO and the path `docs/TESTING.md`
tells users to fetch. The cell list comes from `build-config.yml`, filtered to
`build_image` and `build_iso`, so it tracks the matrix and cannot drift. That
widened the audit from 6 hardcoded names, one of them fictional, to 27 real
cells. Without R2 credentials it skips and does not fail, which is what the
upload step and `prune-r2.yml` already do for forks.

**Lesson:** a check that has never passed is not a strict check. It is an
unread one. When a gate shows red on every run it ever had, doubt the question
before the answer. Delete such a gate only after the intent behind it has
somewhere true to live.

### 30. GNOME is installed but GDM reports a missing shell schema (#2750)

**Symptom:** GDM exits before login with `Settings schema 'org.gnome.shell' is not installed`.
The wootc experiment reproduced this in a VM with Yellowfin digest `ed95623a` on 2026-09-26.

**Cause:** `gnome-shell-50.0-3` provided the name of its own dependency,
`gnome-shell-common`. DNF omitted that RPM, which owns the schema XML.
The image contract checked the GNOME binary and version but never loaded the schema.

**Fix:** [Package PR #748](https://github.com/tuna-os/tunaos-packages/pull/748)
removes the false provider. The image contract now runs
`gsettings list-keys org.gnome.shell` in both build and runtime checks.
This detects missing XML and absent or unreadable compiled schemas.
It does not prove a user can log in; that still needs a boot and session test.

The check ran in two real containers with the network disabled. The original
Yellowfin image returned exit 1 and named the absent schema. The derived image
returned exit 0 after installation of only the matching common RPM. Its digest is
`sha256:4562f4f0fde8cc0ba49e7ce627be2ba35d803c9aa768e79220a1a58c3b0d148b`.
That image is an experiment, not a production repair.

The RPM exposed the schema in an offline chroot but did not repair the boot:
composefs still exposed the original `/usr`. Rebuild the OCI image and install it.

**Build-side fix (#1753):** the new gate then failed every EL10 GNOME cell
at Build Image, because the pinned tier still ships `gnome-shell-50.0-3`
(albacore run 36840489732, yellowfin run 36822471546, skipjack run
36892338904). The tier also ships the real
`gnome-shell-common-50.0-3.noarch`. `packages.el10.packages` in
`manifests/desktops/gnome.yaml` now names `gnome-shell-common`. DNF matches a
package name before a provide, so it installs the real RPM. The line stays
correct after the package PR lands.
`tests/regressions/test_issue_2750_el10_gnome_installs_the_shell_common_rpm.py`
holds it.

## 31. Installed runtime report rejects a working desktop with `starting`

**Symptom:** `TUNAOS_INSTALL_CHECKS_RESULT pass=15 fail=1` with
`system state: starting`, followed by an authenticated GNOME session that worked.

**Cause:** The runtime script runs inside the initial boot transaction. Its
oneshot job can keep the manager in `starting` until the script exits. The
2026-09-26 wootc 32 GiB target / 16 GiB scratch trial showed this failure, then
`systemctl is-system-running` returned `running` in the user's terminal.

**Fix (#2756):** Sample once and accept valid boot states, as the base contract
already does. Reject maintenance, stopping, offline, empty, and unknown results.
Do not wait for the transaction from inside it. This check reports manager
state; the separate display-manager and user-session checks prove more.


## 32. Weekly boot report hides successful non-GNOME QCOW2 captures (#2801)

**Symptom:** The 2026-09-28 report listed KDE, Niri, and COSMIC QCOW2
screenshots as unavailable even though all 12 non-GNOME jobs in workflow run
[36356753451](https://github.com/tuna-os/tunaOS/actions/runs/36356753451)
completed successfully and uploaded their named artifacts.

**Measured cause:** `generate-boot-report.py` fetched a QCOW2 screenshot only
when the flavor's `build_qcow2` value was true. That setting tells the release
process to publish an artifact, and was true only for GNOME. The separate
`weekly-qcow2-screenshots.yml` matrix builds temporary disks and captured all
four desktop flavors for Yellowfin, Albacore, Skipjack, and Bonito.

**Fix:** Derive screenshot coverage from the weekly workflow's matrix in
addition to the release flags, then fetch each declared artifact. The unit test
uses the previous defect: the report must query a matrix cell with
`build_qcow2: false` when the weekly workflow captures it.

### Adoption reports show `desktop` or `latest` for different images

**Symptom:** Image info reports `desktop` or `latest` for different images. It does not identify each flavor or the actual update tag.

**Measured cause:** On main `7c9efe4f`, `scripts/resolve-flavor.sh` sets `DESKTOP_FLAVOR=desktop` for overlays and `build_scripts/90-image-info.sh` writes `image-tag=latest`. These values describe build defaults. The build passes the canonical variant apart from its publish name. Preserve it for Rawhide/Sid reports.

**Fix:** Do not infer adoption categories from these defaults. Preserve the original variant and requested full flavor in separate metadata and verify each final image after desktop/overlay copies. See the [private adoption metrics RFC](rfc/rfc012-private-adoption-metrics.md). `tests/test_countme_images.py` checks metadata and masks in installer output for every matrix flavor. The original flavor travels through `TUNAOS_IMAGE_FLAVOR`, apart from the stage name.


### Missing-tool test fails when the tool exists on the host

**Symptom:** `qemu-img: detects when qemu-img is missing` fails in the local Bats suite.

**Measured cause:** The test checked the host PATH. `/usr/bin/qemu-img` exists here, but the assertion expected no tool.

**Fix:** Run the absence check with an empty fixture PATH and the absolute Bash path. `bats tests/bats/test_build_qcow2.bats` passes all 33 cases with that fixture.


### Automated Corral guests could enter adoption counts

**Symptom:** A CI guest could send an adoption report before SSH checks can disable its timer.

**Measured cause:** [Corral 4c59a6be](https://github.com/tuna-os/corral/blob/4c59a6be9ea6532aa79c6407bab471b4202c1484/pkg/kubevirt/bootc.go#L536) has no kernel argument option for both fresh and resumed guests. The custom script uses a chroot in the raw root partition. Its KubeVirt path ignores a script failure. A command after SSH starts cannot prevent the first report.

**Fix:** The boot gates use `scripts/corral-boot-gate.sh`. It gives `--karg tunaos.countme=0` to `corral vmtest`, and Corral writes the argument into the boot entry before the first boot. `bats tests/bats/test_corral_boot_gate.bats` checks the argument. The GPU-routed path through `iso-e2e.sh` sets the SMBIOS CI marker before boot. The KubeVirt helper `scripts/boot-gate.sh` exits 77 before guest creation unless both of its paths support the exclusion argument. `bats tests/bats/test_boot_gate_resume.bats` checks that helper.

### Adoption dashboard API returns HTTP 503

**Symptom:** `/api/adoption` returns HTTP 503, but the collector returns HTTP 200.

**Measured cause:** On 2026-09-27, the live site Worker rejected `redirect: "error"` with `TypeError: Invalid redirect value`. Node fetch accepts that option. The Node test passed and the live request failed.

**Fix:** The site uses `redirect: "manual"` and rejects a redirect response. The `COUNTME` service binding connects the site to the collector. `npm run test:site` now tests the site proxy in native workerd. The live API returned HTTP 200 after the fix; the browser check found no page errors or axe violations.

### Marlin selects OSTree/XFS during disk installation

On 2026-10-04 the Corral builder on AWS failed with `bootupd is required for ostree-based installs`. The Marlin image had bootupctl and systemd-boot but no GRUB update payload. Its shared installer configuration also reported an XFS root although prepare-root.conf enabled composefs.

The Marlin override `50-marlin.toml` selects systemd-boot and ext4. Containerfile.arch now applies the variant overrides and checks bootc's merged configuration before release. External installers must also select `--composefs-backend` when the image has systemd-boot without a GRUB update payload; the bootupctl executable alone does not identify an OSTree installation. Corral's corrected image probe reports composefs/ext4. The AWS boot result remains a separate qualification gate.


### Roost Screenshot consent cannot open its Access dialog

**Symptom:** A Screenshot request reaches GNOME but cannot complete its consent dialog.

**Measured cause:** [Roost job 111453682195](https://github.com/hanthor/roost-desktop/actions/runs/37207282677/job/111453682195) exercised GNOME 51 with GTK for Access. Allow returned a readable 1280×800 PNG. Deny returned response 2 without a URI. Locked admission returned no image. The fixture for Roost selected `org.freedesktop.impl.portal.Access=gtk;`. TunaOS omitted that preference in its experience configuration.

The image had both backends; the default preferred GNOME for Access.

**Fix:** Select GTK for Access, and GNOME for Screenshot and ScreenCast. The contract for the installed desktop rejects missing, wrong, duplicate, or out-of-section preferences. The admission test runs the shell validator against the shipped configuration and broken variants. Verify the final image in its separate boot gate.

### guppy:gnome installs GNOME 49 and fails the version floor (#2450)

**Symptom:** The `gnome` build of `guppy` (Gentoo) stops in `verify-desktop-experience.sh` with this error:

```
GNOME 49 is below the floor: nothing below GNOME 50 ships
```

**Measured cause:** On 2026-10-07, stable amd64 in `::gentoo` stops at `gnome-shell-49.7`. The GNOME 50 ebuilds (`gnome-shell-50.5`, `mutter-50.5`, `gdm-50.3-r2`) have only the `~amd64` keyword. The official binhost builds only stable versions. Also, `gentoo-binhost-version-lock.sh` masks all `gnome-base` versions that are newer than the binhost. Thus a keyword for `gnome-shell` alone does not have an effect: the lock masks 50.5, the `--pretend` check resolves to 49.7, and the lock stays.

**Fix:** The `emerge_accept_keywords` list in `manifests/desktops/gnome.yaml` gives the GNOME 50 core set. `install-desktop.sh` writes that list to `/etc/portage/package.accept_keywords` before the lock runs. The lock does not mask the packages in that file. These packages compile from source. If `emerge --pretend` shows a mixed 49/50 desktop, add the 49 package to the list. Do not add `gnome-base/nautilus`: `::gentoo` masks `>=nautilus-50` (bug 982084).

### CI steps download an unpinned yq binary

**Symptom:** A CI step downloads `releases/latest/download/yq_linux_amd64` from `mikefarah/yq` into `/usr/bin` or `/usr/local/bin`. The step does not pin a version.

**Measured cause:** Issue tunaOS#2071 found these downloads in CI workflows. The `latest` link can change at any time. The step installs the file as root, and no step verifies the checksum of the downloaded file. If the upstream file changes, the new file runs as root on the runner.

**Fix:** Workflows and composite actions use the `.github/actions/setup-yq` action. That action downloads yq `v4.53.3` and checks its SHA-256 value before it installs the file. It installs the file to `/usr/local/bin`, which comes before the runner image's `/usr/bin/yq` on `PATH`, and then fails the step if the yq on `PATH` does not report exactly `v4.53.3`. The test `tests/regressions/test_issue_2071_yq_downloads_are_pinned.py` checks each yq download in the workflows and actions.

### Desktop image builds download an unverified yq release asset (#3329)

**Symptom:** A manifest-driven desktop build downloads `yq` into
`/usr/bin/yq` before it reads the desktop manifest.

**Measured cause:** `build_scripts/desktop/install-desktop.sh` used a pinned
release URL but did not verify the release asset. A changed or compromised
asset could therefore execute as root inside the image build.

**Fix:** The installer now accepts only `x86_64` and `aarch64`, checks the
architecture-specific SHA-256 for yq `v4.53.3`, and renames the verified file
atomically into `/usr/bin/yq`. `tests/regressions/test_issue_3329_yq_downloads_are_verified.py`
checks the download, checksum, and install sequence.

### AI porting agent executes untrusted upstream diffs with write token

**Symptom:** Scheduled watch workflows send third-party commit diffs to LLM agents with write permissions. The agent commits and pushes branches without review.

**Measured cause:** In #1740, `watch-upstream.yml` read commit text and diffs from third-party repositories. It embedded the diffs into `GEMINI_TASK.md` without checks. A malicious commit diff could inject instructions to write code or exfiltrate tokens (`GH_TOKEN`, `GEMINI_API_KEY`, `COPILOT_PAT`).

**Fix:** Delete the legacy watch workflows and helper scripts. Upstream sync uses `snapshot-upstreams.yml`. That workflow vendors files into `_upstream-snapshots/` and creates pull requests for review. `tests/regressions/test_issue_1740_no_untrusted_upstream_diff_ai_write_pipeline.py` prevents new AI workflows with write tokens on untrusted diffs.

### Codecov project and patch targets never appear on a pull request

**Symptom:** `codecov.yml` declares project and patch targets, but no Codecov
result or coverage trend appears after the `Unit Tests` job; only a downloadable
`coverage-python.xml` artifact exists.

**Measured cause:** On main at `957d9ec6`, a repository-wide search found no
`codecov/codecov-action` or Codecov CLI invocation. `test.yml` generated the XML
and passed it only to `actions/upload-artifact`, which does not send reports to
Codecov or evaluate `codecov.yml`.

**Fix (#2301):** Keep the artifact for debugging and also upload the same XML
with the SHA-pinned Codecov action, the `python` flag, and GitHub OIDC. The BATS
contract in `tests/bats/test_test_yml_pytest_always_runs.bats` holds the upload
path and authentication mode. This report is Python-only; BATS and QEMU E2E
coverage are behavior gates, not line-coverage inputs.

**Slow covered Unit Tests:** Set `COVERAGE_CORE: sysmon` only on the
`Run pytest tests` step. Counterbalanced local full-suite runs on Python 3.12.3,
pytest 9.2, pytest-cov 7.1, coverage 7.17 and xdist 3.8 used four workers on
fixed 2-CPU/8-GiB resources. CTrace took 439.921/407.937 seconds; SysMon took
198.631/242.443 seconds: local means of about **424 versus 221 seconds**, not
a measured hosted-runner gain. Coverage debug `Using core` messages confirmed
the requested core in each of the four runs without fallback.

All 7,082 test cases and outcomes matched, as did the 371-file,
46,165-statement scope. One SysMon run's covered-line set exactly matched one
CTrace run; only process-cleanup lines 1181, 1206 and 1207 in
`scripts/install-checkpoints.py` varied across runs under both cores.
The existing recorder-lifecycle and credential-withholding tests also passed
under SysMon (2 tests, 0.31 seconds).
This selects a supported core for the current CI's line coverage only:
keep `-n auto`, both test paths, `--cov=.`, reports, BATS, dependency versions,
thresholds and timeout windows unchanged. It does not add branch coverage,
dynamic contexts or subprocess coverage.

### Workflow token scope depends on repository defaults

**Symptom:** A workflow does not set `permissions:`. Its token can then receive
scopes that the workflow does not use.

**Measured cause:** The audit for tunaOS#2767 found 27 workflows that used the
repository defaults for token scope.

**Fix:** Set a narrow scope for each workflow. Give write access only to a job
that changes GitHub state. The regression test for #2767 checks each workflow.

### Fork simulation times out while rebuilding images

**Symptom:** The fork rehearsal times out in an ISO, image, or KVM lane. It
does not report token or secret failures.

**Measured cause (#2257):** PR #2604 ran every pull-request workflow under
`act` for three personas. The run included the heavyweight ISO and live-image
lanes. Thus, the weekly job would rebuild or boot large artifacts for each
persona. It would report resource timeouts as fork-safety failures.

**Fix:** Keep an explicit, fail-closed classification in
`scripts/fork-simulation.py`. Run only fork-sensitive, act-compatible lanes.
Pass the intended `GITHUB_REPOSITORY` explicitly.

For workflows that read or change pull-request state, mount
`scripts/fork-simulation-gh`. Its fixture uses PR 1 from the event. It rejects
unlisted requests without a call to GitHub. Record why heavyweight/read-only
lanes remain under static checks. The classification test rejects each
unreviewed pull-request workflow.

### Admitted variant with missing rebuild repository fails CI

**Symptom:** A new variant fails nightly builds for declared desktops (e.g. 10+ red nights for Hummingbird).

**Measured cause (#1755, #1763):** The project admitted Hummingbird without a check for desktop packages or aarch64 repodata. Declared desktops had no manifest sections.

**Fix (#1763):** Extend `VARIANT-LIFECYCLE.md` with a completeness check. Verify repo reachability across declared arches. Add manifest sections before setting `build_image: true`. Exclude unbuilt arches until package sources exist.


### A LUKS cell passes its desktop contract and fails the pixel gate (#979)

**Symptom:** The LUKS path logs `desktop_contract=ok`, but the
`installed-desktop` capture has `stddev=0` and the pixel gate fails the cell.

**Measured cause:** `luks-first-boot.py` sent `system_powerdown` when it
returned. `iso-e2e.sh` then took the capture during the shutdown. A guest that
stopped its display manager in that 8s window left a black framebuffer. Run
36873532817 failed 33 cells this way (sddm, gdm and lightdm). Cells that
stopped more slowly passed.

**Fix:** `iso-e2e.sh` always sets `TUNAOS_LUKS_NO_POWEROFF=1`. It takes the
capture first, then sends the graceful powerdown itself before the kill.
`tests/bats/test_luks_capture_before_powerdown.bats` holds that order.

### Marlin base userland gaps (tunaOS#3351, #3353, #3354, #3355)

**Symptom:** A booted marlin:gnome (BUILD_ID=4ace379) has no `hostname`, `diff`, `less`, `lsusb`, `bluetoothctl`, `distrobox`, or `buildah`. Bluetooth stays `disabled; preset: disabled`. Audio on modern laptops has no SOF firmware and no ALSA-to-PipeWire route.

**Measured cause:** The stock Arch `base` metapackage no longer ships `diffutils` or `less`, and Arch's default preset is `disable *`. `Containerfile.arch` skips `build_scripts/10-base-packages.sh`, so everything that phase provides elsewhere (`buildah`, `distrobox`, `fzf`) never reached marlin, and nothing enabled `bluetooth.service`. `bluez` was present only transitively via `fwupd`. All sixteen missing names resolve in Arch `core`/`extra` (verified with `pacman -Si` against the 20261011 base).

**Fix:** `Containerfile.arch` installs all sixteen explicitly (`inetutils`, `diffutils`, `less`, `usbutils`, `man-db`, `fzf`, `buildah`, `distrobox`, `bluez`, `bluez-utils`, `sof-firmware`, `pipewire-alsa`, plus the updater path in the next row). `40-services.sh` enables `bluetooth.service` and `uupd.timer` on the pacman branch only. A marlin-scoped preset (`system_files_overrides/marlin/.../50-tunaos-marlin.preset`, delivered by `92-variant-customizations.sh`) preserves those symlinks through first-boot preset policy, with no change to any other variant.

### Marlin shipped uupd triggers without uupd (tunaOS#3356)

**Symptom:** `systemctl --failed` reports `uupd-on-ac.service` after every AC event; the journal says `uupd.service: Unit not found`, and the image has no `/usr/bin/uupd`.

**Measured cause:** `Containerfile.arch` copies the common payload that provides the uupd timer and AC trigger. It never ran the package phase that installs the pinned binary and core units. Observed on a reference marlin:gnome host (booted 2026-09-22 image): trigger starts, `systemctl start uupd.service` exits `NOTINSTALLED`, unit enters `start-limit-hit`.

**Fix:** The pinned download moved into shared `build_scripts/install-uupd.sh` (same `image-versions.yaml` pin; stages the binary plus `uupd.service`, `uupd.timer`, `uupd-manual.service` before install; smoke with `UUPD_CONTEXT="$PWD" UUPD_ROOT="$scratch"` into a disposable root). The apt and dnf branches of `10-base-packages.sh` delegate to it unchanged in behavior, and `Containerfile.arch` carries the pin file and runs the installer before `40-services.sh`. The context exact-set test now treats `install-uupd.sh` as a consumer of the pin file.

### Unverified uupd release assets and units installed into images (tunaOS#3386)

**Symptom:** `build_scripts/10-base-packages.sh` and `Containerfile.arch` installed `ublue-os/uupd` release archives and systemd units without checksum verification.

**Measured cause:** `install-uupd.sh` downloaded release archives and unit files from GitHub tags directly. It did not check their hashes against published checksums.

**Fix:** `image-versions.yaml` pins architecture-specific `uupd_sha256` and unit `uupd_units_sha256` digests; `install-uupd.sh` verifies archives and units with `sha256sum --check --strict` before extraction and installation; `scripts/check-download-checksums.py`, `tests/test_pinned_download_checksums.py`, and `renovate.json` (`automerge: false`) guard against silent checksum drift.

### Matrix test cannot find `FULL_MATRIX` (#3395)

**Symptom:** `test_the_build_matrix_honours_build_image.py` raises `ValueError: substring not found` in `_flatten_step`.

**Cause:** The workflow converts YAML in `CONFIG_JSON` before it builds the matrix with jq. The test still searched for an inline yq call.

**Fix:** Locate the `FULL_MATRIX` assignment. Keep the assertions for `.variants[]`, `.flavors[]`, and the `build_image` filter.

### ISO delivery policy refuses a cutover entry (#3382)

**Symptom:** A job fails with an `ERROR:` line that names a cutover target and its receipt, a retained ISO or a platform.

**Cause:** `scripts/iso-delivery-policy.py` validates `[iso_delivery]` in `tunaos.toml` and refuses any entry it cannot prove. Each entry needs a committed receipt at `iso-qualification/receipts/<hex>.json` that proves the same target (#3381). A bad entry stops the job. It never changes what uploads without a message.

**Fix:** Empty `cutover_targets` to restore the prebuilt upload path. Otherwise correct the named field, or collect the receipt again with `scripts/collect-qualification-receipt.py`. `tests/test_iso_delivery_empty_policy_is_identity.py` proves that, when the policy is empty, each upload and each prune stays as it was.

### STE fails on matrix prose

**Symptom:** STE reports 1610 findings with a budget of 1609.

**Cause:** A long sentence or a cluster of nouns in `docs/MATRIX-STATUS.md` crosses the budget.

**Fix:** Split the sentence. For text inside the generated block, edit `scripts/gen-matrix-status.py` and render it again. Keep the budget at 1609. Preserve the dates when you replay saved evidence.