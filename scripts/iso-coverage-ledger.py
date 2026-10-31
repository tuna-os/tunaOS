#!/usr/bin/env python3
"""Append already-authenticated receipts atomically; does not authenticate producers."""
import argparse
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path

from lib.iso_coverage_receipts import timestamp, update_ledger
from lib.tunaos_config import load


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path)
    parser.add_argument('--ledger', type=Path, required=True)
    parser.add_argument('--receipts', type=Path, required=True, help='JSON list from authenticated producer artifact')
    parser.add_argument('--now', type=timestamp)
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location('coverage_planner', Path(__file__).with_name('plan-iso-coverage.py'))
    planner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(planner)
    known = {cell['id'] for cell in planner.inventory(load(args.config))}
    try:
        incoming = json.loads(args.receipts.read_text())
        if not isinstance(incoming, list):
            raise ValueError('incoming receipts must be a JSON list')
        merged = update_ledger(args.ledger, incoming, known, args.now or datetime.now(timezone.utc))
    except (ValueError, TypeError, OSError) as error:
        parser.error(str(error))
    print(json.dumps({'ledger': str(args.ledger), 'receipt_count': len(merged),
                      'producer_authentication': 'caller responsibility; content validation is not origin proof'}))


if __name__ == '__main__':
    main()
