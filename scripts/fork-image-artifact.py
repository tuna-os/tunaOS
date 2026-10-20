#!/usr/bin/env python3
"""Bounded, immutable Actions transport for the two original fork canary images.

This is not a build cache: absent/expired/mismatched pins fail closed. Original
receipts remain byte-for-byte intact; newer harness provenance is separate.
"""
import argparse
from contextlib import contextmanager
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import signal
import stat
import struct
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
import zipfile

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = "tuna-os/tunaOS"
WORKFLOW = ".github/workflows/fork-image-qualification.yml"
VARIANTS = ("yellowfin", "grouper")
LIMIT = 5 * 1024**3
PAIR_LIMIT = 10 * 1024**3
METADATA_LIMIT = 16 * 1024**2
MAX_FILES = 8192
ARCHIVE_LIMIT = LIMIT + 16 * 1024**2  # ZIP framing, never additional payload
HEX = re.compile(r"[0-9a-f]{64}\Z")
COMMIT = re.compile(r"[0-9a-f]{40}\Z")
DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
STAGES = ("build", "image_identity", "boot", "base_contract", "installed_checks",
          "source_export", "installed_identity", "wallpaper_defaults", "initramfs_theme", "greeter_profile")
# These files run only on the host or in disposable derived guests. In particular,
# the original-image builder, exporter, compiler and embedded observer are excluded.
HARNESS = frozenset({
    "scripts/fork-image-artifact.py", "scripts/qualify-fork-login.py",
    "scripts/qualify-fork-installer.py", "scripts/qualify-fork-install.py",
    "scripts/qualify-fork-vm.py", "scripts/qualify-fork-disk.py", "scripts/fork-installer-ui.py",
})


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / filename)
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


EXPORT = module("artifact_export", "export-fork-source.py")
COMPILER = module("artifact_compiler", "resolve-fork-config.py")
TRANSPORT = module("artifact_transport", "qualify-fork-installer.py")


def require(value, message):
    if not value:
        raise ValueError(message)


def sha(path):
    with path.open("rb") as stream:
        return "sha256:" + hashlib.file_digest(stream, "sha256").hexdigest()


def read(path):
    require(path.stat().st_size <= METADATA_LIMIT, "artifact metadata exceeds bound")
    return json.loads(path.read_text(), object_pairs_hook=EXPORT.SOURCE.unique)


def write(path, value):
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n")


def new_directory(path):
    require(":" not in str(path), "artifact path must not contain a colon")
    require(not any(p.is_symlink() for p in (path, *path.parents)), "artifact path has symlinked ancestors")
    path.mkdir(parents=True, exist_ok=False)


def manifest_name(variant):
    require(variant in VARIANTS, "unsupported canary variant")
    return f"prepared/{variant}--gnome--linux-amd64/manifests/fork-config.json"


def target(variant):
    return f"localhost/fork-qualification/{variant}:gnome-linux-amd64"


def artifact_name(run_id, variant):
    return f"fork-original-oci-{run_id}-{variant}"


def metadata_names(variant):
    return {manifest_name(variant), "prepared/source-receipt.json", "wallpaper.jpg",
            "oci-export/source-receipt.json", "oci-export/source-manifest.json"}


def permitted_name(name, variant):
    return name in metadata_names(variant) | {"bundle.json", "oci-export/source/index.json", "oci-export/source/oci-layout"} or bool(
        re.fullmatch(r"oci-export/source/blobs/sha256/[0-9a-f]{64}", name))


def validate_receipt(receipt):
    require(isinstance(receipt, dict) and set(receipt) == {"sha256", "files", "modes"}, "malformed original source receipt")
    files, modes = receipt["files"], receipt["modes"]
    require(isinstance(files, dict) and isinstance(modes, dict) and set(files) == set(modes) and files,
            "source receipt file/mode inventory is malformed")
    for name, digest in files.items():
        require(isinstance(name, str) and not PurePosixPath(name).is_absolute() and ".." not in PurePosixPath(name).parts
                and isinstance(digest, str) and HEX.fullmatch(digest) and modes[name] in {"100644", "100755", "120000"},
                "source receipt contains an invalid entry")
    payload = {"files": files, "modes": modes}
    expected = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    require(receipt["sha256"] == expected, "original source receipt digest differs from its inventory")
    return expected


def harness_changes(original, current):
    validate_receipt(original)
    validate_receipt(current)
    changed = sorted(name for name in set(original["files"]) | set(current["files"])
                     if any(original[field].get(name) != current[field].get(name) for field in ("files", "modes")))
    require(set(changed) <= HARNESS, "image-affecting inputs changed; rebuild required: " + ", ".join(set(changed) - HARNESS))
    # Renames, deletion and symlink substitutions are not harness-only updates.
    require(all(name in original["files"] and name in current["files"]
                and original["modes"][name] == current["modes"][name] != "120000"
                for name in changed), "harness path or mode changed; rebuild required")
    return changed


def payload(root, variant):
    """Verify the export and return only the closed original-image file set."""
    require(not any(p.is_symlink() for p in (root, *root.parents)), "payload path has symlinked ancestors")
    receipt = read(EXPORT.regular(root, "oci-export/source-receipt.json"))
    manifest = read(EXPORT.regular(root, manifest_name(variant)))
    original = read(EXPORT.regular(root, "prepared/source-receipt.json"))
    receipt_sha = validate_receipt(original)
    require(manifest.get("variant") == variant and manifest.get("platform") == "linux/amd64"
            and EXPORT.SOURCE.target_ref(manifest) == target(variant), "fork manifest differs from admitted canary")
    require(manifest.get("sources") == {"sha256": receipt_sha}
            and receipt.get("source_receipt") == manifest["sources"], "original compiler authority does not match manifest/export")
    require(receipt.get("schema_version") == 1 and receipt.get("preserved_digest") is True
            and receipt.get("target_imgref") == target(variant)
            and receipt.get("original_local_imgref") == "containers-storage:" + target(variant), "export is not an original canary")
    require(sha(root / manifest_name(variant)) == receipt.get("fork_manifest_sha256"), "fork manifest bytes changed")
    wallpaper = EXPORT.regular(root, "wallpaper.jpg")
    require(wallpaper.stat().st_size <= METADATA_LIMIT and sha(wallpaper).removeprefix("sha256:")
            == manifest.get("assets", {}).get("wallpaper", {}).get("sha256"), "wallpaper differs from original manifest")
    require(sha(root / "oci-export/source-manifest.json") == receipt.get("source_manifest_digest"), "original OCI manifest bytes changed")
    verified = EXPORT.verify_layout(root / "oci-export/source", "linux/amd64",
                                    receipt.get("source_manifest_digest"), receipt.get("source_image_id"))
    require(verified == receipt.get("verified_oci"), "original verified OCI receipt changed")
    descriptors = [verified["manifest_digest"], verified["config_digest"]] + [x["digest"] for x in verified["layers"]]
    names = metadata_names(variant) | {"oci-export/source/index.json", "oci-export/source/oci-layout"}
    names |= {"oci-export/source/blobs/sha256/" + digest.split(":")[1] for digest in descriptors}
    require(len(names) + 1 <= MAX_FILES, "original image file count exceeds artifact bound")
    for name in names:
        file = EXPORT.regular(root, name)
        require(file.stat().st_size <= (LIMIT if "/blobs/" in name else METADATA_LIMIT), "artifact member exceeds bound")
    size = sum((root / name).stat().st_size for name in names)
    require(size + METADATA_LIMIT <= LIMIT, "original image artifact exceeds 5 GiB bound")
    return receipt, original, names, size


def producer_identity():
    require(os.environ.get("GITHUB_REPOSITORY") == REPOSITORY, "producer repository is not admitted")
    run_id = os.environ.get("GITHUB_RUN_ID", "")
    head = os.environ.get("FORK_SOURCE_HEAD", "")
    build = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    require(run_id.isdecimal() and int(run_id) > 0 and COMMIT.fullmatch(head) and COMMIT.fullmatch(build), "producer requires immutable run/head/build identity")
    return {"repository": REPOSITORY, "run_id": int(run_id), "head_sha": head, "build_sha": build}


def validate_observer(observer, original):
    require(isinstance(observer, dict) and set(observer) == {"scope", "maximum_seconds", "observer_sha256", "unit_sha256"}
            and observer["scope"] == "qualification-only-read-only-serial" and observer["maximum_seconds"] == 3600
            and observer["observer_sha256"] == original["files"].get("scripts/fork-install-observer.py")
            and isinstance(observer["unit_sha256"], str) and HEX.fullmatch(observer["unit_sha256"]),
            "original observer receipt is missing or changed")


def package(evidence, output, identity):
    # Validate BOTH before materializing either upload directory.
    records = {}
    for variant in VARIANTS:
        root = evidence / variant
        report = read(EXPORT.regular(root, "qualification.json"))
        require(report.get("variant") == variant and all(report.get(stage) == "passed" for stage in STAGES),
                "original build/boot/export stages must pass before upload")
        receipt, original, names, size = payload(root, variant)
        observer = report.get("target_observer", {})
        validate_observer(observer, original)
        records[variant] = ({"schema_version": 1, "purpose": "original-fork-image", **identity,
                             "variant": variant, "platform": "linux/amd64", "retention_days": 3,
                             "source_manifest_digest": receipt["source_manifest_digest"],
                             "source_image_id": receipt["source_image_id"], "original_source_sha256": original["sha256"],
                             "target_observer": observer, "passed_original_stages": list(STAGES), "raw_bytes": size,
                             "files": {name: {"sha256": sha(root / name), "size": (root / name).stat().st_size} for name in sorted(names)}}, names)
    require(sum(record[0]["raw_bytes"] + METADATA_LIMIT for record in records.values()) <= PAIR_LIMIT, "original image pair exceeds 10 GiB bound")
    require(all(len(json.dumps(record[0], sort_keys=True, indent=2).encode()) + 1 <= METADATA_LIMIT
                for record in records.values()), "bundle metadata exceeds artifact bound")
    new_directory(output)
    for variant, (record, names) in records.items():
        destination = output / variant
        destination.mkdir()
        for name in sorted(names):
            source = evidence / variant / name
            copied = destination / name
            copied.parent.mkdir(parents=True, exist_ok=True)
            # Same-run immutable originals, on the same runner volume. Avoid an
            # additional 8.5 GiB disk copy; never stage any guest/private tree.
            os.link(source, copied)
        write(destination / "bundle.json", record)
    return {variant: record[0] for variant, record in records.items()}


def pins(value):
    require(isinstance(value, dict) and set(value) == {"run_id", "head_sha", "images"}, "reuse pins require exact run/head and both images")
    require(type(value["run_id"]) is int and value["run_id"] > 0
            and isinstance(value["head_sha"], str) and COMMIT.fullmatch(value["head_sha"]), "reuse run/head is not immutable")
    require(isinstance(value["images"], dict) and set(value["images"]) == set(VARIANTS), "reuse requires exactly yellowfin and grouper")
    for pin in value["images"].values():
        require(isinstance(pin, dict) and set(pin) == {"artifact_id", "archive_sha256", "manifest_digest", "config_digest"}, "incomplete immutable image pins")
        require(type(pin["artifact_id"]) is int and pin["artifact_id"] > 0, "artifact ID must be immutable")
        require(all(isinstance(pin[key], str) and DIGEST.fullmatch(pin[key]) for key in ("archive_sha256", "manifest_digest", "config_digest")), "image pins require exact SHA-256 digests")
    require(len({p["artifact_id"] for p in value["images"].values()}) == 2, "image artifacts must be distinct")
    return value


def select(output):
    supplied = os.environ.get("FORK_REUSE_JSON", "").strip()
    value = json.loads(supplied, object_pairs_hook=EXPORT.SOURCE.unique) if supplied else read(ROOT / ".github/fork-image-reuse.json")
    if value is not None:
        pins(value)
    output.parent.mkdir(parents=True, exist_ok=True)
    write(output, value)
    with Path(os.environ["GITHUB_OUTPUT"]).open("a") as stream:
        stream.write("reuse=" + ("true" if value is not None else "false") + "\n")


def validate_metadata(artifact, run, selection, variant):
    pin = selection["images"][variant]
    expected = {"id": pin["artifact_id"], "name": artifact_name(selection["run_id"], variant),
                "expired": False, "digest": pin["archive_sha256"]}
    require(all(artifact.get(key) == value for key, value in expected.items()), "artifact metadata differs from immutable pins")
    require(type(artifact.get("size_in_bytes")) is int and 0 < artifact["size_in_bytes"] <= ARCHIVE_LIMIT, "artifact download size exceeds bound")
    source = artifact.get("workflow_run", {})
    require(source.get("id") == selection["run_id"] and source.get("head_sha") == selection["head_sha"], "artifact run/head differs from pins")
    require(run.get("id") == selection["run_id"] and run.get("head_sha") == selection["head_sha"]
            and run.get("repository", {}).get("full_name") == REPOSITORY
            and run.get("path") == WORKFLOW and run.get("event") in {"pull_request", "workflow_dispatch"}, "producer workflow provenance differs from pins")
    # A later login/install failure does not invalidate passed original stages.
    # In-progress producers are not admitted, and their conclusions are recorded.
    require(run.get("status") == "completed" and run.get("conclusion") in {"success", "failure"}, "producer run is not terminal success/failure")
    return {"run_status": run["status"], "run_conclusion": run["conclusion"]}


def bounded_zip_directory(archive):
    """Bound central-directory allocation before ZipFile parses its members."""
    size = archive.stat().st_size
    with archive.open("rb") as stream:
        stream.seek(max(0, size - 65557))
        tail = stream.read()
        position = tail.rfind(b"PK\x05\x06")
        require(position >= 0 and position + 22 <= len(tail), "artifact ZIP end record is missing")
        end = struct.unpack("<4s4H2LH", tail[position:position + 22])
        require(position + 22 + end[7] == len(tail) and end[1] == end[2] == 0 and end[3] == end[4],
                "artifact ZIP has unsupported split/end metadata")
        count, directory_size, offset = end[4:7]
        end_offset = size - len(tail) + position
        directory_end = end_offset
        has_zip64 = position >= 20 and tail[position - 20:position - 16] == b"PK\x06\x07"
        if has_zip64 or count == 0xffff or directory_size == 0xffffffff or offset == 0xffffffff:
            require(position >= 20, "artifact ZIP64 locator is missing")
            locator = struct.unpack("<4sLQL", tail[position - 20:position])
            require(locator[0] == b"PK\x06\x07" and locator[1] == 0 and locator[3] == 1
                    and locator[2] >= 0 and locator[2] + 56 == end_offset - 20,
                    "artifact ZIP64 locator is invalid or noncanonical")
            stream.seek(locator[2])
            record = struct.unpack("<4sQ2H2L4Q", stream.read(56))
            require(record[0] == b"PK\x06\x06" and record[1] == 44 and record[4] == record[5] == 0
                    and record[6] == record[7], "artifact ZIP64 end record is unsupported")
            count, directory_size, offset = record[7:10]
            directory_end = locator[2]
        require(offset + directory_size == directory_end, "artifact ZIP directory is not contiguous")
        require(0 < count <= MAX_FILES and directory_size <= METADATA_LIMIT and offset + directory_size <= size,
                "artifact ZIP central directory exceeds bound")


def unpack(archive, output, variant, expected):
    require(archive.stat().st_size <= ARCHIVE_LIMIT and sha(archive) == expected, "artifact archive SHA-256 mismatch or oversized download")
    bounded_zip_directory(archive)
    with zipfile.ZipFile(archive) as zipped:
        members = zipped.infolist()
        require(0 < len(members) <= MAX_FILES and len({m.filename for m in members}) == len(members), "artifact ZIP has duplicate or excessive members")
        require(sum(m.file_size for m in members) <= LIMIT, "artifact ZIP expands beyond 5 GiB bound")
        for member in members:
            require(permitted_name(member.filename, variant) and not member.is_dir()
                    and stat.S_IFMT(member.external_attr >> 16) in (0, stat.S_IFREG)
                    and not member.flag_bits & 1 and member.file_size >= 0
                    and member.compress_type in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED},
                    "artifact ZIP contains unsafe or unapproved member")
            require(member.file_size <= (LIMIT if "/blobs/" in member.filename else METADATA_LIMIT),
                    "artifact ZIP metadata member exceeds bound")
        new_directory(output)
        for member in members:
            destination = output / member.filename
            destination.parent.mkdir(parents=True, exist_ok=True)
            with zipped.open(member) as source, destination.open("xb") as target_file:
                shutil.copyfileobj(source, target_file, 1024 * 1024)


def verify_bundle(root, variant, selection):
    bundle = read(EXPORT.regular(root, "bundle.json"))
    pin = selection["images"][variant]
    keys = {"schema_version", "purpose", "repository", "run_id", "head_sha", "build_sha", "variant",
            "platform", "retention_days", "source_manifest_digest", "source_image_id", "original_source_sha256",
            "target_observer", "passed_original_stages", "raw_bytes", "files"}
    require(isinstance(bundle, dict) and set(bundle) == keys and bundle.get("schema_version") == 1 and bundle.get("purpose") == "original-fork-image"
            and bundle.get("variant") == variant and bundle.get("platform") == "linux/amd64"
            and bundle.get("repository") == REPOSITORY and bundle.get("run_id") == selection["run_id"]
            and bundle.get("head_sha") == selection["head_sha"] and isinstance(bundle.get("build_sha"), str)
            and COMMIT.fullmatch(bundle["build_sha"]) and bundle.get("retention_days") == 3
            and bundle.get("passed_original_stages") == list(STAGES), "bundle producer/stage provenance differs from immutable pins")
    require(bundle.get("source_manifest_digest") == pin["manifest_digest"]
            and bundle.get("source_image_id") == pin["config_digest"], "bundle image digests differ from pins")
    receipt, original, names, size = payload(root, variant)
    require(receipt["source_manifest_digest"] == pin["manifest_digest"] and receipt["source_image_id"] == pin["config_digest"]
            and bundle.get("original_source_sha256") == original["sha256"], "original source differs from bundle identity")
    require(bundle.get("raw_bytes") == size and isinstance(bundle.get("files"), dict) and set(bundle["files"]) == names, "bundle payload inventory differs from exact OCI closure")
    actual = set()
    for path in root.rglob("*"):
        require(not path.is_symlink() and (path.is_dir() or path.is_file()), "bundle contains a nonregular entry")
        if path.is_file():
            actual.add(path.relative_to(root).as_posix())
    require(actual == names | {"bundle.json"}, "bundle contains unapproved extra files")
    for name in names:
        require(bundle["files"][name] == {"sha256": sha(root / name), "size": (root / name).stat().st_size}, "bundle file checksum or size changed")
    observer = bundle.get("target_observer", {})
    validate_observer(observer, original)
    return bundle, original


def api(path, token):
    # Reuse the already-reviewed authenticated API/redirect separation with an
    # explicit repository; never pass credentials to the storage redirect.
    old_api = TRANSPORT.API
    TRANSPORT.API = "https://api.github.com/repos/" + REPOSITORY
    try:
        return TRANSPORT.api_request(path, token)
    finally:
        TRANSPORT.API = old_api


@contextmanager
def hard_deadline(seconds):
    """CLI-only wall-clock deadline, including blocked/slow-trickle socket reads."""
    require(signal.getitimer(signal.ITIMER_REAL) == (0.0, 0.0), "cannot replace an existing process deadline")
    previous = signal.getsignal(signal.SIGALRM)
    def expired(_number, _frame):
        raise TimeoutError("artifact download wall-clock deadline exceeded")
    signal.signal(signal.SIGALRM, expired)
    try:
        signal.setitimer(signal.ITIMER_REAL, seconds)
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def download(selection, variant, output):
    with hard_deadline(1800):
        return download_with_checks(selection, variant, output)


def download_with_checks(selection, variant, output):
    deadline = time.monotonic() + 1800
    pin = selection["images"][variant]
    token = os.environ.get("GITHUB_TOKEN", "")
    with api("/actions/artifacts/" + str(pin["artifact_id"]), token) as response:
        artifact = json.loads(response.read(METADATA_LIMIT))
    with api("/actions/runs/" + str(selection["run_id"]), token) as response:
        run = json.loads(response.read(METADATA_LIMIT))
    status = validate_metadata(artifact, run, selection, variant)
    with api("/actions/artifacts/" + str(pin["artifact_id"]) + "/zip", token) as response:
        require(response.code == 302, "artifact API did not provide the expected redirect")
        url = TRANSPORT.public_archive_url(response.headers.get("Location", ""))
    token = ""
    require(time.monotonic() < deadline, "artifact download deadline exceeded")
    archive = output.parent / (variant + ".zip")
    try:
        with urllib.request.build_opener(TRANSPORT.ArchiveRedirect()).open(url, timeout=60) as response, archive.open("xb") as stream:
            count = 0
            while chunk := response.read(1024 * 1024):
                require(time.monotonic() < deadline, "artifact download deadline exceeded")
                count += len(chunk)
                require(count <= ARCHIVE_LIMIT, "artifact download exceeds bound")
                stream.write(chunk)
        require(time.monotonic() < deadline, "artifact download deadline exceeded")
        unpack(archive, output, variant, pin["archive_sha256"])
    except urllib.error.URLError:
        raise RuntimeError("GitHub original-image artifact download failed") from None
    finally:
        if archive.exists():
            archive.unlink()
    return status


def bounded_command(command, timeout):
    """Bound CLI runtime/output and reap its process group on every outcome."""
    env = {key: value for key, value in os.environ.items() if key != "GITHUB_TOKEN"}
    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr,
                                   env=env, start_new_session=True)
        try:
            deadline = time.monotonic() + timeout
            while process.poll() is None:
                require(os.fstat(stdout.fileno()).st_size + os.fstat(stderr.fileno()).st_size <= METADATA_LIMIT,
                        "original image command output exceeds bound")
                if time.monotonic() >= deadline:
                    raise TimeoutError("original image command deadline exceeded")
                time.sleep(0.1)
            require(os.fstat(stdout.fileno()).st_size + os.fstat(stderr.fileno()).st_size <= METADATA_LIMIT,
                    "original image command output exceeds bound")
            if process.returncode:
                raise subprocess.CalledProcessError(process.returncode, command)
            stdout.seek(0)
            return stdout.read(METADATA_LIMIT)
        finally:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait(timeout=30)


def container_exists(reference):
    try:
        bounded_command(["podman", "container", "exists", reference], 30)
        return True
    except subprocess.CalledProcessError as error:
        require(error.returncode == 1, "could not establish verification container absence")
        return False


def run_verifier(image_id, arguments):
    token = uuid.uuid4().hex
    name = "fork-artifact-verify-" + token
    label = "io.tunaos.fork-artifact-verification"
    require(not container_exists(name), "verification container name is already in use")
    command = ["podman", "run", "--rm", "--name", name, "--label", label + "=" + token,
               "--pull=never", "--network=none", "--read-only", "--cap-drop=all",
               "--entrypoint", "python3", image_id, *arguments]
    try:
        return bounded_command(command, 120)
    finally:
        if container_exists(name):
            inspected = json.loads(bounded_command(["podman", "container", "inspect", name], 30))
            require(isinstance(inspected, list) and len(inspected) == 1 and isinstance(inspected[0], dict),
                    "verification container ownership is ambiguous")
            info = inspected[0]
            container_id = info.get("Id", "")
            require(isinstance(container_id, str) and HEX.fullmatch(container_id)
                    and info.get("Name", "").lstrip("/") == name
                    and info.get("Config", {}).get("Labels", {}).get(label) == token,
                    "refusing to remove a verification container without exact ownership")
            bounded_command(["podman", "rm", "--force", container_id], 60)
            require(not container_exists(container_id), "verification container remains after cleanup")
        require(not container_exists(name), "verification container name remains after cleanup")


def embedded_original(image_id):
    program = ("import json,pathlib; print(json.dumps({p:pathlib.Path('/'+p).read_text() "
               "for p in " + repr(EXPORT.FILES) + "}))")
    files = json.loads(run_verifier(image_id, ["-c", program]), object_pairs_hook=EXPORT.SOURCE.unique)
    require(isinstance(files, dict) and set(files) == set(EXPORT.FILES)
            and all(isinstance(value, str) for value in files.values()), "imported embedded receipt set is malformed")
    run_verifier(image_id, ["/usr/libexec/tunaos/fork-installer-source.py", "--manifest", "/" + EXPORT.FILES[0],
                            "--root", "/", "--backend-probe", "/usr/libexec/tunaos/installer-recipe-backend.sh", "--verify"])
    return files


def import_original(root, variant, bundle):
    image_id = bundle["source_image_id"]
    bounded_command(["skopeo", "copy", "--preserve-digests", "oci:" + str(root / "oci-export/source") + ":canary",
                    "containers-storage:" + target(variant)], 1800)
    inspected = json.loads(bounded_command(["podman", "image", "inspect", target(variant)], 60))
    require(isinstance(inspected, list) and len(inspected) == 1
            and "sha256:" + inspected[0].get("Id", "").removeprefix("sha256:") == image_id,
            "imported original image config differs from pin")
    raw = bounded_command(["skopeo", "inspect", "--raw", "containers-storage:@" + image_id.removeprefix("sha256:")], 60)
    require(EXPORT.sha(raw) == bundle["source_manifest_digest"], "import changed original manifest digest")
    embedded = embedded_original(image_id)
    receipt = read(root / "oci-export/source-receipt.json")
    for name, key in ((EXPORT.FILES[0], "fork_manifest_sha256"), (EXPORT.SOURCE.RECIPE, "recipe_sha256"),
                      (EXPORT.SOURCE.CATALOG, "catalog_sha256")):
        require(EXPORT.sha(embedded[name].encode()) == receipt.get(key), "imported embedded source differs from original receipt")


def restore(selection, output):
    selection = pins(selection)
    new_directory(output)
    # Rejected downloads must never enter the always-uploaded evidence tree.
    staging = output.with_name(output.name + "-original-inputs")
    new_directory(staging)
    current = COMPILER.source_receipt(ROOT)
    harness_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    require(COMMIT.fullmatch(harness_sha), "harness commit is not immutable")
    prepared = {}
    for variant in VARIANTS:
        root = staging / variant
        status = download(selection, variant, root)
        bundle, original = verify_bundle(root, variant, selection)
        changed = harness_changes(original, current)
        prepared[variant] = (bundle, changed, status)
    require(sum(item[0]["raw_bytes"] + METADATA_LIMIT for item in prepared.values()) <= PAIR_LIMIT, "image pair exceeds 10 GiB bound")
    # Validate both and their input differences before importing either image.
    for variant, (bundle, changed, status) in prepared.items():
        root = staging / variant
        import_original(root, variant, bundle)
        write(root / "image-reuse.json", {"schema_version": 1, "mode": "explicit-original-artifact-reuse",
              "repository": REPOSITORY, "run_id": selection["run_id"], "head_sha": selection["head_sha"],
              **selection["images"][variant], **status, "original_build_sha": bundle["build_sha"],
              "original_source_sha256": bundle["original_source_sha256"], "harness_sha": harness_sha,
              "harness_source_sha256": current["sha256"], "changed_harness_inputs": changed,
              "original_receipts_unchanged": True, "login": "not-run", "installed_proof": "not-run"})
        root.rename(output / variant)
    staging.rmdir()
    return {variant: read(output / variant / "image-reuse.json") for variant in VARIANTS}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    selection = commands.add_parser("select")
    selection.add_argument("--output", type=Path, required=True)
    producer = commands.add_parser("package")
    producer.add_argument("--evidence", type=Path, required=True)
    producer.add_argument("--output", type=Path, required=True)
    consumer = commands.add_parser("restore")
    consumer.add_argument("--pins", type=Path, required=True)
    consumer.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "select":
        select(args.output)
    elif args.command == "package":
        result = package(args.evidence, args.output, producer_identity())
        print(json.dumps({v: {k: r[k] for k in ("source_manifest_digest", "source_image_id", "raw_bytes")} for v, r in result.items()}, indent=2))
    else:
        print(json.dumps(restore(read(args.pins), args.output), indent=2))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, RuntimeError, subprocess.CalledProcessError, zipfile.BadZipFile) as exc:
        print(f"ERROR: original image artifact: {exc}", file=sys.stderr)
        sys.exit(2)
