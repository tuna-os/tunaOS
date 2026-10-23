#!/usr/bin/env python3
"""Fetch one immutable native ISO for diagnosis/qualification, never R2 latest.

GitHub's artifact digest identifies the ZIP, not the ISO. Verify that archive
before extracting and record the separately measured media digest for the harness.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import io
import selectors
import stat
import struct
import time
from datetime import datetime
import subprocess
import zipfile

MAX_BYTES = 12 * 1024**3
MAX_STDERR = 16 * 1024
ARCHIVE_IDLE_SECONDS = 120


def archive_deadline(size):
    """Bound large transfers by measured size, with a fixed one-hour ceiling."""
    if type(size) is not int or not 0 < size <= MAX_BYTES:
        raise ValueError('artifact size out of bounds')
    minimum_rate = 2 * 1024**2
    return min(3600, max(1200, (size+minimum_rate-1)//minimum_rate + 120))


def transfer_category(stderr):
    """Return fixed labels only; never expose URLs, tokens or arbitrary stderr."""
    text = stderr.decode('utf-8', errors='replace').lower()
    for code in (401, 403, 404, 408, 429, 500, 502, 503, 504):
        if re.search(rf'\bhttp(?: status)?[ :]+{code}\b', text):
            return 'http_' + str(code)
    for marker, label in (('unexpected eof', 'unexpected_eof'),
                          ('connection reset', 'connection_reset'),
                          ('connection refused', 'connection_refused'),
                          ('tls handshake timeout', 'tls_timeout'),
                          ('i/o timeout', 'io_timeout'),
                          ('context deadline exceeded', 'context_deadline'),
                          ('no space left on device', 'disk_full')):
        if marker in text:
            return label
    return 'unclassified'


def bounded_command(command, destination, limit, timeout, idle_timeout=None):
    """Bound output bytes and elapsed time before writing untrusted output."""
    started = time.monotonic()
    deadline = started + timeout
    last_progress = started
    count = 0
    stderr = bytearray()
    stderr_count = 0
    with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE) as process:
        def failure(reason):
            details = {'bytes_received': count,
                       'elapsed_seconds': round(max(0, time.monotonic()-started), 3),
                       'returncode': process.poll(),
                       'stderr_bytes': stderr_count,
                       'stderr_truncated': stderr_count > MAX_STDERR,
                       'category': transfer_category(stderr)}
            return ValueError(reason + '; ' + json.dumps(details, sort_keys=True))
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ)
                selector.register(process.stderr, selectors.EVENT_READ)
                while selector.get_map():
                    now = time.monotonic()
                    remaining = deadline - now
                    if remaining <= 0:
                        raise failure("GitHub transfer deadline exceeded")
                    if idle_timeout is not None:
                        idle_remaining = last_progress + idle_timeout - now
                        if idle_remaining <= 0:
                            raise failure("GitHub transfer idle deadline exceeded")
                        remaining = min(remaining, idle_remaining)
                    for key, _ in selector.select(min(remaining, 1)):
                        is_stderr = key.fileobj is process.stderr
                        chunk = os.read(key.fd, 16 * 1024 if is_stderr else 1024 * 1024)
                        if not chunk:
                            selector.unregister(key.fileobj)
                            continue
                        if is_stderr:
                            stderr_count += len(chunk)
                            stderr.extend(chunk[:max(0, MAX_STDERR-len(stderr))])
                            continue
                        count += len(chunk)
                        if count > limit:
                            raise failure("GitHub transfer byte limit exceeded")
                        destination.write(chunk)
                        last_progress = time.monotonic()
            wait_deadline = deadline if idle_timeout is None else min(deadline, last_progress + idle_timeout)
            if process.wait(timeout=max(0.001, wait_deadline - time.monotonic())):
                raise failure("GitHub transfer failed")
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
            reason = ("GitHub transfer idle deadline exceeded" if idle_timeout is not None
                      and last_progress + idle_timeout < deadline
                      else "GitHub transfer deadline exceeded")
            raise failure(reason) from None
        except BaseException:
            process.kill()
            process.wait()
            raise
    return count


def api(repo, suffix):
    output = io.BytesIO()
    bounded_command(["gh", "api", f"repos/{repo}/{suffix}"], output, 1024 * 1024, 60)
    return json.loads(output.getvalue())


def validate(run, artifact, args, jobs=None):
    if not re.fullmatch(r"[0-9a-f]{40}", args.source_sha):
        raise ValueError("source SHA must be a full commit")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", args.archive_digest):
        raise ValueError("archive digest must be sha256:<64 lowercase hex>")
    same_run = (os.environ.get("NATIVE_SAME_RUN") == "true"
                and str(args.run_id) == os.environ.get("GITHUB_RUN_ID"))
    if same_run and args.repository != os.environ.get("GITHUB_REPOSITORY"):
        raise ValueError("same-run producer must belong to the current repository")
    if same_run and str(run.get("run_attempt")) != os.environ.get("GITHUB_RUN_ATTEMPT"):
        raise ValueError("same-run artifact must belong to the current producer attempt")
    completed = run.get("status") == "completed" and run.get("conclusion") == "success"
    active = (same_run and run.get("status") in ("queued", "in_progress")
              and run.get("conclusion") is None)
    if run.get("id") != args.run_id or not (completed or active):
        raise ValueError(f"producer is not admissible: id={run.get('id')} "
                         f"status={run.get('status')} conclusion={run.get('conclusion')} same_run={same_run}")
    if run.get("head_sha") != args.source_sha or run.get("path") != ".github/workflows/live-iso-bootc.yml":
        raise ValueError("producer source SHA or workflow mismatch")
    if run.get("repository", {}).get("full_name") != args.repository or run.get("head_repository", {}).get("full_name") != args.repository:
        raise ValueError("producer must originate in this repository")
    if artifact.get("id") != args.artifact_id or artifact.get("expired") is not False:
        raise ValueError("artifact is wrong or expired")
    expected_name = f"{args.variant}-{args.flavor}-live-iso"
    attempt = args.attempt or (run.get("run_attempt") if same_run else 0)
    if attempt:
        if attempt != run.get("run_attempt"):
            raise ValueError("artifact attempt must match the verified producer attempt")
        expected_name += f"-attempt-{attempt}"
        created = datetime.fromisoformat(artifact["created_at"].replace("Z", "+00:00"))
        started = datetime.fromisoformat(run["run_started_at"].replace("Z", "+00:00"))
        if created < started:
            raise ValueError("artifact predates this producer attempt")
    if artifact.get("name") != expected_name:
        raise ValueError("artifact target or attempt mismatch")
    if artifact.get("digest") != args.archive_digest:
        raise ValueError("artifact archive digest mismatch")
    producer = artifact.get("workflow_run", {})
    if producer.get("id") != args.run_id or producer.get("head_sha") != args.source_sha:
        raise ValueError("artifact producer mismatch")
    if not 0 < artifact.get("size_in_bytes", 0) <= MAX_BYTES:
        raise ValueError("artifact size out of bounds")
    if same_run:
        if not isinstance(jobs, dict) or jobs.get("total_count") != len(jobs.get("jobs", [])):
            raise ValueError("complete bounded same-attempt producer jobs required")
        builders = [job for job in jobs["jobs"] if job.get("name") == "build"]
        if len(builders) != 1:
            raise ValueError("exactly one native build job required")
        builder = builders[0]
        if (builder.get("run_id") != args.run_id or builder.get("run_attempt") != attempt
                or builder.get("head_sha") != args.source_sha
                or builder.get("status") != "completed" or builder.get("conclusion") != "success"):
            raise ValueError("native build job must succeed on this exact run, attempt and source")
        built_start = datetime.fromisoformat(builder["started_at"].replace("Z", "+00:00"))
        built_end = datetime.fromisoformat(builder["completed_at"].replace("Z", "+00:00"))
        if not built_start <= created <= built_end:
            raise ValueError("artifact was not created during the successful native build")
        return builder["id"]
    return None


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return "sha256:" + value.hexdigest()


def check_zip_directory(archive):
    """Bound ZIP/ZIP64 directory allocation before Python's ZIP parser runs."""
    size = archive.stat().st_size
    with archive.open("rb") as stream:
        stream.seek(max(0, size - 65557))
        tail = stream.read(65557)
        offset = tail.rfind(b"PK\x05\x06")
        if offset < 0 or offset + 22 > len(tail):
            raise ValueError("missing ZIP end record")
        _, disk, directory_disk, disk_count, count, directory_size, directory_offset, comment = struct.unpack_from("<4s4H2LH", tail, offset)
        if offset + 22 + comment != len(tail):
            raise ValueError("invalid ZIP end record")
        end_position = size - len(tail) + offset
        needs_zip64 = 65535 in (disk_count, count) or 0xffffffff in (directory_size, directory_offset)
        locator = b""
        if end_position >= 20:
            stream.seek(end_position - 20)
            locator = stream.read(20)
        # Python honors a ZIP64 locator even when legacy fields are not sentinels.
        if locator.startswith(b"PK\x06\x07"):
            signature, locator_disk, position, disks = struct.unpack("<4sLQL", locator)
            if signature != b"PK\x06\x07" or locator_disk or disks != 1 or position + 56 > end_position - 20:
                raise ValueError("invalid ZIP64 locator")
            stream.seek(position)
            record = stream.read(56)
            signature, record_size, _, _, disk, directory_disk, disk_count, count, directory_size, directory_offset = struct.unpack("<4sQ2H2L4Q", record)
            if signature != b"PK\x06\x06" or record_size != 44 or position + 12 + record_size != end_position - 20:
                raise ValueError("invalid ZIP64 end record")
            end_position = position
        elif needs_zip64:
            raise ValueError("missing ZIP64 locator")
        if disk or directory_disk or disk_count != 1 or count != 1:
            raise ValueError("native archive must have exactly one member on one disk")
        if not 0 < directory_size <= 256 * 1024 or directory_offset + directory_size > end_position:
            raise ValueError("ZIP central directory out of bounds")


def extract(archive, output, variant, flavor):
    check_zip_directory(archive)
    with zipfile.ZipFile(archive) as bundle:
        members = bundle.infolist()
        if len(members) != 1:
            raise ValueError("native artifact must contain exactly one ISO")
        member = members[0]
        if (member.orig_filename != member.filename
                or not re.fullmatch(r"[A-Za-z0-9_.-]+\.iso", member.filename)
                or not member.filename.startswith(f"{variant}-{flavor}-")
                or not 0 < member.file_size <= MAX_BYTES
                or member.is_dir()
                or stat.S_IFMT(member.external_attr >> 16) not in (0, stat.S_IFREG)):
            raise ValueError("unsafe or unexpected ISO member")
        target = output / member.filename
        with bundle.open(member) as source, target.open("xb") as dest:
            copied = 0
            deadline = time.monotonic() + 600
            while True:
                if time.monotonic() >= deadline:
                    raise ValueError("ISO extraction deadline exceeded")
                chunk = source.read(1024 * 1024)
                if not chunk:
                    break
                copied += len(chunk)
                if copied > member.file_size or copied > MAX_BYTES:
                    raise ValueError("ISO extraction byte limit exceeded")
                dest.write(chunk)
            if copied != member.file_size:
                raise ValueError("ISO extracted size mismatch")
    target.chmod(0o444)
    return target.resolve()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--run-id", required=True, type=int)
    parser.add_argument("--artifact-id", required=True, type=int)
    parser.add_argument("--attempt", type=int, default=0)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--archive-digest", required=True)
    parser.add_argument("--variant", required=True)
    parser.add_argument("--flavor", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", args.repository):
        parser.error("invalid repository")
    for value in (args.variant, args.flavor):
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", value):
            parser.error("invalid target")
    run = api(args.repository, f"actions/runs/{args.run_id}")
    artifact = api(args.repository, f"actions/artifacts/{args.artifact_id}")
    print(json.dumps({"producer_run": run.get("id"), "status": run.get("status"),
                      "conclusion": run.get("conclusion"), "attempt": run.get("run_attempt"),
                      "head_sha": run.get("head_sha")}), flush=True)
    jobs = None
    if os.environ.get("NATIVE_SAME_RUN") == "true" and str(args.run_id) == os.environ.get("GITHUB_RUN_ID"):
        # Query the requested attempt, never the API's mutable latest-attempt view.
        jobs = api(args.repository, f"actions/runs/{args.run_id}/attempts/{args.attempt or run.get('run_attempt')}/jobs?per_page=100")
    builder_id = validate(run, artifact, args, jobs)
    args.output.mkdir(parents=True, exist_ok=False)
    archive = args.output / "native-iso.zip"
    with archive.open("xb") as target:
        timeout = archive_deadline(artifact['size_in_bytes'])
        print(json.dumps({'archive_bytes': artifact['size_in_bytes'],
                          'transfer_deadline_seconds': timeout,
                          'idle_deadline_seconds': ARCHIVE_IDLE_SECONDS}), flush=True)
        bounded_command(["gh", "api", f"repos/{args.repository}/actions/artifacts/{args.artifact_id}/zip"],
                        target, artifact["size_in_bytes"], timeout, ARCHIVE_IDLE_SECONDS)
    if archive.stat().st_size != artifact["size_in_bytes"] or digest(archive) != args.archive_digest:
        raise ValueError("downloaded archive does not match producer artifact")
    iso = extract(archive, args.output, args.variant, args.flavor)
    media_digest = digest(iso)
    harness = io.BytesIO()
    bounded_command(["git", "rev-parse", "HEAD"], harness, 128, 10)
    harness_sha = harness.getvalue().decode().strip()
    if not re.fullmatch(r"[0-9a-f]{40}", harness_sha):
        raise ValueError("invalid checked-out harness SHA")
    receipt = {"repository": args.repository, "producer_workflow": run.get("path"),
               "producer_build_conclusion": "success" if builder_id is not None else None,
               "producer_build_job": builder_id, "producer_status": run.get("status"),
               "producer_conclusion": run.get("conclusion"), "producer_attempt": run.get("run_attempt"),
               "harness_sha": harness_sha, "producer_run": args.run_id, "producer_sha": args.source_sha,
               "artifact_id": args.artifact_id, "archive_digest": args.archive_digest,
               "media_digest": media_digest, "media_size": iso.stat().st_size,
               "media_filename": iso.name, "status": "download_verified_not_boot_tested"}
    (args.output / "artifact-binding.json").write_text(json.dumps(receipt, indent=2) + "\n")
    archive.unlink()
    with open(os.environ["GITHUB_ENV"], "a", encoding="utf-8") as env:
        env.write(f"ISO_PATH={iso}\nVARIANT={args.variant}\nFLAVOR={args.flavor}\nNATIVE_MEDIA_DIGEST={media_digest}\n")
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
