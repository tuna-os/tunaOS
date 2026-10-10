#!/usr/bin/env python3
"""Verify an explicit canonical receipt artifact; never promote its publication."""
import argparse
import json
from pathlib import Path
from contracts.evidence import EvidenceError, loads
from contracts.receipt_collection import authenticate


def policy(path):
    if any(item.is_symlink() for item in (path, *path.parents)) or not path.is_file():
        raise EvidenceError('unsafe receipt policy file')
    with path.open('rb') as stream:
        raw = stream.read(8 * 1024 * 1024 + 1)
    if len(raw) > 8 * 1024 * 1024:
        raise EvidenceError('receipt policy exceeds bound')
    return loads(raw.decode('utf-8'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--artifact-id', type=int, required=True)
    parser.add_argument('--expected-identity', type=Path, required=True)
    parser.add_argument('--target', type=Path, required=True)
    parser.add_argument('--kind', choices=['image-receipt', 'factory-receipt'], required=True)
    parser.add_argument('--api-version', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    # Input identity is caller-reviewed policy, not downloaded verification JSON.
    result = authenticate(args.archive, args.artifact_id, policy(args.expected_identity),
                          policy(args.target), args.kind, args.api_version)
    args.output.write_text(json.dumps(result, sort_keys=True, indent=2) + '\n')


if __name__ == '__main__':
    main()
