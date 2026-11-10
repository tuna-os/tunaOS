"""Real retained KDE installer PNGs through the driver's own OCR; run by the
Test workflow's OCR job. Not named test_*.py: the unit suite fakes OCR.
"""
import hashlib
from pathlib import Path
import shutil
import sys

import pytest

ROOT = Path(__file__).parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
from lib import kde_installer_driver as kd  # noqa: E402

FIXTURES = ROOT / 'tests/fixtures/kde-installer'


def screen(name, digest):
    assert shutil.which('tesseract'), 'Tesseract is required, not an optional skip'
    capture = FIXTURES / name
    assert hashlib.sha256(capture.read_bytes()).hexdigest() == digest
    return kd.Screen(capture)


def test_grouper_confirm_page_reads_the_intended_plain_install():
    # iso-builder run 42804025401, walkthrough-plain frame 12: the driver
    # clicked Install from this frame.
    page = screen('confirm42804025401-plain-12.png',
                  'a272db39ae23a7a1dc81623dc762b63f3b55df8ece15389c04509d358b889596')
    assert page.state == 'confirm'
    kd.verify_confirm(page, kd.confirm_reads(page), 'No encryption', 'tunaose2e')
    with pytest.raises(kd.Unverified):
        kd.verify_confirm(page, kd.confirm_reads(page), 'Passphrase', 'tunaose2e')


def test_grouper_progress_page_names_the_product():
    # Same run, frame 19: fisherman's "Installing OS" step under way.
    page = screen('progress42804025401-plain-19.png',
                  'a78e29bf25e37e6802c69a6df7f8150e0af8568fcb23b59c908fe38fed29730d')
    assert page.state == 'progress'
    assert any(kd.normal(line).startswith('installing grouper') for line in page.lines)


def test_grouper_failure_page_is_failed():
    # Same run, frame 20: fisherman exited 1 (tunaOS#4485).
    page = screen('failed42804025401-plain-20.png',
                  '5758bb9e50afd751d6539d8fa5ddecd6d2f5f7726f2eae097a6f3f5f3ac5ae90')
    assert page.state == 'failed'


def test_done_page_is_known_without_reading_the_restart_button():
    # tuna-os/bootc-installer@e7c42026 frontends/kde/docs/screenshots/07-done.png:
    # OCR reads the button "tart now" (icon plus mnemonic underline).
    page = screen('done-bootc-installer-07.png',
                  '003954754cc1a986e595210de8bf65bf937d5c2b88a5715baab8d6c7c2fe0e23')
    assert page.state == 'done' and page.has('TunaOS is installed')
