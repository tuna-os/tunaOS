"""Full-image evidence harness for tuna-os/tunaos#3802."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "qualify_image_packages", ROOT / "scripts/qualify-image-packages.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

ROUTE_VARIANTS = {
    "el10": "yellowfin",
    "ubuntu": "grouper",
    "debian": "flounder",
    "arch": "marlin",
    "opensuse": "sailfin",
    "gentoo": "guppy",
}
ROUTE_MANAGERS = {
    "el10": "dnf",
    "ubuntu": "apt",
    "debian": "apt",
    "arch": "pacman",
    "opensuse": "zypper",
    "gentoo": "emerge",
}
ROUTE_PACKAGES = {
    "el10": "tree",
    "ubuntu": "jq",
    "debian": "jq",
    "arch": "jq",
    "opensuse": "jq",
    "gentoo": "app-misc/jq",
}


def digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def image_id(reference):
    return digest(reference.encode())


def reference_for_id(value):
    for cell in QUALIFICATION_PLAN["cells"]:
        if cell["images"] is None:
            continue
        for record in cell["images"].values():
            if image_id(record["ref"]) == value:
                return record["ref"]
    raise AssertionError(value)


def plan(images=True):
    cells = []
    for route, variant in ROUTE_VARIANTS.items():
        records = None
        if images:
            records = {
                "stockBase": {"ref": f"localhost/stock-{variant}:base", "flavor": "base"},
                "modifiedBase": {"ref": f"localhost/modified-{variant}:base", "flavor": "base"},
                "modifiedDesktop": {
                    "ref": f"localhost/modified-{variant}:gnome",
                    "flavor": "gnome",
                },
            }
            if route == "el10":
                records["modifiedOverlay"] = {
                    "ref": f"localhost/modified-{variant}:gnome-hwe",
                    "flavor": "gnome-hwe",
                }
        raw = f"base-{route}".encode()
        cells.append({
            "route": route,
            "variant": variant,
            "package": ROUTE_PACKAGES[route],
            "baseImage": f"registry.example/{route}:base@{digest(raw)}",
            "images": records,
        })
    return {
        "schemaVersion": 1,
        "platform": "linux/amd64",
        "stockCommit": "1" * 40,
        "modifiedCommit": "2" * 40,
        "cells": cells,
    }


def test_plan_requires_all_six_routes_pinned_bases_and_overlay():
    valid = plan()
    assert MODULE.validate_plan(valid) == valid

    missing = copy.deepcopy(valid)
    missing["cells"].pop()
    with pytest.raises(MODULE.QualificationError, match="exactly six routes"):
        MODULE.validate_plan(missing)

    mutable = copy.deepcopy(valid)
    next(cell for cell in mutable["cells"] if cell["route"] == "el10")[
        "baseImage"
    ] = "registry.example/el10:latest"
    with pytest.raises(MODULE.QualificationError, match="digest-pinned"):
        MODULE.validate_plan(mutable)

    transported = copy.deepcopy(valid)
    el10 = next(cell for cell in transported["cells"] if cell["route"] == "el10")
    el10["baseImage"] = "docker://" + el10["baseImage"]
    with pytest.raises(MODULE.QualificationError, match="transport-less"):
        MODULE.validate_plan(transported)

    no_overlay = copy.deepcopy(valid)
    el10 = next(cell for cell in no_overlay["cells"] if cell["route"] == "el10")
    del el10["images"]["modifiedOverlay"]
    with pytest.raises(MODULE.QualificationError, match="invalid fields"):
        MODULE.validate_plan(no_overlay)


def test_adapter_rows_ignore_incidental_whitespace_and_indented_comments():
    assert MODULE.adapter_rows(
        b"  \n \t# generated adapter\n  guppy\temerge\tadd\tapp-misc/jq  \n"
    ) == [["guppy", "emerge", "add", "app-misc/jq"]]


def git(root, *args):
    return subprocess.check_output(["git", *args], cwd=root, text=True).strip()


def source_checkout(tmp_path, qualification_plan):
    root = tmp_path / "source"
    (root / "scripts").mkdir(parents=True)
    (root / "build_scripts/lib").mkdir(parents=True)
    (root / "scripts/config.py").write_text("raise SystemExit(0)\n")
    (root / "scripts/resolve-flavor.sh").write_text("#!/usr/bin/env bash\nexit 0\n")
    (root / "tunaos.toml").write_text("stock = true\n")
    (root / "build_scripts/lib/image-packages.tsv").write_text("# generated adapter\n")
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=root, check=True)
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "stock"], cwd=root, check=True)
    stock = git(root, "rev-parse", "HEAD")

    (root / "tunaos.toml").write_text("stock = false\n")
    rows = [
        f"{cell['variant']}\t{ROUTE_MANAGERS[cell['route']]}\tadd\t{cell['package']}"
        for cell in qualification_plan["cells"]
    ]
    (root / "build_scripts/lib/image-packages.tsv").write_text(
        "# generated adapter\n" + "\n".join(rows) + "\n"
    )
    subprocess.run(
        ["git", "add", "tunaos.toml", "build_scripts/lib/image-packages.tsv"],
        cwd=root,
        check=True,
    )
    subprocess.run(["git", "commit", "-q", "-m", "modified"], cwd=root, check=True)
    qualification_plan["stockCommit"] = stock
    qualification_plan["modifiedCommit"] = git(root, "rev-parse", "HEAD")
    return root


def test_source_identity_requires_one_config_and_generated_adapter_commit(tmp_path):
    qualification_plan = plan(images=False)
    root = source_checkout(tmp_path, qualification_plan)
    log_path = tmp_path / "source.log"
    with MODULE.CommandLog(log_path) as log:
        source = MODULE.validate_source(qualification_plan, root, log)

    assert source["stockCommit"] == qualification_plan["stockCommit"]
    assert source["modifiedCommit"] == qualification_plan["modifiedCommit"]
    assert source["managers"] == {
        variant: ROUTE_MANAGERS[route] for route, variant in ROUTE_VARIANTS.items()
    }

    linked = tmp_path / "linked-source"
    linked.symlink_to(root, target_is_directory=True)
    with MODULE.CommandLog(tmp_path / "symlink.log") as log:
        with pytest.raises(MODULE.QualificationError, match="real checkout"):
            MODULE.validate_source(qualification_plan, linked, log)

    (root / "untracked").write_text("not part of the build\n")
    with MODULE.CommandLog(tmp_path / "dirty.log") as log:
        with pytest.raises(MODULE.QualificationError, match="must be clean"):
            MODULE.validate_source(qualification_plan, root, log)


def test_command_log_bounds_both_output_streams(tmp_path):
    size = MODULE.COMMAND_OUTPUT_LIMIT + 4096
    command = [
        sys.executable,
        "-c",
        f"import sys; sys.stdout.buffer.write(b'x' * {size}); "
        f"sys.stderr.buffer.write(b'y' * {size})",
    ]
    with MODULE.CommandLog(tmp_path / "command.log") as log:
        result = log.run(command)

    assert result.returncode == 0
    assert result.stdout.endswith(MODULE.TRUNCATION_MARKER)
    assert result.stderr.endswith(MODULE.TRUNCATION_MARKER)
    assert len(result.stdout) == MODULE.COMMAND_OUTPUT_LIMIT + len(MODULE.TRUNCATION_MARKER)
    assert len(result.stderr) == MODULE.COMMAND_OUTPUT_LIMIT + len(MODULE.TRUNCATION_MARKER)


class FakeLog:
    fail_ref = None
    mismatched_platform_ref = None
    bad_apt_status_ref = None
    wrong_parent_ref = None
    def __init__(self, path=None):
        self.path = path

    def __enter__(self):
        if self.path is not None:
            self.path.write_bytes(b"")
        return self

    def __exit__(self, *_args):
        return None

    def run(self, args, *, cwd=None):
        del cwd
        if args[:2] == ["bash", "scripts/resolve-flavor.sh"]:
            variant, flavor = args[2:]
            route = next(key for key, value in ROUTE_VARIANTS.items() if value == variant)
            if flavor == "gnome-hwe":
                values = {
                    "CONTAINERFILE": "Containerfile.overlay",
                    "DESKTOP_FLAVOR": "desktop",
                    "PARENT_FLAVOR": "gnome",
                }
            else:
                if flavor == "base":
                    target = "base" if route == "ubuntu" else "base-no-de"
                else:
                    target = flavor
                values = {
                    "CONTAINERFILE": MODULE.ROUTES[route],
                    "DESKTOP_FLAVOR": target,
                    "PARENT_FLAVOR": "",
                }
            output = "".join(
                f"{key}={json.dumps(value)}\n" for key, value in values.items()
            ).encode()
            return subprocess.CompletedProcess(args, 0, output, b"")
        if args[:3] == ["podman", "image", "inspect"]:
            reference = args[3]
            parent = ""
            if reference.endswith(":gnome-hwe"):
                parent = image_id(reference.removesuffix("gnome-hwe") + "gnome")
            if reference == self.wrong_parent_ref:
                parent = digest(b"unqualified-parent")
            output = json.dumps([{"Id": image_id(reference), "Parent": parent}]).encode()
            return subprocess.CompletedProcess(args, 0, output, b"")
        if args[:3] == ["skopeo", "inspect", "--raw"]:
            ref = args[3]
            if ref.startswith("docker://"):
                route = ref.split("registry.example/", 1)[1].split(":", 1)[0]
                output = f"base-{route}".encode()
            else:
                output = f"manifest-{ref}".encode()
            return subprocess.CompletedProcess(args, 0, output, b"")
        if args[:3] == ["skopeo", "inspect", "--config"]:
            reference = args[3].removeprefix("containers-storage:")
            architecture = "arm64" if reference == self.mismatched_platform_ref else "amd64"
            output = json.dumps({"os": "linux", "architecture": architecture}).encode()
            return subprocess.CompletedProcess(args, 0, output, b"")
        if args[:2] == ["podman", "run"]:
            entrypoint_index = args.index("--entrypoint")
            entrypoint = args[entrypoint_index + 1]
            image = args[entrypoint_index + 2]
            reference = reference_for_id(image)
            command_args = args[entrypoint_index + 3:]
            modified = "/modified-" in reference
            variant = reference.split("-", 1)[1].split(":", 1)[0]
            route = next(key for key, value in ROUTE_VARIANTS.items() if value == variant)
            flavor = reference.rsplit(":", 1)[1]
            image_info = ["/usr/share/ublue-os/image-info.json"]
            if entrypoint == "/usr/bin/cat" and command_args == image_info:
                target = "desktop" if flavor == "gnome-hwe" else (
                    "base" if route == "ubuntu" and flavor == "base" else
                    "base-no-de" if flavor == "base" else flavor
                )
                base = next(
                    cell["baseImage"]
                    for cell in QUALIFICATION_PLAN["cells"]
                    if cell["route"] == route
                )
                info = {
                    "image-name": variant,
                    "image-flavor": target,
                    "sha": ("22222222" if modified else "11111111"),
                    "base-image": "localhost/parent:gnome" if flavor == "gnome-hwe" else base,
                }
                return subprocess.CompletedProcess(args, 0, json.dumps(info).encode(), b"")
            if entrypoint == "/usr/bin/cat":
                if not modified:
                    return subprocess.CompletedProcess(args, 1, b"", b"missing")
                manager = ROUTE_MANAGERS[route]
                package = ROUTE_PACKAGES[route]
                header = (
                    "# Written by build_scripts/lib/image-packages.sh "
                    f"for {variant} ({manager}).\n"
                )
                output = (header + f"required\t{package}\n").encode()
                return subprocess.CompletedProcess(args, 0, output, b"")
            if reference == self.fail_ref:
                return subprocess.CompletedProcess(args, 1, b"", b"not installed")
            status = b"installed\n"
            if reference == self.bad_apt_status_ref:
                status = b"config-files\n"
            return subprocess.CompletedProcess(
                args, 0 if modified else 1, status if modified else b"", b""
            )
        raise AssertionError(args)


QUALIFICATION_PLAN = plan()
SOURCE = {
    "stockShortCommit": "11111111",
    "modifiedShortCommit": "22222222",
    "managers": {
        variant: ROUTE_MANAGERS[route] for route, variant in ROUTE_VARIANTS.items()
    }
}


def test_real_route_checks_cover_base_desktop_overlay_and_native_receipts(tmp_path):
    for cell in QUALIFICATION_PLAN["cells"]:
        with FakeLog(tmp_path / f"{cell['route']}.log") as log:
            result = MODULE.verify_cell(QUALIFICATION_PLAN, cell, tmp_path, SOURCE, log)
        assert result["status"] == "passed"
        roles = {image["role"] for image in result["images"]}
        expected = {"stockBase", "modifiedBase", "modifiedDesktop"}
        if cell["route"] == "el10":
            expected.add("modifiedOverlay")
        assert roles == expected
        assert all(image["manifestDigest"].startswith("sha256:") for image in result["images"])
        assert all(image["platform"] == "linux/amd64" for image in result["images"])
        assert all(image["imageId"].startswith("sha256:") for image in result["images"])


def test_rejects_wrong_platform_internal_desktop_and_unqualified_overlay_parent(tmp_path):
    qualification_plan = copy.deepcopy(QUALIFICATION_PLAN)
    ubuntu = next(cell for cell in qualification_plan["cells"] if cell["route"] == "ubuntu")
    bad_platform = ubuntu["images"]["modifiedDesktop"]["ref"]
    FakeLog.mismatched_platform_ref = bad_platform
    try:
        with FakeLog(tmp_path / "platform.log") as log:
            with pytest.raises(MODULE.CellError, match="expected linux/amd64"):
                MODULE.verify_cell(qualification_plan, ubuntu, tmp_path, SOURCE, log)
    finally:
        FakeLog.mismatched_platform_ref = None

    internal = copy.deepcopy(ubuntu)
    internal["images"]["modifiedDesktop"]["flavor"] = "base-no-de"
    with FakeLog(tmp_path / "internal.log") as log:
        with pytest.raises(MODULE.QualificationError, match="internal build target"):
            MODULE.verify_cell(qualification_plan, internal, tmp_path, SOURCE, log)

    el10 = next(cell for cell in qualification_plan["cells"] if cell["route"] == "el10")
    overlay_ref = el10["images"]["modifiedOverlay"]["ref"]
    FakeLog.wrong_parent_ref = overlay_ref
    try:
        with FakeLog(tmp_path / "parent.log") as log:
            with pytest.raises(MODULE.CellError, match="parent is not the qualified"):
                MODULE.verify_cell(qualification_plan, el10, tmp_path, SOURCE, log)
    finally:
        FakeLog.wrong_parent_ref = None


def test_apt_requires_fully_installed_status(tmp_path):
    qualification_plan = copy.deepcopy(QUALIFICATION_PLAN)
    ubuntu = next(cell for cell in qualification_plan["cells"] if cell["route"] == "ubuntu")
    bad_status = ubuntu["images"]["modifiedDesktop"]["ref"]
    FakeLog.bad_apt_status_ref = bad_status
    try:
        with FakeLog(tmp_path / "apt-status.log") as log:
            with pytest.raises(MODULE.CellError, match="package is not installed"):
                MODULE.verify_cell(qualification_plan, ubuntu, tmp_path, SOURCE, log)
    finally:
        FakeLog.bad_apt_status_ref = None


def test_one_failed_route_is_reported_without_hiding_other_families(tmp_path, monkeypatch):
    qualification_plan = copy.deepcopy(QUALIFICATION_PLAN)
    source = {
        "stockCommit": qualification_plan["stockCommit"],
        "modifiedCommit": qualification_plan["modifiedCommit"],
        "stockShortCommit": "11111111",
        "modifiedShortCommit": "22222222",
        "stockConfigSha256": "sha256:" + "1" * 64,
        "modifiedConfigSha256": "sha256:" + "2" * 64,
        "stockAdapterSha256": "sha256:" + "3" * 64,
        "modifiedAdapterSha256": "sha256:" + "4" * 64,
        **SOURCE,
    }
    failed_ref = next(
        cell["images"]["modifiedDesktop"]["ref"]
        for cell in qualification_plan["cells"] if cell["route"] == "ubuntu"
    )
    FakeLog.fail_ref = failed_ref
    monkeypatch.setattr(MODULE, "CommandLog", FakeLog)
    monkeypatch.setattr(MODULE, "validate_source", lambda *_args: source)
    try:
        report, passed = MODULE.qualify(qualification_plan, tmp_path, tmp_path / "evidence")
    finally:
        FakeLog.fail_ref = None

    assert not passed
    assert report["summary"] == {"passed": 5, "failed": 1, "not-run": 0}
    statuses = {route["route"]: route["status"] for route in report["routes"]}
    assert statuses["ubuntu"] == "failed"
    assert all(statuses[route] == "passed" for route in MODULE.ROUTES if route != "ubuntu")
    failed = next(route for route in report["routes"] if route["route"] == "ubuntu")
    assert {image["role"] for image in failed["images"]} == {
        "stockBase", "modifiedBase", "modifiedDesktop"
    }
    assert failed["images"][-1]["package"] == "unverified"
    assert (tmp_path / "evidence/report.json").is_file()
