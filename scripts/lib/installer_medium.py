"""Installer medium cells (tunaOS#4907, #4913).

Authoritative per-cell medium layout: which filesystem the medium and the
installed root use, which bootloader the live entry targets, and which bootc
backend `bootc install` runs with. EL10 bases stay on xfs; every other base
uses btrfs (ext4 where the base kernel lacks the btrfs fs-verity fix, as
Dakota's 7.3 kernel did). `installer-medium/` build scripts read this through
`cells()` and `cell()`; `tunaos_config.validate` rejects anything else.
"""
import re
from urllib.parse import urlsplit

SCHEMA_VERSION = 1
FILESYSTEMS = ('xfs', 'btrfs', 'ext4')
BOOTLOADERS = ('grub', 'systemd-boot')
BACKENDS = ('ostree', 'composefs')
LIVE_KARG = 'tunaos.live'
MAX_CHUNK_BYTES = 256 << 20
# EL10 bootc bases (tunaOS#4908): AlmaLinux and CentOS Stream 10. Measured
# 2026-11-22 from the variants.*.base_image pins in tunaos.toml: yellowfin and
# albacore carry almalinux-bootc:10, skipjack carries centos-bootc:stream10.
EL10_BASE = re.compile(r'almalinux|centos-bootc')
CELL = re.compile(r'[a-z0-9][a-z0-9-]*:[a-z0-9][a-z0-9-]*')
COMMIT = re.compile(r'[0-9a-f]{40}')


class MediumError(ValueError):
    """An installer_medium declaration is invalid."""


def _keys(value, required, optional=(), where='installer_medium'):
    if not isinstance(value, dict) or set(required) - set(value) or set(value) - set(required) - set(optional):
        raise MediumError(f'{where}: expected fields {list(required)}')


def is_el10(base_image):
    """True when a variant base image is an EL10 bootc base."""
    return bool(EL10_BASE.search(base_image or ''))


def validate(primary):
    """Validate [installer_medium] against the variant/flavor matrix."""
    _keys(primary.get('installer_medium', {}), ('schema_version', 'systemd_repo', 'systemd_ref', 'chunk_bytes', 'cells'))
    policy = primary['installer_medium']
    if type(policy['schema_version']) is not int or policy['schema_version'] != SCHEMA_VERSION:
        raise MediumError('installer_medium.schema_version: expected integer 1')
    repo = policy['systemd_repo']
    if not isinstance(repo, str) or urlsplit(repo).scheme != 'https' or not urlsplit(repo).hostname:
        raise MediumError('installer_medium.systemd_repo: expected an https:// git URL')
    if not isinstance(policy['systemd_ref'], str) or not COMMIT.fullmatch(policy['systemd_ref']):
        raise MediumError('installer_medium.systemd_ref: expected a full 40-hex systemd main commit, never a branch')
    chunk = policy['chunk_bytes']
    if type(chunk) is not int or chunk < (1 << 20) or chunk > MAX_CHUNK_BYTES:
        raise MediumError(f'installer_medium.chunk_bytes: expected 1 MiB..{MAX_CHUNK_BYTES} (contract v1 caps a chunk at 256 MiB)')
    cells = policy['cells']
    if not isinstance(cells, list) or not cells or len(cells) > 64:
        raise MediumError('installer_medium.cells: expected a non-empty list of at most 64 cells')
    seen = set()
    for i, entry in enumerate(cells):
        where = f'installer_medium.cells[{i}]'
        _keys(entry, ('cell', 'filesystem', 'bootloader', 'backend'), where=where)
        name = entry['cell']
        if not isinstance(name, str) or not CELL.fullmatch(name):
            raise MediumError(f'{where}.cell: expected variant:flavor, such as albacore:gnome')
        if name in seen:
            raise MediumError(f'{where}.cell: duplicate cell {name!r}')
        seen.add(name)
        variant_name, _, flavor_id = name.partition(':')
        if not _flavor_known(primary, variant_name, flavor_id):
            raise MediumError(f'{where}.cell: unknown variant/flavor or sibling desktop {name!r}')
        filesystem, bootloader, backend = entry['filesystem'], entry['bootloader'], entry['backend']
        if filesystem not in FILESYSTEMS:
            raise MediumError(f'{where}.filesystem: expected one of {list(FILESYSTEMS)}')
        if bootloader not in BOOTLOADERS:
            raise MediumError(f'{where}.bootloader: expected one of {list(BOOTLOADERS)}')
        if backend not in BACKENDS:
            raise MediumError(f'{where}.backend: expected one of {list(BACKENDS)}')
        if is_el10(_base_image(primary, variant_name)):
            if filesystem != 'xfs':
                raise MediumError(f'{where}.filesystem: EL10 base {variant_name!r} stays on xfs (tunaOS#4908)')
        elif filesystem == 'xfs':
            raise MediumError(f'{where}.filesystem: non-EL base {variant_name!r} uses btrfs, or ext4 without the btrfs fs-verity fix')
    return policy


def _flavor_known(primary, variant_name, flavor_id):
    """True when flavor_id is a declared flavor of variant, or a sibling desktop."""
    variant = primary.get('variants', {}).get(variant_name)
    if variant is not None:
        return flavor_id in {flavor.get('id') for flavor in variant.get('flavors', [])}
    for sibling in primary.get('sibling_images', []):
        if sibling.get('id') == variant_name:
            return flavor_id in {str(desktop).lower() for desktop in sibling.get('desktops', [])}
    return False


def _base_image(primary, variant_name):
    """The base_image pin of a variant, or '' for a sibling image cell."""
    variant = primary.get('variants', {}).get(variant_name)
    if variant is not None:
        return variant.get('base_image', '')
    return ''


def cells(primary):
    """Return the validated cell rows in declared order."""
    return validate(primary)['cells']


def cell(primary, name):
    """Return the validated row for one variant:flavor cell."""
    for entry in cells(primary):
        if entry['cell'] == name:
            return entry
    raise MediumError(f'installer_medium: no cell {name!r} declared')
