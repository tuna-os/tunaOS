#!/usr/bin/env python3
"""Write bounded failure metadata even when the diagnostic dependencies fail.

Uses only the standard library. Never opens media or copies exception/log text.
Existing collector evidence is left intact; incomplete evidence is an error.
"""
import hashlib
import json
import os
from pathlib import Path
import re


def record(directory, env):
    directory = Path(directory).absolute()
    if any(path.is_symlink() for path in (directory, *directory.parents)):
        raise ValueError('unsafe evidence path')
    if directory.exists():
        if directory.is_symlink() or not directory.is_dir():
            raise ValueError('unsafe evidence directory')
        for name in ('report.json', 'manifest.json'):
            path = directory / name
            if path.is_symlink() or not path.is_file() or path.stat().st_size > 1024 * 1024:
                raise ValueError('incomplete or oversized collector evidence')
        return
    outcomes = {}
    for key in ('HOST_TOOLS_OUTCOME', 'INSPECTOR_OUTCOME', 'DIAGNOSTIC_OUTCOME'):
        value = env.get(key, '')
        if value not in ('', 'success', 'failure', 'cancelled', 'skipped'):
            raise ValueError('invalid step outcome')
        outcomes[key.lower()] = value or 'unknown'
    inputs = {}
    patterns = {'GITHUB_SHA': r'[0-9a-f]{40}', 'GITHUB_RUN_ID': r'[1-9][0-9]{0,19}',
                'GITHUB_RUN_ATTEMPT': r'[1-9][0-9]{0,9}', 'INPUT_PRODUCER_SHA': r'[0-9a-f]{40}',
                'INPUT_ARTIFACT_ID': r'[1-9][0-9]{0,19}', 'INPUT_ARCHIVE_DIGEST': r'sha256:[0-9a-f]{64}'}
    for key, pattern in patterns.items():
        value = env.get(key, '')
        inputs[key.lower()] = value if re.fullmatch(pattern, value) else None
    report = {'schema': 'InstalledBootDiagnosticFailure/v1', 'qualified': False,
              'label': 'fresh reproduction, not the disk from run 40093907774',
              'reference_run': 40093907774,
              'status': 'evidence_unavailable', 'step_outcomes': outcomes,
              'declared_inputs_unverified': inputs,
              'runtime_evidence': 'not_available', 'stop_proof': 'not_established'}
    raw = (json.dumps(report, sort_keys=True) + '\n').encode()
    if len(raw) > 4096:
        raise ValueError('failure report limit')
    directory.mkdir(parents=True, mode=0o700)
    (directory / 'report.json').write_bytes(raw)
    manifest = {'schema': 'InstalledBootDiagnosticManifest/v1', 'files': [
        {'name': 'report.json', 'bytes': len(raw), 'sha256': 'sha256:' + hashlib.sha256(raw).hexdigest()}]}
    (directory / 'manifest.json').write_text(json.dumps(manifest) + '\n')


if __name__ == '__main__':
    record(Path(os.environ['RUNNER_TEMP']) / 'installed-boot-run/installed-boot-diagnostic', os.environ)
