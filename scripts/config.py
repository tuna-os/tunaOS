#!/usr/bin/env python3
"""Validate primary TunaOS TOML or prepare its generated matrix adapter."""
import argparse
from pathlib import Path
import sys

from lib import tunaos_config, iso_builder_config


def builder_target(root, output, relative):
    """Confine stock outputs to the resolved checkout; trust explicit directories."""
    root = root.resolve()
    target = output if output is not None else root / relative
    if target.is_symlink():
        raise tunaos_config.ConfigError(f'{target}: refusing symlink')
    if output is None and not target.parent.resolve().is_relative_to(root):
        raise tunaos_config.ConfigError(f'{target}: generated output escapes checkout')
    if target.exists() and not target.is_file():
        raise tunaos_config.ConfigError(f'{target}: expected regular output file')
    return target


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('validate', 'generate', 'show', 'generate-builder-config', 'check-builder-config', 'generate-builder-flavors', 'check-builder-flavors', 'generate-debian-contract', 'prepare-debian-context', 'verify-debian-image'))
    parser.add_argument('--root', type=Path, default=tunaos_config.ROOT)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--image')
    parser.add_argument('--variant')
    parser.add_argument('--desktop')
    parser.add_argument('--platform')
    args = parser.parse_args()
    try:
        if args.command in ('generate-builder-config', 'check-builder-config', 'generate-builder-flavors', 'check-builder-flavors'):
            flavors = args.command.endswith('-flavors')
            render = iso_builder_config.render_flavors if flavors else iso_builder_config.render
            content = render(tunaos_config.load(args.root / 'tunaos.toml'))
            target = builder_target(args.root, args.output, 'docs/iso-builder.flavors.json' if flavors else 'docs/iso-builder.config.json')
            if args.command.startswith('check-'):
                if not target.is_file() or target.read_text(encoding='utf-8') != content:
                    raise tunaos_config.ConfigError(f'{target}: generated builder config drift; run generate-builder-config')
            else:
                target.write_text(content, encoding='utf-8')
            print(target)
            return 0
        elif args.command == 'verify-debian-image':
            if not all((args.image, args.variant, args.desktop, args.platform)):
                parser.error('verify-debian-image requires --image, --variant, --desktop and --platform')
            import hashlib
            import subprocess
            source = (args.root / 'tunaos.toml').read_bytes()
            document = tunaos_config.validate(tunaos_config.parse(source, args.root / 'tunaos.toml'))
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
