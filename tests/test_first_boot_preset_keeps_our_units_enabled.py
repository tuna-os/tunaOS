"""`systemctl enable` at build time does not survive the first boot.

systemd applies preset policy on first boot, and Fedora's catch-all preset is
`disable *`. A unit the build enabled with a symlink under
/etc/systemd/system/<target>.wants/, but which no preset file names, has that
symlink DELETED before anything else runs. The build is long over by then, so
nothing in CI ever sees it happen.

Measured on the boot gate of run 32925587829 (hummingbird:gnome), which had
just built and pushed cleanly:

    [ 7.686065] systemd[1]: Applying preset policy.
    [ 7.989555] Removed '…/multi-user.target.wants/tunaos-base-contract.service'
    [ 8.001120] Removed '…/graphical.target.wants/tunaos-desktop-contract.service'

Those two units exist only to print the marker `scripts/iso-e2e.sh` greps for.
With them disabled the gate waited its full 900s and exited 2, "readiness
marker not seen" — on an image that had booted to a login prompt without a
single failed unit. `Gate` is a `needs:` of `Promote`, so a perfectly healthy
image does not publish.

The same pass stripped `tunaos-live-ready.service`, which is the equivalent
marker for the ISO path, so the ISO axis was going to hit this too.

The drift test at the bottom is the one that matters: the next boot-contract
unit somebody adds must be named here, or it will be silently disabled on
every image the moment a user boots one.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRESET = ROOT / "system_files/usr/lib/systemd/system-preset/50-tunaos.preset"
BUILD_SCRIPTS = ROOT / "build_scripts"

# Exactly the units the boot gate logged systemd removing, in that run.
STRIPPED_ON_FIRST_BOOT = {
    "ublue-system-setup.service",
    "tunaos-live-ready.service",
    "tunaos-base-contract.service",
    "flatpak-preinstall.service",
    "tailscaled.service",
    "tunaos-var-home-restorecon.service",
    "tunaos-desktop-contract.service",
}


def directives() -> dict[str, str]:
    """Map unit -> verb for every non-comment line of the preset."""
    out = {}
    for line in PRESET.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        verb, _, unit = line.partition(" ")
        out[unit.strip()] = verb
    return out


def test_the_preset_file_is_where_systemd_looks_for_it() -> None:
    assert PRESET.is_file(), f"{PRESET} is missing"
    assert PRESET.parent.name == "system-preset"


def test_every_preset_we_ship_sorts_before_fedoras_catch_all_disable() -> None:
    """`disable *` ships as 99-default.preset; a higher number never wins.

    Checked across EVERY preset file rather than just the one named above,
    because the failure this guards against arrived as a second file, not as
    a rename: `git mv` during a mutation test staged 99-tunaos.preset, a
    directory-level `git add` swept it into a commit, and a version of this
    test that only looked at PRESET.name passed while a file sorting after
    the catch-all sat right beside it.
    """
    shipped = sorted(PRESET.parent.glob("*.preset"))
    assert shipped, "no preset files found — this test is measuring nothing"
    for path in shipped:
        prefix = int(path.name.split("-", 1)[0])
        assert prefix < 99, f"{path.name} sorts at or after the catch-all"


def test_we_ship_exactly_one_tunaos_preset() -> None:
    """Two files with overlapping directives is a merge nobody reviewed."""
    ours = sorted(p.name for p in PRESET.parent.glob("*-tunaos.preset"))
    assert ours == [PRESET.name], f"unexpected tunaos preset files: {ours}"


def test_every_unit_first_boot_stripped_is_now_enabled() -> None:
    verbs = directives()
    missing = sorted(u for u in STRIPPED_ON_FIRST_BOOT if verbs.get(u) != "enable")
    assert not missing, (
        "these were deleted by preset policy on the first boot of run "
        "32925587829 and are still not enabled here: " + ", ".join(missing)
    )


def test_the_boot_contract_units_specifically_are_enabled() -> None:
    """The three that gate Promote and the ISO, called out on their own.

    The set above could be edited down without anyone noticing which entries
    carried the consequence; these three are the ones that do.
    """
    verbs = directives()
    for unit in (
        "tunaos-base-contract.service",
        "tunaos-desktop-contract.service",
        "tunaos-live-ready.service",
    ):
        assert verbs.get(unit) == "enable", f"{unit} is not enabled by preset"


def test_the_existing_suppression_survived() -> None:
    """Guard the guard: this file already had one job before it had this one."""
    assert directives().get("tracker-extract-3.service") == "disable"


def test_every_tunaos_unit_the_build_enables_is_named_here() -> None:
    """Drift guard, and the reason this file needs a test at all.

    A new `tunaos-*` unit enabled by a build script but absent from the preset
    is disabled again on first boot, and every check we run happens before
    that. Restricted to our own `tunaos-` units: third-party ones (gdm,
    greetd, sshd) are enabled conditionally per flavor and a blanket preset
    would override that intent.
    """
    enabled = set()
    for script in BUILD_SCRIPTS.rglob("*.sh"):
        text = script.read_text(encoding="utf-8", errors="replace")
        for match in re.finditer(
            r"^\s*(?:safe_enable|systemctl enable)\s+(tunaos-[\w@.-]+\.(?:service|timer|target))",
            text,
            re.M,
        ):
            enabled.add(match.group(1))
    assert enabled, "found no tunaos-* enables — this test is measuring nothing"
    verbs = directives()
    missing = sorted(u for u in enabled if verbs.get(u) != "enable")
    assert not missing, (
        "enabled by a build script but not named in the preset, so first boot "
        "will disable them: " + ", ".join(missing)
    )
