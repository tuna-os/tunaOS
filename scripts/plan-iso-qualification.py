#!/usr/bin/env python3
"""Print inventory or preflight a bounded explicit campaign; never dispatch."""
import argparse
import json
import sys
from contracts.iso_qualification import manifest, select, select_build


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target', action='append', default=[])
    parser.add_argument('--max-parallel', type=int, default=1)
    parser.add_argument('--candidate-xfce', action='store_true')
    parser.add_argument('--build-only', action='store_true',
                        help='validate native producer inputs without qualification admission')
    args = parser.parse_args()
    try:
        doc = manifest()
        selector = select_build if args.build_only else select
        result = selector(doc, args.target, args.max_parallel, args.candidate_xfce) if args.target else doc
        print(json.dumps(result, sort_keys=True))
    except (ValueError, KeyError, TypeError) as exc:
        print(f'error: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
