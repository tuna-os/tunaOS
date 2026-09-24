"""tunaOS#2485: rolling EL10 images shipped with no working system bus.

skipjack:gnome failed on libselinux 3.11-1.el10 in run 35185567440 and
passed its Gate and desktop contract when only libselinux changed to 3.10 in
run 35191766126. The same 3.11 failure was measured on yellowfin.

Falsification: structural — reverting the declared 3.10 ceiling or either
rolling-variant scope makes this test fail as the pre-fix tree did.
Behavioural for the build block: it runs against stub dnf and rpm with
python3-libselinux not installed. The block as first merged exits 1 there
and locks bare names; both tests below go red on it (checked).
"""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
VERSIONS = ROOT / "image-versions.yaml"
BASE_PACKAGES = ROOT / "build_scripts" / "10-base-packages.sh"


def test_both_rolling_el10_bases_apply_the_declared_ceiling_strictly():
    versions = yaml.safe_load(VERSIONS.read_text(encoding="utf-8"))
    pin = versions["packages"]["el10_rolling_libselinux"]
    script = BASE_PACKAGES.read_text(encoding="utf-8")

    assert pin == "3.10-2.el10"
    assert '"$IMAGE_NAME" == "yellowfin"' in script
    assert '"$IMAGE_NAME" == "skipjack"' in script

    block = script.split("# tunaOS#2485:", 1)[1].split(
        "if [[ $IS_HUMMINGBIRD == true ]]", 1
    )[0]
    assert "dnf -y downgrade" in block
    assert "dnf versionlock add" in block
    assert "libselinux libselinux-utils python3-libselinux" in block
    assert "rpm -q --queryformat" in block
    assert "|| true" not in block


# The block as shipped in #2670 failed every yellowfin and skipjack build (run
# 36054709367): python3-libselinux is not installed on either base, dnf skips
# it in the downgrade, and the strict `rpm -q` check then exited 1 under
# `set -e`. It also locked the bare name, which for an uninstalled package
# locks every available version. These run the real block against stubs.
import os
import subprocess
import textwrap


def _run_block(tmp_path, installed):
    script = BASE_PACKAGES.read_text(encoding="utf-8")
    block = script.split("# tunaOS#2485:", 1)[1].split(
        "if [[ $IS_HUMMINGBIRD == true ]]", 1
    )[0]
    bindir = tmp_path / "bin"
    bindir.mkdir()
    log = tmp_path / "calls.log"
    (bindir / "dnf").write_text(f'#!/bin/bash\necho "dnf $*" >> "{log}"\n')
    installed_list = " ".join(installed)
    (bindir / "rpm").write_text(textwrap.dedent(f"""\
        #!/bin/bash
        pkg="${{@: -1}}"
        for p in {installed_list}; do
          if [[ "$p" == "$pkg" ]]; then
            [[ "$1" == "--quiet" || "$2" == "--quiet" ]] || echo -n "3.10-2.el10"
            exit 0
          fi
        done
        [[ "$*" == *--quiet* ]] || echo "package $pkg is not installed"
        exit 1
        """))
    for f in ("dnf", "rpm"):
        os.chmod(bindir / f, 0o755)
    ctx = tmp_path / "run/context"
    ctx.mkdir(parents=True)
    (ctx / "image-versions.yaml").write_text(
        (ROOT / "image-versions.yaml").read_text(encoding="utf-8")
    )
    body = block.replace("/run/context/", f"{ctx}/")
    proc = subprocess.run(
        ["bash", "-c", "set -euo pipefail\nIMAGE_NAME=yellowfin\n# " + body],
        capture_output=True,
        text=True,
        env={**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}"},
    )
    return proc, log.read_text() if log.exists() else ""


def test_an_uninstalled_python3_libselinux_does_not_fail_the_build(tmp_path):
    proc, calls = _run_block(tmp_path, ["libselinux", "libselinux-utils"])
    assert proc.returncode == 0, proc.stderr
    assert "python3-libselinux is not installed" in proc.stdout


def test_the_versionlock_pins_exact_nevrs_not_bare_names(tmp_path):
    _, calls = _run_block(tmp_path, ["libselinux", "libselinux-utils"])
    lock = [l for l in calls.splitlines() if l.startswith("dnf versionlock add")]
    assert lock == [
        "dnf versionlock add libselinux-3.10-2.el10 libselinux-utils-3.10-2.el10 "
        "python3-libselinux-3.10-2.el10"
    ]


def test_a_missing_libselinux_still_fails(tmp_path):
    proc, _ = _run_block(tmp_path, ["libselinux-utils"])
    assert proc.returncode != 0
