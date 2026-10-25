# Snapdragon / Copilot ARM PC support path

This guide answers [Discussion #93](https://github.com/orgs/tuna-os/discussions/93)
and supports [#3116](https://github.com/tuna-os/tunaOS/issues/3116).
An ARM64 image alone does not establish that TunaOS can boot or install on a
particular Snapdragon laptop. Do not buy a Copilot PC on that assumption.

## Identify the device before choosing an image

The ThinkPad X13s uses Snapdragon 8cx Gen 3 / SC8280XP. It is a different
platform from Snapdragon X Elite / X Plus Copilot+ PCs. See the
[guide from the X13s maintainer](https://github.com/jhovold/linux/wiki/X13s)
and [Qualcomm's kernel overview for X Elite](https://www.qualcomm.com/developer/blog/2024/05/upstreaming-linux-kernel-support-for-the-snapdragon-x-elite).
A result on one platform does not qualify another laptop with an ARM CPU.

For TunaOS evidence, use the [X13s qualification epic #3368](https://github.com/tuna-os/tunaOS/issues/3368).
It records observations on **postmarketOS**, not a successful TunaOS install.
It defines the required TunaOS live boot, installation, kernel update and
rollback tests. Those observations do not qualify a device for TunaOS.
For other models, request a report before you recommend an image.
This issue does not establish which Copilot PCs can run TunaOS.

[HARDWARE.md](HARDWARE.md) is the hardware index. The correction for its older X13s/X Elite row is in [PR #3432](https://github.com/tuna-os/tunaOS/pull/3432)
to match #3368. The archived Bonito/Dakota X13s pages are historical context,
not proof of a current supported download or installation path.

The build inputs in [tunaos.toml](../tunaos.toml) declare platforms per flavor.
Check that exact flavor, its published manifest and the
[generated matrix evidence](MATRIX-STATUS.md). A generic ARM64 QEMU boot proves
neither a laptop's device-tree selection nor its input, graphics or firmware.

## Boot and installation prerequisites

Snapdragon laptop bring-up needs a matching kernel, device tree (DTB), firmware
and initramfs as well as an ARM64 root filesystem. The
[guide for X13s from Fedora](https://fedoraproject.org/wiki/Thinkpad_X13s) describes that
model's UEFI setup, firmware and DTB requirements. Follow the upstream guide
for the exact device; do not copy its firmware settings or kernel arguments
to an unrelated Copilot PC.

UEFI can enter an ARM64 EFI loader, but it does not itself supply every Linux
hardware description or driver. #3368 tracks DTB selection through live boot,
installed boot, kernel updates and rollback. U-Boot on an Apple Silicon/Asahi
path is a separate platform boot chain, not a Snapdragon installation recipe.
[Asahi Linux is for Macs with Apple Silicon](https://asahilinux.org/about/).

There is no verified generic Fisherman or direct `bootc install` procedure for
Copilot PCs established here. Both install a system; neither supplies missing
board enablement. Use [INSTALL.md](INSTALL.md) for media tools after you verify
the boot and installer prerequisites for the device. #3368
also tracks the Tacklebox media and Fisherman installer work needed for X13s.

For experimental bring-up, preserve the existing system and recovery media.
First establish a live boot that does not write to internal storage.
Then use a spare external disk at an agreed time for hardware tests. A complete install
guide needs measured boot, plain/encrypted installation, kernel update,
rollback and recovery results for that device. This document does not replace
those missing qualification steps with a destructive install command.

## Can Linux use the NPU?

The Windows TOPS rating is not evidence that a Linux application can use the
accelerator. Separate CPU execution, Adreno GPU execution and Hexagon NPU
execution in your report.

It is also inaccurate to say that Linux has no Qualcomm accelerator support.
The kernel has a [FastRPC driver](https://github.com/torvalds/linux/blob/master/drivers/misc/fastrpc.c).
The upstream llama.cpp project documents a
[Snapdragon Hexagon backend](https://github.com/ggml-org/llama.cpp/blob/master/docs/backend/snapdragon/README.md)
and a [Linux build/run path](https://github.com/ggml-org/llama.cpp/blob/84663953535d4323e92b4bc90971aa022c305d06/docs/backend/snapdragon/linux.md).
Those are upstream development references, not a tested TunaOS configuration.
A kernel interface alone does not establish usable firmware, runtime libraries,
permissions or application support on a given laptop.

Do not confuse the kernel's
[QAIC driver for AIC100 accelerators](https://docs.kernel.org/accel/qaic/qaic.html)
with proof of support for a laptop's integrated Hexagon NPU.
This repository does not explicitly install a Hexagon/QNN stack in its
manifests or build scripts (`git grep -n -iE 'hexagon|fastrpc|qnn' -- manifests build_scripts`).
That search does not inspect packages from the base image.

This guide does not qualify an NPU workload on TunaOS.
Any future claim needs the exact hardware, firmware, kernel, runtime and model.
The logs must prove NPU execution and rule out CPU fallback.
Check the upstream terms for runtime and firmware redistribution before you
propose packages. Do not copy proprietary firmware into a report.

## Send a useful test report

Open a [TunaOS issue](https://github.com/tuna-os/tunaOS/issues/new/choose) and
link it from Discussion #93. X13s reports should also reference #3368. Include:

- Exact laptop model, SoC and BIOS/UEFI version; Secure Boot state and bootloader.
- Distribution tested, TunaOS variant/flavor if applicable, immutable
  image digest, kernel version, DTB and boot arguments.
- Boot medium and installation target; distinguish live boot from installed boot.
- Results for built-in input, display/GPU, Wi-Fi, Bluetooth, audio,
  battery charge, suspend/resume and external displays. Mark untested functions.
- For installed systems, separate first boot, kernel update and rollback results.
- For NPU tests, runtime/model versions, selected backend and relevant logs.
  A visible device node or active DSP is not a successful inference test.

Redact serial numbers, network identifiers and credentials from logs.
For upstream device work, consult the
[postmarketOS device catalog](https://wiki.postmarketos.org/wiki/Devices)
and the X13s maintainer guide. Those sources describe their own Linux work;
they are not a TunaOS certification matrix.

## Prepared reply for Discussion #93

The following text is ready for a publisher with Discussion-write permission.
For the reply/answer action, see [#2947](https://github.com/tuna-os/tunaOS/issues/2947).
Recheck the qualification issue before you post. Then record the URL of the
public comment. This draft does not answer the public thread.

Thanks for the question. We cannot recommend a purchase of a Snapdragon
Copilot PC on the assumption that TunaOS will install and run on it. An ARM64 build alone is
not a device-support guarantee. The ThinkPad X13s uses 8cx Gen 3 / SC8280XP, not X Elite. Our
[X13s qualification work](https://github.com/tuna-os/tunaOS/issues/3368)
still needs TunaOS boot/install/update/rollback evidence.

Linux NPU work exists: llama.cpp documents a
[Snapdragon backend and Linux path](https://github.com/ggml-org/llama.cpp/blob/master/docs/backend/snapdragon/README.md).
That does not establish a usable NPU stack for your prospective PC on TunaOS.
We have no verified NPU setup on TunaOS to recommend here.

Which exact laptop and SoC do you want to use? If you already own it and
test Linux, please [open a report](https://github.com/tuna-os/tunaOS/issues/new/choose)
with the model, firmware, image/kernel and functions that work or fail.
Our [Snapdragon support guide](https://github.com/tuna-os/tunaOS/blob/main/docs/SNAPDRAGON.md)
explains the evidence needed. The
[postmarketOS device catalog](https://wiki.postmarketos.org/wiki/Devices)
is useful for model-specific upstream research. Asahi Linux is for Macs with Apple Silicon. It does not target Snapdragon PCs.
