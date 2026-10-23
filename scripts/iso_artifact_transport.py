"""Read-only artifact snapshot checks, conditional on trustworthy fresh transport.

No network client, credential handling, archive extraction or production caller is
provided. GitHub artifacts lack upload-attempt identity: only a run observed at
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
