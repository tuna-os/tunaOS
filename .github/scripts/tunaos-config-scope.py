#!/usr/bin/env python3
"""Say which Tuna image cells a tunaos.toml edit can change.

Prints one line, reading the working tree against $TUNA_PR_BASE_SHA:
  iso-only      only [iso_delivery] differs (cutover targets, retained ISOs).
                No pull-request build consumes it: the artifact jobs that read
                the ISO policy skip on pull_request (build-variant.yml).
  <v1> <v2>...  only those variants' own tables changed.
  all           anything else, and every parse/fetch error (fail open).
"""
import os
from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(root / "scripts"))
from lib.tunaos_config import parse


def same_shape(left, right):
    if isinstance(left, dict) and isinstance(right, dict):
        return left.keys() == right.keys() and all(
            same_shape(left[key], right[key]) for key in left
        )
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(
            same_shape(a, b) for a, b in zip(left, right)
        )
    return type(left) is type(right)


try:
    base = os.environ["TUNA_PR_BASE_SHA"]
    if len(base) != 40 or any(c not in "0123456789abcdef" for c in base):
        raise ValueError("not a commit SHA")
    old = parse(subprocess.check_output(
        ["git", "show", f"{base}:tunaos.toml"], cwd=root, text=True,
        stderr=subprocess.DEVNULL,
    ))
    new = parse((root / "tunaos.toml").read_text())
    iso_changed = old.pop("iso_delivery", None) != new.pop("iso_delivery", None)
    # Unknown/new/deleted variants and rollout changes must not narrow coverage.
    before, after = old.pop("variants"), new.pop("variants")
    if not isinstance(before, dict) or not isinstance(after, dict):
        raise ValueError("unknown variant config")
    if old != new or before.keys() != after.keys():
        raise ValueError("shared config changed")
    if not same_shape(before, after):
        raise ValueError("unknown or changed variant config structure")
    changed = [v for v in before if before[v] != after[v]]
    if changed:
        print(" ".join(changed))
    elif iso_changed:
        print("iso-only")
    else:
        raise ValueError("no proven variant-only change")
except (KeyError, ValueError, OSError, subprocess.SubprocessError):
    print("all")
