"""Image declaration intent; never installed inventory or executable fetch identity."""
import re


class PolicyError(ValueError):
    """Invalid primary Flatpak declaration policy."""


def _keys(value, required):
    if not isinstance(value, dict) or set(value) != set(required):
        raise PolicyError(f'expected only fields {required}')


def _apps(value):
    if not isinstance(value, list) or len(value) > 128:
        raise PolicyError('apps must be a bounded list')
    seen = set()
    for app in value:
        _keys(app, ('id', 'branch'))
        if not isinstance(app['id'], str) or not re.fullmatch(r'[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+){2,}', app['id']) or len(app['id']) > 255:
            raise PolicyError('invalid Flatpak app ID')
        if app['branch'] != 'stable':
            raise PolicyError('only stable declarations are supported by the current builder projection')
        if app['id'] in seen:
            raise PolicyError('duplicate app declaration')
        seen.add(app['id'])
    return seen


def validate(primary):
    policy = primary['flatpak_preinstall']
    _keys(policy, ('schema_version', 'common', 'desktop_additions'))
    if type(policy['schema_version']) is not int or policy['schema_version'] != 1:
        raise PolicyError('flatpak_preinstall schema_version must be 1')
    common = _apps(policy['common'])
    additions = policy['desktop_additions']
    if not isinstance(additions, dict) or len(additions) > 64:
        raise PolicyError('desktop_additions must be a bounded table')
    metadata = primary.get('flavor_metadata')
    if not isinstance(metadata, dict) or any(not isinstance(item, dict) or not isinstance(item.get('desktop'), str) for item in metadata.values()):
        raise PolicyError('primary flavor metadata is required for desktop applicability')
    logical_desktops = {item['desktop'] for item in metadata.values()}
    for desktop, apps in additions.items():
        if desktop not in logical_desktops or desktop not in primary.get('desktops', {}) or not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,63}', desktop):
            raise PolicyError('unknown desktop in Flatpak policy')
        if common & _apps(apps):
            raise PolicyError('desktop declaration duplicates common app')
    return policy


def apps(primary, desktop):
    policy = validate(primary)
    return policy['common'] + policy['desktop_additions'].get(desktop, [])


def render(primary):
    policy = validate(primary)
    lines = ['# Generated from tunaos.toml; scope, app ID, branch. Source is unresolved.']
    for scope, declarations in [('*', policy['common']), *sorted(policy['desktop_additions'].items())]:
        lines.extend('\t'.join((scope, app['id'], app['branch'])) for app in declarations)
    return '\n'.join(lines) + '\n'
