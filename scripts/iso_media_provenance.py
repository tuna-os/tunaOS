"""Offline v2 consistency checks; this module never authenticates a producer.

Expected context and observed transport are separate caller-supplied inputs.
A future authenticated collector must obtain them independently. No production
consumer calls this module. Successful checks do not qualify installation media.
"""
import hashlib
import json
import math
import re


class ContractError(ValueError):
    """A document or binding does not conform to the v2 contract."""


def _fail(where, message):
    raise ContractError(f"{where}: {message}")


def parse_document(data):
    """Parse exact UTF-8 receipt bytes without duplicate or non-finite values."""
    if not isinstance(data, bytes) or len(data) > 16 * 1024 * 1024:
        _fail("document", "expected at most 16 MiB of bytes")

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                _fail("document", "duplicate object key")
            result[key] = value
        return result

    def invalid_constant(_):
        _fail("document", "non-finite JSON number")

    def finite_float(text):
        number = float(text)
        if not math.isfinite(number):
            _fail("document", "non-finite JSON number")
        return number

    try:
        value = json.loads(data.decode("utf-8"), object_pairs_hook=pairs,
                           parse_constant=invalid_constant, parse_float=finite_float)
    except (UnicodeDecodeError, ValueError, RecursionError) as exc:
        raise ContractError("document: invalid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        _fail("document", "expected object")
    return value


def _object(value, where, fields, optional=()):
    if not isinstance(value, dict):
        _fail(where, "expected object")
    required = set(fields)
    if not required <= value.keys() or value.keys() - required - set(optional):
        _fail(where, "missing or unknown field")


def _text(value, where, pattern=None):
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        _fail(where, "expected nonempty trimmed text")
    if any(ord(c) < 32 or ord(c) == 127 for c in value):
        _fail(where, "control character")
    if pattern and not re.fullmatch(pattern, value):
        _fail(where, "invalid format")


def _digest(value, where):
    _text(value, where, r"sha256:[0-9a-f]{64}")


def _revision(value, where):
    _text(value, where, r"[0-9a-f]{40}")


def _positive(value, where, integer=False):
    if type(value) not in ((int,) if integer else (int, float)):
        _fail(where, "expected positive number")
    try:
        valid = value > 0 and math.isfinite(value)
    except OverflowError:
        valid = False
    if not valid:
        _fail(where, "expected positive finite number")


def _same(actual, expected, where):
    if type(actual) is not type(expected) or actual != expected:
        _fail(where, "does not match expected value")


def _media(value, where):
    _object(value, where, ("sha256", "sizeBytes"))
    _digest(value["sha256"], where + ".sha256")
    _positive(value["sizeBytes"], where + ".sizeBytes", integer=True)


def _run(value, where):
    _object(value, where, ("repository", "workflowPath", "workflowRevision",
                          "sourceRevision", "harnessRevision", "runId", "runAttempt"))
    _text(value["repository"], where, r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
    _text(value["workflowPath"], where, r"\.github/workflows/[A-Za-z0-9_.-]+\.ya?ml")
    for field in ("workflowRevision", "sourceRevision", "harnessRevision"):
        _revision(value[field], where + "." + field)
    for field in ("runId", "runAttempt"):
        _positive(value[field], where + "." + field, integer=True)


def _inputs(value, where):
    _object(value, where, ("source", "overlay", "installer", "engine"))
    source, overlay, installer, engine = (value[k] for k in ("source", "overlay", "installer", "engine"))
    _object(source, where + ".source", ("kind", "ref", "digest", "platform", "cpuBaseline"))
    _same(source["kind"], "oci-platform-manifest", where + ".source.kind")
    _digest(source["digest"], where + ".source.digest")
    _text(source["ref"], where + ".source.ref", r"[^\s@]+@sha256:[0-9a-f]{64}")
    _same(source["ref"].rsplit("@", 1)[1], source["digest"], where + ".source.ref")
    platforms = {"linux/amd64": "x86-64-v2", "linux/amd64/v2": "x86-64-v2",
                 "linux/arm64": "armv8-a"}
    _text(source["platform"], where + ".source.platform")
    if source["platform"] not in platforms:
        _fail(where + ".source.platform", "unsupported platform")
    _same(source["cpuBaseline"], platforms[source["platform"]], where + ".source.cpuBaseline")
    _object(overlay, where + ".overlay", ("kind", "digest", "baseDigest"))
    _same(overlay["kind"], "oci-platform-manifest", where + ".overlay.kind")
    _digest(overlay["digest"], where + ".overlay.digest")
    _same(overlay["baseDigest"], source["digest"], where + ".overlay.baseDigest")
    _object(installer, where + ".installer", ("kind", "appId", "ref", "arch", "deployedCommit"), ("bundleSha256",))
    _same(installer["kind"], "flatpak-commit", where + ".installer.kind")
    _text(installer["appId"], where + ".installer.appId", r"[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_-]*)+")
    arch = "x86_64" if source["platform"].startswith("linux/amd64") else "aarch64"
    _same(installer["arch"], arch, where + ".installer.arch")
    _text(installer["ref"], where + ".installer.ref", r"app/[^/]+/(x86_64|aarch64)/[^/]+")
    _same(installer["ref"].split("/")[1:3], [installer["appId"], arch], where + ".installer.ref")
    _digest(installer["deployedCommit"], where + ".installer.deployedCommit")
    if "bundleSha256" in installer:
        _digest(installer["bundleSha256"], where + ".installer.bundleSha256")
    _object(engine, where + ".engine", ("kind", "sha256", "sourceRevision", "runtimeShimSha256"))
    _same(engine["kind"], "wasm-module", where + ".engine.kind")
    _digest(engine["sha256"], where + ".engine.sha256")
    _digest(engine["runtimeShimSha256"], where + ".engine.runtimeShimSha256")
    _revision(engine["sourceRevision"], where + ".engine.sourceRevision")


def _profile(value, where):
    _object(value, where, ("product", "version"))
    if value["product"] not in ("chromium", "firefox", "webkit"):
        _fail(where, "unknown browser product")
    _text(value["version"], where + ".version", r"[0-9]+(?:\.[0-9]+){1,3}")


def _resources(values):
    if not isinstance(values, list) or not values:
        _fail("resources", "expected observations")
    seen = set()
    for item in values:
        _object(item, "resources", ("subject", "quantity", "unit", "method", "value", "source"))
        for field, allowed in (("subject", ("browser", "wasm", "host")),
                               ("quantity", ("memoryCapacity", "availableStorage", "elapsedDuration")),
                               ("method", ("measured", "reported", "estimated"))):
            if item[field] not in allowed:
                _fail("resources." + field, "unsupported value")
        key = (item["subject"], item["quantity"])
        if key in seen:
            _fail("resources", "duplicate observation subject and quantity")
        seen.add(key)
        duration = item["quantity"] == "elapsedDuration"
        _same(item["unit"], "seconds" if duration else "bytes", "resources.unit")
        _positive(item["value"], "resources.value")
        if duration:
            _same(item["method"], "measured", "resources.method")
        methods = {
            ("browser", "memoryCapacity"): ("navigator.deviceMemory", "reported"),
            ("browser", "availableStorage"): ("navigator.storage.estimate", "estimated"),
            ("browser", "elapsedDuration"): ("performance.now", "measured"),
            ("wasm", "memoryCapacity"): ("wasm.memory.buffer.byteLength", "measured"),
            ("wasm", "elapsedDuration"): ("performance.now", "measured"),
            ("host", "memoryCapacity"): ("proc.meminfo", "measured"),
            ("host", "availableStorage"): ("statvfs", "measured"),
            ("host", "elapsedDuration"): ("time.monotonic", "measured"),
        }
        if key not in methods:
            _fail("resources", "unsupported observation subject and quantity")
        _same((item["source"], item["method"]), methods[key], "resources.source/method")
    if not {("browser", "memoryCapacity"), ("browser", "availableStorage")} <= seen:
        _fail("resources", "missing browser prerequisites; host values cannot substitute")
    if not any(quantity == "elapsedDuration" for _, quantity in seen):
        _fail("resources", "missing measured duration")


def _harness(value, where):
    _object(value, where, ("kind", "sourceRevision", "qemuSha256"))
    _same(value["kind"], "native-install-harness", where + ".kind")
    _revision(value["sourceRevision"], where + ".sourceRevision")
    _digest(value["qemuSha256"], where + ".qemuSha256")


def _artifact_path(value, where, suffix):
    _text(value, where, r"[A-Za-z0-9][A-Za-z0-9._/-]*" + re.escape(suffix))
    if any(part in ("", ".", "..") for part in value.split("/")):
        _fail(where, "unsafe archive path")


def _producer(value, where, browser):
    _object(value, where, ("run", "artifact", "receiptSha256"))
    _run(value["run"], where + ".run")
    _digest(value["receiptSha256"], where + ".receiptSha256")
    artifact = value["artifact"]
    fields = ("id", "archiveSha256", "expired", "receiptPath") + (("mediaPath",) if browser else ())
    _object(artifact, where + ".artifact", fields)
    _positive(artifact["id"], where + ".artifact.id", integer=True)
    _digest(artifact["archiveSha256"], where + ".artifact.archiveSha256")
    _same(artifact["expired"], False, where + ".artifact.expired")
    _artifact_path(artifact["receiptPath"], where + ".artifact.receiptPath", ".json")
    if browser:
        _artifact_path(artifact["mediaPath"], where + ".artifact.mediaPath", ".iso")


def validate_document(doc):
    """Validate supported v2 structure and local semantics; return its role."""
    if not isinstance(doc, dict):
        _fail("document", "expected object")
    if doc.get("schema") == "QualificationEvidence/v2":
        _object(doc, "native", ("schema", "media", "browserReceiptSha256", "harness", "run", "observed"))
        _media(doc["media"], "native.media")
        _digest(doc["browserReceiptSha256"], "native.browserReceiptSha256")
        _harness(doc["harness"], "native.harness")
        _run(doc["run"], "native.run")
        _same(doc["harness"]["sourceRevision"], doc["run"]["harnessRevision"], "native.harness")
        _object(doc["observed"], "native.observed", ("plain", "encrypted"))
        for mode in ("plain", "encrypted"):
            record = doc["observed"][mode]
            _object(record, mode, ("sourceDigest", "bootedDigest", "offlineNetworkDisabled",
                                   "guiCompleted", "targetOnlyReboot", "desktopContract"))
            for field in ("sourceDigest", "bootedDigest"):
                _digest(record[field], mode + "." + field)
            _same(record["sourceDigest"], record["bootedDigest"], mode + ".bootedDigest")
            for field in ("offlineNetworkDisabled", "guiCompleted", "targetOnlyReboot", "desktopContract"):
                _same(record[field], True, mode + "." + field)
        return "native"
    _same(doc.get("schemaVersion"), 2, "schemaVersion")
    kind = doc.get("kind")
    if kind == "qualification-evidence":
        _object(doc, "browser", ("schemaVersion", "kind", "half", "media", "input_descriptors",
                                "build_request_sha256", "recipe_sha256", "config_sha256", "browser", "resources", "run"))
        _same(doc["half"], "browser", "half")
        _run(doc["run"], "browser.run")
        _resources(doc["resources"])
        role = "browser"
    elif kind in ("iso-media-expected-context", "iso-media-observed-transport"):
        fields = ("schemaVersion", "kind", "browserProducer", "nativeProducer")
        if kind == "iso-media-expected-context":
            fields += ("media", "input_descriptors", "build_request_sha256", "recipe_sha256", "config_sha256", "browser", "harness")
        _object(doc, kind, fields)
        _producer(doc["browserProducer"], "browserProducer", True)
        _producer(doc["nativeProducer"], "nativeProducer", False)
        if kind == "iso-media-observed-transport":
            return "transport"
        _harness(doc["harness"], "context.harness")
        role = "context"
    else:
        _fail("kind", "unsupported v2 role")
    _media(doc["media"], role + ".media")
    _inputs(doc["input_descriptors"], role + ".input_descriptors")
    _profile(doc["browser"], role + ".browser")
    for field in ("build_request_sha256", "recipe_sha256", "config_sha256"):
        _digest(doc[field], role + "." + field)
    return role


def inspect_legacy(data):
    """Read recognized v1 records as diagnostics without converting identities."""
    doc = parse_document(data)
    native = doc.get("schema") == "QualificationEvidence/v1"
    browser = (type(doc.get("schemaVersion")) is int and doc["schemaVersion"] == 1
               and doc.get("kind") == "qualification-evidence" and doc.get("half") == "browser")
    if not native and not browser:
        _fail("legacy", "unrecognized version or role")
    return {"status": "diagnostic_only", "role": "native" if native else "browser",
            "consistency_valid": False, "authentication": "not_authenticated"}


def _media_identity(data, expected_size):
    digest = hashlib.sha256()
    size = 0
    if isinstance(data, bytes):
        if len(data) > expected_size:
            _fail("media", "exceeds expected size")
        digest.update(data)
        size = len(data)
    elif hasattr(data, "read"):
        if hasattr(data, "tell"):
            try:
                position = data.tell()
            except OSError:
                position = 0  # Non-seekable streams still have a strict byte bound.
            if position != 0:
                _fail("media", "stream must start at position zero")
        while True:
            chunk = data.read(min(1024 * 1024, expected_size - size + 1))
            if not isinstance(chunk, bytes):
                _fail("media", "expected binary stream")
            if not chunk:
                break
            size += len(chunk)
            if size > expected_size:
                _fail("media", "exceeds expected size")
            digest.update(chunk)
    else:
        _fail("media", "expected bytes or binary stream")
    return {"sha256": "sha256:" + digest.hexdigest(), "sizeBytes": size}


def check_consistency(browser_bytes, native_bytes, media, expected_context, observed_transport):
    """Check exact bytes and caller-supplied context, never producer authority.

Media may be bytes or a binary stream positioned at its start. Transport metadata
must describe independently measured archives; this function does not fetch them.
"""
    browser, native = parse_document(browser_bytes), parse_document(native_bytes)
    for doc, role in ((browser, "browser"), (native, "native"),
                      (expected_context, "context"), (observed_transport, "transport")):
        _same(validate_document(doc), role, "document role")
    context = expected_context
    identity = _media_identity(media, context["media"]["sizeBytes"])
    for doc in (browser, native, context):
        _same(doc["media"], identity, "media")
    for key, receipt, raw in (("browserProducer", browser, browser_bytes),
                              ("nativeProducer", native, native_bytes)):
        _same(observed_transport[key], context[key], key + ".transport")
        _same(receipt["run"], context[key]["run"], key + ".run")
        _same("sha256:" + hashlib.sha256(raw).hexdigest(), context[key]["receiptSha256"], key + ".receiptSha256")
    _same(native["browserReceiptSha256"], context["browserProducer"]["receiptSha256"], "native.browserReceiptSha256")
    for field in ("input_descriptors", "build_request_sha256", "recipe_sha256", "config_sha256", "browser"):
        _same(browser[field], context[field], "browser." + field)
    _same(native["harness"], context["harness"], "native.harness")
    for mode in ("plain", "encrypted"):
        _same(native["observed"][mode]["sourceDigest"], context["input_descriptors"]["source"]["digest"], mode + ".sourceDigest")
    return {"consistency_valid": True, "authentication": "not_authenticated"}
