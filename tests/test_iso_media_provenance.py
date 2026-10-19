"""Exercise offline byte/context consistency without claiming authentication."""
import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys

import pytest
from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/iso-media-provenance-v2"
SPEC = importlib.util.spec_from_file_location("iso_media_provenance", ROOT / "scripts/iso_media_provenance.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
CASES = json.loads((FIXTURES / "cases.json").read_text())


def digest(data):
    return "sha256:" + hashlib.sha256(data).hexdigest()


def encode(document):
    return json.dumps(document, sort_keys=True, separators=(",", ":"), allow_nan=False).encode() + b"\n"


@pytest.fixture
def bundle():
    return {
        "browser_bytes": CASES["browserReceiptUtf8"].encode(),
        "native_bytes": CASES["nativeReceiptUtf8"].encode(),
        "browser": json.loads(CASES["browserReceiptUtf8"]),
        "native": json.loads(CASES["nativeReceiptUtf8"]),
        "context": copy.deepcopy(CASES["expectedContext"]),
        "transport": copy.deepcopy(CASES["observedTransport"]),
        "media": (FIXTURES / CASES["mediaFile"]).read_bytes(),
    }


def refresh_receipts(bundle, *, bind_browser=True):
    """Recompute test transport hashes, leaving independently expected inputs intact."""
    bundle["browser_bytes"] = encode(bundle["browser"])
    if bind_browser:
        bundle["native"]["browserReceiptSha256"] = digest(bundle["browser_bytes"])
    bundle["native_bytes"] = encode(bundle["native"])
    for role in ("context", "transport"):
        bundle[role]["browserProducer"]["receiptSha256"] = digest(bundle["browser_bytes"])
        bundle[role]["nativeProducer"]["receiptSha256"] = digest(bundle["native_bytes"])


def check(bundle):
    return MODULE.check_consistency(bundle["browser_bytes"], bundle["native_bytes"],
                                    bundle["media"], bundle["context"], bundle["transport"])


class CountingMedia(io.BytesIO):
    def __init__(self, data):
        super().__init__(data)
        self.read_calls = 0
        self.bytes_read = 0

    def read(self, size=-1):
        self.read_calls += 1
        chunk = super().read(size)
        self.bytes_read += len(chunk)
        return chunk


@pytest.fixture
def counting_media(bundle):
    stream = CountingMedia(bundle["media"])
    bundle["media"] = stream
    return stream


def test_portable_positive_is_bound_to_real_fixture_bytes(bundle):
    identity = {"sha256": digest(bundle["media"]), "sizeBytes": len(bundle["media"])}
    assert len(bundle["media"]) == 32
    for role in ("browser", "native", "context"):
        assert bundle[role]["media"] == identity
    assert bundle["native"]["browserReceiptSha256"] == digest(bundle["browser_bytes"])
    assert bundle["context"]["browserProducer"]["receiptSha256"] == digest(bundle["browser_bytes"])
    assert bundle["context"]["nativeProducer"]["receiptSha256"] == digest(bundle["native_bytes"])
    assert bundle["context"]["browserProducer"] == bundle["transport"]["browserProducer"]
    assert bundle["context"]["nativeProducer"] == bundle["transport"]["nativeProducer"]
    assert check(bundle) == {"consistency_valid": True, "authentication": "not_authenticated"}
    assert CASES["expectedResult"] == {"consistency_valid": True, "authentication": "not_authenticated"}


@pytest.mark.parametrize("role", ["browser", "native", "context", "transport"])
def test_positive_roles_pass_independent_schema_and_runtime(bundle, role):
    schema = json.loads((ROOT / "schemas/iso-media-provenance-v2.schema.json").read_text())
    Draft202012Validator(schema).validate(bundle[role])
    assert MODULE.validate_document(bundle[role]) == role


@pytest.mark.parametrize("vector", CASES["bindingCases"], ids=lambda case: case["name"])
def test_shared_negative_binding_vectors(bundle, vector):
    assert vector["expected"] == "reject"
    for change in vector["changes"]:
        path = change["path"]
        if not path:
            bundle[change["document"]] = copy.deepcopy(change["value"])
            continue
        target = bundle[change["document"]]
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = copy.deepcopy(change["value"])
    if vector["refreshReceiptHashes"]:
        refresh_receipts(bundle)
    with pytest.raises(MODULE.ContractError):
        check(bundle)


@pytest.mark.parametrize("mutation", ["changed-byte", "appended-byte", "empty"])
def test_changed_media_bytes_fail_even_when_receipts_are_unchanged(bundle, mutation):
    if mutation == "changed-byte":
        bundle["media"] = b"X" + bundle["media"][1:]
    elif mutation == "appended-byte":
        bundle["media"] += b"X"
    else:
        bundle["media"] = b""
    with pytest.raises(MODULE.ContractError, match="media"):
        check(bundle)


@pytest.mark.parametrize("field,value", [("sizeBytes", 33), ("sha256", "sha256:" + "9" * 64)])
def test_mutually_consistent_media_claims_still_need_matching_bytes(bundle, field, value):
    for role in ("browser", "native", "context"):
        bundle[role]["media"][field] = value
    refresh_receipts(bundle)
    with pytest.raises(MODULE.ContractError, match="media"):
        check(bundle)


@pytest.mark.parametrize("role", ["browser", "native"])
def test_receipt_hash_covers_exact_bytes_including_whitespace(bundle, role):
    bundle[role + "_bytes"] += b" "
    with pytest.raises(MODULE.ContractError, match="receiptSha256"):
        check(bundle)


def test_native_reference_must_identify_exact_browser_receipt(bundle):
    bundle["native"]["browserReceiptSha256"] = "sha256:" + "9" * 64
    refresh_receipts(bundle, bind_browser=False)
    with pytest.raises(MODULE.ContractError, match="native.browserReceiptSha256"):
        check(bundle)


@pytest.mark.parametrize("role", ["browser", "native"])
@pytest.mark.parametrize("field,value", [
    ("repository", "other/repository"), ("workflowPath", ".github/workflows/other.yml"),
    ("workflowRevision", "9" * 40), ("sourceRevision", "9" * 40),
    ("harnessRevision", "9" * 40), ("runId", 909), ("runAttempt", 9),
])
def test_recomputed_receipt_hash_cannot_override_expected_run(bundle, role, field, value):
    bundle[role]["run"][field] = value
    if role == "native" and field == "harnessRevision":
        bundle[role]["harness"]["sourceRevision"] = value
    refresh_receipts(bundle)
    with pytest.raises(MODULE.ContractError, match="run"):
        check(bundle)


@pytest.mark.parametrize("field", ["build_request_sha256", "recipe_sha256", "config_sha256"])
def test_recomputed_receipt_hash_cannot_override_expected_build_input(bundle, field):
    bundle["browser"][field] = "sha256:" + "9" * 64
    refresh_receipts(bundle)
    with pytest.raises(MODULE.ContractError, match=field):
        check(bundle)


def test_self_claimed_source_identity_cannot_override_expected_source(bundle):
    changed = "sha256:" + "9" * 64
    inputs = bundle["browser"]["input_descriptors"]
    inputs["source"]["digest"] = changed
    inputs["source"]["ref"] = "ghcr.io/example/fixture@" + changed
    inputs["overlay"]["baseDigest"] = changed
    for record in bundle["native"]["observed"].values():
        record["sourceDigest"] = record["bootedDigest"] = changed
    refresh_receipts(bundle)
    with pytest.raises(MODULE.ContractError, match="input_descriptors"):
        check(bundle)


@pytest.mark.parametrize("transport", [None, {}, [], True, "trusted"])
def test_independent_observed_transport_is_required(bundle, transport):
    bundle["transport"] = transport
    with pytest.raises(MODULE.ContractError):
        check(bundle)


@pytest.mark.parametrize("role", ["context", "transport"])
@pytest.mark.parametrize("producer,field,suffix", [
    ("browserProducer", "mediaPath", ".iso"),
    ("browserProducer", "receiptPath", ".json"),
    ("nativeProducer", "receiptPath", ".json"),
])
@pytest.mark.parametrize("stem", ["../escape", "dir/../escape", "dir/./escape", "dir//escape",
                                  "/escape", "dir\\escape", "dir/%2e%2e/escape"])
def test_archive_paths_cannot_traverse_or_ambiguously_name_members(bundle, role, producer, field, suffix, stem):
    bundle[role][producer]["artifact"][field] = stem + suffix
    with pytest.raises(MODULE.ContractError):
        MODULE.validate_document(bundle[role])


@pytest.mark.parametrize("data", [
    b'{"x":1,"x":2}', b'{"outer":{"x":1,"x":2}}',
    b'{"x":NaN}', b'{"x":Infinity}', b'{"x":-Infinity}',
    b'{"x":1e999}', b'{"outer":[{"x":-1e999}]}',
    b'{"x":', b'\xff', b'[]', b'null', b'42', b'true',
])
def test_strict_parser_rejects_ambiguous_or_invalid_json(data):
    with pytest.raises(MODULE.ContractError):
        MODULE.parse_document(data)


@pytest.mark.parametrize("data", ["{}", bytearray(b"{}"), None, {}, b" " * (16 * 1024 * 1024 + 1)])
def test_parser_requires_bounded_exact_bytes(data):
    with pytest.raises(MODULE.ContractError):
        MODULE.parse_document(data)


def test_parser_accepts_nested_finite_json_without_changing_claims():
    raw = b'{"nested":[{"value":1.25}],"name":"fixture"}'
    assert MODULE.parse_document(raw) == {"nested": [{"value": 1.25}], "name": "fixture"}


@pytest.mark.parametrize("value", [None, False, 1, "document", []])
def test_validator_rejects_nonobject_documents(value):
    with pytest.raises(MODULE.ContractError):
        MODULE.validate_document(value)


@pytest.mark.parametrize("role", ["browser", "context", "transport"])
@pytest.mark.parametrize("version", [None, True, 1, 3, 2.0, "2"])
def test_version_dispatch_rejects_legacy_unknown_and_noninteger_versions(bundle, role, version):
    bundle[role]["schemaVersion"] = version
    with pytest.raises(MODULE.ContractError):
        MODULE.validate_document(bundle[role])


@pytest.mark.parametrize("role,path", [
    ("browser", ("media", "sizeBytes")), ("browser", ("run", "runId")),
    ("browser", ("run", "runAttempt")), ("browser", ("resources", 0, "value")),
    ("context", ("browserProducer", "artifact", "id")),
])
@pytest.mark.parametrize("value", [True, False, None, "1", 0, -1, float("nan"), float("inf")])
def test_numeric_fields_reject_booleans_missing_and_nonfinite_values(bundle, role, path, value):
    target = bundle[role]
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(MODULE.ContractError):
        MODULE.validate_document(bundle[role])


@pytest.mark.parametrize("mode", ["plain", "encrypted"])
def test_both_native_install_modes_are_required(bundle, mode):
    del bundle["native"]["observed"][mode]
    with pytest.raises(MODULE.ContractError):
        MODULE.validate_document(bundle["native"])


@pytest.mark.parametrize("mode", ["plain", "encrypted"])
@pytest.mark.parametrize("field", ["offlineNetworkDisabled", "guiCompleted", "targetOnlyReboot", "desktopContract"])
@pytest.mark.parametrize("value", [False, None, 1, "true"])
def test_native_observations_require_actual_true_booleans(bundle, mode, field, value):
    bundle["native"]["observed"][mode][field] = value
    with pytest.raises(MODULE.ContractError):
        MODULE.validate_document(bundle["native"])


@pytest.mark.parametrize("mode", ["plain", "encrypted"])
def test_native_booted_digest_must_match_observed_source(bundle, mode):
    bundle["native"]["observed"][mode]["bootedDigest"] = "sha256:" + "9" * 64
    with pytest.raises(MODULE.ContractError, match="bootedDigest"):
        MODULE.validate_document(bundle["native"])


@pytest.mark.parametrize("mode", ["plain", "encrypted"])
def test_matching_native_source_and_booted_claims_still_need_expected_source(bundle, mode):
    record = bundle["native"]["observed"][mode]
    record["sourceDigest"] = record["bootedDigest"] = "sha256:" + "9" * 64
    refresh_receipts(bundle)
    with pytest.raises(MODULE.ContractError, match="sourceDigest"):
        check(bundle)


@pytest.mark.parametrize("index", [0, 1, 2])
def test_resource_observations_require_explicit_source(bundle, index):
    del bundle["browser"]["resources"][index]["source"]
    with pytest.raises(MODULE.ContractError):
        MODULE.validate_document(bundle["browser"])


@pytest.mark.parametrize("field,value", [("source", ""), ("source", None), ("source", "unknown"),
                                        ("method", "measured"), ("subject", "host"), ("unit", "seconds")])
def test_browser_memory_prerequisite_preserves_its_observation_source(bundle, field, value):
    bundle["browser"]["resources"][0][field] = value
    with pytest.raises(MODULE.ContractError):
        MODULE.validate_document(bundle["browser"])


def test_duplicate_resource_observations_are_ambiguous(bundle):
    bundle["browser"]["resources"].append(copy.deepcopy(bundle["browser"]["resources"][0]))
    with pytest.raises(MODULE.ContractError, match="duplicate"):
        MODULE.validate_document(bundle["browser"])


@pytest.mark.parametrize("role,legacy", [
    ("browser", {"schemaVersion": 1, "kind": "qualification-evidence", "half": "browser"}),
    ("native", {"schema": "QualificationEvidence/v1"}),
])
def test_recognized_legacy_records_are_diagnostic_only_and_never_admitted(bundle, role, legacy):
    raw = encode(legacy)
    assert MODULE.inspect_legacy(raw) == {
        "status": "diagnostic_only", "role": role,
        "consistency_valid": False, "authentication": "not_authenticated",
    }
    with pytest.raises(MODULE.ContractError):
        MODULE.validate_document(MODULE.parse_document(raw))
    bundle[role + "_bytes"] = raw
    with pytest.raises(MODULE.ContractError):
        check(bundle)


@pytest.mark.parametrize("legacy", [
    {}, {"schema": "QualificationEvidence/v3"},
    {"schemaVersion": True, "kind": "qualification-evidence", "half": "browser"},
    {"schemaVersion": 1, "kind": "qualification-evidence", "half": "native"},
    {"schemaVersion": 2, "kind": "qualification-evidence", "half": "browser"},
])
def test_legacy_reader_does_not_guess_unrecognized_versions(legacy):
    with pytest.raises(MODULE.ContractError):
        MODULE.inspect_legacy(encode(legacy))


def test_legacy_reader_still_rejects_nonfinite_json():
    with pytest.raises(MODULE.ContractError):
        MODULE.inspect_legacy(b'{"schema":"QualificationEvidence/v1","value":1e999}')


@pytest.mark.parametrize("producer", ["browserProducer", "nativeProducer"])
@pytest.mark.parametrize("section,field,value", [
    ("run", "runId", 999),
    ("run", "runAttempt", 99),
    ("artifact", "id", 999),
    ("artifact", "archiveSha256", "sha256:" + "9" * 64),
])
def test_transport_mismatch_rejected_without_reading_media(
        bundle, counting_media, producer, section, field, value):
    bundle["transport"][producer][section][field] = value
    assert MODULE.validate_document(bundle["transport"]) == "transport"
    with pytest.raises(MODULE.ContractError, match=producer + r"\.transport"):
        check(bundle)
    assert (counting_media.read_calls, counting_media.bytes_read) == (0, 0)


@pytest.mark.parametrize("role", ["browser", "native"])
def test_receipt_hash_mismatch_rejected_without_reading_media(bundle, counting_media, role):
    bundle[role + "_bytes"] += b"\n"
    with pytest.raises(MODULE.ContractError, match=role + r"Producer\.receiptSha256"):
        check(bundle)
    assert (counting_media.read_calls, counting_media.bytes_read) == (0, 0)


@pytest.mark.parametrize("role", ["browser", "native"])
def test_declared_run_mismatch_rejected_without_reading_media(bundle, counting_media, role):
    bundle[role]["run"]["runId"] = 999
    refresh_receipts(bundle)
    with pytest.raises(MODULE.ContractError, match=role + r"Producer\.run"):
        check(bundle)
    assert (counting_media.read_calls, counting_media.bytes_read) == (0, 0)


def test_browser_receipt_link_mismatch_rejected_without_reading_media(bundle, counting_media):
    bundle["native"]["browserReceiptSha256"] = "sha256:" + "9" * 64
    refresh_receipts(bundle, bind_browser=False)
    with pytest.raises(MODULE.ContractError, match=r"native\.browserReceiptSha256"):
        check(bundle)
    assert (counting_media.read_calls, counting_media.bytes_read) == (0, 0)


@pytest.mark.parametrize("path,diagnostic", [
    (("input_descriptors", "engine", "sha256"), "input_descriptors"),
    (("input_descriptors", "installer", "deployedCommit"), "input_descriptors"),
    (("input_descriptors", "overlay", "digest"), "input_descriptors"),
    (("build_request_sha256",), "build_request_sha256"),
    (("recipe_sha256",), "recipe_sha256"),
    (("config_sha256",), "config_sha256"),
    (("harness", "qemuSha256"), "harness"),
])
def test_expected_input_mismatch_rejected_without_reading_media(
        bundle, counting_media, path, diagnostic):
    target = bundle["context"]
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = "sha256:" + "9" * 64
    assert MODULE.validate_document(bundle["context"]) == "context"
    with pytest.raises(MODULE.ContractError, match=diagnostic):
        check(bundle)
    assert (counting_media.read_calls, counting_media.bytes_read) == (0, 0)


@pytest.mark.parametrize("role", ["browser", "native", "context"])
@pytest.mark.parametrize("field,value", [("sha256", "sha256:" + "9" * 64), ("sizeBytes", 33)])
def test_declared_media_mismatch_rejected_without_reading_media(
        bundle, counting_media, role, field, value):
    bundle[role]["media"][field] = value
    refresh_receipts(bundle)
    with pytest.raises(MODULE.ContractError, match="media"):
        check(bundle)
    assert (counting_media.read_calls, counting_media.bytes_read) == (0, 0)


@pytest.mark.parametrize("mode", ["plain", "encrypted"])
def test_installed_source_mismatch_rejected_without_reading_media(bundle, counting_media, mode):
    record = bundle["native"]["observed"][mode]
    record["sourceDigest"] = record["bootedDigest"] = "sha256:" + "9" * 64
    refresh_receipts(bundle)
    assert MODULE.validate_document(bundle["native"]) == "native"
    with pytest.raises(MODULE.ContractError, match=mode + r"\.sourceDigest"):
        check(bundle)
    assert (counting_media.read_calls, counting_media.bytes_read) == (0, 0)


def test_matching_metadata_still_reads_actual_media(bundle, counting_media):
    assert check(bundle) == {"consistency_valid": True, "authentication": "not_authenticated"}
    assert counting_media.read_calls > 0
    assert counting_media.bytes_read == bundle["context"]["media"]["sizeBytes"]


@pytest.mark.parametrize("mutation", ["corrupt", "truncated", "oversized"])
def test_matching_metadata_still_rejects_changed_stream_bytes(bundle, mutation):
    original = bundle["media"]
    changed = {"corrupt": b"X" + original[1:],
               "truncated": original[:-1], "oversized": original + b"X"}[mutation]
    stream = CountingMedia(changed)
    bundle["media"] = stream
    with pytest.raises(MODULE.ContractError, match="media"):
        check(bundle)
    assert stream.read_calls > 0
    assert stream.bytes_read == len(changed)


def test_streamed_media_uses_bounded_binary_reads(bundle):
    class SmallChunks:
        def __init__(self, data):
            self.data = io.BytesIO(data)
            self.requests = []

        def read(self, size):
            assert 0 < size <= 1024 * 1024
            self.requests.append(size)
            return self.data.read(min(size, 7))

    stream = SmallChunks(bundle["media"])
    bundle["media"] = stream
    assert check(bundle) == {"consistency_valid": True, "authentication": "not_authenticated"}
    assert len(stream.requests) > 2


def test_truncated_media_stream_is_rejected(bundle):
    bundle["media"] = io.BytesIO(bundle["media"][:-1])
    with pytest.raises(MODULE.ContractError, match="media"):
        check(bundle)


def test_oversized_media_stream_stops_after_one_excess_byte(bundle):
    class EndlessStream:
        def __init__(self):
            self.consumed = 0

        def read(self, size):
            assert 0 < size <= 1024 * 1024
            self.consumed += size
            return b"x" * size

    expected_size = len(bundle["media"])
    stream = EndlessStream()
    bundle["media"] = stream
    with pytest.raises(MODULE.ContractError, match="exceeds expected size"):
        check(bundle)
    assert stream.consumed == expected_size + 1


def test_seekable_media_stream_must_start_at_zero(bundle):
    stream = io.BytesIO(bundle["media"])
    stream.seek(1)
    bundle["media"] = stream
    with pytest.raises(MODULE.ContractError, match="position zero"):
        check(bundle)
    assert stream.tell() == 1


def test_bytes_and_stream_media_produce_identical_consistency_results(bundle):
    byte_result = check(bundle)
    bundle["media"] = io.BytesIO(bundle["media"])
    assert check(bundle) == byte_result == {
        "consistency_valid": True,
        "authentication": "not_authenticated",
    }


@pytest.mark.parametrize("media", [None, bytearray(b"bytes"), "text", io.StringIO("text")])
def test_media_input_requires_bytes_or_a_binary_stream(bundle, media):
    bundle["media"] = media
    with pytest.raises(MODULE.ContractError, match="media"):
        check(bundle)


def test_checker_runs_without_site_packages():
    script = """
import importlib.util, json, pathlib, sys
root = pathlib.Path(sys.argv[1])
spec = importlib.util.spec_from_file_location('contract', root / 'scripts/iso_media_provenance.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
fixtures = root / 'tests/fixtures/iso-media-provenance-v2'
case = json.loads((fixtures / 'cases.json').read_text())
with (fixtures / case['mediaFile']).open('rb') as media:
    result = module.check_consistency(case['browserReceiptUtf8'].encode(), case['nativeReceiptUtf8'].encode(), media, case['expectedContext'], case['observedTransport'])
print(json.dumps(result))
"""
    output = subprocess.check_output([sys.executable, "-S", "-c", script, str(ROOT)], text=True)
    assert json.loads(output) == {"consistency_valid": True, "authentication": "not_authenticated"}


@pytest.mark.parametrize("baseline", ["x86-64", "x86-64-v2", "x86-64-v3"])
def test_bare_amd64_preserves_independently_supplied_baseline(bundle, baseline):
    for role in ("browser", "context"):
        bundle[role]["input_descriptors"]["source"].update(
            platform="linux/amd64", cpuBaseline=baseline)
    refresh_receipts(bundle)
    assert check(bundle) == {"consistency_valid": True, "authentication": "not_authenticated"}


def test_bare_amd64_baseline_must_match_independent_context(bundle):
    for role in ("browser", "context"):
        bundle[role]["input_descriptors"]["source"]["platform"] = "linux/amd64"
    bundle["browser"]["input_descriptors"]["source"]["cpuBaseline"] = "x86-64-v3"
    refresh_receipts(bundle)
    with pytest.raises(MODULE.ContractError, match="input_descriptors"):
        check(bundle)


@pytest.mark.parametrize("platform,baseline", [
    ("linux/amd64/v2", "x86-64-v3"), ("linux/amd64/v2", "x86-64"),
    ("linux/amd64", "armv8-a"), ("linux/arm64", "x86-64-v2"),
    ("linux/amd64", "x86-64-v4"), ("linux/amd64", "unknown"),
])
@pytest.mark.parametrize("role", ["browser", "context"])
def test_source_baseline_must_be_supported_and_match_explicit_platform(bundle, platform, baseline, role):
    bundle[role]["input_descriptors"]["source"].update(platform=platform, cpuBaseline=baseline)
    with pytest.raises(MODULE.ContractError, match="cpuBaseline"):
        MODULE.validate_document(bundle[role])


def test_catalog_advertised_baseline_inventory_is_supported_without_inference(bundle):
    inventory = json.loads((FIXTURES / "catalog-baselines.json").read_text())
    for pair in inventory["advertisedPairs"]:
        candidate = copy.deepcopy(bundle)
        for role in ("browser", "context"):
            inputs = candidate[role]["input_descriptors"]
            inputs["source"].update(platform=pair["platform"], cpuBaseline=pair["cpuBaseline"])
            if pair["platform"] == "linux/arm64":
                inputs["installer"]["arch"] = "aarch64"
                inputs["installer"]["ref"] = inputs["installer"]["ref"].replace("/x86_64/", "/aarch64/")
        refresh_receipts(candidate)
        assert check(candidate) == {"consistency_valid": True, "authentication": "not_authenticated"}
