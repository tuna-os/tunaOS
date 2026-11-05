"""Fail-closed GUI driver for the installed system's first boot and GDM login.

Contract read from the shipped image (gnome-initial-setup-50.0, gdm-50.0,
vendor.conf skips only the software page): with no account on the installed
disk, GDM starts GNOME Initial Setup, whose About You and password pages
create the account; "Start Using <product>" opens that account's session.
The next boot must offer that account at the GDM greeter, and only a user
session draws the shell overview's "Type to search" entry.

Input is hardware key events and VNC pointer clicks. No guest execution.
"""
import json
from pathlib import Path
import re
import struct
import subprocess
import tempfile
import time

from lib.gnome_installer_driver import Unverified, click_unix, normal, ocr_rows

USER_PATTERN = r'[a-z][a-z0-9]{2,31}'


class Screen:
    """OCR rows of one PNG capture, classified into first-boot states."""

    def __init__(self, path):
        self.path = Path(path)
        with self.path.open('rb') as source:
            header = source.read(24)
        if header[:8] != b'\x89PNG\r\n\x1a\n':
            raise Unverified('capture is not PNG')
        self.width, self.height = struct.unpack('!II', header[16:24])
        if not (640 <= self.width <= 1920 and 480 <= self.height <= 1200):
            raise Unverified('unsupported framebuffer dimensions')
        rows = []
        # GIS draws dark text on light pages; GDM draws light text on dark.
        for threshold in ('-threshold 60%', '-negate -threshold 60%'):
            with tempfile.NamedTemporaryFile(suffix='.png') as prepared:
                subprocess.run(['convert', str(path), '-colorspace', 'gray',
                                *threshold.split(), prepared.name],
                               capture_output=True, timeout=20, check=True)
                result = subprocess.run(['tesseract', prepared.name, 'stdout',
                                         '--psm', '11', 'tsv'],
                                        capture_output=True, text=True, timeout=30, check=True)
            rows.extend(ocr_rows(result.stdout)[1])
        self.rows = rows
        self.lines = [row[0] for row in rows]
        self.state = classify(self.lines)

    def box(self, label):
        boxes = {box for text, box in self.rows if normal(text) == normal(label)}
        if len(boxes) != 1:
            raise Unverified(f'expected one exact control label: {label}; got {len(boxes)}')
        box = boxes.pop()
        if not (0 <= box[0] < box[2] <= self.width and 0 <= box[1] < box[3] <= self.height):
            raise Unverified('control box is outside the capture')
        return box

    def has(self, label):
        return any(normal(text) == normal(label) for text in self.lines)


def classify(lines):
    text = {normal(line) for line in lines}
    joined = '\n'.join(text)
    if any(line.startswith('start using ') for line in text):
        return 'setup-complete'
    if 'about you' in text or 'full name' in text:
        return 'account'
    if 'set a password' in joined or 'confirm password' in joined:
        return 'password'
    if 'next' in text:
        return 'setup-page'
    if 'type to search' in text:
        return 'session'
    if 'password' in text:
        return 'greeter-password'
    return 'unknown'


def drive(outdir, phase, vnc, capture, keys, type_text, user, password,
          screen_factory=Screen, pointer=click_unix, sleep=time.sleep, clock=time.monotonic):
    """phase=setup creates the account in GNOME Initial Setup; phase=login
    proves the greeter offers it and that its password opens a session."""
    evidence = {'driver': 'gnome-first-boot-gis50', 'phase': phase, 'user': user,
                'frames': [], 'clicks': [], 'pages': [], 'completed': False}
    deadline = clock() + 900
    counter = 0
    private = tempfile.TemporaryDirectory(prefix='tunaos-first-boot-')
    secret = False

    def observe(label):
        nonlocal counter
        if clock() >= deadline or counter >= 96:
            raise Unverified('first-boot observation deadline/frame bound exceeded')
        path = capture(counter, label, directory=private.name) if secret else capture(counter, label)
        counter += 1
        if not path:
            raise Unverified('GUI capture unavailable')
        screen = screen_factory(path)
        evidence['frames'].append({'state': screen.state, 'private': True} if secret else
                                  {'file': Path(path).name, 'state': screen.state,
                                   'text': screen.lines})
        return screen

    def click(screen, label):
        box = screen.box(label)
        point = [(box[0] + box[2]) // 2, (box[1] + box[3]) // 2]
        evidence['clicks'].append({'label': label, 'state': screen.state,
                                   'box': list(box), 'point': point})
        if pointer(vnc, *point, screen.width, screen.height) is not True:
            raise Unverified('pointer transport did not acknowledge release')
        sleep(2)

    def wait_for(states, label, polls=40):
        for _ in range(polls):
            screen = observe(label)
            if screen.state in states:
                return screen
            sleep(5)
        raise Unverified(f'no {"/".join(states)} frame within bound')

    try:
        if phase not in ('setup', 'login'):
            raise Unverified('unsupported first-boot phase')
        if not re.fullmatch(USER_PATTERN, user) or not re.fullmatch('[a-z0-9_.-]{8,64}', password):
            raise Unverified('unsupported test account or password format')
        if phase == 'setup':
            screen = wait_for(('setup-page', 'account', 'password', 'setup-complete'), 'await-setup')
            for _ in range(16):
                evidence['pages'].append(screen.state)
                if screen.state == 'setup-complete':
                    product = next(line for line in screen.lines
                                   if normal(line).startswith('start using '))
                    click(screen, product)
                    screen = wait_for(('session',), 'await-session')
                    evidence['completed'] = True
                    return 0
                if screen.state == 'account':
                    # Full Name has focus; GIS derives the username from it.
                    type_text(user)
                    sleep(2)
                    screen = observe('verify-account')
                    if screen.state != 'account' or not screen.has(user):
                        raise Unverified('typed account name not shown on About You')
                    evidence['account_name_observed'] = True
                elif screen.state == 'password':
                    secret = True
                    type_text(password)
                    keys('tab')
                    type_text(password)
                    sleep(2)
                    screen = observe('verify-password')
                    if screen.state != 'password':
                        raise Unverified('password input left the password page')
                elif screen.state != 'setup-page':
                    raise Unverified(f'unexpected first-boot state: {screen.state}')
                previous = screen.state
                click(screen, 'Next')
                secret = False
                screen = wait_for(('setup-page', 'account', 'password', 'setup-complete'),
                                  'after-' + previous, polls=12)
            raise Unverified('initial setup did not complete within page bound')
        screen = wait_for(('greeter-password', 'unknown'), 'await-greeter')
        if not screen.has(user):
            # GDM lists accounts before the password prompt opens.
            screen = wait_for(('unknown', 'greeter-password'), 'await-user-list', polls=12)
            if not screen.has(user):
                raise Unverified('GDM greeter does not offer the GUI-created account')
        evidence['greeter_offers_account'] = True
        if screen.state != 'greeter-password':
            click(screen, user)
        secret = True
        type_text(password)
        keys('ret')
        secret = False
        sleep(5)
        screen = wait_for(('session',), 'await-session')
        evidence['completed'] = True
        return 0
    except (Unverified, OSError, subprocess.SubprocessError, ValueError, StopIteration) as exc:
        evidence['error'] = str(exc)
        print(f'not ok - GNOME first-boot {phase}: {exc}', flush=True)
        return 1
    finally:
        private.cleanup()
        Path(outdir, f'first-boot-{phase}.json').write_text(json.dumps(evidence, indent=2) + '\n')
        print(f'ok - GNOME first-boot {phase} completed' if evidence['completed'] else
              f'# GNOME first-boot {phase} not proven', flush=True)
