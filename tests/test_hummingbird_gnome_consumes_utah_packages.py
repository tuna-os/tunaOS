"""hummingbird:gnome takes GNOME from projectbluefin/utah-packages, by digest.

tuna-os/tunaos-packages#629 and its docs/HUMMINGBIRD-TARGET.md: Bluefin
builds GNOME 51 for Hummingbird in Hummingbird's own root and publishes it as
an OCI image carrying a createrepo_c repository (`/repository`), cosign-signed,
consumed with `COPY --from` by digest. Building a second GNOME 51 for the same
base in tunaos-packages was the part of the plan not paying back, so this
repository consumes utah's instead, the way it already consumes
projectbluefin/common and ublue-os/brew.

What these tests hold, and why each is a test rather than a comment:

- the pin is in image-versions.yaml with a digest, so Renovate's existing
  image-versions block tracks it and check-base-image-pins-style GC does not
  surprise a nightly;
- the build plumbing carries it end to end: resolve-image.sh role, build arg,
  Containerfile stage, and a bind-mount on the gnome stage only (never a
  COPY: the repository is ~500 MB and must not land in any image);
- gnome.yaml's hummingbird section declares the file:// repo at a priority
  that beats the tunaos-hummingbird prefix, marked `unsigned: true`;
- install-desktop.sh's repo loop, run for real against a fake yq, writes
  gpgcheck=0 for that repo and gpgcheck=1 + gpgkey for every other one --
  and refuses `unsigned: true` on anything that is not file://, because a
  network repo has no digest standing in for a signature (tunaOS#1655).
"""
from __future__ import annotations

import os
import re
import stat
import subprocess
import textwrap
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parents[1]
IMAGE_VERSIONS = ROOT / "image-versions.yaml"
REGISTRY_MAP = ROOT / "registry-map.yaml"
RESOLVE = ROOT / "scripts" / "resolve-image.sh"
INNER = ROOT / "scripts" / "build-image-inner.sh"
CONTAINERFILE = ROOT / "Containerfile.el10"
GNOME = ROOT / "manifests" / "desktops" / "gnome.yaml"
INSTALL = ROOT / "build_scripts" / "desktop" / "install-desktop.sh"

MOUNT = "/run/utah-packages"


def pinned() -> dict:
    images = yaml.safe_load(IMAGE_VERSIONS.read_text())["images"]
    by_name = {i["name"]: i for i in images}
    assert "utah-packages" in by_name, "image-versions.yaml has no utah-packages pin"
    return by_name["utah-packages"]


# ── the pin ────────────────────────────────────────────────────────────────


def test_the_pin_is_a_digest_on_the_bluefin_image():
    pin = pinned()
    assert pin["image"] == "ghcr.io/projectbluefin/utah-packages"
    assert re.fullmatch(r"sha256:[0-9a-f]{64}", pin["digest"]), pin
    assert pin.get("tag") == "latest", (
        "Renovate's image-versions block matches `name/image/tag/digest` in "
        "that order; without a tag the digest is never bumped"
    )


def test_registry_map_names_it():
    images = yaml.safe_load(REGISTRY_MAP.read_text())["images"]
    assert images["utah-packages"]["path"] == "projectbluefin/utah-packages"
    assert images["utah-packages"]["registry"] == "ghcr"


# ── the plumbing ───────────────────────────────────────────────────────────


def test_resolve_image_has_a_role_for_it(tmp_path):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    yq = bindir / "yq"
    yq.write_text(
        "#!/usr/bin/env bash\n"
        "# the role queries `.images[] | select(.name == \"utah-packages\") | .digest`\n"
        'case "$*" in *utah-packages*) echo sha256:%s ;; *) echo unexpected-query >&2; exit 1 ;; esac\n'
        % ("ab" * 32)
    )
    yq.chmod(yq.stat().st_mode | stat.S_IEXEC)
    out = subprocess.run(
        ["bash", str(RESOLVE), "hummingbird", "utah-packages"],
        capture_output=True, text=True, cwd=ROOT,
        env={**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}", "YQ": str(yq)},
    )
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "ghcr.io/projectbluefin/utah-packages@sha256:" + "ab" * 32


def test_the_build_engine_passes_the_ref_as_a_build_arg():
    text = INNER.read_text()
    assert 'select(.name == "utah-packages") | .digest' in text
    assert '"UTAH_PACKAGES_IMAGE_REF=${utah_packages_ref}"' in text


def test_the_containerfile_declares_the_stage_and_mounts_it_on_gnome_only():
    text = CONTAINERFILE.read_text()
    assert 'ARG UTAH_PACKAGES_IMAGE_REF="ghcr.io/projectbluefin/utah-packages:unpinned-must-override"' in text, (
        "the default must be a tag that cannot resolve, like COMMON/BREW, so a "
        "bare `podman build` fails loudly instead of pulling an unpinned repo"
    )
    assert "FROM ${UTAH_PACKAGES_IMAGE_REF} AS utah-packages" in text
    mount = f"--mount=type=bind,from=utah-packages,source=/repository,target={MOUNT}"
    stages = re.split(r"^FROM ", text, flags=re.M)
    mounted = [s.split("\n", 1)[0] for s in stages if mount in s]
    assert mounted == ["base-no-de AS gnome"], mounted
    assert "COPY --from=utah-packages" not in text, (
        "the repository is ~500 MB; it is bind-mounted for one RUN, never copied "
        "into an image"
    )


# ── the manifest ───────────────────────────────────────────────────────────


def hummingbird_repos() -> list[dict]:
    return yaml.safe_load(GNOME.read_text())["packages"]["hummingbird"]["repos"]


def test_gnome_on_hummingbird_declares_the_mounted_repo_unsigned():
    repos = {r["name"]: r for r in hummingbird_repos()}
    utah = repos["utah-packages"]
    assert utah["baseurl"] == f"file://{MOUNT}"
    assert utah.get("unsigned") is True
    assert utah["priority"] < repos["tunaos-hummingbird"]["priority"], (
        "utah must win the by-name priority filter over the tunaos-hummingbird "
        "prefix, or the GNOME stack resolves from two builds at once"
    )


def test_the_prefix_repo_is_still_first_and_signed():
    """tests/bats/test_hummingbird_desktop_wiring.bats reads repos[0]."""
    first = hummingbird_repos()[0]
    assert first["name"] == "tunaos-hummingbird"
    assert not first.get("unsigned")


# ── the loop, run for real ─────────────────────────────────────────────────


FAKE_YQ = textwrap.dedent(
    r'''
    #!/usr/bin/env python3
    """Enough of `yq -r <expr> <file>` for install-desktop.sh's repo loop."""
    import re, sys
    import yaml
    expr, path = sys.argv[2], sys.argv[3]
    doc = yaml.safe_load(open(path))
    m = re.fullmatch(r"\.packages\.(\w+) \| type", expr)
    if m:
        v = doc["packages"].get(m.group(1))
        print("!!map" if isinstance(v, dict) else "!!seq" if isinstance(v, list) else "!!null")
        sys.exit(0)
    m = re.fullmatch(r"\.packages\.(\w+)\.repos \| length // 0", expr)
    if m:
        print(len(doc["packages"][m.group(1)].get("repos") or []))
        sys.exit(0)
    m = re.fullmatch(r"\.packages\.(\w+)\.repos\[(\d+)\]\.(\w+)(?: // (.*))?", expr)
    if m:
        os_, i, field, default = m.groups()
        v = doc["packages"][os_]["repos"][int(i)].get(field)
        if v is None:
            print("" if default == '""' else (default if default is not None else "null"))
        else:
            print(str(v).lower() if isinstance(v, bool) else v)
        sys.exit(0)
    print(f"fake yq: unsupported expression {expr!r}", file=sys.stderr)
    sys.exit(1)
    '''
).lstrip()


def repo_loop() -> str:
    text = INSTALL.read_text()
    start = text.index("\t_TD_REPO_COUNT=0\n")
    end = text.index("\tdone\n", start) + len("\tdone\n")
    block = text[start:end]
    assert "unsigned" in block, "repo loop no longer reads `unsigned`"
    return textwrap.dedent(block)


def run_loop(tmp_path: Path, manifest: dict) -> subprocess.CompletedProcess:
    (tmp_path / "manifest.yaml").write_text(yaml.safe_dump(manifest))
    yq = tmp_path / "yq"
    yq.write_text(FAKE_YQ)
    yq.chmod(yq.stat().st_mode | stat.S_IEXEC)
    reposd = tmp_path / "yum.repos.d"
    reposd.mkdir()
    harness = tmp_path / "harness.sh"
    harness.write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\n"
        f'YQ="{yq}"\n_TD_OS=hummingbird\n_TD_MANIFEST="{tmp_path / "manifest.yaml"}"\n'
        # the loop writes to /etc/yum.repos.d; redirect it
        + repo_loop().replace("/etc/yum.repos.d", str(reposd))
    )
    return subprocess.run(["bash", str(harness)], capture_output=True, text=True)


def test_the_loop_writes_gpgcheck_0_only_for_the_unsigned_file_repo(tmp_path):
    manifest = {"packages": {"hummingbird": {
        "repos": [
            {"name": "tunaos-hummingbird",
             "baseurl": "https://repo.tunaos.org/hummingbird/20251124-$basearch/",
             "priority": 5},
            {"name": "utah-packages", "baseurl": f"file://{MOUNT}",
             "priority": 4, "unsigned": True},
        ],
        "packages": ["gnome-shell"],
    }}}
    proc = run_loop(tmp_path, manifest)
    assert proc.returncode == 0, proc.stderr
    signed = (tmp_path / "yum.repos.d" / "tunaos-hummingbird.repo").read_text()
    unsigned = (tmp_path / "yum.repos.d" / "utah-packages.repo").read_text()
    assert "gpgcheck=1\n" in signed and "gpgkey=https://repo.tunaos.org/public.gpg" in signed
    assert "priority=5" in signed
    assert "gpgcheck=0\n" in unsigned and "gpgkey=" not in unsigned
    assert f"baseurl=file://{MOUNT}" in unsigned and "priority=4" in unsigned
    # the properties both share
    for text in (signed, unsigned):
        assert "repo_gpgcheck=0" in text and "skip_if_unavailable=False" in text


def test_unsigned_is_refused_for_a_network_repo(tmp_path):
    """The whole point of tunaOS#1655: nothing fetched over the network at
    build time skips signature checks. `unsigned` is for digest-pinned
    bind-mounted content and nothing else."""
    manifest = {"packages": {"hummingbird": {
        "repos": [{"name": "sneaky", "baseurl": "https://example.invalid/x/",
                   "unsigned": True}],
        "packages": [],
    }}}
    proc = run_loop(tmp_path, manifest)
    assert proc.returncode != 0
    assert "unsigned: true" in proc.stderr and "file://" in proc.stderr
    assert not (tmp_path / "yum.repos.d" / "sneaky.repo").exists()


def test_a_repo_without_the_key_is_signed_by_default(tmp_path):
    manifest = {"packages": {"hummingbird": {
        "repos": [{"name": "plain", "baseurl": "https://repo.tunaos.org/x/"}],
        "packages": [],
    }}}
    proc = run_loop(tmp_path, manifest)
    assert proc.returncode == 0, proc.stderr
    text = (tmp_path / "yum.repos.d" / "plain.repo").read_text()
    assert "gpgcheck=1\n" in text and "\ngpgcheck=0" not in text  # repo_gpgcheck=0 is fine
