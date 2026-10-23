# ThinkPad X13s support

**Status:** `bonito:gnome-x13s` carries the W2 payload: firmware, DTB, kernel
arguments and early-boot drivers. TunaOS has not yet booted, installed or
qualified it on a ThinkPad X13s. Use the procedure below to try it.

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

## W2 bootable payload

W2 adds what the X13s needs on top of the stock payload. Each item
copies what postmarketOS boots this laptop with:

| Item | How the image carries it |
|---|---|
| GPU firmware (`qcom/a660_*`), DSP, audio topology and battery firmware (`qcom/sc8280xp/LENOVO/21BX/`) | Fedora's `qcom-firmware` package |
| Device tree | `/usr/lib/modules/$kver/devicetree`. ostree copies it into every deployment and writes a `devicetree` line in its boot entry. GRUB and systemd-boot load that line. |
| `arm64.nopauth clk_ignore_unused pd_ignore_unused` | `/usr/lib/bootc/kargs.d/10-x13s.toml`, aarch64 only |
| Display, keyboard, NVMe and USB drivers before the root unlocks | `/usr/lib/dracut/dracut.conf.d/90-x13s.conf`, from the postmarketOS `modules-initfs` list, plus the dracut `crypt` module |

The overlay rebuilds the initramfs and writes the inventory. The build fails
if the inventory has a `MISSING` line.

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

For an installed system, W2 uses the ostree `devicetree` file. Each deployment
gets the DTB from its own kernel, and a rollback boots the old pair. The GRUB
`devicetree` command works only with Secure Boot off. The ISO path still
needs a W4 decision.

Primary design evidence:

- [Fedora 44 automatic DTB selection](https://fedoraproject.org/wiki/Changes/Automatic_DTB_selection_for_aarch64_EFI_systems)
- [X13s notes from Fedora](https://fedoraproject.org/wiki/Thinkpad_X13s)
- [upstream X13s status and required boot arguments](https://github.com/jhovold/linux/wiki/X13s)
- [postmarketOS early-module inventory](https://gitlab.postmarketos.org/postmarketOS/pmaports/-/blob/main/device/community/device-lenovo-21bx/modules-initfs)
- [postmarketOS firmware inventory](https://gitlab.postmarketos.org/postmarketOS/pmaports/-/blob/main/device/community/device-lenovo-21bx/firmware.files)

## Try it on an X13s that runs postmarketOS

Do not use bootc-migrate on this laptop yet. It does not recognise an apk
system or a LUKS root. Its in-place mode empties `/boot`, which on
postmarketOS is the ESP with the kernel, the DTB and the boot entry. It has
no undo for package systems yet. Use these stages instead. Each stage keeps
postmarketOS bootable.

1. **Back up.** Copy these to an external disk: an image of the ESP and the
   LUKS header (`cryptsetup luksHeaderBackup`). Also copy the partition table
   (`sfdisk -d`), the output of `efibootmgr -v` and your home directory.
2. **Boot from USB.** On the X13s, write the image to a USB disk with
   `bootc install to-disk`. Give the USB device, never the NVMe disk. Start
   the laptop from the F12 boot menu. Check the display, keyboard, touchpad,
   Wi-Fi, Bluetooth, audio, battery and suspend. To go back, remove the disk.
3. **Install next to postmarketOS.** Boot from the USB disk. Shrink the
   postmarketOS file system, its LUKS mapping and its partition. In the free
   space, make a new ESP, an ext4 `/boot` and a LUKS root for TunaOS. Install
   with `bootc install to-filesystem` and `--karg rd.luks.uuid=<new LUKS UUID>`.
   Then add a firmware boot entry for the new ESP. The postmarketOS ESP and
   its systemd-boot entry do not change.
4. **Go back or commit.** To go back, put postmarketOS first in the boot order.
   Delete the TunaOS partitions and its boot entry. Then grow the postmarketOS
   partition, LUKS mapping and file system again. To commit, copy your data
   and remove the postmarketOS partitions.

## Safety boundary

This repository does not write to real hardware, boot it, or change its
partitions or firmware. The procedure above is for the owner of the laptop.
TunaOS makes no Secure Boot, modem, camera, audio, suspend or installer claim
until physical results exist.
