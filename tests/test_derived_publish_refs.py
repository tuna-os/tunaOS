"""CI and tooling read the publish destination from tunaos.toml, not from a literal.

A fork edits tunaos.toml and its images publish to its own registry and
namespace (scripts/publish-destination.sh is the one resolver). Workflows that
still wrote `ghcr.io/tuna-os/...` pulled, pushed or probed TunaOS's images from
a fork. These tests parse the real workflows and run the real shell, Python and
`just` code that builds each ref, for the stock repository and for a fork:

  * the stock repository resolves to the identical literal it had before;
  * a fork (owner Acme-Corp, or [build.publish] / IMAGE_REGISTRY) resolves to
    its own destination;
  * a new literal `ghcr.io/tuna-os` outside the allow-list below fails.
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import types
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github/workflows"

STOCK = {"GITHUB_REPOSITORY_OWNER": "tuna-os"}
ACME = {"GITHUB_REPOSITORY_OWNER": "Acme-Corp"}
QUAY = {"GITHUB_REPOSITORY_OWNER": "Acme-Corp", "IMAGE_REGISTRY": "quay.io/acme"}
RESOLVER_ENV = ("IMAGE_REGISTRY", "REPO_ORGANIZATION", "GITHUB_REPOSITORY_OWNER", "GITHUB_REPOSITORY", "TUNA_REGISTRY")


# ── The guard ────────────────────────────────────────────────────────────────

# Everything that builds, probes, publishes or documents a published image.
SCANNED = (
    ".github/workflows/*.yml", ".github/workflows/*.yaml", ".github/actions/**/*.yml",
    ".github/*.py", ".github/scripts/*", "scripts/**/*", "just/*.just", "Justfile",
    "Containerfile.custom", "custom/*", "tunaos-builder.yaml",
)

# (file, text on the offending line) -> why a fork keeps pulling it from TunaOS.
# Every entry is a TunaOS-owned dependency or an example, never the fork's own
# destination. Comment lines are not scanned.
ALLOWED = {
    (".github/workflows/build-toolchain.yml", 'REPO="ghcr.io/tuna-os/bootc-toolchain-'):
        "publishes the bootc-toolchain OCI artifact that Containerfile.debian and "
        "Containerfile.ubuntu pull from this exact path; the artifact is TunaOS's, not the fork's image",
    ("scripts/lib/tacklebox.sh", "ghcr.io/tuna-os/tacklebox:latest"):
        "default for the tacklebox tool image (TUNAOS_*-style override: TACKLEBOX_IMAGE); upstream dependency",
    ("scripts/build-image-inner.sh", "ghcr.io/tuna-os/tunaos-packages"):
        "default for the tunaos-packages build input (override: GNOME50_EL10_PACKAGES_IMAGE); upstream dependency",
    ("scripts/resolve-image.sh", "ghcr.io/tuna-os/tunaos-packages"):
        "same tunaos-packages default as build-image-inner.sh, resolved for CI",
    ("scripts/get-base-image.sh", "ghcr.io/tuna-os/archlinuxarm:latest"):
        "the Arch Linux ARM base image TunaOS builds and publishes; a base, not the fork's output",
    ("scripts/installed-lifecycle-pilot.py", "ghcr.io/tuna-os/skipjack@sha256"):
        "error text of the installed-lifecycle pilot, which is pinned by IMAGE_RE to TunaOS's own "
        "skipjack digests (a qualification harness for TunaOS images, not a fork build path)",
    ("scripts/inspect-published-image.py", "ghcr.io/tuna-os/skipjack:gnome"):
        "usage example in the module docstring; the script takes the ref as an argument",
}
LITERAL = re.compile(r"ghcr\.io/tuna-os\b")


def scanned_files():
    seen = set()
    for pattern in SCANNED:
        for path in sorted(ROOT.glob(pattern)):
            if path.is_file() and path not in seen and "__pycache__" not in path.parts and "_vendor" not in path.parts:
                seen.add(path)
                yield path


def literal_lines():
    hits = []
    for path in scanned_files():
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for number, line in enumerate(text.splitlines(), 1):
            if LITERAL.search(line) and not line.lstrip().startswith("#"):
                hits.append((path.relative_to(ROOT).as_posix(), number, line.strip()))
    return hits


def test_no_literal_stock_registry_outside_the_allow_list():
    unexplained = [hit for hit in literal_lines()
                   if not any(hit[0] == name and needle in hit[2] for name, needle in ALLOWED)]
    assert not unexplained, (
        "a published image ref is written as ghcr.io/tuna-os/... instead of derived from "
        "scripts/publish-destination.sh (or scripts/published-image-ref.sh):\n"
        + "\n".join(f"  {name}:{number}: {line}" for name, number, line in unexplained))


def test_every_allow_list_entry_still_matches_a_line():
    """A stale entry would silently excuse a future literal on the same file."""
    hits = literal_lines()
    stale = [entry for entry in ALLOWED if not any(entry[0] == name and entry[1] in line for name, _, line in hits)]
    assert not stale, f"allow-list entries that match no line: {stale}"


def test_the_guard_catches_a_new_literal(tmp_path, monkeypatch):
    """The scan must be able to fail: a workflow with a fresh literal is reported."""
    probe = tmp_path / ".github/workflows/probe.yml"
    probe.parent.mkdir(parents=True)
    probe.write_text("jobs:\n  a:\n    steps:\n      - run: skopeo inspect docker://ghcr.io/tuna-os/yellowfin:gnome\n")
    monkeypatch.setitem(globals(), "ROOT", tmp_path)
    assert [hit[0] for hit in literal_lines()] == [".github/workflows/probe.yml"]


def workflow(name):
    return yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))


def test_no_workflow_forces_the_repository_owner_to_tuna_os():
    """GITHUB_REPOSITORY_OWNER is the runner's own; pinning it made a fork resolve TunaOS's destination."""
    offenders = []

    def walk(node, where):
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "GITHUB_REPOSITORY_OWNER" and value == "tuna-os":
                    offenders.append(where)
                walk(value, f"{where}/{key}")
        elif isinstance(node, list):
            for index, value in enumerate(node):
                walk(value, f"{where}[{index}]")

    for path in sorted(WORKFLOWS.glob("*.yml")):
        walk(yaml.safe_load(path.read_text(encoding="utf-8")), path.name)
    assert not offenders, offenders


# ── Helpers that run the real code ───────────────────────────────────────────

def clean_env(**extra):
    env = {k: v for k, v in os.environ.items() if k not in RESOLVER_ENV}
    env.update(extra)
    return env


def sh(script, env, cwd=ROOT):
    return subprocess.run(["bash", "-c", script], cwd=cwd, env=env, text=True, capture_output=True, check=True).stdout


def find_step(name, job, step_name=None, step_id=None):
    jobs = workflow(name)["jobs"]
    matches = [step for step in jobs[job]["steps"]
               if (step_name is not None and step.get("name") == step_name) or (step_id is not None and step.get("id") == step_id)]
    assert len(matches) == 1, f"{name} {job}: expected one step, found {len(matches)}"
    return matches[0]


def assignment(run, var):
    """The one single-line `VAR="..."` assignment of `var` in a step's script."""
    found = re.findall(rf'^[ \t]*({var}="[^\n]*")[ \t]*$', run, re.M)
    assert len(found) == 1, f"expected one {var}= line, found {found}"
    return found[0]


def value(run, var, env):
    return sh(f'{assignment(run, var)}\nprintf %s "${{{var}}}"', env)


def resolve_destination(name, job, env):
    """Run a workflow's real `Resolve publish destination` step; return its output."""
    step = find_step(name, job, step_id="dest")
    out = ROOT / ".build-test-github-output"
    try:
        out.write_text("")
        subprocess.run(["bash", "-c", step["run"]], cwd=ROOT, text=True, capture_output=True, check=True,
                       env={**env, "GITHUB_OUTPUT": str(out)})
        return dict(line.split("=", 1) for line in out.read_text().splitlines())["destination"]
    finally:
        out.unlink(missing_ok=True)


DESTINATION_STEPS = (
    ("bootc-lifecycle.yml", "generate-matrix"),
    ("live-overlay.yml", "generate-matrix"),
    ("publish-isos.yml", "generate-matrix"),
    ("verify-asahi.yml", "destination"),
    ("asahi-hw-nightly.yml", "destination"),
)


@pytest.mark.parametrize("name,job", DESTINATION_STEPS)
def test_destination_step_resolves_stock_fork_and_override(name, job):
    assert resolve_destination(name, job, clean_env(**STOCK)) == "ghcr.io/tuna-os"
    assert resolve_destination(name, job, clean_env(**ACME)) == "ghcr.io/acme-corp"
    assert resolve_destination(name, job, clean_env(**QUAY)) == "quay.io/acme"


@pytest.mark.parametrize("name,job", DESTINATION_STEPS)
def test_destination_step_honours_the_operator_variable_the_build_honours(name, job):
    env = find_step(name, job, step_id="dest")["env"]
    assert env == {"IMAGE_REGISTRY": "${{ vars.IMAGE_REGISTRY }}"}


# (workflow, job, step, variable, environment) -> the literal the workflow had before.
INLINE_REFS = (
    ("bootc-lifecycle.yml", "lifecycle", "Validate bootc image update, rebase, rollback & aliases", "REF",
     {"VARIANT": "yellowfin", "FLAVOR": "gnome"}, "ghcr.io/tuna-os/yellowfin:gnome"),
    ("bootc-lifecycle.yml", "lifecycle", "Validate bootc image update, rebase, rollback & aliases", "ALIAS_REF",
     {"ALIAS": "tuna", "FLAVOR": "gnome"}, "ghcr.io/tuna-os/tuna:gnome"),
    ("bootc-lifecycle.yml", "lifecycle-beta", "Track beta stream status", "REF",
     {"VARIANT": "guppy", "FLAVOR": "gnome"}, "ghcr.io/tuna-os/guppy:gnome"),
    ("live-overlay.yml", "overlay", "Run live customize and publish overlay", "IMG",
     {"VARIANT": "yellowfin", "FLAVOR": "gnome"}, "ghcr.io/tuna-os/yellowfin:gnome"),
    ("live-overlay.yml", "overlay", "Run live customize and publish overlay", "OUT",
     {"VARIANT": "yellowfin", "FLAVOR": "gnome", "SAFEPLATFORM": "linux-amd64", "GITHUB_RUN_ID": "1", "GITHUB_RUN_ATTEMPT": "1"},
     "ghcr.io/tuna-os/live-overlay:yellowfin-gnome-linux-amd64-1-1"),
    ("publish-iso-groups.yml", "generate-matrix", "Build matrix from iso_groups ∩ variant flavors", "image",
     {"pubname": "flounder", "probe_tag": "gnome-sid"}, "ghcr.io/tuna-os/flounder:gnome-sid"),
    ("catalog-facts.yml", "facts", "Probe this variant's catalog images", "IMG",
     {"CELL": "yellowfin:gnome"}, "ghcr.io/tuna-os/yellowfin:gnome"),
)


@pytest.mark.parametrize("name,job,step_name,var,env,stock", INLINE_REFS)
def test_inline_ref_is_the_old_literal_for_stock_and_follows_a_fork(name, job, step_name, var, env, stock):
    run = find_step(name, job, step_name=step_name)["run"]
    assert "ghcr.io/tuna-os" not in run.replace("\n", " ").split(var + "=", 1)[1].split("\n", 1)[0]
    # The destination arrives as a job output (PUBLISH_DEST) in matrix jobs, or is
    # resolved in the step itself; either way it is what publish-destination.sh prints.
    for owner_env, destination in ((STOCK, "ghcr.io/tuna-os"), (ACME, "ghcr.io/acme-corp")):
        resolved = value(run, var, clean_env(**owner_env, PUBLISH_DEST=destination, **env))
        assert resolved == stock.replace("ghcr.io/tuna-os", destination)


def test_live_initramfs_output_ref_comes_from_the_resolver():
    jobs = workflow("live-initramfs.yml")["jobs"]
    run = next(step["run"] for job in jobs.values() for step in job["steps"]
               if step.get("name") == "Harvest & publish tbox initramfs artifact")
    env = {"VARIANT": "yellowfin", "FLAVOR": "gnome"}
    assert value(run, "OUT", clean_env(**STOCK, **env)) == "ghcr.io/tuna-os/live-initramfs:yellowfin-gnome"
    assert value(run, "OUT", clean_env(**ACME, **env)) == "ghcr.io/acme-corp/live-initramfs:yellowfin-gnome"
    assert value(run, "OUT", clean_env(**QUAY, **env)) == "quay.io/acme/live-initramfs:yellowfin-gnome"


def test_catalog_facts_key_is_the_image_path_without_the_registry():
    """The browser catalog keys facts by `<namespace>/<variant>:<flavor>`; TunaOS's keys must not move."""
    probe = find_step("catalog-facts.yml", "facts", step_name="Probe this variant's catalog images")["run"]
    key = re.search(r'--arg k "([^"]*)"', probe).group(1)
    merge = find_step("catalog-facts.yml", "merge", step_name="Merge shards and validate browser catalog completeness")["run"]
    expression = re.search(r"^\s*(f\"\{os\.environ\['PUBLISH_DEST'\][^\n]*\")\s*$", merge, re.M).group(1)
    for destination, expected in (("ghcr.io/tuna-os", "tuna-os/yellowfin:gnome"), ("quay.io/acme", "acme/yellowfin:gnome")):
        # The shard writer (bash) and the completeness check (python) must agree on the key.
        assert sh(f'PUBLISH_DEST={destination}; CELL=yellowfin:gnome; printf %s "{key}"', clean_env()) == expected
        scope = {"os": types.SimpleNamespace(environ={"PUBLISH_DEST": destination}),
                 "variant": {"id": "yellowfin"}, "flavor": {"id": "gnome"}}
        assert eval(expression, scope) == expected


def test_release_notes_name_the_published_image():
    run = find_step("publish-isos.yml", "attach-release", step_name="Attach ISO to GitHub Release")["run"]
    notes = re.search(r'--notes "([^"]*)"', run).group(1)
    env = clean_env(VARIANT="yellowfin", FLAVOR="gnome", PUBLISH_DEST="ghcr.io/tuna-os")
    assert sh(f'printf %s "{notes}"', env) == "Live ISO for yellowfin:gnome. Built from ghcr.io/tuna-os/yellowfin:gnome."
    assert sh(f'printf %s "{notes}"', {**env, "PUBLISH_DEST": "quay.io/acme"}).endswith("Built from quay.io/acme/yellowfin:gnome.")


@pytest.mark.parametrize("name,flavors", (("verify-asahi.yml", ("bonito", "grouper", "albacore")),
                                          ("asahi-hw-nightly.yml", ("bonito", "grouper"))))
def test_asahi_sweeps_read_the_destination_job(name, flavors):
    sweep = workflow(name)["jobs"]["sweep"]
    needs = sweep["needs"] if isinstance(sweep["needs"], list) else [sweep["needs"]]
    assert "destination" in needs
    template = sweep["with"]["image"]
    assert set(re.findall(r"\$\{\{ ([^}]*) \}\}", template)) == {"needs.destination.outputs.destination", "matrix.flavor"}
    for flavor in flavors:
        for destination in ("ghcr.io/tuna-os", "ghcr.io/acme-corp"):
            ref = template.replace("${{ needs.destination.outputs.destination }}", destination).replace("${{ matrix.flavor }}", flavor)
            assert ref == f"{destination}/{flavor}:gnome-asahi"


@pytest.mark.parametrize("name,job,step_name", (
    ("gdm-paint-benchmark.yml", "build-base", "Build base qcow2"),
))
def test_gdm_default_image_follows_the_destination(name, job, step_name):
    run = find_step(name, job, step_name=step_name)["run"]
    assert value(run, "IMAGE", clean_env(**STOCK, INPUT_IMAGE="")) == "ghcr.io/tuna-os/yellowfin:gnome"
    assert value(run, "IMAGE", clean_env(**ACME, INPUT_IMAGE="")) == "ghcr.io/acme-corp/yellowfin:gnome"
    assert value(run, "IMAGE", clean_env(**ACME, INPUT_IMAGE="quay.io/x/y:z")) == "quay.io/x/y:z"


def test_ghcr_canary_default_image_follows_the_destination(tmp_path):
    jobs = workflow("ghcr-partial-pull-check.yml")["jobs"]["canary"]
    run = next(step["run"] for step in jobs["steps"] if step.get("name") == "Resolve image")
    for env, expected in ((STOCK, "ghcr.io/tuna-os/yellowfin:gnome"), (ACME, "ghcr.io/acme-corp/yellowfin:gnome")):
        github_env = tmp_path / "env"
        github_env.write_text("")
        sh(run, clean_env(**env, INPUT_IMAGE="", GITHUB_ENV=str(github_env)))
        assert github_env.read_text().strip() == f"IMAGE={expected}"
    # The canary only measures GHCR blob handling: any other registry is skipped, not failed.
    check = next(step["run"] for step in jobs["steps"] if step.get("name") == "Raw HTTP range-request check")
    guard = check.split("NAMETAG=", 1)[0]
    result = subprocess.run(["bash", "-c", guard.replace("set -x", "set +x") + "\necho reached-network"],
                            env=clean_env(IMAGE="quay.io/acme/yellowfin:gnome"), text=True, capture_output=True)
    assert result.returncode == 0 and "reached-network" not in result.stdout and "not on ghcr.io" in result.stdout


def test_buildcache_repo_follows_the_project_id(tmp_path):
    run = find_step("reusable-build-image.yml", next(
        job for job, body in workflow("reusable-build-image.yml")["jobs"].items()
        if any(step.get("name") == "Configure buildah registry layer cache" for step in body["steps"])),
        step_name="Configure buildah registry layer cache")["run"]

    def flags(identity, registry="ghcr.io/tuna-os"):
        github_env = tmp_path / "github-env"
        github_env.write_text("")
        sh(run.replace("build_scripts/lib/identity.env", str(identity)),
           clean_env(IMAGE_REGISTRY=registry, IS_PR="true", GITHUB_ENV=str(github_env)))
        return github_env.read_text().strip()

    assert flags(ROOT / "build_scripts/lib/identity.env") == \
        "BUILDAH_CACHE_FLAGS=--layers --cache-from ghcr.io/tuna-os/tunaos-buildcache"
    acme = tmp_path / "identity.env"
    acme.write_text("TUNAOS_PROJECT_ID=acme\n")
    assert flags(acme, "quay.io/acme") == "BUILDAH_CACHE_FLAGS=--layers --cache-from quay.io/acme/acme-buildcache"


def test_parity_script_registry_follows_the_destination():
    text = (ROOT / "scripts/package-parity.sh").read_text(encoding="utf-8")
    block = re.search(r'^(SCRIPT_DIR=.*?^REGISTRY="[^\n]*"\n)', text, re.S | re.M).group(1)
    block = block.replace('SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"', f'SCRIPT_DIR="{ROOT / "scripts"}"')
    probe = f"set -euo pipefail\n{block}\nprintf %s \"$REGISTRY\""
    assert sh(probe, clean_env(**STOCK)) == "ghcr.io/tuna-os"
    assert sh(probe, clean_env(**ACME)) == "ghcr.io/acme-corp"
    assert sh(probe, clean_env(**ACME, TUNA_REGISTRY="mirror.example/os")) == "mirror.example/os"


def load_module(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def python_env(monkeypatch):
    for key in RESOLVER_ENV:
        monkeypatch.delenv(key, raising=False)
    sys.path.insert(0, str(ROOT / "scripts"))
    from lib import publish_destination as seam
    seam.publish_destination.cache_clear()
    yield monkeypatch
    seam.publish_destination.cache_clear()
    sys.path.remove(str(ROOT / "scripts"))


def test_changelog_registry_and_rebase_commands_follow_the_destination(python_env):
    module = load_module("changelogs_under_test", ".github/changelogs.py")
    python_env.setenv("GITHUB_REPOSITORY_OWNER", "tuna-os")
    assert module.publish_destination() == "ghcr.io/tuna-os"
    module.publish_destination.cache_clear()
    python_env.setenv("GITHUB_REPOSITORY_OWNER", "Acme-Corp")
    assert module.publish_destination() == "ghcr.io/acme-corp"
    assert "ghcr.io/tuna-os" not in module.CHANGELOG_FORMAT
    assert module.CHANGELOG_FORMAT.count("{registry}/$IMAGE_NAME:") == 2


def test_changelog_skopeo_inspects_the_derived_ref(python_env):
    module = load_module("changelogs_inspect_under_test", ".github/changelogs.py")
    python_env.setenv("GITHUB_REPOSITORY_OWNER", "tuna-os")
    calls = []

    def fake_run(command, **_):
        calls.append(command)
        return types.SimpleNamespace(stdout=json.dumps({"Labels": {}}).encode())

    python_env.setattr(module, "subprocess", types.SimpleNamespace(
        run=fake_run, PIPE=subprocess.PIPE, CalledProcessError=subprocess.CalledProcessError))
    python_env.setattr(module, "get_images", lambda target: iter([("albacore", "base", "gnome", "main")]))
    module.get_manifests("stable")
    assert calls == [["skopeo", "inspect", "docker://ghcr.io/tuna-os/albacore:stable"]]


def test_matrix_status_reads_this_repository(monkeypatch):
    monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
    assert load_module("matrix_status_stock", "scripts/gen-matrix-status.py").REPO == "tuna-os/tunaOS"
    monkeypatch.setenv("GITHUB_REPOSITORY", "acme/os")
    assert load_module("matrix_status_fork", "scripts/gen-matrix-status.py").REPO == "acme/os"


class _Reply:
    def __init__(self, document):
        self.document = document

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return json.dumps(self.document).encode()


def test_matrix_status_lists_overlay_tags_of_the_destination_namespace(python_env):
    module = load_module("matrix_status_overlay", "scripts/gen-matrix-status.py")
    requested = []

    def fake_urlopen(request, timeout=None):
        url = request if isinstance(request, str) else request.full_url
        requested.append(url)
        return _Reply({"token": "t"} if "/token" in url else {"tags": ["yellowfin-gnome", "sha256-abc"]})

    python_env.setattr(module.urllib.request, "urlopen", fake_urlopen)
    for destination, namespace in (("ghcr.io", "tuna-os"), ("ghcr.io", "acme-corp")):
        python_env.setattr(module, "registry_and_namespace", lambda d=destination, n=namespace: (d, n))
        requested.clear()
        assert module.overlay_tags() == {"yellowfin-gnome"}
        assert requested == [f"https://ghcr.io/token?scope=repository:{namespace}/live-overlay:pull",
                             f"https://ghcr.io/v2/{namespace}/live-overlay/tags/list"]


def test_matrix_status_does_not_ask_ghcr_about_another_registry(python_env, capsys):
    module = load_module("matrix_status_quay", "scripts/gen-matrix-status.py")
    python_env.setattr(module, "registry_and_namespace", lambda: ("quay.io", "acme"))
    python_env.setattr(module.urllib.request, "urlopen", lambda *a, **k: pytest.fail("queried a registry"))
    assert module.overlay_tags() == set()
    assert "quay.io/acme/live-overlay is not read" in capsys.readouterr().err


def test_roadmap_coverage_measures_this_owners_org(monkeypatch):
    monkeypatch.delenv("GITHUB_REPOSITORY_OWNER", raising=False)
    assert load_module("roadmap_stock", "scripts/gen-roadmap-coverage.py").ORG == "tuna-os"
    monkeypatch.setenv("GITHUB_REPOSITORY_OWNER", "acme")
    assert load_module("roadmap_fork", "scripts/gen-roadmap-coverage.py").ORG == "acme"


def test_gfi_pool_report_and_corral_build_follow_the_repository():
    gfi = (ROOT / "scripts/gfi-pool-report.sh").read_text(encoding="utf-8")
    corral = (ROOT / "scripts/corral-build.sh").read_text(encoding="utf-8")
    for owner_env, org in ((clean_env(), "tuna-os"), (clean_env(GITHUB_REPOSITORY_OWNER="acme"), "acme")):
        assert sh(f'{assignment(gfi, "ORG")}\nprintf %s "$ORG"', owner_env) == org
    repo_line = re.search(r'^REPO="[^\n]*"$', corral, re.M).group(0)
    probe = f'{repo_line}\nprintf %s "$REPO"'
    assert sh(probe, clean_env()) == "tuna-os/tunaOS"
    assert sh(probe, clean_env(GITHUB_REPOSITORY="acme/os")) == "acme/os"
    assert sh(probe, clean_env(GITHUB_REPOSITORY="acme/os", CORRAL_REPO="acme/builder")) == "acme/builder"
    assert "https://github.com/${REPO}.git" in corral and "tuna-os/tunaOS.git" not in corral


# ── just build-custom: the default base ──────────────────────────────────────

@pytest.mark.skipif(shutil.which("just") is None, reason="just is not installed")
class TestBuildCustomDefaultBase:
    def build(self, tmp_path, *args, config=None, **env):
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir(exist_ok=True)
        log = tmp_path / "podman.log"
        podman = bin_dir / "podman"
        podman.write_text(f'#!/usr/bin/env bash\nprintf "%s\\n" "$*" >> "{log}"\n')
        podman.chmod(0o755)
        environment = clean_env(PATH=f"{bin_dir}:{os.environ['PATH']}", **env)
        if config is not None:
            environment["TUNAOS_BUILD_CONFIG"] = str(config)
        result = subprocess.run(["just", "build-custom", *args], cwd=ROOT, env=environment, text=True, capture_output=True)
        return result, (log.read_text() if log.exists() else "")

    def config_without(self, tmp_path, expression):
        subprocess.run(["python3", "scripts/config.py", "generate"], cwd=ROOT, check=True, capture_output=True)
        out = tmp_path / "build-config.yml"
        out.write_text(subprocess.run(["yq", "-o=json", expression, ".github/build-config.yml"], cwd=ROOT,
                                      text=True, capture_output=True, check=True).stdout)
        return out

    def test_stock_default_is_the_literal_it_always_was(self, tmp_path):
        result, log = self.build(tmp_path, **STOCK)
        assert result.returncode == 0, result.stderr
        assert "--build-arg BASE_IMAGE=ghcr.io/tuna-os/yellowfin:gnome " in log + " "

    def test_fork_default_is_its_own_first_gnome_variant(self, tmp_path):
        config = self.config_without(tmp_path, 'del(.variants[] | select(.id == "yellowfin"))')
        result, log = self.build(tmp_path, config=config, **ACME)
        assert result.returncode == 0, result.stderr
        assert "--build-arg BASE_IMAGE=ghcr.io/acme-corp/albacore:gnome " in log + " "

    def test_explicit_base_still_wins(self, tmp_path):
        result, log = self.build(tmp_path, "quay.io/x/y:z", **ACME)
        assert result.returncode == 0, result.stderr
        assert "--build-arg BASE_IMAGE=quay.io/x/y:z " in log + " "

    def test_no_gnome_variant_fails_loudly(self, tmp_path):
        config = self.config_without(tmp_path, '.variants |= map(.flavors |= map(select(.id != "gnome")))')
        result, log = self.build(tmp_path, config=config, **STOCK)
        assert result.returncode != 0 and "no variant in tunaos.toml builds a gnome image" in result.stderr
        assert log == ""
