#!/usr/bin/env python3
"""Extract possible live filesystems without interpreting ISO paths as shell code."""
import argparse
from pathlib import Path, PurePosixPath
import shlex
import subprocess
import sys


def payload_paths(output):
    paths = []
    for line in output.splitlines():
        words = shlex.split(line)
        if len(words) != 1:
            raise ValueError("unexpected xorriso path record")
        value = words[0]
        path = PurePosixPath(value)
        if (not value.startswith("/") or value.startswith("//") or
                ".." in path.parts or any(ord(c) < 32 for c in value) or
                path.suffix not in {".squashfs", ".sfs", ".img"} or value in paths):
            raise ValueError("unexpected or duplicate ISO payload path")
        paths.append(value)
    if not paths:
        raise ValueError("ISO inventory contains no candidate live filesystem")
    return paths


def extract(iso, destination):
    destination = Path(destination)
    if any(ord(c) < 32 for c in str(destination)):
        raise ValueError("invalid extraction directory")
    destination.mkdir(parents=True, exist_ok=True)
    result = subprocess.run([
        "xorriso", "-indev", str(iso), "-find", "/", "-type", "f", "(",
        "-name", "*.squashfs", "-o", "-name", "*.sfs", "-o", "-name", "*.img",
        ")", "-exec", "echo", "--",
    ], text=True, stdout=subprocess.PIPE, check=True)
    outputs = []
    for number, source in enumerate(payload_paths(result.stdout)):
        target = destination / f"payload-{number}.sfs"
        if target.exists() or target.is_symlink():
            raise ValueError("extraction destination already exists")
        subprocess.run(["xorriso", "-osirrox", "on", "-indev", str(iso),
                        "-extract", source, str(target)], check=True,
                       stdout=subprocess.DEVNULL)
        if not target.is_file() or target.is_symlink():
            raise ValueError("xorriso did not extract a regular payload file")
        outputs.append(str(target))
    return outputs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("iso", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    try:
        outputs = extract(args.iso, args.destination)
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        print(f"ISO payload extraction failed: {exc}", file=sys.stderr)
        return 1
    print("\n".join(outputs))
    return 0


if __name__ == "__main__":
    sys.exit(main())
