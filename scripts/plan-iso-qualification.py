#!/usr/bin/env python3
"""Print inventory or preflight a bounded explicit campaign; never dispatch."""
import argparse
import json
import sys
from contracts.iso_qualification import manifest, select


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target', action='append', default=[])
    parser.add_argument('--max-parallel', type=int, default=1)
    args = parser.parse_args()
    try:
        doc = manifest()
        result = select(doc, args.target, args.max_parallel) if args.target else doc
        print(json.dumps(result, sort_keys=True))
    except (ValueError, KeyError, TypeError) as exc:
        print(f'error: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
