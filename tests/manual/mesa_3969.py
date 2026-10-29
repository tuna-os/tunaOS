#!/usr/bin/env python3
"""Fail-closed authority and bounded I/O for the manual Mesa #3969 lab."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import time
import uuid
from urllib import error, parse, request
import zipfile

INPUTS = {
    "baseline_parent": "quay.io/almalinuxorg/almalinux-bootc:10@sha256:5f35f25a97714d2047f2c989995c7001044569150b60527a876ba58ba46657cb",
    "srpm_url": "https://vault.almalinux.org/10.2/AppStream/Source/Packages/mesa-25.2.7-4.el10.alma.5.src.rpm",
    "srpm_sha256": "660d85bbe661b36615f9e8992173920a280f30dbff2678aec46abd6935384b39",
    "source_rpm": "mesa-25.2.7-4.el10.alma.5.src.rpm",
    "patch_url": "https://gitlab.freedesktop.org/mesa/mesa/-/commit/c9b298660774291478323c5ef148362d9b136c3b.patch",
    "patch_sha256": "8334f5c7346c6ffff722017f2ff9a939d4b5e5db3b06590d5b912d479a447149",
    "helper_commit": "0172a317c6213a9bbf8650913d5abf8880d8170b"
}

REPOSITORY = "tuna-os/tunaOS"
REPOSITORY_ID = 1029250013
WORKFLOW_PATH = ".github/workflows/mesa-3969-compare.yml"
BUILD_JOB = "Build signed Mesa pair"
GIB = 1024 ** 3
MAX_ARCHIVE = 24 * GIB
MAX_UNPACKED = 32 * GIB
MAX_JSON = 4 * 1024 ** 2
MAX_EVIDENCE = 32 * 1024 ** 2
SHA = re.compile(r"[0-9a-f]{64}\Z")
HEAD = re.compile(r"[0-9a-f]{40}\Z")
TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9+_.~^-]{0,255}\Z")
PRODUCER_FIELDS = {"repository_id", "repository", "head_sha", "run_id", "run_attempt", "workflow_id", "job_id"}
INVENTORY_FIELDS = {"name", "epoch", "version", "release", "arch", "source_rpm", "header_sha256"}
PACKAGE_FIELDS = INVENTORY_FIELDS | {"path", "sha256", "bytes"}
REQUIRED_FILES = {"baseline.oci.tar", "public-key.asc", "baseline-inventory.json", "buildroot-inventory.json", "buildroot-macros.txt", "toolchain.txt", "build-report.json"}
MARKER = ".mesa3969-owned.json"
LOCAL_MARKER = ".mesa3969-local-owned.json"


class LabError(ValueError):
    """An input cannot establish the lab's declared boundary."""


def require(condition, message):
    if not condition:
        raise LabError(message)


def exact(value, fields, where):
    require(isinstance(value, dict) and set(value) == fields, f"{where}: invalid fields")
    return value


def integer(value, where, low=1, high=2 ** 63 - 1):
    require(type(value) is int and low <= value <= high, f"{where}: invalid integer")
    return value


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, f"duplicate JSON field: {key}")
        result[key] = value
    return result


def decode_json(data, max_bytes=MAX_JSON):
    require(0 < len(data) <= max_bytes, "JSON size outside limit")
    def invalid_constant(value):
        raise LabError(f"non-finite JSON number: {value}")
    try:
        return json.loads(data.decode("utf-8"), object_pairs_hook=unique_object, parse_constant=invalid_constant)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise LabError("invalid UTF-8 JSON") from exc


def read_bytes(path, max_bytes):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        require(stat.S_ISREG(info.st_mode) and info.st_size <= max_bytes, "expected bounded regular file")
        data = stream.read(max_bytes + 1)
    require(len(data) <= max_bytes, "file exceeds limit")
    return data


def read_json(path, max_bytes=MAX_JSON):
    return decode_json(read_bytes(path, max_bytes), max_bytes)


def _json_bytes(value):
    return (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")


def write_json(path, value):
    Path(path).write_bytes(_json_bytes(value))


def sha256_file(path, max_bytes=MAX_UNPACKED):
    digest = hashlib.sha256()
    total = 0
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as stream:
        require(stat.S_ISREG(os.fstat(stream.fileno()).st_mode), "expected regular file")
        while chunk := stream.read(1024 * 1024):
            total += len(chunk)
            require(total <= max_bytes, "file exceeds hash limit")
            digest.update(chunk)
    return digest.hexdigest()


def normalize_image_id(value):
    require(isinstance(value, str), "invalid image identity")
    raw = value.removeprefix("sha256:")
    require(SHA.fullmatch(raw) is not None, "invalid image digest")
    return "sha256:" + raw


def digest(value):
    require(isinstance(value, str), "missing SHA256")
    raw = value.removeprefix("sha256:")
    require(SHA.fullmatch(raw) is not None, "invalid SHA256")
    return raw


def _environment_identity(env):
    require(env.get("GITHUB_REPOSITORY") == REPOSITORY, "official repository required")
    require(env.get("GITHUB_REPOSITORY_ID") == str(REPOSITORY_ID), "official repository ID required")
    head = env.get("GITHUB_SHA", "")
    require(HEAD.fullmatch(head) is not None, "exact checkout head required")
    rid = env.get("GITHUB_RUN_ID", "")
    require(re.fullmatch(r"[1-9][0-9]{0,18}", rid) is not None, "run ID required")
    return {"repository_id": REPOSITORY_ID, "repository": REPOSITORY, "head_sha": head, "run_id": integer(int(rid), "run ID"), "run_attempt": 1}


class NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class GitHubAPI:
    def __init__(self, env):
        self.token = env.get("GH_TOKEN") or env.get("GITHUB_TOKEN")
        require(bool(self.token), "read-only GitHub token required")
        self.opener = request.build_opener(NoRedirect())

    def _request(self, path):
        require(path == f"/repos/{REPOSITORY}" or path.startswith(f"/repos/{REPOSITORY}/"), "invalid API path")
        return request.Request("https://api.github.com" + path, headers={"Authorization": "Bearer " + self.token, "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"})

    def __call__(self, path):
        try:
            with self.opener.open(self._request(path), timeout=30) as response:
                value = decode_json(response.read(MAX_JSON + 1))
                require(isinstance(value, dict), "GitHub metadata must be an object")
                return value
        except error.HTTPError as exc:
            raise LabError(f"GitHub metadata unavailable (HTTP {exc.code})") from exc
        except (error.URLError, TimeoutError) as exc:
            raise LabError("GitHub metadata connection failed") from exc

    def download(self, artifact_id, output, expected_bytes):
        location = None
        try:
            response = self.opener.open(self._request(f"/repos/{REPOSITORY}/actions/artifacts/{artifact_id}/zip"), timeout=30)
        except error.HTTPError as exc:
            require(exc.code == 302, f"artifact redirect refused (HTTP {exc.code})")
            location = exc.headers.get("Location", "")
            parts = parse.urlsplit(location)
            require(parts.scheme == "https" and bool(parts.hostname) and not parts.username and not parts.password and not parts.fragment and parts.port in (None, 443), "unsafe artifact redirect")
            response = None
        except (error.URLError, TimeoutError) as exc:
            raise LabError("artifact API connection failed") from exc
        try:
            if location:
                # No GitHub Authorization header accompanies the signed blob URL.
                response = request.build_opener(NoRedirect()).open(request.Request(location), timeout=30)
            require(response is not None, "missing artifact response")
            deadline = time.monotonic() + 900
            total = 0
            hasher = hashlib.sha256()
            fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with response, os.fdopen(fd, "wb") as stream:
                while chunk := response.read(1024 * 1024):
                    total += len(chunk)
                    require(total <= expected_bytes <= MAX_ARCHIVE and time.monotonic() <= deadline, "artifact download exceeds size/time limit")
                    stream.write(chunk)
                    hasher.update(chunk)
            require(total == expected_bytes, "artifact download size mismatch")
            return hasher.hexdigest()
        except error.HTTPError as exc:
            raise LabError(f"artifact download failed (HTTP {exc.code})") from exc
        except (error.URLError, TimeoutError) as exc:
            raise LabError("artifact download connection failed") from exc


def admit_environment(env=None, api=None, checkout_head=None, *, runtime=False):
    env = os.environ if env is None else env
    identity = _environment_identity(env)
    require(env.get("GITHUB_ACTIONS") == "true", "GitHub Actions manual execution required")
    require(env.get("GITHUB_SERVER_URL") == "https://github.com" and env.get("GITHUB_API_URL") == "https://api.github.com", "official GitHub service required")
    require(env.get("GITHUB_EVENT_NAME") == "workflow_dispatch", "manual workflow_dispatch required")
    require(env.get("GITHUB_RUN_ATTEMPT") == "1", "repeated attempts refused")
    require(env.get("LAB_CONFIRM") == "RUN_MESA_3969_ONCE", "explicit lab confirmation required")
    require(env.get("REVIEWED_HEAD") == identity["head_sha"] == env.get("MESA_3969_APPROVED_HEAD"), "exact owner-approved head required; activation is absent by default")
    if runtime:
        require(env.get("MESA_3969_RUNTIME_APPROVED_HEAD") == identity["head_sha"], "separate exact-head runtime approval required")
    if checkout_head is None:
        result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=env.get("GITHUB_WORKSPACE"), capture_output=True, text=True, timeout=30, check=True)
        checkout_head = result.stdout.strip()
    require(checkout_head == identity["head_sha"], "checked-out source differs from approved head")
    api = GitHubAPI(env) if api is None else api
    repo = api(f"/repos/{REPOSITORY}")
    require(isinstance(repo, dict) and type(repo.get("id")) is int and repo.get("id") == REPOSITORY_ID and repo.get("full_name") == REPOSITORY and repo.get("fork") is False, "API repository identity mismatch")
    run = api(f"/repos/{REPOSITORY}/actions/runs/{identity['run_id']}")
    require(isinstance(run, dict), "current run metadata must be an object")
    for key, expected in (("id", identity["run_id"]), ("head_sha", identity["head_sha"]), ("run_attempt", 1), ("event", "workflow_dispatch"), ("status", "in_progress"), ("path", WORKFLOW_PATH)):
        require(run.get(key) == expected and (not isinstance(expected, int) or type(run.get(key)) is int), f"current run {key} mismatch")
    require(all(isinstance(run.get(key), dict) and type(run[key].get("id")) is int and run[key].get("id") == REPOSITORY_ID for key in ("repository", "head_repository")), "run repository mismatch")
    identity["workflow_id"] = integer(run.get("workflow_id"), "workflow ID")
    query = parse.urlencode({"head_sha": identity["head_sha"], "event": "workflow_dispatch", "per_page": 100})
    listing = api(f"/repos/{REPOSITORY}/actions/workflows/{identity['workflow_id']}/runs?{query}")
    require(isinstance(listing, dict), "run listing must be an object")
    rows = listing.get("workflow_runs")
    count = integer(listing.get("total_count"), "run count", high=100)
    require(isinstance(rows, list) and len(rows) == count == 1, "head already consumed or run listing incomplete")
    selected = rows[0]
    require(isinstance(selected, dict), "selected run must be an object")
    for key in ("id", "workflow_id", "run_attempt"):
        integer(selected.get(key), f"selected run {key}")
    require(selected.get("id") == identity["run_id"] and selected.get("head_sha") == identity["head_sha"] and selected.get("workflow_id") == identity["workflow_id"] and selected.get("event") == "workflow_dispatch" and selected.get("run_attempt") == 1, "prior or inconsistent head attempt refused")
    return identity


def build_job(identity, api, completed=False):
    data = api(f"/repos/{REPOSITORY}/actions/runs/{identity['run_id']}/jobs?filter=all&per_page=100")
    require(isinstance(data, dict), "job listing must be an object")
    rows = data.get("jobs")
    count = integer(data.get("total_count"), "job count", high=100)
    require(isinstance(rows, list) and len(rows) == count, "incomplete job listing")
    require(all(isinstance(job, dict) for job in rows), "job records must be objects")
    selected = [job for job in rows if job.get("name") == BUILD_JOB]
    require(len(selected) == 1, "unique Mesa producer job required")
    job = selected[0]
    integer(job.get("run_id"), "job run ID")
    integer(job.get("run_attempt"), "job attempt")
    require(job.get("run_id") == identity["run_id"] and job.get("head_sha") == identity["head_sha"] and job.get("run_attempt") == 1, "producer job identity mismatch")
    require(job.get("status") == ("completed" if completed else "in_progress"), "producer job state mismatch")
    if completed:
        require(job.get("conclusion") == "success", "producer job did not succeed")
    return integer(job.get("id"), "producer job ID")


def validate_producer(value, expected=None):
    item = exact(value, PRODUCER_FIELDS, "producer")
    require(type(item["repository_id"]) is int and item["repository_id"] == REPOSITORY_ID and item["repository"] == REPOSITORY, "producer repository mismatch")
    require(isinstance(item["head_sha"], str) and HEAD.fullmatch(item["head_sha"]) is not None, "producer head invalid")
    require(type(item["run_attempt"]) is int and item["run_attempt"] == 1, "producer retry refused")
    for key in ("run_id", "workflow_id", "job_id"):
        integer(item[key], key)
    if expected is not None:
        require(item == expected, "manifest producer differs from live authority")
    return item


def allowed_member(path):
    require(isinstance(path, str) and len(path) <= 512 and "\\" not in path and "\x00" not in path, "unsafe transfer path")
    posix = PurePosixPath(path)
    require(not posix.is_absolute() and str(posix) == path and all(part not in ("", ".", "..") for part in path.split("/")), "noncanonical transfer path")
    require(path in REQUIRED_FILES or re.fullmatch(r"rpms/(?:control|candidate)/[A-Za-z0-9][A-Za-z0-9+_.~-]{0,240}\.rpm", path) is not None, "transfer member is not allowed")
    return path


def validate_package_record(value, arm=None):
    record = exact(value, PACKAGE_FIELDS, "package")
    for key in ("name", "version", "release"):
        require(isinstance(record[key], str) and TOKEN.fullmatch(record[key]) is not None, f"invalid package {key}")
    integer(record["epoch"], "package epoch", low=0, high=2 ** 32 - 1)
    require(record["arch"] in ("x86_64", "noarch"), "unexpected package architecture")
    require(record["source_rpm"] == INPUTS["source_rpm"], "Mesa source drift")
    require(isinstance(record["header_sha256"], str) and SHA.fullmatch(record["header_sha256"]) is not None, "immutable RPM header SHA256 required")
    require(isinstance(record["sha256"], str) and SHA.fullmatch(record["sha256"]) is not None, "package SHA256 required")
    integer(record["bytes"], "package bytes", high=MAX_UNPACKED)
    allowed_member(record["path"])
    if arm:
        require(record["path"].startswith(f"rpms/{arm}/"), "package arm path mismatch")
    return record


def validate_local_authority(value):
    local = exact(value, {"schema_version", "kind", "operation_id", "head_sha", "owner_uid", "host", "started_at", "checkout"}, "local build authority")
    require(type(local["schema_version"]) is int and local["schema_version"] == 1 and local["kind"] == "mesa3969-local-build", "unsupported local authority")
    require(isinstance(local["operation_id"], str) and re.fullmatch(r"[0-9a-f]{32}", local["operation_id"]) is not None, "invalid local operation identity")
    require(isinstance(local["head_sha"], str) and HEAD.fullmatch(local["head_sha"]) is not None, "invalid local source head")
    integer(local["owner_uid"], "local owner UID", low=0, high=2 ** 32 - 1)
    integer(local["started_at"], "local start time")
    require(isinstance(local["host"], str) and re.fullmatch(r"[A-Za-z0-9_.-]{1,255}", local["host"]) is not None, "invalid local host identity")
    checkout = local["checkout"]
    require(isinstance(checkout, str) and Path(checkout).is_absolute() and ".." not in Path(checkout).parts and not any(ord(c) < 32 for c in checkout), "invalid local checkout identity")
    return local


def authorize_local_build(repository, reviewed_head, confirmation):
    require(confirmation == "BUILD_MESA3969_LOCAL_ONLY", "explicit local build-only confirmation required")
    require(os.environ.get("GITHUB_ACTIONS") != "true", "local authority cannot substitute for hosted admission")
    require(isinstance(reviewed_head, str) and HEAD.fullmatch(reviewed_head) is not None, "exact local reviewed head required")
    repository = _safe_ancestry(repository)
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repository, capture_output=True, text=True, timeout=30, check=True).stdout.strip()
    require(head == reviewed_head, "local checked-out source differs from reviewed head")
    clean = subprocess.run(["git", "diff", "--quiet", "--no-ext-diff", "HEAD", "--", "tests/manual"], cwd=repository, capture_output=True, timeout=30, check=False)
    require(clean.returncode == 0, "local runtime source differs from the reviewed commit")
    tree = subprocess.run(["git", "ls-tree", "-rz", "HEAD", "--", "tests/manual"], cwd=repository, capture_output=True, timeout=30, check=True).stdout
    paths = []
    expected = []
    for entry in tree.split(b"\0"):
        if not entry:
            continue
        metadata, filename = entry.split(b"\t", 1)
        mode, kind, object_id = metadata.decode("ascii").split()
        relative = filename.decode("utf-8")
        path = repository / relative
        _safe_ancestry(path.parent)
        info = path.lstat()
        require(kind == "blob" and mode in ("100644", "100755") and stat.S_ISREG(info.st_mode), "runtime source must be tracked regular files")
        require(bool(info.st_mode & 0o111) == (mode == "100755"), "runtime source mode differs from reviewed commit")
        paths.append(relative)
        expected.append(object_id)
    required = {f"tests/manual/{name}" for name in ("mesa_3969.py", "mesa_3969_packages.py", "mesa_3969_guest.py", "mesa-3969-build.sh", "mesa-3969-probe.service")}
    require(required <= set(paths), "reviewed commit lacks required lab runtime source")
    # hash-object reads actual bytes, ignoring assume-unchanged/skip-worktree
    # flags and clean filters that can conceal a dirty runtime from git diff.
    actual = subprocess.run(["git", "hash-object", "--no-filters", "--", *paths], cwd=repository, capture_output=True, text=True, timeout=30, check=True)
    require(actual.stdout.splitlines() == expected, "runtime source bytes differ from reviewed commit")
    return validate_local_authority({
        "schema_version": 1, "kind": "mesa3969-local-build", "operation_id": uuid.uuid4().hex,
        "head_sha": head, "owner_uid": _owner_uid(), "host": os.uname().nodename,
        "started_at": int(time.time()), "checkout": str(repository),
    })


def validate_manifest(value, expected_producer=None):
    item = exact(value, {"schema_version", "kind", "producer", "inputs", "baseline", "buildroot", "signer", "probe", "arms", "files"}, "manifest")
    require(type(item["schema_version"]) is int and item["schema_version"] == 1 and item["kind"] == "mesa3969-inputs", "unsupported manifest schema")
    producer = validate_producer(item["producer"], expected_producer)
    return _validate_manifest_payload(item, str(producer["run_id"]), producer["head_sha"])


def validate_local_manifest(value, expected_local):
    local = validate_local_authority(expected_local)
    item = exact(value, {"schema_version", "kind", "local", "inputs", "baseline", "buildroot", "signer", "probe", "arms", "files"}, "local manifest")
    require(type(item["schema_version"]) is int and item["schema_version"] == 1 and item["kind"] == "mesa3969-local-inputs", "unsupported local manifest schema")
    require(validate_local_authority(item["local"]) == local, "local manifest authority differs from owned operation")
    return _validate_manifest_payload(item, "local-" + local["operation_id"], local["head_sha"])


def _validate_manifest_payload(item, namespace, head_sha):
    require(item["inputs"] == INPUTS, "fixed experiment input drift")
    base = exact(item["baseline"], {"parent", "raw_image_id", "image_id", "image_tag", "inventory", "software_policy_sha256"}, "baseline")
    require(base["parent"] == INPUTS["baseline_parent"] and base["inventory"] == "baseline-inventory.json", "baseline parent/inventory drift")
    for key in ("raw_image_id", "image_id"):
        require(normalize_image_id(base[key]) == base[key], "noncanonical baseline image identity")
    require(isinstance(base["image_tag"], str) and re.fullmatch(r"localhost/[a-z0-9][a-z0-9._/-]*:[A-Za-z0-9._-]+", base["image_tag"]) is not None and namespace in base["image_tag"] and head_sha[:8] in base["image_tag"], "unique owned baseline tag required")
    require(isinstance(base["software_policy_sha256"], str) and SHA.fullmatch(base["software_policy_sha256"]) is not None, "software policy identity required")
    root = exact(item["buildroot"], {"image_id", "inventory", "macros", "toolchain"}, "buildroot")
    require(normalize_image_id(root["image_id"]) == root["image_id"], "noncanonical buildroot image")
    require((root["inventory"], root["macros"], root["toolchain"]) == ("buildroot-inventory.json", "buildroot-macros.txt", "toolchain.txt"), "buildroot evidence drift")
    signer = exact(item["signer"], {"fingerprint", "public_key"}, "signer")
    require(isinstance(signer["fingerprint"], str) and re.fullmatch(r"[0-9A-F]{40}", signer["fingerprint"]) is not None and signer["public_key"] == "public-key.asc", "isolated signing key identity required")
    probe = exact(item["probe"], {"helper_commit", "source_sha256", "binary_sha256"}, "probe")
    require(probe["helper_commit"] == INPUTS["helper_commit"], "probe helper drift")
    for key in ("source_sha256", "binary_sha256"):
        require(isinstance(probe[key], str) and SHA.fullmatch(probe[key]) is not None, "probe hash required")
    arms = exact(item["arms"], {"control", "candidate"}, "arms")
    arm_sets = []
    packages_by_path = {}
    for name, arm in arms.items():
        exact(arm, {"buildroot_image_id", "generated_srpm_sha256", "packages"}, name)
        require(arm["buildroot_image_id"] == root["image_id"], "arm buildroot differs")
        require(isinstance(arm["generated_srpm_sha256"], str) and SHA.fullmatch(arm["generated_srpm_sha256"]) is not None, "generated source RPM identity required")
        require(isinstance(arm["packages"], list) and 0 < len(arm["packages"]) <= 1000, "complete bounded package set required")
        identities = set()
        for package in arm["packages"]:
            validate_package_record(package, name)
            identity = tuple(package[key] for key in ("name", "epoch", "version", "release", "arch", "source_rpm"))
            require(identity not in identities and package["path"] not in packages_by_path, "duplicate package identity/path")
            identities.add(identity)
            packages_by_path[package["path"]] = package
        arm_sets.append(identities)
    require(arm_sets[0] == arm_sets[1], "control/candidate output sets differ")
    require(isinstance(item["files"], list) and 0 < len(item["files"]) <= 2048, "bounded file inventory required")
    files = {}
    total = 0
    for record in item["files"]:
        exact(record, {"path", "bytes", "sha256"}, "file")
        path = allowed_member(record["path"])
        require(path not in files and isinstance(record["sha256"], str) and SHA.fullmatch(record["sha256"]) is not None, "duplicate file or invalid hash")
        total += integer(record["bytes"], "file bytes", high=MAX_UNPACKED)
        require(total <= MAX_UNPACKED, "transfer unpacked size exceeds limit")
        if path.endswith(".json"):
            require(record["bytes"] <= MAX_JSON, "JSON member exceeds limit")
        if path == "public-key.asc":
            require(record["bytes"] <= 65536, "public key exceeds limit")
        files[path] = record
    require(set(files) == REQUIRED_FILES | set(packages_by_path), "transfer member inventory incomplete or unexpected")
    for path, package in packages_by_path.items():
        require((files[path]["bytes"], files[path]["sha256"]) == (package["bytes"], package["sha256"]), "RPM identity differs from file inventory")
    return item


def _owner_uid():
    if os.geteuid() == 0 and "SUDO_UID" in os.environ:
        return integer(int(os.environ["SUDO_UID"]), "sudo caller UID", low=0, high=2 ** 32 - 1)
    return os.geteuid()


def _safe_ancestry(path):
    path = Path(path)
    require(path.is_absolute() and all(part not in ("..", ".") for part in path.parts) and not any(ord(c) < 32 for c in str(path)), "unsafe absolute owned path")
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        info = current.lstat()
        require(stat.S_ISDIR(info.st_mode) and not stat.S_ISLNK(info.st_mode), "owned path has unsafe ancestry")
    return path


def owned_path(parent, role, identity):
    require(role in ("build", "runtime"), "invalid owned role")
    parent = _safe_ancestry(parent)
    rid = integer(identity["run_id"], "owned run ID")
    require(HEAD.fullmatch(identity["head_sha"]) is not None and identity["repository_id"] == REPOSITORY_ID, "owned identity invalid")
    return parent / f"mesa-3969-{rid}-{role}"


def create_owned_root(parent, role, identity):
    root = owned_path(parent, role, identity)
    root.mkdir(mode=0o700)
    uid = _owner_uid()
    marker = {"schema_version": 1, "repository_id": REPOSITORY_ID, "run_id": identity["run_id"], "head_sha": identity["head_sha"], "role": role, "uid": uid}
    write_json(root / MARKER, marker)
    os.chmod(root / MARKER, 0o600)
    if os.geteuid() == 0:
        os.chown(root / MARKER, uid, -1)
        os.chown(root, uid, -1)
    return root


def check_owned_root(parent, role, identity):
    root = owned_path(parent, role, identity)
    _safe_ancestry(root)
    info = root.lstat()
    uid = _owner_uid()
    require(info.st_uid == uid and stat.S_IMODE(info.st_mode) == 0o700, "owned root owner/mode mismatch")
    marker = read_json(root / MARKER)
    require(isinstance(marker, dict) and all(type(marker.get(key)) is int for key in ("schema_version", "repository_id", "run_id", "uid")), "owned marker types invalid")
    require(marker == {"schema_version": 1, "repository_id": REPOSITORY_ID, "run_id": identity["run_id"], "head_sha": identity["head_sha"], "role": role, "uid": uid}, "owned marker mismatch")
    require((root / MARKER).lstat().st_uid == uid, "marker owner mismatch")
    return root


def cleanup_owned_root(parent, role, identity, child=None):
    root = owned_path(parent, role, identity)
    if not root.exists() and not root.is_symlink():
        return
    root = check_owned_root(parent, role, identity)
    require(shutil.rmtree.avoids_symlink_attacks, "safe directory removal unsupported")
    if child is None:
        shutil.rmtree(root)
    else:
        require(child == "work", "only private work child may be removed")
        path = root / child
        if path.is_symlink():
            raise LabError("private work root is a symlink")
        if path.exists():
            require(path.is_dir(), "private work root is not a directory")
            shutil.rmtree(path)


def create_local_build_root(base, local):
    local = validate_local_authority(local)
    require(local["owner_uid"] == _owner_uid() and local["host"] == os.uname().nodename, "local root must belong to this caller and host")
    root = _safe_ancestry(base) / f"mesa-3969-local-{local['operation_id']}-build"
    root.mkdir(mode=0o700)
    write_json(root / LOCAL_MARKER, {"schema_version": 1, "role": "local-build", "path": str(root), "local": local})
    os.chmod(root / LOCAL_MARKER, 0o600)
    if os.geteuid() == 0:
        os.chown(root / LOCAL_MARKER, local["owner_uid"], -1)
        os.chown(root, local["owner_uid"], -1)
    return root


def check_local_build_root(root, local):
    local = validate_local_authority(local)
    root = _safe_ancestry(root)
    uid = _owner_uid()
    require(root.name == f"mesa-3969-local-{local['operation_id']}-build" and local["owner_uid"] == uid and local["host"] == os.uname().nodename, "local root identity mismatch")
    info = root.lstat()
    require(info.st_uid == uid and stat.S_IMODE(info.st_mode) == 0o700, "local root owner/mode mismatch")
    marker = root / LOCAL_MARKER
    require(read_json(marker) == {"schema_version": 1, "role": "local-build", "path": str(root), "local": local}, "local root marker mismatch")
    marker_info = marker.lstat()
    require(marker_info.st_uid == uid and stat.S_IMODE(marker_info.st_mode) == 0o600, "local marker owner/mode mismatch")
    return root


def cleanup_local_build_root(root, local, child=None):
    root = Path(root)
    if not root.exists() and not root.is_symlink():
        return
    root = check_local_build_root(root, local)
    require(shutil.rmtree.avoids_symlink_attacks, "safe directory removal unsupported")
    if child is None:
        shutil.rmtree(root)
    else:
        require(child == "work", "only private work child may be removed")
        path = root / child
        require(not path.is_symlink(), "private work root is a symlink")
        if path.exists():
            require(path.is_dir(), "private work root is not a directory")
            shutil.rmtree(path)


def validate_public_key(data):
    require(0 < len(data) <= 65536 and data.startswith(b"-----BEGIN PGP PUBLIC KEY BLOCK-----") and b"-----END PGP PUBLIC KEY BLOCK-----" in data and b"PRIVATE KEY" not in data, "public-key material invalid")


def seal_transfer(directory):
    return _seal_transfer(directory, "manifest.json", validate_manifest)


def seal_local_transfer(directory, expected_local):
    validate_local_authority(expected_local)
    return _seal_transfer(directory, "local-manifest.json", lambda value: validate_local_manifest(value, expected_local))


def _stored_zip_member_bound(name, size):
    # cf430e0 upload-artifact uses STORE at level 0. Reserve both Zip64 extras,
    # the longest descriptor, and both UTF-8 filenames without copying payloads.
    return size + 30 + 46 + 24 + 28 + 28 + 2 * len(name.encode("utf-8"))


def _transfer_file_records(directory, manifest_name):
    directory = _safe_ancestry(directory)
    records = []
    for path in sorted(directory.rglob("*")):
        require(not path.is_symlink(), "linked transfer member refused")
        relative = path.relative_to(directory).as_posix()
        if path.is_dir():
            require(relative in ("rpms", "rpms/control", "rpms/candidate"), "unexpected transfer directory")
            continue
        if relative == manifest_name:
            continue
        require(stat.S_ISREG(path.lstat().st_mode), "transfer member is not a regular file")
        allowed_member(relative)
        records.append({"path": relative, "bytes": path.stat().st_size, "sha256": sha256_file(path)})
    return records


def verify_transfer_files(directory, manifest, manifest_name):
    actual = {row["path"]: row for row in _transfer_file_records(directory, manifest_name)}
    expected = {row["path"]: row for row in manifest["files"]}
    require(actual == expected, "sealed transfer member inventory, size or hash changed")


def _seal_transfer(directory, manifest_name, validate):
    directory = _safe_ancestry(directory)
    manifest = read_json(directory / manifest_name)
    validate_public_key(read_bytes(directory / "public-key.asc", 65536))
    records = _transfer_file_records(directory, manifest_name)
    manifest["files"] = records
    validate(manifest)
    encoded = _json_bytes(manifest)
    require(len(encoded) <= MAX_JSON, "serialized manifest exceeds JSON limit")
    # Zip64 EOCD + locator + ordinary EOCD: 56 + 20 + 22 bytes.
    archive_bound = 98 + _stored_zip_member_bound(manifest_name, len(encoded))
    archive_bound += sum(_stored_zip_member_bound(row["path"], row["bytes"]) for row in records)
    require(archive_bound <= MAX_ARCHIVE, "archive transport upper bound exceeds limit")
    (directory / manifest_name).write_bytes(encoded)
    return manifest


def verify_archive(archive, expected_producer=None, destination=None):
    require(Path(archive).stat().st_size <= MAX_ARCHIVE, "archive exceeds limit")
    with zipfile.ZipFile(archive) as zipped:
        infos = zipped.infolist()
        require(0 < len(infos) <= 2048, "archive member count exceeds limit")
        files = {}
        seen = set()
        total = 0
        for info in infos:
            name = info.filename
            require(name not in seen and not info.flag_bits & 1, "duplicate/encrypted ZIP entry")
            seen.add(name)
            mode = stat.S_IFMT(info.external_attr >> 16)
            require(mode in (0, stat.S_IFREG, stat.S_IFDIR), "linked/nonregular ZIP member")
            if info.is_dir():
                require(mode in (0, stat.S_IFDIR) and name in ("rpms/", "rpms/control/", "rpms/candidate/") and info.file_size == 0, "unsafe ZIP directory")
                continue
            require(mode in (0, stat.S_IFREG) and info.compress_type in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED), "unsupported ZIP member type")
            if name != "manifest.json":
                allowed_member(name)
            else:
                require(info.file_size <= MAX_JSON, "manifest exceeds limit")
            total += info.file_size
            require(total <= MAX_UNPACKED + MAX_JSON, "archive unpacked size exceeds limit")
            files[name] = info
        require("manifest.json" in files, "missing manifest")
        with zipped.open(files["manifest.json"]) as stream:
            manifest_data = stream.read(MAX_JSON + 1)
        manifest = validate_manifest(decode_json(manifest_data), expected_producer)
        inventory = {row["path"]: row for row in manifest["files"]}
        require(set(files) == {"manifest.json"} | set(inventory), "archive member set differs from manifest")
        for name, info in files.items():
            expected_size = len(manifest_data) if name == "manifest.json" else inventory[name]["bytes"]
            require(info.file_size == expected_size, "ZIP member size differs from manifest")
        with zipped.open(files["public-key.asc"]) as stream:
            validate_public_key(stream.read(65537))
        output = None
        if destination is not None:
            destination = Path(destination)
            _safe_ancestry(destination.parent)
            require(not destination.exists() and not destination.is_symlink(), "extraction destination must be new")
            required = sum(row["bytes"] for row in inventory.values()) + MAX_JSON + 2 * GIB
            require(shutil.disk_usage(destination.parent).free >= required, "insufficient extraction space")
            destination.mkdir(mode=0o700)
            output = destination
        try:
            for name, info in files.items():
                record = {"bytes": len(manifest_data), "sha256": hashlib.sha256(manifest_data).hexdigest()} if name == "manifest.json" else inventory[name]
                require(info.file_size == record["bytes"], "ZIP member size differs from manifest")
                hasher = hashlib.sha256()
                size = 0
                target = None
                if output is not None:
                    path = output / name
                    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                    target = os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600), "wb")
                try:
                    with zipped.open(info) as source:
                        while chunk := source.read(1024 * 1024):
                            size += len(chunk)
                            require(size <= record["bytes"], "member exceeds declared size")
                            hasher.update(chunk)
                            if target is not None:
                                target.write(chunk)
                    require(size == record["bytes"] and hasher.hexdigest() == record["sha256"], "member size/hash mismatch")
                finally:
                    if target is not None:
                        target.close()
            return manifest
        except BaseException:
            if output is not None:
                shutil.rmtree(output)
            raise


def artifact_name(identity):
    return f"mesa3969-inputs-{identity['run_id']}-{identity['head_sha']}"


def fetch_inputs(artifact_id, upload_digest, destination, env=None):
    env = os.environ if env is None else env
    api = GitHubAPI(env)
    identity = admit_environment(env, api, runtime=True)
    expected = dict(identity, job_id=build_job(identity, api, completed=True))
    artifact_id = integer(artifact_id, "artifact ID")
    artifact = api(f"/repos/{REPOSITORY}/actions/artifacts/{artifact_id}")
    require(type(artifact.get("id")) is int and artifact.get("id") == artifact_id and artifact.get("name") == artifact_name(identity) and artifact.get("expired") is False, "artifact identity/expiry mismatch")
    run = artifact.get("workflow_run", {})
    require(isinstance(run, dict) and all(type(run.get(key)) is int for key in ("id", "repository_id", "head_repository_id")), "artifact run metadata invalid")
    require(run.get("id") == identity["run_id"] and run.get("head_sha") == identity["head_sha"] and run.get("repository_id") == REPOSITORY_ID and run.get("head_repository_id") == REPOSITORY_ID, "cross-run/head artifact refused")
    expected_bytes = integer(artifact.get("size_in_bytes"), "artifact size", high=MAX_ARCHIVE)
    expected_digest = digest(upload_digest)
    require(digest(artifact.get("digest")) == expected_digest, "independent upload digest differs from API")
    root = check_owned_root(env["RUNNER_TEMP"], "runtime", identity)
    destination = Path(destination)
    require(destination == root / "work/inputs", "fixed runtime input destination required")
    _safe_ancestry(destination.parent)
    require(shutil.disk_usage(destination.parent).free >= expected_bytes + 2 * GIB, "insufficient download space")
    archive = destination.parent / "inputs.zip"
    require(api.download(artifact_id, archive, expected_bytes) == expected_digest, "artifact archive digest mismatch")
    # Confirm the same live run/job after transport, before consumption.
    after = admit_environment(env, api, runtime=True)
    require(after == identity and build_job(identity, api, completed=True) == expected["job_id"], "producer changed during transfer")
    manifest = verify_archive(archive, expected, destination)
    archive.unlink()
    return {"directory": str(destination), "manifest": str(destination / "manifest.json"), "producer": manifest["producer"], "authority": "live_same_run"}


def mask_secrets(text):
    values = []
    for line in text.splitlines():
        if "::add-mask::" in line:
            value = line.split("::add-mask::", 1)[1]
            if value:
                values.append(value)
                values.append(value.replace("%0D", "\r").replace("%0A", "\n").replace("%25", "%"))
    return values


def sanitize_text(text, secrets=()):
    require(isinstance(text, str), "text evidence required")
    private_key = re.compile(r"(?:BEGIN[^\n]*PRIVATE KEY|PRIVATE KEY-----|OPENSSH PRIVATE KEY)", re.I)
    require(private_key.search(text) is None, "private key in evidence refused")
    values = set(secrets) | set(mask_secrets(text))
    text = "".join(line for line in text.splitlines(keepends=True) if "::add-mask::" not in line)
    for value in sorted(values, key=len, reverse=True):
        if value:
            text = text.replace(value, "[REDACTED]")
    require(private_key.search(text) is None, "private key in evidence refused")
    return text


def _json_strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, child in value.items():
            yield key
            yield from _json_strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from _json_strings(child)


def _sanitize_json(value, secrets):
    if isinstance(value, str):
        return sanitize_text(value, secrets)
    if isinstance(value, list):
        return [_sanitize_json(child, secrets) for child in value]
    if isinstance(value, dict):
        result = {}
        for key, child in value.items():
            safe_key = sanitize_text(key, secrets)
            require(safe_key not in result, "redacted JSON keys collide")
            result[safe_key] = _sanitize_json(child, secrets)
        return result
    return value


def _evidence_names():
    result = {"build-log.txt", "build-report.json", "comparison.json"}
    for arm in ("control", "candidate"):
        result |= {f"{arm}/{name}" for name in ("report.json", "gate.log", "probe.json", "renderer.json", "serial.log", "greeter-graphics.txt", "vm-host-evidence.txt")}
        result |= {f"{arm}/screenshots/{name}.png" for name in ("ready", "logged-in", "locked", "unlocked")}
    return result


def pack_evidence(source, output):
    source = _safe_ancestry(source)
    output = Path(output)
    _safe_ancestry(output.parent)
    require(not output.exists() and not output.is_symlink() and output != source and source not in output.parents, "evidence destination must be new and separate")
    selected = {}
    secrets = []
    json_values = {}
    for name in sorted(_evidence_names()):
        path = source / name
        if not path.exists() and not path.is_symlink():
            continue
        _safe_ancestry(path.parent)
        limit = 4 * 1024 ** 2 if path.suffix in (".json", ".png") else 8 * 1024 ** 2
        data = read_bytes(path, limit)
        if path.suffix == ".png":
            require(data.startswith(b"\x89PNG\r\n\x1a\n") and len(data) >= 33 and data[12:16] == b"IHDR", "invalid screenshot")
        else:
            if path.suffix == ".json":
                json_values[name] = decode_json(data)
                for text in _json_strings(json_values[name]):
                    secrets.extend(mask_secrets(text))
            else:
                secrets.extend(mask_secrets(data.decode("utf-8")))
        selected[name] = data
    require(bool(selected), "no selected evidence")
    safe = {}
    for name, data in selected.items():
        if name.endswith(".json"):
            value = _sanitize_json(json_values[name], secrets)
            safe[name] = (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")
        elif name.endswith(".png"):
            safe[name] = data
        else:
            safe[name] = sanitize_text(data.decode("utf-8"), secrets).encode("utf-8")
    require(sum(map(len, safe.values())) <= MAX_EVIDENCE, "evidence exceeds aggregate limit")
    output.mkdir(mode=0o700)
    uid = _owner_uid()
    for name, data in safe.items():
        path = output / name
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
    if os.geteuid() == 0:
        for path in output.rglob("*"):
            os.chown(path, uid, -1, follow_symlinks=False)
        os.chown(output, uid, -1)
    return {"files": sorted(safe), "bytes": sum(map(len, safe.values())), "directory": str(output)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("inputs")
    admission = commands.add_parser("admit")
    admission.add_argument("--runtime", action="store_true")
    producer = commands.add_parser("producer")
    producer.add_argument("--job-name", default=BUILD_JOB, choices=[BUILD_JOB])
    for name in ("init-root", "validate-root", "cleanup", "cleanup-child"):
        part = commands.add_parser(name)
        part.add_argument("--role", choices=["build", "runtime"], required=True)
        if name == "cleanup-child":
            part.add_argument("--child", choices=["work"], required=True)
    seal = commands.add_parser("seal-transfer")
    seal.add_argument("--directory", type=Path, required=True)
    local_seal = commands.add_parser("seal-local-transfer")
    local_seal.add_argument("--directory", type=Path, required=True)
    local_seal.add_argument("--owner", type=Path, required=True)
    fetch = commands.add_parser("fetch-inputs")
    fetch.add_argument("--artifact-id", type=int, required=True)
    fetch.add_argument("--artifact-digest", required=True)
    fetch.add_argument("--destination", type=Path, required=True)
    check = commands.add_parser("check-archive", help="integrity only; does not establish runtime authority")
    check.add_argument("--archive", type=Path, required=True)
    evidence = commands.add_parser("pack-evidence")
    evidence.add_argument("--source", type=Path, required=True)
    evidence.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "inputs":
            result = INPUTS
        elif args.command == "admit":
            result = admit_environment(runtime=args.runtime)
        elif args.command == "producer":
            identity = admit_environment()
            result = dict(identity, job_id=build_job(identity, GitHubAPI(os.environ)))
        elif args.command in ("init-root", "validate-root", "cleanup", "cleanup-child"):
            identity = _environment_identity(os.environ)
            if args.command == "init-root":
                print(create_owned_root(os.environ["RUNNER_TEMP"], args.role, identity))
                return 0
            if args.command == "validate-root":
                print(check_owned_root(os.environ["RUNNER_TEMP"], args.role, identity))
                return 0
            cleanup_owned_root(os.environ["RUNNER_TEMP"], args.role, identity, getattr(args, "child", None))
            result = {"cleanup": "complete", "role": args.role}
        elif args.command == "seal-transfer":
            result = seal_transfer(args.directory)
        elif args.command == "seal-local-transfer":
            result = seal_local_transfer(args.directory, read_json(args.owner))
        elif args.command == "fetch-inputs":
            result = fetch_inputs(args.artifact_id, args.artifact_digest, args.destination)
        elif args.command == "check-archive":
            manifest = verify_archive(args.archive)
            result = {"integrity": "verified", "authority": "not_evaluated", "files": len(manifest["files"])}
        else:
            result = pack_evidence(args.source, args.output)
        print(json.dumps(result, sort_keys=True, allow_nan=False))
        return 0
    except (ValueError, OSError, KeyError, TypeError, subprocess.SubprocessError, zipfile.BadZipFile, RuntimeError, UnicodeError) as exc:
        print(f"Mesa lab refused: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
