#!/usr/bin/env python3
"""Bind the live installer to the exact native ISO offline payload."""

import json
from pathlib import Path
import re
import sys


def bind_recipe(path, payload, digest, target):
    """Keep update tracking remote while requiring the measured local source."""
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
        raise ValueError("invalid measured source digest")
    # Match the tracking-reference syntax accepted by xfce-media-input.py.
    if not re.fullmatch(r"[a-z0-9]+(?:[.-][a-z0-9]+)*(?::[0-9]+)?/(?:[a-z0-9]+(?:[._-][a-z0-9]+)*/)*[a-z0-9]+(?:[._-][a-z0-9]+)*:[a-zA-Z0-9_][a-zA-Z0-9._-]{0,127}", target):
        raise ValueError("invalid native target reference")
    if payload != f"{target}@{digest}":
        raise ValueError("offline payload does not match target and measured source")
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError("installer recipe must be a regular file")
    recipe = json.loads(path.read_text())
    if not isinstance(recipe, dict):
        raise ValueError("installer recipe must be an object")
    recipe["imgref"] = target
    recipe["local_imgref"] = f"containers-storage:{payload}"
    path.write_text(json.dumps(recipe, indent=2) + "\n")


if __name__ == "__main__":
    bind_recipe(*sys.argv[1:])
