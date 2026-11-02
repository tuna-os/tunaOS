"""Exercise exact reference selection and retained OCI bytes, never VM claims."""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import resource
import subprocess
import sys
import tarfile

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/config-reference-materialization.py"
SPEC = importlib.util.spec_from_file_location("reference_materialization", SCRIPT)
MATERIAL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MATERIAL)
FIXTURE_SPEC = importlib.util.spec_from_file_location(
    "reference_conformance_fixture", ROOT / "tests/test_config_only_image_qualification.py"
)
CONFORMANCE = importlib.util.module_from_spec(FIXTURE_SPEC)
FIXTURE_SPEC.loader.exec_module(CONFORMANCE)
plan = CONFORMANCE.plan


def encoded(value):
    return json.dumps(value, sort_keys=True).encode()


def digest(raw):
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def archive_fixture(tmp_path, change=None):
    # These are explicit public test bytes, not a substituted VM/image result.
    config = encoded({"os": "linux", "architecture": "amd64"})
    layer = b"public materialization fixture layer\n"
    descriptor = lambda raw: {"digest": digest(raw), "size": len(raw)}
    manifest = encoded({"schemaVersion": 2, "config": descriptor(config), "layers": [descriptor(layer)]})
    files = {
        "oci-layout": encoded({"imageLayoutVersion": "1.0.0"}),
        "index.json": encoded({"schemaVersion": 2, "manifests": [descriptor(manifest)]}),
        "blobs/sha256/" + digest(manifest)[7:]: manifest,
        "blobs/sha256/" + digest(config)[7:]: config,
        "blobs/sha256/" + digest(layer)[7:]: layer,
    }
    if change:
        change(files)
    target = tmp_path / MATERIAL.ARCHIVE
    with tarfile.open(target, "w") as archive:
        for name, raw in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(raw)
            archive.addfile(info, io.BytesIO(raw))
    return target, {"manifestDigest": digest(manifest), "configDigest": digest(config),
                    "role": "modifiedDesktop", "platform": "linux/amd64",
                    "sourceCommit": "2" * 40, "configSha256": digest(b"config")}


def receipt_fixture(tmp_path):
    archive, image = archive_fixture(tmp_path)
    receipt = {
        "purpose": "reference-image-materialization-only", "family": "rpm",
        "variant": "yellowfin", "desktop": "gnome", "platform": "linux/amd64",
        "modifiedCommit": image["sourceCommit"], "configSha256": image["configSha256"],
        "image": image, "desktopArchive": MATERIAL.verify_archive(archive, image),
    }
    path = tmp_path / "materialization.json"
    path.write_bytes(encoded(receipt))
    return path, archive, receipt


@pytest.mark.parametrize("family,variant", [("rpm", "yellowfin"), ("apt", "grouper")])
def test_selects_only_customized_desktop_from_unchanged_conformance_plan(family, variant):
    value = plan()
    original = copy.deepcopy(value)
    build = MATERIAL.selected_build(value, family)
    assert (build["variant"], build["role"], build["flavor"], build["commit"]) == (
        variant, "modifiedDesktop", "gnome", value["modifiedCommit"])
    assert value == original  # Original eight-image source/conformance contract is untouched.


@pytest.mark.parametrize("change", [
    lambda p: p["builds"].pop(3),
    lambda p: p["builds"][3].update(commit=p["stockCommit"]),
    lambda p: p["builds"][3].update(chain="docker.io/example/other:latest"),
    lambda p: p.update(platform="linux/arm64"),
])
def test_rejects_wrong_or_partial_build_selection(change):
    value = plan()
    change(value)
    with pytest.raises((ValueError, MATERIAL.RECIPE.QualificationError)):
        MATERIAL.selected_build(value, "rpm")


def test_rejects_unsupported_family():
    with pytest.raises(ValueError, match="family"):
        MATERIAL.selected_build(plan(), "other")


def test_checks_archive_bytes_and_identity_without_extracting(tmp_path):
    archive, image = archive_fixture(tmp_path)
    result = MATERIAL.verify_archive(archive, image)
    assert result["sha256"] == digest(archive.read_bytes())
    assert result["manifestDigest"] == image["manifestDigest"]
    assert result["configDigest"] == image["configDigest"]
    assert result["sizeBytes"] == archive.stat().st_size
    assert sorted(path.name for path in tmp_path.iterdir()) == [MATERIAL.ARCHIVE]


@pytest.mark.parametrize("identity", ["manifestDigest", "configDigest"])
def test_rejects_archive_for_other_image(tmp_path, identity):
    archive, image = archive_fixture(tmp_path)
    image[identity] = "sha256:" + "0" * 64
    with pytest.raises(ValueError, match="identity changed"):
        MATERIAL.verify_archive(archive, image)


@pytest.mark.parametrize("change,reason", [
    (lambda f: f.update({next(p for p in f if f[p].startswith(b"public")): b"corrupt"}), "size mismatch"),
    (lambda f: f.update({next(p for p in f if f[p].startswith(b"public")): b"x" * len(next(v for v in f.values() if v.startswith(b"public")))}), "blob hash"),
    (lambda f: f.pop(next(p for p in f if f[p].startswith(b"public"))), "size mismatch"),
    (lambda f: f.update({"../escape": b"no"}), "unsafe"),
    (lambda f: f.update({"/absolute": b"no"}), "unsafe"),
    (lambda f: f.update({"oci-layout": b"{}"}), "layout"),
    (lambda f: f.update({"index.json": b'{"schemaVersion":2,"manifests":[]}'}), "one image"),
    (lambda f: f.update({"index.json": b'{"schemaVersion":2,"manifests":[{"digest":42,"size":1}]}'}), "descriptor digest"),
    (lambda f: f.update({"index.json": b'{"schemaVersion":2,"schemaVersion":2,"manifests":[]}'}), "duplicate"),
])
def test_refuses_corrupt_unsafe_or_ambiguous_archive(tmp_path, change, reason):
    archive, image = archive_fixture(tmp_path, change)
    with pytest.raises(ValueError, match=reason):
        MATERIAL.verify_archive(archive, image)


def test_rejects_links_and_duplicate_tar_members(tmp_path):
    archive, image = archive_fixture(tmp_path)
    with tarfile.open(archive, "a") as stream:
        info = tarfile.TarInfo("link")
        info.type = tarfile.SYMTYPE
        info.linkname = "/etc/passwd"
        stream.addfile(info)
    with pytest.raises(ValueError, match="links"):
        MATERIAL.verify_archive(archive, image)
    archive, image = archive_fixture(tmp_path)
    with tarfile.open(archive, "a") as stream:
        info = tarfile.TarInfo("index.json")
        info.size = 2
        stream.addfile(info, io.BytesIO(b"{}"))
    with pytest.raises(ValueError, match="duplicate"):
        MATERIAL.verify_archive(archive, image)


def test_real_cli_verifies_bound_materialization_and_rejects_receipt_tampering(tmp_path):
    receipt, archive, _ = receipt_fixture(tmp_path)
    command = [sys.executable, str(SCRIPT), "verify", "--receipt", str(receipt),
               "--archive", str(archive), "--receipt-sha256", digest(receipt.read_bytes())]
    passed = subprocess.run(command, capture_output=True, text=True)
    assert passed.returncode == 0, passed.stderr
    assert json.loads(passed.stdout)["sha256"] == digest(archive.read_bytes())
    receipt.write_bytes(receipt.read_bytes() + b" ")
    failed = subprocess.run(command, capture_output=True, text=True)
    assert failed.returncode == 2
    assert "independently recorded SHA-256" in failed.stderr


@pytest.mark.parametrize("change", [
    lambda r: r.update(purpose="qualification-pass"),
    lambda r: r.update(variant="skipjack"),
    lambda r: r.update(modifiedCommit="1" * 40),
    lambda r: r["desktopArchive"].update(sha256="sha256:" + "0" * 64),
])
def test_refuses_mismatched_receipt_even_when_receipt_hash_matches(tmp_path, change):
    receipt_path, archive, receipt = receipt_fixture(tmp_path)
    change(receipt)
    receipt_path.write_bytes(encoded(receipt))
    with pytest.raises(ValueError):
        MATERIAL.verify_materialization(receipt_path, archive, digest(receipt_path.read_bytes()))


def test_real_prepare_smoke_uses_primary_recipe_without_building_images(tmp_path):
    checkout = tmp_path / "source"
    subprocess.run(["git", "clone", "--quiet", "--shared", "--no-checkout", str(ROOT), str(checkout)], check=True)
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    subprocess.run(["git", "checkout", "--quiet", "--detach", head], cwd=checkout, check=True)
    selected = subprocess.run([
        sys.executable, str(SCRIPT), "prepare", "--family", "rpm", "--source", str(checkout),
        "--plan", str(tmp_path / "plan.json"),
    ], capture_output=True, text=True)
    assert selected.returncode == 0, selected.stderr
    build = json.loads(selected.stdout)
    value = json.loads((tmp_path / "plan.json").read_bytes())
    assert build["role"] == "modifiedDesktop" and build["family"] == "rpm"
    assert value["stockCommit"] == head and value["modifiedCommit"] != head
    assert len(value["builds"]) == 8  # Input plan is not narrowed or mislabeled a conformance pass.
    assert MATERIAL.selected_build(value, "apt")["variant"] == "grouper"
    assert subprocess.check_output(["git", "status", "--porcelain"], cwd=checkout) == b""


@pytest.mark.parametrize("image", [None, {}, {"manifestDigest": 42, "configDigest": "sha256:" + "0" * 64}])
def test_refuses_missing_immutable_archive_identity(tmp_path, image):
    archive, _ = archive_fixture(tmp_path)
    with pytest.raises(ValueError, match="identity|digest"):
        MATERIAL.verify_archive(archive, image)


@pytest.mark.parametrize("same_size", [True, False])
def test_real_cli_authenticates_archive_before_oversized_pax_parsing(tmp_path, same_size):
    receipt, archive, _ = receipt_fixture(tmp_path)
    original_size = archive.stat().st_size
    header = tarfile.TarInfo("untrusted-pax")
    header.type = tarfile.XHDTYPE
    header.size = 1 << 40
    # Actual malformed tar bytes: a 1 TiB PAX claim in a tiny replacement file.
    # The same-size case forces whole-file authentication, not just stat().
    raw_header = header.tobuf(format=tarfile.GNU_FORMAT)
    assert len(raw_header) == 512
    archive.write_bytes(raw_header + b"\0" * ((original_size if same_size else 1024) - len(raw_header)))

    def bound_parser_process():
        resource.setrlimit(resource.RLIMIT_AS, (256 * 1024 * 1024, 256 * 1024 * 1024))

    result = subprocess.run([
        sys.executable, str(SCRIPT), "verify", "--receipt", str(receipt),
        "--archive", str(archive), "--receipt-sha256", digest(receipt.read_bytes()),
    ], capture_output=True, text=True, timeout=10, preexec_fn=bound_parser_process)
    assert result.returncode == 2, result.stderr
    expected = "retained byte hash" if same_size else "retained byte size"
    assert expected in result.stderr
    assert "Traceback" not in result.stderr and "MemoryError" not in result.stderr


@pytest.mark.parametrize("size,sha256", [
    (True, "sha256:" + "0" * 64),
    (0, "sha256:" + "0" * 64),
    (-1, "sha256:" + "0" * 64),
    (10240, 42),
    (10240, "not-a-digest"),
])
def test_refuses_malformed_authenticated_archive_record(tmp_path, size, sha256):
    receipt_path, archive, receipt = receipt_fixture(tmp_path)
    receipt["desktopArchive"].update(sizeBytes=size, sha256=sha256)
    receipt_path.write_bytes(encoded(receipt))
    with pytest.raises(ValueError, match="invalid retained size or SHA-256"):
        MATERIAL.verify_materialization(receipt_path, archive, digest(receipt_path.read_bytes()))
