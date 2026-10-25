#!/usr/bin/env python3
"""Verify the candidate OCI payload and write Fisherman's existing MediaInput v1."""
import hashlib
import json
from pathlib import Path
import re
import sys

LAYOUT = '/usr/lib/tunaos/xfce-candidate-oci'
TARGET = 'ghcr.io/tuna-os/bonito:xfce'


def descriptor(layout, expected):
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
    return dict(schemaVersion=1, kind='tacklebox-live', image=TARGET,
                platformManifestDigest=expected, configDigest=manifest['config']['digest'],
                ociLayoutPath=LAYOUT, targetImgref=TARGET, platform='linux/amd64')


if __name__ == '__main__':
    Path(sys.argv[3]).write_text(json.dumps(descriptor(Path(sys.argv[1]), sys.argv[2]), indent=2)+'\n')
