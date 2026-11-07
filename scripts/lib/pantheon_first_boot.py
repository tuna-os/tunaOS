"""Fail-closed GUI driver for the installed Pantheon system's greeter login.

On Pantheon (gurnard:pantheon), LightDM manages the display and launches
io.elementary.greeter. Each installed boot must show the expected account at the
LightDM greeter and open its session with its password: the cold boot proves the
account exists and is offered (phase setup), the warm boot that the login
survives a reboot (phase login).

Input is hardware key events and VNC pointer clicks. No guest execution.
"""
import json
import re
import subprocess
import tempfile
import time
from pathlib import Path

from lib.gnome_installer_driver import Unverified, click_unix, normal

USER_PATTERN = r'[a-z][a-z0-9]{2,31}'
# Typed at the greeter; test-only.
DEFAULT_PASSWORD = 'harbor-sunset-4817'


def classify(lines):
    text = {normal(line) for line in lines}
    joined = '\n'.join(text)
    if any(k in joined for k in ('login failed', 'incorrect password', 'authentication failure')):
        return 'login-failed'
    # The io.elementary.greeter: user card/avatar and its password prompt.
    if 'password' in text and ('log in' in text or 'pantheon' in text or 'elementary' in text
                               or 'guest' in text or 'session' in text
                               or any('password' in line for line in text)):
        return 'greeter'
    # Slingshot / Applications menu, opened with Meta: only a user session draws it.
    if any(line.startswith('search') for line in text) or 'applications' in text:
        return 'session-launcher'
    return 'unknown'


class Screen:
    """Pantheon screen OCR representation."""

    def __init__(self, path):
        self.path = Path(path)
        self.width, self.height = 1280, 800
        # When actual images are read, tesseract processes them
        self.lines = []
        try:
            with tempfile.NamedTemporaryFile(suffix='.png') as enlarged:
                subprocess.run(['convert', str(path), '-resize', '300%', enlarged.name],
                               capture_output=True, check=True, timeout=20)
                result = subprocess.run(['tesseract', enlarged.name, 'stdout', '--psm', '11', 'tsv'],
                                        capture_output=True, text=True, check=True, timeout=30)
            from lib.gnome_installer_driver import ocr_rows
            _, rows = ocr_rows(result.stdout)
            self.lines = [text for text, _ in rows]
        except (OSError, subprocess.SubprocessError):
            pass
        self.state = classify(self.lines)

    def has(self, text):
        target = normal(text)
        return any(normal(line) == target or target in normal(line) for line in self.lines)


def drive(outdir, phase, vnc, capture, keys, type_text, user, password,
          screen_factory=Screen, pointer=click_unix, sleep=time.sleep, clock=time.monotonic):
    evidence = {'driver': 'pantheon-first-boot', 'phase': phase, 'user': user,
                'frames': [], 'clicks': [], 'completed': False}
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

    def wait_for(states, label, polls=40):
        for _ in range(polls):
            screen = observe(label)
            if screen.state in states:
                return screen
            if screen.state == 'login-failed':
                raise Unverified('greeter rejected the account password')
            sleep(5)
        raise Unverified(f'no {"/".join(states)} frame within bound')

    try:
        if phase not in ('setup', 'login'):
            raise Unverified('unsupported first-boot phase')
        if not re.fullmatch(USER_PATTERN, user) or not re.fullmatch('[a-z0-9_.-]{8,64}', password):
            raise Unverified('unsupported test account or password format')
        screen = wait_for(('greeter',), 'await-greeter', polls=60)
        if not screen.has(user):
            raise Unverified('greeter does not offer the expected account')
        evidence['greeter_offers_account'] = True
        secret = True
        type_text(password)
        keys('ret')
        secret = False
        sleep(20)
        for _ in range(12):
            keys('meta_l')
            sleep(3)
            screen = observe('await-session')
            if screen.state == 'session-launcher':
                keys('esc')
                evidence['session_user_observed'] = True
                evidence['completed'] = True
                return 0
            if screen.state == 'login-failed':
                raise Unverified('greeter rejected the account password')
            sleep(10)
        raise Unverified('no user session launcher within bound')
    except (Unverified, OSError, subprocess.SubprocessError, ValueError) as exc:
        evidence['error'] = str(exc)
        print(f'not ok - Pantheon first-boot {phase}: {exc}', flush=True)
        return 1
    finally:
        private.cleanup()
        Path(outdir, f'first-boot-{phase}.json').write_text(json.dumps(evidence, indent=2) + '\n')
        print(f'ok - Pantheon first-boot {phase} completed' if evidence['completed'] else
              f'# Pantheon first-boot {phase} not proven', flush=True)
