"""Strict installed boots consume the runtime branding verdict, never assume it.

scripts/lib/branding_marker.py parses the `TUNAOS_BRANDING_REPORT` /
`TUNAOS_BRANDING_OK|FAIL` lines an installed image prints on serial;
scripts/iso-e2e.sh folds them into strict evidence and applies
TUNAOS_STRICT_BRANDING=report|block. scripts/lib/branding_ocr.py checks the
first-boot drivers' OCR text for the product name and upstream names. No
published image prints the markers yet, so every log here is synthetic.
No guest, no VNC, no OCR binaries.
"""

import json
import os
import socket
import subprocess
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from lib import branding_marker as bm
from lib import branding_ocr as bo
from lib import gnome_first_boot as gfb

SOURCE = (ROOT / "scripts/iso-e2e.sh").read_text()
REPORT_OK = {"schema": 1, "variant": "yellowfin", "name": "Yellowfin", "desktop": "gnome",
             "result": "ok", "failed": [], "checks": [{"id": "hostname", "status": "pass"}]}
REPORT_FAIL = dict(REPORT_OK, result="fail", failed=["hostname", "boot.efi"])
OK_LINE = "TUNAOS_BRANDING_OK variant=yellowfin desktop=gnome checks=14 skipped=2"
FAIL_LINE = "TUNAOS_BRANDING_FAIL variant=yellowfin desktop=gnome failed=hostname,boot.efi"


def report_line(value):
    return "TUNAOS_BRANDING_REPORT " + json.dumps(value, separators=(",", ":"))


def function(name):
    if name == "verify_strict_installed_boot":
        return SOURCE[SOURCE.index(name + "() {"): SOURCE.index("emit_qualification_evidence() {")]
    return name + "() {" + SOURCE.split(name + "() {", 1)[1].split("\n}\n", 1)[0] + "\n}\n"


# ── Marker parser ────────────────────────────────────────────────────


def test_ok_verdict_keeps_the_images_own_report():
    """Falsification: return the synthesized document instead of the parsed
    REPORT for a clean boot, or treat OK as anything but `ok`, and this fails."""
    parsed = bm.parse(f"[  OK  ] Started x\n{report_line(REPORT_OK)}\n{OK_LINE}\n")
    assert (parsed["result"], parsed["failed"], parsed["report"]) == ("ok", [], "parsed")
    assert bm.evidence_document(parsed) == REPORT_OK
    assert bm.summary_line(parsed) == "result=ok failed=- report=parsed"


def test_fail_verdict_carries_its_failed_ids():
    """Falsification: drop the `failed=` field of the FAIL line, or let the
    per-desktop sub-check `TUNAOS_BRANDING_GNOME_FAIL` stand in for the verdict,
    and the ids or the result below change."""
    log = (f"{report_line(REPORT_FAIL)}\n"
           "TUNAOS_BRANDING_GNOME_FAIL wallpaper=upstream\n"
           f"{FAIL_LINE}\n")
    parsed = bm.parse(log)
    assert (parsed["result"], parsed["failed"], parsed["report"]) == (
        "fail", ["hostname", "boot.efi"], "parsed")
    assert bm.summary_line(parsed) == "result=fail failed=hostname,boot.efi report=parsed"


def test_sub_check_alone_is_absent_not_fail():
    """Falsification: match `TUNAOS_BRANDING_<DESKTOP>_FAIL` as a verdict and a
    boot with no verdict line would read as `fail` instead of `absent`."""
    parsed = bm.parse("TUNAOS_BRANDING_GNOME_FAIL x=y\nTUNAOS_BRANDING_OKAY\n")
    assert parsed["result"] == "absent"
    assert bm.evidence_document(parsed) == {"result": "absent"}


def test_image_without_the_contract_is_absent():
    """Falsification: default a missing verdict to `ok` (a silent pass) and
    images built before the contract would qualify their branding."""
    parsed = bm.parse("TUNAOS_DESKTOP_CONTRACT_OK\nTUNAOS_IMAGE_IDENTITY digest=sha256:aa\n")
    assert (parsed["result"], parsed["report"]) == ("absent", "absent")
    assert bm.summary_line(parsed) == "result=absent failed=- report=absent"


def test_unparsable_report_still_takes_the_verdict_line():
    """Falsification: take the verdict from the REPORT JSON, or crash on it,
    and a REPORT cut by an interleaved kernel line loses the FAIL verdict."""
    log = ('TUNAOS_BRANDING_REPORT {"schema":1,"variant":"yellowfin","fai'
           "[   12.345678] usb 1-1: new device\n"
           f"{FAIL_LINE}\n")
    parsed = bm.parse(log)
    assert (parsed["result"], parsed["failed"], parsed["report"]) == (
        "fail", ["hostname", "boot.efi"], "report_unparsable")
    assert bm.evidence_document(parsed) == {
        "result": "fail", "failed": ["hostname", "boot.efi"], "report": "unparsable"}


def test_carriage_returns_and_line_prefixes_are_tolerated():
    """Falsification: require the markers at line start, or keep the \\r, and
    journal-prefixed serial lines with CRLF endings no longer parse."""
    log = ("\x1b[0m[  OK  ] Reached target\r\n"
           f"Nov 21 10:00:01 host verify-branding[812]: {report_line(REPORT_FAIL)}\r\n"
           "[   13.000001] random: crng init done\r\n"
           f"Nov 21 10:00:01 host verify-branding[812]: {FAIL_LINE}\r\n")
    parsed = bm.parse(log)
    assert (parsed["result"], parsed["failed"], parsed["report"]) == (
        "fail", ["hostname", "boot.efi"], "parsed")
    assert parsed["document"] == REPORT_FAIL


def test_last_boot_in_one_log_wins_and_keeps_its_own_report():
    """Falsification: take the first verdict, or pair the last verdict with an
    earlier boot's REPORT, and a log holding two boots reports the wrong one."""
    log = "\n".join([report_line(REPORT_FAIL), FAIL_LINE, "--- reboot ---", OK_LINE]) + "\n"
    parsed = bm.parse(log)
    assert (parsed["result"], parsed["failed"], parsed["report"]) == ("ok", [], "absent")
    assert bm.evidence_document(parsed) == {"result": "ok", "failed": [], "report": "absent"}
    log = "\n".join([report_line(REPORT_OK), OK_LINE, report_line(REPORT_FAIL), FAIL_LINE])
    assert bm.parse(log)["result"] == "fail"


def test_failed_ids_never_carry_serial_noise_into_evidence():
    """Falsification: copy `failed=` verbatim and serial garbage lands in the
    one-line evidence record that downstream parsers split on spaces/commas."""
    parsed = bm.parse("TUNAOS_BRANDING_FAIL failed=hostname,$(rm),desktop.gnome.user\n")
    assert parsed["failed"] == ["hostname", "desktop.gnome.user"]


def test_summarize_cli_writes_the_evidence_file(tmp_path):
    """Falsification: print the summary without writing the JSON (or write it
    elsewhere) and strict-<mode>-<phase>-branding.json is missing."""
    log, out = tmp_path / "serial.log", tmp_path / "strict-plain-cold-branding.json"
    log.write_text(f"{report_line(REPORT_OK)}\n{OK_LINE}\n")
    result = subprocess.run([sys.executable, str(ROOT / "scripts/lib/branding_marker.py"),
                             "summarize", "--log", str(log), "--out", str(out)],
                            capture_output=True, text=True, timeout=10, check=True)
    assert result.stdout.strip() == "result=ok failed=- report=parsed"
    assert json.loads(out.read_text()) == REPORT_OK


def test_wait_returns_on_verdict_or_deadline(tmp_path):
    """Falsification: drop the deadline check (the grace would never end) or
    the file check (a present verdict would still wait out the grace)."""
    log = tmp_path / "serial.log"
    log.write_text("booting\n")
    now = [100.0]

    def sleep(seconds):
        now[0] += max(seconds, 1)

    assert bm.wait(str(log), 110, clock=lambda: now[0], sleep=sleep) == 3
    assert now[0] >= 110
    log.write_text(f"booting\n{OK_LINE}\n")
    assert bm.wait(str(log), 0, clock=lambda: now[0], sleep=sleep) == 0


def test_socket_reader_keeps_only_marker_lines(tmp_path):
    """Falsification: append every serial line (the LUKS boot's unredacted
    console would reach evidence) or stop before the verdict, and this fails."""
    path = str(tmp_path / "serial.sock")
    log = tmp_path / "installed.log"
    log.write_text("LUKS_FIRST_BOOT_DESKTOP_CONTRACT=ok\n")
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(path)
    server.listen(1)

    def guest():
        conn, _ = server.accept()
        with conn:
            conn.sendall(b"secret console text\r\n" + report_line(REPORT_OK).encode()
                         + b"\r\n[  14.0] audit: x\r\n" + OK_LINE.encode()[:12])
            conn.sendall(OK_LINE.encode()[12:] + b"\r\nafter verdict\r\n")
            threading.Event().wait(2)

    thread = threading.Thread(target=guest, daemon=True)
    thread.start()
    try:
        assert bm.wait(str(log), 10**10, sock_path=path) == 0
    finally:
        server.close()
    text = log.read_text()
    assert "secret console text" not in text and "audit" not in text
    assert text.endswith(report_line(REPORT_OK) + "\n" + OK_LINE + "\n")


# ── iso-e2e.sh policy and evidence ───────────────────────────────────

def bash(script, env, *args):
    return subprocess.run(["bash", "-c", script, "test", *args], env={**os.environ, **env},
                          capture_output=True, text=True, timeout=30, check=False)


@pytest.mark.parametrize("value,expected", [("", "report"), ("report", "report"),
                                            ("block", "block")])
def test_policy_defaults_to_report(value, expected):
    """Falsification: default to block, or rename the variable, and the
    report-mode rollout changes every strict verdict."""
    env = {"TUNAOS_STRICT_BRANDING": value} if value else {}
    result = bash(function("strict_branding_mode") + "\nstrict_branding_mode", env)
    assert result.returncode == 0 and result.stdout.strip() == expected


@pytest.mark.parametrize("value", ["Block", "warn", "1"])
def test_unknown_policy_is_an_error_not_a_fallback(value):
    """Falsification: map an unknown value to report and a typo in the
    repository variable silently keeps branding non-blocking."""
    result = bash(function("strict_branding_mode") + "\nstrict_branding_mode",
                  {"TUNAOS_STRICT_BRANDING": value})
    assert result.returncode == 2
    assert "must be report or block" in result.stderr


COLLECT = "\n".join(function(name) for name in (
    "strict_branding_mode", "strict_branding_grace", "strict_branding_collect")) + r'''
strict_offline_evidence() { printf '%s\n' "$*" >>"$OUTPUT_DIR/evidence.log"; }
strict_branding_collect plain "$1" "$2" "$(date +%s)"
rc=$?
printf '%s\n' "$STRICT_BRANDING_SUMMARY" >"$OUTPUT_DIR/summary"
exit "$rc"
'''


@pytest.mark.parametrize("policy", ["report", "block"])
@pytest.mark.parametrize("serial,result,failed", [
    (f"{report_line(REPORT_OK)}\n{OK_LINE}\n", "ok", "-"),
    (f"{report_line(REPORT_FAIL)}\n{FAIL_LINE}\n", "fail", "hostname,boot.efi"),
    ("TUNAOS_DESKTOP_CONTRACT_OK\n", "absent", "-"),
])
def test_collect_applies_the_policy(tmp_path, policy, serial, result, failed):
    """Falsification: let report mode fail the leg, let block mode pass a FAIL
    or absent verdict, or drop the evidence line / file, and this fails."""
    log = tmp_path / "serial.log"
    log.write_text(serial)
    run = bash(COLLECT, {"OUTPUT_DIR": str(tmp_path), "SCRIPT_DIR": str(ROOT / "scripts"),
                         "TUNAOS_STRICT_BRANDING": policy, "STRICT_BRANDING_GRACE": "0",
                         "QEMU_PIDFILE": str(tmp_path / "qemu.pid")}, "cold", str(log))
    blocked = policy == "block" and result != "ok"
    assert run.returncode == (1 if blocked else 0), run.stderr
    evidence = (tmp_path / "evidence.log").read_text()
    assert f"installed_plain_cold_branding={result} failed={failed}\n" == evidence
    assert json.loads((tmp_path / "strict-plain-cold-branding.json").read_text())["result"] == result
    summary = (tmp_path / "summary").read_text()
    assert summary.startswith(f"result={result} failed={failed} ")
    assert summary.strip().endswith("file=strict-plain-cold-branding.json")
    if blocked:
        assert "ERROR" in run.stderr and failed in run.stderr
    elif result != "ok":
        assert "WARNING" in run.stderr and "reported only" in run.stderr


@pytest.mark.parametrize("policy,expected", [("report", 0), ("block", 1)])
def test_plain_leg_folds_branding_into_the_fragment(tmp_path, policy, expected):
    """Falsification: skip strict_branding_collect on either boot, or omit the
    `branding` object from strict-qual-plain.json, and the cold/warm verdicts
    below go missing; in block mode a FAIL warm boot must emit no fragment."""
    (tmp_path / "strict-plain-disk.qcow2").touch()
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "lib").symlink_to(ROOT / "scripts/lib")
    resolver = scripts / "published-image-ref.sh"
    resolver.write_text("#!/bin/sh\necho ghcr.io/tuna-os/yellowfin:gnome\n")
    resolver.chmod(0o700)
    harness = "set -o pipefail\n" + "\n".join(function(name) for name in (
        "strict_require_unmodified_boot", "strict_require_desktop_contract",
        "strict_branding_mode", "strict_branding_grace", "strict_branding_watch",
        "strict_branding_collect", "verify_strict_installed_boot")) + r'''
IDENTITY="TUNAOS_IMAGE_IDENTITY digest=sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa targetImgref=ghcr.io/tuna-os/yellowfin:gnome"
strict_launch_installed() {
    printf '%s\n' TUNAOS_DESKTOP_CONTRACT_OK "$IDENTITY" >>"$SERIAL_LOG"
    if [[ "$3" == *cold ]]; then
        printf '%s\n' "$COLD_REPORT" "$COLD_VERDICT" >>"$SERIAL_LOG"
    else
        printf '%s\n' "$WARM_VERDICT" >>"$SERIAL_LOG"
    fi
}
sleep() { :; }
boot_failed_on_serial() { return 1; }
strict_poweroff_installed() { :; }
screenshot() { :; }
strict_offline_evidence() { printf '%s\n' "$*" >>"$OUTPUT_DIR/evidence.log"; }
strict_first_boot_required() { return 1; }
strict_verify_installed_identity() {
    STRICT_VERIFIED_BOOTED_DIGEST=sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
    STRICT_VERIFIED_BOOTED_REF="$3"
    STRICT_VERIFIED_BOOT_ID="$5-boot"
}
verify_strict_installed_boot plain
'''
    env = {"OUTPUT_DIR": str(tmp_path), "SCRIPT_DIR": str(scripts),
           "SERIAL_LOG": str(tmp_path / "serial.log"), "QEMU_PIDFILE": str(tmp_path / "qemu.pid"),
           "TIMEOUT": "120", "VARIANT": "yellowfin", "FLAVOR": "gnome",
           "STRICT_SOURCE_DIGEST": "sha256:" + "a" * 64, "STRICT_BRANDING_GRACE": "0",
           "TUNAOS_STRICT_BRANDING": policy, "COLD_REPORT": report_line(REPORT_OK),
           "COLD_VERDICT": OK_LINE, "WARM_VERDICT": FAIL_LINE}
    run = bash(harness, env)
    assert run.returncode == expected, run.stderr
    evidence = (tmp_path / "evidence.log").read_text()
    assert "installed_plain_cold_branding=ok failed=-" in evidence
    assert "installed_plain_warm_branding=fail failed=hostname,boot.efi" in evidence
    assert json.loads((tmp_path / "strict-plain-cold-branding.json").read_text()) == REPORT_OK
    assert json.loads((tmp_path / "strict-plain-warm-branding.json").read_text()) == {
        "result": "fail", "failed": ["hostname", "boot.efi"], "report": "absent"}
    fragment = tmp_path / "strict-qual-plain.json"
    if expected:
        assert not fragment.exists()
        return
    assert json.loads(fragment.read_text())["branding"] == {
        "cold": {"result": "ok", "failed": [], "report": "parsed",
                 "file": "strict-plain-cold-branding.json"},
        "warm": {"result": "fail", "failed": ["hostname", "boot.efi"], "report": "absent",
                 "file": "strict-plain-warm-branding.json"},
    }


PREPARE = "\n".join(function(name) for name in (
    "strict_branding_mode", "strict_branding_grace", "strict_branding_prepare")) + r'''
strict_offline_evidence() { printf '%s\n' "$*" >>"$OUTPUT_DIR/evidence.log"; }
strict_branding_prepare
rc=$?
printf '%s|%s' "${STRICT_BRANDING_PRODUCT:-}" "${STRICT_BRANDING_ACCENT:-}" >"$OUTPUT_DIR/product"
exit "$rc"
'''


@pytest.mark.parametrize("variant,policy,expected,product,accent", [
    ("yellowfin", "block", 0, "Yellowfin", "#c88800"),
    ("grouper", "report", 0, "Grouper", "#e95420"),
    ("no-such-variant", "report", 0, "", ""),
    ("no-such-variant", "block", 2, "", ""),
])
def test_prepare_resolves_product_and_accent_before_any_install(tmp_path, variant, policy,
                                                                expected, product, accent):
    """Falsification: continue in block mode without a product name or accent
    (those checks could never run), fail report mode on it, or map Ubuntu-based
    grouper to libadwaita orange instead of Yaru #E95420, and this fails."""
    run = bash(PREPARE, {"OUTPUT_DIR": str(tmp_path), "SCRIPT_DIR": str(ROOT / "scripts"),
                         "VARIANT": variant, "TUNAOS_STRICT_BRANDING": policy})
    assert run.returncode == expected, run.stderr
    assert (tmp_path / "product").read_text() == f"{product}|{accent}"
    if expected == 0:
        evidence = (tmp_path / "evidence.log").read_text()
        assert (f"branding_policy={policy} product={product or 'unresolved'} "
                f"accent={accent or 'unresolved'} variant={variant}") in evidence


def test_prepare_rejects_a_non_numeric_grace(tmp_path):
    """Falsification: accept "3m" and the grace arithmetic silently becomes 0."""
    run = bash(PREPARE, {"OUTPUT_DIR": str(tmp_path), "SCRIPT_DIR": str(ROOT / "scripts"),
                         "VARIANT": "yellowfin", "STRICT_BRANDING_GRACE": "3m"})
    assert run.returncode == 2 and "STRICT_BRANDING_GRACE" in run.stderr


OCR_VERDICT = "\n".join(function(name) for name in (
    "strict_branding_mode", "strict_branding_ocr_verdict")) + r'''
strict_offline_evidence() { printf '%s\n' "$*" >>"$OUTPUT_DIR/evidence.log"; }
strict_branding_ocr_verdict plain setup "$1"
'''


@pytest.mark.parametrize("policy", ["report", "block"])
@pytest.mark.parametrize("ocr,result", [
    ({"branding_ocr": {"result": "ok", "findings": []}}, "ok"),
    ({"branding_ocr": {"result": "fail", "findings": [
        {"file": "frame-02.png", "check": "denylist", "names": ["ubuntu"]}]}}, "fail"),
    ({"completed": True}, "absent"),
])
def test_ocr_findings_follow_the_policy(tmp_path, policy, ocr, result):
    """Falsification: fail report mode on an OCR finding, or pass block mode
    on a finding or a driver JSON without branding_ocr, and this fails."""
    path = tmp_path / "first-boot-setup.json"
    path.write_text(json.dumps(ocr))
    run = bash(OCR_VERDICT, {"OUTPUT_DIR": str(tmp_path), "SCRIPT_DIR": str(ROOT / "scripts"),
                             "TUNAOS_STRICT_BRANDING": policy}, str(path))
    assert run.returncode == (1 if policy == "block" and result != "ok" else 0), run.stderr
    line = (tmp_path / "evidence.log").read_text()
    assert line.startswith(f"installed_plain_first_boot_setup_branding_ocr={result} findings=")
    if result == "fail":
        assert "denylist:ubuntu" in line


def test_live_boots_never_consume_branding_markers():
    """Falsification: call strict_branding_collect/watch from the live install
    phase, where the live session legitimately may fail branding today."""
    live = function("run_strict_gui_install")
    assert "strict_branding" not in live
    verify = function("verify_strict_installed_boot")
    assert verify.index('strict_require_desktop_contract "$installed_log"') < verify.index(
        "strict_branding_collect \"$mode\" cold")
    assert verify.index('strict_require_desktop_contract "$warm_log"') < verify.index(
        "strict_branding_collect \"$mode\" warm")


def test_branding_policy_is_forwarded_to_the_harness():
    """Falsification: drop the variable from the workflow's sudo
    --preserve-env list or the GPU wrapper's podman -e list and block mode can
    never reach iso-e2e.sh."""
    workflow = (ROOT / ".github/workflows/iso-e2e.yml").read_text()
    assert "TUNAOS_STRICT_BRANDING: ${{ vars.TUNAOS_STRICT_BRANDING || 'report' }}" in workflow
    preserve = next(line for line in workflow.splitlines() if "sudo --preserve-env=" in line
                    and "TUNAOS_QUAL_SOURCE_DIGEST" in line)
    assert "TUNAOS_STRICT_BRANDING" in preserve and "STRICT_BRANDING_GRACE" in preserve
    gpu = (ROOT / "scripts/iso-e2e-gpu.sh").read_text()
    assert "-e TUNAOS_STRICT_BRANDING" in gpu and "-e STRICT_BRANDING_GRACE" in gpu


# ── OCR branding evaluator ───────────────────────────────────────────

SETUP_COMPLETE = ["Setup Complete", "All done!", "Yellowfin is ready to be used.",
                  "Start Using Yellowfin"]


def test_product_line_on_setup_complete_is_seen():
    """Falsification: match the product case-sensitively, or never look at the
    "is ready to be used" line, and product_seen turns false."""
    result = bo.evaluate(SETUP_COMPLETE, "Yellowfin")
    assert result["product_seen"] is True
    assert result["product_named"] == ["Yellowfin", "Yellowfin"]
    assert result["denylisted"] == [] and result["product_mismatch"] is False


def test_upstream_product_named_on_screen_is_a_mismatch_and_denylisted():
    """Falsification: skip the "Welcome to <NAME>" phrase or the denylist and
    Ubuntu's welcome window over a Grouper session passes."""
    result = bo.evaluate(["Welcome to Ubuntu", "View release notes", "Activities",
                          "Settings"], "Grouper")
    assert result["product_mismatch"] is True
    assert result["denylisted"] == ["ubuntu"]


def test_ocr_slip_of_the_product_name_still_agrees():
    """Falsification: require an exact product match and one misread glyph
    ("Yellowfn") becomes a product mismatch in block mode."""
    result = bo.evaluate(["Setup Complete", "All done!", "Yellowfn is ready to be used."],
                         "Yellowfin")
    assert result["product_mismatch"] is False and result["product_seen"] is True


def test_built_on_attribution_is_allowed():
    """Falsification: drop strip_attribution and the attribution BRANDING.md
    requires ("built on AlmaLinux Kitten 10") counts as an upstream leak."""
    lines = ["About this system", "Yellowfin 10", "Version information", "built on AlmaLinux Kitten 10"]
    assert bo.evaluate(lines, "Yellowfin")["denylisted"] == []
    # The attribution only covers its own base words, not the rest of the line.
    lines[-1] = "built on Fedora Linux 43 with the Bluefin wallpaper"
    assert bo.evaluate(lines, "Yellowfin")["denylisted"] == ["bluefin"]


def test_denylist_is_word_matched_and_case_insensitive():
    """Falsification: substring matching flags "Suspend" (no word "suse") or
    "Fedorable"; case-sensitive matching misses "RED HAT"."""
    lines = ["Suspend Restart Shutdown", "Fedorable themes", "Settings Displays", "RED  HAT support"]
    assert bo.evaluate(lines, "Bonito")["denylisted"] == ["red hat"]


def test_short_lone_tokens_and_unreliable_frames_are_not_asserted():
    """Falsification: drop the short-token rule or the reliability gate and
    tesseract's icon noise ("suse" alone) or a blank frame fails block mode."""
    assert bo.evaluate(["Settings Displays Activities", "suse"], "Bonito")["denylisted"] == []
    assert bo.evaluate(["Settings Displays Activities", "openSUSE"], "Bonito")["denylisted"] == [
        "opensuse"]
    assert bo.evaluate(["Fedora", "Q"], "Bonito")["reliable"] is False
    assert bo.evaluate(["Fedora", "Q"], "Bonito")["denylisted"] == []


def test_desktop_names_are_not_product_names():
    """Falsification: treat "Welcome to KDE Plasma" as a product line and every
    Plasma Welcome Center frame is a product mismatch."""
    result = bo.evaluate(["Welcome to KDE Plasma", "Skip", "Next", "Plasma Welcome"], "Albacore")
    assert result["product_named"] == [] and result["product_mismatch"] is False


def test_scope_covers_setup_and_post_login_frames_only():
    """Falsification: evaluate greeter or private frames, or ignore frames after
    the submitted password, and the recorded frame list changes."""
    frames = [
        {"file": "frame-00.png", "state": "greeter", "text": ["Fedora", "tunaose2e", "Password"]},
        {"state": "password", "private": True},
        {"file": "frame-02.png", "state": "setup-complete", "text": SETUP_COMPLETE},
        {"file": "frame-03.png", "state": "unknown", "text": ["Welcome to Fedora Linux 43",
                                                              "Start Tour", "Skip"]},
        {"file": "frame-04.png", "state": "login-failed", "text": ["Ubuntu login failed again"]},
    ]
    summary = bo.evaluate_frames(frames, "Yellowfin", setup_states=("setup-complete",),
                                 post_login_from=3)
    assert [(f["file"], f["kind"]) for f in summary["frames"]] == [
        ("frame-02.png", "initial-setup"), ("frame-03.png", "post-login")]
    assert summary["findings"] == [
        {"file": "frame-03.png", "check": "denylist", "names": ["fedora"]},
        {"file": "frame-03.png", "check": "product", "names": ["Fedora Linux 43"]},
    ]
    assert summary["result"] == "fail" and summary["product_named_frames"] == 2
    assert bo.verdict_line(summary) == (
        "result=fail findings=denylist:fedora,product:Fedora_Linux_43 accent=not-measured")


def test_verdict_cli_reads_the_driver_json(tmp_path):
    """Falsification: report `ok` for a driver JSON without branding_ocr and a
    driver that never ran the check would pass block mode."""
    path = tmp_path / "first-boot-setup.json"
    path.write_text(json.dumps({"completed": True}))
    script = str(ROOT / "scripts/lib/branding_ocr.py")
    out = subprocess.run([sys.executable, script, "verdict", str(path)], capture_output=True,
                         text=True, timeout=10, check=True).stdout
    assert out.strip() == "result=absent findings=- accent=not-measured"
    path.write_text(json.dumps({"branding_ocr": bo.evaluate_frames([], "Yellowfin")}))
    out = subprocess.run([sys.executable, script, "verdict", str(path)], capture_output=True,
                         text=True, timeout=10, check=True).stdout
    assert out.strip() == "result=ok findings=- accent=not-measured"


def test_product_name_comes_from_tunaos_toml():
    """Falsification: hard-code the product, or drop publish_name, and
    bonito-rawhide (published as bonito) expects the wrong PRETTY_NAME."""
    assert bo.product_name("yellowfin") == "Yellowfin"
    assert bo.product_name("bonito-rawhide") == "Bonito"
    assert bo.product_name("no-such-variant") is None


@pytest.mark.parametrize("value", ["", "report", "block"])
def test_strict_mode_accepts_only_report_and_block(value):
    """Falsification: accept an unknown value here and the driver-side record
    would carry a mode iso-e2e.sh refuses."""
    assert bo.strict_mode(value) == (value or "report")
    with pytest.raises(ValueError):
        bo.strict_mode("strict")


class FakeScreen:
    width, height = 1280, 800

    def __init__(self, lines, path=None):
        self.lines = list(lines)
        self.rows = [(line, (10 + i, 110 + 20 * i, 200 + i, 125 + 20 * i))
                     for i, line in enumerate(lines)]
        self.state = gfb.classify(self.lines)
        if path is not None:
            self.path = path

    box = gfb.Screen.box
    has = gfb.Screen.has
    start_action = gfb.Screen.start_action


GROUPER_SETUP = [
    ["Welcome", "Deutsch", "English", "Unspecified", "Next"],
    ["Welcome", "Deutsch", "English", "Unspecified", "Next"],
    ["Previous", "Ubuntu Pro", "Skip", "Enable Ubuntu Pro", "Skip for now"],
    ["About You", "Full Name", "Username", "Next"],
    ["About You", "Full Name", "Username", "Next", "tunaose2e"],
    ["Set a Password for tunaose2e", "Password", "Confirm Password", "Next"],
    ["Set a Password for tunaose2e", "Password", "Confirm Password", "Next"],
    ["Setup Complete", "Start Using Grouper"],
    ["Q Type to search"],
]


def drive_grouper_setup(tmp_path, with_path):
    frames = iter(GROUPER_SETUP)
    shown = {}

    def capture(index, label, directory=None):
        path = f"{directory or tmp_path}/frame-{index:02d}.png"
        shown[path] = FakeScreen(next(frames), path if with_path else None)
        return path

    result = gfb.drive(tmp_path, "setup", "vnc", capture, lambda *k: None, lambda t: None,
                       "tunaose2e", "harbor-sunset-4817", screen_factory=shown.__getitem__,
                       pointer=lambda *a, **k: True, sleep=lambda s: None, clock=lambda: 0.0)
    return result, json.loads((tmp_path / "first-boot-setup.json").read_text())


def test_gnome_driver_records_branding_ocr_without_failing(tmp_path, monkeypatch):
    """Falsification: remove attach_branding_ocr from the driver's finally block
    (no branding_ocr key), leave Initial Setup frames out of scope, or let a
    finding change its exit status in report mode, and this fails. The grouper
    "Ubuntu Pro" Initial Setup page is a real measured GIS page (run
    42374980522) that names the upstream product."""
    monkeypatch.setenv("TUNAOS_BRANDING_PRODUCT", "Grouper")
    monkeypatch.setenv("TUNAOS_STRICT_BRANDING", "report")
    result, evidence = drive_grouper_setup(tmp_path, with_path=False)
    assert result == 0 and evidence["completed"] is True
    ocr = evidence["branding_ocr"]
    assert ocr["product"] == "Grouper" and ocr["mode"] == "report" and ocr["result"] == "fail"
    assert ocr["findings"] == [{"file": "frame-02.png", "check": "denylist", "names": ["ubuntu"]}]
    complete = next(f for f in ocr["frames"] if f["state"] == "setup-complete")
    assert complete["product_seen"] is True and complete["product_named"] == ["Grouper"]
    assert all(f["file"] for f in ocr["frames"])  # private frames are never evaluated
    # No capture path to read pixels from: the accent is recorded, not guessed.
    assert ocr["accent"]["status"] == "not-measured" and ocr["accent"]["ok"] is None


def test_gnome_driver_samples_the_pills_it_clicks(tmp_path, monkeypatch):
    """Falsification: stop sampling Next / "Start Using" at click time, sample
    the private password frame, or let a slate pill pass against grouper's
    Yaru orange, and this fails (tunaOS#4408: GIS drew slate/sage pills)."""
    monkeypatch.setenv("TUNAOS_BRANDING_PRODUCT", "Grouper")
    monkeypatch.setenv("TUNAOS_BRANDING_ACCENT", "#e95420")
    sampled = []

    def fake_pill(path, box, width, height):
        sampled.append(Path(path).parent == tmp_path)
        return (111, 131, 150)

    monkeypatch.setattr(gfb, "pill_rgb", fake_pill)
    result, evidence = drive_grouper_setup(tmp_path, with_path=True)
    assert result == 0
    labels = [sample["label"] for sample in evidence["accent_samples"]]
    # Language and About You Next clicks, then the Setup Complete pill. The
    # password page's Next is clicked while its frame is private: never sampled.
    assert labels == ["Next", "Next", "Start Using Grouper"]
    assert all(sampled)  # every sampled frame is a public capture
    accent = evidence["branding_ocr"]["accent"]
    assert (accent["status"], accent["observed_rgb"], accent["ok"], accent["rejected"]) == (
        "measured", [111, 131, 150], False, "slate")
    assert {"file": None, "check": "accent", "names": ["#6f8396"]} in evidence["branding_ocr"]["findings"]
    assert bo.verdict_line(evidence["branding_ocr"]).endswith("accent=fail")


def test_dominant_fill_ignores_label_strokes():
    """Falsification: average the whole crop and white label strokes pull an
    orange pill out of tolerance; pick the brightest colour and the label wins."""
    fill, label = bytes((233, 84, 32)), bytes((255, 255, 255))
    raw = fill * 70 + label * 25 + bytes((240, 160, 120)) * 5
    assert bo.dominant_rgb(raw) == (233, 84, 32)
    with pytest.raises(ValueError):
        bo.dominant_rgb(b"\x00\x01")


@pytest.mark.parametrize("samples,expected,state", [
    ([], "#e95420", ("not-measured", None)),
    ([{"label": "Next", "rgb": [236, 90, 40]}], "#e95420", ("measured", True)),
    ([{"label": "Next", "rgb": [101, 123, 105]}], "#3a944a", ("measured", False)),
    ([{"label": "Next", "rgb": [101, 123, 105]}], None, ("measured", False)),
    ([{"label": "Next", "rgb": [53, 132, 228]}], None, ("measured", None)),
    # A disabled (grey) Next does not outvote the always-enabled Start Using pill.
    ([{"label": "Next", "rgb": [250, 250, 250]},
      {"label": "Start Using Bonito", "rgb": [55, 130, 225]}], "#3584e4", ("measured", True)),
])
def test_accent_tolerance_and_rejected_fills(samples, expected, state):
    """Falsification: widen the tolerance past the gap between accents, drop
    the slate/sage rejection, or call an unsampled run a pass, and this fails."""
    record = bo.evaluate_accent(samples, expected)
    assert (record["status"], record["ok"]) == state
