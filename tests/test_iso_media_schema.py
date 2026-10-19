"""The v2 schema checks structure, never authenticates producers or ISO bytes.

The portable schema-* fixtures use synthetic identity values. They are not
receipts from builds, and their receipt/archive hashes make no byte-binding
claim. Governance approval and deployed behavior require separate review.
"""
import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/iso-media-provenance-v2"
SCHEMA = json.loads((ROOT / "schemas/iso-media-provenance-v2.schema.json").read_text())


@pytest.fixture(scope="module")
def validator():
    Draft202012Validator.check_schema(SCHEMA)
    return Draft202012Validator(SCHEMA)


@pytest.fixture
def documents():
    return {role: json.loads((FIXTURES / f"schema-{role}.json").read_text())
            for role in ("browser", "native", "context", "transport")}


@pytest.mark.parametrize("role", ["browser", "native", "context", "transport"])
def test_accepts_structurally_valid_v2_document(validator, documents, role):
    validator.validate(documents[role])


def test_fixture_identity_roles_use_distinct_values(documents):
    browser = documents["browser"]
    inputs = browser["input_descriptors"]
    native = documents["native"]
    context = documents["context"]
    identities = [
        inputs["source"]["digest"], inputs["overlay"]["digest"],
        inputs["installer"]["deployedCommit"], inputs["engine"]["sha256"],
        inputs["engine"]["runtimeShimSha256"], browser["media"]["sha256"],
        browser["build_request_sha256"], browser["recipe_sha256"],
        browser["config_sha256"], native["harness"]["qemuSha256"],
        context["browserProducer"]["receiptSha256"],
        context["nativeProducer"]["receiptSha256"],
        context["browserProducer"]["artifact"]["archiveSha256"],
        context["nativeProducer"]["artifact"]["archiveSha256"],
    ]
    assert len(identities) == len(set(identities))


@pytest.mark.parametrize("role", ["browser", "context"])
@pytest.mark.parametrize("bundle", [False, True])
def test_deployed_frontend_commit_works_with_or_without_bundle(validator, documents, role, bundle):
    installer = documents[role]["input_descriptors"]["installer"]
    assert "bundleSha256" not in installer
    if bundle:
        installer["bundleSha256"] = "sha256:" + "9" * 64
    validator.validate(documents[role])


@pytest.mark.parametrize("role,fields", [
    ("browser", ("schemaVersion", "kind", "half", "media", "input_descriptors",
                 "build_request_sha256", "recipe_sha256", "config_sha256",
                 "browser", "resources", "run")),
    ("native", ("schema", "media", "browserReceiptSha256", "harness", "run", "observed")),
    ("context", ("schemaVersion", "kind", "browserProducer", "nativeProducer",
                 "media", "input_descriptors", "build_request_sha256",
                 "recipe_sha256", "config_sha256", "browser", "harness")),
    ("transport", ("schemaVersion", "kind", "browserProducer", "nativeProducer")),
])
def test_rejects_each_missing_top_level_field(validator, documents, role, fields):
    for field in fields:
        document = copy.deepcopy(documents[role])
        del document[field]
        assert not validator.is_valid(document), (role, field)


@pytest.mark.parametrize("role,path,fields", [
    ("browser", ("media",), ("sha256", "sizeBytes")),
    ("browser", ("input_descriptors",), ("source", "overlay", "installer", "engine")),
    ("browser", ("input_descriptors", "source"), ("kind", "ref", "digest", "platform", "cpuBaseline")),
    ("browser", ("input_descriptors", "overlay"), ("kind", "digest", "baseDigest")),
    ("browser", ("input_descriptors", "installer"), ("kind", "appId", "ref", "arch", "deployedCommit")),
    ("browser", ("input_descriptors", "engine"), ("kind", "sha256", "sourceRevision", "runtimeShimSha256")),
    ("browser", ("browser",), ("product", "version")),
    ("browser", ("resources", 0), ("subject", "quantity", "unit", "method", "source", "value")),
    ("browser", ("run",), ("repository", "workflowPath", "workflowRevision", "sourceRevision", "harnessRevision", "runId", "runAttempt")),
    ("native", ("harness",), ("kind", "sourceRevision", "qemuSha256")),
    ("native", ("observed",), ("plain", "encrypted")),
    ("native", ("observed", "plain"), ("sourceDigest", "bootedDigest", "offlineNetworkDisabled", "guiCompleted", "targetOnlyReboot", "desktopContract")),
    ("native", ("observed", "encrypted"), ("sourceDigest", "bootedDigest", "offlineNetworkDisabled", "guiCompleted", "targetOnlyReboot", "desktopContract")),
    ("context", ("browserProducer",), ("run", "artifact", "receiptSha256")),
    ("context", ("nativeProducer",), ("run", "artifact", "receiptSha256")),
    ("context", ("browserProducer", "artifact"), ("id", "archiveSha256", "expired", "mediaPath", "receiptPath")),
    ("context", ("nativeProducer", "artifact"), ("id", "archiveSha256", "expired", "receiptPath")),
    ("transport", ("browserProducer",), ("run", "artifact", "receiptSha256")),
    ("transport", ("nativeProducer",), ("run", "artifact", "receiptSha256")),
    ("transport", ("browserProducer", "run"), ("repository", "workflowPath", "workflowRevision", "sourceRevision", "harnessRevision", "runId", "runAttempt")),
    ("transport", ("nativeProducer", "run"), ("repository", "workflowPath", "workflowRevision", "sourceRevision", "harnessRevision", "runId", "runAttempt")),
    ("transport", ("browserProducer", "artifact"), ("id", "archiveSha256", "expired", "mediaPath", "receiptPath")),
    ("transport", ("nativeProducer", "artifact"), ("id", "archiveSha256", "expired", "receiptPath")),
])
def test_rejects_each_missing_nested_field(validator, documents, role, path, fields):
    for field in fields:
        document = copy.deepcopy(documents[role])
        target = document
        for key in path:
            target = target[key]
        del target[field]
        assert not validator.is_valid(document), (role, path, field)


@pytest.mark.parametrize("role,path", [
    ("browser", ()), ("native", ()), ("context", ()), ("transport", ()),
    ("browser", ("media",)), ("browser", ("input_descriptors",)),
    ("browser", ("input_descriptors", "source")),
    ("browser", ("input_descriptors", "overlay")),
    ("browser", ("input_descriptors", "installer")),
    ("browser", ("input_descriptors", "engine")),
    ("browser", ("browser",)), ("browser", ("resources", 0)), ("browser", ("run",)),
    ("native", ("harness",)), ("native", ("observed",)),
    ("native", ("observed", "plain")), ("native", ("observed", "encrypted")),
    ("context", ("browserProducer",)), ("context", ("nativeProducer",)),
    ("context", ("browserProducer", "artifact")), ("context", ("nativeProducer", "artifact")),
    ("transport", ("browserProducer",)), ("transport", ("nativeProducer",)),
    ("transport", ("browserProducer", "run")), ("transport", ("nativeProducer", "run")),
    ("transport", ("browserProducer", "artifact")), ("transport", ("nativeProducer", "artifact")),
])
def test_rejects_unknown_fields_in_closed_objects(validator, documents, role, path):
    target = documents[role]
    for key in path:
        target = target[key]
    target["unexpected"] = "cannot extend a closed contract silently"
    assert not validator.is_valid(documents[role])


@pytest.mark.parametrize("role,field,value", [
    (role, "schemaVersion", value)
    for role in ("browser", "context", "transport") for value in (1, 3, "2", True, None)
] + [
    ("browser", "kind", "iso-media-expected-context"),
    ("browser", "half", "native"),
    ("context", "kind", "qualification-evidence"),
    ("transport", "kind", "iso-media-expected-context"),
    ("native", "schema", "QualificationEvidence/v1"),
    ("native", "schema", "QualificationEvidence/v3"),
    ("native", "schema", None),
])
def test_rejects_wrong_role_and_legacy_or_unknown_version(validator, documents, role, field, value):
    documents[role][field] = value
    assert not validator.is_valid(documents[role])


@pytest.mark.parametrize("legacy", [
    {"schemaVersion": 1, "kind": "qualification-evidence", "half": "browser"},
    {"schema": "QualificationEvidence/v1"},
    {"variant": "yellowfin", "flavor": "gnome", "screens": [],
     "luks": True, "installed_boot": True, "desktop_contract": True},
])
def test_legacy_diagnostics_are_not_structurally_valid_v2_evidence(validator, legacy):
    assert not validator.is_valid(legacy)


@pytest.mark.parametrize("field,kind", [
    ("source", "oci-image-index"), ("source", "oci-image-config"),
    ("overlay", "iso-media"), ("installer", "backend-executable"),
    ("installer", "flatpak-bundle"), ("engine", "qemu"),
    ("engine", "native-install-harness"),
])
def test_rejects_wrong_identity_role_kind(validator, documents, field, kind):
    documents["browser"]["input_descriptors"][field]["kind"] = kind
    assert not validator.is_valid(documents["browser"])


@pytest.mark.parametrize("left,right", [("source", "overlay"), ("installer", "engine")])
def test_rejects_swapped_input_descriptors(validator, documents, left, right):
    inputs = documents["browser"]["input_descriptors"]
    inputs[left], inputs[right] = inputs[right], inputs[left]
    assert not validator.is_valid(documents["browser"])


def test_rejects_harness_as_builder_and_builder_as_harness(validator, documents):
    engine = copy.deepcopy(documents["browser"]["input_descriptors"]["engine"])
    documents["browser"]["input_descriptors"]["engine"] = documents["native"]["harness"]
    documents["native"]["harness"] = engine
    assert not validator.is_valid(documents["browser"])
    assert not validator.is_valid(documents["native"])


def test_bundle_hash_does_not_replace_required_deployed_frontend_commit(validator, documents):
    installer = documents["browser"]["input_descriptors"]["installer"]
    installer["bundleSha256"] = installer.pop("deployedCommit")
    assert not validator.is_valid(documents["browser"])


@pytest.mark.parametrize("mode", ["plain", "encrypted"])
@pytest.mark.parametrize("field", ["offlineNetworkDisabled", "guiCompleted", "targetOnlyReboot", "desktopContract"])
@pytest.mark.parametrize("value", [False, None, 1, "true"])
def test_required_native_observations_need_true_booleans(validator, documents, mode, field, value):
    documents["native"]["observed"][mode][field] = value
    assert not validator.is_valid(documents["native"])


@pytest.mark.parametrize("role,path", [
    ("browser", ("media", "sizeBytes")), ("browser", ("run", "runId")),
    ("browser", ("run", "runAttempt")),
    ("context", ("browserProducer", "artifact", "id")),
    ("context", ("nativeProducer", "artifact", "id")),
])
@pytest.mark.parametrize("value", [0, -1, True, "1", 1.5])
def test_ids_attempts_and_media_sizes_are_positive_integers(validator, documents, role, path, value):
    target = documents[role]
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    assert not validator.is_valid(documents[role])


@pytest.mark.parametrize("quantity,unit,method", [
    ("memoryCapacity", "seconds", "reported"),
    ("availableStorage", "seconds", "estimated"),
    ("elapsedDuration", "bytes", "measured"),
    ("elapsedDuration", "seconds", "reported"),
    ("elapsedDuration", "seconds", "estimated"),
])
def test_resource_quantity_limits_units_and_duration_method(validator, documents, quantity, unit, method):
    resource = documents["browser"]["resources"][0]
    resource.update(quantity=quantity, unit=unit, method=method)
    assert not validator.is_valid(documents["browser"])


@pytest.mark.parametrize("field,value", [
    ("subject", "unknown"), ("quantity", "disk"), ("unit", "GiB"),
    ("method", "inferred"), ("value", True), ("value", "16"),
    ("value", 0), ("value", -1), ("value", None),
])
def test_resource_records_require_supported_metadata_and_positive_numbers(validator, documents, field, value):
    documents["browser"]["resources"][0][field] = value
    assert not validator.is_valid(documents["browser"])


@pytest.mark.parametrize("field,value", [("product", "native-qemu"), ("product", "unknown"),
                                        ("version", "unknown"), ("version", ""), ("version", None)])
def test_browser_profile_rejects_missing_or_placeholder_identity(validator, documents, field, value):
    documents["browser"]["browser"][field] = value
    assert not validator.is_valid(documents["browser"])


@pytest.mark.parametrize("role", ["browser", "native"])
def test_receipt_cannot_embed_expected_context_to_authorize_itself(validator, documents, role):
    documents[role]["expectedContext"] = documents["context"]
    assert not validator.is_valid(documents[role])


@pytest.mark.parametrize("producer", ["browserProducer", "nativeProducer"])
def test_context_rejects_expired_artifact(validator, documents, producer):
    documents["context"][producer]["artifact"]["expired"] = True
    assert not validator.is_valid(documents["context"])
