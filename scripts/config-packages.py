#!/usr/bin/env python3
"""Search/add native packages, plan portable additions and verify transactions.

search/add use explicit offline repository-index receipts for desktop policies.
plan resolves one intent across selected image targets from trusted collectors.
verify-transaction simulates a planned addition in a digest-pinned image.
"""
import argparse
import json
import lzma
from pathlib import Path
import sys
import tarfile
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
import subprocess

from lib import package_authoring as author
from lib import portable_add
from lib import tunaos_config


def assignments(values, option):
    result = {}
    for value in values:
        target, separator, path = value.partition('=')
        if not separator or not path or target in result:
            raise author.AuthoringError(f'{option}: expected unique TARGET=VALUE assignments')
        result[target] = path
    return result


def portable(args, source):
    """Plan or verify; the configuration is only read."""
    if args.target or args.index or args.write or args.dry_run:
        raise author.AuthoringError(f'{args.command} does not accept --target, --index, --write or --dry-run')
    if args.command == 'verify-transaction':
        if not (args.plan and args.image_target and args.image):
            raise author.AuthoringError('verify-transaction requires --plan, --image-target and --image')
        plan_bytes = author.read_file(args.plan, author.MAX_CONFIG_BYTES)
        report = portable_add.load_plan(plan_bytes)
        if report.get('query') != args.package:
            raise author.AuthoringError('plan was made for a different package intent')
        print(json.dumps(portable_add.verify_transaction(
            report, plan_bytes, args.image_target, args.image, subprocess.run), indent=2))
        return
    if args.plan or args.image_target or args.image:
        raise author.AuthoringError('plan does not accept --plan, --image-target or --image')
    document = tunaos_config.validate(tunaos_config.parse(source, args.config))
    selected = portable_add.select_targets(document, args.variant, args.flavor, args.platform)
    report = portable_add.plan(document, args.config.resolve().parent, args.package, selected,
                               assignments(args.native, '--native'), now=datetime.now(timezone.utc))
    print(json.dumps(report, indent=2))



def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('search', 'add', 'plan', 'verify-transaction'))
    parser.add_argument('package')
    parser.add_argument('--config', type=Path, default=tunaos_config.ROOT / 'tunaos.toml')
    parser.add_argument('--target', action='append', default=[], help='search/add: existing DESKTOP:FAMILY policy; repeat for all intended policies')
    parser.add_argument('--index', action='append', default=[], help='TARGET=receipt.json; native index provenance receipt')
    parser.add_argument('--native', action='append', default=[], help='TARGET=exact-native-name; explicit rename, verified against index')
    parser.add_argument('--max-age-days', type=int, default=7)
    parser.add_argument('--variant', action='append', default=[], help='plan: restrict image targets; default all')
    parser.add_argument('--flavor', action='append', default=[], help='plan: restrict image targets; default all')
    parser.add_argument('--platform', action='append', default=[], help='plan: restrict image targets; default all')
    parser.add_argument('--plan', type=Path, help='verify-transaction: plan JSON printed by plan')
    parser.add_argument('--image-target', help='verify-transaction: VARIANT:FLAVOR:PLATFORM from the plan')
    parser.add_argument('--image', help='verify-transaction: local image reference pinned by @sha256')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--dry-run', action='store_true', help='show diff only (default)')
    mode.add_argument('--write', action='store_true', help='print diff, validate, then atomically replace configuration')
    args = parser.parse_args(argv)
    try:
        if args.max_age_days < 1:
            raise author.AuthoringError('--max-age-days must be positive')
        source = author.read_config(args.config)
        if args.command in ('plan', 'verify-transaction'):
            portable(args, source)
            return 0
        if not args.target:
            raise author.AuthoringError(f'{args.command} requires --target DESKTOP:FAMILY')
        if args.variant or args.flavor or args.platform or args.plan or args.image_target or args.image:
            raise author.AuthoringError(f'{args.command} does not accept plan/verify-transaction options')
        if args.command == 'search' and (args.write or args.native):
            raise author.AuthoringError('search does not accept --write or --native')
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
    except portable_add.PortableAddError as exc:
        if exc.report is not None:
            print(json.dumps(exc.report, indent=2))
        print(f'ERROR: {exc}', file=sys.stderr)
        return 1
    except (author.AuthoringError, tunaos_config.ConfigError, ValueError, OSError,
            EOFError, lzma.LZMAError, tarfile.TarError, ET.ParseError) as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
