#!/usr/bin/env python3
"""Inspect actual initramfs bytes inside a disposable qualification container."""
import configparser
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile


FILES = ["usr/share/plymouth/themes/fork-identity/" + name
         for name in ("fork-identity.plymouth", "splash.png", "splash.script")]


def validate_payload(root, image_root=Path("/")):
    result = {}
    for relative in FILES + ["etc/plymouth/plymouthd.conf"]:
        extracted = root / relative
        if not extracted.resolve().is_relative_to(root) or not extracted.is_file():
            raise ValueError(f"initramfs missing safe payload: {relative}")
        data = extracted.read_bytes()
        if relative.endswith("plymouthd.conf"):
            config = configparser.ConfigParser(interpolation=None)
            config.read_string(data.decode())
            if config.get("Daemon", "Theme") != "fork-identity":
                raise ValueError("initramfs selects a different Plymouth theme")
        elif data != (image_root / relative).read_bytes():
            raise ValueError(f"initramfs payload differs from image: {relative}")
        result[relative] = hashlib.sha256(data).hexdigest()
    return result


def inspect():
    archives = sorted(Path("/usr/lib/modules").glob("*/initramfs.img"))
    if not archives:
        raise ValueError("no initramfs images found")
    results = []
    for archive in archives:
        with tempfile.TemporaryDirectory(prefix="fork-initramfs-") as directory:
            root = Path(directory)
            subprocess.run(["lsinitrd", "--unpack", str(archive)], cwd=root, check=True,
                           stdout=subprocess.DEVNULL)
            try:
                files = validate_payload(root)
            except ValueError:
                listing = subprocess.run(["lsinitrd", str(archive)], text=True, capture_output=True, check=False)
                print("Failed initramfs payload archive: " + str(archive), file=sys.stderr)
                for line in listing.stdout.splitlines():
                    if "plymouth" in line or "fork-identity" in line:
                        print(line, file=sys.stderr)
                raise
            results.append({"archive": str(archive), "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
                            "files": files})
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    inspect()
