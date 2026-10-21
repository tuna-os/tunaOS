#!/usr/bin/env python3
"""Search/add native packages using explicit offline repository-index receipts."""
import argparse
import json
import lzma
from pathlib import Path
import sys
import tarfile
import xml.etree.ElementTree as ET

from lib import package_authoring as author
from lib import tunaos_config


def assignments(values, option):
    result = {}
    for value in values:
        target, separator, path = value.partition('=')
        if not separator or not path or target in result:
            raise author.AuthoringError(f'{option}: expected unique TARGET=VALUE assignments')
        result[target] = path
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('search', 'add'))
    parser.add_argument('package')
    parser.add_argument('--config', type=Path, default=tunaos_config.ROOT / 'tunaos.toml')
    parser.add_argument('--target', action='append', required=True, help='existing DESKTOP:FAMILY policy; repeat for all intended policies')
    parser.add_argument('--index', action='append', default=[], help='TARGET=receipt.json; native index provenance receipt')
    parser.add_argument('--native', action='append', default=[], help='TARGET=exact-native-name; explicit rename, verified against index')
    parser.add_argument('--max-age-days', type=int, default=7)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--dry-run', action='store_true', help='show diff only (default)')
    mode.add_argument('--write', action='store_true', help='print diff, validate, then atomically replace configuration')
    args = parser.parse_args(argv)
    try:
        if args.max_age_days < 1:
            raise author.AuthoringError('--max-age-days must be positive')
        if args.command == 'search' and (args.write or args.native):
            raise author.AuthoringError('search does not accept --write or --native')
        source = author.read_config(args.config)
        indexes = assignments(args.index, '--index')
        if args.command == 'search':
            document = tunaos_config.validate(tunaos_config.parse(source, args.config))
            scope = author.targets(document, args.target)
            if set(indexes) != set(scope):
                raise author.AuthoringError('--index TARGET=RECEIPT is required exactly once for every selected target')
            output = []
            for target, (_, family) in scope.items():
                names, receipt = author.load_index(indexes[target], family, args.max_age_days)
                output.append({'target': target, 'matches': sorted(name for name in names if args.package in name), 'evidence': receipt})
            print(json.dumps(output, indent=2))
        else:
            document, scope, resolved, evidence = author.plan(
                source, args.target, indexes, args.package,
                assignments(args.native, '--native'), args.max_age_days, source_path=args.config)
            result = author.edit(source, document, scope, resolved)
            print(json.dumps({'resolved': resolved, 'evidence': evidence}, indent=2))
            print('Scope: shared desktop/family policies. Index presence is not per-variant or transaction verification.')
            print(author.diff(source, result, args.config), end='')
            if args.write:
                author.atomic_write(args.config, source, result)
            print('No change.' if source == result else 'Written atomically.' if args.write else 'Dry run; use --write to apply.')
    except (author.AuthoringError, tunaos_config.ConfigError, ValueError, OSError,
            EOFError, lzma.LZMAError, tarfile.TarError, ET.ParseError) as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
