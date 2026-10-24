"""Tiny deterministic browser/native v2 receipt handoff conformance tests.

Falsification: fail or change the closed browser save, replay another browser
run, alter exact media, or report partial/backend/fixture native progress. The
adapter must reject without turning the observation into qualification.
"""
import copy
from dataclasses import replace
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import textwrap

import pytest
from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/iso-media-provenance-v2"


def load(name):
    module_name = "_test_iso_media_handoff_" + name
    spec = importlib.util.spec_from_file_location(
        module_name, ROOT / "scripts" / (name + ".py"))
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load test module {module_name}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        del sys.modules[spec.name]
    return module


CONTRACT = load("iso_media_provenance")
HANDOFF = load("iso_media_receipt_handoff")
CASES = json.loads((FIXTURES / "cases.json").read_text())
MEDIA = (FIXTURES / CASES["mediaFile"]).read_bytes()
BROWSER = json.loads(CASES["browserReceiptUtf8"])
NATIVE = json.loads(CASES["nativeReceiptUtf8"])
SCHEMA = json.loads((ROOT / "schemas/iso-media-provenance-v2.schema.json").read_text())


def test_handoff_module_loads_by_path_without_global_import_side_effects():
    script = textwrap.dedent(
        """
        import importlib.util
        import pathlib
        import sys
        root = pathlib.Path(sys.argv[1])
        path_before = list(sys.path)
        modules_before = set(sys.modules)
        spec = importlib.util.spec_from_file_location("standalone_handoff", root / "scripts/iso_media_receipt_handoff.py")
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        assert sys.path == path_before, "sys.path changed"
        added = {name for name in set(sys.modules) - modules_before if "iso_media" in name or "contract" in name}
        assert added == set(), added
        print(module.ReceiptCandidate.__name__)
        """
    )
    result = subprocess.check_output(
        [sys.executable, "-c", script, str(ROOT)], text=True)
    assert result.strip() == "ReceiptCandidate"


class MediaSource:
    def __init__(self, data, *, browser=False):
        self.data = data
        self.browser = browser
        self.closed_sink = not browser
        self.version = 1
        self.events = []
        self.finish_error = None
        self.finish_result = None
        self.mutate_during_read = False
        self.reader_close_error = None
        self.oversized_read = False

    def finish(self):
        self.events.append("finish")
        if self.finish_error:
            raise self.finish_error
        self.closed_sink = True
        return self.finish_result

    def snapshot_token(self):
        assert self.closed_sink
        self.events.append("snapshot")
        return (self.version, len(self.data))

    def open(self):
        assert self.closed_sink
        self.events.append("open")
        owner = self

        class Stream(io.BytesIO):
            def read(self, size=-1):
                owner.events.append("read")
                chunk = super().read(size)
                if owner.oversized_read:
                    owner.oversized_read = False
                    chunk += b"XX"
                if chunk and owner.mutate_during_read:
                    owner.version += 1
                    owner.mutate_during_read = False
                return chunk

            def close(self):
                owner.events.append("close-reader")
                super().close()
                if owner.reader_close_error:
                    raise owner.reader_close_error

        return Stream(self.data)


def browser_observation():
    inputs = BROWSER["input_descriptors"]
    return HANDOFF.BrowserObservedInput(
        selection_id="operation-101-attempt-2",
        completed_selection_id="operation-101-attempt-2",
        build_status="completed",
        bytes_written=len(MEDIA),
        source_manifest=copy.deepcopy(inputs["source"]),
        overlay=copy.deepcopy(inputs["overlay"]),
        deployed_frontend=copy.deepcopy(inputs["installer"]),
        loaded_engine=copy.deepcopy(inputs["engine"]),
        build_request_sha256=BROWSER["build_request_sha256"],
        recipe_sha256=BROWSER["recipe_sha256"],
        config_sha256=BROWSER["config_sha256"],
        browser=copy.deepcopy(BROWSER["browser"]),
        resources=tuple(copy.deepcopy(BROWSER["resources"])),
        producer_run=copy.deepcopy(BROWSER["run"]),
    )


def native_mode(receipt_mode):
    return {
        "sourceDigest": receipt_mode["sourceDigest"],
        "installedDigest": receipt_mode["bootedDigest"],
        "network": "offline",
        "installer": "gui",
        "installStatus": "completed",
        "bootMedia": "target-only",
        "bootStatus": "completed",
        "desktopContract": "passed",
        "fixture": False,
    }


def native_observation():
    return HANDOFF.NativeObservedInput(
        browser_receipt_sha256=NATIVE["browserReceiptSha256"],
        browser_run=copy.deepcopy(BROWSER["run"]),
        media=copy.deepcopy(NATIVE["media"]),
        harness=copy.deepcopy(NATIVE["harness"]),
        producer_run=copy.deepcopy(NATIVE["run"]),
        plain=native_mode(NATIVE["observed"]["plain"]),
        encrypted=native_mode(NATIVE["observed"]["encrypted"]),
    )


def test_tiny_roundtrip_reproduces_existing_v2_fixtures_and_validator_result():
    browser_media = MediaSource(MEDIA, browser=True)
    browser = HANDOFF.finalize_browser_receipt(browser_observation(), browser_media)
    assert browser.receipt_bytes == CASES["browserReceiptUtf8"].encode()
    assert browser.receipt_sha256 == NATIVE["browserReceiptSha256"]
    assert browser.qualification == "not-assessed"
    assert browser_media.events[:3] == ["finish", "snapshot", "open"]
    assert browser_media.events[-2:] == ["close-reader", "snapshot"]

    native_media = MediaSource(MEDIA)
    native = HANDOFF.finalize_native_receipt(
        native_observation(), browser.receipt_bytes, native_media)
    assert native.receipt_bytes == CASES["nativeReceiptUtf8"].encode()
    assert native.qualification == "not-assessed"
    assert browser.media_sha256 == native.media_sha256
    assert browser.media_size_bytes == native.media_size_bytes == len(MEDIA)

    browser_document = CONTRACT.parse_document(browser.receipt_bytes)
    native_document = CONTRACT.parse_document(native.receipt_bytes)
    Draft202012Validator(SCHEMA).validate(browser_document)
    Draft202012Validator(SCHEMA).validate(native_document)
    assert CONTRACT.validate_document(browser_document) == "browser"
    assert CONTRACT.validate_document(native_document) == "native"
    assert CONTRACT.check_consistency(
        browser.receipt_bytes, native.receipt_bytes, MEDIA,
        CASES["expectedContext"], CASES["observedTransport"],
    ) == {"consistency_valid": True, "authentication": "not_authenticated"}


def test_browser_receipt_is_deterministic_and_optional_bundle_keeps_its_meaning():
    observed = browser_observation()
    frontend = copy.deepcopy(observed.deployed_frontend)
    frontend["bundleSha256"] = "sha256:" + "9" * 64
    observed = replace(observed, deployed_frontend=frontend)
    first = HANDOFF.finalize_browser_receipt(observed, MediaSource(MEDIA, browser=True))
    second = HANDOFF.finalize_browser_receipt(observed, MediaSource(MEDIA, browser=True))
    assert first.receipt_bytes == second.receipt_bytes
    document = CONTRACT.parse_document(first.receipt_bytes)
    assert document["input_descriptors"]["installer"]["deployedCommit"] == BROWSER["input_descriptors"]["installer"]["deployedCommit"]
    assert document["input_descriptors"]["installer"]["bundleSha256"] == "sha256:" + "9" * 64
    Draft202012Validator(SCHEMA).validate(document)


@pytest.mark.parametrize("change", ["stale-selection", "incomplete-build", "zero-bytes"])
def test_browser_incomplete_or_stale_operation_rejects_before_finishing_sink(change):
    observed = browser_observation()
    if change == "stale-selection":
        observed = replace(observed, completed_selection_id="another-selection")
    elif change == "incomplete-build":
        observed = replace(observed, build_status="running")
    else:
        observed = replace(observed, bytes_written=0)
    media = MediaSource(MEDIA, browser=True)
    with pytest.raises(HANDOFF.ReceiptHandoffError):
        HANDOFF.finalize_browser_receipt(observed, media)
    assert media.events == []


@pytest.mark.parametrize("failure", ["write", "close-result"])
def test_failed_browser_save_or_close_emits_no_receipt(failure):
    media = MediaSource(MEDIA, browser=True)
    if failure == "write":
        media.finish_error = OSError("synthetic save failure")
    else:
        media.finish_result = False
    with pytest.raises(HANDOFF.ReceiptHandoffError, match="media_finish_failed"):
        HANDOFF.finalize_browser_receipt(browser_observation(), media)
    assert "open" not in media.events


def test_browser_saved_object_change_during_post_close_hash_rejects():
    media = MediaSource(MEDIA, browser=True)
    media.mutate_during_read = True
    with pytest.raises(HANDOFF.ReceiptHandoffError, match="identity_mismatch: media.snapshot"):
        HANDOFF.finalize_browser_receipt(browser_observation(), media)
    assert media.events[-2:] == ["close-reader", "snapshot"]


def test_primary_media_rejection_survives_reader_close_failure():
    media = MediaSource(MEDIA + b"X", browser=True)
    media.reader_close_error = OSError("synthetic reader close failure")
    with pytest.raises(HANDOFF.ReceiptHandoffError) as caught:
        HANDOFF.finalize_browser_receipt(browser_observation(), media)
    assert (caught.value.code, caught.value.field) == (
        "identity_mismatch", "media.sizeBytes")


def test_reader_close_failure_is_classified_when_no_earlier_error_exists():
    media = MediaSource(MEDIA, browser=True)
    media.reader_close_error = OSError("synthetic reader close failure")
    with pytest.raises(HANDOFF.ReceiptHandoffError) as caught:
        HANDOFF.finalize_browser_receipt(browser_observation(), media)
    assert (caught.value.code, caught.value.field) == (
        "media_io", "media.stream.close")


def test_malformed_stream_close_failure_does_not_escape_raw():
    media = MediaSource(MEDIA, browser=True)

    class MalformedStream:
        def close(self):
            raise OSError("synthetic malformed stream close failure")

    media.open = MalformedStream
    with pytest.raises(HANDOFF.ReceiptHandoffError) as caught:
        HANDOFF.finalize_browser_receipt(browser_observation(), media)
    assert (caught.value.code, caught.value.field) == (
        "invalid_media_interface", "media.stream")


def test_stream_cannot_return_more_than_the_requested_read_bound():
    media = MediaSource(MEDIA)
    media.oversized_read = True
    with pytest.raises(HANDOFF.ReceiptHandoffError) as caught:
        HANDOFF.finalize_native_receipt(
            native_observation(), CASES["browserReceiptUtf8"].encode(), media
        )
    assert (caught.value.code, caught.value.field) == (
        "invalid_media_interface",
        "media.stream.read",
    )


@pytest.mark.parametrize("field", [
    "source_manifest", "overlay", "deployed_frontend", "loaded_engine",
    "browser", "resources", "producer_run",
])
def test_missing_observed_browser_identity_fails_closed(field):
    observed = browser_observation()
    value = () if field == "resources" else {}
    observed = replace(observed, **{field: value})
    media = MediaSource(MEDIA, browser=True)
    with pytest.raises(HANDOFF.ReceiptHandoffError, match="invalid_observation"):
        HANDOFF.finalize_browser_receipt(observed, media)
    assert media.events == []


@pytest.mark.parametrize("field", [
    "build_request_sha256", "recipe_sha256", "config_sha256",
])
def test_missing_observed_browser_digest_is_not_filled_from_request(field):
    observed = replace(browser_observation(), **{field: ""})
    media = MediaSource(MEDIA, browser=True)
    with pytest.raises(HANDOFF.ReceiptHandoffError, match="invalid_observation"):
        HANDOFF.finalize_browser_receipt(observed, media)
    assert media.events == []


def test_frontend_engine_and_harness_roles_cannot_substitute_for_each_other():
    observed = replace(browser_observation(),
                       deployed_frontend=copy.deepcopy(BROWSER["input_descriptors"]["engine"]),
                       loaded_engine=copy.deepcopy(NATIVE["harness"]))
    with pytest.raises(HANDOFF.ReceiptHandoffError, match="invalid_observation"):
        HANDOFF.finalize_browser_receipt(observed, MediaSource(MEDIA, browser=True))


@pytest.mark.parametrize("mutation", ["bytes", "size"])
def test_native_remeasures_exact_supplied_media(mutation):
    data = (b"X" + MEDIA[1:]) if mutation == "bytes" else (MEDIA + b"X")
    with pytest.raises(HANDOFF.ReceiptHandoffError, match="identity_mismatch"):
        HANDOFF.finalize_native_receipt(
            native_observation(), CASES["browserReceiptUtf8"].encode(), MediaSource(data))


def test_native_rejects_mutation_while_reading_supplied_media():
    media = MediaSource(MEDIA)
    media.mutate_during_read = True
    with pytest.raises(HANDOFF.ReceiptHandoffError, match="media.snapshot"):
        HANDOFF.finalize_native_receipt(
            native_observation(), CASES["browserReceiptUtf8"].encode(), media)


def test_native_rejects_mismatched_raw_browser_receipt_hash():
    observed = replace(native_observation(), browser_receipt_sha256="sha256:" + "9" * 64)
    with pytest.raises(HANDOFF.ReceiptHandoffError, match="browserReceipt.sha256"):
        HANDOFF.finalize_native_receipt(
            observed, CASES["browserReceiptUtf8"].encode(), MediaSource(MEDIA))


def test_native_rejects_replayed_browser_run_even_with_same_media():
    observed = native_observation()
    replayed_run = copy.deepcopy(observed.browser_run)
    replayed_run["runId"] += 1
    observed = replace(observed, browser_run=replayed_run)
    with pytest.raises(HANDOFF.ReceiptHandoffError, match="browserReceipt.run"):
        HANDOFF.finalize_native_receipt(
            observed, CASES["browserReceiptUtf8"].encode(), MediaSource(MEDIA))


def test_native_rejects_a_different_installed_source_before_media_read():
    observed = native_observation()
    changed = "sha256:" + "9" * 64
    modes = {}
    for mode in ("plain", "encrypted"):
        modes[mode] = copy.deepcopy(getattr(observed, mode))
        modes[mode]["sourceDigest"] = changed
        modes[mode]["installedDigest"] = changed
    observed = replace(observed, **modes)
    media = MediaSource(MEDIA)
    with pytest.raises(HANDOFF.ReceiptHandoffError) as caught:
        HANDOFF.finalize_native_receipt(
            observed, CASES["browserReceiptUtf8"].encode(), media)
    assert (caught.value.code, caught.value.field) == (
        "identity_mismatch", "plain.sourceDigest")
    assert media.events == []


def test_native_rejects_role_swapped_browser_input():
    with pytest.raises(HANDOFF.ReceiptHandoffError, match="browserReceipt.role"):
        HANDOFF.finalize_native_receipt(
            native_observation(), CASES["nativeReceiptUtf8"].encode(), MediaSource(MEDIA))


def test_native_rejects_duplicate_key_browser_input():
    encoded = json.dumps(BROWSER, sort_keys=True, separators=(",", ":"))
    raw = ('{"schemaVersion":1,' + encoded[1:]).encode()
    with pytest.raises(HANDOFF.ReceiptHandoffError, match="invalid_browser_receipt"):
        HANDOFF.finalize_native_receipt(native_observation(), raw, MediaSource(MEDIA))


@pytest.mark.parametrize("field,value", [
    ("network", "online"),
    ("installer", "backend"),
    ("installStatus", "partial"),
    ("installStatus", "skipped"),
    ("bootMedia", "installation-media"),
    ("bootStatus", "skipped"),
    ("desktopContract", "not-run"),
    ("fixture", True),
])
@pytest.mark.parametrize("mode", ["plain", "encrypted"])
def test_partial_backend_skipped_or_fixture_native_observation_rejects(mode, field, value):
    observed = native_observation()
    changed = copy.deepcopy(getattr(observed, mode))
    changed[field] = value
    observed = replace(observed, **{mode: changed})
    with pytest.raises(HANDOFF.ReceiptHandoffError):
        HANDOFF.finalize_native_receipt(
            observed, CASES["browserReceiptUtf8"].encode(), MediaSource(MEDIA))


def test_native_missing_observation_is_not_promoted_to_success():
    observed = native_observation()
    changed = copy.deepcopy(observed.plain)
    del changed["desktopContract"]
    observed = replace(observed, plain=changed)
    with pytest.raises(HANDOFF.ReceiptHandoffError, match="invalid_observation"):
        HANDOFF.finalize_native_receipt(
            observed, CASES["browserReceiptUtf8"].encode(), MediaSource(MEDIA))


def test_candidates_contain_no_transport_or_admission_claims():
    browser = HANDOFF.finalize_browser_receipt(
        browser_observation(), MediaSource(MEDIA, browser=True))
    native = HANDOFF.finalize_native_receipt(
        native_observation(), browser.receipt_bytes, MediaSource(MEDIA))
    for candidate in (browser, native):
        assert candidate.qualification == "not-assessed"
        document = CONTRACT.parse_document(candidate.receipt_bytes)
        assert "archiveSha256" not in candidate.receipt_bytes.decode()
        assert "authentication" not in document
        assert "qualification" not in document


def test_candidate_handoff_keys_are_role_specific():
    browser = HANDOFF.finalize_browser_receipt(
        browser_observation(), MediaSource(MEDIA, browser=True))
    native = HANDOFF.finalize_native_receipt(
        native_observation(), browser.receipt_bytes, MediaSource(MEDIA))
    assert (browser.selection_id, browser.bound_browser_receipt_sha256) == (
        "operation-101-attempt-2", None)
    assert (native.selection_id, native.bound_browser_receipt_sha256) == (
        None, browser.receipt_sha256)
    assert not hasattr(browser, "handoff_id")


@pytest.mark.parametrize("role", ["browser", "native"])
def test_contract_rejection_reports_a_receipt_field_path(role):
    with pytest.raises(HANDOFF.ReceiptHandoffError) as caught:
        if role == "browser":
            HANDOFF.finalize_browser_receipt(
                replace(browser_observation(), overlay={}),
                MediaSource(MEDIA, browser=True))
        else:
            HANDOFF.finalize_native_receipt(
                replace(native_observation(), harness={}),
                CASES["browserReceiptUtf8"].encode(), MediaSource(MEDIA))
    assert (caught.value.code, caught.value.field) == (
        "invalid_observation", "receipt." + role)
    assert type(caught.value.__cause__).__name__ == "ContractError"


def test_native_size_bound_is_checked_locally_before_any_media_read(monkeypatch):
    monkeypatch.setattr(HANDOFF, "MAX_ISO_BYTES", len(MEDIA) - 1)
    media = MediaSource(MEDIA)
    with pytest.raises(HANDOFF.ReceiptHandoffError) as caught:
        HANDOFF.finalize_native_receipt(
            native_observation(), CASES["browserReceiptUtf8"].encode(), media)
    assert (caught.value.code, caught.value.field) == (
        "invalid_observation", "browserReceipt.media.sizeBytes")
    assert media.events == []


def test_source_and_overlay_observations_cannot_swap_meanings():
    observed = browser_observation()
    observed = replace(observed, source_manifest=observed.overlay,
                       overlay=observed.source_manifest)
    media = MediaSource(MEDIA, browser=True)
    with pytest.raises(HANDOFF.ReceiptHandoffError, match="invalid_observation"):
        HANDOFF.finalize_browser_receipt(observed, media)
    assert media.events == []


@pytest.mark.parametrize("change", ["sha256", "missing-size"])
def test_native_media_identity_must_equal_bound_browser_media(change):
    observed = native_observation()
    media_identity = copy.deepcopy(observed.media)
    if change == "sha256":
        media_identity["sha256"] = "sha256:" + "9" * 64
    else:
        del media_identity["sizeBytes"]
    observed = replace(observed, media=media_identity)
    media = MediaSource(MEDIA)
    with pytest.raises(HANDOFF.ReceiptHandoffError) as caught:
        HANDOFF.finalize_native_receipt(
            observed, CASES["browserReceiptUtf8"].encode(), media)
    assert (caught.value.code, caught.value.field) == (
        "identity_mismatch", "browserReceipt.media")
    assert media.events == []


@pytest.mark.parametrize("change", [
    "installed-digest", "installed-digest-malformed",
    "harness-is-engine", "browser-producer",
])
def test_native_installed_harness_and_producer_identities_keep_their_meaning(change):
    observed = native_observation()
    if change.startswith("installed-digest"):
        plain = copy.deepcopy(observed.plain)
        plain["installedDigest"] = (
            "not-a-digest" if change.endswith("malformed")
            else "sha256:" + "9" * 64)
        observed = replace(observed, plain=plain)
    elif change == "harness-is-engine":
        observed = replace(observed, harness=copy.deepcopy(BROWSER["input_descriptors"]["engine"]))
    else:
        observed = replace(observed, producer_run=copy.deepcopy(BROWSER["run"]))
    media = MediaSource(MEDIA)
    with pytest.raises(HANDOFF.ReceiptHandoffError):
        HANDOFF.finalize_native_receipt(
            observed, CASES["browserReceiptUtf8"].encode(), media)
    assert media.events == []
