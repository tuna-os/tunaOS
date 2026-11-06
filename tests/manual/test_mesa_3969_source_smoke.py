#!/usr/bin/env python3
"""CI-only CLI checks: synthetic integrity and ownership, never runtime approval."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
HEAD = "a" * 40


def synthetic_bundle(inputs, producer):
    """Tiny non-RPM/non-OCI bytes; public armor is NOT a real signing key."""
    members = {
        "baseline.oci.tar": b"synthetic integrity fixture, not an OCI image\n",
        "public-key.asc": (
            b"-----BEGIN PGP PUBLIC KEY BLOCK-----\n"
            b"synthetic-not-a-key\n-----END PGP PUBLIC KEY BLOCK-----\n"
        ),
        "baseline-inventory.json": b"[]\n",
        "buildroot-inventory.json": b"[]\n",
        "buildroot-macros.txt": b"synthetic macros\n",
        "toolchain.txt": b"synthetic toolchain\n",
        "build-report.json": b'{"synthetic":true,"signature_verified":false}\n',
        "rpms/control/mesa-test.rpm": b"control fixture, not an RPM\n",
        "rpms/candidate/mesa-test.rpm": b"candidate fixture, not an RPM\n",
    }
    files = [
        {"path": name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
        for name, data in sorted(members.items())
    ]
    arms = {}
    for index, arm in enumerate(("control", "candidate"), start=1):
        path = f"rpms/{arm}/mesa-test.rpm"
        arms[arm] = {
            "buildroot_image_id": "sha256:" + "3" * 64,
            "generated_srpm_sha256": str(index) * 64,
            "packages": [{
                "name": "mesa-test", "epoch": 0, "version": "25.2.7",
                "release": "4.el10.alma.5", "arch": "x86_64",
                "source_rpm": inputs["source_rpm"],
                "header_sha256": str(index + 4) * 64,
                "path": path, "sha256": hashlib.sha256(members[path]).hexdigest(),
                "bytes": len(members[path]),
            }],
        }
    manifest = {
        "schema_version": 1, "kind": "mesa3969-inputs", "producer": dict(producer),
        "inputs": dict(inputs),
        "baseline": {
            "parent": inputs["baseline_parent"], "raw_image_id": "sha256:" + "1" * 64,
            "image_id": "sha256:" + "2" * 64,
            "image_tag": f"localhost/mesa3969-{producer['run_id']}-{producer['head_sha'][:8]}:labbase",
            "inventory": "baseline-inventory.json", "software_policy_sha256": "4" * 64,
        },
        "buildroot": {
            "image_id": "sha256:" + "3" * 64, "inventory": "buildroot-inventory.json",
            "macros": "buildroot-macros.txt", "toolchain": "toolchain.txt",
        },
        "signer": {"fingerprint": "A" * 40, "public_key": "public-key.asc"},
        "probe": {"helper_commit": inputs["helper_commit"], "source_sha256": "7" * 64,
                  "binary_sha256": "8" * 64},
        "arms": arms, "files": files,
    }
    return manifest, members


def write_archive(path, manifest, members, extra=()):
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest, allow_nan=False))
        for name, data in members.items():
            archive.writestr(name, data)
        for name, data in extra:
            archive.writestr(name, data)
    return path


def checked(condition, message):
    if not condition:
        raise RuntimeError(message)


def run_cli(args, env, cwd, *, refusal=False):
    result = subprocess.run(args, env=env, cwd=cwd, capture_output=True, text=True, timeout=30)
    if refusal:
        checked(result.returncode == 2, f"expected refusal from {args}: {result.stderr}")
    else:
        checked(result.returncode == 0, f"CLI failed {args}: {result.stderr}")
    return result


@unittest.skipUnless(os.environ.get("CI") == "true", "source CLI smoke runs in CI only")
def test_source_cli_safety():
    checked(os.environ.get("CI") == "true", "this source smoke is CI-only; no local execution")
    observations = []
    with tempfile.TemporaryDirectory(prefix="mesa3969-source-smoke-") as temporary:
        temporary = Path(temporary).resolve()
        runner = temporary / "runner"
        runner.mkdir(mode=0o700)
        tools = temporary / "tools"
        tools.mkdir()
        sentinel_log = temporary / "forbidden-tool.log"
        sentinel = tools / "forbidden"
        sentinel.write_text(
            '#!/bin/sh\nprintf "%s\\n" "$0" >> "$MESA_SMOKE_SENTINEL_LOG"\nexit 97\n',
            encoding="utf-8",
        )
        sentinel.chmod(0o700)
        # Only the interpreter and dirname are real. No ambient PATH escape.
        (tools / "python3").symlink_to(Path(sys.executable).resolve())
        dirname = shutil.which("dirname")
        checked(dirname is not None, "dirname is needed for the real guest entry")
        (tools / "dirname").symlink_to(Path(dirname).resolve())
        for name in (
            "git", "sudo", "podman", "docker", "buildah", "just", "rpm", "rpmbuild",
            "gpg", "gpg2", "dnf", "yum", "apt", "apt-get", "curl", "wget", "gh",
            "qemu-system-x86_64", "virt-install", "virsh", "corral", "systemctl",
            "unshare", "mount", "mkfs", "make", "gcc", "cc", "mkdir", "rm", "cp",
            "install", "tee",
        ):
            (tools / name).symlink_to(sentinel)
        # Construct, do not inherit: no GH_TOKEN/GITHUB_TOKEN, activation, SSH or cloud credentials.
        env = {
            "PATH": str(tools), "HOME": str(temporary), "TMPDIR": str(temporary),
            "RUNNER_TEMP": str(runner), "GITHUB_ACTIONS": "true",
            "GITHUB_SERVER_URL": "https://github.com", "GITHUB_API_URL": "https://api.github.com",
            "GITHUB_REPOSITORY": "tuna-os/tunaOS", "GITHUB_REPOSITORY_ID": "1029250013",
            "GITHUB_EVENT_NAME": "workflow_dispatch", "GITHUB_RUN_ID": "3969001",
            "GITHUB_RUN_ATTEMPT": "1", "GITHUB_SHA": HEAD, "REVIEWED_HEAD": HEAD,
            "LAB_CONFIRM": "RUN_MESA_3969_ONCE", "GITHUB_WORKSPACE": str(ROOT),
            "GITHUB_OUTPUT": str(temporary / "github-output"),
            "MESA_SMOKE_SENTINEL_LOG": str(sentinel_log),
        }
        core = [sys.executable, str(HERE / "mesa_3969.py")]
        inputs = json.loads(run_cli(core + ["inputs"], env, temporary).stdout)
        for script in ("mesa-3969-build.sh", "mesa-3969-guest.sh"):
            command = ["/bin/bash", str(HERE / script)]
            run_cli(command, env, temporary, refusal=True)
            checked(json.loads(run_cli(command + ["--plan"], env, temporary).stdout) == inputs,
                    f"{script} plan changed immutable inputs")
        for args in (
            ["admit"], ["producer"],
            ["fetch-inputs", "--artifact-id", "123", "--artifact-digest", "0" * 64,
             "--destination", str(runner / "unapproved")],
        ):
            run_cli(core + args, env, temporary, refusal=True)
        build_approved = dict(env, MESA_3969_APPROVED_HEAD=HEAD)
        run_cli(core + ["admit", "--runtime"], build_approved, temporary, refusal=True)
        local_refusal = subprocess.run(
            ["/bin/bash", str(HERE / "mesa-3969-build.sh"), "local-build",
             "--reviewed-head", HEAD, "--scratch-parent", str(runner),
             "--confirmation", "DO_NOT_BUILD"],
            env=env, cwd=temporary, capture_output=True, text=True, timeout=30,
        )
        checked(local_refusal.returncode == 1, "local build did not refuse its absent confirmation")
        checked(not list(runner.iterdir()), "unapproved entry created owned state")
        checked(not Path(env["GITHUB_OUTPUT"]).exists(), "unapproved entry wrote outputs")
        checked(not sentinel_log.exists(), "unapproved entry reached a forbidden tool")
        observations.append("default build, guest, admission, producer and fetch refused without activation; no tokens, owned state, outputs or forbidden tools")

        producer = {"repository_id": 1029250013, "repository": "tuna-os/tunaOS",
                    "head_sha": HEAD, "run_id": 3969001, "run_attempt": 1,
                    "workflow_id": 3969, "job_id": 701}
        manifest, members = synthetic_bundle(inputs, producer)
        good = write_archive(temporary / "integrity.zip", manifest, members)
        receipt = json.loads(run_cli(core + ["check-archive", "--archive", str(good)], env, temporary).stdout)
        checked(receipt == {"integrity": "verified", "authority": "not_evaluated", "files": 9},
                "integrity CLI misrepresented its authority")
        tampered = dict(members)
        tampered["baseline.oci.tar"] = b"X" * len(members["baseline.oci.tar"])
        bad = write_archive(temporary / "tampered.zip", manifest, tampered)
        run_cli(core + ["check-archive", "--archive", str(bad)], env, temporary, refusal=True)
        observations.append("tiny synthetic archive integrity accepted; equal-size tamper refused; authority not evaluated")

        # Local authority here is synthetic DATA, never an admitted build.
        local = {
            "schema_version": 1, "kind": "mesa3969-local-build",
            "operation_id": "c" * 32, "head_sha": HEAD,
            "owner_uid": os.geteuid(), "host": os.uname().nodename,
            "started_at": 1, "checkout": str(ROOT),
        }
        owner = temporary / "local-owner.json"
        owner.write_text(json.dumps(local), encoding="utf-8")
        local_transfer = temporary / "local-transfer"
        local_transfer.mkdir(mode=0o700)
        for name, data in members.items():
            path = local_transfer / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        local_manifest = dict(manifest, kind="mesa3969-local-inputs", local=local, files=[])
        local_manifest.pop("producer")
        local_manifest["baseline"] = dict(
            manifest["baseline"],
            image_tag=f"localhost/mesa3969-local-{local['operation_id']}-{HEAD[:8]}:baseline",
        )
        (local_transfer / "local-manifest.json").write_text(json.dumps(local_manifest), encoding="utf-8")
        sealed_local = json.loads(run_cli(
            core + ["seal-local-transfer", "--directory", str(local_transfer), "--owner", str(owner)],
            env, temporary,
        ).stdout)
        renamed = write_archive(temporary / "renamed-local.zip", sealed_local, members)
        run_cli(core + ["check-archive", "--archive", str(renamed)], env, temporary, refusal=True)
        observations.append("local-only metadata sealed through real CLI; renamed local manifest refused by hosted archive consumer; no local or CI build authority established")

        # Source-only CLI smoke stays in its isolated runner parent. The fixed
        # short runtime parent and real socket binds have dedicated regressions.
        owned = Path(run_cli(core + ["init-root", "--role", "build"], env, temporary).stdout.strip())
        checked(owned == runner / "mesa-3969-3969001-build", "unexpected owned root")
        checked(owned.stat().st_mode & 0o777 == 0o700, "owned root mode is not private")
        outside = temporary / "unrelated.txt"
        outside.write_text("preserve outside state\n", encoding="utf-8")
        for child in ("work", "transfer", "evidence"):
            (owned / child).mkdir()
            (owned / child / "keep.txt").write_text(child, encoding="utf-8")
        (owned / "work" / "outside-link").symlink_to(outside)
        run_cli(core + ["cleanup-child", "--role", "build", "--child", "work"], env, temporary)
        checked(not (owned / "work").exists(), "private work survived cleanup")
        checked((owned / "transfer/keep.txt").read_text() == "transfer", "cleanup removed transfer")
        checked((owned / "evidence/keep.txt").read_text() == "evidence", "cleanup removed evidence")
        marker = owned / ".mesa3969-owned.json"
        original = marker.read_bytes()
        altered = json.loads(original)
        altered["head_sha"] = "b" * 40
        marker.write_text(json.dumps(altered), encoding="utf-8")
        run_cli(core + ["cleanup", "--role", "build"], env, temporary, refusal=True)
        checked(owned.exists(), "mismatched marker did not protect owned state")
        marker.write_bytes(original)
        run_cli(core + ["cleanup", "--role", "build"], env, temporary)
        checked(not owned.exists(), "final cleanup retained owned root")
        checked(outside.read_text() == "preserve outside state\n", "cleanup touched unrelated state")
        checked(not sentinel_log.exists(), "source checks invoked a forbidden tool")
        observations.append("marker-bound child and final CLI cleanup preserved transfer/evidence until final cleanup and unrelated state throughout")
    print(json.dumps({
        "kind": "mesa3969-source-only-receipt", "status": "passed", "observations": observations,
        "synthetic_archive": "integrity_only_not_authenticated",
        "runtime_exercised": False, "keys_generated": False, "signatures_verified": False,
        "packages_built": False, "guests_started": False, "dispatch_performed": False,
        "unexercised": ["live GitHub authority", "native RPM/GPG signatures and builds", "OCI load",
                        "KVM guests", "GDM/Wayland/software renderer", "Mesa crash repair", "ISO/config qualification"],
    }, sort_keys=True))


if __name__ == "__main__":
    test_source_cli_safety()
