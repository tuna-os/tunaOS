#!/usr/bin/env python3
"""Select exact candidate overlay ancestry using the build's flavor resolver."""

import json
import os
import shlex
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def parent_flavor(variant, flavor):
    result = subprocess.run(
        ["bash", str(ROOT / "scripts/resolve-flavor.sh"), variant, flavor, "1"],
        check=True, capture_output=True, text=True,
    )
    fields = [line.split("=", 1)[1] for line in result.stdout.splitlines()
              if line.startswith("PARENT_FLAVOR=")]
    if len(fields) != 1:
        raise ValueError("resolver must declare exactly one parent")
    values = shlex.split(fields[0])
    return values[0] if values else ""


def select(config, variant_filter, flavor_filter, event, repository, ref, resolver=parent_flavor):
    if (event != "workflow_dispatch" or flavor_filter == "all" or
            (repository == "tuna-os/tunaOS" and ref == "refs/heads/main")):
        return None
    selection = {}
    for variant in config["variants"]:
        vid = variant["id"]
        if variant_filter not in ("all", vid):
            continue
        flavors = {row["id"]: row for row in variant["flavors"]}
        requested = flavors.get(flavor_filter)
        if not requested or not requested.get("build_image", False):
            continue
        needed = selection.setdefault(vid, {})

        def visit(fid, platforms, visiting):
            if fid in visiting:
                raise ValueError(f"candidate parent cycle: {vid}:{fid}")
            row = flavors.get(fid)
            if not row or not row.get("build_image", False):
                raise ValueError(f"required candidate parent is unavailable: {vid}:{fid}")
            allowed = row.get("platforms", variant["platforms"])
            if not set(platforms) <= set(allowed):
                raise ValueError(f"candidate parent lacks required platform: {vid}:{fid}")
            needed[fid] = sorted(set(needed.get(fid, [])) | set(platforms))
            parent = resolver(vid, fid)
            if parent:
                if parent in flavors and flavors[parent]["stage"] >= row["stage"]:
                    raise ValueError(f"candidate parent must precede child stage: {vid}:{fid}")
                visit(parent, platforms, visiting | {fid})

        visit(flavor_filter, requested.get("platforms", variant["platforms"]), set())
    return selection


if __name__ == "__main__":
    result = select(json.load(sys.stdin), os.environ["FILTER_VARIANT"],
                    os.environ["FILTER_FLAVOR"], os.environ["EVENT_NAME"],
                    os.environ["GITHUB_REPOSITORY"], os.environ["GITHUB_REF"])
    print(json.dumps(result, separators=(",", ":")))
