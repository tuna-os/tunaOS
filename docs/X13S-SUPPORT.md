# ThinkPad X13s support

**Status:** image profile defined; the first ARM64 child build and its generated
inspection report are not yet available. TunaOS has not booted, installed, or
qualified this profile on a ThinkPad X13s.

This page is for the X13s Gen 1 from Lenovo (`lenovo,thinkpad-x13s`).
It uses the Qualcomm SC8280XP / Snapdragon 8cx Gen 3 SoC. This page excludes
laptops with Snapdragon X Elite and all other Windows-on-ARM laptops.

Issues: [qualification epic #3368](https://github.com/tuna-os/tunaOS/issues/3368)
and [W1 #3377](https://github.com/tuna-os/tunaOS/issues/3377).

## W1 image profile

`bonito:gnome-x13s` is an ARM64-only stage-3 child of `bonito:gnome`. The
profile uses `Containerfile.overlay` and `build_scripts/overlay/x13s.sh`.
It keeps Fedora's stock kernel and creates no ISO or QCOW2. The overlay rejects
non-ARM64 and non-Fedora parents, then writes its inventory to
`/usr/share/tunaos/x13s-inspection.txt` and the image-build log.

The inventory records:

- the kernel version and Fedora kernel packages;
- the SC8280XP-relevant kernel configuration and a missing-symbol count;
- representative early-boot, display, input, remoteproc, network and audio
  modules;
- every X13s DTB in the kernel payload;
- the board firmware list, including compressed Fedora filenames and explicit
  missing entries.

Missing firmware remains evidence in W1, not an opportunistic download.
W2 will add the complete early-boot payload to the initramfs.

## Stock Fedora payload measured before admission

The following records an inspection made before admission using the ARM64
parent image. This is not evidence from a completed `bonito:gnome-x13s` build.
The source profile resolved on 2026-10-17 to:

```text
ghcr.io/tuna-os/bonito:gnome (linux/arm64)
sha256:ed8e5af1a2e1352d3612741c848f1aea856875ec01658745f03c3735432a1abd

quay.io/fedora/fedora-bootc:44 (linux/arm64)
sha256:5d8c73520a3fa7753b5ad8958ad4d553283ba7e5902d054cc4e88078e0522d08
```

The inspected parent payload used Fedora kernel `7.2.11-200.fc44.aarch64` and
contained both X13s DTBs:

```text
/usr/lib/modules/7.2.11-200.fc44.aarch64/dtb/qcom/sc8280xp-lenovo-thinkpad-x13s.dtb
/usr/lib/modules/7.2.11-200.fc44.aarch64/dtb/qcom/sc8280xp-lenovo-thinkpad-x13s-el2.dtb
```

The 25 configuration symbols checked by `x13s.sh` are all enabled as built-ins
or modules, including `CONFIG_PCIE_QCOM`, `CONFIG_DRM_MSM`,
`CONFIG_QCOM_Q6V5_PAS`, `CONFIG_ATH11K_PCI`, `CONFIG_SND_SOC_SC8280XP` and
`CONFIG_SQUASHFS_ZSTD`. Representative module objects for MSM display, NVMe,
I2C-HID, WCN6855 Wi-Fi, PMIC GLINK, battery management, Qualcomm remoteproc and
SC8280XP audio are present. The result gives no reason to replace the Fedora
kernel.

Fedora's parent payload supplies the WCN6855 Wi-Fi files and the compressed QCA
files for board Bluetooth. It did not contain the X13s
`qcom/sc8280xp/LENOVO/21BX/` DSP/topology directory or `qcom/a660_*` GPU
firmware. W2 must resolve and verify those gaps before a live artifact can be
called complete.

The first normal ARM64 child build will create the immutable digest and full
generated report recorded by issue #3377. Until that succeeds, only the dated
parent-payload measurement above is available.

## DTB boot-path decision for W4

W4 will retain Fedora's shim and GRUB path and use Fedora 44's
`kernel-dtb-loader` vmlinuz. Its systemd-stub selects a kernel-embedded DTB by
CHID while GRUB continues to supply the initramfs and command line. This keeps
the selected DTB version-matched to its kernel and avoids a standalone
`DTBLOADERAA64.EFI` with a fixed ESP DTB.

Tacklebox must stage the `kernel-dtb-loader` vmlinuz from the same kernel build
that supplies the image modules and must preserve the ARM64 `BOOTAA64.EFI`
chain. Generic ARM64 QEMU can prove that this image still boots. It cannot
prove that SC8280XP selects the DTB. It also cannot prove support for X13s.

The installed-system mechanism remains a W3/W5 question: Fisherman and bootc
must preserve a kernel-matched DTB for every deployment and rollback. No
one-time copy to the ESP satisfies that lifecycle requirement.

Primary design evidence:

- [Fedora 44 automatic DTB selection](https://fedoraproject.org/wiki/Changes/Automatic_DTB_selection_for_aarch64_EFI_systems)
- [X13s notes from Fedora](https://fedoraproject.org/wiki/Thinkpad_X13s)
- [upstream X13s status and required boot arguments](https://github.com/jhovold/linux/wiki/X13s)
- [postmarketOS early-module inventory](https://gitlab.postmarketos.org/postmarketOS/pmaports/-/blob/main/device/community/device-lenovo-21bx/modules-initfs)
- [postmarketOS firmware inventory](https://gitlab.postmarketos.org/postmarketOS/pmaports/-/blob/main/device/community/device-lenovo-21bx/firmware.files)

## Safety boundary

W1 does not write to real hardware, boot it, or change its partitions or
firmware. It makes no Secure Boot, modem, camera, audio, suspend or installer
claim. Those claims need the later work packages and physical results.
