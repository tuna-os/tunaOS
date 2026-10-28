"""Behavior contracts for #3806 image evidence and the config-only boundary."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "config_only_image_qualification", ROOT / "scripts/config-only-image-qualification.py"
)
QUALIFICATION = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(QUALIFICATION)


def digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def plan() -> dict:
    assets = {
        (QUALIFICATION.ASSET_DIR / name).as_posix(): digest(
            (QUALIFICATION.ASSET_FIXTURE / name).read_bytes()
        )
        for name in QUALIFICATION.ASSET_FILES
    }
    families = []
    builds = []
    for cell in QUALIFICATION.FAMILIES:
        variant, family = cell["variant"], cell["family"]
        refs = {role: f"localhost/{variant}:config-proof-{role.lower()}" for role in QUALIFICATION.ROLES}
        image_flavors = {
            role: ("base-no-de" if family == "rpm" else "base")
            if role.endswith("Base") else "gnome"
            for role in QUALIFICATION.ROLES
        }
        families.append({
            **cell,
            "package": QUALIFICATION.PACKAGE,
            "desktop": "gnome",
            "platform": QUALIFICATION.PLATFORM,
            "baseImage": f"registry.example/{variant}:base@sha256:{('a' if family == 'rpm' else 'b') * 64}",
            "images": refs,
            "imageFlavors": image_flavors,
        })
        for role in QUALIFICATION.ROLES:
            builds.append({
                "family": family,
                "role": role,
                "commit": "1" * 40 if role.startswith("stock") else "2" * 40,
                "variant": variant,
                "flavor": "base" if role.endswith("Base") else "gnome",
                "isCi": "1",
                "tag": refs[role].split(":", 1)[1],
                "chain": "",
            })
    return {
        "schemaVersion": 1,
        "platform": QUALIFICATION.PLATFORM,
        "stockCommit": "1" * 40,
        "modifiedCommit": "2" * 40,
        "stockConfigSha256": digest(b"stock TOML"),
        "modifiedConfigSha256": digest(b"fork TOML"),
        "stockAdapterSha256": digest(b"stock adapter"),
        "modifiedAdapterSha256": digest(b"modified adapter"),
        "generatedPaths": sorted(QUALIFICATION.GENERATED_PATHS),
        "ownedAssets": assets,
        "changedPaths": sorted({
            "tunaos.toml",
            *QUALIFICATION.GENERATED_PATHS,
            *assets,
        }),
        "expectedBrand": {
            "projectName": QUALIFICATION.PROJECT_NAME,
            "homepage": QUALIFICATION.HOMEPAGE,
            "theme": QUALIFICATION.PLYMOUTH_THEME,
        },
        "families": families,
        "builds": builds,
    }


def passed_report(value: dict) -> dict:
    family_results = []
    for cell in value["families"]:
        images = []
        for index, role in enumerate(QUALIFICATION.ROLES):
            stock = role.startswith("stock")
            receipt = None if stock else (
                f"# Written by build_scripts/lib/image-packages.sh for "
                f"{cell['variant']} ({cell['manager']}).\n"
                f"required\t{cell['package']}\n"
            )
            images.append({
                "role": role,
                "ref": cell["images"][role],
                "sourceCommit": value["stockCommit"] if stock else value["modifiedCommit"],
                "configSha256": value["stockConfigSha256"] if stock else value["modifiedConfigSha256"],
                "publicFlavor": "base" if role.endswith("Base") else "gnome",
                "imageFlavor": cell["imageFlavors"][role],
                "baseImage": cell["baseImage"],
                "baseDigest": cell["baseImage"].rsplit("@", 1)[1],
                "imageId": f"{index + 1:064x}",
                "manifestDigest": digest(f"manifest-{cell['family']}-{role}".encode()),
                "configDigest": digest(f"config-{cell['family']}-{role}".encode()),
                "platform": QUALIFICATION.PLATFORM,
                "packageStatus": "stock" if stock else "installed",
                "packageReceiptSha256": digest(receipt.encode()) if receipt else None,
                "packageReceipt": receipt,
                "branding": None if stock else {
                    "status": "passed",
                    "homeUrl": value["expectedBrand"]["homepage"],
                    "prettyName": cell["variant"].capitalize(),
                    "projectNameMarker": value["expectedBrand"]["projectName"],
                    "theme": value["expectedBrand"]["theme"],
                    "assets": value["ownedAssets"],
                    "plymouth": {
                        "status": "passed",
                        "configuredTheme": value["expectedBrand"]["theme"],
                        "defaultThemeLinkTarget": (
                            f"{value['expectedBrand']['theme']}/{value['expectedBrand']['theme']}.plymouth"
                        ),
                        "scriptPlugin": "/usr/lib64/plymouth/script.so",
                        "checks": {"configuredTheme": True, "defaultThemeLink": True, "scriptPlugin": True},
                        "reason": None,
                    },
                },
            })
        stock_inventory = json.dumps({
            "image": cell["variant"], "flavor": "gnome",
            "pkg_manager": "dnf" if cell["family"] == "rpm" else "apt",
            "count": 1, "packages": [{"name": "existing-package", "version": "1"}],
        })
        custom_inventory = json.dumps({
            "image": cell["variant"], "flavor": "gnome",
            "pkg_manager": "dnf" if cell["family"] == "rpm" else "apt",
            "count": 2, "packages": [
                {"name": "existing-package", "version": "1"},
                {"name": cell["package"], "version": "1"},
            ],
        })
        family_results.append({
            "family": cell["family"],
            "status": "passed",
            "reason": None,
            "baseDigest": cell["baseImage"].rsplit("@", 1)[1],
            "stockParity": {
                "status": "passed",
                "stockInventorySha256": digest(stock_inventory.encode()),
                "customInventorySha256": digest(custom_inventory.encode()),
                "stockInventoryReceipt": stock_inventory,
                "customInventoryReceipt": custom_inventory,
                "stockPackageCount": 1,
                "customPackageCount": 2,
                "missingOrChanged": [],
                "added": [cell["package"]],
            },
            "images": images,
            "logSha256": digest(f"log-{cell['family']}".encode()),
        })
    return {
        "schemaVersion": 1,
        "generatedAt": "2026-10-27T00:00:00Z",
        "planSha256": "",
        "sourceGate": {
            "status": "passed",
            "reason": None,
            "evidence": {
                "stockCommit": value["stockCommit"],
                "modifiedCommit": value["modifiedCommit"],
                "stockConfigSha256": value["stockConfigSha256"],
                "modifiedConfigSha256": value["modifiedConfigSha256"],
                "stockAdapterSha256": value["stockAdapterSha256"],
                "modifiedAdapterSha256": value["modifiedAdapterSha256"],
                "changedPaths": value["changedPaths"],
            },
        },
        "families": family_results,
        "summary": {"passed": 2, "failed": 0, "not-run": 0},
        "qualificationPass": True,
        "scope": "image-build-only; no install, boot, recovery, update, initramfs-rendering claim, publish, or production qualification",
    }


def write_pair(tmp_path: Path, value: dict, report: dict) -> tuple[Path, Path]:
    plan_path = tmp_path / "plan.json"
    report_path = tmp_path / "report.json"
    plan_path.write_text(json.dumps(value), encoding="utf-8")
    report["planSha256"] = digest(plan_path.read_bytes())
    report_path.write_text(json.dumps(report), encoding="utf-8")
    return plan_path, report_path


def test_primary_toml_recipe_resolves_brand_package_and_owned_theme():
    stock = (ROOT / "tunaos.toml").read_text(encoding="utf-8")
    fork = QUALIFICATION.recipe_text(stock)
    document = QUALIFICATION.tunaos_config.validate(
        QUALIFICATION.tunaos_config.parse(fork, "fork tunaos.toml")
    )
    assert document["project"]["name"] == QUALIFICATION.PROJECT_NAME
    assert document["defaults"]["branding"]["homepage"] == QUALIFICATION.HOMEPAGE
    assert document["variants"]["yellowfin"]["branding"]["plymouth"] == QUALIFICATION.PLYMOUTH_THEME
    assert document["variants"]["grouper"]["branding"]["plymouth"] == QUALIFICATION.PLYMOUTH_THEME
    assert document["variants"]["yellowfin"]["packages"]["add"] == [QUALIFICATION.PACKAGE]
    assert document["variants"]["grouper"]["packages"]["add"] == [QUALIFICATION.PACKAGE]


@pytest.mark.parametrize("path,allowed", [
    ("tunaos.toml", True),
    ("build_scripts/lib/image-packages.tsv", True),
    ("docs/iso-builder.config.json", True),
    ("system_files/usr/share/plymouth/themes/config-proof/config-proof.script", True),
    ("system_files/usr/share/plymouth/themes/config-proof/config-proof.plymouth", True),
    (".github/build-config.yml", False),
    ("scripts/build-image-inner.sh", False),
    ("build_scripts/lib/image-packages.sh", False),
    ("system_files/usr/share/backgrounds/fork-wallpaper.jpg", False),
    ("system_files/usr/share/plymouth/themes/config-proof/extra.sh", False),
    ("tests/fixtures/config-only-image-assets/config-proof.script", False),
])
def test_source_boundary_admits_only_primary_config_generated_outputs_and_named_owned_assets(path, allowed):
    assert QUALIFICATION.allowed_source_path(path) is allowed


def _candidate_repo(tmp_path: Path, extra_path: str | None = None):
    root = tmp_path / "candidate"
    root.mkdir()
    (root / ".gitignore").write_text("manifests/desktops/*.yaml\n", encoding="utf-8")
    (root / "build_scripts/lib").mkdir(parents=True)
    (root / "tunaos.toml").write_bytes((ROOT / "tunaos.toml").read_bytes())
    (root / "build_scripts/lib/image-packages.tsv").write_bytes(
        (ROOT / "build_scripts/lib/image-packages.tsv").read_bytes()
    )
    subprocess.run(["git", "init", "--quiet"], cwd=root, check=True)

    def git(*args):
        return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=True).stdout.strip()

    git("add", ".gitignore", "tunaos.toml", "build_scripts/lib/image-packages.tsv")
    git("-c", "user.name=config-boundary-test", "-c", "user.email=test@invalid",
        "commit", "--quiet", "-m", "stock")
    stock = git("rev-parse", "HEAD")

    config_path = root / "tunaos.toml"
    config_path.write_text(QUALIFICATION.recipe_text(config_path.read_text(encoding="utf-8")), encoding="utf-8")
    document = QUALIFICATION.tunaos_config.load(config_path)
    adapter = root / "build_scripts/lib/image-packages.tsv"
    adapter.write_text(QUALIFICATION.tunaos_config.render_image_packages(document), encoding="utf-8")
    identity = root / "build_scripts/lib/identity.env"
    identity.write_text(QUALIFICATION.tunaos_config.render_identity(document), encoding="utf-8")
    assets = QUALIFICATION._expected_asset_digests(root)
    for relative in assets:
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((QUALIFICATION.ASSET_FIXTURE / target.name).read_bytes())
    if extra_path is not None:
        extra = root / extra_path
        extra.parent.mkdir(parents=True, exist_ok=True)
        extra.write_text("unowned input\n", encoding="utf-8")
    git("add", "-A")
    git("-c", "user.name=config-boundary-test", "-c", "user.email=test@invalid",
        "commit", "--quiet", "-m", "config and owned assets")
    return root, stock, git("rev-parse", "HEAD"), assets


def _validate_candidate_outputs(root: Path, mode: str):
    subprocess.run(
        [sys.executable, str(ROOT / "scripts/config.py"), "validate", "--root", str(root)],
        cwd=ROOT, capture_output=True, text=True, check=True,
    )
    document = QUALIFICATION.tunaos_config.load(root / "tunaos.toml")
    assert (root / "build_scripts/lib/image-packages.tsv").read_text(encoding="utf-8") == \
        QUALIFICATION.tunaos_config.render_image_packages(document)
    assert (root / "build_scripts/lib/identity.env").read_text(encoding="utf-8") == \
        QUALIFICATION.tunaos_config.render_identity(document)


def test_committed_tree_delta_accepts_compiled_outputs_and_exact_owned_assets(tmp_path, monkeypatch):
    root, stock, modified, assets = _candidate_repo(tmp_path)
    monkeypatch.setattr(QUALIFICATION, "_generated_commands", _validate_candidate_outputs)
    changed = QUALIFICATION._check_source_delta(root, stock, modified, assets)
    assert set(changed) == {
        "tunaos.toml",
        "build_scripts/lib/image-packages.tsv",
        "build_scripts/lib/identity.env",
        *assets,
    }


@pytest.mark.parametrize("extra_path", [
    "Containerfile.el10",
    "system_files/usr/share/plymouth/themes/config-proof/extra.sh",
])
def test_committed_tree_delta_rejects_code_and_unlisted_assets(tmp_path, monkeypatch, extra_path):
    root, stock, modified, assets = _candidate_repo(tmp_path, extra_path)
    monkeypatch.setattr(QUALIFICATION, "_generated_commands", _validate_candidate_outputs)
    with pytest.raises(QUALIFICATION.QualificationError, match="modified commit contains code"):
        QUALIFICATION._check_source_delta(root, stock, modified, assets)



def test_prepare_build_refreshes_ignored_projections_for_each_checked_commit(tmp_path, monkeypatch):
    root, stock, modified, _assets = _candidate_repo(tmp_path)
    projection = root / "manifests/desktops/yellowfin-gnome.yaml"
    calls = 0

    def generate(root_path, argv, _what):
        assert argv[2] == "generate-all"
        target = root_path / "manifests/desktops/yellowfin-gnome.yaml"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(digest((root_path / "tunaos.toml").read_bytes()), encoding="utf-8")

    def check(root_path, mode):
        nonlocal calls
        assert mode == "check"
        calls += 1
        if calls % 2 == 0:
            expected = digest((root_path / "tunaos.toml").read_bytes())
            assert projection.read_text(encoding="utf-8") == expected

    monkeypatch.setattr(QUALIFICATION, "run", generate)
    monkeypatch.setattr(QUALIFICATION, "_generated_commands", check)
    subprocess.run(["git", "checkout", "--quiet", "--detach", stock], cwd=root, check=True)
    assert QUALIFICATION.prepare_build(root, stock) == stock
    stock_projection = projection.read_text(encoding="utf-8")
    subprocess.run(["git", "checkout", "--quiet", "--detach", modified], cwd=root, check=True)
    assert projection.read_text(encoding="utf-8") == stock_projection
    assert QUALIFICATION.prepare_build(root, modified) == modified
    assert projection.read_text(encoding="utf-8") == digest((root / "tunaos.toml").read_bytes())
    assert projection.read_text(encoding="utf-8") != stock_projection


def _write_plan(tmp_path: Path) -> tuple[dict, Path]:
    value = plan()
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    return value, path


def _source_evidence(value: dict) -> dict:
    return {
        "stockCommit": value["stockCommit"],
        "modifiedCommit": value["modifiedCommit"],
        "stockConfigSha256": value["stockConfigSha256"],
        "modifiedConfigSha256": value["modifiedConfigSha256"],
        "stockAdapterSha256": value["stockAdapterSha256"],
        "modifiedAdapterSha256": value["modifiedAdapterSha256"],
        "changedPaths": value["changedPaths"],
    }


def test_harness_source_error_emits_failed_source_and_not_run_families(tmp_path, monkeypatch):
    value, plan_path = _write_plan(tmp_path)

    def fail_source(*_args):
        raise QUALIFICATION._HARNESS.QualificationError("source unavailable")

    monkeypatch.setattr(QUALIFICATION, "_source_record", fail_source)
    report, passed = QUALIFICATION.qualify(plan_path, tmp_path / "source", tmp_path / "evidence")
    assert not passed
    assert report["sourceGate"]["status"] == "failed"
    assert [item["status"] for item in report["families"]] == ["not-run", "not-run"]


def test_harness_base_probe_error_emits_failed_family(tmp_path, monkeypatch):
    value, plan_path = _write_plan(tmp_path)
    monkeypatch.setattr(QUALIFICATION, "_source_record", lambda *_: _source_evidence(value))

    def fail_base(*_args):
        raise QUALIFICATION._HARNESS.QualificationError("base probe failed")

    monkeypatch.setattr(QUALIFICATION._HARNESS, "verify_base_source", fail_base)
    report, passed = QUALIFICATION.qualify(plan_path, tmp_path / "source", tmp_path / "evidence")
    assert not passed
    assert report["families"][0]["status"] == "failed"
    assert "base probe failed" in report["families"][0]["reason"]


def test_harness_cell_error_emits_failed_family(tmp_path, monkeypatch):
    value, plan_path = _write_plan(tmp_path)
    source = tmp_path / "source"
    source.mkdir()
    monkeypatch.setattr(QUALIFICATION, "_source_record", lambda *_: _source_evidence(value))
    monkeypatch.setattr(QUALIFICATION._HARNESS, "verify_base_source",
                        lambda _log, reference: reference.rsplit("@", 1)[1])

    def fail_image(*_args):
        raise QUALIFICATION._HARNESS.CellError("image missing", [])

    monkeypatch.setattr(QUALIFICATION, "_image_record", fail_image)
    report, passed = QUALIFICATION.qualify(plan_path, source, tmp_path / "evidence")
    assert not passed
    assert report["families"][0]["status"] == "failed"
    assert "image missing" in report["families"][0]["reason"]
    assert report["families"][0]["baseDigest"] == value["families"][0]["baseImage"].rsplit("@", 1)[1]

def test_plan_rejects_code_change_even_when_all_image_evidence_is_present():
    value = plan()
    value["changedPaths"].append("scripts/build-image-inner.sh")
    value["changedPaths"].sort()
    with pytest.raises(QUALIFICATION.QualificationError, match="changedPaths"):
        QUALIFICATION.validate_plan(value)



def test_generated_base_image_records_keep_their_config_digest_and_pass_gate(tmp_path, monkeypatch):
    value = plan()
    cell = value["families"][0]
    ref_roles = {ref: role for role, ref in cell["images"].items()}
    image_roles = {}

    def local_image(_log, ref):
        image_id = digest(ref.encode()).removeprefix("sha256:")
        image_roles[image_id] = ref_roles[ref]
        return {"imageId": image_id}

    monkeypatch.setattr(QUALIFICATION._HARNESS, "local_image", local_image)
    monkeypatch.setattr(QUALIFICATION._HARNESS, "image_identity", lambda *_: {
        "manifestDigest": digest(b"manifest"), "configDigest": digest(b"config"),
        "platform": QUALIFICATION.PLATFORM,
    })
    monkeypatch.setattr(QUALIFICATION._HARNESS, "read_image_info", lambda *_: {})
    monkeypatch.setattr(QUALIFICATION._HARNESS, "verify_info", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(QUALIFICATION, "git", lambda _root, *_args: _args[-1][:7])
    monkeypatch.setattr(QUALIFICATION, "_resolve_image_flavor", lambda _root, _variant, public: (
        cell["imageFlavors"]["stockBase" if public == "base" else "stockDesktop"]
    ))

    def package_query(_log, _manager, image_id, _package):
        status = 1 if image_roles[image_id] == "stockBase" else 0
        return subprocess.CompletedProcess([], status, b"" if status else b"installed", b"")

    def receipt(_log, image_id):
        role = image_roles[image_id]
        if role.startswith("stock"):
            return subprocess.CompletedProcess([], 1, b"", b"")
        raw = (f"# Written by build_scripts/lib/image-packages.sh for "
               f"{cell['variant']} ({cell['manager']}).\nrequired\t{cell['package']}\n").encode()
        return subprocess.CompletedProcess([], 0, raw, b"")

    def podman(_log, _image_id, _entrypoint, path):
        if path == "/etc/os-release":
            raw = (f'HOME_URL="{value["expectedBrand"]["homepage"]}"\n'
                   f'PRETTY_NAME="{cell["variant"].capitalize()}"\n').encode()
        elif path == "/usr/share/plasma/look-and-feel/org.tunaos.desktop/metadata.json":
            raw = value["expectedBrand"]["projectName"].encode()
        else:
            asset = "system_files" + path
            raw = (QUALIFICATION.ASSET_FIXTURE / Path(asset).name).read_bytes()
        return subprocess.CompletedProcess([], 0, raw, b"")

    monkeypatch.setattr(QUALIFICATION._HARNESS, "package_query", package_query)
    monkeypatch.setattr(QUALIFICATION._HARNESS, "receipt", receipt)
    monkeypatch.setattr(QUALIFICATION._HARNESS, "podman", podman)
    monkeypatch.setattr(QUALIFICATION, "_plymouth_observation", lambda *_args: {
        "status": "passed", "configuredTheme": QUALIFICATION.PLYMOUTH_THEME,
        "defaultThemeLinkTarget": f"{QUALIFICATION.PLYMOUTH_THEME}/{QUALIFICATION.PLYMOUTH_THEME}.plymouth",
        "scriptPlugin": "/usr/lib64/plymouth/script.so",
        "checks": {"configuredTheme": True, "defaultThemeLink": True, "scriptPlugin": True},
        "reason": None,
    })

    produced = [
        QUALIFICATION._image_record(value, cell, role, tmp_path, object())
        for role in ("stockBase", "modifiedBase")
    ]
    assert [record["configSha256"] for record in produced] == [
        value["stockConfigSha256"], value["modifiedConfigSha256"],
    ]
    report = passed_report(value)
    by_role = {record["role"]: record for record in report["families"][0]["images"]}
    by_role.update({record["role"]: record for record in produced})
    report["families"][0]["images"] = [by_role[role] for role in QUALIFICATION.ROLES]
    plan_path, report_path = write_pair(tmp_path, value, report)
    QUALIFICATION.gate(plan_path, report_path)

 
def test_gate_accepts_only_complete_matching_rpm_and_apt_evidence(tmp_path):
    value = plan()
    report = passed_report(value)
    plan_path, report_path = write_pair(tmp_path, value, report)
    QUALIFICATION.gate(plan_path, report_path)


@pytest.mark.parametrize("mutation", [
    "stale-plan",
    "source-commit",
    "base-digest",
    "double-family-base-digest",
    "package-receipt-hash",
    "package-inventory-hash",
    "package-inventory-payload",
    "adapter-digest",
    "package-receipt-content",
    "brand-marker",
    "plymouth-default-unselected",
    "plymouth-config-mismatch",
    "plymouth-plugin-missing",
    "stock-parity",
    "not-run-family",
])
def test_gate_fails_closed_for_stale_mismatched_or_not_run_evidence(tmp_path, mutation):
    value = plan()
    report = passed_report(value)
    if mutation == "stale-plan":
        value["modifiedConfigSha256"] = digest(b"different fork TOML")
    elif mutation == "source-commit":
        report["families"][0]["images"][2]["sourceCommit"] = "3" * 40
    elif mutation == "base-digest":
        report["families"][0]["images"][0]["baseDigest"] = "sha256:" + "f" * 64
    elif mutation == "double-family-base-digest":
        report["families"][0]["baseDigest"] = "sha256:" + report["families"][0]["baseDigest"]
    elif mutation == "package-receipt-hash":
        report["families"][0]["images"][2]["packageReceiptSha256"] = "sha256:" + "f" * 64
    elif mutation == "package-receipt-content":
        report["families"][1]["images"][3]["packageReceipt"] = "required\ttree\n"
    elif mutation == "package-inventory-hash":
        report["families"][0]["stockParity"]["stockInventorySha256"] = "sha256:" + "f" * 64
    elif mutation == "package-inventory-payload":
        report["families"][1]["stockParity"]["customInventoryReceipt"] = "{}"
    elif mutation == "adapter-digest":
        report["sourceGate"]["evidence"]["modifiedAdapterSha256"] = "sha256:" + "f" * 64
    elif mutation == "brand-marker":
        report["families"][1]["images"][3]["branding"]["homeUrl"] = "https://stale.example"
    elif mutation == "plymouth-default-unselected":
        report["families"][1]["images"][3]["branding"]["plymouth"]["defaultThemeLinkTarget"] = \
            "tunaos/tunaos.plymouth"
    elif mutation == "plymouth-config-mismatch":
        report["families"][1]["images"][3]["branding"]["plymouth"]["configuredTheme"] = "tunaos"
    elif mutation == "plymouth-plugin-missing":
        report["families"][1]["images"][3]["branding"]["plymouth"]["scriptPlugin"] = None
    elif mutation == "stock-parity":
        report["families"][0]["stockParity"]["status"] = "not-run"
    else:
        report["families"][1]["status"] = "not-run"
    plan_path, report_path = write_pair(tmp_path, value, report)
    with pytest.raises(QUALIFICATION.QualificationError):
        QUALIFICATION.gate(plan_path, report_path)


def test_workflow_is_manual_read_only_and_never_authenticates_or_publishes():
    path = ROOT / ".github/workflows/qualify-config-only-images.yml"
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    triggers = document.get("on", document.get(True))
    assert set(triggers) == {"workflow_dispatch"}
    assert document["permissions"] == {"contents": "read"}
    assert set(document["jobs"]) == {"qualify"}
    assert document["jobs"]["qualify"]["env"]["TUNAOS_BUILD_CONFIG"] == ""
    build_step = next(step for step in document["jobs"]["qualify"]["steps"]
                      if step.get("id") == "build")
    build_script = build_step["run"]
    assert build_script.index('git checkout --quiet --detach "$commit"') < \
        build_script.index("prepare-build") < build_script.index('"$just" build')
    assert '--source "$PWD" --commit "$commit"' in build_script
    body = path.read_text(encoding="utf-8").lower()
    assert "${{ secrets." not in body
    assert "packages: write" not in body
    assert "docker/login-action" not in body
    for forbidden in ("podman push", "buildah push", "skopeo copy", "podman login", "aws s3", "rclone"):
        assert forbidden not in body


def test_workflow_artifact_retains_only_small_machine_readable_evidence():
    path = ROOT / ".github/workflows/qualify-config-only-images.yml"
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    steps = document["jobs"]["qualify"]["steps"]
    uploads = [step for step in steps if step.get("uses", "").startswith("actions/upload-artifact@")]
    assert len(uploads) == 1
    upload = uploads[0]
    assert upload["if"] == "always()"
    assert upload["with"]["retention-days"] == 30
    assert upload["with"]["path"].splitlines() == [
        "${{ runner.temp }}/config-only-image-plan.json",
        "${{ runner.temp }}/config-only-image-evidence/report.json",
    ]
