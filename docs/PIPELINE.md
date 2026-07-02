# TunaOS Build Pipeline Reference

Authoritative map of how images and ISOs get built, verified, and published.
Written for both humans and AI agents (Hive: guide, architect, sec-check,
quality, ci-maintainer, strategist). If you are changing CI, read this first;
if you change the pipeline's shape, update this file in the same PR.

Related: [`AGENT_GUIDE.md`](AGENT_GUIDE.md) (dev workflow),
[`TESTING.md`](TESTING.md) (test harness details),
[`../CONTEXT.md`](../CONTEXT.md) (domain glossary),
[`../.github/build-config.yml`](../.github/build-config.yml) (the matrix).

---

## The product matrix

`variant × desktop [× hardware flavor]`, defined entirely in
`.github/build-config.yml`. Every variant builds **gnome, kde, niri, xfce**
(cosmic on RPM variants only; grouper has no cosmic — `cosmic.sh` has no apt
branch).

| Variant | Base | Desktops | HWE/NVIDIA | Arch |
|---|---|---|---|---|
| yellowfin | AlmaLinux Kitten 10 | gnome, gnome50, cosmic, kde, niri, xfce | yes | amd64, amd64/v2, arm64 (xfce: x86_64 only) |
| albacore | AlmaLinux 10 | gnome, gnome50, cosmic, kde, niri, xfce | yes | amd64, amd64/v2, arm64 (xfce/gnome50: x86_64 only) |
| skipjack | CentOS Stream 10 | gnome, gnome50, cosmic, kde, niri, xfce | gnome/cosmic families | amd64, arm64 (xfce: amd64 only) |
| bonito | Fedora 44 | gnome, cosmic, kde, niri, xfce | nvidia only | amd64, arm64 |
| grouper (experimental) | Ubuntu 26.04 | gnome, kde, niri, xfce | none | amd64 only |

**XFCE is special**: on EL10 it is the [hanthor/xfce-wayland](https://github.com/hanthor/xfce-wayland)
port — the `xfwl4` Rust/Smithay compositor plus Wayland-adapted XFCE
components — installed via the `xfce4-wayland` meta package. Specs live in
[tuna-os/github-copr](https://github.com/tuna-os/github-copr) under
`src/xfce-wayland/`, served from `repo.tunaos.org` (**EL10 x86_64 only**;
that constraint drives the platform restrictions above). bonito ships stock
Fedora XFCE (X11) until a Fedora chroot exists; grouper ships the Ubuntu X11
stack (no debs). Session entry is `startxfce4 --wayland`; xfwl4 requires
`xfwm4` installed (themes).

---

## Image flow: build → testing tag → boot gate → promote

Implemented in `reusable-build-image.yml`. **The bare `:<flavor>` tag is only
ever written by the promote job, after the boot gate.**

```
build_push (per arch)         pushes  :<flavor>-<arch>          (plumbing)
  └─ chunkah rechunk, telemetry, rechunk-metadata check, SBOM
manifest                      pushes  :<flavor>-testing         (multi-arch)
verify_boot  [amd64]          bootc install → qcow2 → QEMU boot
  │                           (skipped for base* flavors — no desktop)
tag-image "Promote Tags"      copies  -testing → :<flavor>, :<flavor>-YYYYMMDD,
                                      :<flavor>-<arch>[-YYYYMMDD]
                              only if boot gate passed AND all platforms built
```

Consequences agents must respect:

- **Consumers pull bare tags** (`ghcr.io/tuna-os/<variant>:<flavor>`) — these
  are always boot-verified. A red boot gate leaves users on the last good
  image; it does not break them.
- **CI stage chaining pulls `-testing`** (`Justfile`, `PARENT_FLAVOR` logic):
  stage-3 `gnome-hwe` builds on this run's `gnome`, not last week's.
- On PRs nothing is pushed; the same QEMU boot check runs against the locally
  built image (amd64 leg only).
- If you see a `-testing` tag newer than the bare tag, the boot gate is
  failing — check the `boot-gate-*` artifact (serial.log + screenshots) on
  the failing run before touching anything else.

## ISO flow

Two paths, both boot-gated **before** any upload:

1. **Per-flavor ISOs** — `reusable-build-artifacts.yml` (called from the
   per-stage `PkgS2/S3/S4` jobs in `build-variant.yml` and from
   `publish-isos.yml`): tacklebox builds the ISO from GHCR → workflow
   artifact (always, for debugging) → `scripts/iso-e2e.sh` boot gate →
   only on success: R2 `live-isos/<variant>-<flavor>[-latest].iso` and
   (publish-isos only) GitHub Release attach.
2. **Grouped dedup ISOs** — `publish-iso-groups.yml` builds one ISO per
   `iso_groups:` entry (flagship / community / nvidia) via
   `just iso-group`; inline boot gate before the R2 upload.

## Boot verification mechanics (`scripts/iso-e2e.sh`)

One harness, three relevant modes:

| Mode | Use | Pass condition |
|---|---|---|
| default (`ready`) | live ISOs | `TUNAOS_LIVE_READY` on serial **or** screenshot-sanity fallback |
| `--disk` | qcow2/raw images (GHCR boot gate, PR gate, `just verify-disk`) | graphical/multi-user marker on serial **or** screenshot-sanity fallback |
| `--kickstart` | unattended `bootc install to-disk` + reboot check | install completes and installed disk boots |

Two hardware facts shape this design — do not "simplify" them away:

- **Serial is unreliable**: EL10 bootc kernels ship `CONFIG_SERIAL_8250=m`,
  so markers often never reach the serial console (`research.md`).
- **Default VGA screendumps are black under UEFI GOP**: every QEMU
  invocation must carry `-vga virtio` or screenshots are useless
  (`STATUS_2026-07-02.md`).

The fallback: a screendump whose grayscale stddev > 0.02 counts as a rendered
screen; blank/absent screenshots fail. It can be fooled by a rendered-but-hung
splash — if you need a stronger signal, extend the harness (VLM check in
`scripts/desktop-verify.py` is wired but advisory), don't weaken the gate.

## Workflow map

| Workflow | Trigger | Role | Gate? |
|---|---|---|---|
| `build-<variant>.yml` ×5 | nightly cron + dispatch (`flavor` input) | thin caller of build-variant | — |
| `build-flavor.yml` | dispatch | one flavor across all variants | — |
| `build-variant.yml` | workflow_call | staged DAG: S1 base → S2 desktops/base-hwe/nvidia → S3 `<de>-hwe/-nvidia` → S4 combos; per-stage artifact jobs | via callees |
| `reusable-build-image.yml` | workflow_call | build/rechunk/push/manifest/**boot-gate/promote** one image | **yes** |
| `reusable-build-artifacts.yml` | workflow_call | build/**boot-gate**/publish one ISO | **yes** |
| `publish-isos.yml` | Sun 22:00 + dispatch | per-flavor ISOs → R2 + Releases | **yes** |
| `publish-iso-groups.yml` | Sun 23:00 + dispatch | grouped dedup ISOs → R2 | **yes** |
| `test.yml` / `lint.yml` | PR + push main | bats+pytest / shellcheck,yamllint,actionlint,justfmt | blocks PRs |
| `daily-verify.yml` | daily 04:00 | skopeo label/config sanity of published images; files issues | advisory |
| `iso-e2e.yml` | Mon 06:00 + PR-on-harness-changes | smoke of *published* ISOs | advisory |
| `weekly-desktop-screenshots.yml` | Mon 02:00 | desktop capture per variant×DE → R2 + **commits to `docs/images/desktops/`** | advisory |
| `installer-screenshots.yml` | Mon 05:00 | GUI-installer walkthrough capture → **commits to `docs/images/installer/`**, then boot-verifies the installed disk | advisory |
| `weekly-boot-report.yml` / `weekly-qcow2-screenshots.yml` | weekly | aggregate report issue / login-screen shots | advisory |

## Tooling for agents (run these before/instead of pushing to find out)

```bash
just lint                      # same shellcheck/yamllint CI's lint.yml runs
just test                      # bats + pytest, same as test.yml
just build <variant> <flavor>  # real image build (rootful podman, 25-60 min)
just qcow2 <variant> <flavor>  # disk image from a local/ghcr image
just verify-disk <file.qcow2>  # the exact boot gate CI uses (QEMU, no Lima)
./scripts/iso-e2e.sh <iso>     # the exact ISO gate CI uses
just iso <variant> <flavor> ghcr <tag>   # tacklebox live ISO (root)
bash scripts/run-walkthrough.sh <iso> out/   # installer screenshots
```

Matrix sanity check after editing `build-config.yml`:

```bash
yq -o=json '.' .github/build-config.yml | jq '.variants[] | {id, flavors: [.flavors[].id]}'
bats tests/bats/test_build_iso_group.bats   # group-selection expectations
```

## Failure triage cheat-sheet

| Symptom | Likely cause | Where to look |
|---|---|---|
| RUN step exits **126** in Containerfile | script not executable (`git ls-files -s build_scripts/`) | `chmod +x`, commit the mode bit |
| Single-flavor dispatch builds nothing | a stage's `needs` skipped and the job `if:` lacks `!cancelled()` | `build-variant.yml` stage conditions |
| shellcheck green locally, red in CI | CI Ubuntu ships shellcheck **0.9.0**; 0.11 suppresses some findings (e.g. SC2015 with `|| true`) | reproduce: `podman run koalaman/shellcheck:v0.9.0` |
| boot gate red, image "looks fine" | black screendump (missing `-vga virtio`), or genuinely no DM | `boot-gate-*`/`e2e-*` artifacts: serial.log + PNGs |
| xfce build fails resolving packages | repo.tunaos.org is EL10 x86_64 only; check chroot/arch | `build_scripts/xfce.sh`, github-copr repo |
| bonito dnf fails after repo add | tuna-os.repo 404s on Fedora ($releasever=44) with `skip_if_unavailable=False` | never install that repo file on Fedora |
| ISO picks wrong kernel on CentOS | `+debug` kernel sorts first, has no initramfs | dracut workaround, see STATUS_2026-07-02.md |
| tacklebox container fails `podman unshare` | runs as root; unshare is rootless-only | `TACKLEBOX_FROM_SOURCE=1` |

## Publishing surfaces

- **GHCR** `ghcr.io/tuna-os/<variant>` — tags: `<flavor>` (verified),
  `<flavor>-testing` (unverified stream), `<flavor>-YYYYMMDD`,
  `<flavor>-<arch>[-YYYYMMDD]`.
- **R2** (`download.tunaos.org`): `live-isos/*.iso` (+ `-latest` aliases),
  `screenshots/<variant>-<flavor>-latest.png`, `screenshots/boot/…`.
- **Repo commits**: `docs/images/desktops/` and `docs/images/installer/`
  are bot-updated weekly (`[skip ci]` commits by github-actions[bot]).
- **GitHub Releases**: `<flavor>-YYYYMMDD` tags with ISO assets.
