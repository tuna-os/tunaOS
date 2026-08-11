# ADR 0003: co-build bootc (OCI) and mkosi DDI from a single recipe tree

- Status: proposed (investigation + POC scaffolding; no build has been executed)
- Date: 2026-08-11
- Issue: [#999](https://github.com/tuna-os/tunaOS/issues/999)
- Supersedes: [docs/mkosi-investigation.md](../mkosi-investigation.md) (research phase; this ADR adds concrete POC scaffolding)

## Context

This repo builds nine variants with hand-maintained Containerfiles
(`Containerfile.arch`, `.el10`, `.ubuntu`, `.debian`, `.opensuse`, `.gentoo`,
`.overlay`, `.custom`, `.final`). The niri stack already sources its DMS
payload from `zirconium-dev/zirconium` — an **mkosi** project — and the
`install-zirconium.sh` stopgap exists only because this repo doesn't build the
payload itself.

The ask in #999 is twofold:

1. Can mkosi replace (or wrap) the Containerfile-based build backend?
2. Can we emit both a bootc OCI image **and** a DDI (Discoverable Disk Image)
   from the **same** recipe tree — and **boot both** in QEMU?

This repo has no mkosi profiles today. A previous investigation
(`docs/mkosi-investigation.md`, merged in #1227) established that zirconium's
`bootc-ostree` profile produces a plain `Format=oci` image — not a new
artifact type — and that its DDI (`sysupdate`) profile is a different OS
deployment model (dm-verity + UKI + systemd-sysupdate, no ostree/bootc), not
an alternate packaging of the same rootfs.

## Decision

**Build exactly one prototype variant (`bonito:gnome`, Fedora 44 base) as**
**both a bootc OCI image and a plain DDI disk image from the same `mkosi/`**
**tree using two output profiles.** This is the lowest-risk entry point:
Fedora matches zirconium's base, so no distro-porting work is needed; bonito
is the TunaOS variant closest to the reference; gnome is the simplest desktop
to validate. The DDI produced here is a **plain disk image** (`Format=disk`,
`Bootable=yes`, `Bootloader=systemd-boot`), **not** the sysupdate/verity
profile — see Finding 2 in the investigation doc for why a particleOS-style
DDI is a separate, much larger undertaking.

Concretely: one `mkosi/` directory containing `mkosi.conf`,
`mkosi.conf.d/bootc.conf`, `mkosi.conf.d/ddi.conf`, `mkosi.extra/`, and
any `mkosi.postinst.chroot` scripts — from which a single `mkosi build`
chooses the output format via `--profile` or `--include-directory`.

## POC scaffolding: directory layout

```
mkosi/
├── mkosi.conf                      # base config: distro, packages, extra tree
├── mkosi.extra/                    # system_files overlay (1:1 with existing system_files/)
│   └── usr/
│       └── lib/
│           └── bootc/
│               └── install/
│                   └── 00-tunaos.toml
├── mkosi.postinst.chroot           # post-install script (maps to build_scripts/*.sh)
├── mkosi.finalize.chroot           # finalization (cleanup, tmpfiles)
├── mkosi.conf.d/
│   ├── bootc.conf                  # profile: OCI output, bootc=1 label
│   └── ddi.conf                    # profile: disk output, systemd-boot
├── mkosi.repart/                   # repartition definitions for the DDI
│   └── 00-esp.conf                 # EFI System Partition
│   └── 10-root.conf                # root partition (ext4 or btrfs)
└── mkosi.profiles/                 # (optional) per-desktop or per-variant overrides
    └── gnome/
        └── mkosi.conf.d/
            └── 10-packages.conf
```

## Concrete mkosi profiles

### Base: `mkosi/mkosi.conf`

This is the common root — same source tree, same packages, same extra files,
but NO output format pinned here. The output format is selected by the profile
drop-in.

```ini
[Config]
MinimumVersion=26

[Distribution]
Distribution=fedora
Release=44

[Content]
Hostname=tunaos
# Packages: the intersection of what Containerfile.el10 installs in its base-no-de
# stage, translated to Fedora package names. This is a representative subset for
# a gnome desktop POC; the full matrix of variant-specific packages belongs in
# per-variant profile drops.
Packages=
    @gnome-desktop
    @core
    @standard
    bootc
    systemd-boot
    systemd-boot-unsigned
    firefox
    flatpak
    podman
    toolbox
    distrobox
    just
    fish
    git
    curl
    wget
    NetworkManager-wifi
    NetworkManager-bluetooth
    fprintd
    fwupd
    power-profiles-daemon
    xdg-desktop-portal-gnome
    xdg-desktop-portal-gtk
    pipewire
    wireplumber
    mesa-dri-drivers
    mesa-vulkan-drivers

[Build]
ToolsTree=default
History=yes
CacheDirectory=mkosi.cache
Incremental=yes

[Validation]
SecureBoot=no
SignExpectedPcr=no

[Output]
ImageId=TunaOS
OutputDirectory=mkosi.output
ManifestFormat=json
# No Format= or Output= here — let profiles decide
```

### Bootc (OCI) profile: `mkosi/mkosi.conf.d/bootc.conf`

Modeled on zirconium's `bootc-ostree` profile. Produces a standard OCI image
with `containers.bootc=1` label — indistinguishable from a buildah-built image
at the point tacklebox / cosign / `bootc install to-disk` consume it.

```ini
# bootc profile: emit a plain OCI image with bootc label.
# Intended to be a drop-in replacement for the buildah-built image
# at exactly the boundary this repo already treats as one (a tagged OCI image).
[Content]
Bootable=no
KernelCommandLine=
RemoveFiles=
    /usr/etc
    /var/
    /boot/*

[Output]
OciLabels=containers.bootc=1
Format=oci
```

### DDI profile: `mkosi/mkosi.conf.d/ddi.conf`

A **plain disk image** — not sysupdate, not dm-verity. Bootable with
systemd-boot, suitable for `systemd-sysext`, portable services, or VM images
(the issue's own use-cases). Uses a UKI (Unified Kernel Image) for simplicity.

```ini
# DDI profile: plain discoverable disk image, bootable via systemd-boot.
# NOT the sysupdate/verity profile — this is a straightforward disk image
# for VM / sysext / portable-service use, not a particleOS deployment.
[Output]
Format=disk
SplitArtifacts=uki

[Content]
Bootable=yes
Bootloader=systemd-boot
KernelCommandLine=
    console=tty0
    console=ttyS0
    systemd.unit=graphical.target
    rhgb quiet

# The UKI is self-contained — kernel + initrd + cmdline in one EFI binary.
UnifiedKernelImage=yes
```

### Partition table for the DDI: `mkosi/mkosi.repart/00-esp.conf`

```ini
[Partition]
Type=esp
SizeMinBytes=512M
SizeMaxBytes=1G
Format=vfat
```

And `mkosi/mkosi.repart/10-root.conf`:

```ini
[Partition]
Type=root
SizeMinBytes=8G
Format=ext4
```

## Concrete build commands

### Prerequisites

mkosi v26+ is required (shipped stable 2025-12-17). On a Fedora 42+ host:

```bash
sudo dnf install mkosi systemd-boot-unsigned
# Or via pip:
pipx install mkosi
```

### Build the bootc OCI image

```bash
# From the repo root.
# mkosi reads mkosi.conf + mkosi.conf.d/bootc.conf (INI merge — later files
# in conf.d/ override earlier ones; profile drops override conf.d).
mkosi \
    --directory=mkosi \
    --include-directory=mkosi/mkosi.conf.d \
    --profile=bootc \
    build

# Output: mkosi/mkosi.output/TunaOS_<version>_<arch>.oci
# (or a directory with an oci-layout if Format=oci produces a layout)
```

Verify the output is a valid bootc image:

```bash
# Load into podman
IMAGE_REF="localhost/tunaos-bonito-gnome:mkosi-poc"
podman load -i mkosi/mkosi.output/*.oci
podman tag $(podman images --format '{{.ID}}' | head -1) "$IMAGE_REF"

# Run bootc's own lint
podman run --rm --entrypoint=bootc "$IMAGE_REF" container lint

# Rechunk (same tooling the existing pipeline uses)
# scripts/rechunk.sh operates on an image ref
```

Then feed it through the existing, **unmodified** pipeline gate:

```bash
# 1. LUKS install-to-disk smoke test (this repo's acceptance gate)
just qcow2 "$IMAGE_REF" gnome
# ...produces bonito.qcow2...

# 2. QEMU boot (reuse iso-e2e.sh's QEMU path)
# scripts/iso-e2e.sh has a --disk mode for qcow2 images:
sudo ./scripts/iso-e2e.sh bonito.qcow2 --disk --output verify-out --timeout 300

# 3. bootc lifecycle (update / rebase / rollback)
# scripts/lifecycle-test.sh if applicable
```

If the mkosi-built image passes the existing unmodified LUKS E2E gate,
**Finding 1 from the investigation is confirmed in practice**: mkosi and
buildah are interchangeable as OCI producers for this repo's pipeline.

### Build the DDI disk image

```bash
# Same recipe tree, different profile — no reconfiguration needed.
mkosi \
    --directory=mkosi \
    --include-directory=mkosi/mkosi.conf.d \
    --profile=ddi \
    build

# Output: mkosi/mkosi.output/TunaOS_<version>_<arch>.raw
# (a raw disk image with GPT, ESP, and root partition)
```

Boot the DDI in QEMU:

```bash
# Direct kernel boot from the UKI (simplest path)
qemu-system-x86_64 \
    -machine q35,accel=kvm \
    -cpu host \
    -smp 4 \
    -m 4096 \
    -bios /usr/share/edk2/ovmf/OVMF_CODE.fd \
    -drive file=mkosi/mkosi.output/TunaOS_*.raw,format=raw,if=virtio \
    -display gtk \
    -serial stdio

# Or convert to qcow2 and use the existing QEMU harness
qemu-img convert -f raw -O qcow2 \
    mkosi/mkosi.output/TunaOS_*.raw \
    bonito-ddi.qcow2

sudo ./scripts/iso-e2e.sh bonito-ddi.qcow2 --disk --output verify-ddi-out --timeout 300
```

### Build both in one pass (the "co-build" promise)

```bash
# mkosi supports --format to override the output format without changing configs.
# Build the bootc OCI:
mkosi --directory=mkosi --include-directory=mkosi/mkosi.conf.d \
    --profile=bootc --format=oci build

# Then build the DDI from the SAME tree (cached packages, no rebuild):
mkosi --directory=mkosi --include-directory=mkosi/mkosi.conf.d \
    --profile=ddi --format=disk build
```

With `Incremental=yes` in the base config, the second build reuses the cached
package install tree and only re-emits a different output format — both
artifacts are produced from one package-resolution pass.

## What maps cleanly vs. what doesn't

### Clean mappings

| Current (Containerfile) | mkosi equivalent |
|---|---|
| `FROM ${BASE_IMAGE}` | `[Distribution]` / `[Content] BaseImage=` |
| `COPY system_files /files` | `mkosi.extra/` (1:1 filesystem overlay) |
| `RUN ... /build_scripts/00-copy-files.sh` | `mkosi.extra/` + `mkosi.postinst.chroot` |
| `RUN ... /build_scripts/01-workarounds.sh` | `mkosi.postinst.chroot` |
| `RUN ... install_base_packages_no_de` | `[Content] Packages=` |
| `ARG ENABLE_HWE / ENABLE_NVIDIA / DESKTOP_FLAVOR` | `mkosi.profiles/<variant>/mkosi.conf.d/` |
| `manifests/desktops/` (package lists) | `[Content] Packages=` in profile drops |
| `system_files_overrides/` | Per-profile `mkosi.extra/` trees or `mkosi.conf.d/` with `ExtraTrees=` |
| `bootc container lint` | same (image-format-agnostic) |
| `bootc install to-disk` | same |
| tacklebox → ISO | same (pulls OCI image by ref) |
| cosign sign + SBOM | `Format=oci` → same signing path |

### Known friction points

1. **RHSM secrets.** The current `Containerfile.el10` mounts RHSM credentials
   via `--secret id=rhsm`. mkosi has a `[Build] Credentials=` mechanism
   (`mkosi.credentials/`) that can carry subscription-manager certs, but this
   has not been tested end-to-end. For Fedora-based POC this is a non-issue
   (no RHSM needed); for EL variants, it requires validation.

2. **Overlay stages (hwe/nvidia/cachyos/asahi).** `Containerfile.overlay` is
   parametrized by `OVERLAY_TYPE` + `DESKTOP_FLAVOR`. In mkosi this maps to
   profile drops (e.g. `mkosi.profiles/nvidia/mkosi.conf.d/` with NVIDIA
   packages + akmods), but the kernel-module build step (akmods → kmod RPM)
   that currently runs inside `Containerfile.hwe` may need to move to a
   `mkosi.build.chroot` or a pre-built kmod layer. The akmods post-build step
   in the current pipeline (`Containerfile.hwe` lines 15–100 approx.) is the
   highest-risk part to port.

3. **Multi-stage builds.** The current Containerfiles use `FROM ... AS
   <stage>` extensively (e.g. `FROM scratch AS context`). mkosi has no direct
   equivalent of Dockerfile multi-stage builds. Workarounds:
   - Pre-build dependency layers as OCI images and reference them via
     `[Content] BaseImage=` — this is how `FROM ${COMMON_IMAGE_REF}` /
     `FROM ${BREW_IMAGE_REF}` would be handled.
   - Use `mkosi.sandbox` scripts to pull/install from external OCI layers.

4. **`build_scripts/` porting.** The 30+ shell scripts in `build_scripts/`
   would move to `mkosi.postinst.chroot` (runs inside the image after package
   install) and `mkosi.finalize.chroot` (runs after image assembly). Most
   scripts are distro-agnostic (they `cp` files, `systemctl enable` services,
   etc.) and would port directly. Distro-specific scripts (e.g.
   `10-base-packages.sh` with its `dnf`/`apt`/`zypper`/`pacman` dispatch)
   would be replaced by `[Content] Packages=` in per-distro profiles.

5. **aarch64.** mkosi supports cross-architecture builds via
   `--architecture=arm64`, but `bootc install to-disk` on a foreign
   architecture requires QEMU user-mode emulation (`qemu-aarch64-static`).
   The existing pipeline already handles this in `build-variant.yml`.

6. **Signing.** `Format=oci` images should sign identically through the
   existing `reusable-build-image.yml` cosign step (same OCI format at the
   point signing happens), but this is untested.

## CI integration sketch

A POC workflow (NOT implemented here — this is the investigation deliverable)
would run as an optional, non-blocking job in `build-variant.yml`:

```yaml
# In build-variant.yml, as an experimental step after the bonito:gnome build:
mkosi-poc:
  if: github.event_name == 'workflow_dispatch' && inputs.variant == 'bonito'
  runs-on: ubuntu-24.04
  steps:
    - uses: actions/checkout@v4
    - name: Install mkosi
      run: pipx install mkosi
    - name: Build bootc OCI
      run: |
        mkosi --directory=mkosi --profile=bootc build
        podman load -i mkosi.output/*.oci
        podman run --rm --entrypoint=bootc localhost/tunaos-bonito-gnome:mkosi-poc container lint
    - name: Build DDI
      run: mkosi --directory=mkosi --profile=ddi build
    - name: Boot smoke (QEMU)
      run: |
        qemu-img convert -f raw -O qcow2 mkosi.output/*.raw ddi.qcow2
        sudo ./scripts/iso-e2e.sh ddi.qcow2 --disk --output ddi-boot-out --timeout 300
```

The POC job MUST be `continue-on-error: true` and not added to any branch
protection required-check list — per AGENTS.md guard rails, `paths:` filters
or required-check context changes need explicit approval.

## Recommendation

**Hybrid: add mkosi as an alternate backend behind a Justfile flag, with ONE**
**proven variant first, before considering any Containerfile removal.**

Concrete path:

1. **Week 1–2:** Land the `mkosi/` directory layout from this ADR (the
   profile files are inert — no pipeline change, no build triggered).
2. **Week 2–3:** Someone with actual build tooling runs the POC commands
   above against `bonito:gnome`, confirms the bootc OCI passes the existing
   LUKS E2E gate unmodified, and confirms the DDI boots in QEMU.
3. **Week 3–4:** Add `just mkosi-bootc bonito gnome` and
   `just mkosi-ddi bonito gnome` recipes that wrap the `mkosi build` calls.
4. **Post-POC:** If the gate passes, add the optional CI job above. Do NOT
   remove any Containerfile or change any production build path until the
   mkosi-built image has been the actual published image for at least one
   release cycle with zero regressions.

The DDI path is a **separate track** (the priority is bootc OCI parity). The
DDI POC can proceed in parallel but should not gate the bootc POC.

## Explicit non-goals for this ADR

- **Not** proposing removal of any Containerfile.
- **Not** proposing a `systemd-sysupdate` / dm-verity migration.
- **Not** proposing workflow-file changes (the bot lacks `workflows` permission).
- **Not** proposing changes to required-check branch-protection contexts.
- **Not** implementing `mkosi.postinst.chroot` or `mkosi.finalize.chroot` scripts
  (those belong in the actual POC implementation, not the investigation).

## References

- [docs/mkosi-investigation.md](../mkosi-investigation.md) — research phase findings
- [zirconium-dev/zirconium](https://github.com/zirconium-dev/zirconium) — mkosi reference
- [docs/build-pipeline.md](../build-pipeline.md) — current build pipeline
- [docs/PIPELINE.md](../PIPELINE.md) — CI/CD overview
- [docs/IMAGE-FACTORY-GATE.md](../IMAGE-FACTORY-GATE.md) — completion gate
- [mkosi documentation](https://github.com/systemd/mkosi)
