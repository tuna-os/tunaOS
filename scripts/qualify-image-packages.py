#!/usr/bin/env python3
"""Verify image-wide package additions in all six native Containerfile routes.

The input names already-built local images. The source checkout must be clean at
an exact modified commit whose only parent is the stock commit and whose only
changes are tunaos.toml plus the generated image-packages.tsv adapter. Evidence
is written once to a new directory; the caller retains that directory as the
build-run artifact.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys
from typing import BinaryIO

ROUTES = {
    "el10": "Containerfile.el10",
    "ubuntu": "Containerfile.ubuntu",
    "debian": "Containerfile.debian",
    "arch": "Containerfile.arch",
    "opensuse": "Containerfile.opensuse",
    "gentoo": "Containerfile.gentoo",
}
DIRECT_ROLES = ("modifiedBase", "modifiedDesktop")
COMMIT = re.compile(r"[0-9a-f]{40}\Z")
DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
TOKEN = re.compile(r"[a-z0-9](?:[a-z0-9._-]{0,79})\Z")
IMAGE_REF = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,511}\Z")
PACKAGE = re.compile(r"[A-Za-z0-9][A-Za-z0-9+_.-]*(?:/[A-Za-z0-9][A-Za-z0-9+_.-]*)?\Z")
APT_PACKAGE = re.compile(r"[a-z0-9][a-z0-9+.-]*\Z")
EMERGE_PACKAGE = re.compile(r"[A-Za-z0-9][A-Za-z0-9+_.-]*/[A-Za-z0-9][A-Za-z0-9+_.-]*\Z")
SOURCE_FILES = {"tunaos.toml", "build_scripts/lib/image-packages.tsv"}


class QualificationError(ValueError):
    """The requested qualification cannot prove its declared contract."""


class CellError(QualificationError):
    """A route failed after collecting zero or more immutable image identities."""

    def __init__(self, message: str, images: list[dict]):
        super().__init__(message)
        self.images = images


def require(condition: bool, message: str) -> None:
    if not condition:
        raise QualificationError(message)


def exact(value: object, fields: set[str], where: str) -> dict:
    require(isinstance(value, dict) and set(value) == fields, f"{where}: invalid fields")
    return value


def unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        require(key not in result, f"duplicate JSON field: {key}")
        result[key] = value
    return result


def sha256(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def read_json(path: Path) -> object:
    data = path.read_bytes()
    require(0 < len(data) <= 256 * 1024, "plan: expected 1..262144 bytes")
    try:
        return json.loads(data, object_pairs_hook=unique_object)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise QualificationError(f"plan: invalid JSON: {exc}") from exc


def validate_image_record(value: object, where: str) -> dict:
    record = exact(value, {"ref", "flavor"}, where)
    require(isinstance(record["ref"], str) and IMAGE_REF.fullmatch(record["ref"]),
            f"{where}.ref: invalid local image reference")
    require(isinstance(record["flavor"], str) and TOKEN.fullmatch(record["flavor"]),
            f"{where}.flavor: invalid flavor")
    return record


def validate_plan(value: object) -> dict:
    fields = {"schemaVersion", "platform", "stockCommit", "modifiedCommit", "cells"}
    plan = exact(value, fields, "plan")
    require(plan["schemaVersion"] == 1, "plan: unsupported schemaVersion")
    require(
        plan["platform"] == "linux/amd64",
        "plan.platform: qualification currently requires linux/amd64",
    )
    for field in ("stockCommit", "modifiedCommit"):
        require(
            isinstance(plan[field], str) and COMMIT.fullmatch(plan[field]),
            f"plan.{field}: expected full commit",
        )
    require(
        plan["stockCommit"] != plan["modifiedCommit"],
        "plan: stock and modified commits must differ",
    )
    require(isinstance(plan["cells"], list) and len(plan["cells"]) == len(ROUTES),
            "plan.cells: expected exactly six routes")
    cells = {}
    variants = set()
    for index, raw in enumerate(plan["cells"]):
        where = f"plan.cells[{index}]"
        cell = exact(raw, {"route", "variant", "package", "baseImage", "images"}, where)
        route = cell["route"]
        require(isinstance(route, str) and route in ROUTES and route not in cells,
                f"{where}.route: expected one unique native route")
        require(isinstance(cell["variant"], str) and TOKEN.fullmatch(cell["variant"])
                and cell["variant"] not in variants, f"{where}.variant: expected unique variant")
        require(isinstance(cell["package"], str) and PACKAGE.fullmatch(cell["package"]),
                f"{where}.package: invalid native package name")
        base = cell["baseImage"]
        require(isinstance(base, str) and IMAGE_REF.fullmatch(base) and "@" in base
                and DIGEST.fullmatch(base.rsplit("@", 1)[1]),
                f"{where}.baseImage: expected digest-pinned reference")
        if cell["images"] is not None:
            required = {"stockBase", *DIRECT_ROLES}
            if route == "el10":
                required.add("modifiedOverlay")
            images = exact(cell["images"], required, f"{where}.images")
            for role, record in images.items():
                validate_image_record(record, f"{where}.images.{role}")
            require(images["stockBase"]["flavor"] == "base"
                    and images["modifiedBase"]["flavor"] == "base",
                    f"{where}.images: base image records must use flavor 'base'")
            require(images["modifiedDesktop"]["flavor"] != "base",
                    f"{where}.images.modifiedDesktop: expected a desktop flavor")
            if route == "el10":
                flavors = {"base", images["modifiedDesktop"]["flavor"]}
                require(
                    images["modifiedOverlay"]["flavor"] not in flavors,
                    f"{where}.images.modifiedOverlay: expected a distinct overlay flavor",
                )
        cells[route] = cell
        variants.add(cell["variant"])
    require(set(cells) == set(ROUTES), "plan.cells: every native Containerfile route is required")
    return plan


class CommandLog:
    """Run fixed argv commands and retain bounded stdout/stderr evidence."""

    def __init__(self, path: Path):
        self.path = path
        self.stream: BinaryIO | None = None

    def __enter__(self) -> "CommandLog":
        self.stream = self.path.open("xb")
        return self

    def __exit__(self, *_args: object) -> None:
        assert self.stream is not None
        self.stream.close()

    def run(
        self, args: list[str], *, cwd: Path | None = None
    ) -> subprocess.CompletedProcess[bytes]:
        valid_args = all(isinstance(arg, str) and "\0" not in arg for arg in args)
        require(valid_args, "command: invalid argv")
        result = subprocess.run(args, cwd=cwd, capture_output=True, check=False)
        assert self.stream is not None
        self.stream.write(("$ " + shlex.join(args) + "\n").encode())
        self.stream.write(f"exit={result.returncode}\nstdout:\n".encode())
        self.stream.write(result.stdout)
        self.stream.write(b"\nstderr:\n")
        self.stream.write(result.stderr)
        self.stream.write(b"\n\n")
        self.stream.flush()
        return result


def checked(log: CommandLog, args: list[str], *, cwd: Path | None = None, what: str) -> bytes:
    result = log.run(args, cwd=cwd)
    require(result.returncode == 0, f"{what}: command failed ({result.returncode})")
    return result.stdout


def git_text(log: CommandLog, root: Path, *args: str) -> str:
    return checked(log, ["git", *args], cwd=root, what="source identity").decode().strip()


def adapter_rows(data: bytes) -> list[list[str]]:
    try:
        lines = data.decode("utf-8").splitlines()
    except UnicodeError as exc:
        raise QualificationError("image-packages.tsv: invalid UTF-8") from exc
    return [line.split("\t") for line in lines if line and not line.startswith("#")]


def validate_package_name(manager: str, package: str) -> None:
    if manager == "emerge":
        pattern = EMERGE_PACKAGE
    elif manager == "apt":
        pattern = APT_PACKAGE
    else:
        pattern = PACKAGE
    require(manager in {"dnf", "apt", "pacman", "zypper", "emerge"},
            f"adapter: unsupported package manager {manager!r}")
    require(bool(pattern.fullmatch(package)), f"adapter: {package!r} is invalid for {manager}")


def validate_source(plan: dict, root: Path, log: CommandLog) -> dict:
    root = root.resolve()
    require(root.is_dir() and not root.is_symlink(), "source: expected a real checkout directory")
    head = git_text(log, root, "rev-parse", "HEAD")
    require(head == plan["modifiedCommit"], "source: checkout HEAD differs from modifiedCommit")
    require(not git_text(log, root, "status", "--porcelain", "--untracked-files=all"),
            "source: checkout must be clean")
    parents = git_text(log, root, "rev-list", "--parents", "-n", "1", head).split()
    require(parents == [head, plan["stockCommit"]],
            "source: modifiedCommit must have stockCommit as its only parent")
    names = git_text(
        log, root, "diff-tree", "--no-commit-id", "--name-only", "-r", head
    ).splitlines()
    changed = set(filter(None, names))
    require(changed == SOURCE_FILES,
            "source: modified commit must change only tunaos.toml and generated image-packages.tsv")

    current = {}
    stock = {}
    for name in SOURCE_FILES:
        path = root / name
        require(path.is_file() and not path.is_symlink(), f"source: {name} must be a regular file")
        current[name] = path.read_bytes()
        stock[name] = checked(log, ["git", "show", f"{plan['stockCommit']}:{name}"], cwd=root,
                              what=f"source {name}")
    require(not adapter_rows(stock["build_scripts/lib/image-packages.tsv"]),
            "source: stock adapter is not empty")
    rows = adapter_rows(current["build_scripts/lib/image-packages.tsv"])
    require(all(len(row) == 4 and row[2] == "add" for row in rows),
            "source: qualification adapter must contain required additions only")
    expected = {(cell["variant"], cell["package"]) for cell in plan["cells"]}
    require({(row[0], row[3]) for row in rows} == expected and len(rows) == len(expected),
            "source: generated adapter does not exactly match the six qualification packages")
    managers = {}
    for variant, manager, _kind, package in rows:
        validate_package_name(manager, package)
        managers[variant] = manager
    checked(log, [sys.executable, "scripts/config.py", "check-image-packages"], cwd=root,
            what="generated adapter check")
    return {
        "stockCommit": plan["stockCommit"],
        "modifiedCommit": head,
        "stockShortCommit": git_text(log, root, "rev-parse", "--short", plan["stockCommit"]),
        "modifiedShortCommit": git_text(log, root, "rev-parse", "--short", head),
        "stockConfigSha256": sha256(stock["tunaos.toml"]),
        "modifiedConfigSha256": sha256(current["tunaos.toml"]),
        "stockAdapterSha256": sha256(stock["build_scripts/lib/image-packages.tsv"]),
        "modifiedAdapterSha256": sha256(current["build_scripts/lib/image-packages.tsv"]),
        "managers": managers,
    }


def parse_route(output: bytes) -> dict[str, object]:
    try:
        values = {}
        for line in output.decode().splitlines():
            key, raw = line.split("=", 1)
            values[key] = json.loads(raw)
        return values
    except (UnicodeError, ValueError, json.JSONDecodeError) as exc:
        raise QualificationError("route resolver: malformed output") from exc


def resolve_flavor(root: Path, variant: str, flavor: str, log: CommandLog) -> dict[str, object]:
    output = checked(log, ["bash", "scripts/resolve-flavor.sh", variant, flavor], cwd=root,
                     what=f"route {variant}:{flavor}")
    return parse_route(output)


def podman(
    log: CommandLog, image: str, entrypoint: str, *args: str
) -> subprocess.CompletedProcess[bytes]:
    return log.run(["podman", "run", "--rm", "--pull=never", "--network=none",
                    "--security-opt=no-new-privileges", "--entrypoint", entrypoint, image, *args])


def image_identity(log: CommandLog, image: str) -> dict:
    prefix = f"containers-storage:{image}"
    manifest = checked(log, ["skopeo", "inspect", "--raw", prefix], what=f"manifest {image}")
    config = checked(log, ["skopeo", "inspect", "--config", prefix], what=f"config {image}")
    return {"manifestDigest": sha256(manifest), "configDigest": sha256(config)}


def read_image_info(log: CommandLog, image: str) -> dict:
    raw = checked(log, ["podman", "run", "--rm", "--pull=never", "--network=none",
                        "--security-opt=no-new-privileges", "--entrypoint", "/usr/bin/cat", image,
                        "/usr/share/ublue-os/image-info.json"], what=f"image info {image}")
    try:
        value = json.loads(raw, object_pairs_hook=unique_object)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise QualificationError(f"image info {image}: invalid JSON") from exc
    require(isinstance(value, dict), f"image info {image}: expected object")
    return value


def package_query(
    log: CommandLog, manager: str, image: str, package: str
) -> subprocess.CompletedProcess[bytes]:
    if manager in {"dnf", "zypper"}:
        return podman(log, image, "/usr/bin/rpm", "-q", "--", package)
    if manager == "apt":
        return podman(log, image, "/usr/bin/dpkg-query", "-W", "-f=${db:Status-Status}\\n", package)
    if manager == "pacman":
        return podman(log, image, "/usr/bin/pacman", "-Q", package)
    if manager == "emerge":
        return podman(log, image, "/usr/bin/qlist", "-IC", package)
    raise QualificationError(f"package query: unsupported manager {manager}")


def receipt(log: CommandLog, image: str) -> subprocess.CompletedProcess[bytes]:
    return podman(log, image, "/usr/bin/cat", "/usr/share/tunaos/image-packages.tsv")


def verify_info(info: dict, *, variant: str, target: str, short_commit: str,
                base_image: str | None, where: str) -> None:
    require(info.get("image-name") == variant, f"{where}: wrong image-name")
    require(info.get("image-flavor") == target, f"{where}: wrong image-flavor")
    require(info.get("sha") == short_commit, f"{where}: wrong source revision")
    if base_image is not None:
        require(info.get("base-image") == base_image, f"{where}: wrong base-image")


def verify_modified_receipt(
    data: bytes, variant: str, manager: str, package: str, where: str
) -> str:
    try:
        lines = data.decode("utf-8").splitlines()
    except UnicodeError as exc:
        raise QualificationError(f"{where}: package receipt is not UTF-8") from exc
    header = f"# Written by build_scripts/lib/image-packages.sh for {variant} ({manager})."
    require(lines and lines[0] == header, f"{where}: package receipt header mismatch")
    require(lines[1:] == [f"required\t{package}"], f"{where}: package receipt rows mismatch")
    return sha256(data)


def verify_base_source(log: CommandLog, reference: str) -> str:
    raw = checked(log, ["skopeo", "inspect", "--raw", f"docker://{reference}"],
                  what=f"base source {reference}")
    expected = reference.rsplit("@", 1)[1]
    require(
        sha256(raw) == expected,
        f"base source {reference}: registry bytes differ from pinned digest",
    )
    return expected


def verify_cell(plan: dict, cell: dict, root: Path, source: dict, log: CommandLog) -> dict:
    route = cell["route"]
    images = cell["images"]
    if images is None:
        return {"route": route, "variant": cell["variant"], "status": "not-run",
                "reason": "images-not-supplied", "images": []}

    variant = cell["variant"]
    manager = source["managers"].get(variant)
    require(manager is not None, f"{route}: adapter has no manager for {variant}")
    base_route = resolve_flavor(root, variant, "base", log)
    require(
        base_route.get("CONTAINERFILE") == ROUTES[route],
        f"{route}: base flavor resolves elsewhere",
    )
    desktop = resolve_flavor(root, variant, images["modifiedDesktop"]["flavor"], log)
    require(
        desktop.get("CONTAINERFILE") == ROUTES[route],
        f"{route}: desktop flavor resolves elsewhere",
    )
    routes = {"stockBase": base_route, "modifiedBase": base_route, "modifiedDesktop": desktop}
    if route == "el10":
        overlay = resolve_flavor(root, variant, images["modifiedOverlay"]["flavor"], log)
        require(
            overlay.get("CONTAINERFILE") == "Containerfile.overlay"
            and overlay.get("PARENT_FLAVOR"),
            "el10: overlay flavor does not inherit from a parent",
        )
        routes["modifiedOverlay"] = overlay

    verify_base_source(log, cell["baseImage"])
    collected = []
    ordered_roles = ["stockBase", *DIRECT_ROLES]
    if route == "el10":
        ordered_roles.append("modifiedOverlay")
    for role in ordered_roles:
        record = images[role]
        image = record["ref"]
        routing = routes[role]
        target = routing.get("DESKTOP_FLAVOR")
        try:
            require(isinstance(target, str) and target, f"{route}.{role}: resolver omitted target")
            identity = image_identity(log, image)
            image_record = {"role": role, "flavor": record["flavor"], **identity,
                            "package": "unverified", "receiptSha256": None}
            collected.append(image_record)
            info = read_image_info(log, image)
            short_commit = (source["stockShortCommit"] if role == "stockBase"
                            else source["modifiedShortCommit"])
            direct_base = None if role == "modifiedOverlay" else cell["baseImage"]
            verify_info(info, variant=variant, target=target, short_commit=short_commit,
                        base_image=direct_base, where=f"{route}.{role}")
            query = package_query(log, manager, image, cell["package"])
            if role == "stockBase":
                require(
                    query.returncode == 1,
                    f"{route}.stockBase: package query did not prove absence",
                )
                installed_receipt = receipt(log, image)
                require(
                    installed_receipt.returncode == 1,
                    f"{route}.stockBase: stock package receipt exists",
                )
                image_record["package"] = "absent"
            else:
                require(
                    query.returncode == 0 and query.stdout.strip(),
                    f"{route}.{role}: package is not installed",
                )
                installed_receipt = receipt(log, image)
                require(
                    installed_receipt.returncode == 0,
                    f"{route}.{role}: package receipt is missing",
                )
                image_record["receiptSha256"] = verify_modified_receipt(
                    installed_receipt.stdout, variant, manager, cell["package"], f"{route}.{role}"
                )
                image_record["package"] = "installed"
        except (QualificationError, OSError) as exc:
            raise CellError(str(exc), collected) from exc
    return {"route": route, "variant": variant, "manager": manager, "package": cell["package"],
            "baseImage": cell["baseImage"], "status": "passed", "reason": None, "images": collected}


def qualify(plan: dict, root: Path, output: Path) -> tuple[dict, bool]:
    require(
        not output.exists() and not output.is_symlink(),
        "output: refusing to replace existing evidence",
    )
    output.mkdir(parents=True)
    with CommandLog(output / "source.log") as source_log:
        source = validate_source(plan, root, source_log)
    source_log_digest = sha256((output / "source.log").read_bytes())

    results = []
    for cell in plan["cells"]:
        log_path = output / f"{cell['route']}.log"
        with CommandLog(log_path) as log:
            try:
                result = verify_cell(plan, cell, root, source, log)
            except CellError as exc:
                result = {"route": cell["route"], "variant": cell["variant"], "status": "failed",
                          "reason": str(exc), "images": exc.images}
            except (QualificationError, OSError) as exc:
                result = {"route": cell["route"], "variant": cell["variant"], "status": "failed",
                          "reason": str(exc), "images": []}
        result["logSha256"] = sha256(log_path.read_bytes())
        results.append(result)

    counts = {status: sum(item["status"] == status for item in results)
              for status in ("passed", "failed", "not-run")}
    generated_at = datetime.now(timezone.utc).replace(microsecond=0)
    report = {
        "schemaVersion": 1,
        "generatedAt": generated_at.isoformat().replace("+00:00", "Z"),
        "platform": plan["platform"],
        "source": {key: value for key, value in source.items() if key != "managers"},
        "sourceLogSha256": source_log_digest,
        "routes": results,
        "summary": counts,
        "releasePass": counts == {"passed": len(ROUTES), "failed": 0, "not-run": 0},
    }
    encoded = (json.dumps(report, indent=2, sort_keys=True) + "\n").encode()
    require(len(encoded) <= 256 * 1024, "report: exceeds 256 KiB")
    (output / "report.json").write_bytes(encoded)
    return report, report["releasePass"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        plan = validate_plan(read_json(args.plan))
        report, passed = qualify(plan, args.source, args.output)
    except (QualificationError, OSError) as exc:
        print(f"ERROR: image package qualification: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(report["summary"], sort_keys=True))
    print(args.output / "report.json")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
