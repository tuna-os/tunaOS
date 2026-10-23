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


@pytest.mark.parametrize('run,mode,digest', [
    ('39891435048', 'plain', '03366a2b7d9a26c3d519a8c8ac9f92ee28041a1004b5dec969900886a46e00ab'),
    ('39891435048', 'luks', '3ab8f7680f15673308aa0ecd9562fc4f0293ad7d439a68d3be0971a5683867ff'),
    ('39897665901', 'plain', 'a4fbaa61eaea3c4770887ee3cece3610b5f13e0def77d8eb27aac835c81249e3'),
    ('39897665901', 'luks', '0199885943d43721a26a7e00caa15cb0565d359a48156de21183cf3617cac405'),
])
def test_retained_summary_png_exact_pre_submit_proof(tmp_path, monkeypatch, run, mode, digest):
    assert shutil.which('convert'), 'ImageMagick is required, not an optional skip'
    assert shutil.which('tesseract'), 'Tesseract is required, not an optional skip'
    capture = FIXTURES / f'summary{run}-{mode}.png'
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
    box, point = driver.control_target(screen, 'Install', enabled=True)
    assert box == (618, 588, 662, 599)
    assert point == [640, 593]
    # Resolving a target never invokes the transport or submits installation.
    converts = [command for command in calls if command[0] == 'convert' and '-crop' in command]
    assert len(converts) == 3
    assert [command[command.index('-crop')+1] for command in converts] == [
        '560x45+390+335', '560x45+390+500', '70x30+605+579']
    assert all('-threshold' not in command and '300%' in command for command in converts)
    assert [command[command.index('--psm')+1]
            for command in calls if command[0] == 'tesseract'] == ['6', '6', '7']
    assert '-negate' in converts[-1]
    # Original pixels must independently prove the enabled button and boundary.
    original_rgb = screen.rgb
    for altered_point, replacement in [((610, 594), (220, 220, 220)),
                                       ((580, 594), (145, 65, 172)),
                                       ((640, 580), (250, 250, 251))]:
        monkeypatch.setattr(screen, 'rgb', lambda x, y, p=altered_point, c=replacement:
                            c if (x, y) == p else original_rgb(x, y))
        with pytest.raises(driver.Unverified):
            driver.control_target(screen, 'Install', enabled=True)
    monkeypatch.setattr(screen, 'rgb', original_rgb)
    screen.rows.append(('Install', (800, 580, 850, 600)))
    with pytest.raises(driver.Unverified):
        driver.control_target(screen, 'Install', enabled=True)
    screen.rows.pop()

    # Preserve the rejected thresholded approach as a real-image negative.
    prepared = tmp_path / 'threshold.png'
    actual_run(['convert', str(capture), '-crop', '560x45+390+335', '+repage',
                '-resize', '300%', '-colorspace', 'gray', '-threshold', '90%',
                str(prepared)], capture_output=True, timeout=20, check=True)
    result = actual_run(['tesseract', str(prepared), 'stdout', '--psm', '6', 'tsv'],
                        capture_output=True, text=True, timeout=30, check=True)
    cards = screen.summary_cards()
    with pytest.raises(driver.Unverified):
        _, cards['Disk'] = driver.ocr_rows(result.stdout, strict=True)
        driver.verify_summary_cards(cards, mode)


@pytest.mark.parametrize('name,digest,title,elapsed,percent', [
    ('plain-07', '9e6e8016f971721ed90a23651e5070157e56396b3aa02ad8509fe3474873a890', 'Almost ready...', '0:00 elapsed', '1%'),
    ('plain-18', 'a547c6bb2986fce8fc86874fe109a9273bb1093aedd83a6943a831c3cf59f639', 'Installing Skipjack...', '2:03 elapsed', '24%'),
    ('luks-09', '85cdbfc135619ae100656d73620be8720dbd6353ac7e72255dd3cd41779a7bce', 'Securing your drive...', '0:00 elapsed', '1%'),
    ('luks-20', '388f0b59ee422ae14afdf1c492943ae867b9927a661e381e9fd72ebbfa3a433f', 'Installing Skipjack...', '1:59 elapsed', '25%'),
])
def test_retained_progress_png_same_frame_proof(monkeypatch, name, digest, title, elapsed, percent):
    capture = FIXTURES / f'progress39932865285-{name}.png'
    assert hashlib.sha256(capture.read_bytes()).hexdigest() == digest
    screen = driver.Screen(capture)
    assert driver.classify(screen.lines) == 'unknown'  # Old full-frame OCR still fails.
    assert screen.state == 'progress'
    assert screen.progress_markers == [title, 'Do not power off the computer.', elapsed, percent]
    assert driver.classify(screen.progress_markers) != 'done'
    # A modelled modal dims the original lower panel; the text crop alone
    # cannot establish foreground progress. This is not a captured modal image.
    original_rgb = screen.rgb
    monkeypatch.setattr(screen, 'rgb', lambda x, y: (180, 180, 180))
    screen.state = 'unknown'
    screen.verify_progress_panel()
    assert screen.state == 'unknown'
    monkeypatch.setattr(screen, 'rgb', original_rgb)
    screen.rows.append((title, (230, 675, 450, 692)))
    screen.verify_progress_panel()
    assert screen.state == 'unknown'


@pytest.mark.parametrize('mode,initial,last', [('plain', '07', '18'), ('luks', '09', '20')])
def test_retained_progress_uses_completion_budget_without_more_input(tmp_path, mode, initial, last):
    # Real progress pixels inside a model transaction; pointer/key functions
    # are test doubles. Repeated progress must never become completion.
    spec = importlib.util.spec_from_file_location('driver_unit_fixture', ROOT / 'tests/test_gnome_installer_driver.py')
    unit = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(unit)
    first = unit.driver.Screen(FIXTURES / f'progress39932865285-{mode}-{initial}.png')
    later = unit.driver.Screen(FIXTURES / f'progress39932865285-{mode}-{last}.png')
    if mode == 'plain':
        prefix = [unit.FakeScreen('welcome'), unit.FakeScreen('encryption', encrypted=True),
                  unit.FakeScreen('encryption'), unit.FakeScreen('summary')]
    else:
        prefix = [unit.FakeScreen('welcome'), unit.FakeScreen('encryption', encrypted=True, tpm=True),
                  unit.FakeScreen('encryption', encrypted=True), unit.FakeScreen('encryption', encrypted=True),
                  unit.FakeScreen('encryption', encrypted=True), unit.FakeScreen('summary', mode='luks')]
    rc, evidence, events = unit.execute(tmp_path, prefix + [first] + [later] * 80, mode)
    assert rc == 1 and evidence['accepted'] and not evidence['completed']
    assert evidence['transitions'] == ['welcome', 'encryption', 'summary', 'progress']
    assert sum(event == ('capture', 'await-completion') for event in events) == 80
    accepted = events.index(('capture', 'await-progress'))
    assert all(event[0] == 'capture' for event in events[accepted:])
