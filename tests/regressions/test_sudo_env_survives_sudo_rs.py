"""`sudo -E` is ignored by sudo-rs (Ubuntu 26.04, ubuntu-latest). Call sites must
name their environment with `--preserve-env=LIST` instead (#4890)."""

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "scripts/lib/sudo-env.sh"
# reusable-build-artifacts.yml is handled by its own fix (#4888).
SKIP = {".github/workflows/reusable-build-artifacts.yml"}


def test_no_executable_sudo_dash_E():
    pat = re.compile(r"^\s*sudo\s+(-E\b|--preserve-env\s)")
    bad = []
    files = [ROOT / "Justfile", *(ROOT / "just").glob("*.just"), *(ROOT / ".github/workflows").glob("*.yml")]
    for f in files:
        if str(f.relative_to(ROOT)) in SKIP:
            continue
        for n, line in enumerate(f.read_text().splitlines(), 1):
            if pat.match(line):
                bad.append(f"{f.relative_to(ROOT)}:{n}")
    assert not bad, bad


def test_helper_lists_exported_names_only():
    out = subprocess.run(
        ["bash", "-c", f". {HELPER}; export FOO_BAR=1; unset NOT_EXPORTED; tunaos_sudo_preserve_env"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert out.startswith("--preserve-env=")
    names = out.split("=", 1)[1].split(",")
    assert "FOO_BAR" in names and "PATH" in names
    assert all(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", n) for n in names)
