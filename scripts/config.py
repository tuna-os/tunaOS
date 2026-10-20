#!/usr/bin/env python3
"""Validate primary TunaOS TOML or prepare its generated matrix adapter."""
import argparse
from pathlib import Path
import sys

from lib import tunaos_config, iso_builder_config


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('validate', 'generate', 'show', 'generate-builder-config', 'check-builder-config', 'generate-debian-contract', 'prepare-debian-context', 'verify-debian-image'))
    parser.add_argument('--root', type=Path, default=tunaos_config.ROOT)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--image')
    parser.add_argument('--variant')
    parser.add_argument('--desktop')
    parser.add_argument('--platform')
    args = parser.parse_args()
    try:
        if args.command in ('generate-builder-config', 'check-builder-config'):
            content = iso_builder_config.render(tunaos_config.load(args.root / 'tunaos.toml'))
            target = args.output or args.root / 'docs/iso-builder.config.json'
            if args.command == 'check-builder-config':
                if not target.is_file() or target.read_text() != content:
                    raise tunaos_config.ConfigError(f'{target}: generated builder config drift; run generate-builder-config')
            else:
                if target.is_symlink():
                    raise tunaos_config.ConfigError(f'{target}: refusing symlink')
                target.write_text(content)
            print(target)
        elif args.command == 'verify-debian-image':
            if not all((args.image, args.variant, args.desktop, args.platform)):
                parser.error('verify-debian-image requires --image, --variant, --desktop and --platform')
            import hashlib
            import subprocess
            source = (args.root / 'tunaos.toml').read_bytes()
            document = tunaos_config.validate(tunaos_config.tomllib.loads(source.decode('utf-8')))
            policy = tunaos_config.package_policy()
            try:
                expected = policy.installation_contract(document, hashlib.sha256(source).hexdigest(),
                                                       args.variant, args.desktop, args.platform,
                                                       manager='apt', os_id='debian')
                policy.verify_debian_image_receipt(args.image, expected, subprocess.run)
            except policy.PolicyError as exc:
                raise tunaos_config.ConfigError(str(exc)) from exc
            print('Required Debian desktop packages are installed and the source/cell receipt matches.')
        elif args.command == 'prepare-debian-context':
            if not all((args.output, args.variant, args.desktop, args.platform)):
                parser.error('prepare-debian-context requires --output, --variant, --desktop and --platform')
            print(tunaos_config.prepare_debian_build_context(args.root, args.output, args.variant, args.desktop, args.platform.split(',')))
        elif args.command == 'generate-debian-contract':
            if not all((args.variant, args.desktop, args.platform)):
                parser.error('generate-debian-contract requires --variant, --desktop and --platform')
            print(tunaos_config.prepare_debian_contract(args.root, args.variant, args.desktop, args.platform))
        elif args.command == 'generate':
            print(tunaos_config.prepare(args.root))
        else:
            config = tunaos_config.load(args.root / 'tunaos.toml')
            if args.command == 'show':
                print(tunaos_config.render(config), end='')
            else:
                print('Primary TunaOS configuration is valid.')
    except (tunaos_config.ConfigError, iso_builder_config.ConfigError, OSError) as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
