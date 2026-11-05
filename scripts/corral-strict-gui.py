#!/usr/bin/env python3
"""Run the strict harness's GUI drivers against a Corral VM.

Usage: corral-strict-gui.py <vm> <output-dir> <phase> [--context CTX]

Phases:
  install-plain, install-luks  scripts/lib/gnome_installer_driver.py on a VM
                               booted from the live ISO (the bundled installer)
  setup, login                 scripts/lib/gnome_first_boot.py on the
                               installed system's first and next boots

The drivers are the ones iso-e2e.sh runs on CI; only the transport differs:
screenshots, keys, typing and pointer clicks go through `corral` (KVM on
KubeVirt), so one GUI step takes seconds instead of a full ISO build.

Environment (defaults as on CI):
  TUNAOS_E2E_INSTALL_USER        first-boot account (tunaose2e)
  TUNAOS_FIRST_BOOT_PASSWORD     its password (gnome_first_boot.DEFAULT_PASSWORD)
  TUNAOS_WALKTHROUGH_LUKS_PASS   disk passphrase (tunaos-e2e-luks)
  TUNAOS_QUAL_SOURCE_REF         image the installer must summarize
                                 (ghcr.io/tuna-os/skipjack:gnome)
  TUNAOS_STRICT_TARGET_DISK      the summary's exact target label, e.g.
                                 "/dev/vda (59.6 GiB)" for a 64G KubeVirt
                                 PVC (CI: "/dev/vda (64 GiB)")
"""
import os
from pathlib import Path
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import gnome_first_boot, gnome_installer_driver

CORRAL = os.environ.get('CORRAL', 'corral')
PHASES = ('install-plain', 'install-luks', 'setup', 'login')


def main(argv):
    context = []
    if '--context' in argv:
        index = argv.index('--context')
        context = ['--context', argv[index + 1]]
        del argv[index:index + 2]
    if len(argv) != 3 or argv[2] not in PHASES:
        print(__doc__, file=sys.stderr)
        return 2
    vm, outdir, phase = argv
    Path(outdir).mkdir(parents=True, exist_ok=True)

    def corral(*args):
        # KubeVirt's VNC subresource drops requests while virt-api restarts;
        # a GUI step is idempotent at this level (one event or one capture).
        for attempt in range(4):
            result = subprocess.run([CORRAL, *args, *context], capture_output=True,
                                    text=True, timeout=120)
            if result.returncode == 0:
                return
            time.sleep(5 * (attempt + 1))
        raise subprocess.CalledProcessError(result.returncode, result.args,
                                            result.stdout, result.stderr)

    def capture(index, label, directory=None):
        path = os.path.abspath(f'{directory or outdir}/{phase}-{index:02d}.png')
        corral('screenshot', vm, '-o', path)
        print(f'captured {index}: {label} -> {path}', flush=True)
        return path

    def keys(*names):
        for name in names:
            corral('key', vm, *name.split('-'))  # HMP "ctrl-a" -> corral "ctrl a"

    def type_text(text):
        corral('type', vm, text)

    def pointer(_vnc, x, y, width, height, click=True):
        corral('pointer', vm, str(x), str(y), *(['--click', 'left'] if click else []))
        if click:
            # QEMU's screendump on CI omits the cursor; KubeVirt's VNC capture
            # draws it, over the label just clicked. Park it like CI sees it.
            corral('pointer', vm, str(width - 2), str(height - 2))
        return True

    if phase.startswith('install-'):
        # The live ISO bundles the measured installer, so its digest is the
        # driver's own contract constant here; CI binds it from the media.
        return gnome_installer_driver.drive(
            outdir, phase.removeprefix('install-'), None, capture, keys, type_text,
            gnome_installer_driver.BUNDLE_DIGEST,
            os.environ.get('TUNAOS_WALKTHROUGH_LUKS_PASS', 'tunaos-e2e-luks'),
            os.environ.get('TUNAOS_QUAL_SOURCE_REF', 'ghcr.io/tuna-os/skipjack:gnome'),
            pointer=pointer,
            target_disk=os.environ.get('TUNAOS_STRICT_TARGET_DISK',
                                       gnome_installer_driver.TARGET_DISK))
    return gnome_first_boot.drive(
        outdir, phase, None, capture, keys, type_text,
        os.environ.get('TUNAOS_E2E_INSTALL_USER', 'tunaose2e'),
        os.environ.get('TUNAOS_FIRST_BOOT_PASSWORD', gnome_first_boot.DEFAULT_PASSWORD),
        pointer=pointer)


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
