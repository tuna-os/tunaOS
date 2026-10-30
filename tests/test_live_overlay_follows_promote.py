"""A Promote that moves a cell's base must rebind that cell's live overlay.

live-overlay:<variant>-<flavor> records the base platform manifest it was
customized from (org.tunaos.live-overlay.base-digest), and tacklebox refuses an
overlay bound to any other base (fail-closed since #425). live-overlay.yml only
ran by hand: skipjack:gnome was promoted within two hours of a manual publish of
its overlay, and browser builds of it were refused from then on.

Promote now dispatches live-overlay.yml for its own cell with the index digest
it wrote, and the overlay run binds only bases its tag still names. These tests
run the real scripts and workflow steps against stub gh/skopeo/podman.
"""

from __future__ import annotations

import json
import os
import subprocess
import textwrap
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parents[1]
REUSABLE = ROOT / ".github/workflows/reusable-build-image.yml"
LIVE_OVERLAY = ROOT / ".github/workflows/live-overlay.yml"

PROMOTED_INDEX = "sha256:" + "1" * 64
AMD64 = "sha256:" + "a" * 64
AMD64_V2 = "sha256:" + "b" * 64
ARM64 = "sha256:" + "c" * 64
NEWER_AMD64 = "sha256:" + "d" * 64

CONFIG = {
    "config": {"global_platforms": ["linux/amd64", "linux/arm64"]},
    "variants": [
        {
            "id": "skipjack",
            "platforms": ["linux/amd64", "linux/amd64/v2", "linux/arm64"],
            "flavors": [
                {"id": "base", "build_image": True},
                {"id": "gnome", "build_image": True},
                {"id": "kde", "build_image": True, "platforms": ["linux/amd64"]},
                {"id": "tuna", "build_image": True},
                {"id": "gnome-asahi", "build_image": True},
                {"id": "gnome-nvidia-hwe", "build_image": False},
            ],
        },
        {
            "id": "bonito-rawhide",
            "publish_name": "bonito",
            "tag_suffix": "rawhide",
            "platforms": ["linux/amd64"],
            "flavors": [{"id": "gnome", "build_image": True}],
        },
    ],
}


def index(*entries: tuple[str, str]) -> str:
    """A raw OCI index as podman writes Promote's: architecture may carry /v2."""
    return json.dumps({
        "schemaVersion": 2,
        "mediaType": "application/vnd.oci.image.index.v1+json",
        "manifests": [
            {"mediaType": "application/vnd.oci.image.manifest.v1+json",
             "digest": digest, "size": 1,
             "platform": {"os": "linux", "architecture": arch}}
            for arch, digest in entries
        ],
    })


@pytest.fixture
def config(tmp_path: Path) -> Path:
    path = tmp_path / "build-config.yml"
    path.write_text(yaml.safe_dump(CONFIG))
    return path


def stub(bin_dir: Path, name: str, body: str) -> None:
    bin_dir.mkdir(exist_ok=True)
    path = bin_dir / name
    path.write_text("#!/usr/bin/env bash\n" + textwrap.dedent(body))
    path.chmod(0o755)


# ── which cells have an overlay to rebind ────────────────────────────────────

def select(config: Path, variant: str, flavor: str) -> list[dict]:
    out = subprocess.run(
        ["bash", str(ROOT / "scripts/live-overlay-matrix.sh"), variant, flavor],
        env=os.environ | {"TUNAOS_BUILD_CONFIG": str(config)},
        text=True, capture_output=True, check=True,
    ).stdout
    return json.loads(out)["include"]


def test_a_desktop_cell_selects_one_row_per_real_arch(config):
    rows = select(config, "skipjack", "gnome")
    assert [(r["platform"], r["runner"]) for r in rows] == [
        ("linux/amd64", "ubuntu-latest"),
        ("linux/arm64", "ubuntu-24.04-arm"),
    ]
    assert {(r["variant"], r["flavor"]) for r in rows} == {("skipjack", "gnome")}


@pytest.mark.parametrize("flavor", ["base", "tuna", "gnome-asahi", "gnome-nvidia-hwe"])
def test_cells_without_a_live_overlay_select_nothing(config, flavor):
    assert select(config, "skipjack", flavor) == []


def test_all_selects_every_desktop_cell(config):
    cells = {(r["variant"], r["flavor"]) for r in select(config, "all", "all")}
    assert cells == {("skipjack", "gnome"), ("skipjack", "kde"), ("bonito-rawhide", "gnome")}


# ── when Promote dispatches ──────────────────────────────────────────────────

PROMOTE = {
    "EVENT_NAME": "schedule",
    "REPOSITORY": "tuna-os/tunaOS",
    "REF": "refs/heads/main",
    "PROMOTED": "true",
    "BASE_INDEX_DIGEST": PROMOTED_INDEX,
    "VARIANT": "skipjack",
    "FLAVOR": "gnome",
    "IMAGE_NAME": "skipjack",
    "IMAGE_TAG": "gnome",
}


def dispatch(tmp_path: Path, config: Path, state: str = "active", **overrides):
    calls = tmp_path / "gh-calls"
    stub(tmp_path / "bin", "gh", f"""\
        printf '%s\\n' "$*" >> {calls}
        if [[ "$1" == api ]]; then echo {state}; fi
    """)
    env = os.environ | PROMOTE | overrides | {
        "TUNAOS_BUILD_CONFIG": str(config),
        "GH": str(tmp_path / "bin/gh"),
    }
    proc = subprocess.run(
        ["bash", str(ROOT / "scripts/dispatch-live-overlay.sh")],
        env=env, text=True, capture_output=True,
    )
    lines = calls.read_text().splitlines() if calls.exists() else []
    return proc, [line for line in lines if line.startswith("workflow run")]


def test_a_promoted_desktop_cell_dispatches_its_overlay_with_the_promoted_index(tmp_path, config):
    proc, runs = dispatch(tmp_path, config)
    assert proc.returncode == 0, proc.stderr
    assert runs == [
        "workflow run live-overlay.yml --repo tuna-os/tunaOS --ref main "
        f"-f variant=skipjack -f flavors=gnome -f base_index_digest={PROMOTED_INDEX}"
    ]


def test_a_manual_build_on_main_dispatches_too(tmp_path, config):
    proc, runs = dispatch(tmp_path, config, EVENT_NAME="workflow_dispatch")
    assert proc.returncode == 0, proc.stderr
    assert len(runs) == 1


@pytest.mark.parametrize("overrides", [
    {"EVENT_NAME": "pull_request"},
    {"REPOSITORY": "someone/tunaOS"},
    {"REF": "refs/heads/feature"},
    {"PROMOTED": ""},
    {"FLAVOR": "base", "IMAGE_TAG": "base"},
    {"FLAVOR": "tuna", "IMAGE_TAG": "tuna"},
    # Promote wrote bonito:gnome-rawhide; the overlay's base is bonito-rawhide:gnome.
    {"VARIANT": "bonito-rawhide", "IMAGE_NAME": "bonito", "IMAGE_TAG": "gnome-rawhide"},
], ids=["pull-request", "fork", "branch", "not-promoted", "base", "tuna", "renamed-image"])
def test_nothing_is_dispatched_for_a_cell_promote_did_not_rebase(tmp_path, config, overrides):
    proc, runs = dispatch(tmp_path, config, **overrides)
    assert proc.returncode == 0, proc.stderr
    assert runs == []
    assert "not dispatching" in proc.stdout


def test_a_promotion_without_its_index_digest_fails(tmp_path, config):
    proc, runs = dispatch(tmp_path, config, BASE_INDEX_DIGEST="")
    assert proc.returncode == 1
    assert runs == []
    assert "no index digest" in proc.stderr


def test_a_disabled_overlay_workflow_fails_with_the_fix(tmp_path, config):
    proc, runs = dispatch(tmp_path, config, state="disabled_manually")
    assert proc.returncode == 1
    assert runs == []
    assert "gh workflow enable live-overlay.yml" in proc.stderr


# ── which bases an overlay may bind ──────────────────────────────────────────

def in_index(raw: str, platform: str, digest: str) -> int:
    return subprocess.run(
        ["bash", "-c", f'source {ROOT}/scripts/lib/platform-digest.sh; '
                       'index_lists_platform_digest "$1" "$2"', "_", platform, digest],
        input=raw, text=True, capture_output=True,
    ).returncode


PROMOTE_INDEX = index(("amd64", AMD64), ("amd64/v2", AMD64_V2), ("arm64", ARM64))


@pytest.mark.parametrize("platform,digest", [
    ("linux/amd64", AMD64),
    ("linux/amd64", AMD64_V2),
    ("linux/arm64", ARM64),
])
def test_a_base_from_the_index_belongs_to_it(platform, digest):
    assert in_index(PROMOTE_INDEX, platform, digest) == 0


@pytest.mark.parametrize("platform,digest", [
    ("linux/amd64", NEWER_AMD64),  # the tag moved to a newer Promote
    ("linux/amd64", ARM64),        # listed, but for another arch
], ids=["tag-moved", "wrong-arch"])
def test_a_base_outside_the_index_is_refused(platform, digest):
    assert in_index(PROMOTE_INDEX, platform, digest) == 1


@pytest.mark.parametrize("raw,platform,digest", [
    ("not json", "linux/amd64", AMD64),
    (PROMOTE_INDEX, "linux/amd64", "latest"),
    (PROMOTE_INDEX, "windows/amd64", AMD64),
], ids=["unreadable", "not-a-digest", "unsupported-platform"])
def test_an_unusable_question_is_an_error_not_a_refusal(raw, platform, digest):
    assert in_index(raw, platform, digest) == 2


# ── Promote reports the index it wrote ───────────────────────────────────────

def run_promote(tmp_path: Path, all_built: str) -> dict:
    step = next(s for s in yaml.safe_load(REUSABLE.read_text())["jobs"]["tag-image"]["steps"]
                if s.get("name") == "Pull Image and Apply Tags")
    bin_dir = tmp_path / "bin"
    stub(bin_dir, "sudo", 'exec "$@"\n')
    stub(bin_dir, "skopeo", f"""\
        while (($#)); do
          if [[ "$1" == --digestfile ]]; then printf '%s' {PROMOTED_INDEX} > "$2"; fi
          shift
        done
    """)
    output = tmp_path / "github-output"
    output.write_text("")
    env = os.environ | {
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "GITHUB_OUTPUT": str(output),
        "IMAGE_NAME": "skipjack", "IMAGE_ALIASES": "", "IMAGE_REGISTRY": "ghcr.io/tuna-os",
        "DEFAULT_TAG": "gnome", "MAJOR_VERSION": "", "ALL_PLATFORMS_BUILT": all_built,
        "INPUT_PLATFORMS": "linux/amd64", "MAX_RETRIES": "1",
    }
    subprocess.run(["bash", "-e", "-c", step["run"]], env=env, text=True,
                   capture_output=True, check=True)
    return dict(line.split("=", 1) for line in output.read_text().splitlines())


def test_promote_reports_the_index_it_wrote_to_the_bare_tag(tmp_path):
    outputs = run_promote(tmp_path, "true")
    assert outputs["promoted"] == "true"
    assert outputs["index_digest"] == PROMOTED_INDEX


def test_a_withheld_promotion_reports_nothing_to_rebind(tmp_path):
    outputs = run_promote(tmp_path, "false")
    assert "promoted" not in outputs
    assert "index_digest" not in outputs


# ── the overlay run binds only what the tag still names ──────────────────────

def publish_index(tmp_path: Path, tag_index: str) -> tuple[subprocess.CompletedProcess, list[str]]:
    job = yaml.safe_load(LIVE_OVERLAY.read_text())["jobs"]["publish-compatible-index"]
    step = next(s for s in job["steps"] if s.get("name") == "Publish complete current-run platform groups")
    bin_dir = tmp_path / "bin"
    calls = tmp_path / "podman-calls"
    stub(bin_dir, "skopeo", f"cat <<'EOF'\n{tag_index}\nEOF\n")
    stub(bin_dir, "podman", f"printf '%s\\n' \"$*\" >> {calls}\n")
    stub(bin_dir, "sleep", "exit 0\n")
    work = tmp_path / "work"
    (work / "receipts").mkdir(parents=True)
    (work / "scripts/lib").mkdir(parents=True)
    (work / "scripts/lib/platform-digest.sh").write_text(
        (ROOT / "scripts/lib/platform-digest.sh").read_text())
    for platform, digest, base in [("linux/amd64", "sha256:" + "e" * 64, AMD64),
                                   ("linux/arm64", "sha256:" + "f" * 64, ARM64)]:
        (work / f"receipts/{platform.replace('/', '-')}.json").write_text(json.dumps({
            "variant": "skipjack", "flavor": "gnome", "platform": platform,
            "repository": "ghcr.io/tuna-os/live-overlay", "digest": digest,
            "base_digest": base, "installer": "app@" + "0" * 64,
        }))
    matrix = {"include": [{"variant": "skipjack", "flavor": "gnome", "platform": p}
                          for p in ("linux/amd64", "linux/arm64")]}
    env = os.environ | {
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "MATRIX": json.dumps(matrix),
        "PUBLISH_DEST": "ghcr.io/tuna-os",
    }
    proc = subprocess.run(["bash", "-e", "-c", step["run"]], cwd=work, env=env,
                          text=True, capture_output=True)
    pushes = [c for c in (calls.read_text().splitlines() if calls.exists() else [])
              if c.startswith("manifest push")]
    return proc, pushes


def test_an_overlay_built_from_the_current_base_is_bound(tmp_path):
    proc, pushes = publish_index(tmp_path, PROMOTE_INDEX)
    assert proc.returncode == 0, proc.stderr
    assert pushes == [
        "manifest push --all ghcr.io/tuna-os/live-overlay:skipjack-gnome "
        "docker://ghcr.io/tuna-os/live-overlay:skipjack-gnome"
    ]


def test_an_overlay_is_not_bound_once_a_newer_promote_moved_its_base(tmp_path):
    newer = index(("amd64", NEWER_AMD64), ("arm64", ARM64))
    proc, pushes = publish_index(tmp_path, newer)
    assert proc.returncode == 0, proc.stderr
    assert pushes == []
    assert "moved since this run built from it (linux/amd64)" in proc.stdout
