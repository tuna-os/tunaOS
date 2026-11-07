"""Fail-closed GUI driver for the installed Niri system's greeter login.

On Niri the bundled installer's account step creates the only user
(scripts/lib/niri_installer_driver.py); nothing on the installed system asks
again. Each installed boot must then accept that account at the greetd
greeter and open a niri session: the cold boot proves the GUI-created
account exists (phase setup), the warm boot that the login survives a
reboot (phase login).

Two greeters front greetd on the niri images:
  gtkgreet under cage   marlin (Arch) and sailfin (openSUSE),
                        build_scripts/desktop/greetd-gtkgreet.sh. It lists no
                        users: it asks "Username:", then greetd's PAM prompt
                        "Password:", and prints "Login failed" on a rejection.
  dms-greeter           the Fedora/EL10 variants (DankMaterialShell). It may
                        offer the last user or ask for one.
Either way greetd starts a session only for the account whose password PAM
accepted, so the greeter accepting the typed account and a niri session
drawing afterwards is the login proof.

The session is recognised by what only a niri user session draws: niri's
"Important Hotkeys" overlay (shown at startup by the config niri writes for a
new user) or the fuzzel launcher that config binds to Mod+D.

Input is hardware key events and VNC pointer clicks. No guest execution.
"""
import json
from pathlib import Path
import re
import subprocess
import tempfile
import time

from lib.gnome_installer_driver import Unverified, click_unix, normal
from lib.niri_installer_driver import Screen as InstallerScreen

USER_PATTERN = r'[a-z][a-z0-9]{2,31}'
# Typed on the installer's account step and at the greeter; test-only.
DEFAULT_PASSWORD = 'harbor-sunset-4817'


def classify(lines):
    text = [normal(line) for line in lines]
    joined = '\n'.join(text)
    if 'login failed' in joined or 'authentication failed' in joined:
        return 'login-failed'
    if 'important hotkeys' in joined:
        return 'session-hotkeys'
    # The greeter: greetd's PAM prompts, as gtkgreet labels them.
    if 'password' in text:
        return 'greeter-password'
    if 'username' in text:
        return 'greeter-username'
    return 'unknown'


class Screen(InstallerScreen):
    """The installer's OCR passes, classified for first boot."""

    def __init__(self, path):
        super().__init__(path)
        self.state = classify(self.lines)


def drive(outdir, phase, vnc, capture, keys, type_text, user, password,
          screen_factory=Screen, pointer=click_unix, sleep=time.sleep, clock=time.monotonic):
    evidence = {'driver': 'niri-first-boot', 'phase': phase, 'user': user,
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
                raise Unverified('greeter rejected the GUI-created account password')
            sleep(5)
        raise Unverified(f'no {"/".join(states)} frame within bound')

    try:
        if phase not in ('setup', 'login'):
            raise Unverified('unsupported first-boot phase')
        if not re.fullmatch(USER_PATTERN, user) or not re.fullmatch('[a-z0-9_.-]{8,64}', password):
            raise Unverified('unsupported test account or password format')
        screen = wait_for(('greeter-username', 'greeter-password'), 'await-greeter', polls=60)
        if screen.state == 'greeter-username':
            # gtkgreet focuses its username entry on start.
            type_text(user)
            keys('ret')
            sleep(3)
            screen = wait_for(('greeter-password',), 'await-password-prompt', polls=6)
            evidence['greeter_accepts_account'] = 'typed'
        elif screen.has(user):
            evidence['greeter_accepts_account'] = 'offered'
        else:
            raise Unverified('greeter asks for a password without naming the GUI-created account')
        secret = True
        type_text(password)
        keys('ret')
        secret = False
        sleep(20)
        for _ in range(12):
            screen = observe('await-session')
            if screen.state == 'login-failed':
                raise Unverified('greeter rejected the GUI-created account password')
            if screen.state in ('greeter-username', 'greeter-password'):
                sleep(10)
                continue
            if screen.state == 'session-hotkeys':
                evidence['session_marker'] = 'important hotkeys'
                keys('esc')
                evidence['completed'] = True
                return 0
            # No overlay: open the launcher niri's default config binds.
            keys('meta_l-d')
            sleep(3)
            screen = observe('await-launcher')
            launcher = screen.state == 'unknown' and any(
                normal(line) in ('nautilus', 'files', 'pavucontrol', 'volume control') for line in screen.lines)
            if launcher:
                evidence['session_marker'] = 'launcher'
                keys('esc')
                evidence['completed'] = True
                return 0
            sleep(10)
        raise Unverified('no niri user session within bound')
    except (Unverified, OSError, subprocess.SubprocessError, ValueError) as exc:
        evidence['error'] = str(exc)
        print(f'not ok - Niri first-boot {phase}: {exc}', flush=True)
        return 1
    finally:
        private.cleanup()
        Path(outdir, f'first-boot-{phase}.json').write_text(json.dumps(evidence, indent=2) + '\n')
        print(f'ok - Niri first-boot {phase} completed' if evidence['completed'] else
              f'# Niri first-boot {phase} not proven', flush=True)
