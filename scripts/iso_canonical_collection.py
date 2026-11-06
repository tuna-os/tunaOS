"""Read-only RFC014 collection and diagnostic handoff; never admission authority.

Policy, context, and artifact coordinates are independent operator inputs. No
candidate can select a URL, workflow, artifact, or expected digest. A successful
collection still reports not_authenticated and cannot qualify installation media.
"""
import argparse
from contextlib import contextmanager
import copy
import hashlib
import io
import json
from pathlib import Path
import stat
import struct
import subprocess
import tempfile
import zipfile

import iso_artifact_transport as artifact
import iso_authoritative_transport as http
import iso_media_provenance as contract
import iso_media_receipt_handoff as handoff


MAX_DIRECTORY_BYTES = 1024 * 1024


class CollectionError(ValueError):
    def __init__(self, code, field):
        self.code, self.field = code, field
        super().__init__(f"{code}: {field}")


def _reject(code, field):
    raise CollectionError(code, field)


def _same(actual, expected, field):
    if type(actual) is not type(expected) or actual != expected:
        _reject("identity_mismatch", field)


def _digest(data):
    return "sha256:" + hashlib.sha256(data).hexdigest()


class _RecordingReader:
    def __init__(self, stream, destination):
        self.stream, self.destination = stream, destination

    def read(self, size):
        data = self.stream.read(size)
        if type(data) is not bytes or len(data) > size:
            _reject("invalid_stream", "archive.read")
        self.destination.write(data)
        return data


def _run_refusal(document, policy, selection, where):
    try:
        artifact._run(document, policy, selection, where)
    except artifact.ArtifactVerificationError as error:
        return {"code": error.code, "field": error.field}
    return None


@contextmanager
def _collect_archive(policy, selection, network_policy, github_token, *, _transport=None):
    """Retain one bounded exact ZIP privately, with before/after REST checks.

    Failed producer runs may be collected as diagnostics, but the unchanged
    snapshot validator's refusal is retained and canonical collection rejects it.
    No ZIP member is extracted and temporary archive bytes are deleted on exit.
    """
    artifact._validate_inputs(policy, selection)
    if policy.max_archive_bytes > artifact.MAX_ISO_BYTES + artifact.MAX_DIAGNOSTIC_BYTES:
        _reject("archive_limit", "policy.max_archive_bytes")
    transport = _transport or http.AuthoritativeTransport(
        policy, selection, network_policy, github_token)
    base = f"/repos/{policy.repository}/actions"
    run_path = f"{base}/runs/{selection.run_id}"
    artifact_path = f"{base}/artifacts/{selection.artifact_id}"
    before = transport.get_json(run_path)
    attempt = transport.get_json(run_path + "/attempts/1")
    metadata = transport.get_json(artifact_path)
    artifact._artifact(metadata, policy, selection)
    refusals = []
    for document, where in ((before, "run_before"), (attempt, "attempt")):
        refusal = _run_refusal(document, policy, selection, where)
        if refusal:
            refusals.append(refusal)
    with tempfile.TemporaryFile(mode="w+b") as destination:
        with transport.open_archive(artifact_path + "/zip") as stream:
            digest, size = artifact._archive_digest(
                _RecordingReader(stream, destination), metadata["size_in_bytes"])
        _same(digest, policy.archive_sha256, "archive.sha256")
        after_artifact = transport.get_json(artifact_path)
        artifact._artifact(after_artifact, policy, selection)
        _same(after_artifact["size_in_bytes"], size, "artifact_after.size_in_bytes")
        after = transport.get_json(run_path)
        refusal = _run_refusal(after, policy, selection, "run_after")
        if refusal:
            refusals.append(refusal)
        _same(after, before, "run.snapshot")
        destination.seek(0)
        report = {
            "status": "diagnostic_only", "authentication": "not_authenticated",
            "qualification": "not-assessed", "archive_digest_verified": True,
            "snapshot_checks_passed": not refusals, "refusals": refusals,
            "repository": policy.repository, "repositoryId": policy.repository_id,
            "workflowId": policy.workflow_id, "workflowPath": policy.workflow_path,
            "sourceRevision": policy.source_revision, "ref": policy.ref,
            "runId": selection.run_id, "runAttempt": selection.attempt,
            "artifactId": selection.artifact_id, "archiveSha256": digest,
            "sizeBytes": size,
        }
        yield destination, report


def collect_artifact_diagnostics(policy, selection, network_policy, github_token, *,
                                 receipt_path=None, _transport=None):
    """Measure a selected archive, without turning failed runs into acceptance."""
    if receipt_path is not None:
        artifact._validate_inputs(policy, selection)
        if policy.max_archive_bytes > artifact.MAX_DIAGNOSTIC_BYTES:
            _reject("archive_limit", "policy.max_archive_bytes")
        artifact._safe_member(receipt_path, "receiptPath")
    with _collect_archive(policy, selection, network_policy, github_token,
                          _transport=_transport) as (archive, report):
        if receipt_path is not None:
            try:
                with _bounded_zip(archive) as zipped:
                    raw = _members(zipped, receipt_path)
            except (zipfile.BadZipFile, NotImplementedError, RuntimeError) as error:
                raise CollectionError("invalid_archive", "archive") from error
            document = contract.parse_document(raw)
            if document.get("schemaVersion") == 1 or document.get("schema") == "QualificationEvidence/v1":
                result = contract.inspect_legacy(raw)
                role, status = result["role"], "legacy_diagnostic_only"
            else:
                role, status = contract.validate_document(document), "structurally_valid_not_admitted"
            report["receipt"] = {"path": receipt_path, "sha256": _digest(raw),
                                 "role": role, "status": status}
        return report


def _bounded_zip(archive):
    """Bound and count the ZIP/ZIP64 directory before ZipInfo allocation."""
    archive.seek(0, 2)
    size = archive.tell()
    archive.seek(max(0, size - 65557))
    ending = archive.read(65557)
    position = ending.rfind(b"PK\x05\x06")
    if position < 0 or len(ending) - position < 22:
        _reject("invalid_archive", "archive.directory")
    end = struct.unpack_from("<4s4H2IH", ending, position)
    if position + 22 + end[7] != len(ending):
        _reject("invalid_archive", "archive.comment")
    absolute_end = size - len(ending) + position
    _, disk, directory_disk, disk_entries, entries, directory_size, offset, _ = end
    boundary = absolute_end
    if absolute_end >= 20:
        archive.seek(absolute_end - 20)
        locator = archive.read(20)
        if locator[:4] == b"PK\x06\x07":
            _, locator_disk, record_offset, disks = struct.unpack("<4sIQI", locator)
            if locator_disk != 0 or disks != 1 or record_offset + 56 != absolute_end - 20:
                _reject("invalid_archive", "archive.zip64")
            archive.seek(record_offset)
            record = archive.read(56)
            if len(record) != 56:
                _reject("invalid_archive", "archive.zip64")
            (signature, record_size, _, _, disk, directory_disk, disk_entries,
             entries, directory_size, offset) = struct.unpack("<4sQ2H2I4Q", record)
            if signature != b"PK\x06\x06" or record_size != 44:
                _reject("invalid_archive", "archive.zip64")
            boundary = record_offset
    if disk != 0 or directory_disk != 0 or disk_entries != entries:
        _reject("invalid_archive", "archive.disks")
    if not 1 <= entries <= 256 or not 0 < directory_size <= MAX_DIRECTORY_BYTES:
        _reject("archive_member_limit", "archive.directory")
    if offset + directory_size != boundary:
        _reject("invalid_archive", "archive.directory")
    archive.seek(offset)
    directory = archive.read(directory_size)
    if len(directory) != directory_size:
        _reject("invalid_archive", "archive.directory")
    cursor, measured_entries = 0, 0
    while cursor < directory_size:
        if directory[cursor:cursor + 4] != b"PK\x01\x02" or directory_size - cursor < 46:
            _reject("invalid_archive", "archive.directory")
        name_size, extra_size, comment_size = struct.unpack_from("<3H", directory, cursor + 28)
        cursor += 46 + name_size + extra_size + comment_size
        measured_entries += 1
        if cursor > directory_size or measured_entries > 256:
            _reject("archive_member_limit", "archive.directory")
    _same(measured_entries, entries, "archive.directory.entries")
    archive.seek(0)
    return zipfile.ZipFile(archive)


def _members(zipped, receipt_path, media_path=None, media_size=None):
    members = zipped.infolist()
    if not 1 <= len(members) <= 256:
        _reject("archive_member_limit", "archive")
    names, diagnostic_size = set(), 0
    for member in members:
        name = member.orig_filename
        artifact._safe_member(name, "archive.member")
        _same(member.filename, name, "archive.member")
        if name in names:
            _reject("duplicate_member", "archive.member")
        names.add(name)
        mode = member.external_attr >> 16
        if (stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR)
                or member.flag_bits & 1):
            _reject("unsafe_member", "archive.member")
        if member.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
            _reject("unsupported_compression", "archive.member")
        if name == media_path:
            _same(member.is_dir(), False, "archive.mediaPath")
            _same(member.file_size, media_size, "archive.media.sizeBytes")
        else:
            diagnostic_size += member.file_size
            if member.file_size < 0 or diagnostic_size > artifact.MAX_DIAGNOSTIC_BYTES:
                _reject("archive_member_limit", "archive.member")
    for name in (receipt_path, media_path):
        if name is not None and name not in names:
            _reject("missing_member", name)
    receipt = zipped.getinfo(receipt_path)
    if receipt.is_dir() or not 0 < receipt.file_size <= artifact.MAX_MANIFEST_BYTES:
        _reject("receipt_size_limit", "archive.receiptPath")
    with zipped.open(receipt) as stream:
        output = io.BytesIO()
        artifact._read_bounded(stream, artifact.MAX_MANIFEST_BYTES, "receipt",
                               expected_size=receipt.file_size, sink=output)
        return output.getvalue()


def _anchor(context, name, policy, selection):
    artifact._validate_inputs(policy, selection)
    producer = context[name]
    run = producer["run"]
    for key, expected in {
        "repository": policy.repository, "workflowPath": policy.workflow_path,
        "workflowRevision": policy.source_revision, "sourceRevision": policy.source_revision,
        "runId": selection.run_id, "runAttempt": selection.attempt,
    }.items():
        _same(run[key], expected, name + ".run." + key)
    for key, expected in {"id": selection.artifact_id,
                          "archiveSha256": policy.archive_sha256, "expired": False}.items():
        _same(producer["artifact"][key], expected, name + ".artifact." + key)


def collect_canonical_v2(context, browser_policy, browser_selection, native_policy,
                         native_selection, network_policy, github_token, *, _transports=None):
    """Join independently selected GitHub archives and actual selected ISO bytes.

    Expected context MUST be independently reviewed, not generated from receipt
    contents. This function checks consistency, not whether that review occurred.
    Existing retained R2 media still requires a separately approved signer.
    """
    context = copy.deepcopy(context)
    _same(contract.validate_document(context), "context", "context.role")
    if context["media"]["sizeBytes"] > artifact.MAX_ISO_BYTES:
        _reject("media_limit", "media.sizeBytes")
    _anchor(context, "browserProducer", browser_policy, browser_selection)
    _anchor(context, "nativeProducer", native_policy, native_selection)
    if native_policy.max_archive_bytes > artifact.MAX_DIAGNOSTIC_BYTES:
        _reject("archive_limit", "native_policy.max_archive_bytes")
    if "mediaTransport" in context["browserProducer"]:
        # Do not invent a signer, public URL, archive member or alternate trust.
        _reject("retained_signer_required", "browserProducer.mediaTransport")
    transports = _transports or (None, None)
    with _collect_archive(browser_policy, browser_selection, network_policy, github_token,
                          _transport=transports[0]) as (browser_archive, browser_report):
        if not browser_report["snapshot_checks_passed"]:
            first = browser_report["refusals"][0]
            _reject(first["code"], first["field"])
        with _collect_archive(native_policy, native_selection, network_policy, github_token,
                              _transport=transports[1]) as (native_archive, native_report):
            if not native_report["snapshot_checks_passed"]:
                first = native_report["refusals"][0]
                _reject(first["code"], first["field"])
            try:
                with _bounded_zip(browser_archive) as browser_zip, _bounded_zip(native_archive) as native_zip:
                    browser_producer, native_producer = context["browserProducer"], context["nativeProducer"]
                    media_path = browser_producer["artifact"]["mediaPath"]
                    browser_bytes = _members(browser_zip, browser_producer["artifact"]["receiptPath"],
                                             media_path, context["media"]["sizeBytes"])
                    native_bytes = _members(native_zip, native_producer["artifact"]["receiptPath"])
                    # Only independently measured archive identities populate transport.
                    observed = {"schemaVersion": 2, "kind": "iso-media-observed-transport"}
                    for name, producer, report, raw in (
                        ("browserProducer", browser_producer, browser_report, browser_bytes),
                        ("nativeProducer", native_producer, native_report, native_bytes),
                    ):
                        observed[name] = {
                            "run": copy.deepcopy(contract.parse_document(raw)["run"]),
                            "artifact": {**producer["artifact"], "id": report["artifactId"],
                                         "archiveSha256": report["archiveSha256"]},
                            "receiptSha256": _digest(raw),
                        }
                    with browser_zip.open(media_path) as media:
                        checked = contract.check_consistency(browser_bytes, native_bytes, media, context, observed)
            except (zipfile.BadZipFile, NotImplementedError, RuntimeError) as error:
                raise CollectionError("invalid_archive", "archive") from error
    return {**checked, "status": "consistent_not_admitted", "qualification": "not-assessed",
            "browserSnapshot": browser_report, "nativeSnapshot": native_report,
            "observedTransport": observed}


def inspect_browser_diagnostics(measurement_bytes, receipt_bytes, observation_bytes=None):
    """Explain actual legacy/incomplete producer bytes without upgrading them."""
    measured, receipt = contract.parse_document(measurement_bytes), contract.parse_document(receipt_bytes)
    _same(measured.get("kind"), "diagnostic-build-measurements", "measurements.kind")
    media = measured.get("iso")
    contract._media(media, "measurements.iso")
    refusals = []
    if media["sizeBytes"] > artifact.MAX_ISO_BYTES:
        refusals.append({"code": "media_limit", "field": "media.sizeBytes"})
    if receipt.get("schemaVersion") == 1:
        contract.inspect_legacy(receipt_bytes)
        refusals.append({"code": "legacy_receipt", "field": "browser.schemaVersion"})
    else:
        _same(contract.validate_document(receipt), "browser", "browser.role")
        _same(receipt["media"], media, "browser.media")
    for name in measured.get("missingIdentity", []):
        refusals.append({"code": "missing_observation", "field": name})
    envelope = (contract.parse_document(observation_bytes)
                if observation_bytes is not None else None)
    if envelope is None:
        refusals.append({"code": "missing_observation", "field": "browserObservedInput"})
    else:
        _same(envelope.get("kind"), "browser-observed-input", "observation.kind")
        _same(envelope.get("schemaVersion"), 1, "observation.schemaVersion")
        _same(envelope.get("qualification"), "not-assessed", "observation.qualification")
        _same(envelope.get("media"), media, "observation.media")
        fields = set(handoff.BrowserObservedInput.__dataclass_fields__)
        missing, values = envelope.get("missingFields"), envelope.get("observed")
        if (type(missing) is not list or any(type(name) is not str for name in missing)
                or len(missing) != len(set(missing)) or type(values) is not dict
                or set(missing) & set(values) or set(missing) | set(values) != fields):
            _reject("invalid_observation", "observation.fields")
        for name in missing:
            refusals.append({"code": "missing_observation", "field": name})
    return {"status": "refused" if refusals else "observation_only", "authentication": "not_authenticated",
            "qualification": "not-assessed", "refusals": refusals, "media": media,
            "measurementSha256": _digest(measurement_bytes), "receiptSha256": _digest(receipt_bytes)}


def _read_document(path):
    with Path(path).open("rb") as stream:
        raw = stream.read(artifact.MAX_DIAGNOSTIC_BYTES + 1)
    return contract.parse_document(raw)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("collect", "snapshot"):
        command = sub.add_parser(name)
        command.add_argument("--reviewed-policy", required=True,
                             help="Independent review input; never a candidate-supplied file")
    inspect = sub.add_parser("inspect-browser")
    inspect.add_argument("--measurements", required=True)
    inspect.add_argument("--receipt", required=True)
    inspect.add_argument("--observation", help="Post-close producer envelope; never a replacement receipt")
    args = parser.parse_args(argv)
    try:
        if args.command == "inspect-browser":
            def raw(path):
                with Path(path).open("rb") as stream:
                    return stream.read(artifact.MAX_DIAGNOSTIC_BYTES + 1)
            report = inspect_browser_diagnostics(raw(args.measurements), raw(args.receipt),
                raw(args.observation) if args.observation else None)
        else:
            reviewed = _read_document(args.reviewed_policy)
            network = dict(reviewed["networkPolicy"])
            network["artifact_redirect_origins"] = tuple(network["artifact_redirect_origins"])
            network = http.ReviewedNetworkPolicy(**network)
            # Use existing auth, never print it or persist it in a receipt/report.
            token = subprocess.run(["gh", "auth", "token"], check=True,
                                   capture_output=True, text=True, timeout=15).stdout.strip()
            browser = artifact.ReviewedPolicy(**reviewed["browserPolicy"])
            selection = artifact.ArtifactSelection(**reviewed["browserSelection"])
            if args.command == "snapshot":
                report = collect_artifact_diagnostics(browser, selection, network, token,
                    receipt_path=reviewed.get("receiptPath"))
            else:
                report = collect_canonical_v2(reviewed["expectedContext"], browser, selection,
                    artifact.ReviewedPolicy(**reviewed["nativePolicy"]),
                    artifact.ArtifactSelection(**reviewed["nativeSelection"]), network, token)
        print(json.dumps(report, sort_keys=True, indent=2))
        return 2 if report["status"] == "refused" or report.get("snapshot_checks_passed") is False else 0
    except (CollectionError, artifact.ArtifactVerificationError, http.AuthoritativeTransportError,
            contract.ContractError, OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        # Only typed, bounded error coordinates; never arbitrary credential-bearing text.
        print(json.dumps({"status": "refused", "authentication": "not_authenticated",
                          "qualification": "not-assessed", "code": getattr(error, "code", "invalid_input"),
                          "field": getattr(error, "field", "collection")}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
