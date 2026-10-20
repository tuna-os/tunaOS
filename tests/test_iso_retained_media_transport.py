"""Synthetic, tiny, offline GitHub/R2 snapshot and existing-v2 join tests.

Falsification: alter producer API facts, the selected ZIP receipt, manifest or
chunk bytes, or media identity; the verifier must reject before a v2 join.
"""
import copy
from dataclasses import replace
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import stat
import sys
import zipfile

import pytest
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


TRANSPORT = load("iso_artifact_transport")
CONTRACT = load("iso_media_provenance")
CASE = json.loads((ROOT / "tests/fixtures/iso-artifact-transport-v1/case.json").read_text())
BUNDLE = json.loads((ROOT / "tests/fixtures/iso-media-provenance-v2/cases.json").read_text())
SCHEMA = json.loads((ROOT / "schemas/iso-media-provenance-v2.schema.json").read_text())


def digest(value):
    return "sha256:" + hashlib.sha256(value).hexdigest()


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode() + b"\n"


class CheckedStream(io.BytesIO):
    def read(self, size=-1):
        assert 0 < size <= 1024 * 1024
        return super().read(size)


class FakeTransport:
    def __init__(self, case):
        self.case, self.calls, self.streams = case, [], []
        self.endpoint, self.bucket = case.retained.endpoint, case.retained.bucket
        self.api_index = 0

    def get_json(self, path):
        index = self.api_index
        self.api_index += 1
        expected = ["run_before", "attempt", "artifact", "artifact_after", "run_after"][index]
        base = "/repos/tuna-os/iso-builder/actions"
        run = f"{base}/runs/{self.case.selection.run_id}"
        artifact = f"{base}/artifacts/{self.case.selection.artifact_id}"
        assert path == [run, run + "/attempts/1", artifact, artifact, run][index]
        assert all(stream.closed for stream in self.streams)
        self.calls.append(("json", path))
        return copy.deepcopy(self.case.api[expected])

    def _stream(self, data):
        stream = CheckedStream(data)
        self.streams.append(stream)
        return stream

    def open_archive(self, path):
        assert path == f"/repos/tuna-os/iso-builder/actions/artifacts/{self.case.selection.artifact_id}/zip"
        self.calls.append(("archive", path))
        return self._stream(self.case.archive)

    def open_object(self, key):
        assert all(stream.closed for stream in self.streams)
        self.calls.append(("object", key))
        return self._stream(self.case.objects[key])


class Candidate:
    def __init__(self):
        self.policy = TRANSPORT.ReviewedPolicy(**CASE["policy"])
        self.selection = TRANSPORT.ArtifactSelection(**CASE["selection"])
        self.media = b"tiny retained candidate fixture\n"
        self.identity = {"sha256": digest(self.media), "sizeBytes": len(self.media)}
        self.browser = json.loads(BUNDLE["browserReceiptUtf8"])
        self.browser["media"] = self.identity
        self.browser["run"].update({
            "repository": self.policy.repository, "workflowPath": self.policy.workflow_path,
            "sourceRevision": self.policy.source_revision, "workflowRevision": self.policy.source_revision,
            "runId": self.selection.run_id, "runAttempt": 1,
        })
        self.prefix = f"browser-iso/candidates/{self.selection.run_id}/1/yellowfin-gnome/s1/"
        self.manifest_key = self.prefix + "manifest.json"
        self.objects = {self.prefix + f"chunks/{i:05d}": chunk for i, chunk in enumerate((self.media[:8], self.media[8:]))}
        self.manifest = {
            "schemaVersion": 1, "kind": "retained-browser-candidate", "qualification": "not-assessed",
            "state": "complete", "expiry": None, "iso": self.identity,
            "warning": "Synthetic fixture; no objects uploaded.",
            "chunks": [{"key": key, "sizeBytes": len(value), "sha256": digest(value)[7:]}
                       for key, value in self.objects.items()],
            "provenance": {
                "schemaVersion": 1, "kind": "candidate-producer-observations", "qualification": "not-assessed",
                "iso": self.identity, "producerContext": {
                    "authentication": "not-verified", "repository": self.policy.repository,
                    "job": "full-matrix", "checkoutSha": self.policy.source_revision,
                    "workflowSha": self.policy.source_revision,
                    "workflowRef": f"{self.policy.repository}/{self.policy.workflow_path}@refs/heads/main",
                    "runId": str(self.selection.run_id), "runAttempt": "1",
                },
            },
        }
        self.retained = TRANSPORT.RetainedMediaPolicy(
            endpoint="https://" + "a" * 32 + ".r2.cloudflarestorage.com", bucket="synthetic-bucket",
            manifest_sha256=digest(encode(self.manifest)), media_sha256=digest(self.media),
            media_size_bytes=len(self.media), receipt_sha256=digest(encode(self.browser)),
            receipt_path="evidence/browser.json",
        )
        self.api = {key: copy.deepcopy(CASE[source]) for key, source in (
            ("run_before", "currentBefore"), ("attempt", "attempt"), ("artifact", "artifact"),
            ("artifact_after", "artifactAfter"), ("run_after", "currentAfter"))}
        self.rehash_manifest()
        self.repack_archive()
        self.transport = FakeTransport(self)

    def rehash_manifest(self):
        raw = encode(self.manifest)
        self.objects[self.manifest_key] = raw
        self.retained = replace(self.retained, manifest_sha256=digest(raw))

    def repack_archive(self, entries=None):
        raw = encode(self.browser)
        entries = entries if entries is not None else [(self.retained.receipt_path, raw)]
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as zipped:
            for name, value in entries:
                zipped.writestr(name, value)
        self.archive = output.getvalue()
        self.retained = replace(self.retained, receipt_sha256=digest(raw))
        self.rehash_archive()

    def rehash_archive(self):
        self.policy = replace(self.policy, archive_sha256=digest(self.archive), max_archive_bytes=16 * 1024 * 1024)
        for key in ("artifact", "artifact_after"):
            self.api[key]["digest"] = digest(self.archive)
            self.api[key]["size_in_bytes"] = len(self.archive)

    def verify(self):
        return TRANSPORT.verify_retained_candidate_snapshot(self.policy, self.selection, self.retained, self.transport)


@pytest.fixture
def candidate():
    return Candidate()


def join_documents(candidate, result):
    native = json.loads(BUNDLE["nativeReceiptUtf8"])
    native["media"] = candidate.identity
    native["browserReceiptSha256"] = candidate.retained.receipt_sha256
    context = copy.deepcopy(BUNDLE["expectedContext"])
    context["media"] = candidate.identity
    context["browserProducer"] = result["browserProducer"]
    context["nativeProducer"]["receiptSha256"] = digest(encode(native))
    transport = {"schemaVersion": 2, "kind": "iso-media-observed-transport",
                 "browserProducer": copy.deepcopy(context["browserProducer"]),
                 "nativeProducer": copy.deepcopy(context["nativeProducer"])}
    return native, context, transport


def test_verified_retained_bytes_feed_existing_v2_boundary(candidate):
    result = candidate.verify()
    assert result["authentication"] == "not_authenticated"
    assert result["attempt_policy"] == "first_attempt_only"
    assert result["browserReceiptBytes"] == encode(candidate.browser)
    assert all(result[key] is True for key in ("metadata_checks_passed", "archive_digest_verified",
               "receipt_digest_verified", "manifest_digest_verified", "chunks_digest_verified", "media_digest_verified"))
    assert "mediaPath" not in result["browserProducer"]["artifact"]
    assert all(stream.closed for stream in candidate.transport.streams)
    native, context, transport = join_documents(candidate, result)
    for doc in (context, transport):
        Draft202012Validator(SCHEMA).validate(doc)
        CONTRACT.validate_document(doc)
    assert CONTRACT.check_consistency(result["browserReceiptBytes"], encode(native), candidate.media, context, transport) == {
        "consistency_valid": True, "authentication": "not_authenticated"}


@pytest.mark.parametrize("field,value", [("endpoint", "https://" + "b" * 32 + ".r2.cloudflarestorage.com"),
                                          ("bucket", "another-bucket")])
def test_wrong_configured_storage_origin_fails_before_requests(candidate, field, value):
    setattr(candidate.transport, field, value)
    with pytest.raises(TRANSPORT.ArtifactVerificationError):
        candidate.verify()
    assert candidate.transport.calls == []


@pytest.mark.parametrize("field,value", [("manifest_sha256", "sha256:" + "f" * 64),
                                          ("receipt_sha256", "sha256:" + "f" * 64)])
def test_independent_digest_mismatch_rejects_before_chunks(candidate, field, value):
    candidate.retained = replace(candidate.retained, **{field: value})
    with pytest.raises(TRANSPORT.ArtifactVerificationError):
        candidate.verify()
    assert not any("/chunks/" in path for _, path in candidate.transport.calls)


@pytest.mark.parametrize("field,value", [
    ("repository", "fork/iso-builder"), ("job", "other"), ("checkoutSha", "f" * 40),
    ("workflowSha", "f" * 40), ("workflowRef", "tuna-os/iso-builder/.github/workflows/ci.yml@refs/heads/feature"),
    ("runId", "123"), ("runAttempt", "2"),
])
def test_wrong_manifest_origin_or_replay_rejects_even_if_hash_is_reviewed(candidate, field, value):
    candidate.manifest["provenance"]["producerContext"][field] = value
    candidate.rehash_manifest()
    with pytest.raises(TRANSPORT.ArtifactVerificationError):
        candidate.verify()
    assert not any("/chunks/" in path for _, path in candidate.transport.calls)


@pytest.mark.parametrize("snapshot", ["run_before", "attempt", "run_after"])
@pytest.mark.parametrize("field,value", [("run_attempt", 2), ("head_sha", "f" * 40),
                                          ("conclusion", "failure"), ("event", "push")])
def test_github_producer_snapshot_changes_fail_closed(candidate, snapshot, field, value):
    candidate.api[snapshot][field] = value
    with pytest.raises(TRANSPORT.ArtifactVerificationError):
        candidate.verify()
    assert all(stream.closed for stream in candidate.transport.streams)


@pytest.mark.parametrize("mutation", ["missing", "corrupt", "truncated", "overlong"])
def test_missing_or_different_chunk_never_verifies(candidate, mutation):
    key = candidate.manifest["chunks"][1]["key"]
    if mutation == "missing":
        del candidate.objects[key]
    elif mutation == "corrupt":
        candidate.objects[key] = b"X" + candidate.objects[key][1:]
    elif mutation == "truncated":
        candidate.objects[key] = candidate.objects[key][:-1]
    else:
        candidate.objects[key] += b"X"
    with pytest.raises((TRANSPORT.ArtifactVerificationError, KeyError)):
        candidate.verify()
    assert all(stream.closed for stream in candidate.transport.streams)


@pytest.mark.parametrize("mutation", ["missing", "reordered", "duplicate", "cross-run", "external-url", "oversize"])
def test_chunk_descriptor_set_is_exact_and_bounded(candidate, mutation):
    parts = candidate.manifest["chunks"]
    if mutation == "missing":
        parts.pop()
    elif mutation == "reordered":
        parts.reverse()
    elif mutation == "duplicate":
        parts[1] = copy.deepcopy(parts[0])
    elif mutation == "cross-run":
        parts[0]["key"] = parts[0]["key"].replace(str(candidate.selection.run_id), "123")
    elif mutation == "external-url":
        parts[0]["key"] = "https://untrusted.invalid/chunk"
    else:
        parts[0]["sizeBytes"] = TRANSPORT.MAX_CHUNK_BYTES + 1
    candidate.rehash_manifest()
    with pytest.raises(TRANSPORT.ArtifactVerificationError):
        candidate.verify()
    assert not any("/chunks/" in path for _, path in candidate.transport.calls)


def test_individually_matching_chunks_still_require_whole_iso_hash(candidate):
    key = candidate.manifest["chunks"][1]["key"]
    candidate.objects[key] = b"X" + candidate.objects[key][1:]
    candidate.manifest["chunks"][1]["sha256"] = digest(candidate.objects[key])[7:]
    candidate.rehash_manifest()
    with pytest.raises(TRANSPORT.ArtifactVerificationError, match="media.sha256"):
        candidate.verify()


@pytest.mark.parametrize("mutation", ["duplicate", "missing", "symlink", "traversal", "oversize", "encrypted"])
def test_unsafe_archive_never_reaches_r2(candidate, mutation):
    name, raw = candidate.retained.receipt_path, encode(candidate.browser)
    entries = [(name, raw)]
    if mutation == "duplicate":
        entries.append((name, raw))
    elif mutation == "missing":
        entries = [("other.json", raw)]
    elif mutation == "symlink":
        info = zipfile.ZipInfo(name)
        info.create_system = 3
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        entries = [(info, raw)]
    elif mutation == "traversal":
        entries.append(("../outside.json", raw))
    elif mutation == "oversize":
        entries = [(name, b" " * (TRANSPORT.MAX_MANIFEST_BYTES + 1))]
    with pytest.warns(UserWarning) if mutation == "duplicate" else __import__("contextlib").nullcontext():
        candidate.repack_archive(entries)
    if mutation == "encrypted":
        raw_archive = bytearray(candidate.archive)
        offset = raw_archive.index(b"PK\x01\x02")
        raw_archive[offset + 8] |= 1
        candidate.archive = bytes(raw_archive)
        candidate.rehash_archive()
    with pytest.raises(TRANSPORT.ArtifactVerificationError):
        candidate.verify()
    assert not any(method == "object" for method, _ in candidate.transport.calls)


@pytest.mark.parametrize("mutation", ["duplicate-key", "non-finite", "invalid-utf8", "oversize"])
def test_manifest_exact_hash_is_checked_then_strict_bounded_json(candidate, mutation):
    raw = {"duplicate-key": b'{"schemaVersion":1,"schemaVersion":1}',
           "non-finite": b'{"value":1e999}', "invalid-utf8": b'\xff',
           "oversize": b" " * (TRANSPORT.MAX_MANIFEST_BYTES + 1)}[mutation]
    candidate.objects[candidate.manifest_key] = raw
    candidate.retained = replace(candidate.retained, manifest_sha256=digest(raw))
    with pytest.raises(TRANSPORT.ArtifactVerificationError):
        candidate.verify()
    assert not any("/chunks/" in path for _, path in candidate.transport.calls)


@pytest.mark.parametrize("mutation", ["both-locations", "no-location", "wrong-run-key", "unknown-kind", "native-r2"])
def test_v2_union_rejects_ambiguous_or_unsupported_transports(candidate, mutation):
    _, context, transport = join_documents(candidate, candidate.verify())
    producer = context["browserProducer"]
    if mutation == "both-locations":
        producer["artifact"]["mediaPath"] = "invented.iso"
    elif mutation == "no-location":
        del producer["mediaTransport"]
    elif mutation == "wrong-run-key":
        producer["mediaTransport"]["manifestKey"] = candidate.manifest_key.replace(str(candidate.selection.run_id), "123")
    elif mutation == "unknown-kind":
        producer["mediaTransport"]["kind"] = "other"
    else:
        context["nativeProducer"]["mediaTransport"] = producer["mediaTransport"]
    with pytest.raises(CONTRACT.ContractError):
        CONTRACT.validate_document(context)
    if mutation != "wrong-run-key":
        assert not Draft202012Validator(SCHEMA).is_valid(context)


def test_r2_media_claims_must_equal_existing_context_before_media_read(candidate):
    result = candidate.verify()
    native, context, transport = join_documents(candidate, result)
    for doc in (context, transport):
        doc["browserProducer"]["mediaTransport"]["media"] = {"sha256": "sha256:" + "f" * 64, "sizeBytes": 1}
    with pytest.raises(CONTRACT.ContractError, match="mediaTransport.media"):
        CONTRACT.check_consistency(result["browserReceiptBytes"], encode(native), candidate.media, context, transport)
