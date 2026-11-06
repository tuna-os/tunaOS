#!/usr/bin/env python3
"""Derive report categories from the official build matrix, never image aliases."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import tunaos_config

import argparse
import json



def generate(root: Path) -> str:
    config = tunaos_config.matrix(tunaos_config.load(root / "tunaos.toml"))
    architectures = {"amd64": "x86_64", "arm64": "aarch64"}
    tuples = set()
    for variant in config["variants"]:
        for flavor in variant["flavors"]:
            if flavor.get("build_image", True) is False:
                continue
            platforms = flavor.get("platforms", variant.get("platforms", config["config"]["global_platforms"]))
            for platform in platforms:
                tuples.add((variant["id"], flavor["id"], architectures[platform.split("/")[1]]))
    return json.dumps([dict(zip(("variant", "flavor", "arch"), item)) for item in sorted(tuples)], indent=2) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    targets = (root / "services/countme/src/allowlist.json", root / "system_files/usr/share/tunaos/countme-allowlist.json")
    content = generate(root)
    for target in targets:
        if args.check:
            if not target.exists() or target.read_text() != content:
                parser.exit(1, "Countme categories are stale; run scripts/generate-countme-allowlist.py\n")
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)


if __name__ == "__main__":
    main()
