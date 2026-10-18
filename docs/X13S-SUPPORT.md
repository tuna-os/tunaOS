# ThinkPad X13s: support assessment and bring-up requirements

Implementation epic: [#3368](https://github.com/tuna-os/tunaOS/issues/3368).
The epic defines dependencies and evidence gates; this report does not approve
an implementation design or authorize changes to the reference machine.

## Decision and evidence boundary

Use Bonito GNOME on ARM64 as the first X13s target. The proposed profile is
`bonito:gnome-x13s`; it is not an existing flavor or a download instruction.
Start with Fedora's stock kernel. Use a custom kernel only if a measured
failure identifies a configuration gap, fix, or driver that it needs.

This assessment records a read-only investigation on **2026-10-17**, against
TunaOS checkout `ee8c8ce7` and a laptop with postmarketOS. It is a dated
measurement, not a generated matrix of current product support. **The
investigation did not boot or install TunaOS on the laptop.** Published
manifests for ARM64 images do not establish X13s support.

The investigation left the machine's packages, boot configuration, disks,
firmware, network, and power state unchanged. It did not test audio playback,
audio capture, the camera, reboot, suspend, installation, or firmware updates.

## Reference machine

The Lenovo ThinkPad X13s uses **Snapdragon 8cx Gen 3 / SC8280XP**, not Snapdragon
X Elite. Support for this machine says nothing about X1E-based laptops.

| Measurement | Captured result |
|---|---|
| DMI product | `21BYS02100`, ThinkPad X13s Gen 1 |
| Device-tree compatible | `lenovo,thinkpad-x13s`, `qcom,sc8280xp` |
| SoC identification | `SC8280XP`, Snapdragon, SoC ID `449` |
| Memory | Approximately 15 GiB usable; 16 GB-class machine |
| Storage | 476.9 GiB KIOXIA NVMe; encrypted ext4 root |
| EFI System Partition | Approximately 487 MB, mounted at `/boot`; 238 MB free |
| BIOS | `N3HET95W (1.67 )`, date `12/11/2025` as reported by DMI |
| Operating system | postmarketOS edge, systemd-based installation |
| Kernel | `linux-postmarketos-stable-7.2.6-r0`; `uname -r` = `7.2.6` |
| Page size | 4096 bytes; `CONFIG_ARM64_4K_PAGES=y` |
| Boot manager | systemd-boot 261.3; EFI fallback `EFI/BOOT/BOOTAA64.EFI` |
| Secure Boot | Disabled, setup mode |

SSH access used the workstation `dilli` and then `james@kerala-1`. The latter
reports hostname `kerala`. MagicDNS resolved `kerala` to a stale peer, and the
connection timed out. Direct authentication from the investigation workstation
to the active peer failed; the key on `dilli` worked. Do not infer future
reachability from these aliases.

## Working boot chain

The postmarketOS device package was `device-lenovo-21bx-24-r0`, with its stable
kernel subpackage. It depends on `dtbloader`, `systemd-boot`, `alsa-ucm-conf`,
`linux-firmware-ath11k`, `linux-firmware-qca`, `linux-firmware-qcom`,
`libmbim-tools`, and `qmi-utils`, in addition to the postmarketOS base.

The ESP contained `EFI/SYSTEMD/DRIVERS/DTBLOADERAA64.EFI`. The selected
`loader/entries/pmos.conf` used these fields:

```text
title postmarketOS
sort-key postmarketOS
linux vmlinuz
initrd initramfs
devicetree sc8280xp-lenovo-thinkpad-x13s.dtb
```

The active command line included:

```text
arm64.nopauth clk_ignore_unused pd_ignore_unused
```

It also contained postmarketOS root/boot UUID arguments and
`pmos.force-partition-resize`. Those are postmarketOS integration details;
do not copy them into TunaOS. The installed initramfs was about
29.2 MiB and the selected DTB about 163.5 KiB.

Upstream documents `efi=noruntime` as a conditional firmware workaround.
Recent UEFI can omit it with the Linux Boot option enabled. The live
machine did not use it. Bootctl reported Secure Boot disabled; the
investigation did not inspect the Linux Boot menu option. Fedora documents
a minimum BIOS of 1.56. It recommends Linux Boot enabled and Secure Boot
disabled [S1, S2]. Do not change firmware settings or flash a BIOS during
unattended bring-up.

**Do not persist `modprobe.blacklist=qcom_q6v5_pas` as a default.** It is an
older, conditional USB-boot workaround in Fedora guidance, absent from this
installation. SLPI, ADSP, and CDSP each reported `running` under
`qcom_q6v5_pas`. Other devices need services from these processors.

## Hardware observations and limits

| Area | Observed evidence | What remains unverified |
|---|---|---|
| Graphics | GNOME Shell/mutter 50.4 ran as a Wayland server; `msm` supplied atomic modesetting and a GBM renderer/EGL context | Physical display quality, application rendering, external displays, resume |
| Internal display | eDP connected; modes included 1920x1200 and 1600x1200 | Brightness controls and touch operation |
| Wi-Fi | WCN6855 hw2.1, PCI ID `17cb:1103`, `ath11k_pci`; NetworkManager connected; SSH used Wi-Fi | Reconnect, suspend/resume, range and sustained throughput |
| Bluetooth | Controller present and powered | Pairing, audio transport, range and address persistence across boots |
| DSPs | SLPI, ADSP, CDSP each reported `running` with model-specific firmware | Reliability across cold boot, update and resume |
| Audio | ALSA `SC8280XP-LENOVO-X13S`; PulseAudio 17 exposed speakers, headphones, microphone and headset endpoints | Audible playback, recording and safe gain limits |
| Input | Keyboard, pointing-device, touchpad and touchscreen input nodes enumerated | Physical operation, boot-menu input and encrypted-root unlock |
| Battery | `qcom-battmgr` supplied capacity and energy telemetry; discharging during capture | Charging, USB-PD negotiation, idle draw and suspend drain |
| CPU frequency | `qcom-cpufreq-hw` active | Thermal limits and performance under load |
| Sleep | `freeze mem` available, `[s2idle]` selected | Any suspend/resume success or power-saving claim |
| Camera | CCI and CAMSS probing failed with `-110`; no video device exposed | Capture and camera applications |
| Fingerprint | USB device `06cb:00fc` enumerated | libfprint support and enrollment/authentication |
| Modem | No `/dev/wwan*` exposed in the probe | Whether this unit has a usable modem, FCC unlock and connectivity |
| TPM / virtualization | No `/dev/tpmrm0` or `/dev/kvm`; bootctl reported no TPM2 support | No TPM-unlock or KVM support claim is justified |

PipeWire was active but its device graph had no audio sinks or sources.
PulseAudio owned the audio endpoints. Do not use that PipeWire result alone
to diagnose missing audio hardware or claim that a PipeWire-based TunaOS
session works.

The kernel repeatedly logged:

```text
qcom_q6v5_pas 2400000.remoteproc: Handover signaled, but it already happened
```

The log also showed initial failures to load Bluetooth firmware, but the
final controller reported power on. Record these as baseline diagnostics,
not as proof of complete Bluetooth failure or as reasons to disable
remoteproc. The camera failure is a separate measured limitation.

## Kernel, firmware and userspace requirements

### Kernel and initramfs

The stable-kernel recipe from postmarketOS uses upstream stable sources.
It lists PowerPC build patches, not X13s-specific patches [S4]. This supports
a first test with Fedora's stock kernel. It does not prove that Fedora's
configuration will boot. Compare the selected kernel with the configuration
that boots postmarketOS and with upstream guidance for X13s [S1].

The reference kernel enables pinctrl/interconnect support for SC8280XP,
`DRM_MSM`, `ATH11K_PCI`, `BT_QCA`, `SND_SOC_SC8280XP`, `QCOM_Q6V5_PAS`, and
`QCOM_PD_MAPPER`. NVMe and EROFS are modules; dm-crypt and EFI stub support
are enabled. Firmware decompression supports XZ and Zstd.

Start with the device package's audited inventory in `modules-initfs` [S3].
It includes Qualcomm PCIe/USB PHYs, NVMe, I2C-HID input, panel/MSM,
QRTR, PMIC GLINK/altmode, remoteproc and modules for power control. Translate
these requirements to dracut; do not copy scripts from postmarketOS initramfs.
Include the filesystem, crypto and input drivers that the actual
TunaOS installation and passphrase-unlock path need.

The reference kernel has **no `CONFIG_SQUASHFS_ZSTD`**, although XZ SquashFS
and EROFS are enabled. This kernel cannot boot media with the default
Zstd compression. Validate the selected kernel against all live and installed
filesystem/compression formats. TunaOS has a SquashFS workaround for kernels
from Arch, not this package.

### Firmware inventory

The device package lists these early-boot files in `firmware.files` [S3].
Many installed blobs have a `.zst` suffix; Fedora can use different
compression. Resolve the paths in each package and include their dependencies.
Do not hardcode a guessed suffix.

| Function | Logical firmware paths under `lib/firmware/` |
|---|---|
| Adreno GPU | `qcom/a660_gmu.bin`, `qcom/a660_sqe.fw` |
| Wi-Fi | `ath11k/WCN6855/hw2.1/{amss.bin,board-2.bin,m3.bin,regdb.bin}` |
| Bluetooth | `qca/hpbtfw21.tlv`, `qca/hpnv21.b8c`; check board-specific alternatives requested by the selected driver |
| DSP services and topology | `qcom/sc8280xp/LENOVO/21BX/{adspr.jsn,adspua.jsn,audioreach-tplg.bin,battmgr.jsn,cdspr.jsn,qcadsp8280.mbn,qccdsp8280.mbn,qcdxkmsuc8280.mbn,qcslpi8280.mbn}` |
| Video firmware inventory | `qcom/sc8280xp/LENOVO/21BX/qcvss8280.mbn`; presence does not prove accelerated decoding |

Fedora publishes `qcom-firmware` and `atheros-firmware` [S5]. Resolve the
Bluetooth files to their Fedora package as well. Use redistributable
linux-firmware inputs and preserve license notices. Do not distribute
Windows-extracted blobs without a separate license review.

### Userspace and hardware policy

- Use Mesa Freedreno and the ALSA UCM configuration for X13s. The reference has
  `mesa-vulkan-freedreno` and `alsa-ucm-conf` 1.2.16.1. Upstream lists a
  microphone regression in 1.2.14 [S1]. Validate the selected release.
  Do not blindly pin a version to preserve an old workaround.
- Keep the speaker gain limits in UCM. Upstream has not enabled active
  protection for speakers [S1]. Do not test with unrestricted speaker volume.
- Do not install a userspace `pd-mapper` just to satisfy an old meta-package.
  The kernel supplies this function since 6.11. The reference enables
  `CONFIG_QCOM_PD_MAPPER=m` [S1, S6].
- Treat the old `jlinton/x13s` package as configuration history, not a required
  custom kernel. Its scriptlets rebuild dracut, start services and generate a
  Bluetooth address [S6]. Review these assumptions before use in a container
  build. Generate identities for each installation, never once for the shared
  image.
- Evaluate PipeWire quirks against current kernels; do not copy the older
  quantum workaround without a reproduced need. Physical audio still needs
  verification even when endpoints exist.
- Keep modem FCC unlock an explicit user choice. Do not enable every unlock
  script in the distributed image [S7]. Camera, modem and fingerprint claims
  need independent device-level evidence.
- Exclude suspend, Secure Boot, TPM unlock, accelerated video and KVM from the
  initial support claim. Each needs separate proof [S1, S2].

## TunaOS integration map

The following paths are implementation targets, not changes made by this
assessment. The inspected source had no X13s flavor or overlay.

| Work package | Integration points and requirement |
|---|---|
| ARM64 image profile | `.github/build-config.yml`, `scripts/resolve-flavor.sh`, `Containerfile.overlay`, new `build_scripts/overlay/x13s.sh`; reuse the parent-image/overlay convention and reject unsupported architectures |
| Kernel and firmware | Inspect the actual Bonito kernel package/configuration/DTB, firmware and dracut output; use stock Fedora unless a measured gap requires a change |
| Persistent boot arguments | Image-side `/usr/lib/bootc/kargs.d/*.toml`, following `build_scripts/overlay/overrides/nvidia/20-nvidia.sh`; verify first install, upgrade and rollback |
| DTB deployment | Package the kernel-matched X13s DTB and select it in the chosen boot path; both active and rollback kernels must have their own usable boot artifacts |
| Live media | `scripts/build-iso-tacklebox.sh` currently sets only `console=ttyS0`; pass the X13s arguments and arrange DTB/EFI-driver staging and selection in Tacklebox |
| Installer | Inspect Fisherman's actual Bonito bootloader/backend path; preserve device arguments and DTB selection on plain and passphrase-LUKS installations |
| CI and release | Update generated matrix/target data and declared gates with the profile; combine image/artifact checks with physical hardware evidence |
| Documentation | Correct unsupported X13s/X Elite/download claims here and in the sibling user-documentation site before promoting the profile |

Bonito GNOME resolved through `Containerfile.el10`, with no HWE, NVIDIA or
Asahi overlay. Queries to the registries returned these ARM64 children:

```text
quay.io/fedora/fedora-bootc:44
sha256:5d8c73520a3fa7753b5ad8958ad4d553283ba7e5902d054cc4e88078e0522d08

ghcr.io/tuna-os/bonito:gnome
sha256:ed8e5af1a2e1352d3612741c848f1aea856875ec01658745f03c3735432a1abd
```

These are capture-time identifiers, not new build pins or a verified support
matrix. The investigation did not inspect image contents or boot Fedora.

Tacklebox's inspected recipe schema has `kargs`, but no DTB field; its BLS
writer emits `linux`, `initrd` and `options` [S8]. The installed boot arguments
alone therefore do not solve first live boot. Choose and prove a DTB delivery
mechanism: explicit boot-entry selection, an EFI DTB loader, or a verified
firmware handoff. A manual copy to the ESP does not define upgrade/rollback behavior.

Fisherman handles ARM64 names in its GRUB fallback. Its systemd-boot
fallback searches for `systemd-bootx64.efi` and writes `BOOTX64.EFI` [S9]. Fix
that path if the selected installation uses it; this is a source-level risk,
not an observed failed X13s install. Confirm the shipped sibling revisions
before implementation; source-HEAD observations are not release guarantees.

## Bring-up order and completion gates

1. **Inspect and build the image.** Record an immutable OCI digest and the
   kernel version/configuration. Record the DTB, firmware inventory, license
   notices and unpacked initramfs contents. Verify architecture, filesystem
   support and device arguments. Do not publish an untested flavor as supported.
2. **Prepare external live media.** Use its own ESP and ARM64 fallback loader.
   Prove the X13s arguments, DTB, early input, storage and firmware are present
   before first boot. The storage inventory had no external USB device.
   Arrange a separate, explicit execution window with physical recovery access
   before a media write or reboot.
3. **Boot with internal storage unchanged.** Reach the boot menu, graphical
   session and network. Check brightness, keyboard, trackpad, mouse and touch.
   Test Wi-Fi/Bluetooth, safe-volume audio playback/capture, battery telemetry,
   charge control and both USB-C orientations. Capture kernel logs and compare
   the known camera and remoteproc diagnostics. Do not call enumeration a
   functional pass.
4. **Install to a spare external SSD first.** Exercise the normal installer
   and a passphrase-based LUKS path without TPM dependencies. Confirm the
   installed system boots with its own DTB and arguments, including the
   encrypted-root prompt with built-in input. Do not repartition or reuse the
   laptop's small postmarketOS ESP for initial bring-up.
5. **Upgrade and roll back on that external installation.** Use `bootc upgrade`
   with a new kernel, reboot, then rollback and reboot. Verify that each
   deployment selects its own kernel/initramfs/DTB and retains network access,
   graphics and usable input. An ARM VM with QEMU `virt` cannot prove these
   hardware properties on SC8280XP.
6. **Qualify remaining functions separately.** Measure suspend/resume and
   battery drain with a person present. Record camera, modem, fingerprint,
   external display and accelerated-video results or explicit limitations.
   Do not infer support for other Snapdragon platforms.
7. **Promote only with evidence.** Attach artifact digests, relevant CI runs,
   actual install/upgrade/rollback logs, hardware results and known limits.
   Publish accurate download/install guidance and correct false support
   claims. Build success or an SSH session under postmarketOS is insufficient.

## Evidence commands

These read-only probes record the assessment, not a full qualification of the
hardware. Run them on the appropriate host; package names and permissions can
differ on Fedora. Kernel logs can contain private details. Redact them before
publication.

```sh
# Local checkout: published ARM64 inputs and current flavor routing.
./scripts/get-base-image.sh bonito linux/arm64
./scripts/resolve-flavor.sh bonito gnome
podman manifest inspect quay.io/fedora/fedora-bootc:44
podman manifest inspect ghcr.io/tuna-os/bonito:gnome

# Reference laptop: identity, boot artifacts, modules and package inventories.
uname -a
cat /etc/os-release /proc/cmdline
tr '\000' '\n' < /proc/device-tree/compatible
getconf PAGESIZE
lsblk -o NAME,SIZE,TYPE,FSTYPE,MOUNTPOINTS,PARTLABEL
sudo -n bootctl status --no-pager
sudo -n cat /boot/loader/entries/pmos.conf
apk info -R device-lenovo-21bx device-lenovo-21bx-kernel-stable
cat /usr/share/mkinitfs/modules/00-device-lenovo-21bx.modules
cat /usr/share/mkinitfs/files/firmware.files
zcat /proc/config.gz

# Runtime evidence; none of these trigger suspend or audio playback.
nmcli -t -f DEVICE,TYPE,STATE device status
cat /sys/class/remoteproc/remoteproc*/state
cat /proc/asound/cards
XDG_RUNTIME_DIR=/run/user/10000 pactl list short sinks
XDG_RUNTIME_DIR=/run/user/10000 pactl list short sources
bluetoothctl show
cat /sys/power/state /sys/power/mem_sleep
sudo -n dmesg
```

## Primary sources

- **S1:** [Johan Hovold's X13s status](https://github.com/jhovold/linux/wiki/X13s):
  mainline features, configuration guidance, boot arguments, firmware and
  userspace requirements, known limitations. Check each workaround against
  the selected kernel and package versions.
- **S2:** [Fedora guidance for X13s](https://fedoraproject.org/wiki/Thinkpad_X13s):
  BIOS requirements, Linux Boot, Secure Boot, DTB paths and historical boot
  workarounds. The [broader Snapdragon install guidance](https://fedoraproject.org/wiki/Snapdragon_WoA_Laptop_Install)
  also covers other hardware. Check the SoC before use.
- **S3:** postmarketOS [device package](https://gitlab.postmarketos.org/postmarketOS/pmaports/-/blob/main/device/community/device-lenovo-21bx/APKBUILD),
  [firmware inventory](https://gitlab.postmarketos.org/postmarketOS/pmaports/-/blob/main/device/community/device-lenovo-21bx/firmware.files),
  [early modules](https://gitlab.postmarketos.org/postmarketOS/pmaports/-/blob/main/device/community/device-lenovo-21bx/modules-initfs),
  and [boot arguments](https://gitlab.postmarketos.org/postmarketOS/pmaports/-/blob/main/device/community/device-lenovo-21bx/kernel-cmdline.conf).
- **S4:** postmarketOS [stable-kernel recipe](https://gitlab.postmarketos.org/postmarketOS/pmaports/-/blob/main/device/main/linux-postmarketos-stable/APKBUILD).
  The fetched recipe was 7.2.11; the installed reference kernel was 7.2.6.
- **S5:** Fedora metadata for [Qualcomm firmware](https://packages.fedoraproject.org/pkgs/linux-firmware/qcom-firmware/)
  and [Atheros firmware](https://packages.fedoraproject.org/pkgs/linux-firmware/atheros-firmware/).
  Retain the redistribution terms for each file.
- **S6:** The [X13s meta-package](https://github.com/fedora-arm/x13s/blob/master/x13s.spec)
  from Fedora ARM and its [dracut configuration](https://github.com/fedora-arm/x13s/blob/master/x13s.conf).
  These older scriptlets are not a container-safe integration contract.
- **S7:** [ModemManager FCC-unlock policy](https://modemmanager.org/docs/modemmanager/fcc-unlock/).
- **S8:** Tacklebox [recipe schema](https://github.com/tuna-os/tacklebox/blob/main/internal/recipe/recipe.go),
  [BLS writer](https://github.com/tuna-os/tacklebox/blob/main/internal/install/bootloader.go),
  and [ISO assembly](https://github.com/tuna-os/tacklebox/blob/main/internal/target/iso.go).
- **S9:** Fisherman [systemd-boot fallback](https://github.com/tuna-os/fisherman/blob/HEAD/fisherman/internal/install/systemdboot.go)
  and [GRUB fallback](https://github.com/tuna-os/fisherman/blob/HEAD/fisherman/internal/install/grub.go).
