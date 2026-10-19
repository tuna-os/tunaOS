"""Two-phase shell wiring with a fake adapter; these are not native solver proof."""
import json
import os
from pathlib import Path
import subprocess

import pytest

from tests.test_fork_package_consumer import manifest

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "build_scripts/lib/fork-packages.sh"


@pytest.fixture
def run(tmp_path):
    context = tmp_path / "context"
    (context / "manifests").mkdir(parents=True)
    output = tmp_path / "root"
    output.mkdir()
    payload = manifest(add=["htop"], remove=["fastfetch"])
    (context / "manifests/fork-config.json").write_text(json.dumps(payload))
    log = tmp_path / "log"
    script = r'''
set -euo pipefail
source "$HELPER"
uname() { echo x86_64; }
pkg_refresh() { echo refresh >> "$LOG"; }
pkg_install() { echo "install:$*" >> "$LOG"; [[ "${FAIL_INSTALL:-0}" == 0 ]]; }
python3() {
    local action="$2"
    echo "$action" >> "$LOG"
    case "$action" in
        validate) return 0 ;;
        capture) printf '%064d\n' 0 ;;
        apply) [[ "${FAIL_APPLY:-0}" == 0 ]] ;;
        verify-complete) [[ "${FAIL_VERIFY:-0}" == 0 ]] ;;
        *) return 99 ;;
    esac
}
tunaos_apply_fork_packages "$CONTEXT" "$ROOT"
receipt="$ROOT/usr/share/tunaos/fork-config/packages/yellowfin--gnome--linux-amd64.json"
jq -e '.status == "pending-removal" and .remove == []' "$receipt" >/dev/null
echo desktop-setup >> "$LOG"
if [[ "${LOSE_BASELINE:-0}" == 1 ]]; then unset TUNAOS_FORK_REMOVAL_BASELINE_SHA256; fi
if [[ "${CHANGE_MANIFEST:-0}" == 1 ]]; then
    jq '.intent.packages.add = ["vim"]' "$CONTEXT/manifests/fork-config.json" > "$CONTEXT/changed"
    mv "$CONTEXT/changed" "$CONTEXT/manifests/fork-config.json"
fi
tunaos_finalize_fork_packages "$CONTEXT" gnome "$ROOT"
if [[ "${SECOND_SHELL:-0}" == 1 ]]; then
    export -f python3 uname pkg_refresh pkg_install
    bash -c 'source "$HELPER"; tunaos_apply_fork_packages "$CONTEXT" "$ROOT" && tunaos_finalize_fork_packages "$CONTEXT" gnome "$ROOT"'
fi
'''

    def invoke(**env):
        result = subprocess.run(["bash", "-c", script], text=True, capture_output=True,
                                env=dict(os.environ, HELPER=str(HELPER), CONTEXT=str(context),
                                         ROOT=str(output), LOG=str(log), PKG_MGR="dnf",
                                         IMAGE_NAME_VARIANT="yellowfin", TUNAOS_IMAGE_FLAVOR="gnome", **env))
        receipts = list(output.glob("usr/share/tunaos/fork-config/packages/*.json"))
        receipt = json.loads(receipts[0].read_text()) if receipts else None
        return result, log.read_text().splitlines(), receipt
    return invoke


def test_capture_precedes_additions_and_remove_follows_desktop_setup(run):
    result, events, receipt = run()
    assert result.returncode == 0, result.stderr
    assert events == ["validate", "capture", "refresh", "install:htop", "desktop-setup", "validate", "apply"]
    assert receipt["status"] == "complete"
    assert receipt["remove"] == ["fastfetch"]


@pytest.mark.parametrize("failure", ["FAIL_APPLY", "LOSE_BASELINE", "CHANGE_MANIFEST"])
def test_failed_finalization_never_completes_receipt(run, failure):
    result, events, receipt = run(**{failure: "1"})
    assert result.returncode != 0
    assert receipt["status"] == "pending-removal"
    assert receipt["remove"] == []
    if failure != "FAIL_APPLY":
        assert "apply" not in events


def test_addition_failure_cannot_reach_removal_or_receipt(run):
    result, events, receipt = run(FAIL_INSTALL="1")
    assert result.returncode != 0
    assert "apply" not in events
    assert receipt is None


def test_absent_manifest_finalizer_is_noop_without_tools(tmp_path):
    result = subprocess.run(["/bin/bash", "-c", 'source "$1"; tunaos_finalize_fork_packages "$2" gnome',
                             "test", str(HELPER), str(tmp_path)], env={"PATH": str(tmp_path)},
                            text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    assert list(tmp_path.iterdir()) == []


def test_both_desktop_entrypoints_finalize_after_branding():
    for relative in ("install-desktop.sh", "configure-desktop-runtime.sh"):
        source = (ROOT / "build_scripts/desktop" / relative).read_text()
        assert source.index("tunaos_apply_fork_packages") < source.index("tunaos_finalize_fork_packages")
        assert source.rindex("tunaos_apply_fork_branding") < source.index("tunaos_finalize_fork_packages")


def test_second_desktop_shell_only_verifies_completed_removal(run):
    result, events, receipt = run(SECOND_SHELL="1")
    assert result.returncode == 0, result.stderr
    assert events.count("capture") == events.count("apply") == 1
    assert events[-1] == "verify-complete"
    assert receipt["status"] == "complete"


def test_second_shell_propagates_failed_completed_state_verification(run):
    result, events, _ = run(SECOND_SHELL="1", FAIL_VERIFY="1")
    assert result.returncode != 0
    assert events.count("apply") == 1
    assert events[-1] == "verify-complete"
