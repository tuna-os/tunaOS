"""tunaOS#1832: every sailfin desktop failed the codec baseline.

The base stage installs Packman's full-codec ffmpeg (--allow-vendor-change),
but the desktop transaction can pull a NEWER openSUSE-vendor ffmpeg through a
dependency bump — vendor stickiness does not survive a version-forced upgrade
— and openSUSE's build compiles the h264/hevc/vc1 decoders out. Measured on
nightly 31987555325, all five desktops, all three in-job attempts:

    ffmpeg cannot decode h264 — a free/crippled libavcodec is installed
    configure --disable-decoder='h264,hevc,vc1,prores_raw,vvc'

install-desktop.sh's zypper path now re-asserts Packman after its install.
"""
from __future__ import annotations

import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = (ROOT / "build_scripts" / "desktop" /
          "install-desktop.sh").read_text(encoding="utf-8")
BASE = (ROOT / "Containerfile.opensuse").read_text(encoding="utf-8")


def test_desktop_stage_reasserts_packman_after_its_transaction() -> None:
    assert "dup --from packman-essentials --allow-vendor-change" in SCRIPT
    # It must come AFTER the desktop package install, or the install can
    # undo it again — the exact bug this fixes.
    assert SCRIPT.index('_td_zypper_install_retry "${_TD_ZYPPER_PKGS[@]}"') \
        < SCRIPT.index("dup --from packman-essentials")


def test_reassert_is_guarded_and_loud() -> None:
    # Only when the repo exists (local/dev builds without Packman must not
    # break), and a failed re-assert fails the build rather than shipping a
    # crippled codec stack for the Gate to find later.
    assert "zypper --non-interactive repos packman-essentials" in SCRIPT
    assert "could not re-assert Packman multimedia" in SCRIPT


def test_base_stage_still_installs_packman_first() -> None:
    """The re-assert complements the base install, it does not replace it."""
    assert "packman-essentials" in BASE
    assert "--allow-vendor-change" in BASE


def test_ownership_is_verified_not_inferred_from_the_dup() -> None:
    """Run 32047331620 proved the dup alone is insufficient (openSUSE's
    NEWER ffmpeg → "Nothing to do"), and run 32052422745 proved which
    packages the check must target: Packman Essentials carries NO package
    named `ffmpeg` (measured live 2026-08-17 — only ffmpeg-3..8 and
    libavcodecNN), so forcing the openSUSE package names was a no-op
    ('not found in package names'). The invariant is that the LIBRARY
    complements are Packman-vendored: every installed libavcodecNN, the
    gstreamer *-codecs packages, and vlc-codecs."""
    assert "rpm -q --qf '%{VENDOR}" in SCRIPT
    assert "--oldpackage" in SCRIPT
    assert "--from packman-essentials" in SCRIPT
    # The corrected target set: libraries, not the openSUSE binary names.
    assert "'libavcodec*'" in SCRIPT
    assert "gstreamer-plugins-bad-codecs" in SCRIPT
    assert "gstreamer-plugins-ugly-codecs" in SCRIPT
    assert "vlc-codecs" in SCRIPT
    # And it must assert the outcome, not hope: a post-force vendor
    # re-check that fails the build where the zypper output is on screen.
    assert "still not Packman-vendored after the forced install" in SCRIPT
    # The vendor check must come AFTER the dup — it is the fallback for the
    # case the dup cannot handle, not a replacement for it.
    assert SCRIPT.index("dup --from packman-essentials") \
        < SCRIPT.index("rpm -q --qf '%{VENDOR}")
