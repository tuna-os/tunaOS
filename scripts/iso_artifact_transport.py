"""Read-only artifact snapshot checks, conditional on trustworthy fresh transport.

No network client, credential handling, filesystem archive extraction or
production caller is provided. The retained-media path reads one bounded ZIP
receipt member in memory and streams candidate chunks. GitHub artifacts lack upload-attempt identity: only a run observed at
attempt one before and after collection is supported. This is not attestation.
"""
from dataclasses import dataclass
import hashlib
import re


class ArtifactVerificationError(ValueError):
    """A selected artifact cannot satisfy the snapshot policy."""

    def __init__(self, code, field):
        self.code = code
        self.field = field
        super().__init__(f"{code}: {field}")


@dataclass(frozen=True)
class ReviewedPolicy:
    """Independent reviewed input; never construct this from candidate evidence."""

    repository: str
    repository_id: int
    workflow_id: int
    workflow_path: str
    source_revision: str
    ref: str
    archive_sha256: str
    max_archive_bytes: int


@dataclass(frozen=True)
class ArtifactSelection:
    run_id: int
    attempt: int
    artifact_id: int


def _reject(code, field):
    raise ArtifactVerificationError(code, field)


def _positive(value, field):
    if type(value) is not int or value <= 0:
        _reject("invalid_integer", field)


def _match(value, expected, field):
    if type(value) is not type(expected) or value != expected:
        _reject("identity_mismatch", field)


def _object(value, field):
    if type(value) is not dict:
        _reject("invalid_object", field)
    return value


def _pattern(value, pattern, field):
    if type(value) is not str or re.fullmatch(pattern, value) is None:
        _reject("invalid_string", field)


def _validate_inputs(policy, selection):
    if type(policy) is not ReviewedPolicy or type(selection) is not ArtifactSelection:
        _reject("invalid_input", "policy/selection")
    # This first adapter deliberately supports only the approved producer scope.
    _match(policy.repository, "tuna-os/iso-builder", "policy.repository")
    _match(policy.workflow_path, ".github/workflows/ci.yml", "policy.workflow_path")
    _match(policy.ref, "refs/heads/main", "policy.ref")
    for field in ("repository_id", "workflow_id", "max_archive_bytes"):
        _positive(getattr(policy, field), "policy." + field)
    _pattern(policy.source_revision, r"[0-9a-f]{40}", "policy.source_revision")
    _pattern(policy.archive_sha256, r"sha256:[0-9a-f]{64}", "policy.archive_sha256")
    for field in ("run_id", "attempt", "artifact_id"):
        _positive(getattr(selection, field), "selection." + field)
    _match(selection.attempt, 1, "selection.attempt")


def _run(document, policy, selection, where):
    doc = _object(document, where)
    expected = {
        "id": selection.run_id, "run_attempt": 1,
        "workflow_id": policy.workflow_id, "path": policy.workflow_path,
        "head_sha": policy.source_revision, "head_branch": "main",
        "event": "workflow_dispatch", "status": "completed", "conclusion": "success",
    }
    for key, value in expected.items():
        _match(doc.get(key), value, where + "." + key)
    for key in ("repository", "head_repository"):
        repo = _object(doc.get(key), where + "." + key)
        _match(repo.get("id"), policy.repository_id, where + "." + key + ".id")
        _match(repo.get("full_name"), policy.repository, where + "." + key + ".full_name")
        _match(repo.get("fork"), False, where + "." + key + ".fork")
    _match(doc.get("pull_requests"), [], where + ".pull_requests")


def _artifact(document, policy, selection):
    doc = _object(document, "artifact")
    _match(doc.get("id"), selection.artifact_id, "artifact.id")
    _match(doc.get("expired"), False, "artifact.expired")
    _match(doc.get("digest"), policy.archive_sha256, "artifact.digest")
    _positive(doc.get("size_in_bytes"), "artifact.size_in_bytes")
    if doc["size_in_bytes"] > policy.max_archive_bytes:
        _reject("archive_limit", "artifact.size_in_bytes")
    run = _object(doc.get("workflow_run"), "artifact.workflow_run")
    for key, value in {
        "id": selection.run_id, "repository_id": policy.repository_id,
        "head_repository_id": policy.repository_id, "head_branch": "main",
        "head_sha": policy.source_revision,
    }.items():
        _match(run.get(key), value, "artifact.workflow_run." + key)


def _metadata(policy, selection, transport):
    _validate_inputs(policy, selection)
    base = f"/repos/{policy.repository}/actions"
    run_path = f"{base}/runs/{selection.run_id}"
    _run(transport.get_json(run_path), policy, selection, "run_before")
    _run(transport.get_json(f"{run_path}/attempts/1"), policy, selection, "attempt")
    artifact_path = f"{base}/artifacts/{selection.artifact_id}"
    artifact = transport.get_json(artifact_path)
    _artifact(artifact, policy, selection)
    return run_path, artifact_path, artifact["size_in_bytes"]


def _archive_digest(stream, expected_size):
    if hasattr(stream, "seekable") and stream.seekable():
        if stream.tell() != 0:
            _reject("invalid_stream", "archive.position")
    measured = 0
    digest = hashlib.sha256()
    while True:
        requested = min(1024 * 1024, expected_size - measured + 1)
        chunk = stream.read(requested)
        if type(chunk) is not bytes or len(chunk) > requested:
            _reject("invalid_stream", "archive.read")
        if not chunk:
            break
        measured += len(chunk)
        if measured > expected_size:
            _reject("archive_size_mismatch", "archive.sizeBytes")
        digest.update(chunk)
    if measured != expected_size:
        _reject("archive_size_mismatch", "archive.sizeBytes")
    return "sha256:" + digest.hexdigest(), measured


def verify_artifact_snapshot(policy, selection, transport):
    """Verify a first-attempt snapshot, conditional on reviewed policy/transport.

    Transport must supply fresh authoritative JSON objects and a context-managed
    binary stream for the exact paths requested. No candidate URL is followed.
    The artifact is checked again after hashing, then the run is checked again.
    REST does not promise atomicity; success is neither authentication nor proof
    of archive members, a browser build, or an installation.
    """
    run_path, artifact_path, expected_size = _metadata(policy, selection, transport)
    with transport.open_archive(artifact_path + "/zip") as stream:
        archive_sha256, size = _archive_digest(stream, expected_size)
    _match(archive_sha256, policy.archive_sha256, "archive.sha256")
    artifact_after = transport.get_json(artifact_path)
    _artifact(artifact_after, policy, selection)
    _match(artifact_after["size_in_bytes"], expected_size, "artifact_after.size_in_bytes")
    _run(transport.get_json(run_path), policy, selection, "run_after")
    return {
        "metadata_checks_passed": True,
        "archive_digest_verified": True,
        "attempt_policy": "first_attempt_only",
        "authentication": "not_authenticated",
        "repository": policy.repository,
        "repositoryId": policy.repository_id,
        "workflowId": policy.workflow_id,
        "workflowPath": policy.workflow_path,
        "sourceRevision": policy.source_revision,
        "ref": policy.ref,
        "runId": selection.run_id,
        "runAttempt": selection.attempt,
        "artifactId": selection.artifact_id,
        "archiveSha256": archive_sha256,
        "sizeBytes": size,
    }


@dataclass(frozen=True)
class RetainedMediaPolicy:
    """Independent media/receipt expectations and non-credential R2 coordinates.

    Endpoint and bucket must also equal the adapter's trusted configuration.
    Candidate JSON cannot supply an endpoint, bucket, URL, or receipt path.
    """

    endpoint: str
    bucket: str
    manifest_sha256: str
    media_sha256: str
    media_size_bytes: int
    receipt_sha256: str
    receipt_path: str


MAX_MANIFEST_BYTES = 1024 * 1024
MAX_DIAGNOSTIC_BYTES = 16 * 1024 * 1024
MAX_ISO_BYTES = 10 * 1024 ** 3
MAX_CHUNK_BYTES = 64 * 1024 * 1024
MAX_CHUNKS = 160


def _strict_json(data, where):
    import json
    import math

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                _reject("duplicate_key", where)
            result[key] = value
        return result

    def invalid(_):
        _reject("invalid_json", where)

    def finite(text):
        result = float(text)
        if not math.isfinite(result):
            invalid(text)
        return result

    try:
        return _object(json.loads(data.decode("utf-8"), object_pairs_hook=pairs,
                                  parse_constant=invalid, parse_float=finite), where)
    except (UnicodeDecodeError, ValueError, RecursionError) as exc:
        raise ArtifactVerificationError("invalid_json", where) from exc


def _read_bounded(stream, limit, where, *, expected_size=None, whole=None, sink=None):
    """Measure exact bytes, with at most limit + one byte read from the stream."""
    if hasattr(stream, "seekable") and stream.seekable() and stream.tell() != 0:
        _reject("invalid_stream", where + ".position")
    digest, measured = hashlib.sha256(), 0
    while True:
        requested = min(1024 * 1024, limit - measured + 1)
        chunk = stream.read(requested)
        if type(chunk) is not bytes or len(chunk) > requested:
            _reject("invalid_stream", where + ".read")
        if not chunk:
            break
        measured += len(chunk)
        if measured > limit:
            _reject("size_limit", where)
        digest.update(chunk)
        if whole is not None:
            whole.update(chunk)
        if sink is not None:
            sink.write(chunk)
    if expected_size is not None:
        _match(measured, expected_size, where + ".sizeBytes")
    return "sha256:" + digest.hexdigest(), measured


def _safe_member(path, where):
    _pattern(path, r"[A-Za-z0-9][A-Za-z0-9._/-]*", where)
    normalized = path[:-1] if path.endswith("/") else path
    if any(part in ("", ".", "..") for part in normalized.split("/")):
        _reject("unsafe_member", where)


def _receipt_member(archive, retained):
    """Read only the named bounded member; never extract files to disk."""
    import io
    import stat
    import zipfile

    try:
        with zipfile.ZipFile(io.BytesIO(archive)) as zipped:
            members = zipped.infolist()
            if not 1 <= len(members) <= 256:
                _reject("archive_member_limit", "archive")
            names, total = set(), 0
            for member in members:
                _safe_member(member.filename, "archive.member")
                if member.filename in names:
                    _reject("duplicate_member", "archive.member")
                names.add(member.filename)
                mode = member.external_attr >> 16
                if stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR) or member.flag_bits & 1:
                    _reject("unsafe_member", "archive.member")
                if member.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
                    _reject("unsupported_compression", "archive.member")
                total += member.file_size
                if member.file_size < 0 or total > MAX_DIAGNOSTIC_BYTES:
                    _reject("archive_member_limit", "archive.member")
            if retained.receipt_path not in names:
                _reject("missing_receipt", "archive.receiptPath")
            member = zipped.getinfo(retained.receipt_path)
            if member.is_dir() or not 0 < member.file_size <= MAX_MANIFEST_BYTES:
                _reject("receipt_size_limit", "archive.receiptPath")
            output = io.BytesIO()
            with zipped.open(member) as stream:
                digest, _ = _read_bounded(stream, MAX_MANIFEST_BYTES, "receipt",
                                          expected_size=member.file_size, sink=output)
            _match(digest, retained.receipt_sha256, "receipt.sha256")
            return output.getvalue()
    except (zipfile.BadZipFile, NotImplementedError, RuntimeError) as exc:
        raise ArtifactVerificationError("invalid_archive", "archive") from exc


def _retained_inputs(policy, selection, retained, transport):
    _validate_inputs(policy, selection)
    if type(retained) is not RetainedMediaPolicy:
        _reject("invalid_input", "retained_policy")
    _pattern(retained.endpoint, r"https://[0-9a-f]{32}\.r2\.cloudflarestorage\.com", "retained.endpoint")
    _pattern(retained.bucket, r"[a-z0-9][a-z0-9-]{1,61}[a-z0-9]", "retained.bucket")
    _match(getattr(transport, "endpoint", None), retained.endpoint, "transport.endpoint")
    _match(getattr(transport, "bucket", None), retained.bucket, "transport.bucket")
    for field in ("manifest_sha256", "media_sha256", "receipt_sha256"):
        _pattern(getattr(retained, field), r"sha256:[0-9a-f]{64}", "retained." + field)
    _positive(retained.media_size_bytes, "retained.media_size_bytes")
    if retained.media_size_bytes > MAX_ISO_BYTES or policy.max_archive_bytes > MAX_DIAGNOSTIC_BYTES:
        _reject("size_limit", "retained.media/archive")
    _safe_member(retained.receipt_path, "retained.receipt_path")
    if not retained.receipt_path.endswith(".json"):
        _reject("invalid_receipt_path", "retained.receipt_path")


def _match_media(value, expected, where):
    _object(value, where)
    _positive(value.get("sizeBytes"), where + ".sizeBytes")
    _pattern(value.get("sha256"), r"sha256:[0-9a-f]{64}", where + ".sha256")
    _match(value, expected, where)


def _receipt_identity(receipt_bytes, policy, selection, retained):
    receipt = _strict_json(receipt_bytes, "receipt")
    for key, expected in {"schemaVersion": 2, "kind": "qualification-evidence", "half": "browser"}.items():
        _match(receipt.get(key), expected, "receipt." + key)
    identity = {"sha256": retained.media_sha256, "sizeBytes": retained.media_size_bytes}
    _match_media(receipt.get("media"), identity, "receipt.media")
    run = _object(receipt.get("run"), "receipt.run")
    _match(set(run), {"repository", "workflowPath", "workflowRevision", "sourceRevision",
                      "harnessRevision", "runId", "runAttempt"}, "receipt.run.fields")
    for key, expected in {
        "repository": policy.repository, "workflowPath": policy.workflow_path,
        "workflowRevision": policy.source_revision, "sourceRevision": policy.source_revision,
        "runId": selection.run_id, "runAttempt": selection.attempt,
    }.items():
        _match(run.get(key), expected, "receipt.run." + key)
    _pattern(run.get("harnessRevision"), r"[0-9a-f]{40}", "receipt.run.harnessRevision")
    return run, identity


def _manifest_identity(manifest, policy, selection, identity, prefix):
    for key, expected in {"schemaVersion": 1, "kind": "retained-browser-candidate",
                          "qualification": "not-assessed", "state": "complete", "expiry": None}.items():
        if key not in manifest:
            _reject("missing_field", "manifest." + key)
        _match(manifest[key], expected, "manifest." + key)
    _match_media(manifest.get("iso"), identity, "manifest.iso")
    provenance = _object(manifest.get("provenance"), "manifest.provenance")
    for key, expected in {"schemaVersion": 1, "kind": "candidate-producer-observations",
                          "qualification": "not-assessed"}.items():
        _match(provenance.get(key), expected, "manifest.provenance." + key)
    _match_media(provenance.get("iso"), identity, "manifest.provenance.iso")
    context = _object(provenance.get("producerContext"), "manifest.producerContext")
    for key, expected in {
        "repository": policy.repository, "job": "full-matrix",
        "checkoutSha": policy.source_revision, "workflowSha": policy.source_revision,
        "workflowRef": f"{policy.repository}/{policy.workflow_path}@{policy.ref}",
        "runId": str(selection.run_id), "runAttempt": str(selection.attempt),
    }.items():
        _match(context.get(key), expected, "manifest.producerContext." + key)
    parts = manifest.get("chunks")
    if type(parts) is not list or not 1 <= len(parts) <= MAX_CHUNKS:
        _reject("invalid_chunks", "manifest.chunks")
    total = 0
    for index, part in enumerate(parts):
        _object(part, "manifest.chunk")
        _match(set(part), {"key", "sizeBytes", "sha256"}, "manifest.chunk.fields")
        _match(part.get("key"), prefix + f"chunks/{index:05d}", "manifest.chunk.key")
        _positive(part.get("sizeBytes"), "manifest.chunk.sizeBytes")
        if part["sizeBytes"] > MAX_CHUNK_BYTES:
            _reject("chunk_size_limit", "manifest.chunk.sizeBytes")
        _pattern(part.get("sha256"), r"[0-9a-f]{64}", "manifest.chunk.sha256")
        total += part["sizeBytes"]
    _match(total, identity["sizeBytes"], "manifest.chunks.sizeBytes")
    return parts


def verify_retained_candidate_snapshot(policy, selection, retained_policy, transport):
    """Verify a GitHub receipt anchor and R2 media bytes without authenticating them.

    The adapter supplies fresh authoritative GitHub JSON, open_archive(path), and
    open_object(key), both context-managed binary streams. Its endpoint/bucket are
    trusted configuration matched to independent policy; no candidate URL is used.
    The exact receipt bytes are returned for the existing v2 consistency boundary.
    This does not reconstruct an ISO, emit qualification, or prove API freshness.
    """
    import io

    retained = retained_policy
    _retained_inputs(policy, selection, retained, transport)
    run_path, artifact_path, expected_size = _metadata(policy, selection, transport)
    archive = io.BytesIO()
    with transport.open_archive(artifact_path + "/zip") as stream:
        archive_sha256, _ = _read_bounded(stream, expected_size, "archive",
                                          expected_size=expected_size, sink=archive)
    _match(archive_sha256, policy.archive_sha256, "archive.sha256")
    receipt_bytes = _receipt_member(archive.getvalue(), retained)
    run, identity = _receipt_identity(receipt_bytes, policy, selection, retained)
    prefix = f"browser-iso/candidates/{selection.run_id}/{selection.attempt}/yellowfin-gnome/s1/"
    manifest_key = prefix + "manifest.json"
    manifest_bytes = io.BytesIO()
    with transport.open_object(manifest_key) as stream:
        manifest_sha256, _ = _read_bounded(stream, MAX_MANIFEST_BYTES, "manifest", sink=manifest_bytes)
    _match(manifest_sha256, retained.manifest_sha256, "manifest.sha256")
    manifest = _strict_json(manifest_bytes.getvalue(), "manifest")
    parts = _manifest_identity(manifest, policy, selection, identity, prefix)
    whole = hashlib.sha256()
    for part in parts:
        with transport.open_object(part["key"]) as stream:
            digest, _ = _read_bounded(stream, part["sizeBytes"], "chunk",
                                      expected_size=part["sizeBytes"], whole=whole)
        _match(digest, "sha256:" + part["sha256"], "chunk.sha256")
    _match("sha256:" + whole.hexdigest(), identity["sha256"], "media.sha256")
    artifact_after = transport.get_json(artifact_path)
    _artifact(artifact_after, policy, selection)
    _match(artifact_after["size_in_bytes"], expected_size, "artifact_after.size_in_bytes")
    _run(transport.get_json(run_path), policy, selection, "run_after")
    return {
        "metadata_checks_passed": True, "archive_digest_verified": True,
        "receipt_digest_verified": True, "manifest_digest_verified": True,
        "chunks_digest_verified": True, "media_digest_verified": True,
        "attempt_policy": "first_attempt_only", "authentication": "not_authenticated",
        "browserReceiptBytes": receipt_bytes,
        "browserProducer": {
            "run": run, "receiptSha256": retained.receipt_sha256,
            "artifact": {"id": selection.artifact_id, "archiveSha256": archive_sha256,
                         "expired": False, "receiptPath": retained.receipt_path},
            "mediaTransport": {
                "kind": "r2-chunked-candidate", "endpoint": retained.endpoint,
                "bucket": retained.bucket, "manifestKey": manifest_key,
                "manifestSha256": manifest_sha256, "media": identity,
            },
        },
    }
