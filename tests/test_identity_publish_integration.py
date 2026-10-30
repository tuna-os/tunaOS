"""F1/F3a integration: one primary config controls destination and identity.

The real writer and verifier run on a redirected filesystem, not a built image.
No legacy fork manifest participates in this contract.
"""
import copy
import json
from pathlib import Path
import shutil
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).parent))
from test_anime_finalization import Image  # noqa: E402
from test_identity_config import ACME_PROJECT, config  # noqa: E402
from test_publish_destination import resolve  # noqa: E402
from test_verify_branding_vendor import verify, vendor_lines  # noqa: E402


def test_primary_identity_and_publish_destination_share_the_consumer_path(tmp_path):
    fork = copy.deepcopy(config.load())
    fork["build"]["publish"] = {"registry": "quay.io", "namespace": "acme"}
    fork["project"] = dict(ACME_PROJECT)
    # Replace only the URLs: [defaults.branding] also carries the required
    # plymouth default (#3668 F3d).
    fork["defaults"]["branding"].update({
        key: f"https://acme.example/{key}" for key in config.BRANDING_URLS
    })
    fork["variants"]["yellowfin"]["codename"] = "Wile E"
    config.validate(fork)
    adapter = tmp_path / "build-config.yml"
    adapter.write_text(config.render(fork), encoding="utf-8")
    registry, namespace = resolve(adapter).split()
    assert (registry, namespace) == ("quay.io", "acme")

    image = Image(tmp_path)
    (image.context / "build_scripts/lib/identity.env").write_text(
        config.render_identity(fork), encoding="utf-8")
    image.env.update(IMAGE_REGISTRY=registry, IMAGE_VENDOR=namespace)
    image.info()
    info = json.loads((image.root / "usr/share/ublue-os/image-info.json").read_text(encoding="utf-8"))
    assert info["image-vendor"] == "acme"
    assert info["image-ref"] == "ostree-image-signed:docker://quay.io/acme/yellowfin"
    release = (image.root / "usr/lib/os-release").read_text(encoding="utf-8")
    assert 'VERSION_CODENAME="Wile E"' in release
    assert 'HOME_URL="https://acme.example/homepage"' in release
    assert not (image.context / "manifests/fork-config.json").exists()
    installed_identity = image.root / "usr/share/tunaos/identity-config.env"
    assert installed_identity.read_bytes() == (
        image.context / "build_scripts/lib/identity.env"
    ).read_bytes()
    for env in ({}, {"IMAGE_VENDOR": namespace}):
        output = verify(image, **env)
        assert vendor_lines(output) == ["ok: image-vendor=acme"]
        assert "ok: HOME_URL=https://acme.example/homepage" in output


ROOT = Path(__file__).resolve().parents[1]
# Files system_files ships with @TUNAOS_*@ tokens or a recipe, which 90-image-info.sh fills.
IDENTITY_FILES = (
    "etc/bootc-installer/recipe.json",
    "usr/share/plasma/look-and-feel/org.tunaos.desktop/metadata.json",
    "usr/share/plasma/look-and-feel/org.tunaos.light.desktop/metadata.json",
    "usr/share/wallpapers/TunaOS/metadata.json",
    "usr/lib/systemd/system/tunaos-live-ready.service",
)


def image_with_identity_files(tmp_path, fork=None, **env):
    image = Image(tmp_path, "yellowfin", "kde")
    image.env.update({f"IS_{base}": "false" for base in (
        "FEDORA", "HUMMINGBIRD", "ALMALINUX", "ALMALINUXKITTEN", "CENTOS", "UBUNTU",
        "DEBIAN", "OPENSUSE", "GENTOO")}, IS_ARCH="true", IMAGE_FLAVOR="kde", **env)
    if fork is not None:
        (image.context / "build_scripts/lib/identity.env").write_text(config.render_identity(fork), encoding="utf-8")
    for relative in IDENTITY_FILES:
        target = image.root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / "system_files" / relative, target)
    return image


def acme_fork():
    fork = copy.deepcopy(config.load())
    fork["build"]["publish"] = {"registry": "quay.io", "namespace": "acme"}
    fork["project"] = dict(ACME_PROJECT)
    fork["defaults"]["branding"].update({key: f"https://acme.example/{key}" for key in config.BRANDING_URLS})
    return fork


def test_a_fork_image_names_itself_in_every_shipped_identity_file(tmp_path):
    """Installer image, installer slides, Plasma theme and wallpaper metadata and the
    live-ready unit carry the fork's name, URLs and destination, not TunaOS's."""
    image = image_with_identity_files(tmp_path, acme_fork(), IMAGE_REGISTRY="quay.io", IMAGE_VENDOR="acme")
    image.info()
    recipe = json.loads((image.root / "etc/bootc-installer/recipe.json").read_text(encoding="utf-8"))
    assert recipe["imgref"] == "quay.io/acme/yellowfin:kde"
    assert recipe["local_imgref"] == "containers-storage:quay.io/acme/yellowfin:kde"
    assert recipe["tour"]["completed"]["description"] == "Reboot your machine to enter your new Yellowfin workstation environment!"
    rendered = {name: (image.root / name).read_text(encoding="utf-8") for name in IDENTITY_FILES}
    for name, text in rendered.items():
        assert "@TUNAOS_" not in text, name
        if name.endswith("recipe.json"):
            continue
        assert "TunaOS" not in text and "tuna-os" not in text, name
    dark = json.loads(rendered["usr/share/plasma/look-and-feel/org.tunaos.desktop/metadata.json"])["KPlugin"]
    light = json.loads(rendered["usr/share/plasma/look-and-feel/org.tunaos.light.desktop/metadata.json"])["KPlugin"]
    wallpaper = json.loads(rendered["usr/share/wallpapers/TunaOS/metadata.json"])["KPlugin"]
    assert (dark["Name"], light["Name"], wallpaper["Name"]) == ("Yellowfin", "Yellowfin Light", "Yellowfin")
    assert dark["Description"] == "Acme OS - Theme variant of KDE BreezeDark"
    assert dark["Authors"][0]["Name"] == "Acme OS Contributors"
    assert dark["Website"] == light["Website"] == "https://acme.example/homepage"
    unit = rendered["usr/lib/systemd/system/tunaos-live-ready.service"]
    assert "Description=Acme OS live environment ready marker" in unit
    assert "Documentation=https://acme.example/homepage/blob/main/docs/IMPROVEMENT_PLAN.md" in unit


def test_the_branding_contract_fails_an_image_with_an_unrendered_identity_token(tmp_path):
    image = image_with_identity_files(tmp_path)
    image.info()
    clean = verify(image)
    assert "ok: no unrendered identity tokens" in clean
    unit = image.root / "usr/lib/systemd/system/tunaos-live-ready.service"
    unit.write_text(unit.read_text(encoding="utf-8") + "Description=@TUNAOS_PROJECT_NAME@\n")
    broken = verify(image)
    assert "FAIL: unrendered @TUNAOS_*@ identity token in:" in broken
    assert str(unit) in broken


def test_stock_installer_still_installs_the_stock_umbrella_image(tmp_path):
    image = image_with_identity_files(tmp_path)
    image.info()
    recipe = json.loads((image.root / "etc/bootc-installer/recipe.json").read_text(encoding="utf-8"))
    assert recipe["imgref"] == "ghcr.io/tuna-os/yellowfin:kde"
    assert recipe["local_imgref"] == "containers-storage:ghcr.io/tuna-os/yellowfin:kde"


def test_an_identity_token_no_adapter_value_fills_fails_the_build(tmp_path):
    image = image_with_identity_files(tmp_path)
    metadata = image.root / "usr/share/wallpapers/TunaOS/metadata.json"
    metadata.write_text(metadata.read_text(encoding="utf-8").replace("@TUNAOS_PROJECT_NAME@", "@TUNAOS_NO_SUCH_VALUE@", 1))
    result = subprocess.run(["bash", str(image.context / "build_scripts/90-image-info.sh")], env=image.env,
                            capture_output=True, text=True)
    assert result.returncode != 0
    assert "identity token" in result.stderr and "@TUNAOS_NO_SUCH_VALUE@" in result.stderr


def test_image_info_reports_an_unreadable_identity_adapter(tmp_path):
    image = Image(tmp_path)
    adapter = image.context / "build_scripts/lib/identity.env"
    adapter.chmod(0)

    result = subprocess.run(
        ["bash", str(image.context / "build_scripts/90-image-info.sh")],
        env=image.env,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "missing or unreadable" in result.stderr


def test_image_info_rejects_unreviewed_identity_override(tmp_path):
    image = Image(tmp_path)
    override = tmp_path / "outside.env"
    override.write_text(
        (image.context / "build_scripts/lib/identity.env").read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    result = subprocess.run(
        ["bash", str(image.context / "build_scripts/90-image-info.sh")],
        env={**image.env, "TUNAOS_IDENTITY_ENV": str(override)},
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "test-only" in result.stderr


# ── workflows: labels, release identity ─────────────────────────────────────

import os  # noqa: E402
import re  # noqa: E402

import yaml  # noqa: E402


def run_identity_step(workflow, job, tmp_path, identity_text, **env):
    """Execute a workflow's `Project identity` step body against an identity adapter."""
    document = yaml.safe_load((ROOT / ".github/workflows" / workflow).read_text(encoding="utf-8"))
    step = next(s for s in document["jobs"][job]["steps"] if s.get("id") == "identity")
    work = tmp_path / "work"
    (work / "build_scripts/lib").mkdir(parents=True)
    (work / "build_scripts/lib/identity.env").write_text(identity_text, encoding="utf-8")
    output = tmp_path / "github-output"
    result = subprocess.run(["bash", "-c", step["run"]], cwd=work, text=True, capture_output=True,
                            env={**os.environ, "GITHUB_OUTPUT": str(output), **env})
    assert result.returncode == 0, result.stderr
    return dict(line.split("=", 1) for line in output.read_text(encoding="utf-8").splitlines()), document["jobs"][job]


def test_oci_labels_keep_their_stock_values_and_follow_a_fork(tmp_path):
    stock_identity = (ROOT / "build_scripts/lib/identity.env").read_text(encoding="utf-8")
    outputs, job = run_identity_step("reusable-build-image.yml", "manifest", tmp_path / "stock", stock_identity)
    assert outputs == {"website": "https://tunaos.org", "documentation": "https://tunaos.org/docs/intro", "keyword": "tunaos"}
    labels = next(s for s in job["steps"] if s.get("id") == "metadata")["with"]["labels"]
    assert "org.opencontainers.image.url=${{ steps.identity.outputs.website }}" in labels
    assert "org.opencontainers.image.documentation=${{ steps.identity.outputs.documentation }}" in labels
    assert "io.artifacthub.package.keywords=bootc,${{ steps.identity.outputs.keyword }}" in labels
    assert "tunaos.org" not in labels
    fork_outputs, _ = run_identity_step("reusable-build-image.yml", "manifest", tmp_path / "fork", config.render_identity(acme_fork()))
    assert fork_outputs == {"website": "https://acme.example", "documentation": "https://acme.example/docs/intro", "keyword": "acmeos"}


def test_release_card_identity_derives_from_the_adapter_and_the_repository(tmp_path):
    stock_identity = (ROOT / "build_scripts/lib/identity.env").read_text(encoding="utf-8")
    outputs, job = run_identity_step("generate-changelog-release.yml", "generate-release", tmp_path / "stock", stock_identity,
                                     REPOSITORY="tuna-os/tunaOS")
    # The literals this replaced: title/project-name "TunaOS", docs-url, and the signing identity.
    assert outputs == {"name": "TunaOS", "docs-url": "https://tunaos.org/docs",
                       "cert-identity-regexp": r"^https://github\.com/tuna-os/tunaOS/\.github/workflows/"}
    fork_outputs, _ = run_identity_step("generate-changelog-release.yml", "generate-release", tmp_path / "fork",
                                        config.render_identity(acme_fork()), REPOSITORY="Acme-Corp/acme.os")
    assert fork_outputs["cert-identity-regexp"] == r"^https://github\.com/Acme-Corp/acme\.os/\.github/workflows/"
    assert re.match(fork_outputs["cert-identity-regexp"], "https://github.com/Acme-Corp/acme.os/.github/workflows/x.yml@refs/heads/main")
    assert not re.match(fork_outputs["cert-identity-regexp"], "https://github.com/Acme-Corp/acmeXos/.github/workflows/x.yml@refs/heads/main")
    release = next(s for s in job["steps"] if s.get("id") == "release")["with"]
    assert "TunaOS" not in json.dumps(release) and "tunaos.org" not in json.dumps(release) and "tuna-os" not in json.dumps(release)


def test_the_final_image_title_names_the_configured_project():
    containerfile = (ROOT / "Containerfile.final").read_text(encoding="utf-8")
    assert 'LABEL org.opencontainers.image.title="${TUNAOS_PROJECT_NAME} ${IMAGE_NAME} (${DESKTOP_FLAVOR})"' in containerfile
    assert containerfile.count("ARG TUNAOS_PROJECT_NAME") == 2        # global (FROM scope) and the stage that reads it
    build = (ROOT / "scripts/build-image-inner.sh").read_text(encoding="utf-8")
    assert '--build-arg "TUNAOS_PROJECT_NAME=${TUNAOS_PROJECT_NAME}"' in build
    assert build.index("build_scripts/lib/identity.env") < build.index('--build-arg "TUNAOS_PROJECT_NAME')
