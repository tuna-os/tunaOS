# Azure Linux — what it is

Written before any build work, so the first Containerfile does not start from a
wrong picture. Azure Linux 4.0 is **not** the tdnf-based CBL-Mariner that older
write-ups describe, and `ID_LIKE=fedora` does not make it Fedora (see
[HUMMINGBIRD.md](HUMMINGBIRD.md) for the same mistake made once already).

Status: **Proposal**. No workflow, Containerfile or `tunaos.toml` row exists.
The decision is in #4086; this page and the admission record are issue #4376.

## The short version

**Azure Linux 4.0 is Fedora 43 plus Microsoft overlays, built with dnf5, in
public preview, with no published support dates and no official bootc base
image.**

| | |
|---|---|
| Lineage | Renamed CBL-Mariner. Microsoft-maintained, MIT-licensed distro definitions in [microsoft/azurelinux](https://github.com/microsoft/azurelinux) |
| 4.0 base | Fedora 43 dist-git pinned at a snapshot, with Microsoft overlays. Package manager is **dnf5, not tdnf** |
| 3.0 | GA, tdnf, systemd 255. Its `prod/base` repo has no `bootc`, `bootupd` or `composefs`. This page does not cover 3.0 |
| Support | 4.0 is **public preview**. No support dates are published |
| bootc | The 4.0 repos package `bootc`, `ostree`, `rpm-ostree`, `bootupd` and `composefs`. There is **no official bootc base image**. The upstream request, [microsoft/azurelinux#18817](https://github.com/microsoft/azurelinux/issues/18817), has no commitment |
| Desktop | Out of scope for Microsoft: no GUI, no ISO, no bare metal. `gnome-shell`, `gdm` and `nautilus` are in neither Azure Linux repository |
| Defaults | `systemd-networkd` and `cloud-init`, ext4, GRUB2, SELinux enforcing |

Sources and the full measurement are in #4086 (measured 2026-10-29).

## What this means for tunaOS

There is nothing to `FROM`. `hummingbird`, Alma, CentOS and Fedora all start
from a published bootc image (`base_image` in `tunaos.toml`). Azure Linux
publishes a plain container, so a variant is a *bootcification* of that
container, the way `Containerfile.debian`, `.arch`, `.opensuse` and `.ubuntu`
work. It does not reuse `Containerfile.el10`.

The maintainer decision on #4086 (2026-10-30) admits one thing: a headless
**`base`** variant, **experimental** tier. No desktop flavor, no ISO. A desktop
needs a sanctioned package source for `gnome-shell`/`gdm`/`nautilus` on Azure
Linux first ([PACKAGE-SOURCING.md](../PACKAGE-SOURCING.md)); none exists.

## Pinned base image

The base is `mcr.microsoft.com/azurelinux-beta/base/core:4.0`. A floating tag
is never used. The Containerfile pins a digest.

| Platform | Digest |
|---|---|
| `linux/amd64` | `sha256:9070b05147f01e5a4bac47723c95f2555e11b9d3324c1df1910ff3545b7ce319` |
| `linux/arm64` (v8) | `sha256:e541db83a8511c25fa1dd989161263874b7395ddd588f5caaa25453ea4e23263` |
| manifest list (`:4.0`) | `sha256:63ef5dda2fb5681ae3aa5c9597a8c4b24364da91ec459b419fa3c38160595fae` |

The image was created 2026-05-27. The per-platform digests were first resolved
on 2026-11-06 with `skopeo inspect --raw`. They were resolved again on
2026-11-25 by reading the manifest list from the registry API and confirming
the same two per-platform digests:

```bash
curl -sD - "https://mcr.microsoft.com/v2/azurelinux-beta/base/core/manifests/4.0" \
  -H "Accept: application/vnd.docker.distribution.manifest.list.v2+json" -o index.json
# docker-content-digest header = the manifest-list digest above;
# index.json .manifests[].digest = the per-platform digests above
```

`docker buildx imagetools inspect mcr.microsoft.com/azurelinux-beta/base/core:4.0`
shows the same values. The image lags the package repositories by about five
months, and the preview repository has no snapshots. The base is pinned and the
packages float. That is the rolling/pinned mismatch described in
[HUMMINGBIRD.md](HUMMINGBIRD.md).

## Architectures

The base image publishes **amd64 and arm64**, so both are candidates. The first
build is **amd64**; arm64 is a stated follow-up, not an omission. arm64 joins
when `bootc install to-disk` is shown to work on a native arm64 runner (the
proof of concept reports that it fails under user-mode emulation) and
`packages.microsoft.com/azurelinux/4/preview/base/aarch64` carries every
package the Containerfile installs. Until then `tunaos.toml` must list only
`linux/amd64` in the variant's `platforms`. If arm64 is added later, the
admission record changes in the same PR.

## Third-party proof of concept

[JayDoubleu/azurelinux-bootc](https://github.com/JayDoubleu/azurelinux-bootc)
(MIT, created 2026-09-08, last push 2026-10-23) is the best evidence that a
bootc image is feasible. Its `STATUS.md` claims are **author-reported and not
reproduced by tunaOS**:

- `bootc install to-disk` boots under QEMU/OVMF on x86_64 and aarch64.
- `bootc upgrade`, `rollback`, sigstore policy and
  `rpm-ostree compose build-chunked-oci` work.
- SELinux is enforcing, and `bootc container lint` reports 12 checks and 1
  warning.

The fixes it needed are the ones an official image would settle: move `vmlinuz`
out of `/boot` into `/usr/lib/modules/<kver>/`, stage `/boot/efi` for
`bootupctl backend generate-update-metadata`, add `bubblewrap` and
`grub2-pc-modules`, move the rpmdb to `/usr/share/rpm`, mask
`systemd-firstboot`, and unlock root's `!unprovisioned` shadow field. It has no
`bootc-base-imagectl`, and its packages are unpinned.

Use it as a starting point for the Containerfile, not as evidence. The first
tunaOS run is the evidence.

## Rebuild-config completeness (#1763)

[VARIANT-LIFECYCLE.md](../VARIANT-LIFECYCLE.md) item 5 applies before any
workflow lands. #1341 and #1763 are the failures to avoid: a variant declared
with flavors, architectures or manifest sections that do not exist. The check
for this variant:

| Check | Required result |
|---|---|
| Package repository reachable per declared arch | `https://packages.microsoft.com/azurelinux/4/preview/base/<arch>/repodata/repomd.xml` returns HTTP 200 for each arch in `platforms` |
| Mandatory base packages | `bootc`, `ostree`, `bootupd`, `composefs`, `rpm-ostree`, `bubblewrap`, `grub2-pc-modules` and `xfsprogs` resolve on every declared arch (`10-base-packages.sh` exits without `xfsprogs`) |
| Declared flavors | Only `base`. Any desktop flavor in `tunaos.toml` needs a concrete `packages.azurelinux` manifest section first, so none is declared |
| Version label | `reusable-build-image.yml` defaults `major-version` to `10`. An Azure Linux image must carry `4` (from `VERSION_ID`), not `10` |
| Boot Gate | `verify-base-contract.sh` reaches `TUNAOS_BASE_CONTRACT_OK`. Whether the system bus is up on the default `systemd-networkd`/`cloud-init` image is **unverified** |

## Risks that stay open

- **Redistribution and trademark.** No terms were reviewed for pushing binaries
  from MCR and `packages.microsoft.com` into a public `ghcr.io/tuna-os` image.
  `os-release` carries `CPE_NAME=cpe:2.3:o:microsoft:azure_linux`. Microsoft's
  README forbids confusion or implied sponsorship in modified versions. A
  maintainer must read this before the first publish.
- **Support scope.** Microsoft supports Azure scenarios only. A tunaOS image on
  bare metal is outside every supported scenario.
- **Duplication.** The variant adds Microsoft's kernel, hardening and Azure
  agents. It adds no desktop base. `bonito` already carries the Fedora lineage.
- **Kernel config.** The shipped kernel has `CONFIG_BT`, `CONFIG_WLAN` and
  `CONFIG_SOUND` off. It is a server and cloud kernel.

## Triggers to widen scope

Any one of these, plus an owner, reopens the question beyond headless `base`:

1. #18817 is accepted (an official bootc base on MCR), or 4.0 reaches GA with
   published support dates. Then the Containerfile gets simpler.
2. GNOME or KDE runtime packages appear in an Azure Linux channel, or a
   sanctioned `tunaos-packages` target for Azure Linux exists.
