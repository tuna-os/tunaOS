#!/usr/bin/env python3
"""Check reviewed parser bytes offline, optionally against an upstream checkout."""
import argparse
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
FILES = {'__init__.py', '_parser.py', '_re.py', '_types.py', 'py.typed', 'LICENSE'}


def check(root=ROOT, upstream=None):
    vendor = Path(root) / 'scripts/lib/_vendor'
    manifest = json.loads((vendor / 'tomli-provenance.json').read_text())
    if set(manifest) != {'schema_version', 'project', 'version', 'commit', 'grammar', 'license', 'files'}:
        raise ValueError('unexpected parser provenance fields')
    if manifest['schema_version'] != 1 or manifest['version'] != '2.3.2' or manifest['grammar'] != 'TOML 1.0':
        raise ValueError('parser policy changed without review')
    if manifest['project'] != 'https://github.com/hukkin/tomli' or manifest['license'] != 'MIT':
        raise ValueError('unexpected parser source or license')
    if not re.fullmatch(r'[0-9a-f]{40}', manifest['commit']) or set(manifest['files']) != FILES:
        raise ValueError('invalid parser revision or file set')
    package = vendor / 'tomli'
    if package.is_symlink() or {p.name for p in package.iterdir() if p.name != '__pycache__'} != FILES:
        raise ValueError('unexpected parser package files')
    for name, expected in manifest['files'].items():
        source = vendor / 'tomli' / name
        if source.is_symlink() or not source.is_file() or not re.fullmatch(r'[0-9a-f]{64}', expected):
            raise ValueError(f'invalid parser file: {name}')
        data = source.read_bytes()
        if hashlib.sha256(data).hexdigest() != expected:
            raise ValueError(f'parser file drift: {name}')
        if upstream is not None:
            original = Path(upstream) / ('LICENSE' if name == 'LICENSE' else 'src/tomli/' + name)
            if original.read_bytes() != data:
                raise ValueError(f'upstream parser bytes differ: {name}')
    init = (vendor / 'tomli/__init__.py').read_text()
    if '__version__ = "2.3.2"' not in init:
        raise ValueError('parser source version differs')
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--upstream', type=Path)
    args = parser.parse_args()
    try:
        check(args.root, args.upstream)
    except (OSError, ValueError, TypeError) as exc:
        parser.exit(1, f'ERROR: {exc}\n')
    print('Reviewed parser bytes match the recorded source.')


if __name__ == '__main__':
    main()
