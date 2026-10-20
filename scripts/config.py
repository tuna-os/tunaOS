#!/usr/bin/env python3
"""Validate primary TunaOS TOML or prepare its generated matrix adapter."""
import argparse
from pathlib import Path
import sys

from lib import tunaos_config


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('validate', 'generate', 'show'))
    parser.add_argument('--root', type=Path, default=tunaos_config.ROOT)
    args = parser.parse_args()
    try:
        if args.command == 'generate':
            print(tunaos_config.prepare(args.root))
        else:
            config = tunaos_config.load(args.root / 'tunaos.toml')
            if args.command == 'show':
                print(tunaos_config.render(config), end='')
            else:
                print('Primary TunaOS matrix configuration is valid.')
    except (tunaos_config.ConfigError, OSError) as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
