#!/usr/bin/env python3
"""Select the earlier build stages needed by a filtered flavor build.

The build workflow runs stage matrices in dependency order. A flavor-only
manual dispatch still needs every buildable flavor in an earlier stage so its
base image exists in the same run. The selector emits the platform override
map consumed by build-variant.yml; an unfiltered run emits JSON null so the
normal config filters remain authoritative.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any


def main() -> int:
    try:
        config = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError) as exc:
        raise SystemExit(f"candidate selection: invalid build config: {exc}") from exc

    want_variant = os.environ.get("FILTER_VARIANT", "all")
    want_flavor = os.environ.get("FILTER_FLAVOR", "all")
    if want_flavor == "all":
        print("null")
        return 0
    if not isinstance(config, dict) or not isinstance(config.get("variants"), list):
        raise SystemExit("candidate selection: config requires variants")

    selected: dict[str, dict[str, list[str]]] = {}
    found_variant = False
    found_flavor = False
    for variant in config["variants"]:
        if not isinstance(variant, dict):
            continue
        variant_id = variant.get("id")
        if want_variant != "all" and variant_id != want_variant:
            continue
        found_variant = True
        flavors = variant.get("flavors")
        if not isinstance(flavors, list):
            raise SystemExit(f"candidate selection: {variant_id} has no flavors list")
        target = next(
            (flavor for flavor in flavors
             if isinstance(flavor, dict) and flavor.get("id") == want_flavor),
            None,
        )
        if target is None:
            continue
        found_flavor = True
        target_stage = target.get("stage")
        if type(target_stage) is not int or target_stage < 1:
            raise SystemExit(
                f"candidate selection: {variant_id}:{want_flavor} has invalid stage"
            )
        variant_platforms = variant.get("platforms")
        if not isinstance(variant_platforms, list) or not variant_platforms:
            raise SystemExit(
                f"candidate selection: {variant_id} has no variant platforms"
            )
        candidates: dict[str, list[str]] = {}
        for flavor in flavors:
            if not isinstance(flavor, dict) or flavor.get("build_image") is not True:
                continue
            stage = flavor.get("stage")
            if type(stage) is not int or stage > target_stage:
                continue
            platforms = flavor.get("platforms", variant_platforms)
            if not isinstance(platforms, list) or not platforms:
                raise SystemExit(
                    f"candidate selection: {variant_id}:{flavor.get('id')} has no platforms"
                )
            candidates[flavor["id"]] = platforms
        selected[variant_id] = candidates

    if not found_variant:
        raise SystemExit(f"candidate selection: unknown variant {want_variant!r}")
    if not found_flavor:
        raise SystemExit(f"candidate selection: unknown flavor {want_flavor!r}")
    print(json.dumps(selected, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
