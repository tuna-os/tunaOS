"""A failure message that names only what it wanted.

The live customize installs the installer flatpak, and when that fails the
only thing recorded is flatpak's own error:

    error: The application org.bootcinstaller.Installer/x86_64/master requires
    the runtime org.gnome.Platform/x86_64/50 which was not found

which reads as "flathub is missing". It is not necessarily that. In Live ISOs
run 32725309736 the `flatpak remote-add ... flathub` immediately above it had
SUCCEEDED, and an hour earlier installer-smoke run 32704425971 installed the
same application onto yellowfin-gnome without trouble. Same app, same runtime
requirement, different base -- and the message cannot tell those apart.

Three different situations produce that one line:
  * no flathub remote at all;
  * flathub present but carrying no //50 branch;
  * the app asking for a branch nobody publishes yet.

So the failure path now lists the configured remotes, the Platform/Sdk
branches those remotes actually carry, and what the app asks for. Only on
failure -- it costs nothing when the install works.

Tested by RUNNING the block with flatpak stubbed, because its risk is that a
diagnostic added to an error path is itself broken and nobody notices until
the error path runs. Every probe is `|| true`; a probe that fails must not
become the failure being diagnosed.
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "live-iso" / "common" / "src" / "customize-live.sh"


def failure_block() -> str:
    """The `if ! timeout ... flatpak install` block, dedented to run alone."""
    text = SCRIPT.read_text(encoding="utf-8")
    start = text.index("\t\tif ! timeout 900 flatpak install")
    end = text.index("\n\t\tfi\n", start) + len("\n\t\tfi\n")
    return "\n".join(l[2:] if l.startswith("\t\t") else l
                     for l in text[start:end].splitlines())


def _run(tmp_path: Path, *, install_ok: bool, sshd: bool):
    tmp_path.mkdir(parents=True, exist_ok=True)
    binb = tmp_path / "bin"
    binb.mkdir()
    (binb / "flatpak").write_text(
        "#!/bin/sh\n"
        'case "$1" in\n'
        f"  install) exit {0 if install_ok else 1};;\n"
        '  remotes) echo "flathub\thttps://dl.flathub.org/repo/";;\n'
        # remote-info succeeds only for //49, so the probe must report
        # PRESENT for 49 and absent for 50 -- the mismatch under diagnosis.
        '  remote-info) case "$4" in *//49) exit 0;; *) exit 1;; esac;;\n'
        "esac\n",
        encoding="utf-8",
    )
    (binb / "timeout").write_text('#!/bin/sh\nshift; exec "$@"\n', encoding="utf-8")
    for f in binb.iterdir():
        f.chmod(0o755)

    sd = tmp_path / "sd"
    sd.mkdir()
    if sshd:
        (sd / ".enable-sshd").write_text("", encoding="utf-8")

    script = tmp_path / "b.sh"
    script.write_text(
        f'SCRIPT_DIR="{sd}"\nINSTALLER_APP=org.bootcinstaller.Installer\n'
        + failure_block(),
        encoding="utf-8",
    )
    return subprocess.run(
        ["bash", str(script)], capture_output=True, text=True,
        env=dict(os.environ, PATH=f"{binb}:/usr/bin:/bin"),
    )


def test_the_block_was_extracted():
    body = failure_block()
    assert "flatpak install" in body
    assert "remote-ls" in body, body


def test_the_block_is_valid_shell(tmp_path):
    f = tmp_path / "b.sh"
    f.write_text(failure_block(), encoding="utf-8")
    proc = subprocess.run(["bash", "-n", str(f)], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr


def test_a_successful_install_prints_no_diagnostic(tmp_path):
    """It must stay quiet on the happy path, or it is noise on every build."""
    proc = _run(tmp_path, install_ok=True, sshd=False)
    assert proc.returncode == 0, proc.stderr
    assert "FAILED" not in proc.stdout, proc.stdout
    assert "what the remotes offer" not in proc.stdout, proc.stdout


def test_a_failed_install_names_the_available_branches(tmp_path):
    """The whole point: report what IS there, not only what was wanted."""
    proc = _run(tmp_path, install_ok=False, sshd=True)
    out = proc.stdout
    assert "what the remotes offer" in out, out
    assert "flathub" in out, out
    # The probe must report BOTH branches per remote, so "//50 absent while
    # //49 is present" is readable off one block rather than inferred.
    assert re.search(r"flathub\s+org\.gnome\.Platform//50\s+absent", out), out
    assert re.search(r"flathub\s+org\.gnome\.Platform//49\s+PRESENT", out), out
    # And it must name every remote it asked, not just the first.
    assert "tuna-os" in out, out


def test_the_dev_iso_still_continues_and_the_production_iso_still_fails(tmp_path):
    """The diagnostic must not change the outcome it is diagnosing."""
    dev = _run(tmp_path / "dev", install_ok=False, sshd=True)
    assert dev.returncode == 0, dev.stdout + dev.stderr
    assert "continuing (dev/e2e ISO)" in dev.stdout, dev.stdout

    prod = _run(tmp_path / "prod", install_ok=False, sshd=False)
    assert prod.returncode != 0, prod.stdout


def test_every_network_probe_is_time_bounded():
    """The probe must not be able to outlive the runner.

    The first version ran a bare `flatpak remote-ls --system`, which pulls the
    full index of every configured remote. Run 32728454277 was killed during
    exactly that command --

        + flatpak remote-ls --system --columns=ref
        ##[error]The runner has received a shutdown signal.

    -- so the listing never printed and the question it was added to answer
    stayed open. `|| true` guards a non-zero exit, not a probe slow enough to
    lose the runner, and I had claimed the former covered the latter.

    A diagnostic on an error path must be cheap, or it replaces one unanswered
    failure with another. This is asserted on the script text rather than by
    running it, because what matters is that no unbounded network call can
    reach production -- a stub cannot demonstrate the absence of one.
    """
    body = failure_block()

    calls = [
        l.strip()
        for l in body.splitlines()
        # Comments quote the very command this test forbids, as the record of
        # why it is forbidden. Match executable lines only.
        if not l.strip().startswith("#")
        and re.search(r"\bflatpak\s+(remote-ls|remote-info|remote-add)\b", l)
    ]
    assert calls, "no flatpak remote call found in the failure block"

    for call in calls:
        assert call.startswith("timeout ") or "timeout " in call, (
            f"unbounded flatpak network call on the failure path: {call!r}"
        )

    # remote-ls over every remote is the specific shape that cost a runner.
    executable = "\n".join(
        l for l in body.splitlines() if not l.strip().startswith("#")
    )
    assert not re.search(r"flatpak remote-ls --system\s+--columns", executable), (
        "bare `remote-ls --system` pulls every remote's full index; ask about "
        "the specific ref with remote-info instead"
    )
