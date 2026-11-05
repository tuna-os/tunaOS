#!/usr/bin/env python3
"""Drive GNOME first boot on a Corral VM with the strict harness's driver.

Usage: corral-first-boot.py <vm> <output-dir> setup|login [--context CTX]

Runs scripts/lib/gnome_first_boot.py, the driver iso-e2e.sh runs on the
strict installed boots, against a Corral VM (KVM on KubeVirt): screenshots,
keys, typing and pointer clicks all go through `corral`. Same driver, same
evidence file (first-boot-<phase>.json), minutes per iteration instead of a
full ISO build and install.

Account: TUNAOS_E2E_INSTALL_USER / TUNAOS_FIRST_BOOT_PASSWORD
(default tunaose2e / gnome_first_boot.DEFAULT_PASSWORD).
"""
import os
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.gnome_first_boot import DEFAULT_PASSWORD, drive

CORRAL = os.environ.get('CORRAL', 'corral')


def main(argv):
    context = []
    if '--context' in argv:
        index = argv.index('--context')
        context = ['--context', argv[index + 1]]
        del argv[index:index + 2]
    if len(argv) != 3 or argv[2] not in ('setup', 'login'):
        print(__doc__, file=sys.stderr)
        return 2
    vm, outdir, phase = argv
    Path(outdir).mkdir(parents=True, exist_ok=True)

    def corral(*args):
        subprocess.run([CORRAL, *args, *context], check=True, capture_output=True,
                       text=True, timeout=120)

    def capture(index, label, directory=None):
        path = os.path.abspath(f'{directory or outdir}/first-boot-{phase}-{index:02d}.png')
        corral('screenshot', vm, '-o', path)
        print(f'captured {index}: {label} -> {path}', flush=True)
        return path

    def keys(*names):
        for name in names:
            corral('key', vm, *name.split('-'))  # HMP "ctrl-a" -> corral "ctrl a"

    def type_text(text):
        corral('type', vm, text)

    def pointer(_vnc, x, y, _width, _height, click=True):
        corral('pointer', vm, str(x), str(y), *(['--click', 'left'] if click else []))
        return True

    return drive(outdir, phase, None, capture, keys, type_text,
                 os.environ.get('TUNAOS_E2E_INSTALL_USER', 'tunaose2e'),
                 os.environ.get('TUNAOS_FIRST_BOOT_PASSWORD', DEFAULT_PASSWORD),
                 pointer=pointer)


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
