"""Check synthetic artifact snapshots without network or authentication claims."""
import base64
import copy
from dataclasses import FrozenInstanceError
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("iso_artifact_transport", ROOT / "scripts/iso_artifact_transport.py")
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)
CASE = json.loads((ROOT / "tests/fixtures/iso-artifact-transport-v1/case.json").read_text())


class CountingStream(io.BytesIO):
    def __init__(self, data):
        super().__init__(data)
        self.requests = []
        self.bytes_read = 0

    def read(self, size=-1):
        assert 0 < size <= 1024 * 1024, "archive reads must be bounded"
        self.requests.append(size)
        chunk = super().read(size)
        self.bytes_read += len(chunk)
        return chunk


class FakeTransport:
    """Only the selected endpoints exist; wrong requests cannot silently pass."""
    def __init__(self, case):
        self.case = case
        self.calls = []
        self.stream = CountingStream(base64.b64decode(case["archiveBase64"]))
        self.error_at = None
        self.error = OSError("synthetic transport failure")

    def _record(self, method, path):
        index = len(self.calls)
        assert [method, path] == self.case["expectedPaths"][index]
        self.calls.append([method, path])
        if index == self.error_at:
            raise self.error
        return index

    def get_json(self, path):
        index = self._record("json", path)
        if index >= 4:
            assert self.stream.closed, "archive must close before post-collection API calls"
        return copy.deepcopy(self.case[{0: "currentBefore", 1: "attempt", 2: "artifact",
                                        4: "artifactAfter", 5: "currentAfter"}[index]])

    def open_archive(self, path):
        self._record("archive", path)
        return self.stream


@pytest.fixture
def case():
    return copy.deepcopy(CASE)


@pytest.fixture
def transport(case):
    return FakeTransport(case)


def metadata(case, transport):
    return MODULE._metadata(MODULE.ReviewedPolicy(**case["policy"]),
                            MODULE.ArtifactSelection(**case["selection"]), transport)


def verify(case, transport):
    return MODULE.verify_artifact_snapshot(MODULE.ReviewedPolicy(**case["policy"]),
                                          MODULE.ArtifactSelection(**case["selection"]), transport)


def assert_classified(error):
    assert isinstance(error, ValueError)
    assert isinstance(error.code, str) and error.code
    assert isinstance(error.field, str) and error.field


def mutate(document, path, value, *, missing=False):
    for key in path[:-1]:
        document = document[key]
    if missing:
        del document[path[-1]]
    else:
        document[path[-1]] = value


RUN_FIELDS = [
    ("id",), ("run_attempt",), ("workflow_id",), ("path",), ("head_sha",),
    ("head_branch",), ("event",), ("status",), ("conclusion",),
    ("repository",), ("repository", "id"), ("repository", "full_name"), ("repository", "fork"),
    ("head_repository",), ("head_repository", "id"), ("head_repository", "full_name"),
    ("head_repository", "fork"), ("pull_requests",),
]
ARTIFACT_FIELDS = [
    ("id",), ("expired",), ("digest",), ("size_in_bytes",), ("workflow_run",),
    ("workflow_run", "id"), ("workflow_run", "repository_id"),
    ("workflow_run", "head_repository_id"), ("workflow_run", "head_branch"),
    ("workflow_run", "head_sha"),
]


def test_metadata_selects_only_explicit_endpoints(case, transport):
    assert metadata(case, transport) == (
        "/repos/tuna-os/iso-builder/actions/runs/900000000001",
        "/repos/tuna-os/iso-builder/actions/artifacts/900000000002",
        168,
    )
    assert transport.calls == case["expectedPaths"][:3]
    assert transport.stream.requests == []
    assert "run_attempt" not in case["artifact"]["workflow_run"]


def test_fixture_archive_is_byte_bound_and_synthetic(case):
    raw = base64.b64decode(case["archiveBase64"], validate=True)
    assert len(raw) == case["archiveSizeBytes"] == 168
    assert "sha256:" + hashlib.sha256(raw).hexdigest() == case["archiveSha256"]
    assert case["policy"]["archive_sha256"] == case["artifact"]["digest"] == case["archiveSha256"]
    assert case["selection"]["run_id"] != 39321317858


@pytest.mark.parametrize("kind,field", [("policy", "repository"), ("selection", "run_id")])
def test_reviewed_policy_and_selection_are_frozen(case, kind, field):
    constructor = MODULE.ReviewedPolicy if kind == "policy" else MODULE.ArtifactSelection
    instance = constructor(**case[kind])
    with pytest.raises(FrozenInstanceError):
        setattr(instance, field, None)


@pytest.mark.parametrize("snapshot", ["currentBefore", "attempt"])
@pytest.mark.parametrize("path", RUN_FIELDS)
@pytest.mark.parametrize("missing", [False, True], ids=["null", "missing"])
def test_consumed_run_fields_are_required(case, transport, snapshot, path, missing):
    mutate(case[snapshot], path, None, missing=missing)
    with pytest.raises(MODULE.ArtifactVerificationError) as caught:
        metadata(case, transport)
    assert_classified(caught.value)
    assert transport.stream.requests == []


@pytest.mark.parametrize("snapshot", ["currentBefore", "attempt"])
@pytest.mark.parametrize("path,value", [
    (("id",), 999), (("run_attempt",), 2), (("workflow_id",), 999),
    (("path",), ".github/workflows/other.yml"), (("path",), ".github/workflows/ci.yml@main"),
    (("head_sha",), "a" * 40), (("head_branch",), "feature"),
    (("event",), "push"), (("event",), "pull_request"), (("event",), "pull_request_target"),
    (("status",), "in_progress"), (("conclusion",), "failure"), (("conclusion",), "neutral"),
    (("repository", "id"), 999), (("repository", "full_name"), "fork/iso-builder"),
    (("repository", "fork"), True), (("head_repository", "id"), 999),
    (("head_repository", "full_name"), "fork/iso-builder"), (("head_repository", "fork"), True),
    (("pull_requests",), [{"number": 1}]),
])
def test_wrong_run_coordinates_reject_before_archive(case, transport, snapshot, path, value):
    mutate(case[snapshot], path, value)
    with pytest.raises(MODULE.ArtifactVerificationError) as caught:
        metadata(case, transport)
    assert_classified(caught.value)
    assert transport.stream.requests == []


@pytest.mark.parametrize("path", ARTIFACT_FIELDS)
@pytest.mark.parametrize("missing", [False, True], ids=["null", "missing"])
def test_consumed_artifact_fields_are_required(case, transport, path, missing):
    mutate(case["artifact"], path, None, missing=missing)
    with pytest.raises(MODULE.ArtifactVerificationError) as caught:
        metadata(case, transport)
    assert_classified(caught.value)
    assert transport.stream.requests == []


@pytest.mark.parametrize("snapshot,path", [
    *[(snapshot, path) for snapshot in ("currentBefore", "attempt") for path in RUN_FIELDS],
    *[("artifact", path) for path in ARTIFACT_FIELDS],
])
def test_every_consumed_api_field_rejects_wrong_type(case, transport, snapshot, path):
    original = case[snapshot]
    for key in path:
        original = original[key]
    wrong_type = {str: False, int: True, bool: 0, list: {}, dict: []}[type(original)]
    mutate(case[snapshot], path, wrong_type)
    with pytest.raises(MODULE.ArtifactVerificationError) as caught:
        metadata(case, transport)
    assert_classified(caught.value)
    assert transport.stream.requests == []


@pytest.mark.parametrize("path,value", [
    (("id",), 999), (("expired",), True), (("expired",), 0),
    (("digest",), "sha256:" + "9" * 64), (("digest",), "invalid"),
    (("size_in_bytes",), 0), (("size_in_bytes",), -1), (("size_in_bytes",), 4097),
    (("workflow_run", "id"), 999), (("workflow_run", "repository_id"), 999),
    (("workflow_run", "head_repository_id"), 999),
    (("workflow_run", "head_branch"), "feature"), (("workflow_run", "head_sha"), "a" * 40),
])
def test_wrong_artifact_coordinates_reject_before_archive(case, transport, path, value):
    mutate(case["artifact"], path, value)
    with pytest.raises(MODULE.ArtifactVerificationError) as caught:
        metadata(case, transport)
    assert_classified(caught.value)
    assert transport.stream.requests == []


@pytest.mark.parametrize("snapshot,path", [
    *[(snapshot, path) for snapshot in ("currentBefore", "attempt")
      for path in (("id",), ("run_attempt",), ("workflow_id",),
                   ("repository", "id"), ("head_repository", "id"))],
    *[("artifact", path) for path in (("id",), ("size_in_bytes",), ("workflow_run", "id"),
                                      ("workflow_run", "repository_id"), ("workflow_run", "head_repository_id"))],
])
@pytest.mark.parametrize("value", [True, False, "1", 1.0, [], {}])
def test_api_integer_fields_reject_wrong_types(case, transport, snapshot, path, value):
    mutate(case[snapshot], path, value)
    with pytest.raises(MODULE.ArtifactVerificationError):
        metadata(case, transport)
    assert transport.stream.requests == []


@pytest.mark.parametrize("kind,field", [
    ("policy", "repository_id"), ("policy", "workflow_id"), ("policy", "max_archive_bytes"),
    ("selection", "run_id"), ("selection", "attempt"), ("selection", "artifact_id"),
])
@pytest.mark.parametrize("value", [True, False, 0, -1, "latest", 1.0, None])
def test_input_integer_fields_fail_before_any_request(case, transport, kind, field, value):
    case[kind][field] = value
    with pytest.raises(MODULE.ArtifactVerificationError) as caught:
        metadata(case, transport)
    assert_classified(caught.value)
    assert transport.calls == []


@pytest.mark.parametrize("field,value", [
    ("repository", "other/repo"), ("repository", "../tuna-os/iso-builder"),
    ("workflow_path", ".github/workflows/other.yml"), ("ref", "refs/heads/feature"),
    ("source_revision", "main"), ("source_revision", "a" * 39),
    ("source_revision", "a" * 41), ("archive_sha256", "sha256:" + "z" * 64),
    ("archive_sha256", None),
])
def test_policy_scope_cannot_select_arbitrary_sources(case, transport, field, value):
    case["policy"][field] = value
    with pytest.raises(MODULE.ArtifactVerificationError):
        metadata(case, transport)
    assert transport.calls == []


def test_explicit_rerun_selection_is_not_supported(case, transport):
    case["selection"]["attempt"] = 2
    with pytest.raises(MODULE.ArtifactVerificationError) as caught:
        metadata(case, transport)
    assert caught.value.field == "selection.attempt"
    assert transport.calls == []


@pytest.mark.parametrize("kind", ["policy", "selection"])
@pytest.mark.parametrize("value", [None, {}, [], "latest"])
def test_policy_and_selection_require_the_declared_types(case, transport, kind, value):
    inputs = {"policy": MODULE.ReviewedPolicy(**case["policy"]),
              "selection": MODULE.ArtifactSelection(**case["selection"])}
    inputs[kind] = value
    with pytest.raises(MODULE.ArtifactVerificationError) as caught:
        MODULE._metadata(inputs["policy"], inputs["selection"], transport)
    assert caught.value.code == "invalid_input"
    assert transport.calls == []


@pytest.mark.parametrize("snapshot", ["currentBefore", "attempt", "artifact"])
@pytest.mark.parametrize("value", [None, [], "object", True])
def test_api_roots_must_be_objects(case, transport, snapshot, value):
    case[snapshot] = value
    with pytest.raises(MODULE.ArtifactVerificationError):
        metadata(case, transport)
    assert transport.stream.requests == []


def test_unrelated_api_fields_and_urls_are_not_selection_inputs(case, transport):
    for snapshot in ("currentBefore", "attempt", "artifact"):
        case[snapshot]["url"] = "https://untrusted.invalid/latest"
        case[snapshot]["archive_download_url"] = "file:///untrusted"
        case[snapshot]["unrelated"] = {"arbitrary": [1, 2, 3]}
    metadata(case, transport)
    assert transport.calls == case["expectedPaths"][:3]


@pytest.mark.parametrize("index", [0, 1, 2])
def test_metadata_transport_failures_propagate_without_archive_reads(case, transport, index):
    transport.error_at = index
    with pytest.raises(OSError) as caught:
        metadata(case, transport)
    assert caught.value is transport.error
    assert transport.stream.requests == []


def test_metadata_returns_size_for_later_exact_byte_verification(case, transport):
    case["artifact"]["size_in_bytes"] = 1
    assert metadata(case, transport)[2] == 1
    assert transport.calls == case["expectedPaths"][:3]


def test_full_snapshot_checks_exact_bytes_coordinates_and_request_order(case, transport):
    result = verify(case, transport)
    assert result == case["expectedResult"]
    assert transport.calls == case["expectedPaths"]
    assert transport.stream.bytes_read == 168
    assert transport.stream.closed
    assert not {"nativeProducer", "qualified", "consistency_valid", "authenticated"} & result.keys()


@pytest.mark.parametrize("snapshot,path", [
    *[(snapshot, path) for snapshot in ("currentBefore", "attempt", "currentAfter") for path in RUN_FIELDS],
    *[(snapshot, path) for snapshot in ("artifact", "artifactAfter") for path in ARTIFACT_FIELDS],
])
@pytest.mark.parametrize("mutation", ["missing", "wrong-type"])
def test_public_api_revalidates_every_consumed_field(case, transport, snapshot, path, mutation):
    original = case[snapshot]
    for key in path:
        original = original[key]
    wrong_type = {str: False, int: True, bool: 0, list: {}, dict: []}[type(original)]
    mutate(case[snapshot], path, wrong_type, missing=mutation == "missing")
    with pytest.raises(MODULE.ArtifactVerificationError) as caught:
        verify(case, transport)
    assert_classified(caught.value)
    if snapshot in ("artifactAfter", "currentAfter"):
        assert transport.stream.bytes_read == 168
        assert transport.stream.closed
    else:
        assert transport.stream.requests == []
        assert all(method != "archive" for method, _ in transport.calls)


@pytest.mark.parametrize("snapshot,path,value", [
    ("currentBefore", ("run_attempt",), 2), ("currentAfter", ("run_attempt",), 2),
    ("currentAfter", ("id",), 999), ("currentAfter", ("head_sha",), "a" * 40),
    ("currentAfter", ("workflow_id",), 999), ("currentAfter", ("status",), "in_progress"),
    ("currentAfter", ("conclusion",), "failure"), ("currentAfter", ("event",), "push"),
    ("currentAfter", ("head_branch",), "feature"),
    ("currentAfter", ("repository", "id"), 999),
    ("currentAfter", ("head_repository", "fork"), True),
    ("currentAfter", ("pull_requests",), [{"number": 1}]),
    ("artifactAfter", ("id",), 999), ("artifactAfter", ("expired",), True),
    ("artifactAfter", ("digest",), "sha256:" + "9" * 64),
    ("artifactAfter", ("size_in_bytes",), 169),
    ("artifactAfter", ("workflow_run", "id"), 999),
    ("artifactAfter", ("workflow_run", "head_sha"), "a" * 40),
    ("artifactAfter", ("workflow_run", "head_repository_id"), 999),
])
def test_visible_rerun_or_changed_snapshot_never_succeeds(case, transport, snapshot, path, value):
    mutate(case[snapshot], path, value)
    with pytest.raises(MODULE.ArtifactVerificationError) as caught:
        verify(case, transport)
    assert caught.value.code == "identity_mismatch"
    if snapshot == "currentBefore":
        assert transport.stream.requests == []
    else:
        assert transport.stream.closed
        assert transport.stream.bytes_read == 168


@pytest.mark.parametrize("mutation", ["corrupt", "truncated", "overlong", "empty"])
def test_archive_content_failures_close_stream_before_post_metadata(case, transport, mutation):
    original = base64.b64decode(case["archiveBase64"])
    changed = {"corrupt": b"X" + original[1:], "truncated": original[:-1],
               "overlong": original + b"X", "empty": b""}[mutation]
    transport.stream = CountingStream(changed)
    with pytest.raises(MODULE.ArtifactVerificationError) as caught:
        verify(case, transport)
    expected = "identity_mismatch" if mutation == "corrupt" else "archive_size_mismatch"
    assert caught.value.code == expected
    assert transport.calls == case["expectedPaths"][:4]
    assert transport.stream.bytes_read == len(changed)
    assert transport.stream.closed


@pytest.mark.parametrize("reported_size", [1, 167, 169, 4096])
def test_actual_stream_length_must_equal_api_size(case, transport, reported_size):
    case["artifact"]["size_in_bytes"] = reported_size
    with pytest.raises(MODULE.ArtifactVerificationError) as caught:
        verify(case, transport)
    assert caught.value.code == "archive_size_mismatch"
    assert transport.stream.bytes_read <= min(168, reported_size + 1)
    assert transport.stream.closed
    assert transport.calls == case["expectedPaths"][:4]


def test_api_digest_mismatch_prevents_archive_open(case, transport):
    case["artifact"]["digest"] = "sha256:" + "9" * 64
    with pytest.raises(MODULE.ArtifactVerificationError) as caught:
        verify(case, transport)
    assert caught.value.code == "identity_mismatch"
    assert caught.value.field == "artifact.digest"
    assert transport.stream.requests == []
    assert transport.calls == case["expectedPaths"][:3]


def test_matching_api_and_policy_digest_still_need_matching_bytes(case, transport):
    case["policy"]["archive_sha256"] = case["artifact"]["digest"] = "sha256:" + "9" * 64
    with pytest.raises(MODULE.ArtifactVerificationError) as caught:
        verify(case, transport)
    assert caught.value.field == "archive.sha256"
    assert transport.stream.bytes_read == 168
    assert transport.stream.closed


def test_independent_archive_cap_rejects_before_download(case, transport):
    case["policy"]["max_archive_bytes"] = 167
    with pytest.raises(MODULE.ArtifactVerificationError) as caught:
        verify(case, transport)
    assert caught.value.code == "archive_limit"
    assert transport.stream.requests == []


def test_archive_exactly_at_independent_limit_passes(case, transport):
    case["policy"]["max_archive_bytes"] = 168
    assert verify(case, transport) == case["expectedResult"]
    assert transport.stream.closed


def test_endless_archive_stops_after_one_excess_byte(case, transport):
    class EndlessStream(CountingStream):
        def read(self, size=-1):
            assert 0 < size <= 1024 * 1024
            self.requests.append(size)
            self.bytes_read += size
            return b"X" * size

    transport.stream = EndlessStream(b"")
    with pytest.raises(MODULE.ArtifactVerificationError) as caught:
        verify(case, transport)
    assert caught.value.code == "archive_size_mismatch"
    assert transport.stream.bytes_read == 169
    assert transport.stream.closed


@pytest.mark.parametrize("returned", [None, "text", bytearray(b"x"), memoryview(b"x"), 1])
def test_nonbinary_read_results_are_classified_and_closed(case, transport, returned):
    class WrongRead(CountingStream):
        def read(self, size=-1):
            return returned

    transport.stream = WrongRead(b"")
    with pytest.raises(MODULE.ArtifactVerificationError) as caught:
        verify(case, transport)
    assert caught.value.code == "invalid_stream"
    assert transport.stream.closed


def test_stream_cannot_return_more_bytes_than_requested(case, transport):
    class OversizedRead(CountingStream):
        def read(self, size=-1):
            return b"x" * (size + 1)

    transport.stream = OversizedRead(b"")
    with pytest.raises(MODULE.ArtifactVerificationError) as caught:
        verify(case, transport)
    assert caught.value.code == "invalid_stream"
    assert transport.stream.closed


def test_seekable_archive_must_start_at_zero(case, transport):
    transport.stream.seek(1)
    with pytest.raises(MODULE.ArtifactVerificationError) as caught:
        verify(case, transport)
    assert caught.value.code == "invalid_stream"
    assert transport.stream.requests == []
    assert transport.stream.closed


def test_nonseekable_archive_can_be_hashed_without_tell(case, transport):
    class NonSeekable(CountingStream):
        def seekable(self):
            return False

        def tell(self):
            raise io.UnsupportedOperation("nonseekable")

    transport.stream = NonSeekable(base64.b64decode(case["archiveBase64"]))
    assert verify(case, transport) == case["expectedResult"]
    assert transport.stream.closed


def test_short_reads_are_not_mistaken_for_eof(case, transport):
    class ShortReads(CountingStream):
        def read(self, size=-1):
            return super().read(min(size, 7))

    transport.stream = ShortReads(base64.b64decode(case["archiveBase64"]))
    assert verify(case, transport) == case["expectedResult"]
    assert len(transport.stream.requests) > 20
    assert transport.stream.closed


def test_large_archive_is_hashed_in_at_most_one_mib_chunks(case, transport):
    raw = b"synthetic bounded stream\n" * 100000
    sha = "sha256:" + hashlib.sha256(raw).hexdigest()
    case["policy"].update(archive_sha256=sha, max_archive_bytes=len(raw))
    for snapshot in ("artifact", "artifactAfter"):
        case[snapshot].update(digest=sha, size_in_bytes=len(raw))
    transport.stream = CountingStream(raw)
    result = verify(case, transport)
    assert result["archiveSha256"] == sha
    assert result["sizeBytes"] == len(raw)
    assert transport.stream.bytes_read == len(raw)
    assert len(transport.stream.requests) >= 4
    assert max(transport.stream.requests) == 1024 * 1024
    assert transport.stream.closed


def test_stream_read_exception_propagates_and_closes(case, transport):
    error = OSError("synthetic read failure")

    class BrokenRead(CountingStream):
        def read(self, size=-1):
            raise error

    transport.stream = BrokenRead(b"")
    with pytest.raises(OSError) as caught:
        verify(case, transport)
    assert caught.value is error
    assert transport.stream.closed
    assert transport.calls == case["expectedPaths"][:4]


def test_stream_close_exception_prevents_success(case, transport):
    error = OSError("synthetic close failure")

    class BrokenClose(CountingStream):
        def __exit__(self, *args):
            super().__exit__(*args)
            raise error

    transport.stream = BrokenClose(base64.b64decode(case["archiveBase64"]))
    with pytest.raises(OSError) as caught:
        verify(case, transport)
    assert caught.value is error
    assert transport.stream.closed
    assert transport.calls == case["expectedPaths"][:4]


@pytest.mark.parametrize("index", range(6))
def test_public_transport_failures_never_return_success(case, transport, index):
    transport.error_at = index
    with pytest.raises(OSError) as caught:
        verify(case, transport)
    assert caught.value is transport.error
    assert transport.calls == case["expectedPaths"][:index + 1]
    if index > 3:
        assert transport.stream.closed
    else:
        assert transport.stream.requests == []


def test_extra_unrelated_fields_do_not_change_full_snapshot(case, transport):
    for snapshot in ("currentBefore", "attempt", "artifact", "artifactAfter", "currentAfter"):
        case[snapshot]["archive_download_url"] = "https://untrusted.invalid/latest"
        case[snapshot]["unrelated"] = {"value": [True, None, 9]}
    assert verify(case, transport) == case["expectedResult"]
    assert transport.calls == case["expectedPaths"]
