"""getbinpkg was already wired for guppy's desktop stage -- it just never fired.

Containerfile.gentoo's desktop-build stage already carries `FEATURES=getbinpkg`,
a `binrepos.conf` pointed at the official Gentoo binhost, and
`--binpkg-respect-use=y` on `EMERGE_DEFAULT_OPTS` (all inherited from the base
stage, tuna-os/tunaOS#644). None of that is broken: measured against run
31953925629 / job 95187041080 (2026-08-16), `>>> Emerging (` appears 70 times
in the desktop stage and `>>> Emerging (binary` appears 0 times -- every
package, including kde-plasma/sddm-kcm (whose only IUSE flag is `debug`, which
already matched the local config) compiled from source.

The reason is not USE flags. --getbinpkg only substitutes a binary on an exact
CPV (category/name-version) match. The log resolved kde-plasma to 6.6.5; the
official binhost, read live from
https://distfiles.gentoo.org/releases/amd64/binpackages/23.0/x86-64/Packages
on 2026-08-17, has only 6.6.6 kde-plasma builds -- no 6.6.5 entries anywhere.
56 of the 70 emerged packages (80%) are kde-plasma/*-6.6.5 atoms, all pulled
in transitively off one root atom (kde-plasma/plasma-meta, packages.emerge[0]
in manifests/desktops/kde.yaml) via `>=kde-plasma/foo-6.6.6:6`-style RDEPEND.
A bare `emerge --sync` races ahead of the binhost's slower rebuild cadence for
a category that bumps this often, so the whole chain misses.

build_scripts/desktop/gentoo-binhost-version-lock.sh masks anything in the
anchor category newer than what the configured binhost actually published, so
that RDEPEND chain has nowhere to resolve but a version --getbinpkg can serve.
These tests pin that the mechanism is wired in, generically covers every
guppy desktop flavor's anchor category (not just kde), and fails open rather
than risking a build that used to succeed.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parents[1]
INSTALL_DESKTOP = ROOT / "build_scripts/desktop/install-desktop.sh"
LOCK_SCRIPT = ROOT / "build_scripts/desktop/gentoo-binhost-version-lock.sh"
CONTAINERFILE_GENTOO = ROOT / "Containerfile.gentoo"
DESKTOPS_DIR = ROOT / "manifests/desktops"

# The anchor atom is packages.emerge[0] in each manifest that declares an
# emerge section -- read from the real files rather than hardcoded, except
# for the expected category, which is the one fact this test pins.
EXPECTED_ANCHOR_CATEGORY = {
    "kde": "kde-plasma",
    "gnome": "gnome-base",
    "xfce": "xfce-base",
}


def _emerge_anchor_atom(desktop: str) -> str | None:
    manifest = yaml.safe_load((DESKTOPS_DIR / f"{desktop}.yaml").read_text())
    emerge_pkgs = manifest.get("packages", {}).get("emerge")
    if not emerge_pkgs:
        return None
    return emerge_pkgs[0]


def test_lock_script_exists_and_is_executable():
    assert LOCK_SCRIPT.is_file(), f"missing {LOCK_SCRIPT}"
    assert LOCK_SCRIPT.stat().st_mode & 0o111, f"{LOCK_SCRIPT} is not executable"


def test_lock_script_has_valid_shell_syntax():
    result = subprocess.run(
        ["bash", "-n", str(LOCK_SCRIPT)], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr


def test_lock_script_embeds_syntactically_valid_python():
    import ast

    body = LOCK_SCRIPT.read_text()
    start = body.index("<<'PYEOF'") + len("<<'PYEOF'\n")
    end = body.index("\nPYEOF", start)
    ast.parse(body[start:end])


def test_install_desktop_calls_the_lock_script_before_the_real_emerge():
    """The mechanism has to run before `emerge --verbose "${_TD_EMERGE_PKGS[@]}"`,
    with its own package.mask, or the version lock it writes is a no-op."""
    body = INSTALL_DESKTOP.read_text()
    emerge_branch = body[body.index('"${_TD_OS}" == "emerge"') :]
    lock_call = emerge_branch.index("gentoo-binhost-version-lock.sh")
    real_emerge = emerge_branch.index('emerge --verbose "${_TD_EMERGE_PKGS[@]}"')
    assert lock_call < real_emerge, (
        "gentoo-binhost-version-lock.sh must run before the real emerge, "
        "not after"
    )


def test_install_desktop_call_site_fails_open():
    """A crash in the lock script must never take the desktop build down with
    it -- install-desktop.sh runs under `set -euo pipefail`."""
    body = INSTALL_DESKTOP.read_text()
    assert "set -xeuo pipefail" in body or "set -euo pipefail" in body, (
        "this test assumes install-desktop.sh runs under errexit; if that "
        "changed, the || true guard below may no longer be load-bearing"
    )
    call_idx = body.index("gentoo-binhost-version-lock.sh")
    # The call is a multi-line, backslash-continued statement; look at the
    # next couple of lines rather than assuming the guard is on the same
    # physical line as the script path.
    call_statement = body[call_idx : call_idx + 200]
    assert "|| true" in call_statement, (
        "the call site needs its own `|| true` under errexit -- the script's "
        "internal fallbacks are not enough if something outside them (a "
        "missing file, a permissions error) throws before they run"
    )


@pytest.mark.parametrize("desktop", ["kde", "gnome", "xfce"])
def test_each_desktop_manifests_anchor_atom_matches_the_expected_category(desktop):
    """gentoo-binhost-version-lock.sh derives its anchor category from
    packages.emerge[0] -- pin that this atom is still the right one for
    each desktop manifest that declares an emerge section, and that its
    category is the one carrying the version churn (or, for gnome/xfce,
    the category the mechanism is expected to generalize to)."""
    atom = _emerge_anchor_atom(desktop)
    assert atom is not None, f"manifests/desktops/{desktop}.yaml has no emerge section"
    category = atom.split("/", 1)[0]
    assert category == EXPECTED_ANCHOR_CATEGORY[desktop], (
        f"manifests/desktops/{desktop}.yaml's first emerge atom is {atom!r} "
        f"(category {category!r}); gentoo-binhost-version-lock.sh keys off "
        f"packages.emerge[0]'s category, so a reorder here silently changes "
        f"what gets version-locked"
    )


def test_lock_script_never_forces_binpkg_only():
    """--getbinpkg-only would make a binhost miss fatal instead of a silent
    from-source fallback -- the task this script exists for is strictly
    best-effort."""
    body = LOCK_SCRIPT.read_text()
    assert "--getbinpkg-only" not in body
    assert "getbinpkgonly" not in body


def test_lock_script_does_not_touch_signature_or_respect_use_policy():
    """The fix is a version mask, not a trust or USE-matching policy change.
    Containerfile.gentoo's desktop stage keeps --binpkg-respect-use=y and
    whatever signature enforcement the base stage already set (#644); this
    script must not carry its own opinion on either."""
    body = LOCK_SCRIPT.read_text()
    # Look for the script actually *setting* one of these (an '=' right
    # after the flag name), not just discussing them in the header comment
    # that explains why it deliberately leaves them alone.
    assert not re.search(r"binpkg-respect-use\s*=", body)
    assert not re.search(r"binpkg-ignore-signature\s*=", body)
    assert not re.search(r"binpkg-request-signature\s*=", body)


def test_lock_script_validates_before_committing_the_mask():
    """A binhost version that has already been pruned from the synced tree
    must not turn a working (if slow) source build into a hard failure."""
    body = LOCK_SCRIPT.read_text()
    assert "emerge --pretend" in body, (
        "the mask must be validated against the synced tree before the real "
        "emerge sees it, and reverted (not left in place) if resolution fails"
    )
    # rindex, not index: "emerge --pretend" is also named in the header
    # comment explaining the mechanism -- the actual invocation is the last
    # occurrence, in the code below the docstring.
    pretend_idx = body.rindex("emerge --pretend")
    revert_window = body[pretend_idx : pretend_idx + 400]
    assert "rm -f" in revert_window, (
        "an unresolvable lock has to be removed, not just logged, or the "
        "real emerge below inherits a broken package.mask"
    )


def test_desktop_stage_still_declares_getbinpkg_and_a_binhost():
    """Guard against the actual wiring (FEATURES=getbinpkg, binrepos.conf,
    --getbinpkg on EMERGE_DEFAULT_OPTS) regressing while this version-lock
    layer is added on top of it -- #1802's diagnosis was that the wiring was
    already correct and insufficient by itself, not that it was missing."""
    body = CONTAINERFILE_GENTOO.read_text()
    assert "FEATURES=" in body and "getbinpkg" in body
    assert "binrepos.conf" in body
    assert re.search(r"EMERGE_DEFAULT_OPTS.*--getbinpkg", body), (
        "--getbinpkg must still reach the emerge invocations via "
        "EMERGE_DEFAULT_OPTS"
    )
    assert "--binpkg-respect-use=y" in body, (
        "the desktop stage's exact-USE-match policy (fixing the elogind/"
        "multilib binpkg bug this repo already hit) must stay as-is"
    )
