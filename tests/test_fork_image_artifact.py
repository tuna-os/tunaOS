"""Exact original-image transport contracts; fixtures do not prove native builds."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import stat
import subprocess
import zipfile

import pytest
import yaml

from tests.test_fork_source_export import EXPORT, make_layout

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("image_artifact", ROOT / "scripts/fork-image-artifact.py")
ARTIFACT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ARTIFACT)
IDENTITY = {"repository": ARTIFACT.REPOSITORY, "run_id": 123, "head_sha": "a" * 40, "build_sha": "b" * 40}


def source_receipt(files=None, modes=None):
    files = files or {"scripts/fork-install-observer.py": "1" * 64, "scripts/qualify-fork-install.py": "2" * 64,
                      "scripts/fork-image-artifact.py": "3" * 64, "Containerfile.el10": "4" * 64}
    payload = {"files": files, "modes": modes or dict.fromkeys(files, "100644")}
    return {**payload, "sha256": hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()}


def make_evidence(root, variant):
    path = root / variant
    layout = path / "oci-export/source"
    raw, image_id, _ = make_layout(layout)
    source = source_receipt()
    manifest = {"schema_version": 1, "variant": variant, "flavor": "gnome", "platform": "linux/amd64",
                "image": {"registry": "localhost", "namespace": "fork-qualification"},
                "sources": {"sha256": source["sha256"]},
                "assets": {"wallpaper": {"sha256": hashlib.sha256(b"wallpaper").hexdigest()}}}
    manifest_path = path / ARTIFACT.manifest_name(variant)
    manifest_path.parent.mkdir(parents=True)
    ARTIFACT.write(manifest_path, manifest)
    (path / "wallpaper.jpg").write_bytes(b"wallpaper")
    ARTIFACT.write(path / "prepared/source-receipt.json", source)
    receipt = {"schema_version": 1, "target_imgref": ARTIFACT.target(variant), "preserved_digest": True,
               "original_local_imgref": "containers-storage:" + ARTIFACT.target(variant),
               "source_manifest_digest": EXPORT.sha(raw), "source_image_id": image_id,
               "source_receipt": manifest["sources"], "fork_manifest_sha256": ARTIFACT.sha(manifest_path),
               "verified_oci": EXPORT.verify_layout(layout, "linux/amd64", EXPORT.sha(raw), image_id)}
    ARTIFACT.write(path / "oci-export/source-receipt.json", receipt)
    (path / "oci-export/source-manifest.json").write_bytes(raw)
    report = {"variant": variant, **dict.fromkeys(ARTIFACT.STAGES, "passed"),
              "login": "not-run", "installed_proof": "not-run",
              "target_observer": {"scope": "qualification-only-read-only-serial", "maximum_seconds": 3600,
                                  "observer_sha256": source["files"]["scripts/fork-install-observer.py"], "unit_sha256": "5" * 64}}
    ARTIFACT.write(path / "qualification.json", report)
    return path


@pytest.fixture
def bundle(tmp_path):
    evidence, output = tmp_path / "evidence", tmp_path / "bundles"
    for variant in ARTIFACT.VARIANTS:
        make_evidence(evidence, variant)
    result = ARTIFACT.package(evidence, output, IDENTITY)
    selection = {"run_id": IDENTITY["run_id"], "head_sha": IDENTITY["head_sha"], "images": {}}
    for index, variant in enumerate(ARTIFACT.VARIANTS):
        selection["images"][variant] = {"artifact_id": 456 + index, "archive_sha256": "sha256:" + "6" * 64,
            "manifest_digest": result[variant]["source_manifest_digest"], "config_digest": result[variant]["source_image_id"]}
    return evidence, output, selection


def test_package_and_reuse_keep_old_receipt_bytes_and_separate_harness(bundle, tmp_path, monkeypatch):
    evidence, output, selection = bundle
    original = source_receipt()
    changed_files = {**original["files"], "scripts/qualify-fork-install.py": "7" * 64}
    current = source_receipt(changed_files)
    for variant in ARTIFACT.VARIANTS:
        record, saved = ARTIFACT.verify_bundle(output / variant, variant, selection)
        assert saved == original and record["build_sha"] == IDENTITY["build_sha"]
        for relative in ("oci-export/source-receipt.json", "prepared/source-receipt.json", ARTIFACT.manifest_name(variant)):
            assert (output / variant / relative).read_bytes() == (evidence / variant / relative).read_bytes()
    monkeypatch.setattr(ARTIFACT.COMPILER, "source_receipt", lambda root: current)
    monkeypatch.setattr(subprocess, "check_output", lambda *a, **kw: "c" * 40 + "\n")
    def download(pins, variant, destination):
        shutil.copytree(output / variant, destination)
        return {"run_status": "completed", "run_conclusion": "failure"}
    monkeypatch.setattr(ARTIFACT, "download", download)
    imported = []
    monkeypatch.setattr(ARTIFACT, "import_original", lambda root, variant, record: imported.append(variant))
    restored = ARTIFACT.restore(selection, tmp_path / "restored")
    assert imported == list(ARTIFACT.VARIANTS)
    for record in restored.values():
        assert record["original_source_sha256"] == original["sha256"]
        assert record["harness_source_sha256"] == current["sha256"]
        assert record["harness_sha"] == "c" * 40 and record["original_build_sha"] == "b" * 40
        assert record["changed_harness_inputs"] == ["scripts/qualify-fork-install.py"]
        assert record["login"] == record["installed_proof"] == "not-run"
        assert record["run_conclusion"] == "failure"


@pytest.mark.parametrize("name", ["scripts/fork-install-observer.py", "scripts/export-fork-source.py",
    "scripts/qualify-fork-image.py", "scripts/resolve-fork-config.py", "Containerfile.el10",
    "manifests/desktops/gnome.yaml", "system_files/usr/share/example", "scripts/other-new-file.py"])
def test_image_affecting_change_forces_rebuild(name):
    original = source_receipt()
    current = source_receipt({**original["files"], name: "8" * 64})
    with pytest.raises(ValueError, match="rebuild required"):
        ARTIFACT.harness_changes(original, current)


@pytest.mark.parametrize("operation", ["delete", "new", "mode", "symlink"])
def test_harness_path_or_mode_changes_are_not_silently_allowed(operation):
    original = source_receipt()
    files, modes = copy.deepcopy(original["files"]), copy.deepcopy(original["modes"])
    name = "scripts/qualify-fork-install.py"
    if operation == "delete":
        del files[name]
        del modes[name]
    elif operation == "new":
        files["scripts/fork-installer-ui.py"] = "8" * 64
        modes["scripts/fork-installer-ui.py"] = "100644"
    else:
        modes[name] = "120000" if operation == "symlink" else "100755"
    with pytest.raises(ValueError, match="rebuild required"):
        ARTIFACT.harness_changes(original, source_receipt(files, modes))


def test_producer_never_stages_guest_secrets_or_unreferenced_blobs(bundle, tmp_path):
    evidence, _, _ = bundle
    for variant in ARTIFACT.VARIANTS:
        root = evidence / variant
        (root / "installed-proof").mkdir()
        (root / "installed-proof/password").write_text("private")
        (root / "oci-export/source/blobs/sha256" / ("f" * 64)).write_text("unreferenced")
    output = tmp_path / "clean"
    ARTIFACT.package(evidence, output, IDENTITY)
    names = [p.relative_to(output).as_posix() for p in output.rglob("*")]
    assert not any("private" in name or "password" in name or "f" * 64 in name for name in names)


@pytest.mark.parametrize("corruption", ["failed-stage", "observer", "wallpaper", "manifest", "source-receipt", "symlink", "oversize"])
def test_bad_original_pair_fails_before_staging(bundle, tmp_path, monkeypatch, corruption):
    evidence, _, _ = bundle
    root = evidence / "grouper"
    if corruption in {"failed-stage", "observer"}:
        report = ARTIFACT.read(root / "qualification.json")
        if corruption == "failed-stage":
            report["boot"] = "failed"
        else:
            report["target_observer"]["observer_sha256"] = "9" * 64
        ARTIFACT.write(root / "qualification.json", report)
    elif corruption == "wallpaper":
        (root / "wallpaper.jpg").write_bytes(b"changed wallpaper")
    elif corruption == "manifest":
        path = root / ARTIFACT.manifest_name("grouper")
        path.write_text(path.read_text() + "\n")
    elif corruption == "source-receipt":
        source = ARTIFACT.read(root / "prepared/source-receipt.json")
        source["files"]["Containerfile.el10"] = "8" * 64
        ARTIFACT.write(root / "prepared/source-receipt.json", source)
    elif corruption == "oversize":
        monkeypatch.setattr(ARTIFACT, "LIMIT", 1)
    else:
        path = root / "wallpaper.jpg"
        path.unlink()
        path.symlink_to(evidence / "yellowfin/wallpaper.jpg")
    with pytest.raises(ValueError):
        ARTIFACT.package(evidence, tmp_path / "refused", IDENTITY)
    assert not (tmp_path / "refused").exists()


@pytest.mark.parametrize("corruption", ["extra", "blob", "pin", "head", "stage", "inventory", "observer", "observer-extra", "observer-scope", "observer-duration", "observer-unit", "bundle-extra"])
def test_corrupt_bundle_is_rejected(bundle, corruption):
    _, output, selection = bundle
    root = output / "yellowfin"
    record = ARTIFACT.read(root / "bundle.json")
    if corruption == "extra":
        (root / "secret.key").write_text("private")
    elif corruption == "blob":
        next((root / "oci-export/source/blobs/sha256").iterdir()).write_bytes(b"changed")
    elif corruption == "pin":
        selection["images"]["yellowfin"]["config_digest"] = "sha256:" + "f" * 64
    elif corruption == "head":
        record["head_sha"] = "e" * 40
    elif corruption == "stage":
        record["passed_original_stages"].remove("boot")
    elif corruption == "inventory":
        del record["files"]["wallpaper.jpg"]
    elif corruption == "observer-extra":
        record["target_observer"]["private_key"] = "must not be accepted"
    elif corruption == "observer-scope":
        record["target_observer"]["scope"] = "other"
    elif corruption == "observer-duration":
        record["target_observer"]["maximum_seconds"] = 999999
    elif corruption == "observer-unit":
        record["target_observer"]["unit_sha256"] = "invalid"
    elif corruption == "bundle-extra":
        record["private_key"] = "must not be accepted"
    else:
        record["target_observer"]["observer_sha256"] = "e" * 64
    ARTIFACT.write(root / "bundle.json", record)
    with pytest.raises(ValueError):
        ARTIFACT.verify_bundle(root, "yellowfin", selection)


def metadata(selection):
    pin = selection["images"]["yellowfin"]
    artifact = {"id": pin["artifact_id"], "name": ARTIFACT.artifact_name(selection["run_id"], "yellowfin"),
                "expired": False, "digest": pin["archive_sha256"], "size_in_bytes": 1234,
                "workflow_run": {"id": selection["run_id"], "head_sha": selection["head_sha"]}}
    run = {"id": selection["run_id"], "head_sha": selection["head_sha"], "path": ARTIFACT.WORKFLOW,
           "repository": {"full_name": ARTIFACT.REPOSITORY}, "event": "pull_request",
           "status": "completed", "conclusion": "failure"}
    return artifact, run


def test_failed_later_proof_does_not_invalidate_original_producer(bundle):
    _, _, selection = bundle
    artifact, run = metadata(selection)
    assert ARTIFACT.validate_metadata(artifact, run, selection, "yellowfin")["run_conclusion"] == "failure"


@pytest.mark.parametrize("corruption", ["expired", "id", "digest", "head", "run", "repository", "workflow", "running", "cancelled", "size"])
def test_artifact_provenance_must_match_explicit_immutable_pins(bundle, corruption):
    _, _, selection = bundle
    artifact, run = metadata(selection)
    if corruption == "expired":
        artifact["expired"] = True
    elif corruption in {"id", "digest"}:
        artifact[corruption] = "different"
    elif corruption == "head":
        artifact["workflow_run"]["head_sha"] = "e" * 40
    elif corruption == "run":
        artifact["workflow_run"]["id"] += 1
    elif corruption == "repository":
        run["repository"]["full_name"] = "other/repository"
    elif corruption == "workflow":
        run["path"] = ".github/workflows/build-image.yml"
    elif corruption == "running":
        run["status"] = "in_progress"
    elif corruption == "cancelled":
        run["conclusion"] = "cancelled"
    else:
        artifact["size_in_bytes"] = ARTIFACT.ARCHIVE_LIMIT + 1
    with pytest.raises(ValueError):
        ARTIFACT.validate_metadata(artifact, run, selection, "yellowfin")


@pytest.mark.parametrize("member", ["../outside", "/outside", "oci-export/source/../password", "private/disk.qcow2", "password", "source.key"])
def test_zip_paths_fail_closed(tmp_path, member):
    archive = tmp_path / "archive.zip"
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr(member, b"private")
    with pytest.raises(ValueError, match="unapproved"):
        ARTIFACT.unpack(archive, tmp_path / "out", "yellowfin", ARTIFACT.sha(archive))
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize("kind", ["symlink", "duplicate", "oversize", "checksum"])
def test_zip_links_duplicates_size_and_checksum_fail_closed(tmp_path, monkeypatch, kind):
    archive = tmp_path / "archive.zip"
    with zipfile.ZipFile(archive, "w") as zipped:
        info = zipfile.ZipInfo("wallpaper.jpg")
        if kind == "symlink":
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
        zipped.writestr(info, b"123456789")
        if kind == "duplicate":
            with pytest.warns(UserWarning):
                zipped.writestr("wallpaper.jpg", b"other")
    expected = ARTIFACT.sha(archive)
    if kind == "oversize":
        monkeypatch.setattr(ARTIFACT, "LIMIT", 8)
    if kind == "checksum":
        expected = "sha256:" + "f" * 64
    with pytest.raises(ValueError):
        ARTIFACT.unpack(archive, tmp_path / "out", "yellowfin", expected)
    assert not (tmp_path / "out").exists()


def test_valid_zip_round_trip_preserves_every_original_byte(bundle, tmp_path):
    _, output, selection = bundle
    source = output / "yellowfin"
    archive = tmp_path / "archive.zip"
    with zipfile.ZipFile(archive, "w") as zipped:
        for path in source.rglob("*"):
            if path.is_file():
                zipped.write(path, path.relative_to(source))
    ARTIFACT.unpack(archive, tmp_path / "unpacked", "yellowfin", ARTIFACT.sha(archive))
    ARTIFACT.verify_bundle(tmp_path / "unpacked", "yellowfin", selection)
    for path in source.rglob("*"):
        if path.is_file():
            assert path.read_bytes() == (tmp_path / "unpacked" / path.relative_to(source)).read_bytes()


@pytest.mark.parametrize("corruption", ["missing-image", "extra-image", "latest", "short-sha", "same-artifact", "extra-key"])
def test_no_rolling_partial_or_fallback_pins(bundle, corruption):
    _, _, selection = bundle
    if corruption == "missing-image":
        del selection["images"]["grouper"]
    elif corruption == "extra-image":
        selection["images"]["albacore"] = selection["images"]["yellowfin"]
    elif corruption == "latest":
        selection["run_id"] = "latest"
    elif corruption == "short-sha":
        selection["head_sha"] = "1234567"
    elif corruption == "same-artifact":
        selection["images"]["grouper"]["artifact_id"] = selection["images"]["yellowfin"]["artifact_id"]
    else:
        selection["fallback"] = "build"
    with pytest.raises(ValueError):
        ARTIFACT.pins(selection)


def test_source_controlled_pins_default_disabled_and_workflow_stages_are_separate():
    selection = json.loads((ROOT / ".github/fork-image-reuse.json").read_text())
    if selection is not None:
        ARTIFACT.pins(selection)
    document = yaml.safe_load((ROOT / ARTIFACT.WORKFLOW).read_text())
    steps = document["jobs"]["canary"]["steps"]
    uploads = [s for s in steps if s.get("id") in {"yellowfin_image", "grouper_image"}]
    assert len(uploads) == 2
    for upload in uploads:
        assert upload["with"]["retention-days"] == 3
        assert upload["with"]["compression-level"] == 0
        assert upload["if"] == "steps.reuse.outputs.reuse == 'false'"
        assert "fork-original-images" in upload["with"]["path"]
    names = [s.get("name", "") for s in steps]
    assert names.index("Qualify RPM canary, then apt canary") < names.index("Upload original Yellowfin image")
    assert names.index("Upload original Grouper image") < names.index("Download frozen installer artifact")
    assert names.index("Install test tools") < names.index("Select explicit original-image pins")
    assert document["permissions"] == {"actions": "read", "contents": "read", "packages": "read"}
    assert "github.head_ref == 'feat/fork-image-qualification'" in document["jobs"]["canary"]["if"]
    triggers = document.get("on", document.get(True))
    assert ".github/fork-image-reuse.json" in triggers["pull_request"]["paths"]


@pytest.mark.parametrize("kind", ["metadata", "compression", "central-directory"])
def test_zip_rejects_excess_metadata_before_allocating_output(tmp_path, monkeypatch, kind):
    archive = tmp_path / "archive.zip"
    compression = zipfile.ZIP_BZIP2 if kind == "compression" else zipfile.ZIP_STORED
    with zipfile.ZipFile(archive, "w", compression=compression) as zipped:
        zipped.writestr("bundle.json", b"x" * 1024)
    if kind == "metadata":
        monkeypatch.setattr(ARTIFACT, "METADATA_LIMIT", 256)
    elif kind == "central-directory":
        import struct
        raw = bytearray(archive.read_bytes())
        end = raw.rfind(b"PK\x05\x06")
        struct.pack_into("<L", raw, end + 12, ARTIFACT.METADATA_LIMIT + 1)
        archive.write_bytes(raw)
    with pytest.raises(ValueError):
        ARTIFACT.unpack(archive, tmp_path / "out", "yellowfin", ARTIFACT.sha(archive))
    assert not (tmp_path / "out").exists()


def test_disabled_selection_is_explicit_without_implicit_lookup(tmp_path, monkeypatch):
    root = tmp_path / "checkout"
    (root / ".github").mkdir(parents=True)
    ARTIFACT.write(root / ".github/fork-image-reuse.json", None)
    monkeypatch.setattr(ARTIFACT, "ROOT", root)
    monkeypatch.delenv("FORK_REUSE_JSON", raising=False)
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / "outputs"))
    destination = tmp_path / "selection.json"
    ARTIFACT.select(destination)
    assert ARTIFACT.read(destination) is None
    assert (tmp_path / "outputs").read_text() == "reuse=false\n"


def test_real_compiler_receipt_and_generated_canary_manifest_round_trip(tmp_path):
    """Use the real compiler/asset shapes; OCI layers remain explicit fixtures."""
    from PIL import Image
    prepare = ARTIFACT.module("artifact_real_prepare", "prepare-fork-config.py")
    Image.new("RGB", (32, 32), "navy").save(tmp_path / "logo.png")
    Image.new("RGB", (1920, 1080), "#12394b").save(tmp_path / "wallpaper.jpg")
    original = ARTIFACT.COMPILER.source_receipt(ROOT)
    config = {"schema_version": 1, "catalog": {"sha256": original["sha256"]},
              "image": {"registry": "localhost", "namespace": "fork-qualification"},
              "targets": {"variants": list(ARTIFACT.VARIANTS), "flavors": ["gnome"], "platforms": ["linux/amd64"]},
              "global": {"branding": {"name": "Harbor Canary", "logo": "logo.png", "wallpaper": "wallpaper.jpg",
                                        "homepage": "https://example.org/harbor"}}}
    config_path = tmp_path / "fork.yaml"
    config_path.write_text(yaml.safe_dump(config))
    plan, cells, _ = prepare.compile_cells(config_path, identity_staging=True)
    assert plan["sources"] == original
    assert ARTIFACT.validate_receipt(original) == original["sha256"]
    evidence = tmp_path / "real-evidence"
    for cell in cells:
        manifest = cell["manifest"]
        variant = manifest["variant"]
        root = make_evidence(evidence, variant)
        # Match prepare()'s original manifest serialization exactly.
        path = root / ARTIFACT.manifest_name(variant)
        path.write_text(json.dumps(manifest, indent=2) + "\n")
        ARTIFACT.write(root / "prepared/source-receipt.json", original)
        (root / "wallpaper.jpg").write_bytes((tmp_path / "wallpaper.jpg").read_bytes())
        receipt = ARTIFACT.read(root / "oci-export/source-receipt.json")
        receipt.update(source_receipt=manifest["sources"], fork_manifest_sha256=ARTIFACT.sha(path))
        ARTIFACT.write(root / "oci-export/source-receipt.json", receipt)
        report = ARTIFACT.read(root / "qualification.json")
        report["target_observer"]["observer_sha256"] = original["files"]["scripts/fork-install-observer.py"]
        ARTIFACT.write(root / "qualification.json", report)
    output = tmp_path / "real-bundle"
    records = ARTIFACT.package(evidence, output, IDENTITY)
    selection = {"run_id": IDENTITY["run_id"], "head_sha": IDENTITY["head_sha"], "images": {
        variant: {"artifact_id": 400 + index, "archive_sha256": "sha256:" + "6" * 64,
                  "manifest_digest": records[variant]["source_manifest_digest"], "config_digest": records[variant]["source_image_id"]}
        for index, variant in enumerate(ARTIFACT.VARIANTS)}}
    for variant in ARTIFACT.VARIANTS:
        _, restored = ARTIFACT.verify_bundle(output / variant, variant, selection)
        assert restored == original
        assert ARTIFACT.harness_changes(restored, ARTIFACT.COMPILER.source_receipt(ROOT)) == []
        assert (output / variant / ARTIFACT.manifest_name(variant)).read_bytes() == (evidence / variant / ARTIFACT.manifest_name(variant)).read_bytes()


@pytest.mark.parametrize("mismatch", [None, "config", "manifest", "embedded"])
def test_import_is_digest_preserving_bounded_and_checks_embedded_receipts(bundle, monkeypatch, mismatch):
    _, output, selection = bundle
    root = output / "yellowfin"
    record = ARTIFACT.read(root / "bundle.json")
    receipt = ARTIFACT.read(root / "oci-export/source-receipt.json")
    receipt.update(recipe_sha256=EXPORT.sha(b"recipe"), catalog_sha256=EXPORT.sha(b"catalog"))
    ARTIFACT.write(root / "oci-export/source-receipt.json", receipt)
    calls = []
    def command(argv, timeout):
        calls.append((argv, timeout))
        if argv[:2] == ["skopeo", "copy"]:
            assert argv[2:] == ["--preserve-digests", "oci:" + str(root / "oci-export/source") + ":canary",
                                "containers-storage:" + ARTIFACT.target("yellowfin")]
            assert timeout == 1800
            return b""
        if argv[:3] == ["podman", "image", "inspect"]:
            assert timeout == 60
            return json.dumps([{"Id": "sha256:" + "f" * 64 if mismatch == "config" else record["source_image_id"]}]).encode()
        if argv[:3] == ["skopeo", "inspect", "--raw"]:
            assert timeout == 60 and argv[-1] == "containers-storage:@" + record["source_image_id"].removeprefix("sha256:")
            return b"changed" if mismatch == "manifest" else (root / "oci-export/source-manifest.json").read_bytes()
        if argv[:3] == ["podman", "container", "exists"]:
            raise subprocess.CalledProcessError(1, argv)
        assert argv[:2] == ["podman", "run"] and timeout == 120
        assert all(flag in argv for flag in ["--rm", "--pull=never", "--read-only", "--network=none", "--cap-drop=all"])
        assert record["source_image_id"] in argv
        if "-c" in argv:
            return json.dumps({EXPORT.FILES[0]: (root / ARTIFACT.manifest_name("yellowfin")).read_text(),
                               EXPORT.SOURCE.RECIPE: "recipe", EXPORT.SOURCE.CATALOG: "changed" if mismatch == "embedded" else "catalog"}).encode()
        assert argv[-1] == "--verify"
        return b""
    monkeypatch.setattr(ARTIFACT, "bounded_command", command)
    if mismatch:
        with pytest.raises(ValueError):
            ARTIFACT.import_original(root, "yellowfin", record)
    else:
        ARTIFACT.import_original(root, "yellowfin", record)
        assert len([call for call in calls if call[0][:3] != ["podman", "container", "exists"]]) == 5
    assert not any("push" in argv or "docker://" in " ".join(argv) for argv, _ in calls)


def test_command_timeout_terminates_the_child_process_group(tmp_path):
    import sys
    import time
    child_pid = tmp_path / "child.pid"
    code = ("import pathlib,subprocess,sys,time; "
            "p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']); "
            "pathlib.Path(sys.argv[1]).write_text(str(p.pid)); time.sleep(60)")
    with pytest.raises(TimeoutError, match="deadline"):
        ARTIFACT.bounded_command([sys.executable, "-c", code, str(child_pid)], 0.5)
    assert child_pid.exists()
    status = Path("/proc") / child_pid.read_text() / "stat"
    deadline = time.monotonic() + 5
    while status.exists() and status.read_text().split()[2] not in {"Z", "X"} and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not status.exists() or status.read_text().split()[2] in {"Z", "X"}


def test_command_output_is_bounded_and_token_not_inherited(monkeypatch):
    import sys
    monkeypatch.setenv("GITHUB_TOKEN", "test-token-must-not-reach-child")
    assert ARTIFACT.bounded_command([sys.executable, "-c", "import os;print('GITHUB_TOKEN' in os.environ)"], 5) == b"False\n"
    monkeypatch.setattr(ARTIFACT, "METADATA_LIMIT", 256)
    with pytest.raises(ValueError, match="output exceeds"):
        ARTIFACT.bounded_command([sys.executable, "-c", "print('x' * 1024)"], 5)


def test_download_overall_deadline_has_no_implicit_fallback(bundle, tmp_path, monkeypatch):
    import io
    _, _, selection = bundle
    artifact, run = metadata(selection)
    replies = iter([json.dumps(artifact).encode(), json.dumps(run).encode(), b""])
    class Response(io.BytesIO):
        code = 302
        headers = {"Location": "https://test.blob.core.windows.net/image.zip"}
    monkeypatch.setattr(ARTIFACT, "api", lambda *args: Response(next(replies)))
    ticks = iter([0, 1801])
    monkeypatch.setattr(ARTIFACT.time, "monotonic", lambda: next(ticks))
    with pytest.raises(ValueError, match="deadline"):
        ARTIFACT.download(selection, "yellowfin", tmp_path / "out")
    assert not (tmp_path / "out").exists() and not (tmp_path / "yellowfin.zip").exists()


def test_zip64_end_records_are_supported_for_large_original_artifacts(tmp_path):
    import struct
    archive = tmp_path / "zip64.zip"
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr("wallpaper.jpg", b"fixture")
    raw = archive.read_bytes()
    position = raw.rfind(b"PK\x05\x06")
    end = list(struct.unpack("<4s4H2LH", raw[position:]))
    count, size, offset = end[4:7]
    extended = struct.pack("<4sQ2H2L4Q", b"PK\x06\x06", 44, 45, 45, 0, 0, count, count, size, offset)
    locator = struct.pack("<4sLQL", b"PK\x06\x07", 0, position, 1)
    end[3] = end[4] = 0xffff
    end[5] = end[6] = 0xffffffff
    archive.write_bytes(raw[:position] + extended + locator + struct.pack("<4s4H2LH", *end))
    ARTIFACT.unpack(archive, tmp_path / "out", "yellowfin", ARTIFACT.sha(archive))
    assert (tmp_path / "out/wallpaper.jpg").read_bytes() == b"fixture"


def test_invalid_second_original_is_rejected_before_any_import(bundle, tmp_path, monkeypatch):
    _, output, selection = bundle
    (output / "grouper/wallpaper.jpg").write_bytes(b"changed")
    monkeypatch.setattr(ARTIFACT.COMPILER, "source_receipt", lambda root: source_receipt())
    monkeypatch.setattr(subprocess, "check_output", lambda *args, **kwargs: "c" * 40 + "\n")
    def download(pins, variant, destination):
        shutil.copytree(output / variant, destination)
        return {"run_status": "completed", "run_conclusion": "failure"}
    monkeypatch.setattr(ARTIFACT, "download", download)
    monkeypatch.setattr(ARTIFACT, "import_original", lambda *args: pytest.fail("invalid pair must not import"))
    with pytest.raises(ValueError, match="wallpaper"):
        ARTIFACT.restore(selection, tmp_path / "refused")
    assert list((tmp_path / "refused").iterdir()) == []


@pytest.mark.parametrize("outcome", ["timeout", "failure", "unowned", "residual"])
def test_verification_container_cleanup_checks_exact_ownership(monkeypatch, outcome):
    from types import SimpleNamespace
    token, container_id = "a" * 32, "b" * 64
    name = "fork-artifact-verify-" + token
    label = "io.tunaos.fork-artifact-verification"
    monkeypatch.setattr(ARTIFACT.uuid, "uuid4", lambda: SimpleNamespace(hex=token))
    live = False
    calls = []
    def command(argv, timeout):
        nonlocal live
        calls.append(argv)
        if argv[:3] == ["podman", "container", "exists"]:
            assert argv[-1] in {name, container_id}
            if not live:
                raise subprocess.CalledProcessError(1, argv)
            return b""
        if argv[:2] == ["podman", "run"]:
            assert argv[argv.index("--name") + 1] == name
            assert argv[argv.index("--label") + 1] == label + "=" + token
            live = True
            if outcome == "failure":
                raise subprocess.CalledProcessError(125, argv)
            raise TimeoutError("fixture container remains after client timeout")
        if argv[:3] == ["podman", "container", "inspect"]:
            assert argv[-1] == name
            return json.dumps([{"Id": container_id, "Name": name,
                "Config": {"Labels": {label: "wrong-owner" if outcome == "unowned" else token}}}]).encode()
        assert argv == ["podman", "rm", "--force", container_id] and timeout == 60
        live = outcome == "residual"
        return b""
    monkeypatch.setattr(ARTIFACT, "bounded_command", command)
    expected = ValueError if outcome in {"unowned", "residual"} else subprocess.CalledProcessError if outcome == "failure" else TimeoutError
    with pytest.raises(expected):
        ARTIFACT.run_verifier("sha256:" + "f" * 64, ["-c", "pass"])
    removals = [call for call in calls if call[:2] == ["podman", "rm"]]
    assert removals == ([] if outcome == "unowned" else [["podman", "rm", "--force", container_id]])
    assert live == (outcome in {"unowned", "residual"})


def test_container_absence_probe_failure_is_not_success(monkeypatch):
    def fail(argv, timeout):
        raise subprocess.CalledProcessError(125, argv)
    monkeypatch.setattr(ARTIFACT, "bounded_command", fail)
    with pytest.raises(ValueError, match="could not establish"):
        ARTIFACT.run_verifier("sha256:" + "a" * 64, ["-c", "pass"])


def test_producer_file_count_is_bounded_before_staging(bundle, tmp_path, monkeypatch):
    evidence, _, _ = bundle
    monkeypatch.setattr(ARTIFACT, "MAX_FILES", 10)
    with pytest.raises(ValueError, match="file count"):
        ARTIFACT.package(evidence, tmp_path / "refused", IDENTITY)
    assert not (tmp_path / "refused").exists()


def test_zip64_effective_directory_bounds_apply_without_classic_sentinels(tmp_path, monkeypatch):
    import struct
    archive = tmp_path / "zip64.zip"
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr("wallpaper.jpg", b"fixture")
        zipped.writestr("bundle.json", b"{}")
    raw = archive.read_bytes()
    position = raw.rfind(b"PK\x05\x06")
    end = list(struct.unpack("<4s4H2LH", raw[position:]))
    count, size, offset = end[4:7]
    assert size > 64
    extended = struct.pack("<4sQ2H2L4Q", b"PK\x06\x06", 44, 45, 45, 0, 0, count, count, size, offset)
    locator = struct.pack("<4sLQL", b"PK\x06\x07", 0, position, 1)
    end[3] = end[4] = 1
    end[5] = 16
    archive.write_bytes(raw[:position] + extended + locator + struct.pack("<4s4H2LH", *end))
    monkeypatch.setattr(ARTIFACT, "METADATA_LIMIT", 64)
    with pytest.raises(ValueError, match="central directory"):
        ARTIFACT.unpack(archive, tmp_path / "refused", "yellowfin", ARTIFACT.sha(archive))
    assert not (tmp_path / "refused").exists()


def test_hard_deadline_interrupts_blocked_reads_and_restores_handler():
    import signal
    import time
    previous = signal.getsignal(signal.SIGALRM)
    with pytest.raises(TimeoutError, match="wall-clock deadline"):
        with ARTIFACT.hard_deadline(0.05):
            time.sleep(10)
    assert signal.getitimer(signal.ITIMER_REAL) == (0.0, 0.0)
    assert signal.getsignal(signal.SIGALRM) == previous


def test_existing_process_deadline_is_never_silently_replaced():
    import signal
    signal.setitimer(signal.ITIMER_REAL, 60)
    try:
        with pytest.raises(ValueError, match="existing process deadline"):
            with ARTIFACT.hard_deadline(30):
                pytest.fail("must reject nesting")
        assert signal.getitimer(signal.ITIMER_REAL)[0] > 30
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
