"""The gate that never executed, and reported 127 failures while not doing so.

scripts/e2e-installer-gui-checks.sh is the assertion that the right compositor
is running and the right installer frontend launched -- the per-flavor half of
the ISO axis. It has never run.

iso-e2e.sh uploads the TAP helpers FLAT, beside the check script:

    scp scripts/lib/e2e-assert.sh guest:${GUEST_HOME}/e2e-assert.sh
    ssh  TEST_LIB_DIR=${GUEST_HOME} bash ${GUEST_HOME}/e2e-installer-gui-checks.sh

and the script resolved them as `${TEST_LIB_DIR}/lib/e2e-assert.sh`, putting
`/lib` AFTER the expansion instead of inside the default. With TEST_LIB_DIR
set -- which is always, from the harness -- that names a directory the guest
does not have. From smoke run 32681262659:

    /home/liveuser/e2e-installer-gui-checks.sh: line 25:
      /home/liveuser/lib/e2e-assert.sh: No such file or directory
    /home/liveuser/e2e-installer-gui-checks.sh: line 54: check: command not found
    ...
    line 159: print_summary: command not found

`source` failed, `check` was never defined, every assertion evaporated onto
stderr, and bash exited 127. The harness printed that as

    ::warning::installer GUI checks reported 127 failure(s) for gnome

127 is bash for command-not-found. It is not a count of anything, and it was
a WARNING, in a mode that tolerates warnings.

Two properties, and the second matters more than the first:

1. THE SCRIPT RESOLVES ITS HELPERS TO WHERE THEY ARE UPLOADED. Tested by
   building the guest's layout on disk and RUNNING the script, because the bug
   was in a shell expansion -- reading the line is how it survived review.

2. A GATE THAT DID NOT RUN IS NOT A GATE THAT FOUND PROBLEMS. Non-strict mode
   exists to tolerate failed assertions, not an absent gate. The discriminator
   is the TAP summary: `# Results:` comes only from print_summary, the last
   statement of every check script, so its absence means the script never
   reached the end whatever the exit code claims.

The two sibling scripts get (1) right two different ways, which is exactly how
the odd one out went unnoticed. This file holds all three to one rule.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
HARNESS = SCRIPTS / "iso-e2e.sh"
CHECK_SCRIPTS = [
    "e2e-installer-gui-checks.sh",
    "e2e-smoke-checks.sh",
    "e2e-luks-checks.sh",
]


def _guest_layout(tmp_path: Path, script: str) -> Path:
    """Reproduce what iso-e2e.sh actually puts on the guest: both files flat."""
    home = tmp_path / "liveuser"
    home.mkdir()
    shutil.copy(SCRIPTS / script, home / script)
    shutil.copy(SCRIPTS / "lib" / "e2e-assert.sh", home / "e2e-assert.sh")
    return home


@pytest.mark.parametrize("script", CHECK_SCRIPTS)
def test_the_check_script_runs_in_the_layout_the_harness_creates(tmp_path, script):
    """Run it. A path bug in a shell expansion is invisible to reading."""
    home = _guest_layout(tmp_path, script)
    proc = subprocess.run(
        ["bash", str(home / script)],
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin", "TEST_LIB_DIR": str(home), "FLAVOR": "gnome"},
    )
    combined = proc.stdout + proc.stderr
    # The assertions themselves are expected to FAIL here -- this machine is
    # not a booted live guest. What must not happen is the helpers going
    # missing, which is the difference between a red gate and no gate.
    assert "No such file or directory" not in combined, combined
    assert "command not found" not in combined, combined
    assert "Bail out!" not in combined, combined
    # print_summary ran, so the exit status is a failure COUNT.
    assert "# Results:" in proc.stdout, combined
    assert proc.returncode != 127, "127 is command-not-found, not a count"


@pytest.mark.parametrize("script", CHECK_SCRIPTS)
def test_a_missing_helper_bails_out_instead_of_evaporating(tmp_path, script):
    """The guard: no helpers must be loud, not silently assertion-free."""
    home = tmp_path / "liveuser"
    home.mkdir()
    shutil.copy(SCRIPTS / script, home / script)  # helper deliberately absent
    proc = subprocess.run(
        ["bash", str(home / script)],
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin", "TEST_LIB_DIR": str(home), "FLAVOR": "gnome"},
    )
    out = proc.stdout + proc.stderr
    assert "Bail out!" in out, out
    # And it must NOT look like a completed run of zero failures.
    assert "# Results:" not in proc.stdout, out
    assert proc.returncode != 0


def _checks_ran(tmp_path, output: str, rc: str) -> subprocess.CompletedProcess:
    """Run the harness's own discriminator, lifted out of iso-e2e.sh."""
    text = HARNESS.read_text()
    start = text.index("checks_ran() {")
    end = text.index("\n}\n", start) + len("\n}\n")
    script = tmp_path / "cr.sh"
    script.write_text(text[start:end] + f'\nchecks_ran "$1" "$2" "installer GUI"\n')
    return subprocess.run(
        ["bash", str(script), output, rc], capture_output=True, text=True
    )


def test_a_run_with_no_tap_summary_is_a_hard_failure(tmp_path):
    """The exact pre-fix output, which the harness called a warning."""
    proc = _checks_ran(
        tmp_path,
        "# Installer GUI checks — flavor=gnome\n"
        "/home/liveuser/e2e-installer-gui-checks.sh: line 54: check: command not found\n",
        "127",
    )
    assert proc.returncode != 0
    assert "did not run to completion" in proc.stderr, proc.stderr
    # It must say plainly that 127 is not a count, or the next reader repeats
    # the reading that let this sit.
    assert "NOT a count of failed assertions" in proc.stderr, proc.stderr


def test_a_completed_run_with_failures_is_not_treated_as_absent(tmp_path):
    """It must be able to say YES, or every real red leg becomes 'did not run'."""
    proc = _checks_ran(
        tmp_path, "ok - a\nnot ok - b\n# Results: 1 passed, 1 failed, 2 total\n", "1"
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stderr == "", proc.stderr


def test_a_bail_out_reason_is_surfaced(tmp_path):
    """When the script said why, repeat it -- do not make someone find it."""
    proc = _checks_ran(
        tmp_path, "Bail out! cannot read assertion helpers at /home/liveuser/lib\n", "99"
    )
    assert proc.returncode != 0
    assert "cannot read assertion helpers" in proc.stderr, proc.stderr


@pytest.mark.parametrize("phase", ["run_smoke_checks", "run_installer_gui_checks"])
def test_both_on_guest_gates_are_wired_to_the_discriminator(phase):
    """A discriminator nothing calls is the same bug one level up."""
    text = HARNESS.read_text()
    start = text.index(f"{phase}() {{")
    end = text.index("\n}\n", start)
    assert "checks_ran " in text[start:end], f"{phase} does not call checks_ran"


# ── The screen contract had never seen the GNOME frontend ───────────────────
#
# tests/installer-screens.yaml was measured on 2026-08-07 against KDE, Niri,
# XFCE and COSMIC. gnome was absent from installer-smoke.yml's matrix until
# #1039, so upstream bootc-installer -- the frontend gnome actually runs -- was
# never OCRed. Run 32681262659 is the first time that cell has ever run, and it
# reported no 'disk' screen while crediting encryption and summary, which both
# sit after disk selection. Its heading is "Install Location".
#
# The same shape as the 'install' list before it: a frontend failing a screen it
# demonstrably reached is one wrong list, not a wording bug.

SCREENS = ROOT / "tests" / "installer-screens.yaml"


def _screen(sid):
    doc = yaml.safe_load(SCREENS.read_text())
    return next(s for s in doc["screens"] if s["id"] == sid)


def test_the_disk_contract_matches_the_gnome_frontends_own_heading():
    kws = [k.lower() for k in _screen("disk")["keywords"]]
    assert any(k in "install location" for k in kws), (
        "the gnome frontend's disk page is headed 'Install Location' "
        "(bootc_installer/gtk/default-disk.blp); no keyword matches it"
    )


def test_no_disk_keyword_carries_a_product_name():
    """The branding work must not be able to break this contract."""
    for k in _screen("disk")["keywords"]:
        low = k.lower()
        for name in ("tunaos", "bluefin", "aurora", "bazzite"):
            assert name not in low, f"{k!r} embeds a product name"


def test_the_required_screens_are_the_ones_a_walkthrough_can_reach():
    """install/done stay optional: a walkthrough stops at the summary rather
    than confirming a destructive install, so it cannot reach either."""
    import yaml

    doc = yaml.safe_load(SCREENS.read_text())
    required = {s["id"] for s in doc["screens"] if s["required"]}
    assert required == {"welcome", "disk", "summary"}, required


# ── The compositor's own reason for exiting ─────────────────────────────────
#
# greetd captures nothing from the session it runs. When xfwl4 exits at once,
# the journal holds greetd's bookkeeping and not one line from the process
# that died (run 32681262659):
#
#   greetd: pam_unix(greetd-greeter:session): session closed for user liveuser
#   greetd: error: check_children: greeter exited without creating a session
#
# repeated to start-limit-hit. That message is the entire evidence base on
# which this failure has been attributed to a missing DRM render node, and the
# same run disproves the attribution: the guest HAS /dev/dri/renderD128, and
# the kernel reports `[drm] features: -virgl`. Node present, 3D absent --
# different claims needing different evidence.
#
# So the session runs under systemd-cat and the workflow reads the tag. A log
# nobody prints is worth no more than no log, which is why both halves are
# pinned here.

LIVE_SRC = ROOT / "live-iso" / "common" / "src"
SESSION_TAG = "tunaos-live-session"
GREETD_ADAPTERS = ["desktop-xfce.sh", "desktop-niri.sh", "desktop-cosmic.sh"]


@pytest.mark.parametrize("adapter", GREETD_ADAPTERS)
def test_every_greetd_session_command_is_journal_captured(adapter):
    """Every one -- initial_session AND default_session, in every branch."""
    lines = [
        ln.strip()
        for ln in (LIVE_SRC / adapter).read_text().splitlines()
        if ln.strip().startswith("command = ")
    ]
    assert lines, f"{adapter} writes no greetd command; this test found nothing"
    for ln in lines:
        assert f"systemd-cat -t {SESSION_TAG}" in ln, ln


def test_the_adapters_checked_are_the_ones_that_write_greetd_configs():
    """Guard against the list above going stale as adapters are added."""
    writers = {
        p.name
        for p in LIVE_SRC.glob("desktop-*.sh")
        if "command = " in p.read_text()
    }
    assert writers == set(GREETD_ADAPTERS), writers


def test_the_workflow_prints_the_session_journal():
    body = (ROOT / ".github" / "workflows" / "installer-smoke.yml").read_text()
    assert f"journalctl -t {SESSION_TAG}" in body, (
        "the session now logs under a tag nothing reads"
    )


# ── A setup step that configures something and never checks it ──────────────
#
# `Sync image into rootless storage` runs `sudo podman save ... | podman load`.
# The second half is rootless, and on Ubuntu 24.04 -- which is the distro the
# kubic repo pins podman against in this very workflow -- an unprivileged
# clone(CLONE_NEWUSER) is refused by default:
#
#   kernel.apparmor_restrict_unprivileged_userns = 1
#
# podman reports that without naming it:
#
#   cannot clone: Permission denied
#   Error: cannot re-exec process
#   ##[error]Process completed with exit code 125
#
# (run 32688258870). Twelve minutes of image build happen first, because the
# first rootless command in the job is the one immediately after `Build OS
# image` -- so the cost of the missing diagnosis is a whole build, and the
# message names neither namespaces nor AppArmor nor the sysctl.
#
# The subuid/subgid step already existed to make rootless podman work. It set
# a precondition and never verified the thing it was a precondition FOR, which
# is the same shape as the helper-path bug above: configuration present,
# behaviour absent, nobody looking. So the step now PROVES it with the cheapest
# possible instance of the operation everything downstream needs.

LIVE_ISO_WORKFLOW = ROOT / ".github" / "workflows" / "live-iso-bootc.yml"


def _live_iso_steps():
    doc = yaml.safe_load(LIVE_ISO_WORKFLOW.read_text())
    return doc["jobs"]["build"]["steps"]


def _rootless_setup_step():
    for s in _live_iso_steps():
        if "Setup rootless podman" in s.get("name", ""):
            return s
    raise AssertionError("no rootless-podman setup step found")


def test_the_setup_step_runs_before_any_rootless_command():
    """Configuring userns after the thing that needs it would prove nothing.

    This used to key off a `Sync image into rootless storage` step by name.
    That step is gone: the build now runs image and ISO in one ROOT context,
    because the rootless commit ran past tacklebox's hardcoded 600s bound on
    a GitHub-hosted runner while the root one takes 133s (#1893). Keying on
    a step name meant the test broke the moment the step was removed rather
    than the moment the PROPERTY was violated, so it keys on the property
    now: whatever rootless commands exist, the setup precedes all of them.

    A rootless command here is a `podman` invocation NOT under sudo. The
    setup step is exempt — proving rootless podman works is what it is for.
    """
    steps = _live_iso_steps()
    names = [s.get("name", "") for s in steps]
    setup = next(i for i, n in enumerate(names) if "Setup rootless podman" in n)

    rootless = []
    for i, step in enumerate(steps):
        if i == setup:
            continue
        for line in str(step.get("run", "")).splitlines():
            code = line.split("#", 1)[0].strip()
            if not code:
                continue
            # `sudo podman ...` and `sudo -E env ... podman` are root; a bare
            # `podman` or one on the right of a pipe is not.
            for fragment in code.split("|"):
                fragment = fragment.strip()
                if re.match(r"^podman\b", fragment):
                    rootless.append((i, names[i], fragment[:60]))

    for i, name, fragment in rootless:
        assert setup < i, (
            f"step {i} ({name!r}) runs rootless podman ({fragment!r}) before "
            f"the setup step at index {setup}; configuring userns afterwards "
            f"proves nothing"
        )


def test_the_rootless_setup_step_is_still_present_as_a_guard():
    """It is kept deliberately even though nothing rootless remains.

    Nothing in this workflow needs rootless podman any more. The step costs
    a fraction of a second and its `podman unshare true` probe fails loudly,
    so if anyone restores a bare `just iso` it fails HERE naming the cause
    instead of twelve minutes into a build. Removing it would make that
    regression silent, so its presence is asserted rather than assumed.
    """
    assert _rootless_setup_step()["run"], "the rootless setup step has no body"


def test_the_setup_step_proves_rootless_podman_works(tmp_path):
    """Run the body with podman shimmed to fail; it must exit nonzero and SAY why."""
    import os
    import subprocess

    step = tmp_path / "step.sh"
    step.write_text(_rootless_setup_step()["run"], encoding="utf-8")

    shims = tmp_path / "bin"
    shims.mkdir()
    (shims / "sudo").write_text('#!/bin/sh\nexec "$@"\n')
    (shims / "podman").write_text("#!/bin/sh\nexit 1\n")  # userns refused
    (shims / "sysctl").write_text('#!/bin/sh\n[ "$1" = "-n" ] && { echo 1; exit 0; }\nexit 0\n')
    (shims / "tee").write_text("#!/bin/sh\ncat >/dev/null\n")
    for f in shims.iterdir():
        f.chmod(0o755)

    env = dict(os.environ, PATH=f"{shims}:/usr/bin:/bin", USER="runner")
    proc = subprocess.run(["bash", str(step)], capture_output=True, text=True, env=env)

    assert proc.returncode != 0, proc.stdout
    assert "cannot create a user namespace" in proc.stdout, proc.stdout
    # The values that identify WHICH gate is closed must be printed, or the
    # step just relocates an unexplained failure instead of explaining it.
    assert "apparmor_restrict_unprivileged_userns" in proc.stdout, proc.stdout


def test_the_setup_step_passes_when_the_namespace_can_be_created(tmp_path):
    """It must also be able to succeed, or it is a permanently red gate."""
    import os
    import subprocess

    step = tmp_path / "step.sh"
    step.write_text(_rootless_setup_step()["run"], encoding="utf-8")

    shims = tmp_path / "bin"
    shims.mkdir()
    (shims / "sudo").write_text('#!/bin/sh\nexec "$@"\n')
    (shims / "podman").write_text("#!/bin/sh\nexit 0\n")  # userns allowed
    (shims / "sysctl").write_text('#!/bin/sh\n[ "$1" = "-n" ] && { echo 0; exit 0; }\nexit 0\n')
    (shims / "tee").write_text("#!/bin/sh\ncat >/dev/null\n")
    for f in shims.iterdir():
        f.chmod(0o755)

    env = dict(os.environ, PATH=f"{shims}:/usr/bin:/bin", USER="runner")
    proc = subprocess.run(["bash", str(step)], capture_output=True, text=True, env=env)

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "can create a user namespace" in proc.stdout, proc.stdout


def test_the_gate_values_survive_log_truncation(tmp_path):
    """The diagnostic must land somewhere the job log's truncation cannot eat.

    `Build OS image` emits tens of thousands of lines, and the log download for
    that job comes back starting PART-WAY THROUGH it -- everything steps 1-6
    printed is simply absent. On run 32690010127 step 8 went from failing to
    passing across this change and the evidence for WHY was in the cut region,
    which is the same defect as never capturing it.
    """
    import os
    import subprocess

    step = tmp_path / "step.sh"
    step.write_text(_rootless_setup_step()["run"], encoding="utf-8")

    shims = tmp_path / "bin"
    shims.mkdir()
    (shims / "sudo").write_text('#!/bin/sh\nexec "$@"\n')
    (shims / "podman").write_text("#!/bin/sh\nexit 0\n")
    (shims / "sysctl").write_text('#!/bin/sh\n[ "$1" = "-n" ] && { echo 1; exit 0; }\nexit 0\n')
    (shims / "tee").write_text("#!/bin/sh\ncat >/dev/null\n")
    for f in shims.iterdir():
        f.chmod(0o755)

    summary = tmp_path / "summary.md"
    env = dict(
        os.environ,
        PATH=f"{shims}:/usr/bin:/bin",
        USER="runner",
        GITHUB_STEP_SUMMARY=str(summary),
    )
    proc = subprocess.run(["bash", str(step)], capture_output=True, text=True, env=env)
    assert proc.returncode == 0, proc.stdout + proc.stderr

    written = summary.read_text(encoding="utf-8")
    assert "apparmor_restrict_unprivileged_userns" in written, written
    # The VALUE, not just the key -- a summary naming the gate without saying
    # what it was set to settles nothing.
    assert "`1`" in written, written


def test_the_step_survives_a_missing_step_summary(tmp_path):
    """`set -u` plus an unset GITHUB_STEP_SUMMARY must not kill the step.

    Caught by this suite rather than by a run: the first version referenced the
    variable unguarded and died with `unbound variable` after the probe had
    already passed.
    """
    import os
    import subprocess

    step = tmp_path / "step.sh"
    step.write_text(_rootless_setup_step()["run"], encoding="utf-8")

    shims = tmp_path / "bin"
    shims.mkdir()
    (shims / "sudo").write_text('#!/bin/sh\nexec "$@"\n')
    (shims / "podman").write_text("#!/bin/sh\nexit 0\n")
    (shims / "sysctl").write_text('#!/bin/sh\n[ "$1" = "-n" ] && { echo 0; exit 0; }\nexit 0\n')
    (shims / "tee").write_text("#!/bin/sh\ncat >/dev/null\n")
    for f in shims.iterdir():
        f.chmod(0o755)

    env = {k: v for k, v in os.environ.items() if k != "GITHUB_STEP_SUMMARY"}
    env.update(PATH=f"{shims}:/usr/bin:/bin", USER="runner")
    proc = subprocess.run(["bash", str(step)], capture_output=True, text=True, env=env)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "unbound variable" not in proc.stderr, proc.stderr
