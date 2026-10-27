"""tunaOS#3969: late screenshot failures must retain evidence and their verdict.

Falsification: behavioural — the unmodified c6d025b4 gate exits with status 37
without collecting after-failure evidence when initial paint succeeds and a
later screenshot fails. All guest commands are intercepted; no guest script,
process inspection, or service command executes on the test host.
"""

import os
import subprocess
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
GATE = ROOT / "scripts/gdm-login-gate.sh"


def run_gate(failing_shot="", evidence_status=0, login=True, diagnostics_status=0, diagnostics_scripts=None):
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        bindir = root / "bin"
        bindir.mkdir()
        out = root / "out"
        (out / "corral").mkdir(parents=True)
        (out / "corral/result.json").write_text("{}")
        scripts = {
            "sleep": "exit 0",
            "jq": """case "$*" in
*.host*) echo localhost;;
*.port*) echo 2222;;
*.user*) echo root;;
*.identityFile*) echo /fixture/key;;
esac""",
            "ssh": """while [[ $# -gt 0 ]]; do
case "$1" in
*@*) shift; break;;
-F|-i|-p|-o) shift 2;;
*) exit 99;;
esac
done
if [[ "$1" == bash ]]; then
    body="$(cat)"
    if [[ "$*" == 'bash -s -- sample 40' ]]; then
        echo sample >> "$STATE/collections"
        echo fixture-sample
        exit "$EVIDENCE_STATUS"
    elif [[ "$*" == 'bash -s -- once 0' ]]; then
        echo once >> "$STATE/collections"
        echo fixture-after-failure
        exit "$EVIDENCE_STATUS"
    elif [[ "$body" == *'for session in'* ]]; then
        [[ "$LOGIN" == 1 && -f "$STATE/password" ]] || exit 1
        echo 41
    elif [[ "$body" == *'==> loginctl sessions'* ]]; then
        if [[ "$EXECUTE_DIAGNOSTICS" == 1 ]]; then
            printf '%s\n' "$body" | /bin/bash -s -- "$4" "${5:-}"
            exit $?
        fi
        echo fixture-diagnostics
        exit "$DIAGNOSTICS_STATUS"
    elif [[ "$body" != *'test account already has a session'* ]]; then
        exit 98
    fi
elif [[ "$1" == busctl ]]; then
    case "${!#}" in
    Lock) touch "$STATE/locked";;
    GetActive)
        if [[ -f "$STATE/locked" ]]; then echo 'b true'; else echo 'b false'; fi;;
    *) exit 97;;
    esac
elif [[ "$1" == tee ]]; then
    cat >/dev/null
elif [[ "$1" != true && "$1" != mkdir && "$1" != systemctl && "$1" != loginctl ]]; then
    exit 96
fi""",
            "corral": """case "$1" in
screenshot)
    file="$4"
    echo "${file##*/}" >> "$STATE/screenshots"
    if [[ "${file##*/}" == "$FAILING_SHOT" ]]; then exit 37; fi
    echo 'fixture — painted';;
type)
    if [[ "$3" == test-password ]]; then touch "$STATE/password"; fi;;
key)
    if [[ "$3" == ret && -f "$STATE/password" ]]; then rm -f "$STATE/locked"; fi;;
*) exit 95;;
esac""",
        }
        if diagnostics_scripts:
            scripts.update(diagnostics_scripts)
        for name, body in scripts.items():
            path = bindir / name
            path.write_text("#!/bin/bash\nset -eu\n" + body + "\n")
            path.chmod(0o755)
        env = dict(os.environ)
        env.update(
            PATH=f"{bindir}:/usr/bin:/bin",
            STATE=str(root),
            CORRAL=str(bindir / "corral"),
            FAILING_SHOT=failing_shot,
            EVIDENCE_STATUS=str(evidence_status),
            LOGIN=str(int(login)),
            DIAGNOSTICS_STATUS=str(diagnostics_status),
            EXECUTE_DIAGNOSTICS=str(int(diagnostics_scripts is not None)),
            TUNAOS_GDM_TEST_PASSWORD="test-password",
        )
        result = subprocess.run(
            ["/bin/bash", str(GATE), "fixture", str(out), "fixture-user"],
            env=env, capture_output=True, text=True, timeout=20, check=False,
        )
        collections = (root / "collections").read_text().splitlines()
        screenshots = (root / "screenshots").read_text().splitlines()
        after = out / "greeter-graphics-evidence-after-failure.txt"
        return result, collections, screenshots, after.read_text() if after.exists() else None

@pytest.mark.parametrize("shot", [
    "gdm-attempt-1.png", "gdm-logged-in.png", "gdm-locked.png", "gdm-unlocked.png",
])
@pytest.mark.parametrize("evidence_status", [0, 73])
def test_late_screenshot_failures_collect_once_and_keep_status(shot, evidence_status):
    result, collections, screenshots, after = run_gate(shot, evidence_status)
    assert result.returncode == 37, result.stderr
    assert screenshots[0] == "gdm-greeter.png"
    assert screenshots[-1] == shot
    assert collections == ["sample", "once"]
    assert after == "fixture-after-failure\n"


@pytest.mark.parametrize("evidence_status", [0, 73])
def test_success_keeps_login_lock_unlock_and_has_no_failure_collection(evidence_status):
    result, collections, screenshots, after = run_gate(evidence_status=evidence_status)
    assert result.returncode == 0, result.stderr
    for marker in ("LOGIN", "LOCK", "UNLOCK"):
        assert f"TUNAOS_GDM_{marker}_OK" in result.stdout
    assert screenshots[-1] == "gdm-unlocked.png"
    assert collections == ["sample"]
    assert after is None


def test_initial_paint_verdict_survives_failed_diagnostics():
    result, collections, _, after = run_gate(
        "gdm-greeter.png", evidence_status=73, diagnostics_status=55
    )
    assert result.returncode == 1, result.stderr
    assert "no painted frame appeared" in result.stderr
    assert "fixture-diagnostics" in result.stdout
    assert collections == ["sample", "once"]
    assert after == "fixture-after-failure\n"


@pytest.mark.parametrize("shot,login,message", [
    ("", False, "GDM did not start an active Wayland session"),
    ("gdm-greeter.png", True, "no painted frame appeared"),
])
@pytest.mark.parametrize("evidence_status", [0, 73])
def test_explicit_failures_collect_once(shot, login, message, evidence_status):
    result, collections, _, after = run_gate(shot, evidence_status, login)
    assert result.returncode == 1, result.stderr
    assert message in result.stderr
    assert collections == ["sample", "once"]
    assert after == "fixture-after-failure\n"
