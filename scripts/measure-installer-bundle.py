#!/usr/bin/env python3
"""Add an installer bundle digest to scripts/lib/measured-bundles.json from strict-run evidence.

  measure-installer-bundle.py --de kde --run 43593732151 --slug flounder-kde [--write]
  measure-installer-bundle.py --de kde FILE... [--write]

Every bootc-installer release changes the digest of each desktop's Flatpak, and
the strict driver fails closed on a digest nobody measured. A digest is measured
when a strict run of that bundle walked every page of the wizard on BOTH legs
(the driver records `ui_contract_walked` only after the ordered page transitions
reached the done page) and the only thing it refused was the digest. The
page-text contract is not relaxed: a bundle that changed a page fails the walk
and is never added. One measurement covers every cell, because the digest is
per desktop, not per base.

FILE is a walkthrough-<de>.json (artifact `full-<slug>-diag`, path
luks-verify-<slug>/walkthrough-{plain,luks}/). Without --write the tool only
reports. With --write it appends the digest, then run `just fix && just check`
and commit.
"""

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).parent))
from lib import measured_bundles

REFUSAL = 'unsupported installer bundle'


def judge(desktop, files):
    """Return (digest, evidence note) when the files prove one bundle's walk, else raise ValueError."""
    modes, digests = {}, set()
    for path in files:
        evidence = json.loads(Path(path).read_text())
        where = str(path)
        if evidence.get('driver') != f'{desktop}-installer':
            raise ValueError(f'{where}: not a {desktop} installer walk (driver {evidence.get("driver")!r})')
        digest = evidence.get('installer_digest')
        if not isinstance(digest, str) or not measured_bundles.DIGEST.fullmatch(digest):
            raise ValueError(f'{where}: no installer digest in the evidence')
        if not evidence.get('ui_contract_walked') or not evidence.get('completed'):
            raise ValueError(f'{where}: the wizard was not walked to the done page '
                             f'(error: {evidence.get("error")})')
        error = evidence.get('error')
        if error and not error.startswith(REFUSAL):
            raise ValueError(f'{where}: refused for another reason: {error}')
        if evidence.get('mode') not in ('plain', 'luks'):
            raise ValueError(f'{where}: unknown mode {evidence.get("mode")!r}')
        modes[evidence['mode']] = Path(path)
        digests.add(digest)
    if len(digests) != 1:
        raise ValueError(f'the files name {len(digests)} different bundles: {sorted(digests)}')
    if set(modes) != {'plain', 'luks'}:
        raise ValueError(f'both legs are required, got: {sorted(modes)}')
    return digests.pop()


def append(digest, desktop, note, path=measured_bundles.PATH):
    data = json.loads(Path(path).read_text())
    entries = data.setdefault(desktop, [])
    if any(entry['digest'] == digest for entry in entries):
        return False
    entries.append({'digest': digest, 'evidence': note})
    Path(path).write_text(json.dumps(data, indent=2) + '\n')
    measured_bundles.load(path)
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--de', required=True)
    parser.add_argument('--run', help='iso-builder run id; downloads the small full-<slug>-diag artifact')
    parser.add_argument('--slug')
    parser.add_argument('--write', action='store_true')
    parser.add_argument('files', nargs='*')
    args = parser.parse_args()
    tmp = None
    try:
        files = list(args.files)
        note = ', '.join(files)
        if args.run:
            if not args.slug:
                parser.error('--run needs --slug')
            tmp = tempfile.mkdtemp(prefix='measure-bundle-')
            subprocess.run(['gh', 'run', 'download', args.run, '--repo', 'tuna-os/iso-builder',
                            '-n', f'full-{args.slug}-diag', '-D', tmp], check=True)
            files += sorted(str(p) for p in Path(tmp).glob(f'**/walkthrough-*/walkthrough-{args.de}.json'))
            note = f'{args.slug}, iso-builder run {args.run}'
        if not files:
            parser.error('no evidence files')
        digest = judge(args.de, files)
        if not args.write:
            print(f'{args.de}: {digest} was walked on both legs ({note}); rerun with --write to pin it')
        elif append(digest, args.de, f'every page walked on both legs ({note})'):
            print(f'{args.de}: pinned {digest}')
        else:
            print(f'{args.de}: {digest} is already measured')
        return 0
    except ValueError as exc:
        print(f'not measured: {exc}', file=sys.stderr)
        return 1
    finally:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == '__main__':
    sys.exit(main())
