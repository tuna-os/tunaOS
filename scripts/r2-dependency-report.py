#!/usr/bin/env python3
"""Report what image builds still read from repo.tunaos.org (epic #3470).

Two parts, both derived, none typed by hand:

* the SCAN: every https://repo.tunaos.org/ URL in tunaos.toml, build_scripts/,
  Containerfile* and image-versions.yaml, with the config table or file that
  reads it (comment lines skipped);
* the MEASUREMENT (network, anonymous, read-only): package count and bytes of
  each prefix from its own native index (rpm primary.xml, apt Packages.gz,
  pacman database), and the layer sizes of the tunaos-packages OCI tags.

PACKAGE-SOURCING.md keeps the decisions (next step per prefix). Counts, sizes
and "is there an OCI equivalent" come from here, so they cannot go stale in a
document. The scheduled workflow r2-dependency-report.yml writes the output
to its job summary.

  python3 scripts/r2-dependency-report.py            # scan + measurement
  python3 scripts/r2-dependency-report.py --offline  # scan only
"""
from __future__ import annotations

import argparse
import gzip
import io
import json
import lzma
import re
import sys
import tarfile
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOST = 'https://repo.tunaos.org/'
URL = re.compile(r'https://repo\.tunaos\.org/([^\s"\'`)>,]+)')
TABLE = re.compile(r'^\s*\[\[?([A-Za-z0-9_.\-]+)\]\]?\s*$')
OCI_REPOSITORY = 'tuna-os/tunaos-packages'
SIGNATURE_TAG = re.compile(r'^sha256-[0-9a-f]{64}(\.sig|\.att|\.sbom)?$|-candidate-')
ARCH = 'x86_64'
RPM_NS = {'c': 'http://linux.duke.edu/metadata/common'}


def build_input_files(root: Path = ROOT) -> list[Path]:
    files = [root / 'tunaos.toml', root / 'image-versions.yaml']
    files += sorted(root.glob('Containerfile*'))
    files += sorted(p for p in (root / 'build_scripts').rglob('*') if p.is_file())
    return [p for p in files if p.is_file()]


def scan(root: Path = ROOT) -> dict[str, list[str]]:
    """Map each URL path to the readers: a TOML table path, or a file name."""
    found: dict[str, list[str]] = {}
    for path in build_input_files(root):
        try:
            lines = path.read_text().splitlines()
        except UnicodeDecodeError:
            continue
        table = ''
        for line in lines:
            if path.name == 'tunaos.toml':
                header = TABLE.match(line)
                if header:
                    table = header.group(1)
            if line.lstrip().startswith('#'):
                continue
            for match in URL.finditer(line):
                # printf-style escapes end the URL in Containerfile.arch.
                prefix = match.group(1).removesuffix('\\n')
                reader = f'tunaos.toml [{table}]' if path.name == 'tunaos.toml' else path.name
                readers = found.setdefault(prefix, [])
                if reader not in readers:
                    readers.append(reader)
    return found


def kind(prefix: str) -> str:
    if prefix.endswith('.gpg'):
        return 'key'
    if prefix.startswith('tideforge/'):
        return 'apt'
    if prefix.startswith('pacman/'):
        return 'pacman'
    return 'rpm'


def expand(prefix: str) -> str:
    return prefix.replace('$basearch', ARCH).replace('$arch', ARCH)


def fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={'User-Agent': 'tunaos-r2-report'})
    with urllib.request.urlopen(request, timeout=120) as response:
        return response.read()


def decompress(name: str, data: bytes) -> bytes:
    if name.endswith('.gz'):
        return gzip.decompress(data)
    if name.endswith('.xz'):
        return lzma.decompress(data)
    if name.endswith('.zst'):
        raise ValueError('zstd metadata needs the zstd tool; not supported here')
    return data


def rpm_totals(primary_xml: bytes) -> tuple[int, int]:
    root = ET.fromstring(primary_xml)
    sizes = [int(e.attrib['package']) for e in root.iter('{%s}size' % RPM_NS['c'])]
    return len(sizes), sum(sizes)


def apt_totals(packages: str) -> tuple[int, int]:
    sizes = [int(s) for s in re.findall(r'^Size: (\d+)', packages, re.MULTILINE)]
    return len(sizes), sum(sizes)


def pacman_totals(database: bytes) -> tuple[int, int]:
    count = total = 0
    with tarfile.open(fileobj=io.BytesIO(database)) as archive:
        for member in archive.getmembers():
            if member.name.endswith('/desc'):
                text = archive.extractfile(member).read().decode()
                size = re.search(r'%CSIZE%\n(\d+)', text)
                count += 1
                total += int(size.group(1)) if size else 0
    return count, total


def measure_prefix(prefix: str, get=fetch) -> dict:
    base = HOST + expand(prefix)
    what = kind(prefix)
    if what == 'key':
        return {'kind': what, 'packages': None, 'bytes': len(get(base))}
    if what == 'apt':
        text = decompress('Packages.gz', get(base + 'Packages.gz')).decode(errors='replace')
        count, total = apt_totals(text)
    elif what == 'pacman':
        count, total = pacman_totals(decompress('tunaos.db', get(base.rstrip('/') + '/tunaos.db')))
    else:
        repomd = get(base + 'repodata/repomd.xml').decode()
        href = re.search(r'href="([^"]*primary\.xml[^"]*)"', repomd)
        if not href:
            raise ValueError(f'{prefix}: repomd.xml names no primary.xml')
        count, total = rpm_totals(decompress(href.group(1), get(base + href.group(1))))
    return {'kind': what, 'packages': count, 'bytes': total}


def oci_manifest(token: str, reference: str, get_json) -> dict:
    accept = ('application/vnd.oci.image.manifest.v1+json, '
              'application/vnd.oci.image.index.v1+json')
    return get_json(f'https://ghcr.io/v2/{OCI_REPOSITORY}/manifests/{reference}', token, accept)


def registry_json(url: str, token: str, accept: str = '') -> dict:
    headers = {'Authorization': f'Bearer {token}', 'User-Agent': 'tunaos-r2-report'}
    if accept:
        headers['Accept'] = accept
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=120) as r:
        return json.load(r)


def oci_family_tags(get_json=registry_json, get_token=None) -> list[dict]:
    """Layer sizes of every non-signature, non-candidate tag of tunaos-packages."""
    token = (get_token or (lambda: json.loads(fetch(
        f'https://ghcr.io/token?scope=repository:{OCI_REPOSITORY}:pull'))['token']))()
    tags = get_json(f'https://ghcr.io/v2/{OCI_REPOSITORY}/tags/list?n=1000', token)['tags'] or []
    rows = []
    for tag in sorted(t for t in tags if not SIGNATURE_TAG.search(t)):
        manifest = oci_manifest(token, tag, get_json)
        layers = [layer['size'] for layer in manifest.get('layers', [])]
        rows.append({'tag': tag, 'layers': layers})
    return rows


def table(headers: list[str], rows: list[list]) -> str:
    out = ['| ' + ' | '.join(headers) + ' |', '|' + '---|' * len(headers)]
    out += ['| ' + ' | '.join(str(cell) for cell in row) + ' |' for row in rows]
    return '\n'.join(out)


def render_scan(found: dict[str, list[str]]) -> str:
    rows = [[f'`{p}`', kind(p), '<br>'.join(f'`{r}`' for r in found[p])] for p in sorted(found)]
    return table(['Prefix', 'Kind', 'Read by'], rows)


def render_measurements(found: dict[str, list[str]], get=fetch) -> str:
    rows = []
    for prefix in sorted(found):
        try:
            m = measure_prefix(prefix, get)
            rows.append([f'`{prefix}`', m['kind'], '' if m['packages'] is None else m['packages'],
                         f"{m['bytes']:,}"])
        except Exception as error:  # a failed measurement is a row, never a silent gap
            rows.append([f'`{prefix}`', kind(prefix), 'ERROR', str(error)[:80]])
    return table(['Prefix', 'Kind', 'Packages', 'Bytes (x86_64)'], rows)


def render_oci(rows: list[dict]) -> str:
    return table(['OCI tag of ' + OCI_REPOSITORY, 'Layers', 'Layer bytes'],
                 [[f"`{r['tag']}`", len(r['layers']), ', '.join(f'{s:,}' for s in r['layers'])]
                  for r in rows])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--offline', action='store_true', help='scan only, no network')
    args = parser.parse_args(argv)
    found = scan()
    print('## R2 reads in the build inputs\n')
    print(render_scan(found))
    if args.offline:
        return 0
    print('\n## Measured package sets\n')
    print(render_measurements(found))
    print('\n## OCI family tags\n')
    print(render_oci(oci_family_tags()))
    return 0


if __name__ == '__main__':
    sys.exit(main())
