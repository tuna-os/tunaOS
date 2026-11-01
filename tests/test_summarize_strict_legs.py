"""The strict qualification job reports one verdict per leg, from real evidence.

``scripts/iso-e2e.sh --strict-offline-gui`` keeps going after a failed leg, so
the job's single exit code hid which leg stopped. ``summarize-strict-legs.py``
reads only the files the harness wrote. The fixtures under
``tests/fixtures/native-iso/run40093907774`` are the retained files of that
run (head 3e61b0e0): the plain leg installed and booted cold and warm, and the
encrypted leg's unmodified installed cold boot showed no passphrase prompt.

Falsification: a summary that calls the encrypted leg "passed", drops it, or
labels an unrelated failure as the #3380 prompt problem fails below. None of
these tests install or boot a guest.
"""

from __future__ import annotations

import importlib.util
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/summarize-strict-legs.py"
FIXTURE = ROOT / "tests/fixtures/native-iso/run40093907774"

spec = importlib.util.spec_from_file_location("summarize_strict_legs", SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def fragment(leg: str, **override) -> dict:
    """A per-leg fragment with the keys the harness writes."""
    value = {
        "mode": leg,
        "installed_boot": True,
        "desktop_contract": True,
        "cold_boot": True,
        "warm_boot": True,
        "media_detached": True,
        "boot_arguments_unmodified": True,
        "passphrase_prompt": leg == "luks",
        "source_digest": "sha256:" + "a" * 64,
        "booted_digest": "sha256:" + "a" * 64,
        "target_imgref": "ghcr.io/tuna-os/skipjack:gnome",
        "duration_s": 583,
        "install_duration_s": 453,
        "cold_boot_s": 17,
        "warm_boot_s": 10,
    }
    value.update(override)
    return value


@pytest.fixture()
def out(tmp_path: Path) -> Path:
    """The retained layout of the failed run, without a plain fragment."""
    target = tmp_path / "iso-e2e-out"
    shutil.copytree(FIXTURE, target)
    return target


def verdicts(root: Path) -> dict[str, tuple[str, str]]:
    return {mode: mod.judge(root, mode) for mode in mod.MODES}


def test_real_failed_run_reports_each_leg_on_its_own(out):
    result = verdicts(out)
    assert result["plain"][0] == "passed (evidence log only)"
    assert result["luks"][0] == "failed: unresolved prompt visibility (#3380)"
    detail = result["luks"][1]
    assert "GUI install completed" in detail
    assert "unchanged_frame_timeout" in detail
    assert "tdx_warning" in detail


def test_summary_of_the_real_run_is_not_qualified(out):
    text = mod.summarize(out)
    assert "| plain | passed (evidence log only) |" in text
    assert "| luks | failed: unresolved prompt visibility (#3380) |" in text
    assert "Not qualified" in text
    assert "qualification-evidence.json" not in text


def test_harness_fragment_is_a_pass_and_outranks_the_log(out):
    (out / "strict-qual-plain.json").write_text(json.dumps(fragment("plain")))
    verdict, detail = mod.judge(out, "plain")
    assert verdict == "passed"
    assert "cold 17s" in detail and "warm 10s" in detail


@pytest.mark.parametrize(
    "override",
    [
        {"mode": "luks"},
        {"warm_boot": False},
        {"media_detached": False},
        {"boot_arguments_unmodified": False},
        {"installed_boot": None},
        {"passphrase_prompt": True},
    ],
)
def test_a_fragment_missing_an_observation_is_rejected(out, override):
    (out / "strict-qual-plain.json").write_text(json.dumps(fragment("plain", **override)))
    verdict, _ = mod.judge(out, "plain")
    assert verdict == "failed: leg fragment rejected"


def test_luks_fragment_must_show_the_prompt(out):
    (out / "strict-qual-luks.json").write_text(json.dumps(fragment("luks", passphrase_prompt=False)))
    assert mod.judge(out, "luks")[0] == "failed: leg fragment rejected"
    (out / "strict-qual-luks.json").write_text(json.dumps(fragment("luks")))
    assert mod.judge(out, "luks")[0] == "passed"


def test_malformed_fragment_is_a_failure_not_a_pass(out):
    (out / "strict-qual-plain.json").write_text("[]")
    assert mod.judge(out, "plain")[0] == "failed: malformed leg fragment"
    (out / "strict-qual-plain.json").write_text("{")
    assert mod.judge(out, "plain")[0] == "failed: malformed leg fragment"


def test_the_prompt_label_needs_the_helper_line(out):
    """An unrelated installed-boot failure must not borrow the #3380 label."""
    log = out / "strict-luks-installed-serial.log"
    log.write_text(log.read_text().replace("!!! passphrase prompt never appeared", "!!! something else"))
    verdict, _ = mod.judge(out, "luks")
    assert verdict == "failed: installed boot did not verify"
    assert "#3380" not in verdict


def test_unlock_without_userspace_has_its_own_label(out):
    log = out / "strict-luks-installed-serial.log"
    log.write_text("!!! first boot never reached userspace after unlock\n")
    assert mod.judge(out, "luks")[0] == "failed: installed boot did not reach userspace after unlock"


def test_the_prompt_label_needs_a_completed_gui_install(out):
    """No prompt line counts when the GUI install itself never finished."""
    report = out / "walkthrough-luks/walkthrough-gnome.json"
    value = json.loads(report.read_text())
    value.update(completed=False, accepted=False)
    value["transitions"] = ["welcome", "encryption", "summary"]
    report.write_text(json.dumps(value))
    verdict, detail = mod.judge(out, "luks")
    assert verdict == "failed: installer GUI did not complete"
    assert "last state `summary`" in detail


def test_missing_gui_report_is_reported(out):
    (out / "walkthrough-luks/walkthrough-gnome.json").unlink()
    assert mod.judge(out, "luks")[0] == "failed: installer GUI report absent"


def test_a_leg_that_never_started_is_not_run(tmp_path):
    assert mod.judge(tmp_path, "luks") == ("not run", "no start marker, no installer report")


def test_two_passing_legs_still_need_the_receipt(out):
    for mode in mod.MODES:
        (out / f"strict-qual-{mode}.json").write_text(json.dumps(fragment(mode)))
    text = mod.summarize(out)
    assert "target is not qualified" in text
    (out / "qualification-evidence.json").write_text("{}")
    text = mod.summarize(out)
    assert "does not qualify the target" in text
    assert "Not qualified" not in text


def test_fragment_keys_match_what_the_harness_writes():
    """The test fragment must track verify_strict_installed_boot's writer."""
    source = (ROOT / "scripts/iso-e2e.sh").read_text()
    block = source[source.index("frag = {") :]
    block = block[: block.index("\n}\n")]
    written = set(re.findall(r'"(\w+)":', block))
    assert written == set(fragment("plain"))
    assert set(mod.REQUIRED_TRUE) <= written


def test_cli_prints_markdown_and_rejects_a_bad_directory(out, tmp_path):
    ok = subprocess.run([sys.executable, str(SCRIPT), str(out)], capture_output=True, text=True)
    assert ok.returncode == 0, ok.stderr
    assert ok.stdout.startswith("## Strict offline GUI qualification: per-leg verdicts")
    bad = subprocess.run(
        [sys.executable, str(SCRIPT), str(tmp_path / "absent")], capture_output=True, text=True
    )
    assert bad.returncode == 2
    usage = subprocess.run([sys.executable, str(SCRIPT)], capture_output=True, text=True)
    assert usage.returncode == 2


def test_xfce_summary_uses_only_the_selected_frontend_report(tmp_path):
    walk=tmp_path/'walkthrough-plain';walk.mkdir()
    gui={'submitted':True,'accepted':True,'completed':True,'transitions':['welcome','done']}
    (walk/'walkthrough-xfce.json').write_text(json.dumps(gui))
    assert mod.judge(tmp_path,'plain','xfce')[0]=='failed: installed boot did not verify'
    assert mod.judge(tmp_path,'plain')[0]=='not run'
    gui['completed']=False
    (walk/'walkthrough-xfce.json').write_text(json.dumps(gui))
    assert mod.judge(tmp_path,'plain','xfce')[0]=='failed: installer GUI did not complete'
    result=subprocess.run([sys.executable,str(SCRIPT),str(tmp_path),'xfce'],capture_output=True,text=True)
    assert result.returncode==0 and 'installer GUI did not complete' in result.stdout
    bad=subprocess.run([sys.executable,str(SCRIPT),str(tmp_path),'unknown'],capture_output=True,text=True)
    assert bad.returncode==2
