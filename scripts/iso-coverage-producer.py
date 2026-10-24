#!/usr/bin/env python3
"""Capture measured legacy backend identity and emit bounded producer payloads."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re

from lib.iso_coverage_receipts import validate_identity


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return 'sha256:' + h.hexdigest()


def capture(source_manifest, iso, installer, source_sha, workflow_sha):
    raw = Path(source_manifest).read_bytes()
    if len(raw) > 4 * 1024 * 1024:
        raise ValueError('source manifest exceeds limit')
    manifest = json.loads(raw)
    if (manifest.get('schemaVersion') != 2 or not isinstance(manifest.get('config'), dict)
            or not re.fullmatch(r'sha256:[0-9a-f]{64}', manifest['config'].get('digest', ''))
            or not isinstance(manifest.get('layers'), list)):
        raise ValueError('expected actual platform image manifest, not tag/index/config')
    for path in (iso, installer):
        if not Path(path).is_file() or Path(path).stat().st_size == 0:
            raise ValueError('measured media/installer file is absent or empty')
    identity = {'source_sha': source_sha, 'workflow_sha': workflow_sha,
                'source_digest': 'sha256:' + hashlib.sha256(raw).hexdigest(),
                'media_digest': digest(iso), 'installer_digest': digest(installer)}
    validate_identity(identity)
    return identity


def emit(identity, evidence, cell_id, source_sha, workflow_sha, run_id, attempt, outcome, finished_at):
    if identity is None:
        identity = {'source_sha': source_sha, 'workflow_sha': workflow_sha,
                    'source_digest': None, 'media_digest': None, 'installer_digest': None}
        if not all(re.fullmatch(r'[a-f0-9]{40}', identity[field]) for field in ('source_sha', 'workflow_sha')):
            raise ValueError('missing immutable checkout identity')
    else:
        validate_identity(identity)
    if identity['source_sha'] != source_sha or identity['workflow_sha'] != workflow_sha:
        raise ValueError('producer checkout identity changed after capture')
    if outcome not in {'success', 'failure', 'cancelled', 'skipped'}:
        raise ValueError('unknown step outcome')
    lines = set(evidence.splitlines())
    started = 'TUNAOS_LUKS_E2E_INSTALL_STARTED luks=1' in lines
    encrypted = 'TUNAOS_LUKS_E2E_ENCRYPTED_DISK_CONFIRMED' in lines
    passed = 'TUNAOS_LUKS_E2E_PASS encrypted=1 passphrase_unlock=1 installed_boot=1' in lines
    checks = {'backend_install': started and encrypted and passed,
              'installed_boot': passed, 'passphrase_unlock': encrypted and passed}
    measured = all(identity[field] is not None for field in ('source_digest', 'media_digest', 'installer_digest'))
    status = 'infra' if not measured else 'pass' if outcome == 'success' and all(checks.values()) else 'fail' if started else 'infra'
    return dict(identity, schema_version=1, cell_id=cell_id, stage='legacy-luks', mode='luks',
                status=status, finished_at=finished_at, repository='tuna-os/tunaOS',
                run_id=int(run_id), run_attempt=int(attempt), checks=checks)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    cap = sub.add_parser('capture')
    for option in ('source-manifest', 'iso', 'installer'):
        cap.add_argument('--' + option, type=Path, required=True)
    output = sub.add_parser('emit')
    output.add_argument('--identity', type=Path, required=True)
    output.add_argument('--evidence', type=Path, required=True)
    for option in ('cell-id', 'run-id', 'attempt', 'outcome'):
        output.add_argument('--' + option, required=True)
    for command in (cap, output):
        command.add_argument('--source-sha', required=True)
        command.add_argument('--workflow-sha', required=True)
    args = parser.parse_args()
    try:
        if args.command == 'capture':
            result = capture(args.source_manifest, args.iso, args.installer, args.source_sha, args.workflow_sha)
        else:
            result = emit(json.loads(args.identity.read_text()) if args.identity.exists() and args.identity.stat().st_size else None,
                          args.evidence.read_text() if args.evidence.exists() else '', args.cell_id,
                           args.source_sha, args.workflow_sha, args.run_id, args.attempt, args.outcome,
                           datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'))
    except (OSError, ValueError, TypeError) as error:
        parser.error(str(error))
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
