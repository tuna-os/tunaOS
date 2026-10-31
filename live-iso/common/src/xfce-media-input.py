#!/usr/bin/env python3
"""Verify the candidate OCI payload and write Fisherman's existing MediaInput v1."""
import hashlib
import json
from pathlib import Path
import re
import sys
import subprocess
import tempfile

LAYOUT = '/usr/lib/tunaos/xfce-candidate-oci'
# --preserve-digests keeps containers-storage layers uncompressed, so this
# ceiling bounds uncompressed tar bytes. bonito:xfce measured 6478177651
# (run 40546860986); ghcr amd64 728db807 is 6480981504 uncompressed over 65
# layers, none above 0.3 GiB. scripts/lib/xfce_launch.py BUILD_DISK holds
# three copies of this ceiling.
PAYLOAD_LIMIT = 8 * 1024**3
ISO_LIMIT = 10 * 1024**3



def check_budget(path, kind):
    limit = PAYLOAD_LIMIT if kind == 'payload' else ISO_LIMIT
    paths = list(path.rglob('*')) if kind == 'payload' else [path]
    total = 0
    for item in paths:
        if item.is_symlink():
            raise ValueError('size budget refuses symlink')
        if item.is_file():
            total += item.stat().st_size
        elif not item.is_dir():
            raise ValueError('size budget needs regular files')
    report = dict(kind=kind, bytes=total, limit_bytes=limit, within_budget=0 < total <= limit)
    print(json.dumps(report), flush=True)
    if not report['within_budget']:
        raise ValueError('candidate size budget exceeded or empty')
    return report


def source_budget(path, expected):
    raw = path.read_bytes()
    if 'sha256:'+hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError('source manifest digest mismatch')
    manifest = json.loads(raw)
    sizes = [item['size'] for item in [manifest['config'], *manifest['layers']]]
    if any(type(size) is not int or size < 0 for size in sizes):
        raise ValueError('invalid source descriptor size')
    total = sum(sizes)+len(raw)
    report = dict(kind='source-payload-estimate', bytes=total, limit_bytes=PAYLOAD_LIMIT, within_budget=0 < total <= PAYLOAD_LIMIT)
    print(json.dumps(report), flush=True)
    if not report['within_budget']:
        raise ValueError('source payload exceeds candidate budget')
    return report


def descriptor(layout, expected, target):
    if not isinstance(target, str) or not re.fullmatch(r"[a-z0-9]+(?:[.-][a-z0-9]+)*(?::[0-9]+)?/(?:[a-z0-9]+(?:[._-][a-z0-9]+)*/)*[a-z0-9]+(?:[._-][a-z0-9]+)*:[a-zA-Z0-9_][a-zA-Z0-9._-]{0,127}", target):
        raise ValueError("invalid tracking target")
    check_budget(layout, 'payload')
    if not re.fullmatch(r'sha256:[0-9a-f]{64}', expected):
        raise ValueError('invalid source digest')
    def blob(desc):
        digest = desc['digest']
        if type(desc.get('size')) is not int or desc['size'] < 0:
            raise ValueError('invalid blob size')
        if not re.fullmatch(r'sha256:[0-9a-f]{64}', digest):
            raise ValueError('invalid blob digest')
        path = layout/'blobs'/'sha256'/digest[7:]
        if path.is_symlink() or not path.is_file():
            raise ValueError('missing regular OCI blob')
        hasher = hashlib.sha256()
        with path.open('rb') as stream:
            for chunk in iter(lambda: stream.read(1024*1024), b''):
                hasher.update(chunk)
        if 'sha256:'+hasher.hexdigest() != digest or path.stat().st_size != desc['size']:
            raise ValueError('OCI blob size/digest mismatch')
        return path
    if json.loads((layout/'oci-layout').read_text()) != {'imageLayoutVersion':'1.0.0'}:
        raise ValueError('invalid OCI layout')
    index = json.loads((layout/'index.json').read_text())
    if index.get('schemaVersion') != 2:
        raise ValueError('invalid index schema')
    entries = index['manifests']
    if len(entries) != 1 or entries[0]['digest'] != expected:
        raise ValueError('OCI manifest differs from source')
    platform = entries[0].get('platform') or {}
    if platform and (platform.get('os') != 'linux' or platform.get('architecture') != 'amd64'):
        raise ValueError('wrong index architecture')
    if entries[0].get('mediaType') not in ('application/vnd.oci.image.manifest.v1+json', 'application/vnd.docker.distribution.manifest.v2+json'):
        raise ValueError('invalid manifest media type')
    manifest = json.loads(blob(entries[0]).read_text())
    if manifest.get('schemaVersion') != 2 or not manifest.get('layers'):
        raise ValueError('invalid manifest schema/layers')
    config = json.loads(blob(manifest['config']).read_text())
    if config.get('architecture') != 'amd64' or config.get('os') != 'linux':
        raise ValueError('wrong payload architecture')
    for layer in manifest['layers']:
        blob(layer)
    allowed={'oci-layout','index.json'} | {'blobs/sha256/'+entry['digest'][7:] for entry in [entries[0],manifest['config'],*manifest['layers']]}
    actual={str(item.relative_to(layout)) for item in layout.rglob('*') if item.is_file()}
    if actual != allowed:
        raise ValueError('unexpected files in candidate OCI payload')
    return dict(schemaVersion=1, kind='tacklebox-live', image=target,
                platformManifestDigest=expected, configDigest=manifest['config']['digest'],
                ociLayoutPath=LAYOUT, targetImgref=target, platform='linux/amd64')

def verify_iso_payload(iso, expected, target):
    """Verify the source actually shipped in the candidate, not host staging."""
    duplicate = subprocess.check_output([
        'xorriso', '-indev', str(iso), '-find', '/LiveOS',
        '-name', 'store.squashfs.img', '-exec', 'echo', '--',
    ], text=True)
    if duplicate.strip():
        raise ValueError('candidate ISO contains redundant offline store')
    # Extract only the installer input and OCI subtree, never the desktop or
    # Flatpak runtime. Temporary files are removed on every failure path.
    with tempfile.TemporaryDirectory(prefix='xfce-media-', dir=iso.parent) as directory:
        work = Path(directory)
        squash = work/'rootfs.sfs'
        subprocess.run([
            'xorriso', '-osirrox', 'on', '-indev', str(iso), '-extract',
            '/LiveOS/bonito-xfce.rootfs.sfs', str(squash),
        ], check=True, stdout=subprocess.DEVNULL)
        root = work/'root'
        receipt = Path('etc/bootc-installer/media-input.json')
        subprocess.run([
            'unsquashfs', '-no-progress', '-no-xattrs', '-d', str(root),
            str(squash), LAYOUT.lstrip('/'), str(receipt),
        ], check=True, stdout=subprocess.DEVNULL)
        embedded = root/receipt
        if embedded.is_symlink() or not embedded.is_file():
            raise ValueError('candidate media input is not a regular file')
        verified = descriptor(root/LAYOUT.lstrip('/'), expected, target)
        if json.loads(embedded.read_text()) != verified:
            raise ValueError('embedded media input differs from verified source')
    print(json.dumps(dict(kind='embedded-oci-payload', media_input=verified)), flush=True)
    return verified



if __name__ == '__main__':
    if sys.argv[1] == '--iso-budget':
        check_budget(Path(sys.argv[2]), 'iso')
        raise SystemExit(0)
    if sys.argv[1] == '--source-budget':
        source_budget(Path(sys.argv[2]), sys.argv[3])
        raise SystemExit(0)
    if sys.argv[1] == '--verify-iso-payload':
        verify_iso_payload(Path(sys.argv[2]), sys.argv[3], sys.argv[4])
        raise SystemExit(0)
    Path(sys.argv[3]).write_text(json.dumps(descriptor(Path(sys.argv[1]), sys.argv[2], sys.argv[4]), indent=2)+'\n')
