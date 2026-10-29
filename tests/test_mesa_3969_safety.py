"""Source-only Mesa authority, integrity, owned-state and publication boundaries.

No fixtures are RPMs, OCI images, signing keys or authenticated GitHub receipts.
The only process queried here is git for the actual CI checkout identity.
"""
import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import stat
import struct
import subprocess
from types import SimpleNamespace
from urllib import error
import warnings
import zipfile

import pytest


ROOT = Path(__file__).resolve().parents[1]
MANUAL = ROOT / "tests/manual"


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CORE = load_module("mesa3969_safety_core", MANUAL / "mesa_3969.py")
SMOKE = load_module("mesa3969_safety_smoke", MANUAL / "mesa_3969_source_smoke.py")
HEAD = "a" * 40


def environment(tmp_path, head=HEAD):
    return {
        "GITHUB_ACTIONS": "true", "GITHUB_SERVER_URL": "https://github.com",
        "GITHUB_API_URL": "https://api.github.com", "GITHUB_REPOSITORY": "tuna-os/tunaOS",
        "GITHUB_REPOSITORY_ID": "1029250013", "GITHUB_EVENT_NAME": "workflow_dispatch",
        "GITHUB_RUN_ID": "3969001", "GITHUB_RUN_ATTEMPT": "1", "GITHUB_SHA": head,
        "REVIEWED_HEAD": head, "MESA_3969_APPROVED_HEAD": head,
        "LAB_CONFIRM": "RUN_MESA_3969_ONCE", "RUNNER_TEMP": str(tmp_path),
        "GITHUB_WORKSPACE": str(ROOT),
    }


def identity(head=HEAD):
    return {"repository_id": 1029250013, "repository": "tuna-os/tunaOS", "head_sha": head,
            "run_id": 3969001, "run_attempt": 1, "workflow_id": 3969}


class MetadataAPI:
    """An untrusted metadata/byte transport boundary, not a substitute validator."""

    def __init__(self, head=HEAD):
        self.identity = identity(head)
        self.repo = {"id": 1029250013, "full_name": "tuna-os/tunaOS", "fork": False}
        self.run = {
            "id": 3969001, "head_sha": head, "run_attempt": 1, "event": "workflow_dispatch",
            "status": "in_progress", "path": ".github/workflows/mesa-3969-compare.yml",
            "workflow_id": 3969, "repository": {"id": 1029250013},
            "head_repository": {"id": 1029250013},
        }
        self.listing = {"total_count": 1, "workflow_runs": [copy.deepcopy(self.run)]}
        self.jobs = {"total_count": 1, "jobs": [{
            "id": 701, "run_id": 3969001, "run_attempt": 1, "head_sha": head,
            "name": "Build signed Mesa pair", "status": "completed", "conclusion": "success",
        }]}
        self.artifact = {
            "id": 123, "name": f"mesa3969-inputs-3969001-{head}", "expired": False,
            "workflow_run": {"id": 3969001, "head_sha": head,
                             "repository_id": 1029250013, "head_repository_id": 1029250013},
        }
        self.calls = []
        self.downloads = []
        self.archive = b""
        self.after_download = None

    def __call__(self, path):
        self.calls.append(path)
        base = "/repos/tuna-os/tunaOS"
        if path == base:
            return copy.deepcopy(self.repo)
        if path == base + "/actions/runs/3969001":
            return copy.deepcopy(self.run)
        if path == base + f"/actions/workflows/3969/runs?head_sha={self.identity['head_sha']}&event=workflow_dispatch&per_page=100":
            return copy.deepcopy(self.listing)
        if path == base + "/actions/runs/3969001/jobs?filter=all&per_page=100":
            return copy.deepcopy(self.jobs)
        if path == base + "/actions/artifacts/123":
            return copy.deepcopy(self.artifact)
        raise AssertionError(f"unexpected authority query: {path}")

    def download(self, artifact_id, output, expected_bytes):
        self.downloads.append((artifact_id, output, expected_bytes))
        assert expected_bytes == len(self.archive)
        with Path(output).open("xb") as stream:
            stream.write(self.archive)
        if self.after_download:
            self.after_download()
        return hashlib.sha256(self.archive).hexdigest()


def changed(value, path, replacement):
    node = value
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = replacement


@pytest.fixture
def bundle():
    return SMOKE.synthetic_bundle(CORE.INPUTS, dict(identity(), job_id=701))


@pytest.fixture
def plentiful_space(monkeypatch):
    monkeypatch.setattr(CORE.shutil, "disk_usage", lambda path: SimpleNamespace(free=100 * 1024 ** 3))


def forbidden(*args, **kwargs):
    raise AssertionError("unapproved input reached an effect or API boundary")


def test_exact_manual_head_is_admitted_only_by_live_repository_and_single_run(tmp_path):
    api = MetadataAPI()
    result = CORE.admit_environment(environment(tmp_path), api, checkout_head=HEAD)
    assert result == identity()
    assert len(api.calls) == 3
    assert api.calls[0] == "/repos/tuna-os/tunaOS"
    assert api.calls[1] == "/repos/tuna-os/tunaOS/actions/runs/3969001"
    assert "head_sha=" + HEAD in api.calls[2]


@pytest.mark.parametrize("key,value", [
    ("MESA_3969_APPROVED_HEAD", None), ("MESA_3969_APPROVED_HEAD", "b" * 40),
    ("REVIEWED_HEAD", "b" * 40), ("LAB_CONFIRM", "yes"), ("GITHUB_ACTIONS", "false"),
    ("GITHUB_EVENT_NAME", "push"), ("GITHUB_EVENT_NAME", "pull_request"),
    ("GITHUB_RUN_ATTEMPT", "2"), ("GITHUB_RUN_ATTEMPT", "01"),
    ("GITHUB_SERVER_URL", "https://github.example"),
    ("GITHUB_API_URL", "https://api.github.example"), ("GITHUB_REPOSITORY", "fork/tunaOS"),
    ("GITHUB_REPOSITORY_ID", "1029250014"), ("GITHUB_SHA", "A" * 40),
    ("GITHUB_RUN_ID", "0"), ("GITHUB_RUN_ID", "01"),
    ("GITHUB_RUN_ID", "9223372036854775808"),
])
def test_local_refusals_precede_checkout_tools_api_and_state(tmp_path, monkeypatch, key, value):
    env = environment(tmp_path)
    if value is None:
        env.pop(key)
    else:
        env[key] = value
    monkeypatch.setattr(CORE.subprocess, "run", forbidden)
    monkeypatch.setattr(CORE, "GitHubAPI", forbidden)
    with pytest.raises(CORE.LabError):
        CORE.admit_environment(env)
    assert list(tmp_path.iterdir()) == []


def test_actual_checkout_head_is_not_replaceable_by_environment(tmp_path):
    api = MetadataAPI()
    with pytest.raises(CORE.LabError, match="checked-out source"):
        CORE.admit_environment(environment(tmp_path), api, checkout_head="b" * 40)
    assert api.calls == []


@pytest.mark.parametrize("section,path,value", [
    ("repo", ("id",), 1029250014), ("repo", ("id",), 1029250013.0),
    ("repo", ("fork",), True), ("repo", ("full_name",), "fork/tunaOS"),
    ("run", ("id",), 3969002), ("run", ("id",), 3969001.0),
    ("run", ("head_sha",), "b" * 40), ("run", ("run_attempt",), True),
    ("run", ("event",), "push"), ("run", ("status",), "completed"),
    ("run", ("path",), ".github/workflows/other.yml"),
    ("run", ("repository", "id"), 1029250014),
    ("run", ("head_repository", "id"), "1029250013"),
    ("run", ("workflow_id",), 0), ("run", ("workflow_id",), True),
    ("listing", ("total_count",), 101), ("listing", ("total_count",), True),
    ("listing", ("total_count",), 2), ("listing", ("workflow_runs",), []),
    ("listing", ("workflow_runs", 0, "workflow_id"), 3970),
    ("listing", ("workflow_runs", 0, "id"), 3969002),
    ("listing", ("workflow_runs", 0, "run_attempt"), 2),
    ("listing", ("workflow_runs", 0, "head_sha"), "b" * 40),
])
def test_live_metadata_cannot_override_manual_first_attempt_authority(tmp_path, section, path, value):
    api = MetadataAPI()
    changed(getattr(api, section), path, value)
    with pytest.raises(CORE.LabError):
        CORE.admit_environment(environment(tmp_path), api, checkout_head=HEAD)
    assert list(tmp_path.iterdir()) == []


def test_cancelled_prior_run_consumes_the_head_even_if_current_run_is_in_progress(tmp_path):
    api = MetadataAPI()
    prior = dict(api.run, id=3969000, status="completed", conclusion="cancelled")
    api.listing = {"total_count": 2, "workflow_runs": [api.run, prior]}
    with pytest.raises(CORE.LabError, match="head already consumed"):
        CORE.admit_environment(environment(tmp_path), api, checkout_head=HEAD)


@pytest.mark.parametrize("field,value", [
    ("id", True), ("run_id", 3969002), ("run_attempt", 2),
    ("head_sha", "b" * 40), ("status", "in_progress"), ("conclusion", "failure"),
    ("conclusion", "cancelled"),
])
def test_only_successful_exact_run_producer_can_authorize_consumption(field, value):
    api = MetadataAPI()
    api.jobs["jobs"][0][field] = value
    with pytest.raises(CORE.LabError):
        CORE.build_job(identity(), api, completed=True)


def test_producer_must_be_unique_and_listing_complete():
    api = MetadataAPI()
    assert CORE.build_job(identity(), api, completed=True) == 701
    api.jobs["jobs"].append(dict(api.jobs["jobs"][0], id=702))
    api.jobs["total_count"] = 2
    with pytest.raises(CORE.LabError, match="unique"):
        CORE.build_job(identity(), api, completed=True)
    api.jobs["jobs"].pop()
    with pytest.raises(CORE.LabError, match="incomplete"):
        CORE.build_job(identity(), api, completed=True)
    api.jobs["total_count"] = 1
    api.jobs["jobs"][0].update(status="in_progress", conclusion=None)
    assert CORE.build_job(identity(), api) == 701


@pytest.mark.parametrize("data", [
    b'{"x":1,"x":2}', b'{"outer":{"x":1,"x":2}}', b'{"x":NaN}',
    b'{"x":Infinity}', b'{"x":-Infinity}', b'\xff', b'{', b'',
])
def test_strict_json_refuses_ambiguous_nonfinite_or_invalid_inputs(data):
    with pytest.raises(CORE.LabError):
        CORE.decode_json(data)


def test_json_and_hash_byte_limits_accept_exact_boundary_and_refuse_one_more(tmp_path):
    path = tmp_path / "value.json"
    data = b'{"value":1}'
    path.write_bytes(data)
    assert CORE.read_json(path, max_bytes=len(data)) == {"value": 1}
    assert CORE.sha256_file(path, max_bytes=len(data)) == hashlib.sha256(data).hexdigest()
    with pytest.raises(CORE.LabError):
        CORE.read_json(path, max_bytes=len(data) - 1)
    with pytest.raises(CORE.LabError):
        CORE.sha256_file(path, max_bytes=len(data) - 1)
    link = tmp_path / "linked.json"
    link.symlink_to(path)
    with pytest.raises(OSError):
        CORE.read_json(link)


@pytest.mark.parametrize("path,value", [
    (("schema_version",), True), (("unknown",), "not permitted"),
    (("producer", "run_id"), True), (("producer", "run_attempt"), 2),
    (("producer", "job_id"), "701"), (("producer", "workflow_id"), 0),
    (("inputs", "patch_sha256"), "9" * 64),
    (("baseline", "image_id"), "2" * 64),
    (("baseline", "image_tag"), "localhost/not-owned:base"),
    (("signer", "fingerprint"), "a" * 40),
    (("probe", "helper_commit"), "b" * 40),
    (("arms", "candidate", "buildroot_image_id"), "sha256:" + "9" * 64),
    (("arms", "control", "packages", 0, "epoch"), True),
    (("arms", "control", "packages", 0, "epoch"), -1),
    (("arms", "control", "packages", 0, "epoch"), 2 ** 32),
    (("arms", "control", "packages", 0, "bytes"), 0),
    (("arms", "control", "packages", 0, "header_sha256"), None),
    (("arms", "control", "packages", 0, "path"), "rpms/candidate/mesa-test.rpm"),
    (("arms", "candidate", "packages", 0, "version"), "25.2.8"),
    (("files", 0, "bytes"), True), (("files", 0, "sha256"), "SHA256:not-a-digest"),
])
def test_manifest_schema_types_fixed_inputs_and_pair_identity_cannot_drift(bundle, path, value):
    manifest, _ = bundle
    changed(manifest, path, value)
    with pytest.raises(CORE.LabError):
        CORE.validate_manifest(manifest)


def test_manifest_matches_live_producer_and_supports_nonzero_epoch(bundle):
    manifest, _ = bundle
    for arm in ("control", "candidate"):
        manifest["arms"][arm]["packages"][0]["epoch"] = 2 ** 32 - 1
    validated = CORE.validate_manifest(manifest, dict(identity(), job_id=701))
    assert validated["arms"]["control"]["packages"][0]["epoch"] == 4294967295
    for field, value in (("head_sha", "b" * 40), ("run_id", 3969002), ("job_id", 702), ("workflow_id", 3970)):
        producer = dict(identity(), job_id=701)
        producer[field] = value
        with pytest.raises(CORE.LabError, match="live authority"):
            CORE.validate_manifest(manifest, producer)


@pytest.mark.parametrize("path", [
    "../baseline.oci.tar", "/baseline.oci.tar", "rpms/control/../x.rpm",
    "rpms//control/x.rpm", "./baseline.oci.tar", "rpms/control/./x.rpm",
    "rpms\\control\\x.rpm", "rpms/control/x.rpm\x00", "rpms/control/.hidden.rpm",
    "private-key.asc", "raw/result.json", "disk.qcow2", "image.iso", "source.src.rpm",
])
def test_transfer_paths_reject_traversal_noncanonical_and_unselected_state(path):
    with pytest.raises(CORE.LabError):
        CORE.allowed_member(path)


def test_manifest_requires_complete_unique_file_and_package_sets(bundle):
    manifest, _ = bundle
    for mutator in (
        lambda m: m["files"].pop(),
        lambda m: m["files"].append(copy.deepcopy(m["files"][0])),
        lambda m: m["arms"]["control"]["packages"].append(copy.deepcopy(m["arms"]["control"]["packages"][0])),
        lambda m: m["arms"]["candidate"]["packages"].clear(),
        lambda m: m["arms"]["control"]["packages"][0].update(sha256="9" * 64),
    ):
        altered = copy.deepcopy(manifest)
        mutator(altered)
        with pytest.raises(CORE.LabError):
            CORE.validate_manifest(altered)


def test_archive_round_trip_extracts_only_declared_integrity_checked_bytes(tmp_path, bundle, plentiful_space):
    manifest, members = bundle
    archive = SMOKE.write_archive(tmp_path / "inputs.zip", manifest, members)
    destination = tmp_path / "extracted"
    outside = tmp_path / "unrelated"
    outside.write_bytes(b"preserve")
    result = CORE.verify_archive(archive, dict(identity(), job_id=701), destination)
    assert result["producer"] == dict(identity(), job_id=701)
    assert {p.relative_to(destination).as_posix() for p in destination.rglob("*") if p.is_file()} == set(members) | {"manifest.json"}
    for name, expected in members.items():
        assert (destination / name).read_bytes() == expected
    assert stat.S_IMODE(destination.stat().st_mode) == 0o700
    assert all(stat.S_IMODE(p.stat().st_mode) == 0o600 for p in destination.rglob("*") if p.is_file())
    assert outside.read_bytes() == b"preserve"


@pytest.mark.parametrize("mutation", ["hash", "size", "missing", "extra", "producer", "private-key"])
def test_archive_refuses_consumer_visible_substitution_and_removes_partial_output(tmp_path, bundle, plentiful_space, mutation):
    manifest, members = bundle
    expected = dict(identity(), job_id=701)
    if mutation == "hash":
        members["baseline.oci.tar"] = b"X" * len(members["baseline.oci.tar"])
    elif mutation == "size":
        members["baseline.oci.tar"] += b"X"
    elif mutation == "missing":
        del members["toolchain.txt"]
    elif mutation == "extra":
        members["rpms/control/extra.rpm"] = b"not declared"
    elif mutation == "producer":
        expected["job_id"] = 702
    else:
        members["public-key.asc"] = b"-----BEGIN PGP PRIVATE KEY BLOCK-----\nnot-a-key\n"
        record = next(row for row in manifest["files"] if row["path"] == "public-key.asc")
        record.update(bytes=len(members["public-key.asc"]), sha256=hashlib.sha256(members["public-key.asc"]).hexdigest())
    archive = SMOKE.write_archive(tmp_path / "bad.zip", manifest, members)
    destination = tmp_path / "output"
    outside = tmp_path / "keep"
    outside.write_bytes(b"outside")
    with pytest.raises(CORE.LabError):
        CORE.verify_archive(archive, expected, destination)
    assert not destination.exists()
    assert outside.read_bytes() == b"outside"


@pytest.mark.parametrize("entry", ["traversal", "duplicate", "symlink", "fifo", "unsupported", "unsafe-directory", "encrypted"])
def test_archive_refuses_path_duplicate_link_special_encrypted_or_compression_entries(tmp_path, bundle, entry):
    manifest, members = bundle
    name = "../escape" if entry == "traversal" else "rpms/control/extra.rpm"
    info = zipfile.ZipInfo(name)
    info.create_system = 3
    info.external_attr = (stat.S_IFREG | 0o600) << 16
    if entry == "duplicate":
        info.filename = "baseline.oci.tar"
    elif entry in ("symlink", "fifo"):
        info.external_attr = ((stat.S_IFLNK if entry == "symlink" else stat.S_IFIFO) | 0o600) << 16
    elif entry == "unsupported":
        info.compress_type = zipfile.ZIP_BZIP2
    elif entry == "unsafe-directory":
        info.filename = "outside/"
        info.external_attr = (stat.S_IFDIR | 0o700) << 16
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        archive = SMOKE.write_archive(tmp_path / "bad.zip", manifest, members, [(info, b"bad")])
    if entry == "encrypted":
        # Set the real ZIP header flag; ZipFile.writestr clears an assigned flag_bits.
        data = bytearray(archive.read_bytes())
        central = data.index(b"PK\x01\x02")
        flags = struct.unpack_from("<H", data, central + 8)[0]
        struct.pack_into("<H", data, central + 8, flags | 1)
        archive.write_bytes(data)
    with pytest.raises(CORE.LabError):
        CORE.verify_archive(archive)
    assert not (tmp_path / "escape").exists()


def test_archive_and_unpacked_limits_have_exact_positive_boundaries(tmp_path, bundle, monkeypatch):
    manifest, members = bundle
    archive = SMOKE.write_archive(tmp_path / "inputs.zip", manifest, members)
    monkeypatch.setattr(CORE, "MAX_ARCHIVE", archive.stat().st_size)
    monkeypatch.setattr(CORE, "MAX_UNPACKED", sum(len(data) for data in members.values()))
    assert CORE.verify_archive(archive)["kind"] == "mesa3969-inputs"
    monkeypatch.setattr(CORE, "MAX_ARCHIVE", archive.stat().st_size - 1)
    with pytest.raises(CORE.LabError, match="archive exceeds"):
        CORE.verify_archive(archive)
    monkeypatch.setattr(CORE, "MAX_ARCHIVE", archive.stat().st_size)
    monkeypatch.setattr(CORE, "MAX_UNPACKED", sum(len(data) for data in members.values()) - 1)
    with pytest.raises(CORE.LabError, match="unpacked size"):
        CORE.verify_archive(archive)


def test_archive_member_count_refuses_2049_even_when_all_members_are_tiny(tmp_path):
    archive = tmp_path / "too-many.zip"
    with zipfile.ZipFile(archive, "w") as stream:
        for index in range(2049):
            stream.writestr(f"rpms/control/tiny-{index}.rpm", b"x")
    with pytest.raises(CORE.LabError, match="member count"):
        CORE.verify_archive(archive)


def test_archive_manifest_size_refuses_before_decode(tmp_path, bundle, monkeypatch):
    manifest, members = bundle
    archive = SMOKE.write_archive(tmp_path / "inputs.zip", manifest, members)
    monkeypatch.setattr(CORE, "MAX_JSON", 20)
    with pytest.raises(CORE.LabError, match="manifest exceeds"):
        CORE.verify_archive(archive)


def test_extraction_refuses_existing_linked_and_low_space_destinations(tmp_path, bundle, monkeypatch):
    manifest, members = bundle
    archive = SMOKE.write_archive(tmp_path / "inputs.zip", manifest, members)
    existing = tmp_path / "existing"
    existing.mkdir()
    (existing / "keep").write_bytes(b"keep")
    linked = tmp_path / "linked"
    linked.symlink_to(existing, target_is_directory=True)
    for destination in (existing, linked):
        with pytest.raises(CORE.LabError):
            CORE.verify_archive(archive, destination=destination)
    monkeypatch.setattr(CORE.shutil, "disk_usage", lambda path: SimpleNamespace(free=0))
    with pytest.raises(CORE.LabError, match="insufficient extraction"):
        CORE.verify_archive(archive, destination=tmp_path / "new")
    assert not (tmp_path / "new").exists()
    assert (existing / "keep").read_bytes() == b"keep"


@pytest.fixture
def fetch_case(tmp_path, monkeypatch, plentiful_space):
    # Use the real checkout head; do not fake a successful git subprocess.
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, check=True,
                          capture_output=True, text=True, timeout=30).stdout.strip()
    env = environment(tmp_path, head)
    api = MetadataAPI(head)
    producer = dict(identity(head), job_id=701)
    manifest, members = SMOKE.synthetic_bundle(CORE.INPUTS, producer)
    archive = SMOKE.write_archive(tmp_path / "server.zip", manifest, members)
    api.archive = archive.read_bytes()
    upload_digest = hashlib.sha256(api.archive).hexdigest()
    api.artifact.update(size_in_bytes=len(api.archive), digest="sha256:" + upload_digest)
    root = CORE.create_owned_root(tmp_path, "runtime", identity(head))
    (root / "work").mkdir()
    destination = root / "work/inputs"
    monkeypatch.setattr(CORE, "GitHubAPI", lambda supplied: api)
    return SimpleNamespace(api=api, env=env, digest=upload_digest, destination=destination,
                           producer=producer, manifest=manifest, members=members, root=root)


def test_fetch_joins_live_run_job_upload_digest_and_manifest_before_consumption(fetch_case):
    case = fetch_case
    result = CORE.fetch_inputs(123, "sha256:" + case.digest, case.destination, case.env)
    assert result == {"directory": str(case.destination), "manifest": str(case.destination / "manifest.json"),
                      "producer": case.producer, "authority": "live_same_run"}
    assert (case.destination / "baseline.oci.tar").read_bytes() == case.members["baseline.oci.tar"]
    assert len(case.api.downloads) == 1
    assert case.api.calls.count("/repos/tuna-os/tunaOS/actions/runs/3969001") == 2
    assert not (case.root / "work/inputs.zip").exists()


@pytest.mark.parametrize("path,value", [
    (("id",), 124), (("id",), 123.0), (("name",), "mesa3969-inputs-latest"),
    (("expired",), True), (("expired",), 0),
    (("workflow_run", "id"), 3969002), (("workflow_run", "id"), 3969001.0),
    (("workflow_run", "head_sha"), "b" * 40),
    (("workflow_run", "repository_id"), 1029250014),
    (("workflow_run", "repository_id"), 1029250013.0),
    (("workflow_run", "head_repository_id"), 1029250013.0),
    (("size_in_bytes",), True), (("size_in_bytes",), 0),
    (("size_in_bytes",), 24 * 1024 ** 3 + 1),
    (("digest",), "sha256:" + "9" * 64),
])
def test_fetch_refuses_artifact_metadata_substitution_before_transport(fetch_case, path, value):
    case = fetch_case
    changed(case.api.artifact, path, value)
    with pytest.raises(CORE.LabError):
        CORE.fetch_inputs(123, case.digest, case.destination, case.env)
    assert case.api.downloads == []
    assert not case.destination.exists()


def test_fetch_rejects_independent_digest_and_nonowned_destination_before_download(fetch_case):
    case = fetch_case
    with pytest.raises(CORE.LabError, match="independent upload digest"):
        CORE.fetch_inputs(123, "0" * 64, case.destination, case.env)
    with pytest.raises(CORE.LabError, match="fixed runtime input destination"):
        CORE.fetch_inputs(123, case.digest, case.root / "other", case.env)
    assert case.api.downloads == []


def test_fetch_refuses_archive_digest_substitution_before_extraction(fetch_case):
    case = fetch_case
    case.api.archive = case.api.archive[:-1] + bytes([case.api.archive[-1] ^ 1])
    with pytest.raises(CORE.LabError, match="archive digest"):
        CORE.fetch_inputs(123, case.digest, case.destination, case.env)
    assert not case.destination.exists()


@pytest.mark.parametrize("replacement", ["job", "head", "attempt", "status"])
def test_fetch_rechecks_live_authority_after_transport_before_extracting(fetch_case, replacement):
    case = fetch_case
    def change_live():
        if replacement == "job":
            case.api.jobs["jobs"][0]["id"] = 702
        elif replacement == "head":
            case.api.run["head_sha"] = "b" * 40
        elif replacement == "attempt":
            case.api.run["run_attempt"] = 2
        else:
            case.api.run["status"] = "completed"
    case.api.after_download = change_live
    with pytest.raises(CORE.LabError):
        CORE.fetch_inputs(123, case.digest, case.destination, case.env)
    assert len(case.api.downloads) == 1
    assert not case.destination.exists()


def test_fetch_rejects_manifest_producer_even_with_self_consistent_upload_digest(fetch_case, tmp_path):
    case = fetch_case
    case.manifest["producer"]["job_id"] = 702
    archive = SMOKE.write_archive(tmp_path / "wrong-producer.zip", case.manifest, case.members)
    case.api.archive = archive.read_bytes()
    case.digest = hashlib.sha256(case.api.archive).hexdigest()
    case.api.artifact.update(size_in_bytes=len(case.api.archive), digest="sha256:" + case.digest)
    with pytest.raises(CORE.LabError, match="live authority"):
        CORE.fetch_inputs(123, case.digest, case.destination, case.env)
    assert not case.destination.exists()


class Response(io.BytesIO):
    pass


class Opener:
    def __init__(self, result):
        self.result = result
        self.requests = []

    def open(self, request, timeout):
        self.requests.append(request)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def test_signed_download_redirect_strips_github_authorization_and_checks_real_bytes(tmp_path, monkeypatch):
    location = "https://blob.example.test/inputs.zip?signature=synthetic"
    github = Opener(error.HTTPError("https://api.github.com", 302, "redirect", {"Location": location}, None))
    blob = Opener(Response(b"real transport fixture"))
    monkeypatch.setattr(CORE.request, "build_opener", lambda *args: github)
    api = CORE.GitHubAPI({"GITHUB_TOKEN": "synthetic-token-not-a-credential"})
    monkeypatch.setattr(CORE.request, "build_opener", lambda *args: blob)
    output = tmp_path / "download.zip"
    digest = api.download(123, output, len(b"real transport fixture"))
    assert github.requests[0].get_header("Authorization") == "Bearer synthetic-token-not-a-credential"
    assert blob.requests[0].full_url == location
    assert blob.requests[0].get_header("Authorization") is None
    assert output.read_bytes() == b"real transport fixture"
    assert digest == hashlib.sha256(b"real transport fixture").hexdigest()


@pytest.mark.parametrize("location", ["http://blob.example.test/x", "https://user:pass@blob.example.test/x",
                                      "https://blob.example.test:444/x", "https://blob.example.test/x#fragment"])
def test_unsafe_download_redirects_never_contact_blob(tmp_path, monkeypatch, location):
    github = Opener(error.HTTPError("https://api.github.com", 302, "redirect", {"Location": location}, None))
    monkeypatch.setattr(CORE.request, "build_opener", lambda *args: github)
    api = CORE.GitHubAPI({"GH_TOKEN": "synthetic"})
    monkeypatch.setattr(CORE.request, "build_opener", forbidden)
    with pytest.raises(CORE.LabError, match="unsafe artifact redirect"):
        api.download(123, tmp_path / "output", 1)
    assert not (tmp_path / "output").exists()


@pytest.fixture
def owned(tmp_path, monkeypatch):
    monkeypatch.delenv("SUDO_UID", raising=False)
    root = CORE.create_owned_root(tmp_path, "runtime", identity())
    return root


def test_owned_cleanup_keeps_public_outputs_until_final_removal_and_preserves_outside(tmp_path, owned):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep").write_bytes(b"outside")
    for child in ("work", "transfer", "evidence"):
        (owned / child).mkdir()
        (owned / child / "keep").write_text(child)
    (owned / "work/link").symlink_to(outside, target_is_directory=True)
    assert CORE.check_owned_root(tmp_path, "runtime", identity()) == owned
    assert stat.S_IMODE(owned.stat().st_mode) == 0o700
    CORE.cleanup_owned_root(tmp_path, "runtime", identity(), "work")
    assert not (owned / "work").exists()
    assert (owned / "transfer/keep").read_text() == "transfer"
    assert (owned / "evidence/keep").read_text() == "evidence"
    assert (outside / "keep").read_bytes() == b"outside"
    CORE.cleanup_owned_root(tmp_path, "runtime", identity())
    CORE.cleanup_owned_root(tmp_path, "runtime", identity())
    assert not owned.exists()
    assert (outside / "keep").read_bytes() == b"outside"


@pytest.mark.parametrize("field,value", [
    ("schema_version", True), ("repository_id", 1029250014), ("run_id", 3969002),
    ("head_sha", "b" * 40), ("role", "build"), ("uid", -1), ("unknown", "extra"),
])
def test_cleanup_refuses_marker_substitution_without_removing_any_state(tmp_path, owned, field, value):
    marker = owned / ".mesa3969-owned.json"
    data = CORE.read_json(marker)
    data[field] = value
    CORE.write_json(marker, data)
    keep = owned / "keep"
    keep.write_bytes(b"private state")
    with pytest.raises(CORE.LabError):
        CORE.cleanup_owned_root(tmp_path, "runtime", identity())
    assert keep.read_bytes() == b"private state"


def test_cleanup_refuses_missing_linked_marker_root_or_work_and_unsafe_mode(tmp_path, owned):
    marker = owned / ".mesa3969-owned.json"
    saved = marker.read_bytes()
    marker.unlink()
    with pytest.raises(OSError):
        CORE.cleanup_owned_root(tmp_path, "runtime", identity())
    outside = tmp_path / "outside.json"
    outside.write_bytes(saved)
    marker.symlink_to(outside)
    with pytest.raises(OSError):
        CORE.cleanup_owned_root(tmp_path, "runtime", identity())
    marker.unlink()
    marker.write_bytes(saved)
    owned.chmod(0o755)
    with pytest.raises(CORE.LabError, match="owner/mode"):
        CORE.cleanup_owned_root(tmp_path, "runtime", identity())
    owned.chmod(0o700)
    (owned / "work").symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(CORE.LabError, match="symlink"):
        CORE.cleanup_owned_root(tmp_path, "runtime", identity(), "work")
    with pytest.raises(CORE.LabError, match="only private work"):
        CORE.cleanup_owned_root(tmp_path, "runtime", identity(), "transfer")
    assert outside.read_bytes() == saved
    (owned / "work").unlink()
    moved = tmp_path / "moved"
    owned.rename(moved)
    owned.symlink_to(moved, target_is_directory=True)
    with pytest.raises(CORE.LabError, match="unsafe ancestry"):
        CORE.cleanup_owned_root(tmp_path, "runtime", identity())
    assert (moved / ".mesa3969-owned.json").read_bytes() == saved


def test_owned_root_creation_refuses_symlinked_parent_and_reuse(tmp_path, owned):
    with pytest.raises(FileExistsError):
        CORE.create_owned_root(tmp_path, "runtime", identity())
    link = tmp_path / "parent-link"
    link.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(CORE.LabError, match="unsafe ancestry"):
        CORE.create_owned_root(link, "build", identity())


def test_evidence_redacts_masks_across_files_and_does_not_recurse_raw_state(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "control").mkdir()
    (source / "build-log.txt").write_text("::add-mask::synthetic-secret-long\n::add-mask::synthetic-secret\npublic build log\n")
    (source / "control/gate.log").write_text("value synthetic-secret-long and synthetic-secret\n")
    (source / "comparison.json").write_text('{"value":"synthetic-secret-long","result":"source-only"}\n')
    (source / "raw").mkdir()
    (source / "raw/private-key").write_text("-----BEGIN PRIVATE KEY-----\nnot a real key\n")
    (source / "raw/result.json").write_text('{"not":"public"}')
    output = tmp_path / "public"
    receipt = CORE.pack_evidence(source, output)
    assert receipt["files"] == ["build-log.txt", "comparison.json", "control/gate.log"]
    assert (output / "build-log.txt").read_text() == "public build log\n"
    assert (output / "control/gate.log").read_text() == "value [REDACTED] and [REDACTED]\n"
    assert CORE.read_json(output / "comparison.json") == {"value": "[REDACTED]", "result": "source-only"}
    assert not (output / "raw").exists()
    assert receipt["bytes"] == sum(p.stat().st_size for p in output.rglob("*") if p.is_file())
    assert stat.S_IMODE(output.stat().st_mode) == 0o700
    assert all(stat.S_IMODE(p.stat().st_mode) == 0o600 for p in output.rglob("*") if p.is_file())


def test_mask_percent_escaping_and_overlaps_are_redacted_without_command_lines():
    text = "::add-mask::alpha%25beta%0Asecond\nalpha%beta\nsecond\nalpha%25beta%0Asecond\n"
    assert CORE.sanitize_text(text) == "[REDACTED]\n[REDACTED]\n"


@pytest.mark.parametrize("private", [
    "-----BEGIN PRIVATE KEY-----", "-----BEGIN PGP PRIVATE KEY BLOCK-----",
    "-----BEGIN RSA PRIVATE KEY-----", "-----BEGIN OPENSSH PRIVATE KEY-----",
    "-----begin ec private key-----",
])
def test_selected_private_key_markers_refuse_publication_even_if_masked(tmp_path, private):
    source = tmp_path / "source"
    source.mkdir()
    (source / "build-log.txt").write_text("::add-mask::" + private + "\n" + private + "\nnot a key fixture\n")
    output = tmp_path / "public"
    with pytest.raises(CORE.LabError, match="private key"):
        CORE.pack_evidence(source, output)
    assert not output.exists()


@pytest.mark.parametrize("kind", ["duplicate-json", "nonfinite-json", "invalid-utf8", "linked-file", "linked-directory", "invalid-png", "empty"])
def test_evidence_refuses_unsafe_selected_inputs_before_creating_output(tmp_path, kind):
    source = tmp_path / "source"
    source.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "gate.log").write_text("outside untouched\n")
    if kind == "duplicate-json":
        (source / "comparison.json").write_text('{"x":1,"x":2}')
    elif kind == "nonfinite-json":
        (source / "comparison.json").write_text('{"x":NaN}')
    elif kind == "invalid-utf8":
        (source / "build-log.txt").write_bytes(b"\xff")
    elif kind == "linked-file":
        (source / "build-log.txt").symlink_to(outside / "gate.log")
    elif kind == "linked-directory":
        (source / "control").symlink_to(outside, target_is_directory=True)
    elif kind == "invalid-png":
        (source / "control/screenshots").mkdir(parents=True)
        (source / "control/screenshots/ready.png").write_bytes(b"not PNG")
    output = tmp_path / "public"
    with pytest.raises((CORE.LabError, OSError, UnicodeError)):
        CORE.pack_evidence(source, output)
    assert not output.exists()
    assert (outside / "gate.log").read_text() == "outside untouched\n"


def test_evidence_aggregate_limit_has_exact_positive_boundary(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    (source / "build-log.txt").write_bytes(b"public\n")
    monkeypatch.setattr(CORE, "MAX_EVIDENCE", 7)
    assert CORE.pack_evidence(source, tmp_path / "accepted")["bytes"] == 7
    monkeypatch.setattr(CORE, "MAX_EVIDENCE", 6)
    with pytest.raises(CORE.LabError, match="aggregate limit"):
        CORE.pack_evidence(source, tmp_path / "refused")
    assert not (tmp_path / "refused").exists()


def test_evidence_destination_must_be_new_and_outside_source(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "build-log.txt").write_text("public\n")
    existing = tmp_path / "existing"
    existing.mkdir()
    (existing / "keep").write_text("keep")
    for output in (source, source / "nested", existing):
        with pytest.raises(CORE.LabError, match="new and separate"):
            CORE.pack_evidence(source, output)
    assert (existing / "keep").read_text() == "keep"


def test_sealing_computes_real_file_hashes_and_archive_consumes_sealed_inventory(tmp_path, bundle):
    manifest, members = bundle
    transfer = tmp_path / "transfer"
    transfer.mkdir(mode=0o700)
    for name, data in members.items():
        path = transfer / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    manifest["files"] = []
    CORE.write_json(transfer / "manifest.json", manifest)
    sealed = CORE.seal_transfer(transfer)
    inventory = {row["path"]: row for row in sealed["files"]}
    assert set(inventory) == set(members)
    for name, data in members.items():
        assert inventory[name] == {
            "path": name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
        }
    assert CORE.read_json(transfer / "manifest.json") == sealed
    archive = SMOKE.write_archive(tmp_path / "sealed.zip", sealed, members)
    assert CORE.verify_archive(archive)["producer"] == dict(identity(), job_id=701)


@pytest.mark.parametrize("unsafe", ["link", "directory", "private", "package-tamper"])
def test_sealing_refuses_unselected_linked_private_or_inconsistent_state(tmp_path, bundle, unsafe):
    manifest, members = bundle
    transfer = tmp_path / "transfer"
    transfer.mkdir()
    for name, data in members.items():
        path = transfer / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    CORE.write_json(transfer / "manifest.json", manifest)
    if unsafe == "link":
        path = transfer / "toolchain.txt"
        path.unlink()
        outside = tmp_path / "outside"
        outside.write_bytes(b"outside")
        path.symlink_to(outside)
    elif unsafe == "directory":
        (transfer / "raw-state").mkdir()
    elif unsafe == "private":
        (transfer / "public-key.asc").write_bytes(
            b"-----BEGIN PGP PUBLIC KEY BLOCK-----\nPRIVATE KEY\n-----END PGP PUBLIC KEY BLOCK-----"
        )
    else:
        (transfer / "rpms/control/mesa-test.rpm").write_bytes(b"wrong immutable package bytes")
    before = (transfer / "manifest.json").read_bytes()
    with pytest.raises((CORE.LabError, OSError)):
        CORE.seal_transfer(transfer)
    assert (transfer / "manifest.json").read_bytes() == before


@pytest.mark.parametrize("name,limit", [
    ("build-report.json", 4 * 1024 ** 2), ("public-key.asc", 65536),
])
def test_manifest_member_byte_limits_refuse_one_byte_over_without_allocating_large_files(bundle, name, limit):
    manifest, _ = bundle
    row = next(row for row in manifest["files"] if row["path"] == name)
    row["bytes"] = limit
    assert next(record for record in CORE.validate_manifest(manifest)["files"] if record["path"] == name)["bytes"] == limit
    row["bytes"] += 1
    with pytest.raises(CORE.LabError, match="exceeds limit"):
        CORE.validate_manifest(manifest)


@pytest.mark.parametrize("body", [b'{"id":1,"id":2}', b'{"id":NaN}', b'[]', b'\xff'])
def test_github_metadata_decoder_does_not_admit_nonobject_or_ambiguous_authority(monkeypatch, body):
    opener = Opener(Response(body))
    monkeypatch.setattr(CORE.request, "build_opener", lambda *args: opener)
    api = CORE.GitHubAPI({"GH_TOKEN": "synthetic-not-a-credential"})
    with pytest.raises(CORE.LabError):
        api("/repos/tuna-os/tunaOS")


@pytest.mark.parametrize("body,expected", [(b"long", 3), (b"short", 6)])
def test_download_bounds_actual_bytes_not_just_metadata(tmp_path, monkeypatch, body, expected):
    opener = Opener(Response(body))
    monkeypatch.setattr(CORE.request, "build_opener", lambda *args: opener)
    api = CORE.GitHubAPI({"GH_TOKEN": "synthetic-not-a-credential"})
    with pytest.raises(CORE.LabError):
        api.download(123, tmp_path / "download", expected)
    assert (tmp_path / "download").stat().st_size <= expected


def test_evidence_screenshot_allowlist_selects_canonical_name_not_other_pngs(tmp_path):
    source = tmp_path / "source"
    screenshots = source / "control/screenshots"
    screenshots.mkdir(parents=True)
    # Header-only synthetic bytes exercise selection, not native PNG decoding.
    png = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + b"\x00" * 17
    (screenshots / "ready.png").write_bytes(png)
    (screenshots / "raw-private.png").write_bytes(png)
    receipt = CORE.pack_evidence(source, tmp_path / "public")
    assert receipt["files"] == ["control/screenshots/ready.png"]
    assert (tmp_path / "public/control/screenshots/ready.png").read_bytes() == png
    assert not (tmp_path / "public/control/screenshots/raw-private.png").exists()


def test_cross_file_masks_redact_decoded_json_strings_with_escaping(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    secret = 'synthetic\\path"suffix'
    (source / "build-log.txt").write_text("::add-mask::" + secret + "\npublic log\n")
    (source / "comparison.json").write_text(json.dumps({
        "nested": [{"credential": secret}], "public": "source-only",
    }))
    output = tmp_path / "public"
    CORE.pack_evidence(source, output)
    assert CORE.read_json(output / "comparison.json") == {
        "nested": [{"credential": "[REDACTED]"}], "public": "source-only",
    }
    assert (output / "build-log.txt").read_text() == "public log\n"


def test_json_unicode_escaping_cannot_hide_private_key_material_from_publication(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "comparison.json").write_bytes(
        b'{"detail":"\\u002d\\u002d\\u002d\\u002d\\u002dBEGIN PRIVATE KEY\\u002d\\u002d\\u002d\\u002d\\u002d"}'
    )
    output = tmp_path / "public"
    with pytest.raises(CORE.LabError, match="private key"):
        CORE.pack_evidence(source, output)
    assert not output.exists()
