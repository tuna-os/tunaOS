"""The Rawhide rpmdb probe must not run on images that are not Fedora.

`rawhide_rpmdb_probe` describes itself as "a no-op off Rawhide". It was not.
`detect_fedora_ver` maps an UNEXPANDED `%fedora` to "rawhide", and `%fedora`
is undefined on every non-Fedora dnf image, so "this is not a Fedora at all"
was read as "this is Rawhide". Measured on skipjack
(quay.io/centos-bootc/centos-bootc:stream10, IS_CENTOS=true, IS_FEDORA=false)
in run 32534198668, where the Rawhide-only copy-up ran and then aborted the
build on a lossy salvage.

The fallback itself is fine where it was designed to be used:
`10-base-packages.sh` only reaches it inside an `elif [[ $IS_FEDORA == true ]]`
branch. What was missing is that this function consumed it with no such guard.

This is an EXPERIMENT for tunaOS#1823 -- see the comment in lib.sh. These
tests pin the shape of the change, not its outcome.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIB = ROOT / "build_scripts" / "lib.sh"


def probe_body() -> str:
    text = LIB.read_text(encoding="utf-8")
    start = text.index("rawhide_rpmdb_probe() {")
    return text[start:text.index("\n}\n", start)]


def run_probe(env: dict[str, str], fedora_macro: str) -> int:
    """Run the two guard lines with a stubbed `rpm`, returning the exit code.

    0 means the function returned early (probe skipped).
    """
    lib = LIB.read_text(encoding="utf-8")
    detect = re.search(r"^detect_fedora_ver\(\) \{.*?^\}", lib, re.S | re.M).group(0)
    guards = "\n".join(
        ln for ln in probe_body().splitlines()
        if ln.strip().startswith("[[") and "return 0" in ln
    )
    script = f"""
    rpm() {{ [[ "$1" == "-E" && "$2" == "%fedora" ]] && {{ echo '{fedora_macro}'; return 0; }}; return 1; }}
    {detect}
    probe() {{
    {guards}
        echo RAN
    }}
    probe
    """
    r = subprocess.run(["bash", "-c", script], capture_output=True, text=True,
                       env={"PATH": "/usr/bin:/bin", **env})
    return 0 if "RAN" not in r.stdout else 1


def test_the_is_fedora_guard_is_present():
    assert '[[ "${IS_FEDORA:-false}" == true ]] || return 0' in probe_body()


def test_it_guards_before_consulting_detect_fedora_ver():
    """detect_fedora_ver is the thing that misreports; checking it first and
    IS_FEDORA second would leave the misfire in place for anything that
    short-circuits on the first guard."""
    # CODE only. The comment explaining this change names detect_fedora_ver
    # repeatedly and sits above the guards, so scanning prose would compare
    # the explanation instead of the logic.
    code = "\n".join(
        ln for ln in probe_body().splitlines() if not ln.strip().startswith("#")
    )
    assert code.index("IS_FEDORA") < code.index("detect_fedora_ver")


def test_centos_skips_the_probe():
    """The measured case: %fedora unexpanded, IS_FEDORA false."""
    assert run_probe({"IS_FEDORA": "false"}, "%fedora") == 0


def test_centos_skips_even_though_detect_still_says_rawhide():
    """Pins the actual mechanism rather than the outcome: detect_fedora_ver is
    deliberately left alone, because 10-base-packages.sh relies on its
    fallback inside an IS_FEDORA branch."""
    lib = LIB.read_text(encoding="utf-8")
    detect = re.search(r"^detect_fedora_ver\(\) \{.*?^\}", lib, re.S | re.M).group(0)
    r = subprocess.run(
        ["bash", "-c", f"rpm() {{ echo '%fedora'; }}\n{detect}\ndetect_fedora_ver"],
        capture_output=True, text=True, env={"PATH": "/usr/bin:/bin"})
    assert r.stdout.strip() == "rawhide"


def test_a_real_rawhide_image_still_runs_the_probe():
    """The whole point of the probe must survive the gate."""
    assert run_probe({"IS_FEDORA": "true"}, "%fedora") == 1


def test_a_pinned_fedora_release_still_skips():
    """Numeric %fedora is not Rawhide, so the second guard still applies."""
    assert run_probe({"IS_FEDORA": "true"}, "44") == 0


def test_the_experiment_is_labelled_with_its_issue():
    assert "tunaOS#1823" in probe_body()
