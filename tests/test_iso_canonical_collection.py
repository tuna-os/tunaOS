"""Bounded ZIP/receipt/media integration; all fixture executions are synthetic."""
import copy
import hashlib
import io
import json
from pathlib import Path
import struct
import sys
import urllib.error
import zipfile

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
try:
    import iso_canonical_collection as COLLECT
    import iso_media_receipt_handoff as HANDOFF
finally:
    sys.path.remove(str(ROOT / "scripts"))

FIXTURES = ROOT / "tests/fixtures/iso-media-provenance-v2"
CASES = json.loads((FIXTURES / "cases.json").read_text())
MEDIA = (FIXTURES / CASES["mediaFile"]).read_bytes()
BASE = json.loads((ROOT / "tests/fixtures/iso-artifact-transport-v1/case.json").read_text())


def encode(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def digest(raw):
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def archive(entries):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as zipped:
        for name, data in entries:
            zipped.writestr(name, data)
    return output.getvalue()


class Transport:
    def __init__(self, policy, selection, raw):
        self.policy, self.selection, self.raw = policy, selection, raw
        self.calls = []
        self.run = copy.deepcopy(BASE["currentBefore"])
        self.run.update(id=selection.run_id, head_sha=policy.source_revision)
        self.metadata = copy.deepcopy(BASE["artifact"])
        self.metadata.update(id=selection.artifact_id, digest=policy.archive_sha256, size_in_bytes=len(raw))
        self.metadata["workflow_run"].update(id=selection.run_id, head_sha=policy.source_revision)
        self.after_run = None
        self.after_artifact = None
        self.run_reads = self.artifact_reads = 0

    def get_json(self, path):
        self.calls.append(("json", path))
        base = f"/repos/{self.policy.repository}/actions"
        if path == f"{base}/runs/{self.selection.run_id}/attempts/1":
            return copy.deepcopy(self.run)
        if path == f"{base}/runs/{self.selection.run_id}":
            self.run_reads += 1
            return copy.deepcopy(self.after_run if self.run_reads > 1 and self.after_run is not None else self.run)
        assert path == f"{base}/artifacts/{self.selection.artifact_id}"
        self.artifact_reads += 1
        return copy.deepcopy(self.after_artifact if self.artifact_reads > 1 and self.after_artifact is not None else self.metadata)

    def open_archive(self, path):
        self.calls.append(("archive", path))
        assert path == f"/repos/{self.policy.repository}/actions/artifacts/{self.selection.artifact_id}/zip"
        return io.BytesIO(self.raw)


def pair(*, extra_browser=(), native_mutation=None, media=MEDIA):
    browser = json.loads(CASES["browserReceiptUtf8"])
    native = json.loads(CASES["nativeReceiptUtf8"])
    for index, document in enumerate((browser, native), 1):
        document["run"].update(repository="tuna-os/iso-builder", workflowPath=".github/workflows/ci.yml",
                               workflowRevision=str(index) * 40, sourceRevision=str(index) * 40,
                               runId=100 + index, runAttempt=1)
    raw_browser = encode(browser)
    native["browserReceiptSha256"] = digest(raw_browser)
    if native_mutation:
        native_mutation(native)
    raw_native = encode(native)
    archives = (archive([("receipts/browser.json", raw_browser), ("media.iso", media), *extra_browser]),
                archive([("receipts/native.json", raw_native)]))
    policies = tuple(COLLECT.artifact.ReviewedPolicy(**{
        **BASE["policy"], "source_revision": str(index) * 40,
        "archive_sha256": digest(raw), "max_archive_bytes": 1024 * 1024,
    }) for index, raw in enumerate(archives, 1))
    selections = tuple(COLLECT.artifact.ArtifactSelection(100 + index, 1, 200 + index) for index in (1, 2))
    context = {"schemaVersion": 2, "kind": "iso-media-expected-context"}
    for key in ("media", "input_descriptors", "build_request_sha256", "recipe_sha256", "config_sha256", "browser"):
        context[key] = copy.deepcopy(browser[key])
    context["harness"] = copy.deepcopy(native["harness"])
    for name, document, raw, policy, selection in zip(
            ("browserProducer", "nativeProducer"), (browser, native), (raw_browser, raw_native), policies, selections):
        context[name] = {"run": copy.deepcopy(document["run"]), "receiptSha256": digest(raw),
                         "artifact": {"id": selection.artifact_id, "archiveSha256": policy.archive_sha256,
                                      "expired": False, "receiptPath": f"receipts/{name.removesuffix('Producer')}.json"}}
    context["browserProducer"]["artifact"]["mediaPath"] = "media.iso"
    transports = tuple(Transport(policy, selection, raw) for policy, selection, raw in zip(policies, selections, archives))
    return context, policies, selections, transports


def collect(case):
    context, policies, selections, transports = case
    return COLLECT.collect_canonical_v2(context, policies[0], selections[0], policies[1], selections[1],
                                         None, None, _transports=transports)


def test_complete_pair_hashes_actual_archive_receipts_and_media_without_admission():
    case = pair()
    result = collect(case)
    assert result["status"] == "consistent_not_admitted"
    assert result["authentication"] == "not_authenticated"
    assert result["qualification"] == "not-assessed"
    assert result["consistency_valid"] is True
    assert result["observedTransport"]["browserProducer"]["receiptSha256"] == case[0]["browserProducer"]["receiptSha256"]
    for transport in case[3]:
        assert [kind for kind, _ in transport.calls] == ["json", "json", "json", "archive", "json", "json"]


def test_failed_live_shape_is_collectable_only_as_diagnostic():
    context, policies, selections, transports = pair()
    transports[0].run["conclusion"] = "failure"
    result = COLLECT.collect_artifact_diagnostics(policies[0], selections[0], None, None, _transport=transports[0])
    assert result["archive_digest_verified"] is True
    assert result["snapshot_checks_passed"] is False
    assert result["authentication"] == "not_authenticated"
    assert result["refusals"] == [{"code": "identity_mismatch", "field": field} for field in
                                  ("run_before.conclusion", "attempt.conclusion", "run_after.conclusion")]
    with pytest.raises(COLLECT.CollectionError, match="run_before.conclusion"):
        collect((context, policies, selections, tuple(Transport(p, s, t.raw) if i else t
                for i, (p, s, t) in enumerate(zip(policies, selections, transports)))))


@pytest.mark.parametrize("mutation,field", [
    (lambda c: c["media"].update(sizeBytes=COLLECT.artifact.MAX_ISO_BYTES + 1), "media.sizeBytes"),
    (lambda c: c["browserProducer"]["artifact"].update(id=999), "artifact.id"),
    (lambda c: c["nativeProducer"]["run"].update(runAttempt=2), "run.runAttempt"),
])
def test_independent_policy_and_cap_fail_before_network(mutation, field):
    case = pair()
    mutation(case[0])
    with pytest.raises(COLLECT.CollectionError, match=field):
        collect(case)
    assert all(not transport.calls for transport in case[3])


def test_swapped_raw_browser_binding_is_not_repaired_from_expected_context():
    case = pair(native_mutation=lambda native: native.update(browserReceiptSha256="sha256:" + "f" * 64))
    with pytest.raises(COLLECT.contract.ContractError, match="native.browserReceiptSha256"):
        collect(case)


def test_native_source_identity_mismatch_is_not_repaired():
    case = pair(native_mutation=lambda native: native["observed"]["plain"].update(
        sourceDigest="sha256:" + "f" * 64, bootedDigest="sha256:" + "f" * 64))
    with pytest.raises(COLLECT.contract.ContractError, match="plain.sourceDigest"):
        collect(case)


@pytest.mark.parametrize("path", ["../escape.json", "receipts//bad.json", "/absolute.json", "media.iso"])
def test_unsafe_or_duplicate_members_refuse_without_extracting(path):
    case = pair(extra_browser=((path, b"not media"),))
    with pytest.raises((COLLECT.CollectionError, COLLECT.artifact.ArtifactVerificationError)):
        collect(case)


def test_archive_mutation_after_hashing_refuses():
    case = pair()
    case[3][0].after_artifact = copy.deepcopy(case[3][0].metadata)
    case[3][0].after_artifact["expired"] = True
    with pytest.raises(COLLECT.artifact.ArtifactVerificationError, match="artifact.expired"):
        collect(case)


def test_visible_run_rerun_after_hashing_refuses():
    case = pair()
    case[3][0].after_run = copy.deepcopy(case[3][0].run)
    case[3][0].after_run["run_attempt"] = 2
    with pytest.raises(COLLECT.CollectionError, match="run.snapshot"):
        collect(case)


def test_current_diagnostic_shape_reports_size_legacy_and_identity_gaps_exactly():
    measured = {"kind": "diagnostic-build-measurements", "iso": {"sha256": "sha256:" + "a" * 64,
                "sizeBytes": 11445235712}, "missingIdentity": ["producer", "frontend"]}
    legacy = {"schemaVersion": 1, "kind": "qualification-evidence", "half": "browser"}
    result = COLLECT.inspect_browser_diagnostics(encode(measured), encode(legacy))
    assert result["status"] == "refused"
    assert result["refusals"] == [
        {"code": "media_limit", "field": "media.sizeBytes"},
        {"code": "legacy_receipt", "field": "browser.schemaVersion"},
        {"code": "missing_observation", "field": "producer"},
        {"code": "missing_observation", "field": "frontend"},
        {"code": "missing_observation", "field": "browserObservedInput"},
    ]


def test_same_size_wrong_media_is_not_repaired_from_receipt_hash():
    case = pair(media=bytes([MEDIA[0] ^ 1]) + MEDIA[1:])
    with pytest.raises(COLLECT.contract.ContractError, match="media"):
        collect(case)


def test_retained_media_refuses_without_new_signer_or_archive_fallback():
    case = pair()
    producer = case[0]["browserProducer"]
    del producer["artifact"]["mediaPath"]
    producer["mediaTransport"] = {
        "kind": "r2-chunked-candidate", "endpoint": "https://" + "a" * 32 + ".r2.cloudflarestorage.com",
        "bucket": "synthetic-fixture",
        "manifestKey": "browser-iso/candidates/101/1/yellowfin-gnome/s1/manifest.json",
        "manifestSha256": "sha256:" + "f" * 64, "media": copy.deepcopy(case[0]["media"]),
    }
    with pytest.raises(COLLECT.CollectionError, match="retained_signer_required"):
        collect(case)
    assert all(not transport.calls for transport in case[3])


@pytest.mark.parametrize("kind", ["declared-count", "actual-count", "directory-bytes"])
def test_directory_limits_precede_zipinfo_construction(monkeypatch, kind):
    raw = bytearray(archive([(f"entry-{index}.json", b"{}") for index in range(257 if kind == "actual-count" else 1)]))
    end = raw.rfind(b"PK\x05\x06")
    if kind == "declared-count":
        struct.pack_into("<2H", raw, end + 8, 257, 257)
    elif kind == "actual-count":
        struct.pack_into("<2H", raw, end + 8, 1, 1)
    else:
        struct.pack_into("<I", raw, end + 12, COLLECT.MAX_DIRECTORY_BYTES + 1)
    def forbidden(*_args, **_kwargs):
        raise AssertionError("ZipInfo allocation preceded directory bounds")
    monkeypatch.setattr(COLLECT.zipfile, "ZipFile", forbidden)
    with pytest.raises(COLLECT.CollectionError, match="archive_member_limit"):
        COLLECT._bounded_zip(io.BytesIO(raw))


def test_zip64_directory_is_bounded_and_readable_without_large_fixture():
    raw = archive([("receipt.json", b"{}")])
    end = raw.rfind(b"PK\x05\x06")
    fields = struct.unpack_from("<4s4H2IH", raw, end)
    record = struct.pack("<4sQ2H2I4Q", b"PK\x06\x06", 44, 45, 45, 0, 0,
                         fields[4], fields[4], fields[5], fields[6])
    locator = struct.pack("<4sIQI", b"PK\x06\x07", 0, end, 1)
    ending = struct.pack("<4s4H2IH", b"PK\x05\x06", 0, 0, 65535, 65535,
                         0xffffffff, 0xffffffff, 0)
    with COLLECT._bounded_zip(io.BytesIO(raw[:end] + record + locator + ending)) as zipped:
        assert zipped.read("receipt.json") == b"{}"


def test_github_archive_api_negotiates_supported_media_type_before_binary_redirect():
    _, policies, selections, transports = pair()
    raw = transports[0].raw
    api_url = (f"https://api.github.com/repos/{policies[0].repository}/actions/artifacts/"
               f"{selections[0].artifact_id}/zip")

    class Response(io.BytesIO):
        status = 200
        headers = {"Content-Length": str(len(raw))}

        def geturl(self):
            return api_url

        def settimeout(self, timeout):
            assert timeout > 0

    class Api:
        def open(self, request, timeout):
            # GitHub's REST archive endpoint returns HTTP415 for octet-stream;
            # binary Accept belongs only on the credential-free redirected GET.
            if request.get_header("Accept") != "application/vnd.github+json":
                raise urllib.error.HTTPError(api_url, 415, "unsupported media type", {}, None)
            assert request.get_header("Authorization") == "Bearer synthetic-token"
            return Response(raw)

    network = COLLECT.http.ReviewedNetworkPolicy(
        ("https://artifacts.example.test",), 3, 5, 30, 65536, 65536, 1024 * 1024)
    transport = COLLECT.http.AuthoritativeTransport(
        policies[0], selections[0], network, "synthetic-token", _openers=(Api(), Api(), Api()))
    with transport.open_archive(api_url.removeprefix(COLLECT.http.API_ORIGIN)) as response:
        assert response.read() == raw


def observation():
    browser = json.loads(CASES["browserReceiptUtf8"])
    descriptors = browser["input_descriptors"]
    values = {"selection_id": "operation-1-attempt-1", "completed_selection_id": "operation-1-attempt-1",
              "build_status": "completed", "bytes_written": len(MEDIA),
              "source_manifest": descriptors["source"], "overlay": descriptors["overlay"],
              "deployed_frontend": descriptors["installer"], "loaded_engine": descriptors["engine"],
              "browser": browser["browser"], "resources": browser["resources"], "producer_run": browser["run"]}
    values.update({key: browser[key] for key in ("build_request_sha256", "recipe_sha256", "config_sha256")})
    return {"schemaVersion": 1, "kind": "browser-observed-input", "qualification": "not-assessed",
            "observed": values, "missingFields": [], "media": browser["media"], "measurements": {}}


class SavedMedia:
    def __init__(self, data=MEDIA):
        self.data, self.closed = data, False

    def finish(self):
        self.closed = True

    def snapshot_token(self):
        assert self.closed
        return (1, len(self.data))

    def open(self):
        assert self.closed
        return io.BytesIO(self.data)


def test_complete_observation_finalizes_only_after_saved_media_measurement():
    source = SavedMedia()
    candidate = HANDOFF.finalize_browser_observation(encode(observation()), source)
    assert source.closed
    assert candidate.receipt_bytes == CASES["browserReceiptUtf8"].encode()
    assert candidate.qualification == "not-assessed"


def test_incomplete_observation_does_not_touch_sink_or_fill_from_measurements():
    envelope = observation()
    del envelope["observed"]["recipe_sha256"]
    envelope["missingFields"] = ["recipe_sha256"]
    envelope["measurements"]["catalogRecipe"] = "sha256:" + "a" * 64
    source = SavedMedia()
    with pytest.raises(HANDOFF.ReceiptHandoffError, match="envelope.missingFields"):
        HANDOFF.finalize_browser_observation(encode(envelope), source)
    assert source.closed is False


def test_observed_digest_cannot_substitute_for_reopened_media_hash():
    envelope = observation()
    envelope["media"]["sha256"] = "sha256:" + "f" * 64
    with pytest.raises(HANDOFF.ReceiptHandoffError, match="envelope.media.sha256"):
        HANDOFF.finalize_browser_observation(encode(envelope), SavedMedia())
