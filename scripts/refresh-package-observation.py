#!/usr/bin/env python3
"""Re-measure a package catalog's target observation and update its pin.

Reviewed refresh step for the error "effective package-source configuration
changed; refresh observation". It prints which recorded inputs changed. With
--write it replaces the observation file and the `target_observation_sha256` pin
in tunaos.toml. The reviewer reads the diff before committing. It does no
network access and does not touch the base observation, keys or catalog sources.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from lib import package_authoring as author
from lib import package_catalogs as catalogs
from lib import tunaos_config


def _changed_inputs(old, new):
    lines = []
    for section in ('configuration_files', 'configuration_extracts'):
        for path, identity in new[section].items():
            before = old.get(section, {}).get(path)
            if before != identity:
                lines.append(f'{section}: {path}: '
                             f'{(before or {}).get("sha256", "absent")[:12]} -> {identity["sha256"][:12]}')
    for key in ('copied_package_source_files', 'common_image', 'build_sources', 'flavors',
                'base_image', 'variant', 'platform', 'schema_version'):
        if old.get(key) != new.get(key):
            lines.append(f'{key}: changed')
    return lines


def _replace_pin(source, catalog_name, digest):
    """Replace the one pin inside [package_catalogs.<name>]; nothing else."""
    header = re.search(r'(?m)^\[package_catalogs\.' + re.escape(catalog_name) + r'\]\s*$', source)
    if header is None:
        raise catalogs.CatalogError(f'tunaos.toml has no [package_catalogs.{catalog_name}] table')
    following = re.search(r'(?m)^\[', source[header.end():])
    end = header.end() + following.start() if following else len(source)
    table = source[header.end():end]
    pin = re.compile(r'(?m)^(target_observation_sha256 = ")[0-9a-f]{64}(")$')
    if len(pin.findall(table)) != 1:
        raise catalogs.CatalogError('target_observation_sha256 pin is missing or ambiguous')
    return source[:header.end()] + pin.sub(r'\g<1>' + digest + r'\g<2>', table) + source[end:]


def _atomic_write(path, data):
    mode = path.stat().st_mode & 0o7777 if path.exists() else 0o644
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=f'.{path.name}.')
    try:
        with os.fdopen(descriptor, 'wb') as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    except BaseException:
        os.unlink(temporary)
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=tunaos_config.ROOT / 'tunaos.toml')
    parser.add_argument('--catalog', required=True)
    parser.add_argument('--write', action='store_true',
                        help='replace the observation file and the pin; default only reports')
    args = parser.parse_args(argv)
    try:
        source = author.read_config(args.config)
        document = tunaos_config.validate(tunaos_config.parse(source, path=str(args.config)))
        catalog = document.get('package_catalogs', {}).get(args.catalog)
        if catalog is None:
            raise catalogs.CatalogError(f'unknown package catalog: {args.catalog}')
        root = args.config.resolve().parent
        observation_path = root / catalog['target_observation']
        old = json.loads(catalogs._public_file(root, catalog['target_observation']))
        now = datetime.now(timezone.utc)
        raw, changed = catalogs.refresh_target_observation(catalog, root, now)
        new = json.loads(raw)
        digest = hashlib.sha256(raw).hexdigest()
        stale_pin = catalog['target_observation_sha256'] != hashlib.sha256(
            catalogs._public_file(root, catalog['target_observation'])).hexdigest()
        if not changed and not stale_pin:
            print(f'{args.catalog}: observation is current; nothing to do')
            return 0
        for line in _changed_inputs(old, new):
            print(line)
        print(f'observed_at: {old.get("observed_at")} -> {new["observed_at"]}')
        if not args.write:
            print('dry run: review the changes above, then repeat with --write')
            return 0
        print(f'target_observation_sha256: {catalog["target_observation_sha256"][:12]} -> {digest[:12]}')
        updated = _replace_pin(source.decode('utf-8'), args.catalog, digest)
        _atomic_write(observation_path, raw)
        _atomic_write(args.config, updated.encode())
        print('written: review `git diff`, then run the package catalog tests')
    except (catalogs.CatalogError, tunaos_config.ConfigError, ValueError, OSError, RecursionError) as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
