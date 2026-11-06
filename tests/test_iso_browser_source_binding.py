"""Existing v2 source context binds consumed facts, never candidate policy."""
import copy
import importlib.util
import io
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "_test_browser_source_binding", ROOT / "scripts/iso_media_receipt_handoff.py")
HANDOFF = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = HANDOFF
try:
    SPEC.loader.exec_module(HANDOFF)
finally:
    del sys.modules[SPEC.name]
FIXTURES = ROOT / "tests/fixtures/iso-media-provenance-v2"
CASES = json.loads((FIXTURES / "cases.json").read_text())
BROWSER = json.loads(CASES["browserReceiptUtf8"])
MEDIA = (FIXTURES / CASES["mediaFile"]).read_bytes()
ENDPOINT = "https://relay.example.test/registry"
ORIGINS = {ENDPOINT: "ghcr.io"}


def encode(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def envelope():
    descriptors = BROWSER["input_descriptors"]
    values = {
        "selection_id": "operation-1", "completed_selection_id": "operation-1",
        "build_status": "completed", "bytes_written": len(MEDIA),
        "overlay": descriptors["overlay"], "deployed_frontend": descriptors["installer"],
        "loaded_engine": descriptors["engine"], "browser": BROWSER["browser"],
        "resources": BROWSER["resources"], "producer_run": BROWSER["run"],
    }
    values.update({name: BROWSER[name] for name in
                   ("build_request_sha256", "recipe_sha256", "config_sha256")})
    source = {
        "registryEndpoint": ENDPOINT, "repository": "example/fixture",
        "requestedReference": "mutable-tag-is-not-an-origin",
        "manifestDigest": descriptors["source"]["digest"],
        "indexDigest": "sha256:" + "b" * 64,
        "platformDescriptor": {"architecture": "amd64", "variant": "v2"},
        "config": {"bytesVerified": True,
                   "content": {"os": "linux", "architecture": "amd64", "variant": "v2"}},
    }
    return {"schemaVersion": 1, "kind": "browser-observed-input", "qualification": "not-assessed",
            "observed": copy.deepcopy(values), "missingFields": ["source_manifest"],
            "media": copy.deepcopy(BROWSER["media"]), "measurements": {"source": source}}


class MediaSink:
    def __init__(self):
        self.closed = False

    def finish(self):
        self.closed = True

    def snapshot_token(self):
        assert self.closed
        return (1, len(MEDIA))

    def open(self):
        assert self.closed
        return io.BytesIO(MEDIA)


def test_independent_context_binds_exact_consumed_source_then_real_handoff_hashes_media():
    observed = envelope()
    source_context = copy.deepcopy(BROWSER["input_descriptors"]["source"])
    before = copy.deepcopy(source_context)
    raw = HANDOFF.bind_browser_source_observation(encode(observed), source_context, ORIGINS)
    bound = json.loads(raw)
    assert source_context == before
    assert observed["missingFields"] == ["source_manifest"]
    assert bound["observed"]["source_manifest"] == source_context
    assert bound["missingFields"] == []
    assert bound["measurements"]["sourceBinding"]["cpuBaselineClaim"] == {
        "value": "x86-64-v2", "source": "independent-context", "method": "supplied-claim"}
    sink = MediaSink()
    receipt = HANDOFF.finalize_browser_observation(raw, sink)
    assert sink.closed
    assert receipt.receipt_bytes == CASES["browserReceiptUtf8"].encode()
    assert receipt.qualification == "not-assessed"


def test_candidate_request_catalog_and_origin_map_cannot_authorize_their_source():
    observed = envelope()
    observed["measurements"].update(
        transportOrigins=ORIGINS, requestedSource=BROWSER["input_descriptors"]["source"],
        catalogSource=BROWSER["input_descriptors"]["source"],
        sourceBinding={"origin": "ghcr.io", "reviewed": True})
    with pytest.raises(HANDOFF.ReceiptHandoffError, match="missing_origin_mapping"):
        HANDOFF.bind_browser_source_observation(
            encode(observed), BROWSER["input_descriptors"]["source"], {})


@pytest.mark.parametrize("mutation,field", [
    (lambda s: s.update(manifestDigest="sha256:" + "f" * 64), "source.manifestDigest"),
    (lambda s: s.update(repository="another/repository"), "source.ref"),
    (lambda s: s["config"].update(bytesVerified=False), "source.config.bytesVerified"),
    (lambda s: s["config"].pop("content"), "source.config.content"),
    (lambda s: s["config"]["content"].update(os="another-os"), "source.config.content.os"),
    (lambda s: s["config"]["content"].update(architecture="arm64"), "source.config.content.architecture"),
    (lambda s: s["platformDescriptor"].update(architecture="arm64"), "source.platformDescriptor.architecture"),
    (lambda s: s["platformDescriptor"].update(variant="v3"), "source.variant"),
    (lambda s: s.pop("indexDigest"), "source.indexDigest"),
    (lambda s: s.pop("registryEndpoint"), "source.registryEndpoint"),
])
def test_mismatched_or_unmeasured_source_facts_refuse(mutation, field):
    observed = envelope()
    mutation(observed["measurements"]["source"])
    with pytest.raises(HANDOFF.ReceiptHandoffError, match=field):
        HANDOFF.bind_browser_source_observation(
            encode(observed), BROWSER["input_descriptors"]["source"], ORIGINS)


def test_unsupported_proxy_mapping_is_not_inferred_from_repository_or_request():
    with pytest.raises(HANDOFF.ReceiptHandoffError, match="source.ref"):
        HANDOFF.bind_browser_source_observation(
            encode(envelope()), BROWSER["input_descriptors"]["source"], {ENDPOINT: "registry.example.test"})


def test_explicit_platform_variant_needs_an_actual_observation():
    observed = envelope()
    observed["measurements"]["source"]["config"]["content"].pop("variant")
    observed["measurements"]["source"]["platformDescriptor"].pop("variant")
    with pytest.raises(HANDOFF.ReceiptHandoffError, match="missing_observation: source.variant"):
        HANDOFF.bind_browser_source_observation(
            encode(observed), BROWSER["input_descriptors"]["source"], ORIGINS)


def test_bare_architecture_keeps_baseline_as_supplied_claim_not_hardware_measurement():
    observed = envelope()
    observed["measurements"]["source"]["config"]["content"].pop("variant")
    observed["measurements"]["source"]["platformDescriptor"].pop("variant")
    context = copy.deepcopy(BROWSER["input_descriptors"]["source"])
    context.update(platform="linux/amd64", cpuBaseline="x86-64-v3")
    bound = json.loads(HANDOFF.bind_browser_source_observation(encode(observed), context, ORIGINS))
    assert bound["observed"]["source_manifest"] == context
    assert bound["measurements"]["sourceBinding"]["cpuBaselineClaim"]["method"] == "supplied-claim"


@pytest.mark.parametrize("endpoint", [
    "https://user:private@relay.example.test", "https://relay.example.test/?token=private",
    "https://relay.example.test/#private", "https://relay.example.test/?",
])
def test_sensitive_transport_coordinates_never_bind_or_leak(endpoint):
    observed = envelope()
    observed["measurements"]["source"]["registryEndpoint"] = endpoint
    with pytest.raises(HANDOFF.ReceiptHandoffError) as error:
        HANDOFF.bind_browser_source_observation(
            encode(observed), BROWSER["input_descriptors"]["source"], {endpoint: "ghcr.io"})
    assert "private" not in str(error.value)


def test_binding_preserves_other_missing_contract_inputs_and_unchanged_media_cap():
    observed = envelope()
    observed["observed"].pop("recipe_sha256")
    observed["missingFields"].append("recipe_sha256")
    bound = HANDOFF.bind_browser_source_observation(
        encode(observed), BROWSER["input_descriptors"]["source"], ORIGINS)
    sink = MediaSink()
    with pytest.raises(HANDOFF.ReceiptHandoffError, match="envelope.missingFields"):
        HANDOFF.finalize_browser_observation(bound, sink)
    assert not sink.closed
    observed = envelope()
    observed["media"]["sizeBytes"] = HANDOFF.MAX_ISO_BYTES + 1
    observed["observed"]["bytes_written"] = HANDOFF.MAX_ISO_BYTES + 1
    bound = HANDOFF.bind_browser_source_observation(
        encode(observed), BROWSER["input_descriptors"]["source"], ORIGINS)
    with pytest.raises(HANDOFF.ReceiptHandoffError, match="envelope.media.sizeBytes"):
        HANDOFF.finalize_browser_observation(bound, sink)
    assert not sink.closed
