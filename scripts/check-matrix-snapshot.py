#!/usr/bin/env python3
"""Fail before publication when matrix board and provenance are from different snapshots."""
import json
import sys
from pathlib import Path

from matrix_snapshot import validate_snapshot


def main():
    try:
        validate_snapshot(Path("docs/MATRIX-STATUS.md").read_text(),
                          json.loads(Path("docs/matrix-provenance.json").read_text()), Path("."))
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"Invalid committed matrix snapshot: {error}", file=sys.stderr)
        return 1
    print("Matrix board and provenance form one consistent snapshot")
    return 0


if __name__ == "__main__":
    sys.exit(main())
