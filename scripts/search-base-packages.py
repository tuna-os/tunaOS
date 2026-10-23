#!/usr/bin/env python3
"""Search signed upstream base-image indexes; never edit package policy."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from lib import tunaos_config
from lib import package_authoring as author
from lib import package_catalogs as catalogs
from lib import signed_apt


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('query')
    parser.add_argument('--config', type=Path, default=tunaos_config.ROOT / 'tunaos.toml')
    parser.add_argument('--catalog', required=True)
    parser.add_argument('--variant', required=True)
    parser.add_argument('--release', required=True)
    parser.add_argument('--platform', required=True)
    args = parser.parse_args(argv)
    try:
        if not args.query or len(args.query) > 256 or any(ord(c) < 32 for c in args.query):
            raise catalogs.CatalogError('query must be a bounded nonempty single-line string')
        source = author.read_config(args.config)
        document = tunaos_config.validate(tunaos_config.parse(source, path=str(args.config)))
        catalog = catalogs.select(document, args.catalog, args.variant, args.release, args.platform)
        observation, keys = catalogs.bind_observation(catalog, args.config.resolve().parent)
        results = signed_apt.acquire_catalog(catalog, lambda source: keys[source['id']], datetime.now(timezone.utc))
        output = {'coverage': 'base-image-only', 'cell_coverage_complete': False,
                  'add_supported': False, 'variant': args.variant, 'release': args.release,
                  'platform': args.platform, 'base_image': observation['base_image'],
                  'warning': 'Build-script and desktop repositories are not covered, including Tailscale. Index presence does not prove installability.',
                  'sources': []}
        for result in results:
            result = dict(result)
            result['matches'] = sorted(n for n in result.pop('names') if args.query in n)
            result['expires'] = result['expires'].isoformat() if result['expires'] else None
            output['sources'].append(result)
        print(json.dumps(output, indent=2))
    except (catalogs.CatalogError, tunaos_config.ConfigError, ValueError, OSError, RecursionError) as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
