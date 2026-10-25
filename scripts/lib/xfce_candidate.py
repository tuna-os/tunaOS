"""Opt-in Bonito/XFCE contract for bootc-installer source 9259ef88.

The source mapping is an index observation. Runtime admission checks the deployed
Flatpak commit and the live squash's receipt independently, before GUI input.
"""
APP = 'org.tunaos.InstallerXfce'
SOURCE = '9259ef88876f0eabab2499edaf09829ded5dc609'
COMMIT = '2de0ddf67b8f26a90bb49e8ad837044986db95b333e734683d7da4c4ea29e3ad'
# Bundled fisherman source is 02ac7097; the GUI actually invokes the host
# /usr/local/bin/fisherman. Record that executable's digest separately.
TRANSITIONS = ['welcome', 'source', 'destination', 'setup', 'identity', 'confirm', 'progress', 'done']
TARGET = ('bonito', 'xfce', 'linux/amd64')


def validate_frontend(value):
    expected = {'app': APP, 'commit': COMMIT, 'receipt_app': APP,
                'receipt_revision': COMMIT, 'receipt_digest': COMMIT,
                'architecture': 'x86_64', 'running_app': APP, 'host_fisherman_matches_deployment': True}
    import re
    if not isinstance(value, dict) or any(value.get(k) != v for k, v in expected.items()):
        raise ValueError('actual installed XFCE frontend differs from pinned mapping')
    if not re.fullmatch(r'sha256:[0-9a-f]{64}',str(value.get('host_fisherman_digest',''))):
        raise ValueError('actual host installation backend identity missing')


LIVE_PROBE = '''import json, subprocess
from pathlib import Path
def call(*args):
    return subprocess.check_output(args, text=True, timeout=20).strip()
info = dict(line.split('=',1) for line in Path('/etc/tunaos/live-installer-info').read_text().splitlines() if '=' in line and not line.startswith('#'))
app = 'org.tunaos.InstallerXfce'
running = call('flatpak', 'ps', '--columns=application').splitlines()
deployment = Path(call('flatpak','info','--system','--show-location',app))
bundled = (deployment/'files/bin/fisherman').resolve(strict=True)
host = Path('/usr/local/bin/fisherman').resolve(strict=True)
assert host == bundled, 'host backend is not the deployed frontend backend'
result = dict(app=app, commit=call('flatpak','info','--system','--show-commit',app),
    receipt_app=info.get('INSTALLER_APP'), receipt_revision=info.get('INSTALLER_REVISION'),
    receipt_digest=info.get('INSTALLER_BUNDLE_SHA256'), architecture=call('uname','-m'),
    running_app=app if app in running else '',
    host_fisherman_matches_deployment=host == bundled,
    media_input=json.loads(Path('/etc/bootc-installer/media-input.json').read_text()),
    host_fisherman_digest='sha256:'+__import__('hashlib').sha256(Path('/usr/local/bin/fisherman').read_bytes()).hexdigest())
print(json.dumps(result))
'''
