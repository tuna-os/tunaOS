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
The overlay tests are behavioural: they resolve the -hwe, -nvidia and -gdx
flavors with scripts/resolve-flavor.sh, walk the build target's stage chain in
the Containerfile it names, and execute the RUN step that carries the gate
against fixtures; they fail when no step runs the gate after the overlay's
package transactions, when the fix does not run first, or when a gate failure
does not fail the step (remove the RUN from Containerfile.overlay).
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

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
# This file is used to configure base path aliases as in:
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


# ── The library under its callers' `set -euo pipefail` ─────────────────────

LIB = ROOT / "build_scripts" / "lib" / "selinux-home-labels.sh"


def _strict(root: Path, body: str) -> subprocess.CompletedProcess[str]:
    """Run `body` with the lib sourced under the callers' shell options."""
    env = {"PATH": os.environ["PATH"], "TUNAOS_SELINUX_ROOT": str(root)}
    return subprocess.run(
        ["bash", "-c", f'set -euo pipefail\nsource "{LIB}"\n{body}\necho REACHED-END'],
        env=env,
        capture_output=True,
        text=True,
    )


def test_flip_of_a_file_with_nothing_to_flip_does_not_abort_under_errexit(
    tmp_path: Path,
) -> None:
    root = _tree(
        tmp_path, useradd_home="/var/home", subs_dist=SUBS_EL, rules_under="/var/home"
    )
    files = root / "etc/selinux/targeted/contexts/files"
    r = _strict(root, f'_selhome_flip_file "{files}/file_contexts.subs_dist" /var/home')
    assert r.returncode == 0, r.stderr
    assert "REACHED-END" in r.stdout
    assert _subs_dist(root) == SUBS_EL


def test_fix_and_gate_work_with_subs_dist_but_no_local_subs(tmp_path: Path) -> None:
    root = _tree(
        tmp_path, useradd_home="/var/home", subs_dist=SUBS_FEDORA, rules_under="/var/home"
    )
    (root / "etc/selinux/targeted/contexts/files/file_contexts.subs").unlink()
    r = _strict(root, "selhome_fix\nselhome_check")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "REACHED-END" in r.stdout
    assert "subs=[/var/lib/xguest/home -> /home" in r.stdout
    assert "/home -> /var/home]" in r.stdout
    assert "/home /var/home\n" in _subs_dist(root)


def test_fix_refuses_a_home_aliased_to_two_targets(tmp_path: Path) -> None:
    # Flipping both would leave two aliases onto /var/home and lose one target.
    root = _tree(
        tmp_path,
        useradd_home="/var/home",
        subs_dist=SUBS_FEDORA,
        rules_under="/var/home",
        local_subs="/var/home /srv/home\n",
    )
    files = root / "etc/selinux/targeted/contexts/files"
    before = (_subs_dist(root), (files / "file_contexts.subs").read_text())
    r = _strict(root, "selhome_fix")
    assert r.returncode == 2, r.stdout + r.stderr
    assert "REACHED-END" not in r.stdout
    assert "/var/home is aliased to more than one target" in r.stderr
    assert "conflict" in r.stderr
    assert (_subs_dist(root), (files / "file_contexts.subs").read_text()) == before


def test_fix_on_an_already_reversed_tree_is_idempotent_under_errexit(
    tmp_path: Path,
) -> None:
    root = _tree(
        tmp_path, useradd_home="/var/home", subs_dist=SUBS_FEDORA, rules_under="/var/home"
    )
    files = root / "etc/selinux/targeted/contexts/files"
    r = _strict(
        root,
        "selhome_fix\n"
        "selhome_fix\n"
        f'_selhome_flip_file "{files}/file_contexts.subs_dist" /var/home\n'
        "selhome_check",
    )
    assert r.returncode == 0, r.stdout + r.stderr
    assert "REACHED-END" in r.stdout
    assert r.stderr.count("flipped alias") == 1
    assert _subs_dist(root) == SUBS_FEDORA.replace("/var/home            /home", "/home /var/home")


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


# ── Overlay builds: -hwe, -nvidia, -gdx ────────────────────────────────────
#
# An overlay chains on the PUBLISHED parent instead of rebuilding it, and its
# kernel/driver transactions can replace selinux-policy (which rewrites
# file_contexts.subs_dist). So the gate in install-desktop.sh does not cover
# the image an overlay publishes; the overlay build has to run it itself.

AFFECTED_VARIANTS = ("albacore", "yellowfin", "skipjack")
OVERLAY_FLAVORS = ("gnome-hwe", "gnome-nvidia", "gdx-hwe")
# Steps that can replace selinux-policy or lay files over /etc: the overlay
# dispatch (kernel/driver transactions), package installs, the system_files copy.
_TRANSACTION = re.compile(
    r"build_scripts/overlay/|00-copy-files\.sh"
    r"|\b(pacman|dnf|apt-get|zypper)\b[^;&|]*\s(-S\S*|install|upgrade|swap)\b"
)


def _resolve(variant: str, flavor: str) -> dict[str, str]:
    out = subprocess.run(
        ["bash", str(ROOT / "scripts/resolve-flavor.sh"), variant, flavor],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return dict(re.findall(r'^([A-Z_]+)="(.*)"$', out, re.M))


def _instructions(containerfile: Path) -> list[tuple[str, str]]:
    """(KEYWORD, arguments) per instruction, continuations joined, comments dropped."""
    out: list[tuple[str, str]] = []
    buf = ""
    for line in containerfile.read_text().splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if s.endswith("\\"):
            buf += s[:-1] + " "
            continue
        kw, _, rest = (buf + s).partition(" ")
        out.append((kw.upper(), rest.strip()))
        buf = ""
    return out


def _build_steps(variant: str, flavor: str) -> list[str]:
    """RUN arguments executed to build the flavor's --target, base stage first."""
    r = _resolve(variant, flavor)
    stages: dict[str, tuple[str, list[str]]] = {}
    current = None
    for kw, rest in _instructions(ROOT / r["CONTAINERFILE"]):
        if kw == "FROM":
            m = re.match(r"(?:--\S+\s+)*(\S+)(?:\s+as\s+(\S+))?", rest, re.I)
            assert m, rest
            current = (m.group(2) or f"<stage {len(stages)}>").lower()
            stages[current] = (m.group(1).lower(), [])
        elif kw == "RUN" and current is not None:
            stages[current][1].append(rest)
    target = r["DESKTOP_FLAVOR"].lower()
    assert target in stages, f"{flavor}: --target {target} is not a stage of {r['CONTAINERFILE']}"
    steps: list[str] = []
    name = target
    while name in stages:
        parent, runs = stages[name]
        steps = runs + steps
        name = parent
    return steps


def _gate_step(variant: str, flavor: str) -> str:
    steps = _build_steps(variant, flavor)
    gates = [i for i, s in enumerate(steps) if "checks/verify-selinux-home-labels.sh" in s]
    assert gates, f"{variant}:{flavor}: no build step runs verify-selinux-home-labels.sh"
    return steps[gates[-1]]


def _run_step(step: str, root: Path) -> subprocess.CompletedProcess[str]:
    """Execute a RUN step's shell form with the build context at the repo root."""
    m = re.match(r"((?:--\S+\s+)*)(.*)", step, re.S)
    assert m
    flags, command = m.group(1), m.group(2)
    # The scripts are reached through the context bind mount; without it the
    # step would fail on a missing file, not on labels.
    assert "from=context" in flags and "target=/run/context" in flags, flags
    env = {"PATH": os.environ["PATH"], "TUNAOS_SELINUX_ROOT": str(root)}
    return subprocess.run(
        ["sh", "-c", command.replace("/run/context", str(ROOT))],
        env=env,
        capture_output=True,
        text=True,
    )


@pytest.mark.parametrize("variant", AFFECTED_VARIANTS)
@pytest.mark.parametrize("flavor", OVERLAY_FLAVORS)
def test_overlay_builds_run_the_gate_after_their_package_transactions(
    variant: str, flavor: str
) -> None:
    steps = _build_steps(variant, flavor)
    gate = max(
        (i for i, s in enumerate(steps) if "checks/verify-selinux-home-labels.sh" in s),
        default=None,
    )
    assert gate is not None, f"{variant}:{flavor}: no build step runs the home-label gate"
    last_transaction = max(i for i, s in enumerate(steps) if _TRANSACTION.search(s))
    assert gate > last_transaction, (
        f"{variant}:{flavor}: the gate runs before step {last_transaction}, "
        f"which can still replace selinux-policy: {steps[last_transaction][:120]}"
    )


@pytest.mark.parametrize("flavor", OVERLAY_FLAVORS)
def test_overlay_gate_step_repairs_the_43_1_shape_first(tmp_path: Path, flavor: str) -> None:
    # A stale published parent (or an overlay transaction) carrying the 43.1
    # aliases is repaired, not just rejected.
    root = _tree(
        tmp_path, useradd_home="/var/home", subs_dist=SUBS_FEDORA, rules_under="/var/home"
    )
    r = _run_step(_gate_step("yellowfin", flavor), root)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "/home /var/home\n" in _subs_dist(root)
    assert "rule_type=default_t" not in r.stdout


@pytest.mark.parametrize("flavor", OVERLAY_FLAVORS)
def test_overlay_gate_step_fails_the_build_when_homes_stay_default_t(
    tmp_path: Path, flavor: str
) -> None:
    # Rules generated under a prefix no alias reaches: the fix has nothing to
    # reverse, so only the gate can stop this image, and its failure must fail
    # the step.
    root = _tree(
        tmp_path, useradd_home="/var/home", subs_dist=SUBS_EL, rules_under="/srv/home"
    )
    r = _run_step(_gate_step("yellowfin", flavor), root)
    assert r.returncode != 0, r.stdout + r.stderr
    assert "FAIL" in r.stderr and "default_t" in r.stderr


@pytest.mark.parametrize("flavor", OVERLAY_FLAVORS)
def test_overlay_gate_step_skips_images_without_selinux(tmp_path: Path, flavor: str) -> None:
    root = _tree(
        tmp_path, useradd_home="/var/home", subs_dist="", rules_under="/var/home", policy=False
    )
    r = _run_step(_gate_step("yellowfin", flavor), root)
    assert r.returncode == 0, r.stderr
    assert "no SELinux policy" in r.stdout + r.stderr
