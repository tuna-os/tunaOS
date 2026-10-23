"""Real retained PNG OCR regression; explicitly run by the Test workflow's OCR job.

Not named test_*.py: the dependency-light unit suite tests the parser separately.
This file is selected explicitly by the GNOME summary OCR job and never skips.
"""
import hashlib
import importlib.util
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).parents[2]
spec = importlib.util.spec_from_file_location('gnome_driver', ROOT / 'scripts/lib/gnome_installer_driver.py')
driver = importlib.util.module_from_spec(spec)
spec.loader.exec_module(driver)
FIXTURES = ROOT / 'tests/fixtures/gnome-installer'


@pytest.mark.parametrize('mode,digest', [
    ('plain', '03366a2b7d9a26c3d519a8c8ac9f92ee28041a1004b5dec969900886a46e00ab'),
    ('luks', '3ab8f7680f15673308aa0ecd9562fc4f0293ad7d439a68d3be0971a5683867ff'),
])
def test_retained_summary_png_exact_pre_submit_proof(tmp_path, monkeypatch, mode, digest):
    assert shutil.which('convert'), 'ImageMagick is required, not an optional skip'
    assert shutil.which('tesseract'), 'Tesseract is required, not an optional skip'
    capture = FIXTURES / f'summary39891435048-{mode}.png'
    assert hashlib.sha256(capture.read_bytes()).hexdigest() == digest
    screen = driver.Screen(capture)
    assert screen.state == 'summary'
    with pytest.raises(driver.Unverified):
        screen.box('Disk')  # Reproduce the old whole-line/icon failure on real pixels.

    calls = []
    actual_run = driver.subprocess.run
    def recorded(command, **kwargs):
        calls.append(command)
        return actual_run(command, **kwargs)
    monkeypatch.setattr(driver.subprocess, 'run', recorded)
    driver.verify_summary(screen, mode)
    converts = [command for command in calls if command[0] == 'convert']
    assert len(converts) == 2
    assert [command[command.index('-crop')+1] for command in converts] == [
        '560x45+390+335', '560x45+390+500']
    assert all('-threshold' not in command and '300%' in command for command in converts)
    assert all(command[command.index('--psm')+1] == '6'
               for command in calls if command[0] == 'tesseract')

    # Preserve the rejected thresholded approach as a real-image negative.
    prepared = tmp_path / 'threshold.png'
    actual_run(['convert', str(capture), '-crop', '560x45+390+335', '+repage',
                '-resize', '300%', '-colorspace', 'gray', '-threshold', '90%',
                str(prepared)], capture_output=True, timeout=20, check=True)
    result = actual_run(['tesseract', str(prepared), 'stdout', '--psm', '6', 'tsv'],
                        capture_output=True, text=True, timeout=30, check=True)
    cards = screen.summary_cards()
    _, cards['Disk'] = driver.ocr_rows(result.stdout, strict=True)
    with pytest.raises(driver.Unverified):
        driver.verify_summary_cards(cards, mode)
