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


def _load_contract():
    """Load the sibling v2 contract by path; no ``sys.path``/``sys.modules`` change."""
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
        token = copy.deepcopy(method())
    except Exception as exc:
        _reject("media_io", field, exc)
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
            chunk = reader(min(READ_SIZE, expected_size - measured + 1))
            if type(chunk) is not bytes:
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
    _validate_receipt(_browser_document(observed, placeholder), "browser")
    media = _measure_media(saved_media, observed.bytes_written, finish=True)
    document = _browser_document(observed, media)
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
        _same(document["observed"][mode]["sourceDigest"], source_digest,
              mode + ".sourceDigest")
    # browser["media"] passed the v2 contract and equals observed.media above;
    # bound it locally too so no contract change can drive an oversized read.
    expected_size = browser["media"]["sizeBytes"]
    _size(expected_size, "browserReceipt.media.sizeBytes")
    measured = _measure_media(supplied_media, expected_size, finish=False)
    _same(measured, observed.media, "media")
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
