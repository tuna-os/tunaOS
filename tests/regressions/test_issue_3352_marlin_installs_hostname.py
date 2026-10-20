"""tunaOS#3352: marlin images ship the POSIX `hostname` command.

A measured marlin:gnome host returned no path for `command -v hostname` and
reported that the `inetutils` package was not installed, although
`hostnamectl` was available. Arch provides `/usr/bin/hostname` through
`inetutils`; the package must be named in the Arch base install block rather
than relying on the `base` metapackage. The runtime check's
`/proc/sys/kernel/hostname` fallback allowed the omission to ship unnoticed.

Falsification: structural. Remove `inetutils` from the
`pacman -S --noconfirm --needed` block in `Containerfile.arch` and this test
fails, even if `hostname` remains mentioned in unrelated checks or comments.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONTAINERFILE = ROOT / "Containerfile.arch"


def _arch_base_packages() -> set[str]:
    source = CONTAINERFILE.read_text(encoding="utf-8")
    marker = "pacman -S --noconfirm --needed \\\n"
    start = source.index(marker) + len(marker)
    end = source.index("        gst-libav &&", start)
    return {
        line.strip().removesuffix("\\").strip()
        for line in source[start:end].splitlines()
        if line.strip()
    }


def test_marlin_base_installs_the_hostname_provider():
    assert "inetutils" in _arch_base_packages(), (
        "Containerfile.arch must install Arch's inetutils package; it owns "
        "/usr/bin/hostname"
    )
