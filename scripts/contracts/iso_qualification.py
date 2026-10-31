"""ISO inventory and bounded campaigns, derived from validated primary TOML.

Readiness, a completed plan, and a missing receipt never confer qualification.
"""
from __future__ import annotations

import hashlib
import json
import re

from lib.tunaos_config import load, matrix
from lib.publish_destination import publish_destination
from lib.tunaos_config import PLATFORMS

DESKTOPS = {
    'gnome': ('org.bootcinstaller.Installer', 'gnome-shell', ('gnome',), ('wayland', 'x11')),
    'kde': ('org.tunaos.InstallerKde', 'plasmashell', ('KDE',), ('wayland', 'x11')),
    'xfce': ('org.tunaos.InstallerXfce', 'xfce4-session', ('XFCE', 'xfce'), ('x11', 'wayland')),
    'cosmic': ('org.tunaos.InstallerCosmic', 'cosmic-comp', ('COSMIC',), ('wayland',)),
    'niri': ('org.tunaos.InstallerNiri', 'niri', ('niri',), ('wayland',)),
    'pantheon': ('org.bootcinstaller.Installer', 'gala', ('Pantheon',), ('x11', 'wayland')),
}
# This is driver availability, not a declaration that any image passed.
NATIVE_OSTREE_VARIANTS = {'yellowfin', 'albacore', 'bonito', 'skipjack'}
STRICT_DRIVERS = {'gnome': 'gnome-23e47c51'}


def digest(value):
    return 'sha256:' + hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def cpu_baseline(variant, platform):
    """Preserve explicit OCI baseline and the native Stream/ELN requirement.

    Bare Alma amd64 is a configured native target, not an alias for its v2
    build. Do not rewrite configured platform identities to preview policy.
    """
    if platform not in PLATFORMS:
        raise ValueError('unsupported platform')
    if platform == 'linux/arm64':
        return 'armv8-a'
    if platform.endswith('/v2'):
        return 'x86-64-v2'
    if platform.endswith('/v3') or variant in {'skipjack', 'wahoo', 'albacore', 'yellowfin'}:
        return 'x86-64-v3'
    return 'x86-64'


def manifest():
    config = matrix(load())
    destination = publish_destination()
    rows = []
    pairs = set()
    for variant in config['variants']:
        for flavor in variant['flavors']:
            if not flavor.get('build_iso'):
                continue
            pairs.add((variant['id'], flavor['id']))
            for platform in flavor.get('platforms', variant['platforms']):
                name = flavor['id']
                desktop = name.split('-')[0]
                scope = 'apple-silicon' if 'asahi' in name.split('-') else 'apple-t2' if 't2' in name.split('-') else 'generic'
                target = dict(variant=variant['id'], flavor=name, platform=platform,
                              cpuBaseline=cpu_baseline(variant['id'], platform), hardwareScope=scope)
                gaps = []
                if not flavor.get('build_image'):
                    gaps.append('source image build disabled')
                if desktop == 'base':
                    gaps.append('headless: GUI qualification inapplicable')
                elif desktop not in DESKTOPS:
                    gaps.append('unknown desktop contract')
                if 'nvidia' in name.split('-'):
                    gaps.append('physical NVIDIA GPU qualification required')
                if scope != 'generic':
                    gaps.append('physical hardware qualification required')
                if platform == 'linux/arm64':
                    gaps.append('native producer architecture not implemented')
                if platform.endswith('/v2') and variant['id'] not in {'yellowfin', 'albacore'}:
                    gaps.append('configured CPU baseline conflicts with native producer support')
                if variant['id'] not in NATIVE_OSTREE_VARIANTS:
                    gaps.append('native OSTree producer backend not admitted')
                if desktop not in STRICT_DRIVERS:
                    gaps.append('production qualification driver not admitted for this frontend')
                suffix = variant.get('tag_suffix', '')
                tag = name if not suffix or name.endswith('-'+suffix) or '-'+suffix+'-' in name else name+'-'+suffix
                publication = dict(repository=destination+'/'+variant.get('publish_name', variant['id']), tag=tag)
                rows.append(dict(target=target, configured=True, image_supported=bool(flavor.get('build_image')),
                    desktop=desktop, backend='ostree' if variant['id'] in NATIVE_OSTREE_VARIANTS else None,
                    result='unrun', gaps=gaps, runnable=not gaps, publication=publication,
                    installer=DESKTOPS.get(desktop, (None,))[0]))
    rows.sort(key=lambda r: tuple(r['target'][k] for k in ('variant', 'flavor', 'platform')))
    doc = dict(schema='ISOQualificationTargets/v2', targets=rows,
               support_contract='tunaos.toml: build_iso selection; build_image and flavor/variant platforms',
               counts=dict(flavor_pairs=len(pairs), configured=len(rows),
                           image_supported=sum(r['image_supported'] for r in rows)),
               unsupported=[dict(variant='hummingbird', flavor='tuna',
                                 reason='not admitted; tunaOS#3200 (package prerequisite #832 closed)')])
    doc['manifestDigest'] = digest(doc)
    return doc


def select(doc, keys, max_parallel=1, candidate_xfce=False):
    if type(max_parallel) is not int or not 1 <= max_parallel <= 2:
        raise ValueError('max_parallel must be an integer from 1 to 2')
    if not 1 <= len(keys) <= 4 or len(set(keys)) != len(keys):
        raise ValueError('select 1 to 4 distinct explicit targets; no all-cell wave')
    index = {':'.join(r['target'][k] for k in ('variant', 'flavor', 'platform')): r for r in doc['targets']}
    selected = []
    for key in keys:
        row = index.get(key)
        candidate = candidate_xfce and key == 'bonito:xfce:linux/amd64' and row is not None and row['gaps'] == ['production qualification driver not admitted for this frontend']
        if candidate_xfce and (len(keys)!=1 or not candidate):
            raise ValueError('candidate permits only Bonito XFCE AMD64')
        if row is None or (not row['runnable'] and not candidate):
            raise ValueError(f'{key}: ' + '; '.join(row['gaps'] if row else ['target not configured']))
        selected.append(row)
    return dict(manifestDigest=doc['manifestDigest'], max_parallel=max_parallel,
                include=[dict(r['target'], backend=r['backend']) for r in selected], result='unrun')


def select_build(doc, keys, max_parallel=1, candidate_xfce=False):
    """Admit native producer inputs without claiming GUI qualification.

    The workflow uses AMD64 and verifies an OSTree offline store. Keep those
    producer limits while leaving desktop-driver and hardware qualification
    gaps to select(), which remains the qualification admission boundary.
    """
    if candidate_xfce:
        return select(doc, keys, max_parallel, candidate_xfce=True)
    if type(max_parallel) is not int or not 1 <= max_parallel <= 2:
        raise ValueError('max_parallel must be an integer from 1 to 2')
    if not 1 <= len(keys) <= 4 or len(set(keys)) != len(keys):
        raise ValueError('select 1 to 4 distinct explicit targets; no all-cell wave')
    index = {':'.join(r['target'][k] for k in ('variant', 'flavor', 'platform')): r for r in doc['targets']}
    selected = []
    for key in keys:
        row = index.get(key)
        if (row is None or not row['image_supported'] or row['backend'] != 'ostree'
                or row['target']['platform'] not in {'linux/amd64', 'linux/amd64/v2'}
                or (row['target']['platform'].endswith('/v2')
                    and row['target']['variant'] not in {'yellowfin', 'albacore'})):
            raise ValueError(f'{key}: target not supported by the native AMD64 OSTree producer')
        selected.append(row)
    return dict(manifestDigest=doc['manifestDigest'], max_parallel=max_parallel,
                include=[dict(r['target'], backend=r['backend']) for r in selected], result='unrun')


def validate_session(session, desktop, platform):
    """A DM/greeter alone cannot satisfy a logged-in desktop contract."""
    if desktop not in DESKTOPS or not isinstance(session, dict):
        raise ValueError('missing desktop/session contract')
    _, process, names, types = DESKTOPS[desktop]
    expected_arch = 'aarch64' if platform == 'linux/arm64' else 'x86_64'
    sid = session.get('session_id')
    scope = session.get('scope')
    cgroup = session.get('process_cgroup')
    if (not isinstance(sid, str) or not re.fullmatch(r'[A-Za-z0-9]+', sid)
            or scope != f'session-{sid}.scope' or not isinstance(cgroup, str)
            or scope not in cgroup.split('/')):
        raise ValueError('desktop process is not bound to the login session')
    checks = [session.get('desktop') == desktop, session.get('architecture') == expected_arch,
              session.get('desktop_contract') is True, session.get('active') is True,
              session.get('class') == 'user', session.get('remote') is False,
              type(session.get('uid')) is int and session['uid'] >= 1000,
              session.get('session_desktop') in names, session.get('type') in types,
              session.get('process') == process, type(session.get('process_uid')) is int and session.get('process_uid') == session.get('uid'),
              type(session.get('process_pid')) is int and session['process_pid'] > 1]
    if not all(checks):
        raise ValueError('desktop-specific login/session contract not proven')
