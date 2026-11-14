"""Fail-closed GUI driver for the installed KDE system's greeter login.

On Plasma the bundled installer's account step creates the only user
(scripts/lib/kde_installer_driver.py); nothing on the installed system asks
again. Each installed boot must then show that account at the Plasma greeter
(plasmalogin or SDDM) and open its session with its password: the cold boot
proves the GUI-created account exists (phase setup), the warm boot that the
login survives a reboot (phase login).

Input is hardware key events and VNC pointer clicks. No guest execution.
"""
import json
from pathlib import Path
import re
import subprocess
import tempfile
import time

from lib.gnome_installer_driver import Unverified, click_unix, normal
from lib.kde_installer_driver import Screen as InstallerScreen

USER_PATTERN = r'[a-z][a-z0-9]{2,31}'
# Typed on the installer's account step and at the greeter; test-only.
DEFAULT_PASSWORD = 'harbor-sunset-4817'
# Consecutive Welcome Center frames, each after a Meta press, that stand in for
# a Kickoff launcher the shell never draws.
WELCOME_POLLS = 6


def classify(lines):
    text = {normal(line) for line in lines}
    joined = '\n'.join(text)
    if 'login failed' in joined or 'login failed' in text:
        return 'login-failed'
    # Kickoff, opened with Meta: only a user session draws its search field.
    if any(line.startswith('search') for line in text) and 'applications' in text:
        return 'session-launcher'
    # The greeter: a user tile and its password prompt. The placeholder in the
    # empty field is grey and is not always read (yellowfin-kde, iso-builder run
    # 43233767372: only the user name, clock and the Sleep / Restart / Shut Down
    # row were), so the power row names the greeter too.
    # Plasma Welcome opens on a new account's first login (kded6: `Launching
    # Welcome Center with no last seen version`). Only a logged-in user session
    # draws it. yellowfin-kde, iso-builder run 43569429086: the greeter accepted
    # the password and the Welcome Center showed for 40 frames on a black screen
    # with no panel, so Meta never opened Kickoff.
    if 'welcome center' in text and any(line.endswith('skip') for line in text):
        return 'welcome-center'
    if 'password' in text and ('switch user' in text or 'other' in text or 'log in' in text
                               or 'virtual keyboard' in text or 'keyboard layout' in joined):
        return 'greeter'
    if {'restart', 'shut down'} <= text:
        return 'greeter'
    # SDDM's fallback theme (grouper-kde, iso-builder run 43572130394: a white
    # panel, the user tile, a grey prompt and two power icons) has no word row
    # and OCR misses the white prompt, but it always draws the session chooser.
    if any(line.startswith('session plasma') for line in text):
        return 'greeter'
    return 'unknown'


def terminal_shows(lines, user):
    """True when a line carries the account name inside a shell prompt or window title
    (`tunaose2e@grouper:~`). Greeter, launcher and Welcome Center frames are classified
    before this is asked."""
    names = {normal(user), normal(user).replace('2', 'z')}
    return any(name in normal(line) for line in lines for name in names)


class Screen(InstallerScreen):
    """The installer's Breeze-dark OCR passes, classified for first boot."""

    def __init__(self, path):
        super().__init__(path)
        self.state = classify(self.lines)


def drive(outdir, phase, vnc, capture, keys, type_text, user, password,
          screen_factory=Screen, pointer=click_unix, sleep=time.sleep, clock=time.monotonic):
    evidence = {'driver': 'kde-first-boot', 'phase': phase, 'user': user,
                'frames': [], 'clicks': [], 'completed': False}
    deadline = clock() + 2400
    counter = 0
    private = tempfile.TemporaryDirectory(prefix='tunaos-first-boot-')
    secret = False

    def observe(label):
        nonlocal counter
        if clock() >= deadline or counter >= 160:
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

    def wait_for(states, label, polls=40, wake=False):
        for _ in range(polls):
            screen = observe(label)
            if screen.state in states:
                return screen
            if screen.state == 'login-failed':
                raise Unverified('greeter rejected the GUI-created account password')
            if wake and screen.state == 'unknown':
                # The greeter hides its login UI after a minute and shows only
                # the clock over the wallpaper (run 43233767372, 59 of 60
                # frames); any key brings it back, and the password field is
                # focused again.
                keys('shift')
                # Pointer motion wakes it where a bare modifier did not (LUKS
                # leg of run 43368481798: 47 clock-only frames, the greeter
                # process alive the whole time).
                pointer(vnc, screen.width // 2, screen.height // 2, screen.width, screen.height, click=False)
                pointer(vnc, screen.width - 2, screen.height - 2, screen.width, screen.height, click=False)
            sleep(5)
        raise Unverified(f'no {"/".join(states)} frame within bound')

    try:
        if phase not in ('setup', 'login'):
            raise Unverified('unsupported first-boot phase')
        if not re.fullmatch(USER_PATTERN, user) or not re.fullmatch('[a-z0-9_.-]{8,64}', password):
            raise Unverified('unsupported test account or password format')
        screen = wait_for(('greeter',), 'await-greeter', polls=60, wake=True)
        if not screen.has(user):
            raise Unverified('greeter does not offer the GUI-created account')
        evidence['greeter_offers_account'] = True
        secret = True
        type_text(password)
        keys('ret')
        secret = False
        sleep(20)
        # A software-rendered Plasma greeter and session start take minutes: the
        # plain leg of run 43368481798 still showed the filled password field 6
        # minutes after Enter. Watch longer, and press Enter again now and then
        # (the password is already in the field) in case the first one was lost.
        welcome = 0
        state = 'unknown'
        for attempt in range(40):
            keys('meta_l')
            if attempt and state in ('unknown', 'welcome-center'):
                # Where the shell draws no panel (grouper-kde, iso-builder run 43587030184: a
                # black screen for 18 minutes after PAM and `startplasma-wayland` succeeded),
                # Konsole's default Ctrl+Alt+T opens a terminal that names the account.
                keys('ctrl-alt-t')
            sleep(3)
            screen = observe('await-session')
            state = screen.state
            if screen.state in ('unknown', 'welcome-center') and terminal_shows(screen.lines, user):
                evidence['session_evidence'] = 'konsole'
                evidence['session_user_observed'] = True
                evidence['completed'] = True
                return 0
            if screen.state == 'session-launcher':
                if not screen.has(user):
                    raise Unverified('session launcher does not belong to the GUI-created account')
                keys('esc')
                evidence['session_user_observed'] = True
                evidence['completed'] = True
                return 0
            if screen.state == 'login-failed':
                raise Unverified('greeter rejected the GUI-created account password')
            if screen.state == 'greeter' and attempt % 6 == 5:
                keys('ret')
            if screen.state == 'welcome-center':
                # Left open on purpose: Skip records the version, so the warm boot
                # would show no Welcome Center to prove its login by.
                welcome += 1
                if welcome >= WELCOME_POLLS:
                    evidence['session_evidence'] = 'plasma-welcome'
                    evidence['session_user_observed'] = True
                    evidence['completed'] = True
                    return 0
            else:
                welcome = 0
            sleep(10)
        raise Unverified('no user session launcher within bound')
    except (Unverified, OSError, subprocess.SubprocessError, ValueError) as exc:
        evidence['error'] = str(exc)
        print(f'not ok - KDE first-boot {phase}: {exc}', flush=True)
        return 1
    finally:
        private.cleanup()
        Path(outdir, f'first-boot-{phase}.json').write_text(json.dumps(evidence, indent=2) + '\n')
        print(f'ok - KDE first-boot {phase} completed' if evidence['completed'] else
              f'# KDE first-boot {phase} not proven', flush=True)
