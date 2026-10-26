#!/usr/bin/env python3
"""Bind the opt-in same-attempt diagnostic to prior verified media inputs."""
import json
import os
from pathlib import Path
import subprocess
from lib import installed_boot_diagnostic as d


def prepare(env, binding, sha, qemu_digest, qemu_version):
    d.require(env.get('VARIANT') == 'skipjack' and env.get('FLAVOR') == 'gnome'
              and env.get('TUNAOS_QUAL_PLATFORM') == 'linux/amd64', 'diagnostic_target')
    p = {'repository': env['GITHUB_REPOSITORY'], 'collector_sha': sha,
         'producer_sha': binding['producer_sha'], 'producer_run': binding['producer_run'],
         'producer_attempt': binding['producer_attempt'], 'artifact_id': binding['artifact_id'],
         'run': int(env['GITHUB_RUN_ID']), 'attempt': int(env['GITHUB_RUN_ATTEMPT']),
         'archive': binding['archive_digest']}
    for key in ('source','overlay','installer','engine','media'):
        p[key] = env['TUNAOS_QUAL_'+key.upper()+'_DIGEST']
    p = d.provenance(p)
    d.require(p['producer_sha'] == sha and p['producer_run'] == p['run'] and
              p['producer_attempt'] == p['attempt'] and p['media'] == binding['media_digest'], 'same_attempt_inputs')
    return p, {'qemu': {'path':'/usr/bin/qemu-system-x86_64', 'sha256':qemu_digest,
                        'version':qemu_version}, 'guestfs_version':'1.52.0'}


def main():
    import hashlib
    binding = json.loads(Path('native-iso-input/artifact-binding.json').read_text())
    sha = subprocess.check_output(['git','rev-parse','HEAD'], text=True).strip()
    qemu = '/usr/bin/qemu-system-x86_64'
    qemu_digest = 'sha256:'+hashlib.sha256(Path(qemu).read_bytes()).hexdigest()
    qemu_version = subprocess.check_output([qemu, '--version'], text=True, timeout=10).splitlines()[0]
    p, lock = prepare(os.environ, binding, sha, qemu_digest, qemu_version)
    for name, value in (('provenance',p), ('tools',lock)):
        path = Path(os.environ['RUNNER_TEMP']) / ('installed-boot-'+name+'.json')
        with path.open('x') as stream:
            json.dump(value, stream)


if __name__ == '__main__':
    main()
