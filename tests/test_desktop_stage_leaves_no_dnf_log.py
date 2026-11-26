"""A desktop image ships no dnf log in /var/log.

99-cleanup.sh removed /var/log/dnf5.log in the base stage, but every desktop
stage of Containerfile.el10 runs dnf again in install-desktop.sh (and niri in
install-zirconium.sh before it). bonito:niri d11611b66c66 shipped
/var/log/dnf5.log, .1 and .2, bonito:kde 9b0441b1 shipped dnf5.log to .4
(layer file lists, 2026-11-26). dnf5.log holds Copr's presigned S3 URLs; the
installer medium's secret check stopped on them.
"""
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIB = ROOT / "build_scripts" / "lib.sh"
DESKTOP = ROOT / "build_scripts" / "desktop" / "install-desktop.sh"
CLEANUP = ROOT / "build_scripts" / "99-cleanup.sh"
LOGS = ["dnf5.log", "dnf5.log.1", "dnf5.log.4", "dnf.log", "dnf.rpm.log",
        "dnf.librepo.log", "hawkey.log"]


def _function(tmp_path):
    body = re.search(r"^dnf_log_clean\(\) \{\n.*?^\}\n", LIB.read_text(), re.M | re.S)
    assert body, "lib.sh defines dnf_log_clean"
    return body.group(0).replace("/var/log/", f"{tmp_path}/")


def _run(tmp_path, pkg_mgr):
    for name in LOGS + ["keep.log"]:
        (tmp_path / name).write_text("x")
    subprocess.run(["bash", "-euc", _function(tmp_path) + "dnf_log_clean"],
                   check=True, env={"PATH": "/usr/bin:/bin", "PKG_MGR": pkg_mgr})
    return sorted(p.name for p in tmp_path.iterdir())


def test_the_dnf_logs_go_and_other_logs_stay(tmp_path):
    assert _run(tmp_path, "dnf") == ["keep.log"]


def test_other_package_managers_keep_their_logs(tmp_path):
    assert len(_run(tmp_path, "apt")) == len(LOGS) + 1


def test_the_desktop_stage_cleans_after_its_last_package_step():
    """Falsification: without the call at the end, the desktop stage's dnf
    log reaches the image."""
    text = DESKTOP.read_text()
    calls = [m.start() for m in re.finditer(r"^dnf_log_clean$", text, re.M)]
    assert calls, "install-desktop.sh runs dnf_log_clean"
    last_package_step = max(text.rfind("emit_packages_manifest\n"),
                            text.rfind("install-countme.sh"))
    assert calls[-1] > last_package_step


def test_the_base_stage_uses_the_same_function():
    assert re.search(r"^dnf_log_clean$", CLEANUP.read_text(), re.M)
    assert "rm -f /var/log/dnf5.log" not in CLEANUP.read_text()
