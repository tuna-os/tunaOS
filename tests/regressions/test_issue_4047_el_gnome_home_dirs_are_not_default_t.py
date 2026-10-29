"""tunaOS#4047: every EL GNOME image labelled all of /home default_t.

Measured on albacore:gnome, yellowfin:gnome and skipjack:gnome (not the KDE
images): `matchpathcon /var/home/user/.ssh/authorized_keys` printed
`system_u:object_r:default_t:s0`, so sshd could not read authorized_keys and
GNOME session processes got EACCES under ~/.local/share. Reproduced in a rootful
container from the albacore base (almalinux-bootc@sha256:5f35f25a...,
selinux-policy-targeted 42.1.18) by `dnf install` of the 43.1-1.el10 RPMs from
ghcr.io/tuna-os/tunaos-packages (gnome50-el10-x86_64, the priority-1 GNOME
repo): 205 rules under /var/home, 0 under /home, and subs_dist flipped from
`/home /var/home` to `/var/home /home`, so libselinux rewrote every
/var/home lookup to /home before it could match a rule.

What this holds: the real build scripts (build_scripts/selinux-home-labels.sh
fix, build_scripts/checks/verify-selinux-home-labels.sh gate) run against
fixture policy trees shaped like both policies. The gate rejects the 43.1
shape, the fix turns it into a tree the gate accepts, and neither the fix nor
the gate disturbs the shape that already works (Alma 42.x) or an image with no
SELinux policy.

Falsification: behavioural -- the 43.1-shaped fixture is the tree that shipped
the incident; `test_gate_rejects_the_43_1_policy_shape` fails if the gate stops
detecting it, and `test_fix_makes_the_43_1_shape_pass_the_gate` fails if the fix
stops repairing it. The wiring test is structural: it fails if install-desktop.sh
stops running the fix and then the gate (revert the install-desktop.sh hunk).
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIX = ROOT / "build_scripts" / "selinux-home-labels.sh"
GATE = ROOT / "build_scripts" / "checks" / "verify-selinux-home-labels.sh"

# Lines copied from file_contexts.homedirs generated in the repro container;
# only the prefix differs between the two HOME settings.
_HOMEDIRS_RULES = """\
{p}/[^/]+/.+\tunconfined_u:object_r:user_home_t:s0
{p}/[^/]+/.maildir(/.*)?\tunconfined_u:object_r:mail_home_rw_t:s0
{p}/[^/]+/.*/plugins/nppdf\\.so.*\t--\tunconfined_u:object_r:textrel_shlib_t:s0
{p}/[^/]+/tmp/.*\t<<none>>
{p}/[^/]+/\\.ssh(/.*)?\tunconfined_u:object_r:ssh_home_t:s0
{p}/[^/]+/\\.local/share(/.*)?\tunconfined_u:object_r:data_home_t:s0
"""

_SUBS_COMMON = """\
# This file can is used to configure base path aliases as in:
#
# /aliased_path /original_path_as_configured_in_file_contexts
#
/var/lib/xguest/home /home
/home-inst           /home
/home/home-inst      /home
/var/roothome        /root
"""

# selinux-policy-targeted-43.1-1.el10 (tunaos-packages): Fedora direction.
SUBS_FEDORA = _SUBS_COMMON + "/var/home            /home\n"
# selinux-policy-targeted-42.1.18-4.el10_2.4 (AlmaLinux): EL direction.
SUBS_EL = _SUBS_COMMON + "/home /var/home\n"


def _tree(
    tmp_path: Path,
    *,
    useradd_home: str | None,
    subs_dist: str,
    rules_under: str,
    local_subs: str = "",
    policy: bool = True,
) -> Path:
    root = tmp_path / "root"
    (root / "etc/default").mkdir(parents=True)
    if useradd_home is not None:
        (root / "etc/default/useradd").write_text(
            f"# useradd defaults file\nGROUP=100\nHOME={useradd_home}\nSHELL=/bin/bash\n"
        )
    if policy:
        files = root / "etc/selinux/targeted/contexts/files"
        files.mkdir(parents=True)
        (root / "etc/selinux/config").write_text("SELINUX=enforcing\nSELINUXTYPE=targeted\n")
        (files / "file_contexts.subs_dist").write_text(subs_dist)
        (files / "file_contexts.subs").write_text(local_subs)
        (files / "file_contexts.homedirs").write_text(
            "#\n# User-specific file contexts, generated via libsemanage\n#\n\n"
            + _HOMEDIRS_RULES.format(p=rules_under)
        )
    return root


def _run(script: Path, root: Path) -> subprocess.CompletedProcess[str]:
    env = {
        "PATH": os.environ["PATH"],
        "TUNAOS_SELINUX_ROOT": str(root),
    }
    return subprocess.run(
        ["bash", str(script)], env=env, capture_output=True, text=True
    )


def _subs_dist(root: Path) -> str:
    return (
        root / "etc/selinux/targeted/contexts/files/file_contexts.subs_dist"
    ).read_text()


def test_gate_rejects_the_43_1_policy_shape(tmp_path: Path) -> None:
    root = _tree(
        tmp_path, useradd_home="/var/home", subs_dist=SUBS_FEDORA, rules_under="/var/home"
    )
    r = _run(GATE, root)
    assert r.returncode != 0, r.stdout + r.stderr
    # Names the path, where libselinux sent it, and the label that results.
    assert "/var/home/tunaos-check/.ssh/authorized_keys resolves to /home/" in r.stderr
    assert "default_t" in r.stderr


def test_fix_makes_the_43_1_shape_pass_the_gate(tmp_path: Path) -> None:
    root = _tree(
        tmp_path, useradd_home="/var/home", subs_dist=SUBS_FEDORA, rules_under="/var/home"
    )
    fixed = _run(FIX, root)
    assert fixed.returncode == 0, fixed.stderr
    assert "flipped alias '/var/home /home' to '/home /var/home'" in fixed.stderr

    after = _subs_dist(root)
    assert "/home /var/home\n" in after
    assert "/var/home /home" not in after
    # Every other alias is untouched, in place.
    for line in SUBS_FEDORA.splitlines():
        if line.strip() and line.split()[0] != "/var/home":
            assert line in after.splitlines()

    gate = _run(GATE, root)
    assert gate.returncode == 0, gate.stdout + gate.stderr
    assert "type=default_t" not in gate.stdout


def test_fix_is_idempotent(tmp_path: Path) -> None:
    root = _tree(
        tmp_path, useradd_home="/var/home", subs_dist=SUBS_FEDORA, rules_under="/var/home"
    )
    assert _run(FIX, root).returncode == 0
    once = _subs_dist(root)
    again = _run(FIX, root)
    assert again.returncode == 0
    assert _subs_dist(root) == once
    assert "flipped" not in again.stderr


def test_the_shape_that_already_works_is_left_byte_identical(tmp_path: Path) -> None:
    root = _tree(
        tmp_path, useradd_home="/var/home", subs_dist=SUBS_EL, rules_under="/var/home"
    )
    assert _run(GATE, root).returncode == 0
    assert _run(FIX, root).returncode == 0
    assert _subs_dist(root) == SUBS_EL
    assert _run(GATE, root).returncode == 0


def test_fix_follows_a_home_that_is_not_var_home(tmp_path: Path) -> None:
    # Rules generated for HOME=/home with the EL alias: the same disagreement
    # the other way round. The fix reverses the alias, it does not hardcode
    # /var/home.
    root = _tree(
        tmp_path, useradd_home="/home", subs_dist=SUBS_EL, rules_under="/home"
    )
    assert _run(GATE, root).returncode != 0
    assert _run(FIX, root).returncode == 0
    assert "/var/home /home\n" in _subs_dist(root)
    assert _run(GATE, root).returncode == 0


def test_a_local_alias_for_home_is_repaired_where_it_lives(tmp_path: Path) -> None:
    root = _tree(
        tmp_path,
        useradd_home="/var/home",
        subs_dist=_SUBS_COMMON,
        rules_under="/var/home",
        local_subs="/var/home /home\n",
    )
    assert _run(GATE, root).returncode != 0
    assert _run(FIX, root).returncode == 0
    local = (
        root / "etc/selinux/targeted/contexts/files/file_contexts.subs"
    ).read_text()
    assert local == "/home /var/home\n"
    assert _subs_dist(root) == _SUBS_COMMON
    assert _run(GATE, root).returncode == 0


def test_fix_refuses_an_alias_conflict_instead_of_guessing(tmp_path: Path) -> None:
    # Reversing `/var/home /home` would add a second alias for /home.
    root = _tree(
        tmp_path,
        useradd_home="/var/home",
        subs_dist=SUBS_FEDORA,
        rules_under="/var/home",
        local_subs="/home /srv/home\n",
    )
    before = _subs_dist(root)
    r = _run(FIX, root)
    assert r.returncode != 0
    assert "conflict" in r.stderr
    assert _subs_dist(root) == before


def test_images_without_selinux_policy_are_skipped(tmp_path: Path) -> None:
    root = _tree(
        tmp_path,
        useradd_home="/var/home",
        subs_dist="",
        rules_under="/var/home",
        policy=False,
    )
    for script in (FIX, GATE):
        r = _run(script, root)
        assert r.returncode == 0, r.stderr
        assert "no SELinux policy" in r.stdout + r.stderr


def test_missing_useradd_defaults_to_home(tmp_path: Path) -> None:
    # useradd's own default when /etc/default/useradd has no HOME: rules sit
    # under /home, so the EL alias must be reversed for them to be reachable.
    root = _tree(
        tmp_path, useradd_home=None, subs_dist=SUBS_EL, rules_under="/home"
    )
    assert _run(GATE, root).returncode != 0
    assert _run(FIX, root).returncode == 0
    assert _run(GATE, root).returncode == 0


def test_install_desktop_runs_the_fix_then_the_gate_before_the_desktop_contract() -> None:
    src = (ROOT / "build_scripts/desktop/install-desktop.sh").read_text()
    fix = src.index("/build_scripts/selinux-home-labels.sh")
    gate = src.index("/build_scripts/checks/verify-selinux-home-labels.sh")
    contract = src.index('"${_TD_CTX}/build_scripts/checks/verify-desktop-experience.sh"')
    assert fix < gate < contract
