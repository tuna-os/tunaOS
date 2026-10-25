"""ISO inventory and bounded campaigns, derived from validated primary TOML.

Readiness, a completed plan, and a missing receipt never confer qualification.
"""
from __future__ import annotations

import hashlib
import json
import re

from lib.tunaos_config import load, matrix
from contracts.targets import cpu_baseline, resolve_required_targets, validate_target

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
STRICT_DRIVERS = {'gnome': 'gnome-9f582fe0'}


def digest(value):
    return 'sha256:' + hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def manifest(path=None):
    config = matrix(load(path))
    pairs = {(v['id'], f['id']) for v in config['variants'] for f in v['flavors'] if f.get('build_iso')}
    required = {tuple(r['target'][k] for k in ('variant', 'flavor', 'platform')): r
                for r in resolve_required_targets(config)
                if (r['target']['variant'], r['target']['flavor']) in pairs}
    configured = {(v['id'], f['id'], p) for v in config['variants'] for f in v['flavors']
                  if f.get('build_iso') for p in f.get('platforms', v['platforms'])}
    rows = []
    for key in sorted(set(required) | configured):
        variant, flavor, platform = key
        desktop = flavor.split('-')[0]
        target = dict(variant=variant, flavor=flavor, platform=platform,
                      cpuBaseline=cpu_baseline(variant, platform), hardwareScope='generic')
        gaps = []
        try:
            validate_target(target)
        except ValueError as exc:
            gaps.append('configured-policy-conflict: ' + str(exc))
        if key not in configured:
            gaps.append('unscheduled')
        if key not in required:
            gaps.append('configured-not-required: explicit policy review required')
        if desktop == 'base':
            gaps.append('headless: GUI qualification inapplicable')
        elif desktop not in DESKTOPS:
            gaps.append('unknown desktop contract')
        if 'nvidia' in flavor.split('-'):
            gaps.append('physical NVIDIA GPU qualification required')
        if platform == 'linux/arm64':
            gaps.append('native producer architecture not implemented')
        if variant not in NATIVE_OSTREE_VARIANTS:
            gaps.append('native OSTree producer backend not admitted')
        if desktop not in STRICT_DRIVERS:
            gaps.append('production qualification driver not admitted for this frontend')
        row = dict(target=target, required=key in required, configured=key in configured,
                   desktop=desktop, backend='ostree' if variant in NATIVE_OSTREE_VARIANTS else None, result='unrun', gaps=gaps,
                   runnable=not gaps, publication=required.get(key, {}).get('publication'), installer=DESKTOPS.get(desktop, (None,))[0])
        rows.append(row)
    doc = dict(schema='ISOQualificationTargets/v1', targets=rows,
               counts=dict(flavor_pairs=len(pairs), configured=len(configured), required=len(required),
                           configured_not_required=len(configured-set(required)),
                           required_unscheduled=len(set(required)-configured)),
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
