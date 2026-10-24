#!/usr/bin/env python3
"""Run the bounded Skipjack/GNOME installed update and rollback pilot.

This harness only boots a disposable qcow2 overlay. It never installs to a
host disk and never attaches installation media. A successful run proves the
exact A -> B -> A sequence described by tunaOS#3798; image/container
inspection alone cannot produce a passing result.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

SCHEMA_VERSION = 1
TARGET = {"variant": "skipjack", "flavor": "gnome", "platform": "linux/amd64"}
IMAGE_RE = re.compile(r"^ghcr\.io/tuna-os/skipjack@sha256:([0-9a-f]{64})$")
SHA256_RE = re.compile(r"^(?:sha256:)?([0-9a-f]{64})$")
GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
RUN_ID_RE = re.compile(r"^[0-9]+(?:/[1-9][0-9]*)?$")
SSH_USER_RE = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")
MAX_LOG_BYTES = 32 * 1024
STAGE_IDS = (
    "preflight",
    "prepare_disk",
    "cold_boot_a",
    "stage_update_b",
    "warm_boot_b",
    "stage_rollback_a",
    "recovery_boot_a",
    "cleanup",
)


class PilotFailure(RuntimeError):
    """A classified pilot failure suitable for retained evidence."""

    def __init__(self, category: str, message: str):
        super().__init__(message)
        self.category = category


@dataclass(frozen=True)
class PilotConfig:
    disk: Path
    disk_sha256: str
    image_a: str
    image_b: str
    ssh_key: Path
    ssh_user: str
    ssh_port: int
    output_dir: Path
    source_run_id: str
    source_head_sha: str
    harness_sha: str
    command_timeout: int = 600
    boot_timeout: int = 900
    reboot_timeout: int = 900
    memory_mib: int = 4096
    cpus: int = 4
    keep_disk: bool = False
    confirmed: bool = False
    variant: str = "skipjack"
    flavor: str = "gnome"
    platform: str = "linux/amd64"


@dataclass
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _serialized_text_size(text: str) -> int:
    return len(json.dumps(text).encode("utf-8")) - 2


def _fit_serialized_text(text: str, limit: int, *, from_end: bool = False) -> str:
    if _serialized_text_size(text) <= limit:
        return text
    low, high = 0, len(text)
    while low < high:
        size = (low + high + 1) // 2
        candidate = text[-size:] if from_end else text[:size]
        if _serialized_text_size(candidate) <= limit:
            low = size
        else:
            high = size - 1
    return text[-low:] if from_end and low else text[:low]


def bounded_text(raw: bytes, limit: int = MAX_LOG_BYTES) -> tuple[str, bool]:
    decoded = raw.decode("utf-8", errors="replace")
    if _serialized_text_size(decoded) <= limit:
        return decoded, False
    marker = _fit_serialized_text(
        "\n...[output truncated by installed lifecycle pilot]...\n",
        limit,
    )
    budget = max(0, limit - _serialized_text_size(marker))
    prefix = _fit_serialized_text(decoded, budget // 2)
    suffix_source = decoded[len(prefix):]
    remaining = budget - _serialized_text_size(prefix)
    suffix = _fit_serialized_text(suffix_source, remaining, from_end=True)
    return prefix + marker + suffix, True


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalized_digest(value: str) -> str:
    match = SHA256_RE.fullmatch(value)
    if not match:
        raise PilotFailure("invalid_input", "disk_sha256 must be a SHA-256 digest")
    return match.group(1)


def requested_disk_digest(value: str) -> str:
    """Normalize a valid digest for evidence; retain an invalid one verbatim for preflight to reject."""
    match = SHA256_RE.fullmatch(value)
    return f"sha256:{match.group(1)}" if match else value


def validate_static(config: PilotConfig) -> None:
    if not config.confirmed:
        raise PilotFailure(
            "safety_confirmation_missing",
            "refusing to run without --confirm-disposable-vm",
        )
    if {
        "variant": config.variant,
        "flavor": config.flavor,
        "platform": config.platform,
    } != TARGET:
        raise PilotFailure(
            "wrong_target",
            "pilot is restricted to skipjack/gnome on linux/amd64",
        )
    match_a = IMAGE_RE.fullmatch(config.image_a)
    match_b = IMAGE_RE.fullmatch(config.image_b)
    if not match_a or not match_b:
        raise PilotFailure(
            "missing_identity",
            "image A and B must be immutable ghcr.io/tuna-os/skipjack@sha256 references",
        )
    if match_a.group(1) == match_b.group(1):
        raise PilotFailure("identical_images", "image A and B digests must differ")
    normalized_digest(config.disk_sha256)
    if not RUN_ID_RE.fullmatch(config.source_run_id):
        raise PilotFailure(
            "missing_identity",
            "source_run_id must be a numeric run ID with optional /attempt",
        )
    for name, value in (
        ("source_head_sha", config.source_head_sha),
        ("harness_sha", config.harness_sha),
    ):
        if not GIT_SHA_RE.fullmatch(value):
            raise PilotFailure("missing_identity", f"{name} must be a full Git SHA")
    if not SSH_USER_RE.fullmatch(config.ssh_user):
        raise PilotFailure("invalid_input", "ssh_user is not a valid local account name")
    if config.ssh_port < 1024 or config.ssh_port > 65535:
        raise PilotFailure("invalid_input", "ssh_port must be between 1024 and 65535")
    for name, value in (
        ("command_timeout", config.command_timeout),
        ("boot_timeout", config.boot_timeout),
        ("reboot_timeout", config.reboot_timeout),
        ("memory_mib", config.memory_mib),
        ("cpus", config.cpus),
    ):
        if value <= 0:
            raise PilotFailure("invalid_input", f"{name} must be positive")


class CommandRunner:
    def __init__(self, events: list[dict[str, Any]]):
        self.events = events

    def run(
        self,
        argv: list[str],
        *,
        timeout: int,
        check: bool = True,
        event_name: str | None = None,
    ) -> CommandResult:
        started = time.monotonic()
        with tempfile.TemporaryFile() as stdout_file, tempfile.TemporaryFile() as stderr_file:
            try:
                completed = subprocess.run(
                    argv,
                    stdin=subprocess.DEVNULL,
                    stdout=stdout_file,
                    stderr=stderr_file,
                    check=False,
                    timeout=timeout,
                )
                returncode = completed.returncode
                timed_out = False
            except subprocess.TimeoutExpired:
                returncode = 124
                timed_out = True
            stdout_file.seek(0)
            stderr_file.seek(0)
            stdout, stdout_truncated = bounded_text(stdout_file.read())
            stderr, stderr_truncated = bounded_text(stderr_file.read())

        event = {
            "name": event_name or Path(argv[0]).name,
            "argv": argv,
            "returncode": returncode,
            "duration_seconds": round(time.monotonic() - started, 3),
            "stdout": stdout,
            "stderr": stderr,
            "stdout_truncated": stdout_truncated,
            "stderr_truncated": stderr_truncated,
        }
        self.events.append(event)
        if timed_out:
            raise PilotFailure("timeout", f"command timed out: {event['name']}")
        if check and returncode != 0:
            detail = stderr.strip() or stdout.strip() or f"exit {returncode}"
            raise PilotFailure("command_failed", f"{event['name']} failed: {detail}")
        return CommandResult(returncode, stdout, stderr)


class LocalQemuBackend:
    QEMU_CANDIDATES = (
        "/usr/libexec/qemu-kvm",
        "/usr/bin/qemu-kvm",
        "/usr/bin/qemu-system-x86_64",
        "/home/linuxbrew/.linuxbrew/bin/qemu-system-x86_64",
    )
    UEFI_CODE_CANDIDATES = (
        "/usr/share/OVMF/OVMF_CODE_4M.fd",
        "/usr/share/OVMF/OVMF_CODE.fd",
        "/usr/share/edk2/ovmf/OVMF_CODE.fd",
        "/usr/share/edk2-ovmf/x64/OVMF_CODE.fd",
        "/usr/share/ovmf/OVMF.fd",
        "/home/linuxbrew/.linuxbrew/share/qemu/edk2-x86_64-code.fd",
    )
    UEFI_VARS_CANDIDATES = (
        "/usr/share/OVMF/OVMF_VARS_4M.fd",
        "/usr/share/OVMF/OVMF_VARS.fd",
        "/usr/share/edk2/ovmf/OVMF_VARS.fd",
        "/usr/share/edk2-ovmf/x64/OVMF_VARS.fd",
        "/home/linuxbrew/.linuxbrew/share/qemu/edk2-x86_64-vars.fd",
    )

    def __init__(self, config: PilotConfig, command_events: list[dict[str, Any]]):
        self.config = config
        self.events = command_events
        self.runner = CommandRunner(command_events)
        self.qemu_bin: str | None = None
        self.uefi_code: Path | None = None
        self.uefi_vars_source: Path | None = None
        self.overlay = config.output_dir / "disposable.qcow2"
        self.uefi_vars = config.output_dir / "UEFI_VARS.fd"
        self.qemu_process: subprocess.Popen[bytes] | None = None
        self.qemu_thread: threading.Thread | None = None
        self.qemu_log = bytearray()
        self.qemu_log_lock = threading.Lock()
        self.qemu_log_truncated = False
        self.qemu_started = 0.0
        self.created_paths: set[Path] = set()
        self.qemu_event: dict[str, Any] | None = None

    def _binary(self, name: str) -> str:
        value = shutil.which(name)
        if not value:
            raise PilotFailure("missing_dependency", f"required command not found: {name}")
        return value

    def _first_file(self, candidates: tuple[str, ...]) -> Path | None:
        for candidate in candidates:
            path = Path(candidate)
            if path.is_file():
                return path
        return None

    def _inspect_image(self, reference: str) -> dict[str, Any]:
        result = self.runner.run(
            [
                self._binary("skopeo"),
                "inspect",
                "--override-os",
                "linux",
                "--override-arch",
                "amd64",
                f"docker://{reference}",
            ],
            timeout=self.config.command_timeout,
            event_name="inspect_image",
        )
        try:
            document = json.loads(result.stdout)
        except json.JSONDecodeError as error:
            raise PilotFailure("missing_identity", f"invalid skopeo identity: {error}") from error
        expected_digest = reference.rsplit("@", 1)[1]
        if document.get("Digest") != expected_digest:
            raise PilotFailure(
                "missing_identity",
                f"resolved linux/amd64 digest {document.get('Digest')!r} does not match "
                f"{expected_digest}; the pilot requires the linux/amd64 image manifest "
                "digest, not an index or manifest-list digest",
            )
        os_name = document.get("Os")
        architecture = document.get("Architecture")
        if not isinstance(os_name, str) or not isinstance(architecture, str):
            raise PilotFailure("missing_identity", f"{reference} lacks OS/architecture identity")
        if architecture != "amd64" or os_name != "linux":
            raise PilotFailure(
                "wrong_architecture",
                f"{reference} resolved as {os_name}/{architecture}",
            )
        labels = document.get("Labels") or {}
        if labels.get("org.opencontainers.image.title") != "TunaOS skipjack (gnome)":
            raise PilotFailure(
                "missing_identity",
                f"{reference} is not labeled as the Skipjack GNOME target",
            )
        if labels.get("containers.bootc") != "1" and labels.get("ostree.bootable") != "1":
            raise PilotFailure("incompatible_image", f"{reference} lacks a bootc image label")
        return {
            "reference": reference,
            "digest": expected_digest,
            "name": document.get("Name"),
            "os": os_name,
            "architecture": architecture,
            "title": labels["org.opencontainers.image.title"],
            "revision": labels.get("org.opencontainers.image.version"),
            "bootc_label": labels.get("containers.bootc"),
            "ostree_bootable_label": labels.get("ostree.bootable"),
        }

    def preflight(self) -> dict[str, Any]:
        configured_disk = self.config.disk
        disk = configured_disk.resolve()
        if configured_disk.is_symlink() or not disk.is_file():
            raise PilotFailure("unsafe_disk", "source disk must be a regular, non-symlink file")
        if disk.suffix != ".qcow2":
            raise PilotFailure("unsafe_disk", "source disk must have a .qcow2 suffix")
        configured_key = self.config.ssh_key
        key = configured_key.resolve()
        if configured_key.is_symlink() or not key.is_file():
            raise PilotFailure("missing_identity", "SSH key must be a regular, non-symlink file")
        for output_path in (self.overlay, self.uefi_vars):
            if output_path.exists():
                raise PilotFailure(
                    "unsafe_disk",
                    f"refusing to overwrite existing pilot state: {output_path}",
                )
        actual_disk_digest = file_sha256(disk)
        if actual_disk_digest != normalized_digest(self.config.disk_sha256):
            raise PilotFailure("disk_digest_mismatch", "source disk SHA-256 does not match")

        qemu_img = self._binary("qemu-img")
        disk_info_result = self.runner.run(
            [qemu_img, "info", "--output=json", str(disk)],
            timeout=self.config.command_timeout,
            event_name="inspect_disk",
        )
        try:
            disk_info = json.loads(disk_info_result.stdout)
        except json.JSONDecodeError as error:
            raise PilotFailure("unsafe_disk", f"invalid qemu-img output: {error}") from error
        if disk_info.get("format") != "qcow2":
            raise PilotFailure("unsafe_disk", "source disk is not qcow2")

        self._binary("ssh")
        self.qemu_bin = next(
            (candidate for candidate in self.QEMU_CANDIDATES if os.access(candidate, os.X_OK)),
            None,
        )
        if not self.qemu_bin:
            raise PilotFailure("missing_dependency", "qemu-system-x86_64 not found")
        self.uefi_code = self._first_file(self.UEFI_CODE_CANDIDATES)
        self.uefi_vars_source = self._first_file(self.UEFI_VARS_CANDIDATES)
        if not self.uefi_code or not self.uefi_vars_source:
            raise PilotFailure("missing_dependency", "OVMF code and variables firmware are required")
        with socket.socket() as probe:
            try:
                probe.bind(("127.0.0.1", self.config.ssh_port))
            except OSError as error:
                raise PilotFailure("port_unavailable", str(error)) from error

        return {
            "disk": {
                "path": str(disk),
                "sha256": f"sha256:{actual_disk_digest}",
                "format": disk_info["format"],
                "virtual_size": disk_info.get("virtual-size"),
            },
            "images": {
                "a": self._inspect_image(self.config.image_a),
                "b": self._inspect_image(self.config.image_b),
            },
            "qemu": self.qemu_bin,
            "uefi_code": str(self.uefi_code),
            "installation_media_attached": False,
            "host_block_device_targeted": False,
        }

    def prepare_disk(self) -> dict[str, Any]:
        if not self.qemu_bin or not self.uefi_code or not self.uefi_vars_source:
            raise PilotFailure("internal_error", "preflight did not establish QEMU prerequisites")
        if self.config.output_dir.is_symlink():
            raise PilotFailure("unsafe_disk", "refusing a symlink output directory")
        self.config.output_dir.mkdir(parents=True, exist_ok=True)
        self.created_paths.add(self.overlay)
        self.runner.run(
            [
                self._binary("qemu-img"),
                "create",
                "-q",
                "-f",
                "qcow2",
                "-F",
                "qcow2",
                "-b",
                str(self.config.disk.resolve()),
                str(self.overlay),
            ],
            timeout=self.config.command_timeout,
            event_name="create_disposable_overlay",
        )
        self.created_paths.add(self.uefi_vars)
        shutil.copyfile(self.uefi_vars_source, self.uefi_vars)
        return {
            "overlay": str(self.overlay),
            "backing_disk_unchanged": True,
            "installation_media_attached": False,
        }

    def _drain_qemu(self) -> None:
        assert self.qemu_process is not None and self.qemu_process.stdout is not None
        while chunk := self.qemu_process.stdout.read(4096):
            with self.qemu_log_lock:
                remaining = MAX_LOG_BYTES - len(self.qemu_log)
                if remaining > 0:
                    self.qemu_log.extend(chunk[:remaining])
                if len(chunk) > remaining:
                    self.qemu_log_truncated = True

    def start_vm(self) -> None:
        assert self.qemu_bin and self.uefi_code
        accel = "kvm" if Path("/dev/kvm").exists() and os.access("/dev/kvm", os.R_OK | os.W_OK) else "tcg"
        argv = [
            self.qemu_bin,
            "-machine",
            f"q35,accel={accel}",
            "-cpu",
            "host" if accel == "kvm" else "max",
            "-m",
            str(self.config.memory_mib),
            "-smp",
            str(self.config.cpus),
            "-drive",
            f"if=pflash,format=raw,readonly=on,file={self.uefi_code}",
            "-drive",
            f"if=pflash,format=raw,file={self.uefi_vars}",
            "-drive",
            f"file={self.overlay},if=virtio,format=qcow2",
            "-netdev",
            f"user,id=net0,hostfwd=tcp:127.0.0.1:{self.config.ssh_port}-:22",
            "-device",
            "virtio-net-pci,netdev=net0",
            "-display",
            "none",
            "-monitor",
            "none",
            "-serial",
            "stdio",
        ]
        self.qemu_started = time.monotonic()
        self.qemu_process = subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        self.qemu_thread = threading.Thread(target=self._drain_qemu, daemon=True)
        self.qemu_thread.start()
        self.qemu_event = {
            "name": "start_qemu",
            "argv": argv,
            "returncode": None,
            "duration_seconds": 0,
            "stdout": "",
            "stderr": "",
            "stdout_truncated": False,
            "stderr_truncated": False,
        }
        self.events.append(self.qemu_event)

    def _ssh_argv(self, command: str) -> list[str]:
        return [
            self._binary("ssh"),
            "-F",
            "/dev/null",
            "-i",
            str(self.config.ssh_key.resolve()),
            "-p",
            str(self.config.ssh_port),
            "-o",
            "BatchMode=yes",
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            "UserKnownHostsFile=/dev/null",
            "-o",
            "ConnectTimeout=5",
            f"{self.config.ssh_user}@127.0.0.1",
            command,
        ]

    def guest(
        self,
        command: str,
        *,
        check: bool = True,
        timeout: int | None = None,
        event_name: str = "guest_command",
    ) -> CommandResult:
        return self.runner.run(
            self._ssh_argv(command),
            timeout=timeout or self.config.command_timeout,
            check=check,
            event_name=event_name,
        )

    def _ssh_ready(self, timeout: float) -> bool:
        probe_timeout = max(1, min(10, int(timeout)))
        result = self.guest("true", check=False, timeout=probe_timeout, event_name="ssh_probe")
        return result.returncode == 0

    def wait_for_ssh(self, timeout: int) -> None:
        deadline = time.monotonic() + timeout
        while (remaining := deadline - time.monotonic()) > 0:
            if self.qemu_process and self.qemu_process.poll() is not None:
                raise PilotFailure("vm_exited", "QEMU exited before SSH became ready")
            try:
                if self._ssh_ready(remaining):
                    return
            except PilotFailure as error:
                if error.category != "timeout":
                    raise
            time.sleep(max(0.0, min(5.0, deadline - time.monotonic())))
        raise PilotFailure("timeout", "guest SSH did not become ready")

    def reboot(self) -> None:
        self.guest("systemctl reboot", check=False, timeout=30, event_name="guest_reboot")
        down_deadline = time.monotonic() + 90
        while (remaining := down_deadline - time.monotonic()) > 0:
            try:
                if not self._ssh_ready(remaining):
                    break
            except PilotFailure as error:
                if error.category != "timeout":
                    raise
                break
            time.sleep(max(0.0, min(2.0, down_deadline - time.monotonic())))
        else:
            raise PilotFailure("timeout", "guest never disconnected for reboot")
        self.wait_for_ssh(self.config.reboot_timeout)

    def _status(self) -> dict[str, Any]:
        result = self.guest("bootc status --json", event_name="bootc_status")
        try:
            status = json.loads(result.stdout)
        except json.JSONDecodeError as error:
            raise PilotFailure("missing_identity", f"bootc status is not JSON: {error}") from error
        if not isinstance(status, dict):
            raise PilotFailure("missing_identity", "bootc status has no object identity")
        return status

    @staticmethod
    def _booted_reference(status: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
        try:
            booted = status["status"]["booted"]
            image = booted["image"]["image"]
            reference = image["image"]
            transport = image["transport"]
        except (KeyError, TypeError) as error:
            raise PilotFailure("missing_identity", "bootc status lacks booted image identity") from error
        if not isinstance(reference, str) or not isinstance(transport, str):
            raise PilotFailure("missing_identity", "bootc status booted identity is not textual")
        return reference, transport, booted

    @staticmethod
    def _staged_reference(status: dict[str, Any]) -> tuple[str, str]:
        try:
            image = status["status"]["staged"]["image"]["image"]
            reference = image["image"]
            transport = image["transport"]
        except (KeyError, TypeError) as error:
            raise PilotFailure("missing_identity", "bootc status lacks staged image identity") from error
        if not isinstance(reference, str) or not isinstance(transport, str):
            raise PilotFailure("missing_identity", "bootc status staged identity is not textual")
        return reference, transport

    def verify_boot(self, expected_reference: str) -> dict[str, Any]:
        status = self._status()
        reference, transport, booted = self._booted_reference(status)
        if reference != expected_reference or transport != "registry":
            raise PilotFailure(
                "wrong_deployment",
                f"expected registry image {expected_reference}, booted {transport}:{reference}",
            )
        arch = self.guest("uname -m", event_name="guest_architecture").stdout.strip()
        if arch != "x86_64":
            raise PilotFailure("wrong_architecture", f"guest architecture is {arch!r}")
        identity_command = (
            "set -eu; . /etc/os-release; "
            "printf '%s\\n%s\\n%s\\n' \"${VARIANT_ID:-}\" "
            "\"${IMAGE_ID:-}\" \"${IMAGE_VERSION:-}\""
        )
        identity_lines = self.guest(identity_command, event_name="guest_os_identity").stdout.splitlines()
        identity_lines += [""] * (3 - len(identity_lines))
        variant_id, image_id, image_version = identity_lines[:3]
        if variant_id != "skipjack" or image_id != "skipjack":
            raise PilotFailure(
                "wrong_target",
                f"guest identity is VARIANT_ID={variant_id!r} IMAGE_ID={image_id!r}",
            )
        if not image_version.startswith("gnome-"):
            raise PilotFailure("wrong_target", f"guest flavor identity is {image_version!r}")
        contract = self.guest(
            "/usr/libexec/tunaos/verify-desktop-experience gnome --runtime",
            event_name="desktop_contract",
        )
        return {
            "reference": reference,
            "transport": transport,
            "booted_deployment": booted,
            "architecture": arch,
            "variant_id": variant_id,
            "image_id": image_id,
            "image_version": image_version,
            "desktop_contract": {
                "command": "/usr/libexec/tunaos/verify-desktop-experience gnome --runtime",
                "outcome": "passed",
                "stdout": contract.stdout,
            },
        }

    def stage_update(self) -> dict[str, Any]:
        self.guest(
            f"bootc switch --retain {self.config.image_b}",
            event_name="bootc_switch_b",
        )
        status = self._status()
        reference, transport = self._staged_reference(status)
        if reference != self.config.image_b or transport != "registry":
            raise PilotFailure(
                "wrong_deployment",
                f"bootc staged {transport}:{reference}, expected registry:{self.config.image_b}",
            )
        return {"command": "bootc switch --retain", "staged_reference": self.config.image_b}

    def stage_rollback(self) -> dict[str, Any]:
        self.guest("bootc rollback", event_name="bootc_rollback_a")
        status = self._status()
        reference, transport = self._staged_reference(status)
        if reference != self.config.image_a or transport != "registry":
            raise PilotFailure(
                "wrong_deployment",
                f"bootc staged {transport}:{reference}, expected registry:{self.config.image_a}",
            )
        return {"command": "bootc rollback", "staged_reference": self.config.image_a}

    def cleanup(self) -> dict[str, Any]:
        removed: list[str] = []
        errors: list[str] = []
        if self.qemu_process is not None:
            if self.qemu_process.poll() is None:
                self.qemu_process.terminate()
                try:
                    self.qemu_process.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    self.qemu_process.kill()
                    try:
                        self.qemu_process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        errors.append("QEMU did not exit after SIGKILL")
            if self.qemu_thread:
                self.qemu_thread.join(timeout=5)
                if self.qemu_thread.is_alive():
                    errors.append("QEMU log drain did not stop; serial log may be incomplete")
            with self.qemu_log_lock:
                raw_log = bytes(self.qemu_log)
                log_truncated = self.qemu_log_truncated
            output, truncated = bounded_text(raw_log)
            if self.qemu_event is not None:
                self.qemu_event.update(
                    returncode=self.qemu_process.returncode,
                    duration_seconds=round(time.monotonic() - self.qemu_started, 3),
                    stdout=output,
                    stdout_truncated=truncated or log_truncated,
                )
        if not self.config.keep_disk:
            for path in sorted(self.created_paths):
                try:
                    path.unlink(missing_ok=True)
                    removed.append(str(path))
                except OSError as error:
                    errors.append(f"could not remove {path}: {error}")
        if errors:
            raise PilotFailure("cleanup_failed", "; ".join(errors))
        return {"removed": removed, "disposable_disk_retained": self.config.keep_disk}


def new_evidence(config: PilotConfig) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "pilot": {
            "issue": "tuna-os/tunaos#3798",
            "target": {
                "variant": config.variant,
                "flavor": config.flavor,
                "platform": config.platform,
            },
            "scope": "installed_update_and_rollback",
            "rebase": "not_tested",
        },
        "provenance": {
            "source_run_id": config.source_run_id,
            "source_head_sha": config.source_head_sha,
            "harness_sha": config.harness_sha,
        },
        "inputs": {
            "source_disk": {
                "path": str(config.disk),
                "expected_sha256": requested_disk_digest(config.disk_sha256),
            },
            "image_a": config.image_a,
            "image_b": config.image_b,
        },
        "safety": {
            "disposable_overlay_only": True,
            "installation_media_attached": False,
            "host_root_or_block_device_targeted": False,
        },
        "started_at": utc_now(),
        "finished_at": None,
        "stages": [
            {"id": stage_id, "required": True, "outcome": "pending", "details": {}}
            for stage_id in STAGE_IDS
        ],
        "commands": [],
        "outcomes": {"cold": "pending", "warm": "pending", "recovery": "pending"},
        "result": {
            "verdict": "incomplete",
            "runtime_acceptance": "incomplete",
            "first_failure": None,
        },
    }

def require_boot_proof(details: Any, expected_reference: str) -> dict[str, Any]:
    """Reject boot-stage results that are not an installed deployment booted from the image.

    Container or registry inspection carries no booted deployment and no runtime
    desktop contract, so it can never satisfy a boot stage.
    """
    if (
        not isinstance(details, dict)
        or details.get("reference") != expected_reference
        or details.get("transport") != "registry"
        or not isinstance(details.get("booted_deployment"), dict)
        or not details["booted_deployment"]
        or not isinstance(details.get("desktop_contract"), dict)
        or details["desktop_contract"].get("outcome") != "passed"
    ):
        raise PilotFailure(
            "missing_boot_proof",
            f"boot stage lacks booted installed-deployment proof for {expected_reference}",
        )
    return details


def require_staged(details: Any, expected_reference: str) -> dict[str, Any]:
    if not isinstance(details, dict) or details.get("staged_reference") != expected_reference:
        raise PilotFailure(
            "wrong_deployment",
            f"staging did not report {expected_reference} as the staged deployment",
        )
    return details



def execute_pilot(
    config: PilotConfig,
    backend_factory: Callable[[PilotConfig, list[dict[str, Any]]], Any] = LocalQemuBackend,
) -> tuple[dict[str, Any], bool]:
    evidence = new_evidence(config)
    stages = {stage["id"]: stage for stage in evidence["stages"]}
    backend = backend_factory(config, evidence["commands"])
    first_failure: dict[str, str] | None = None

    def run_stage(stage_id: str, action: Callable[[], dict[str, Any]]) -> bool:
        nonlocal first_failure
        stage = stages[stage_id]
        stage["started_at"] = utc_now()
        try:
            stage["details"] = action()
            stage["outcome"] = "passed"
            return True
        except PilotFailure as error:
            stage["outcome"] = "failed"
            stage["details"] = {"category": error.category, "message": str(error)}
            if first_failure is None:
                first_failure = {
                    "stage": stage_id,
                    "category": error.category,
                    "message": str(error),
                }
            return False
        except Exception as error:  # Retain unexpected failures without losing cleanup.
            stage["outcome"] = "failed"
            stage["details"] = {"category": "internal_error", "message": str(error)}
            if first_failure is None:
                first_failure = {
                    "stage": stage_id,
                    "category": "internal_error",
                    "message": str(error),
                }
            return False
        finally:
            stage["finished_at"] = utc_now()

    def preflight() -> dict[str, Any]:
        validate_static(config)
        return backend.preflight()

    def cold_boot_a() -> dict[str, Any]:
        backend.start_vm()
        backend.wait_for_ssh(config.boot_timeout)
        return require_boot_proof(backend.verify_boot(config.image_a), config.image_a)

    def stage_update_b() -> dict[str, Any]:
        return require_staged(backend.stage_update(), config.image_b)

    def warm_boot_b() -> dict[str, Any]:
        backend.reboot()
        return require_boot_proof(backend.verify_boot(config.image_b), config.image_b)

    def stage_rollback_a() -> dict[str, Any]:
        return require_staged(backend.stage_rollback(), config.image_a)

    def recovery_boot_a() -> dict[str, Any]:
        backend.reboot()
        return require_boot_proof(backend.verify_boot(config.image_a), config.image_a)

    functional_stages: list[tuple[str, Callable[[], dict[str, Any]]]] = [
        ("preflight", preflight),
        ("prepare_disk", backend.prepare_disk),
        ("cold_boot_a", cold_boot_a),
        ("stage_update_b", stage_update_b),
        ("warm_boot_b", warm_boot_b),
        ("stage_rollback_a", stage_rollback_a),
        ("recovery_boot_a", recovery_boot_a),
    ]

    blocked_by: str | None = None
    for stage_id, action in functional_stages:
        if blocked_by:
            stages[stage_id]["outcome"] = "skipped"
            stages[stage_id]["details"] = {"reason": f"blocked_by:{blocked_by}"}
            continue
        if not run_stage(stage_id, action):
            blocked_by = stage_id

    run_stage("cleanup", backend.cleanup)
    if stages["cleanup"]["outcome"] == "failed" and first_failure is None:
        details = stages["cleanup"]["details"]
        first_failure = {
            "stage": "cleanup",
            "category": details["category"],
            "message": details["message"],
        }

    evidence["outcomes"] = {
        "cold": stages["cold_boot_a"]["outcome"],
        "warm": stages["warm_boot_b"]["outcome"],
        "recovery": stages["recovery_boot_a"]["outcome"],
    }
    passed = [stage["id"] for stage in evidence["stages"]] == list(STAGE_IDS) and all(
        stage["outcome"] == "passed" for stage in evidence["stages"]
    )
    evidence["result"] = {
        "verdict": "passed" if passed else "failed",
        "runtime_acceptance": "passed" if passed else "failed",
        "first_failure": first_failure,
    }
    evidence["finished_at"] = utc_now()
    return evidence, passed


def parse_args(argv: list[str] | None = None) -> PilotConfig:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--disk", required=True, type=Path)
    parser.add_argument("--disk-sha256", required=True)
    parser.add_argument("--image-a", required=True)
    parser.add_argument("--image-b", required=True)
    parser.add_argument("--variant", required=True)
    parser.add_argument("--flavor", required=True)
    parser.add_argument("--platform", required=True)
    parser.add_argument("--ssh-key", required=True, type=Path)
    parser.add_argument("--ssh-user", default="root")
    parser.add_argument("--ssh-port", type=int, default=2222)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--source-run-id", required=True)
    parser.add_argument("--source-head-sha", required=True)
    parser.add_argument("--harness-sha", required=True)
    parser.add_argument("--command-timeout", type=int, default=600)
    parser.add_argument("--boot-timeout", type=int, default=900)
    parser.add_argument("--reboot-timeout", type=int, default=900)
    parser.add_argument("--memory-mib", type=int, default=4096)
    parser.add_argument("--cpus", type=int, default=4)
    parser.add_argument("--keep-disk", action="store_true")
    parser.add_argument("--confirm-disposable-vm", action="store_true")
    args = parser.parse_args(argv)
    return PilotConfig(
        disk=args.disk,
        disk_sha256=args.disk_sha256,
        image_a=args.image_a,
        image_b=args.image_b,
        ssh_key=args.ssh_key,
        ssh_user=args.ssh_user,
        ssh_port=args.ssh_port,
        output_dir=args.output_dir,
        source_run_id=args.source_run_id,
        source_head_sha=args.source_head_sha,
        harness_sha=args.harness_sha,
        command_timeout=args.command_timeout,
        boot_timeout=args.boot_timeout,
        reboot_timeout=args.reboot_timeout,
        memory_mib=args.memory_mib,
        cpus=args.cpus,
        keep_disk=args.keep_disk,
        confirmed=args.confirm_disposable_vm,
        variant=args.variant,
        flavor=args.flavor,
        platform=args.platform,
    )


def main(argv: list[str] | None = None) -> int:
    config = parse_args(argv)
    if config.output_dir.is_symlink():
        raise SystemExit("refusing a symlink output directory")
    config.output_dir.mkdir(parents=True, exist_ok=True)
    evidence_path = config.output_dir / "installed-lifecycle-evidence.json"
    if evidence_path.exists():
        raise SystemExit(f"refusing to overwrite existing evidence: {evidence_path}")
    evidence, passed = execute_pilot(config)
    evidence_path.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"evidence: {evidence_path}")
    print(f"runtime acceptance: {evidence['result']['runtime_acceptance']}")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
