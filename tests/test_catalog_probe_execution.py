"""Execute the workflow's real successful child-probe path without network."""
import json
import platform
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
DIGEST = 'sha256:' + 'a' * 64


def test_native_child_probe_updates_compatibility_image_and_descriptor(tmp_path, monkeypatch):
    workflow = yaml.safe_load((ROOT / '.github/workflows/catalog-facts.yml').read_text())
    run = next(step['run'] for job in workflow['jobs'].values()
               for step in job.get('steps', [])
               if 'def probe_child(' in step.get('run', ''))
    body = run.split("<<'PY'\nimport json\nimport subprocess", 1)[1].split('\nPY\n', 1)[0]
    source = 'import json\nimport subprocess' + body
    monkeypatch.chdir(tmp_path)
    (tmp_path / 'shard.json').write_text(json.dumps({'images': {}, 'descriptors': {}, 'overlays': {}}))
    monkeypatch.setattr(sys, 'argv', ['-', 'skipjack', 'gnome', 'ghcr.io/tuna-os/skipjack',
                                    'gnome', 'linux/amd64', DIGEST, 'gnome', '', '', 'true', '', ''])
    monkeypatch.setattr(platform, 'machine', lambda: 'x86_64')

    def inspect(args, **kwargs):
        assert args[0:2] == ['skopeo', 'inspect']
        if '--raw' in args:
            return json.dumps({'config': {'digest': DIGEST}, 'layers': [{'size': 123}]})
        if '--config' in args:
            return json.dumps({'os': 'linux', 'architecture': 'amd64'})
        return json.dumps({'Digest': DIGEST, 'Labels': {}})

    def probe(args, **kwargs):
        assert args[:2] == ['podman', 'run']
        assert f'ghcr.io/tuna-os/skipjack@{DIGEST}' in args
        return subprocess.CompletedProcess(args, 0, stdout=(
            'kernelVer=6.18.0\nhasSdBoot=true\npkgManager=apt\nrepoFamily=debian\n'
            'desktop=gnome\nbootc=true\n'), stderr='')

    monkeypatch.setattr(subprocess, 'check_output', inspect)
    monkeypatch.setattr(subprocess, 'run', probe)
    exec(compile(source, 'catalog-facts-probe', 'exec'), {})
    shard = json.loads((tmp_path / 'shard.json').read_text())
    image = shard['images']['tuna-os/skipjack:gnome']
    descriptor = shard['descriptors']['skipjack:gnome:linux/amd64']
    assert image['kernelVer'] == descriptor['facts']['kernelVer'] == '6.18.0'
    assert image['hasSdBoot'] is True
    assert image['pkgManager'] == 'apt'
    assert image['platformManifestDigest'] == descriptor['platformManifestDigest'] == DIGEST
