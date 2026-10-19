#!/usr/bin/env python3
"""Qualification-only package protection; never enables production removals.

Capture base and desktop inventories in disposable images, then qualify an exact
removal against both. Native command failure or any unexpected package delta is
fatal; failed roots must be discarded. No package operation runs concurrently.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

MANAGERS = {"apt", "dnf", "zypper", "pacman"}
NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9+_.-]*")
SHA = re.compile(r"[a-f0-9]{64}")
HELPER = Path(__file__).with_name("fork-removals.sh")


class ProtectionError(ValueError):
    pass


def invoke(command):
    return subprocess.check_output(command, text=True, env={**os.environ, "LC_ALL": "C"}, timeout=120)


def validate_records(records, manager):
    if not isinstance(records, list):
        raise ProtectionError("inventory must be a list")
    for record in records:
        if not isinstance(record, dict) or set(record) != {"name", "version", "architecture"}:
            raise ProtectionError("invalid inventory record fields")
        if not isinstance(record["name"], str) or not NAME.fullmatch(record["name"]):
            raise ProtectionError("invalid native package name")
        if manager == "apt" and not re.fullmatch(r"[a-z0-9][a-z0-9+.-]*", record["name"]):
            raise ProtectionError("invalid Debian package name")
        if not isinstance(record["version"], str) or not record["version"] or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in record["version"]):
            raise ProtectionError("invalid native package version")
        arch = record["architecture"]
        if manager == "pacman":
            if arch is not None:
                raise ProtectionError("pacman query does not report package architecture")
        elif not isinstance(arch, str) or not re.fullmatch(r"[A-Za-z0-9_.+-]+", arch):
            raise ProtectionError("invalid native package architecture")
    keys = [tuple(record[k] or "" for k in ("name", "version", "architecture")) for record in records]
    if len(set(keys)) != len(keys):
        raise ProtectionError("duplicate native package record")
    return sorted(records, key=lambda r: (r["name"], r["version"], r["architecture"] or ""))


def snapshot(manager):
    if manager not in MANAGERS:
        raise ProtectionError("unsupported native inventory manager")
    if manager in {"dnf", "zypper"}:
        output = invoke(["rpm", "-qa", "--qf", "%{NAME}\\t%{EPOCHNUM}:%{VERSION}-%{RELEASE}\\t%{ARCH}\\n"])
    elif manager == "apt":
        output = invoke(["dpkg-query", "-W", "-f=${Package}\\t${Version}\\t${Architecture}\\t${db:Status-Status}\\n"])
    else:
        output = invoke(["pacman", "-Q"])
    records = []
    for line in output.splitlines():
        fields = line.split() if manager == "pacman" else line.split("\t")
        if manager == "apt":
            if len(fields) != 4:
                raise ProtectionError("unrecognized dpkg inventory output")
            if fields[-1] in {"config-files", "not-installed"}:
                continue
            if fields[-1] != "installed":
                raise ProtectionError("dpkg database contains an incomplete package state")
            fields = fields[:-1]
        elif manager == "pacman":
            if len(fields) != 2:
                raise ProtectionError("unrecognized pacman inventory output")
            fields.append(None)
        if len(fields) != 3:
            raise ProtectionError("unrecognized native inventory output")
        records.append(dict(zip(("name", "version", "architecture"), fields)))
    return validate_records(records, manager)


def provenance(manager, source_sha256, image_digest):
    if manager not in MANAGERS or not isinstance(source_sha256, str) or not SHA.fullmatch(source_sha256) or not isinstance(image_digest, str) or not re.fullmatch(r"sha256:[a-f0-9]{64}", image_digest):
        raise ProtectionError("invalid manager or pinned source/image identity")
    return {"package_manager": manager, "source_sha256": source_sha256, "image_digest": image_digest}


def checked_path(path, output=False):
    path = Path(path).absolute()
    if any(part.is_symlink() for part in (path, *path.parents)):
        raise ProtectionError("inventory/receipt paths cannot contain symlinks")
    if output:
        if path.exists() or not path.parent.is_dir():
            raise ProtectionError("output must be new with an existing parent directory")
    elif not path.is_file():
        raise ProtectionError("baseline must be a regular file")
    return path


def write_new(path, value):
    path = checked_path(path, output=True)
    data = (json.dumps(value, sort_keys=True, indent=2) + "\n").encode()
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o644)
    with os.fdopen(fd, "wb") as stream:
        stream.write(data)


def capture(manager, stage, source_sha256, image_digest, output):
    identity = provenance(manager, source_sha256, image_digest)
    if stage not in {"base", "desktop"}:
        raise ProtectionError("baseline stage must be base or desktop")
    checked_path(output, output=True)
    records = snapshot(manager)
    if not records:
        raise ProtectionError("empty baseline cannot protect a build")
    write_new(output, {"schema_version": 1, "stage": stage, **identity, "packages": records})


def unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ProtectionError("duplicate baseline key")
        result[key] = value
    return result


def read_baseline(path, stage, identity):
    path = checked_path(path)
    with path.open("rb") as stream:
        data = stream.read(16 * 1024 * 1024 + 1)
    if len(data) > 16 * 1024 * 1024:
        raise ProtectionError("baseline is too large")
    value = json.loads(data, object_pairs_hook=unique_pairs)
    if not isinstance(value, dict) or set(value) != {"schema_version", "stage", "packages", *identity}:
        raise ProtectionError("invalid baseline schema")
    if type(value["schema_version"]) is not int or value["schema_version"] != 1 or value["stage"] != stage:
        raise ProtectionError("invalid baseline schema version/stage")
    if any(value[k] != v for k, v in identity.items()):
        raise ProtectionError("baseline provenance mismatch")
    records = validate_records(value["packages"], identity["package_manager"])
    if not records:
        raise ProtectionError("empty baseline cannot protect a build")
    return records, hashlib.sha256(data).hexdigest()


def qualify(manager, source_sha256, image_digest, base, desktop, remove, receipt):
    if os.environ.get("TUNAOS_FORK_REMOVAL_QUALIFICATION") != "1":
        raise ProtectionError("requires an explicit disposable qualification environment")
    identity = provenance(manager, source_sha256, image_digest)
    checked_path(receipt, output=True)
    if not isinstance(remove, list) or not remove or any(not isinstance(name, str) or not NAME.fullmatch(name) for name in remove) or len(set(remove)) != len(remove):
        raise ProtectionError("removals must be unique exact native package names")
    base_records, base_hash = read_baseline(base, "base", identity)
    desktop_records, desktop_hash = read_baseline(desktop, "desktop", identity)
    # Desktop capture records approved upgrades of base names. No baseline name
    # can disappear; every protected name must match its latest captured set.
    protected = {}
    for records in (base_records, desktop_records):
        for name in {r["name"] for r in records}:
            protected[name] = [r for r in records if r["name"] == name]
    overlap = set(remove) & set(protected)
    if overlap:
        raise ProtectionError("refusing protected base/desktop package: " + ", ".join(sorted(overlap)))
    before = snapshot(manager)
    for name, records in protected.items():
        if [r for r in before if r["name"] == name] != records:
            raise ProtectionError("protected baseline inventory drift: " + name)
    if set(remove) - {r["name"] for r in before}:
        raise ProtectionError("removal target is not installed")
    subprocess.run(["bash", "-c", 'source "$1"; shift; tunaos_qualify_fork_removals "$@"',
                    "qualify", str(HELPER), manager, *remove], check=True, timeout=300)
    after = snapshot(manager)
    expected = [r for r in before if r["name"] not in set(remove)]
    if after != expected:
        raise ProtectionError("unexpected package delta; discard the failed qualification root")
    result = {"schema_version": 1, "status": "qualified-fixture-only", **identity,
              "baselines": {"base_sha256": base_hash, "desktop_sha256": desktop_hash},
              "removed": remove, "before": before, "after": after}
    write_new(receipt, result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("capture", "qualify"):
        cmd = sub.add_parser(name)
        cmd.add_argument("--manager", required=True, choices=sorted(MANAGERS))
        cmd.add_argument("--source-sha256", required=True)
        cmd.add_argument("--image-digest", required=True)
        if name == "capture":
            cmd.add_argument("--stage", required=True, choices=("base", "desktop"))
            cmd.add_argument("--output", type=Path, required=True)
        else:
            cmd.add_argument("--base", type=Path, required=True)
            cmd.add_argument("--desktop", type=Path, required=True)
            cmd.add_argument("--receipt", type=Path, required=True)
            cmd.add_argument("--remove", nargs="+", required=True)
    args = vars(parser.parse_args())
    command = args.pop("command")
    try:
        (capture if command == "capture" else qualify)(**args)
    except (ProtectionError, OSError, UnicodeError, json.JSONDecodeError, subprocess.SubprocessError) as exc:
        print(f"fork protected removals: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
