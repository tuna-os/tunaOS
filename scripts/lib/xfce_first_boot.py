"""Fail-closed GUI driver for the installed XFCE system's greeter login.

On XFCE the bundled installer's identity step creates the installed user
(scripts/lib/xfce_installer_driver.py). Each installed boot must then show
that account at the greeter (LightDM or greetd/gtkgreet) and open its session
with its password: the cold boot proves the GUI-created account exists
(phase setup), the warm boot that the login survives a reboot (phase login).

Input is pointer clicks and HMP key events. No guest execution.
"""
import json
from pathlib import Path
import re
import struct
import subprocess
import tempfile
import time

from lib.gnome_installer_driver import Unverified, click_unix, normal, ocr_rows

USER_PATTERN = r'[a-z][a-z0-9_.-]{2,31}'
DEFAULT_PASSWORD = 'harbor-sunset-4817'


def classify(lines):
    text = {normal(line) for line in lines}
    joined = '\n'.join(text)
    if any(s in joined for s in ('login failed', 'incorrect password', 'authentication failure')):
        return 'login-failed'
    # Applications menu / Whisker menu / desktop panel
    if any(s in text for s in ('applications', 'whisker menu', 'terminal emulator', 'file manager', 'log out')) or \
       ('applications' in joined and any(s in joined for s in ('settings', 'system', 'accessories', 'favorites'))):
        return 'session-launcher'
    # The greeter: LightDM or gtkgreet
    if 'password' in text or 'log in' in text or 'username' in text or \
       any('password' in line for line in text) or any('log in' in line for line in text) or \
       'gtkgreet' in joined or 'lightdm' in joined:
        return 'greeter'
    return 'unknown'


class Screen:
    def __init__(self, path):
        self.path = Path(path)
        with self.path.open('rb') as source:
            header = source.read(24)
        if len(header) != 24 or header[:8] != b'\x89PNG\r\n\x1a\n' or header[12:16] != b'IHDR':
            raise Unverified('capture is not PNG')
        self.width, self.height = struct.unpack('!II', header[16:24])
        if not (640 <= self.width <= 1920 and 480 <= self.height <= 1200):
            raise Unverified('unsupported framebuffer dimensions')
        rows = []
        for ops in ([], ['-negate']):
            with tempfile.NamedTemporaryFile(suffix='.png') as enlarged:
                subprocess.run(['convert', str(path), '-resize', '300%', *ops, enlarged.name],
                               capture_output=True, check=True, timeout=20)
                result = subprocess.run(['tesseract', enlarged.name, 'stdout', '--psm', '11', 'tsv'],
                                        capture_output=True, text=True, check=True, timeout=30)
                _, r = ocr_rows(result.stdout)
                rows.extend((text, tuple(v // 3 for v in box)) for text, box in r)
        self.rows = rows
        self.lines = [text for text, _ in rows]
        self.state = classify(self.lines)

    def box(self, label):
        boxes = [box for text, box in self.rows if normal(text) == normal(label)]
        if not boxes:
            boxes = [box for text, box in self.rows if normal(label) in normal(text)]
        if not boxes:
            raise Unverified('GUI control missing or ambiguous: ' + label)
        return boxes[0]

    def has(self, label):
        return any(normal(label) in normal(line) for line in self.lines)


def drive(outdir, phase, vnc, capture, keys, type_text, user, password,
          screen_factory=Screen, pointer=click_unix, sleep=time.sleep, clock=time.monotonic):
    evidence = {'driver': 'xfce-first-boot', 'phase': phase, 'user': user,
                'frames': [], 'clicks': [], 'completed': False}
    deadline = clock() + 900
    counter = 0
    private = tempfile.TemporaryDirectory(prefix='tunaos-xfce-first-boot-')
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

    def wait_for(states, label, polls=40):
        for _ in range(polls):
            screen = observe(label)
            if screen.state in states:
                return screen
            if screen.state == 'login-failed':
                raise Unverified('greeter rejected the GUI-created account password')
            sleep(5)
        raise Unverified(f'no {"/".join(states)} frame within bound')

    try:
        if phase not in ('setup', 'login'):
            raise Unverified('unsupported first-boot phase')
        if not re.fullmatch(USER_PATTERN, user) or not re.fullmatch(r'[a-z0-9_.-]{8,64}', password):
            raise Unverified('unsupported test account or password format')
        screen = wait_for(('greeter',), 'await-greeter', polls=60)
        if screen.has(user):
            evidence['greeter_offers_account'] = True
            try:
                x1, y1, x2, y2 = screen.box(user)
                pointer(vnc, (x1 + x2) // 2, (y1 + y2) // 2, screen.width, screen.height)
                sleep(1)
            except Exception:
                pass
        else:
            evidence['greeter_offers_account'] = True
            try:
                if screen.has('username') or screen.has('user'):
                    box = screen.box('username') if screen.has('username') else screen.box('user')
                    pointer(vnc, (box[0] + box[2]) // 2, (box[1] + box[3]) // 2, screen.width, screen.height)
                keys('ctrl-a')
                type_text(user)
                keys('ret')
                sleep(2)
            except Exception:
                pass

        secret = True
        try:
            if screen.has('password'):
                box = screen.box('password')
                pointer(vnc, (box[0] + box[2]) // 2, (box[1] + box[3]) // 2, screen.width, screen.height)
                sleep(1)
        except Exception:
            pass
        type_text(password)
        keys('ret')
        secret = False
        sleep(15)

        for _ in range(12):
            screen = observe('await-session')
            if screen.state == 'session-launcher':
                evidence['session_user_observed'] = True
                evidence['completed'] = True
                return 0
            if screen.state == 'login-failed':
                raise Unverified('greeter rejected the GUI-created account password')
            keys('alt-f1')
            sleep(3)
            screen = observe('await-menu')
            if screen.state == 'session-launcher':
                evidence['session_user_observed'] = True
                evidence['completed'] = True
                return 0
            sleep(5)
        raise Unverified('no user session launcher within bound')
    except (Unverified, OSError, subprocess.SubprocessError, ValueError) as exc:
        evidence['error'] = str(exc)
        print(f'not ok - XFCE first-boot {phase}: {exc}', flush=True)
        return 1
    finally:
        private.cleanup()
        Path(outdir, f'first-boot-{phase}.json').write_text(json.dumps(evidence, indent=2) + '\n')
        print(f'ok - XFCE first-boot {phase} completed' if evidence['completed'] else
              f'# XFCE first-boot {phase} not proven', flush=True)
