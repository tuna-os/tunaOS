"""Construct diagnostic-only RFC014 v2 receipts from explicit observations.

The browser boundary finishes the selected media sink before it reopens and
measures the saved bytes. The native boundary remeasures the supplied media and
binds the exact raw browser receipt. Neither boundary authenticates a producer,
creates transport metadata, or admits media for qualification.
"""
from dataclasses import dataclass
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import urllib.parse


def _load_contract():
    """Load by path without changing ``sys.path`` or registering this module."""
    path = Path(__file__).resolve().with_name("iso_media_provenance.py")
    spec = importlib.util.spec_from_file_location("_receipt_handoff_contract", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


contract = _load_contract()


MAX_ISO_BYTES = 10 * 1024 ** 3
READ_SIZE = 1024 * 1024


class ReceiptHandoffError(ValueError):
    """An observed result cannot produce a diagnostic v2 receipt candidate."""

    def __init__(self, code, field):
        self.code = code
        self.field = field
        super().__init__(f"{code}: {field}")


@dataclass(frozen=True)
class BrowserObservedInput:
    """Operation-local observations; request and catalog fallbacks are forbidden."""

    selection_id: str
    completed_selection_id: str
    build_status: str
    bytes_written: int
    source_manifest: dict
    overlay: dict
    deployed_frontend: dict
    loaded_engine: dict
    build_request_sha256: str
    recipe_sha256: str
    config_sha256: str
    browser: dict
    resources: tuple
    producer_run: dict


@dataclass(frozen=True)
class NativeObservedInput:
    """Native observations of the handed-off receipt, media, and strict GUI runs."""

    browser_receipt_sha256: str
    browser_run: dict
    media: dict
    harness: dict
    producer_run: dict
    plain: dict
    encrypted: dict


@dataclass(frozen=True)
class ReceiptCandidate:
    """Exact receipt bytes for retention; never an admission or trust decision.

    Handoff keys are role-specific and never share one field: a browser
    candidate carries the completed operation's ``selection_id``; a native
    candidate carries the exact raw ``bound_browser_receipt_sha256`` it names.
    The key that does not apply to ``role`` is ``None``.
    """

    role: str
    qualification: str
    receipt_bytes: bytes
    receipt_sha256: str
    media_sha256: str
    media_size_bytes: int
    selection_id: str | None
    bound_browser_receipt_sha256: str | None
    run_id: int
    run_attempt: int


def _reject(code, field, cause=None):
    error = ReceiptHandoffError(code, field)
    if cause is None:
        raise error
    raise error from cause


# Identity checks use exact types on purpose: ``isinstance`` would let ``True``
# pass as an ``int`` size and let a dict/str subclass with a custom ``__eq__``
# decide its own equality. A receipt boundary must not delegate that.
def _same(actual, expected, field):
    if type(actual) is not type(expected) or actual != expected:
        _reject("identity_mismatch", field)


def _selection(value, field):
    if (type(value) is not str or not value.strip() or value != value.strip()
            or any(ord(char) < 32 or ord(char) == 127 for char in value)):
        _reject("invalid_observation", field)


def _size(value, field):
    if type(value) is not int or value <= 0 or value > MAX_ISO_BYTES:
        _reject("invalid_observation", field)


def _digest(data):
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _encode(document):
    try:
        return (json.dumps(document, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
    except (TypeError, ValueError, RecursionError) as exc:
        _reject("invalid_observation", "receipt", exc)


def _validate_receipt(document, role):
    try:
        actual = contract.validate_document(document)
    except contract.ContractError as exc:
        _reject("invalid_observation", "receipt." + role, exc)
    _same(actual, role, "receipt.role")


def _snapshot_token(media, field):
    method = getattr(media, "snapshot_token", None)
    if not callable(method):
        _reject("invalid_media_interface", field)
    try:
        token = method()
    except Exception as exc:
        _reject("media_io", field, exc)
    try:
        token = copy.deepcopy(token)
    except Exception as exc:
        # A token the adapter cannot hold independently is an interface defect,
        # not an I/O failure: the caller could still mutate it under us.
        _reject("invalid_media_interface", field, exc)
    if token is None:
        _reject("invalid_media_interface", field)
    return token


def _measure_media(media, expected_size, *, finish):
    """Hash one stable stream; the browser variant finishes its sink first."""
    if finish:
        method = getattr(media, "finish", None)
        if not callable(method):
            _reject("invalid_media_interface", "media.finish")
        try:
            result = method()
        except Exception as exc:
            _reject("media_finish_failed", "media.finish", exc)
        if result is not None:
            _reject("media_finish_failed", "media.finish")

    before = _snapshot_token(media, "media.snapshotBefore")
    opener = getattr(media, "open", None)
    if not callable(opener):
        _reject("invalid_media_interface", "media.open")
    try:
        stream = opener()
    except Exception as exc:
        _reject("media_io", "media.open", exc)
    reader = getattr(stream, "read", None)
    closer = getattr(stream, "close", None)
    if not callable(reader) or not callable(closer):
        if callable(closer):
            try:
                closer()
            except Exception:
                pass
        _reject("invalid_media_interface", "media.stream")

    digest = hashlib.sha256()
    measured = 0
    primary_error = None
    try:
        tell = getattr(stream, "tell", None)
        if callable(tell):
            try:
                if tell() != 0:
                    _reject("invalid_media_interface", "media.stream.position")
            except OSError:
                pass
        while True:
            # Request one byte more than the bytes still expected. read(0) would
            # return b"" at the boundary and hide trailing bytes as a clean EOF,
            # so this +1 is what makes an overlong stream detectable below.
            requested = min(READ_SIZE, expected_size - measured + 1)
            chunk = reader(requested)
            if type(chunk) is not bytes or len(chunk) > requested:
                _reject("invalid_media_interface", "media.stream.read")
            if not chunk:
                break
            measured += len(chunk)
            if measured > expected_size:
                _reject("identity_mismatch", "media.sizeBytes")
            digest.update(chunk)
    except BaseException as exc:
        primary_error = exc
        if isinstance(exc, ReceiptHandoffError):
            raise
        if isinstance(exc, Exception):
            _reject("media_io", "media.stream", exc)
        raise
    finally:
        try:
            closer()
        except Exception as exc:
            if primary_error is None:
                _reject("media_io", "media.stream.close", exc)

    after = _snapshot_token(media, "media.snapshotAfter")
    _same(after, before, "media.snapshot")
    _same(measured, expected_size, "media.sizeBytes")
    return {"sha256": "sha256:" + digest.hexdigest(), "sizeBytes": measured}


def _browser_document(observed, media):
    return {
        "schemaVersion": 2,
        "kind": "qualification-evidence",
        "half": "browser",
        "media": media,
        "input_descriptors": {
            "source": copy.deepcopy(observed.source_manifest),
            "overlay": copy.deepcopy(observed.overlay),
            "installer": copy.deepcopy(observed.deployed_frontend),
            "engine": copy.deepcopy(observed.loaded_engine),
        },
        "build_request_sha256": observed.build_request_sha256,
        "recipe_sha256": observed.recipe_sha256,
        "config_sha256": observed.config_sha256,
        "browser": copy.deepcopy(observed.browser),
        "resources": copy.deepcopy(list(observed.resources)),
        "run": copy.deepcopy(observed.producer_run),
    }


def finalize_browser_receipt(observed, saved_media):
    """Finish, reopen, and measure saved media before emitting browser v2 bytes.

    ``saved_media`` must provide ``finish()``, ``snapshot_token()``, and
    ``open()``. ``finish`` performs the successful save and sink close and MUST
    return ``None``; any other return value is a failed or ambiguous save.
    ``open`` returns a fresh binary stream over those closed bytes. The snapshot
    token must change whenever the saved object changes.
    """
    if type(observed) is not BrowserObservedInput:
        _reject("invalid_observation", "browser")
    _selection(observed.selection_id, "selection_id")
    _selection(observed.completed_selection_id, "completed_selection_id")
    _same(observed.completed_selection_id, observed.selection_id, "selection")
    _same(observed.build_status, "completed", "build_status")
    _size(observed.bytes_written, "bytes_written")

    placeholder = {"sha256": "sha256:" + "0" * 64,
                   "sizeBytes": observed.bytes_written}
    # Snapshot every caller-owned field once, before finish()/open()/read() can
    # run; only the measured media is substituted afterwards.
    document = _browser_document(observed, placeholder)
    _validate_receipt(document, "browser")
    media = _measure_media(saved_media, observed.bytes_written, finish=True)
    document["media"] = media
    _validate_receipt(document, "browser")
    receipt = _encode(document)
    run = document["run"]
    return ReceiptCandidate(
        role="browser", qualification="not-assessed", receipt_bytes=receipt,
        receipt_sha256=_digest(receipt), media_sha256=media["sha256"],
        media_size_bytes=media["sizeBytes"], selection_id=observed.selection_id,
        bound_browser_receipt_sha256=None,
        run_id=run["runId"], run_attempt=run["runAttempt"],
    )


def _browser_observation_envelope(envelope_bytes):
    try:
        envelope = contract.parse_document(envelope_bytes)
    except contract.ContractError as exc:
        _reject("invalid_observation", "envelope", exc)
    required = {"schemaVersion", "kind", "qualification", "observed",
                "missingFields", "media", "measurements"}
    if set(envelope) != required:
        _reject("invalid_observation", "envelope.fields")
    _same(envelope["schemaVersion"], 1, "envelope.schemaVersion")
    _same(envelope["kind"], "browser-observed-input", "envelope.kind")
    _same(envelope["qualification"], "not-assessed", "envelope.qualification")
    values, missing = envelope["observed"], envelope["missingFields"]
    fields = set(BrowserObservedInput.__dataclass_fields__)
    if (type(values) is not dict or type(missing) is not list
            or any(type(name) is not str for name in missing)
            or len(missing) != len(set(missing)) or set(missing) & set(values)
            or set(missing) | set(values) != fields
            or type(envelope["measurements"]) is not dict):
        _reject("invalid_observation", "envelope.observed")
    try:
        contract._media(envelope["media"], "envelope.media")
    except contract.ContractError as exc:
        _reject("invalid_observation", "envelope.media", exc)
    return envelope


def finalize_browser_observation(envelope_bytes, saved_media):
    """Join a complete explicit envelope to remeasured media, never fallback IDs."""
    envelope = _browser_observation_envelope(envelope_bytes)
    _same(envelope["missingFields"], [], "envelope.missingFields")
    values = envelope["observed"]
    if type(values["resources"]) is not list:
        _reject("invalid_observation", "envelope.observed.resources")
    _size(envelope["media"]["sizeBytes"], "envelope.media.sizeBytes")
    _same(values["bytes_written"], envelope["media"]["sizeBytes"], "envelope.media.sizeBytes")
    values = copy.deepcopy(values)
    values["resources"] = tuple(values["resources"])
    candidate = finalize_browser_receipt(BrowserObservedInput(**values), saved_media)
    _same(candidate.media_sha256, envelope["media"]["sha256"], "envelope.media.sha256")
    return candidate


def bind_browser_source_observation(envelope_bytes, source_context, transport_origins):
    """Bind consumed source facts to existing independently supplied v2 context.

    ``source_context`` is the source descriptor already defined by RFC014;
    ``transport_origins`` is its independent exact transport-to-origin map.
    Neither argument may come from a candidate, request or catalog fallback.
    The CPU baseline remains a supplied claim, never measured hardware support.
    This function creates no producer authentication or admission authority.
    """
    envelope = _browser_observation_envelope(envelope_bytes)
    if "source_manifest" not in envelope["missingFields"]:
        _reject("invalid_observation", "envelope.source_already_bound")
    if type(source_context) is not dict or type(transport_origins) is not dict:
        _reject("invalid_context", "source")
    source_context = copy.deepcopy(source_context)
    try:
        contract.validate_source_descriptor(source_context)
    except contract.ContractError as exc:
        _reject("invalid_context", "source", exc)
    source = envelope["measurements"].get("source")
    if type(source) is not dict:
        _reject("missing_observation", "source")
    for field in ("registryEndpoint", "repository", "manifestDigest"):
        if field not in source:
            _reject("missing_observation", "source." + field)
        _selection(source[field], "source." + field)
    endpoint, repository = source["registryEndpoint"], source["repository"]
    try:
        parsed = urllib.parse.urlsplit(endpoint)
        if (parsed.scheme != "https" or not parsed.hostname
                or parsed.username is not None or parsed.password is not None
                or parsed.query or parsed.fragment or "?" in endpoint or "#" in endpoint):
            _reject("invalid_observation", "source.registryEndpoint")
        parsed.port
    except ValueError as exc:
        _reject("invalid_observation", "source.registryEndpoint", exc)
    origin = transport_origins.get(endpoint)
    if type(origin) is not str or not origin:
        _reject("missing_origin_mapping", "source.registryEndpoint")
    try:
        parsed_origin = urllib.parse.urlsplit("https://" + origin)
        if (parsed_origin.netloc != origin or not parsed_origin.hostname
                or parsed_origin.username is not None or parsed_origin.password is not None
                or parsed_origin.path or parsed_origin.query or parsed_origin.fragment):
            _reject("invalid_context", "source.origin")
        parsed_origin.port
    except ValueError as exc:
        _reject("invalid_context", "source.origin", exc)
    _same(source["manifestDigest"], source_context["digest"], "source.manifestDigest")
    _same(origin + "/" + repository + "@" + source["manifestDigest"],
          source_context["ref"], "source.ref")
    config = source.get("config")
    if type(config) is not dict or config.get("bytesVerified") is not True:
        _reject("missing_observation", "source.config.bytesVerified")
    content = config.get("content")
    if type(content) is not dict:
        _reject("missing_observation", "source.config.content")
    if set(content) - {"os", "architecture", "variant"}:
        _reject("invalid_observation", "source.config.content")
    platform = source_context["platform"].split("/")
    for field, expected in (("os", platform[0]), ("architecture", platform[1])):
        if field not in content:
            _reject("missing_observation", "source.config.content." + field)
        _same(content[field], expected, "source.config.content." + field)
    config_variant = content.get("variant", "")
    if type(config_variant) is not str:
        _reject("invalid_observation", "source.config.content.variant")
    descriptor = source.get("platformDescriptor")
    descriptor_variant = ""
    if descriptor is not None:
        if type(descriptor) is not dict:
            _reject("invalid_observation", "source.platformDescriptor")
        try:
            contract._digest(source.get("indexDigest"), "source.indexDigest")
        except contract.ContractError as exc:
            _reject("invalid_observation", "source.indexDigest", exc)
        _same(descriptor.get("architecture"), platform[1], "source.platformDescriptor.architecture")
        descriptor_variant = descriptor.get("variant", "")
        if type(descriptor_variant) is not str:
            _reject("invalid_observation", "source.platformDescriptor.variant")
    if config_variant and descriptor_variant:
        _same(config_variant, descriptor_variant, "source.variant")
    if len(platform) == 3:
        if not config_variant and not descriptor_variant:
            _reject("missing_observation", "source.variant")
        for variant in (config_variant, descriptor_variant):
            if variant:
                _same(variant, platform[2], "source.variant")
    envelope["observed"]["source_manifest"] = source_context
    envelope["missingFields"].remove("source_manifest")
    envelope["measurements"]["sourceBinding"] = {
        "registryEndpoint": endpoint, "origin": origin, "repository": repository,
        "cpuBaselineClaim": {"value": source_context["cpuBaseline"],
                             "source": "independent-context", "method": "supplied-claim"},
    }
    return _encode(envelope)


_MODE_FIELDS = {
    "sourceDigest", "installedDigest", "network", "installer", "installStatus",
    "bootMedia", "bootStatus", "desktopContract", "fixture",
}
_MODE_REQUIREMENTS = {
    "network": "offline",
    "installer": "gui",
    "installStatus": "completed",
    "bootMedia": "target-only",
    "bootStatus": "completed",
    "desktopContract": "passed",
}


def _native_mode(value, name):
    if type(value) is not dict or set(value) != _MODE_FIELDS:
        _reject("invalid_observation", name)
    for field, expected in _MODE_REQUIREMENTS.items():
        _same(value[field], expected, name + "." + field)
    if value["fixture"] is not False:
        _reject("nonqualifying_observation", name + ".fixture")
    return {
        "sourceDigest": value["sourceDigest"],
        "bootedDigest": value["installedDigest"],
        "offlineNetworkDisabled": True,
        "guiCompleted": True,
        "targetOnlyReboot": True,
        "desktopContract": True,
    }


def _native_document(observed):
    return {
        "schema": "QualificationEvidence/v2",
        "media": copy.deepcopy(observed.media),
        "browserReceiptSha256": observed.browser_receipt_sha256,
        "harness": copy.deepcopy(observed.harness),
        "run": copy.deepcopy(observed.producer_run),
        "observed": {
            "plain": _native_mode(observed.plain, "plain"),
            "encrypted": _native_mode(observed.encrypted, "encrypted"),
        },
    }


def finalize_native_receipt(observed, browser_receipt_bytes, supplied_media):
    """Bind strict native observations to exact browser receipt and media bytes.

    ``supplied_media`` provides ``snapshot_token()`` and ``open()`` for the exact
    media selected for the native run. The caller's observed receipt hash, run,
    and media identity are compared rather than synthesized from browser data.
    """
    if type(observed) is not NativeObservedInput:
        _reject("invalid_observation", "native")
    if type(browser_receipt_bytes) is not bytes:
        _reject("invalid_browser_receipt", "browserReceipt")
    try:
        browser = contract.parse_document(browser_receipt_bytes)
        role = contract.validate_document(browser)
    except contract.ContractError as exc:
        _reject("invalid_browser_receipt", "browserReceipt", exc)
    _same(role, "browser", "browserReceipt.role")
    _same(_digest(browser_receipt_bytes), observed.browser_receipt_sha256,
          "browserReceipt.sha256")
    _same(browser["run"], observed.browser_run, "browserReceipt.run")
    _same(browser["media"], observed.media, "browserReceipt.media")

    document = _native_document(observed)
    _validate_receipt(document, "native")
    source_digest = browser["input_descriptors"]["source"]["digest"]
    for mode in ("plain", "encrypted"):
        mode_observed = document["observed"][mode]
        _same(mode_observed["sourceDigest"], source_digest,
              mode + ".sourceDigest")
        _same(mode_observed["bootedDigest"], source_digest,
              mode + ".bootedDigest")
    # browser["media"] passed the v2 contract and equals observed.media above;
    # bound it locally too so no contract change can drive an oversized read.
    expected_size = browser["media"]["sizeBytes"]
    _size(expected_size, "browserReceipt.media.sizeBytes")
    measured = _measure_media(supplied_media, expected_size, finish=False)
    # Compare with the validated copy the receipt bytes are built from, not the
    # caller-owned dict, which can change while the media is opened and read.
    _same(measured, document["media"], "media")
    receipt = _encode(document)
    run = document["run"]
    return ReceiptCandidate(
        role="native", qualification="not-assessed", receipt_bytes=receipt,
        receipt_sha256=_digest(receipt), media_sha256=measured["sha256"],
        media_size_bytes=measured["sizeBytes"],
        selection_id=None,
        bound_browser_receipt_sha256=observed.browser_receipt_sha256,
        run_id=run["runId"], run_attempt=run["runAttempt"],
    )
