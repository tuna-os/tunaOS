#!/usr/bin/env python3
"""Install and verify the lint binaries pinned in toolchain/lint-tools.json."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import BinaryIO

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONTRACT = ROOT / "toolchain" / "lint-tools.json"
REQUIRED_TOOLS = ("actionlint", "shellcheck", "just", "shfmt")
SUPPORTED_SYSTEMS = {"Linux": "linux", "Darwin": "darwin"}
SUPPORTED_MACHINES = {
    "x86_64": "x86_64",
    "amd64": "x86_64",
    "aarch64": "aarch64",
    "arm64": "aarch64",
}


class ContractError(RuntimeError):
    """The reviewed tool contract or an installed tool is invalid."""


def _load_contract(path: Path) -> dict:
    try:
        contract = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"cannot read {path}: {exc}") from exc

    if contract.get("schema") != 1:
        raise ContractError(f"{path}: unsupported schema {contract.get('schema')!r}")
    tools = contract.get("tools")
    if not isinstance(tools, dict):
        raise ContractError(f"{path}: tools must be an object")
    missing = [name for name in REQUIRED_TOOLS if name not in tools]
    unexpected = sorted(set(tools) - set(REQUIRED_TOOLS))
    if missing or unexpected:
        raise ContractError(
            f"{path}: tools must contain exactly {', '.join(REQUIRED_TOOLS)}; "
            f"missing {missing}; unexpected {unexpected}"
        )

    platforms = contract.get("platforms")
    if not isinstance(platforms, list) or not platforms:
        raise ContractError(f"{path}: platforms must be a non-empty list")

    for name in REQUIRED_TOOLS:
        tool = tools[name]
        if not isinstance(tool, dict):
            raise ContractError(f"{path}: {name} must be an object")
        for field in ("version", "repository", "tag", "version_regex"):
            if not isinstance(tool.get(field), str) or not tool[field]:
                raise ContractError(f"{path}: {name}.{field} must be a non-empty string")
        version_args = tool.get("version_args")
        if (
            not isinstance(version_args, list)
            or not version_args
            or not all(isinstance(argument, str) and argument for argument in version_args)
        ):
            raise ContractError(
                f"{path}: {name}.version_args must be a non-empty list of strings"
            )
        assets = tool.get("assets")
        if not isinstance(assets, dict) or set(assets) != set(platforms):
            raise ContractError(f"{path}: {name}.assets must cover every platform")
        for platform_name, asset in assets.items():
            if asset.get("format") not in {"raw", "tar.gz"}:
                raise ContractError(
                    f"{path}: {name}.{platform_name} has unsupported format"
                )
            if not re.fullmatch(r"[0-9a-f]{64}", str(asset.get("sha256", ""))):
                raise ContractError(
                    f"{path}: {name}.{platform_name} needs a lowercase SHA-256"
                )
            if not asset.get("name") or not asset.get("member"):
                raise ContractError(
                    f"{path}: {name}.{platform_name} needs name and member"
                )
    return contract


def _host_platform() -> str:
    system = SUPPORTED_SYSTEMS.get(platform.system())
    machine = SUPPORTED_MACHINES.get(platform.machine().lower())
    if not system or not machine:
        raise ContractError(
            f"unsupported host {platform.system()}/{platform.machine()}; "
            "supported hosts are listed in toolchain/lint-tools.json"
        )
    return f"{system}-{machine}"


def _release_url(tool: dict, asset: dict) -> str:
    return (
        f"https://github.com/{tool['repository']}/releases/download/"
        f"{tool['tag']}/{asset['name']}"
    )


def _run_version(executable: Path, tool: dict) -> tuple[bool, str]:
    try:
        result = subprocess.run(
            [str(executable), *tool["version_args"]],
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)
    output = (result.stdout + result.stderr).strip()
    matches = result.returncode == 0 and re.search(tool["version_regex"], output) is not None
    return matches, output


def verify(contract: dict, bin_dir: Path | None = None) -> None:
    """Check every pinned tool's version.

    Without bin_dir the tool that PATH resolves is checked, because that is
    the binary the lint recipes will run. With bin_dir the check is strict:
    the tool must be in that directory, with no PATH fallback, so an
    incomplete install cannot pass on the strength of an unrelated copy.
    """
    failures: list[str] = []
    for name in REQUIRED_TOOLS:
        tool = contract["tools"][name]
        if bin_dir is not None:
            candidate = bin_dir.expanduser() / name
            where = f" in {candidate.parent}"
            if candidate.is_file() and not os.access(candidate, os.X_OK):
                failures.append(
                    f"{name}: not executable{where} (expected {tool['version']})"
                )
                continue
            executable = candidate if candidate.is_file() else None
        else:
            located = shutil.which(name)
            executable = Path(located) if located else None
            where = " on PATH"
        if executable is None:
            failures.append(f"{name}: missing{where} (expected {tool['version']})")
            continue
        matches, output = _run_version(executable, tool)
        if not matches:
            shown = output.replace("\n", "; ") or "no version output"
            failures.append(
                f"{name}: expected {tool['version']}, got {shown} ({executable})"
            )
            continue
        print(f"{name} {tool['version']} ({executable})")

    if failures:
        detail = "\n  ".join(failures)
        raise ContractError(
            "lint tool contract mismatch:\n  "
            f"{detail}\nRun 'just setup' or "
            "'python3 scripts/lint_tools.py install --bin-dir ~/.local/bin', "
            "then ensure that directory precedes older tools on PATH."
        )


def _download(url: str, output: BinaryIO) -> str:
    digest = hashlib.sha256()
    request = urllib.request.Request(url, headers={"User-Agent": "tunaos-lint-tools/1"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            while chunk := response.read(1024 * 1024):
                digest.update(chunk)
                output.write(chunk)
    except (OSError, urllib.error.URLError) as exc:
        raise ContractError(f"failed to download {url}: {exc}") from exc
    output.flush()
    output.seek(0)
    return digest.hexdigest()


def _write_binary(source: BinaryIO, asset: dict, destination: Path) -> None:
    temporary = destination.with_name(f".{destination.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("wb") as output:
            if asset["format"] == "raw":
                shutil.copyfileobj(source, output)
            else:
                with tarfile.open(fileobj=source, mode="r:gz") as archive:
                    try:
                        member = archive.getmember(asset["member"])
                    except KeyError as exc:
                        raise ContractError(
                            f"{asset['name']}: missing archive member {asset['member']}"
                        ) from exc
                    if not member.isfile():
                        raise ContractError(
                            f"{asset['name']}: {asset['member']} is not a regular file"
                        )
                    extracted = archive.extractfile(member)
                    if extracted is None:
                        raise ContractError(
                            f"{asset['name']}: cannot read {asset['member']}"
                        )
                    with extracted:
                        shutil.copyfileobj(extracted, output)
        temporary.chmod(
            stat.S_IRUSR
            | stat.S_IWUSR
            | stat.S_IXUSR
            | stat.S_IRGRP
            | stat.S_IXGRP
            | stat.S_IROTH
            | stat.S_IXOTH
        )
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def install(contract: dict, bin_dir: Path) -> None:
    host = _host_platform()
    if host not in contract["platforms"]:
        supported = ", ".join(contract["platforms"])
        raise ContractError(
            f"host {host} is not supported by this contract; "
            f"supported platforms: {supported}"
        )
    bin_dir = bin_dir.expanduser()
    try:
        bin_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ContractError(
            f"cannot create install destination {bin_dir}: {exc}"
        ) from exc
    if not bin_dir.is_dir():
        raise ContractError(f"install destination is not a directory: {bin_dir}")

    for name in REQUIRED_TOOLS:
        tool = contract["tools"][name]
        destination = bin_dir / name
        if destination.is_file() and _run_version(destination, tool)[0]:
            print(f"{name} {tool['version']} already installed at {destination}")
            continue

        asset = tool["assets"][host]
        url = _release_url(tool, asset)
        print(f"Installing {name} {tool['version']} from {url}")
        with tempfile.TemporaryFile() as download:
            actual_sha256 = _download(url, download)
            if actual_sha256 != asset["sha256"]:
                raise ContractError(
                    f"{asset['name']}: SHA-256 mismatch: expected {asset['sha256']}, "
                    f"got {actual_sha256}"
                )
            _write_binary(download, asset, destination)

        matches, output = _run_version(destination, tool)
        if not matches:
            destination.unlink(missing_ok=True)
            raise ContractError(
                f"installed {name} failed its {tool['version']} version check: {output}"
            )

    verify(contract, bin_dir)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    subparsers = parser.add_subparsers(dest="command", required=True)

    install_parser = subparsers.add_parser("install", help="install verified binaries")
    install_parser.add_argument("--bin-dir", type=Path, required=True)

    verify_parser = subparsers.add_parser("verify", help="verify binaries on PATH")
    verify_parser.add_argument("--bin-dir", type=Path)
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        contract = _load_contract(args.contract)
        if args.command == "install":
            install(contract, args.bin_dir)
        else:
            verify(contract, args.bin_dir)
    except ContractError as exc:
        print(f"lint-tools: error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
