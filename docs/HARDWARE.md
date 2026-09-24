# Hardware support

System requirements and per-platform hardware status. For which *image* fits
your hardware (HWE kernels, NVIDIA, ARM), see the
[User Guide](USER-GUIDE.md) and the tag reference in
[IMAGE-TAGS.md](IMAGE-TAGS.md).

## System requirements

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| **CPU** | x86_64, ARM64 | x86_64, ARM64 |
| **RAM** | 4 GB | 8 GB+ |
| **Storage** | 20 GB | 50 GB+ |

## Supported hardware (ARM laptops)

| Hardware | Status | Docs |
|----------|--------|------|
| Snapdragon X Elite (e.g. Lenovo ThinkPad X13s) | Supported via [Bonito](https://tunaos.org/docs/bonito) (ARM64) | [Snapdragon X Elite FAQ](https://tunaos.org/docs/faq); the dedicated [bonito-x13s](https://tunaos.org/docs/bonito-x13s) / [dakota-x13s](https://tunaos.org/docs/dakota-x13s) pages are archived |
| Apple Silicon (M1, M2) | In progress via [Asahi Linux](https://asahilinux.org/) — see note below | [bootc-installer-asahi](https://github.com/tuna-os/bootc-installer-asahi) |
| Apple Silicon (M3 and newer) | Not supported (no Asahi support for M3+ yet) | — |

> **Apple Silicon status.** [`ROADMAP.md`](../ROADMAP.md) is the canonical source
> and lists Apple Silicon support as 🟡 **in progress**
> ([#781](https://github.com/tuna-os/tunaOS/issues/781)). This row states the
> same status instead of "Supported". Concretely, the `-asahi` images
> build and pass CI gates (Bonito & Grouper, 36/36 verified,
> [#776](https://github.com/tuna-os/tunaOS/issues/776)).

> The installer track has D0–D2 and D4 done. What does not exist yet: the D3
> macOS installer app, any tagged release of `bootc-installer-asahi`, and
> validation on real Apple hardware. That repo's deepest test is qemu +
> U-Boot. Install now by execution of the Asahi installer path
> by hand. If you have M1/M2 hardware to test on, #781 is the place to help.

## Supported hardware (Intel Macs with the Apple T2 chip)

| Hardware | Status | Image |
|----------|--------|-------|
| Intel Mac with the Apple T2 security chip (2018-2020 MacBook Pro, MacBook Air, iMac, Mac mini) | Builds and boots; **not yet validated on real T2 hardware** | `bonito:gnome-t2` (x86_64) |

The T2 overlay swaps Fedora's kernel for the [T2 Linux](https://wiki.t2linux.org/)
project's COPR build, which carries the bridge, keyboard, trackpad and audio
patches those machines need. `build_scripts/overlay/t2.sh` asserts the result: a kernel without the
`.t2.` dist tag fails the build, and no such image ships.

What that status means, precisely. The flavor builds, passes the desktop
contract, boots in the CI gate and publishes, first measured in run
[34768771243](https://github.com/tuna-os/tunaOS/actions/runs/34768771243) on
2026-09-13. Nobody has run it on a T2 Mac. The gate boots the image under
QEMU, which exercises the kernel and the desktop, and says nothing at all
about Apple's bridge hardware.

**Wi-Fi and Bluetooth need firmware this image cannot carry.** Apple does not
let anyone redistribute the Broadcom firmware, so it is absent on purpose.
The installer extracts it from the machine's own macOS partition and transfers
it during installation. An image booted without that step has no Wi-Fi. The
overlay ships `iwd` and points NetworkManager at it. That is the backend recommended by
the T2 Linux project for these chips.

If you have a T2 Mac to test on, that is the missing evidence.
