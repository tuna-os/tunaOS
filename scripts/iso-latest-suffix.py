#!/usr/bin/env python3
"""Print the `-latest<suffix>.iso` suffix R2 uses for one ISO cell.

Producer (reusable-build-artifacts.yml) and consumer (iso-e2e.yml) both call
this, so the object name cannot drift between them. AMD64/v2 owns the bare
pointer when a flavor has it; generic AMD64 keeps the bare pointer only when
the flavor has no v2 sibling.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.lib import tunaos_config  # noqa: E402


def suffix(config, variant_id, flavor_id, platform):
    if platform == "linux/arm64":
        return "-arm64"
    if platform == "linux/amd64/v2":
        return ""
    if platform != "linux/amd64":
        raise ValueError(f"unsupported canonical platform: {platform}")
    variant = next(v for v in config["variants"] if v["id"] == variant_id)
    flavor = next(f for f in variant["flavors"] if f["id"] == flavor_id)
    platforms = (
        flavor.get("platforms")
        or variant.get("platforms")
        or config["config"]["global_platforms"]
    )
    return "-amd64" if "linux/amd64/v2" in platforms else ""


def main(argv):
    if len(argv) != 3:
        print("usage: iso-latest-suffix.py VARIANT FLAVOR PLATFORM", file=sys.stderr)
        return 2
    try:
        print(suffix(tunaos_config.matrix(tunaos_config.load()), *argv), end="")
    except (ValueError, StopIteration) as error:
        print(f"::error::{error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
