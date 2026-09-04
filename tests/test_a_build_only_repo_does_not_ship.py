"""A repo that only exists during the build must not ship in the image.

install-desktop.sh writes /etc/yum.repos.d/<name>.repo for every repo the
manifest's OS section declares. For an https tier that is fine and sometimes
deliberate -- 10-base-packages.sh writes tunaos-hummingbird.repo the same way,
and a booted host can reach it.

For a file:// repo it is not. Those baseurls are bind mounts of digest-pinned
OCI images that Containerfile.el10 provides for the duration of ONE RUN
(/run/utah-packages for hummingbird:gnome, /run/gnome50-el10-packages for
el10). The .repo file is not scoped to that RUN: 99-cleanup.sh runs in
base-no-de, BEFORE the desktop stages fork from it, so nothing removed it and
it shipped. And the write loop emits skip_if_unavailable=False, so the result
is not a harmless stale entry -- it fails every dnf transaction the user runs
on the booted host. hummingbird has shipped utah-packages.repo that way since
8a31ace9.

These tests run the shipped loops themselves, against a fake yq, rather than a
paraphrase of them.
"""
from __future__ import annotations

import stat
import subprocess
import textwrap
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "build_scripts" / "desktop" / "install-desktop.sh"

MOUNTED_REPO = "gnome50-el10-packages"
MOUNTED_URL = f"file:///run/{MOUNTED_REPO}"


FAKE_YQ = """#!/usr/bin/env python3
import re, sys, yaml
expr, path = sys.argv[2], sys.argv[3]
doc = yaml.safe_load(open(path))
m = re.fullmatch(r"\\.packages\\.(\\w+) \\| type", expr)
if m:
    v = doc["packages"].get(m.group(1))
    print("!!map" if isinstance(v, dict) else "!!seq" if isinstance(v, list) else "!!null")
    sys.exit(0)
m = re.fullmatch(r"\\.packages\\.(\\w+)\\.repos \\| length // 0", expr)
if m:
    print(len(doc["packages"][m.group(1)].get("repos") or []))
    sys.exit(0)
m = re.fullmatch(r"\\.packages\\.(\\w+)\\.repos\\[(\\d+)\\]\\.(\\w+)(?: // (.*))?", expr)
if m:
    os_, i, field, default = m.groups()
    v = doc["packages"][os_]["repos"][int(i)].get(field)
    if v is None:
        print("" if default == '\"\"' else (default if default is not None else "null"))
    else:
        print(str(v).lower() if isinstance(v, bool) else v)
    sys.exit(0)
sys.exit(1)
"""


def _block(start_marker: str) -> str:
    """The literal loop out of install-desktop.sh, so the test runs the shipped
    code rather than a paraphrase of it."""
    src = SCRIPT.read_text()
    start = src.index(start_marker)
    end = src.index("\tdone\n", start) + len("\tdone\n")
    return textwrap.dedent(src[start:end])


def test_a_file_repo_is_removed_after_the_install_and_an_https_one_is_not(tmp_path):
    """Containerfile.el10 mounts the repository for exactly one RUN, but the
    .repo file the write loop leaves behind is not scoped to that RUN --
    99-cleanup.sh runs in base-no-de, before the desktop stages fork from it.
    A shipped repo whose baseurl is a path that no longer exists, written with
    skip_if_unavailable=False, fails every dnf the user runs on the booted
    host. It has to be retired at the end of the section."""
    manifest = {"packages": {"el10": {"repos": [
        {"name": MOUNTED_REPO, "baseurl": MOUNTED_URL, "priority": 1, "unsigned": True},
        {"name": "keep-me", "baseurl": "https://repo.tunaos.org/xfce/10-stream-x86_64/"},
    ]}}}
    (tmp_path / "manifest.yaml").write_text(yaml.safe_dump(manifest))
    yq = tmp_path / "yq"
    yq.write_text(FAKE_YQ)
    yq.chmod(yq.stat().st_mode | stat.S_IEXEC)
    reposd = tmp_path / "yum.repos.d"
    reposd.mkdir()

    body = (_block("\t_TD_REPO_COUNT=0\n") + "\n"
            + _block("\t# ── Retire the build-only repos"))
    harness = tmp_path / "harness.sh"
    harness.write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\n"
        f'YQ="{yq}"\n_TD_OS=el10\n_TD_MANIFEST="{tmp_path / "manifest.yaml"}"\n'
        + body.replace("/etc/yum.repos.d", str(reposd))
    )
    proc = subprocess.run(["bash", str(harness)], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr

    assert not (reposd / f"{MOUNTED_REPO}.repo").exists(), (
        f"{MOUNTED_REPO}.repo survives into the image; its baseurl {MOUNTED_URL} is a bind "
        "mount that does not exist on a booted host"
    )
    kept = (reposd / "keep-me.repo").read_text()
    assert "https://repo.tunaos.org" in kept, (
        "an https tier is reachable from a booted host; only file:// repos are "
        "build-only"
    )


def test_the_removal_loop_runs_after_the_packages_are_installed():
    src = SCRIPT.read_text()
    assert src.index("\t# Install packages\n") < src.index(
        "\t# ── Retire the build-only repos"
    ), "the repo cannot be retired before the transaction that needs it"
    assert src.index("\t# ── Retire the build-only repos") < src.index(
        "\nfi # end DNF path (el10/fedora)"
    )
