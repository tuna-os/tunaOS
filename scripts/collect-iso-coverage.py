#!/usr/bin/env python3
"""Reconstruct coverage from authenticated Actions receipts; plan bounded capture."""
import argparse
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import re

from lib.iso_coverage_artifacts import discover_import
from lib.iso_coverage_receipts import IDENTITY_FIELDS, assess_coverage, select_catchup, validate_identity, timestamp
from lib.tunaos_config import load


def reconstruct(api, cells, desired_sha, now, capacity=2):
    if not re.fullmatch(r'[a-f0-9]{40}', desired_sha):
        raise ValueError('desired SHA must be immutable')
    if type(capacity) is not int or not 1 <= capacity <= 2:
        raise ValueError('scheduled execution cap is one or two cells')
    if api.main_sha() != desired_sha:
        raise ValueError('checkout is not current main; do not execute stale/draft source')
    imported = discover_import(api, cells, now, [api.resolve_workflow_id()])
    # These are API-authenticated producer measurements, not arbitrary receipt
    # input. A desired new ISO digest does not exist until that source is built.
    # Never fabricate it: missing/new-source media remains unresolved until capture.
    expected = {}
    for cell in cells:
        records = [r for r in imported['receipts'] if r['cell_id'] == cell['id']
                   and r['stage'] == 'legacy-luks' and r['mode'] == 'luks'
                   and r['source_sha'] == desired_sha and r['workflow_sha'] == desired_sha]
        measured = []
        for record in records:
            try:
                validate_identity({field: record[field] for field in IDENTITY_FIELDS})
            except ValueError:
                continue
            measured.append(record)
        if measured:
            latest = max(measured, key=lambda r: (r['finished_at'], r['run_id'], r['run_attempt']))
            expected[cell['id']] = {field: latest[field] for field in IDENTITY_FIELDS}
    report = assess_coverage(cells, imported['receipts'], expected, now, 'legacy-luks', 'luks')
    baseline = {c['id']: c for c in cells if c['platform'] == 'linux/amd64' and c['install_admitted']}
    scheduling_attempts = imported['receipts'] + imported.get('historical_attempts', [])
    queue_rows = []
    for row in report['cells']:
        if row['cell_id'] not in baseline:
            continue
        candidate = dict(row)
        prior = [r for r in scheduling_attempts if r['cell_id'] == row['cell_id']
                 and r['stage'] == 'legacy-luks' and r['mode'] == 'luks']
        if prior:
            candidate['last_attempt_at'] = max(prior, key=lambda r: timestamp(r['finished_at']))['finished_at']
        if candidate['status'] == 'unresolved-inputs':
            # Running an admitted build to MEASURE missing inputs is allowed.
            # The displayed coverage status stays unresolved, never fresh.
            candidate['status'] = 'missing'
            candidate['execution_reason'] = 'capture current immutable inputs; no qualification exists yet'
        queue_rows.append(candidate)
    today_attempts = {(r['cell_id'], r['run_id'], r['run_attempt']) for r in scheduling_attempts
                      if r['cell_id'] in baseline and r['stage'] == 'legacy-luks' and r['mode'] == 'luks'
                      and timestamp(r['finished_at']).date() == now.date()}
    remaining = max(0, capacity - len(today_attempts))
    if remaining:
        queue = select_catchup(dict(report, cells=queue_rows), remaining)
    else:
        queue = {'selected': [], 'deferred': queue_rows, 'blocked': [], 'capacity': 0}
    ready = imported['complete_history']
    # Incomplete discovery could hide a newer failure or an attempt that already
    # consumed budget. Do not execute or publish a green snapshot on partial data.
    selected_ids = {r['cell_id'] for r in queue['selected']} if ready else set()
    return {'schema_version': 1, 'desired_source_sha': desired_sha,
            'execution_ready': ready, 'history': imported, 'freshness': report,
            'selected': [baseline[key] for key in sorted(selected_ids)],
            'catchup': queue, 'max_parallel': 2, 'daily_cell_cap': capacity,
            'attempts_completed_today': len(today_attempts), 'remaining_daily_cells': remaining,
            'strict_gui_status': 'unqualified: legacy backend receipts cannot establish GUI qualification',
            'budget': {'estimated_runner_minutes': [45 * len(selected_ids), 60 * len(selected_ids)],
                       'timeout_ceiling_runner_minutes': 240 * len(selected_ids)}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-sha', required=True)
    parser.add_argument('--config', type=Path)
    args = parser.parse_args()
    from lib.iso_coverage_github import GitHubCoverageAPI
    spec = importlib.util.spec_from_file_location('coverage_plan', Path(__file__).with_name('plan-iso-coverage.py'))
    planner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(planner)
    try:
        report = reconstruct(GitHubCoverageAPI(), planner.inventory(load(args.config)), args.source_sha,
                             datetime.now(timezone.utc))
    except (OSError, ValueError, TypeError) as error:
        print(json.dumps({'schema_version': 1, 'execution_ready': False, 'selected': [],
                          'error': str(error), 'coverage_status': 'unknown: collection failed'}))
        return 2
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report['execution_ready'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
