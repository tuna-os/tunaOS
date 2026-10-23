#!/usr/bin/env python3
"""Plan bounded coverage; never treat a scheduled cell as successful evidence."""
from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import hashlib
import json
from pathlib import Path
import re

from lib.tunaos_config import load, matrix
from lib.iso_coverage_changes import affected_cells
from lib.iso_coverage_receipts import assess_coverage, select_catchup, timestamp, read_ledger

OVERLAY = re.compile(r"-(hwe|nvidia|asahi|t2|zfs|cachyos)$")
EPOCH = date(2026, 1, 1)


def inventory(config):
    """Use declared image cells, not a Cartesian product or build_iso alone."""
    cells = []
    for variant in matrix(config)['variants']:
        for flavor in variant['flavors']:
            name = flavor['id']
            if not flavor.get('build_image') or name == 'base' or name.startswith('base-') or OVERLAY.search(name):
                continue
            for platform in flavor.get('platforms', variant.get('platforms', [])):
                admitted = flavor.get('luks_e2e') is not False
                cells.append({
                    'id': f"{variant['id']}:{name}:{platform}",
                    'variant': variant['id'], 'flavor': name, 'platform': platform,
                    'install_admitted': admitted,
                    'required_modes': ['plain', 'luks'] if admitted else [],
                    'strict_gui_status': 'unqualified',
                    'gap': ('no successful exact-media install and detached-boot receipt imported'
                            if admitted else 'image-only admission: luks_e2e=false'),
                })
    return sorted(cells, key=lambda cell: cell['id'])


def plan(config, day, period=28, capacity=2, selected=None):
    if period < 1 or capacity < 1:
        raise ValueError('period and capacity must be positive')
    cells = inventory(config)
    baseline = [c for c in cells if c['platform'] == 'linux/amd64' and c['install_admitted']]
    if len(baseline) > period * capacity:
        raise ValueError(f'{len(baseline)} cells exceed {period} days × {capacity} cells/day; review budget explicitly')
    slot = (day - EPOCH).days % period
    if selected is None:
        chosen = [cell for index, cell in enumerate(baseline) if index % period == slot]
    else:
        unknown = set(selected) - {c['id'] for c in baseline}
        if unknown:
            raise ValueError('unknown or non-admitted baseline cells: ' + ', '.join(sorted(unknown)))
        chosen = [c for c in baseline if c['id'] in selected]
        if len(chosen) > capacity:
            raise ValueError('changed-cell selection exceeds budget; split explicit batches')
    fingerprint = hashlib.sha256(json.dumps(cells, sort_keys=True).encode()).hexdigest()
    return {
        'schema_version': 1, 'execution_enabled': False, 'date': day.isoformat(),
        'inventory_sha256': fingerprint, 'rotation_epoch': EPOCH.isoformat(),
        'period_days': period, 'slot': slot, 'max_parallel': 2,
        'legacy_cell_timeout_minutes': 240,
        'legacy_selected_timeout_ceiling_minutes': 240 * len(chosen),
        'daily_cell_cap': capacity, 'baseline_install_cells': len(baseline),
        'coverage_claim': 'plan only; no build, live GUI, install, or detached boot verdict',
        'legacy_cell_runner_minutes_estimate': [45 * len(chosen), 60 * len(chosen)],
        'estimate_scope': 'legacy dev-ISO backend LUKS; NOT cost of strict plain+luks GUI qualification',
        'selected': chosen, 'inventory': cells,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path)
    parser.add_argument('--date', type=date.fromisoformat, required=True)
    parser.add_argument('--period', type=int, default=28)
    parser.add_argument('--capacity', type=int, default=2)
    parser.add_argument('--receipts', type=Path, help='authenticated durable receipt ledger JSON')
    parser.add_argument('--expected-inputs', type=Path, help='independently resolved immutable input map; never derive from receipts')
    parser.add_argument('--now', type=timestamp, help='UTC timestamp for reproducible freshness assessment')
    parser.add_argument('--stage', choices=['legacy-luks', 'strict-gui'], default='legacy-luks')
    parser.add_argument('--mode', choices=['plain', 'luks'], default='luks')
    parser.add_argument('--changed-path', action='append', help='repository-relative changed path; conservative affected-cell mapping')
    parser.add_argument('--cell', action='append', help='explicit affected baseline cell; repeat at most capacity times')
    args = parser.parse_args()
    try:
        result = plan(load(args.config), args.date, args.period, args.capacity, args.cell)
    except ValueError as error:
        parser.error(str(error))
    if args.changed_path is not None:
        if args.cell is not None:
            parser.error('--cell and --changed-path are mutually exclusive')
        changes = affected_cells(result['inventory'], args.changed_path, args.capacity)
        result['changes'] = changes
        result['selected'] = changes['selected']
        result['legacy_selected_timeout_ceiling_minutes'] = 240 * len(result['selected'])
        result['legacy_cell_runner_minutes_estimate'] = [45 * len(result['selected']), 60 * len(result['selected'])]
    if (args.receipts is None) != (args.expected_inputs is None):
        parser.error('--receipts and --expected-inputs must be supplied together')
    if args.receipts is not None:
        if args.changed_path is not None or args.cell is not None:
            parser.error('receipt catchup and changed-cell selection are separate budgeted plans')
        now = args.now or datetime.now(timezone.utc)
        try:
            report = assess_coverage(result['inventory'], read_ledger(args.receipts),
                                     json.loads(args.expected_inputs.read_text()), now, args.stage, args.mode)
            baseline_ids = {c['id'] for c in result['inventory'] if c['platform'] == 'linux/amd64'}
            queue = select_catchup(dict(report, cells=[c for c in report['cells'] if c['cell_id'] in baseline_ids]), args.capacity)
        except (ValueError, TypeError, OSError) as error:
            parser.error(str(error))
        selected_ids = {cell['cell_id'] for cell in queue['selected']}
        result['selected'] = [cell for cell in result['inventory'] if cell['id'] in selected_ids]
        result['freshness'] = report
        result['catchup'] = queue
        result['selection_basis'] = 'least-recent current-input attempt; no run is counted before its receipt'
        result['legacy_selected_timeout_ceiling_minutes'] = 240 * len(result['selected'])
        result['legacy_cell_runner_minutes_estimate'] = [45 * len(result['selected']), 60 * len(result['selected'])]
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
