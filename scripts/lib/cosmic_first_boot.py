"""Fail-closed GUI driver for the installed COSMIC system's greeter login.

On COSMIC the bundled installer's account page creates the only user
(scripts/lib/cosmic_installer_driver.py); nothing on the installed system asks
again. Each installed boot must then show that account at cosmic-greeter and
open its session with its password: the cold boot proves the GUI-created
account exists (phase setup), the warm boot that the login survives a reboot
(phase login).

Strings are read from pop-os/cosmic-greeter (i18n/en/cosmic_greeter.ftl,
src/greeter.rs, daemon/src/lib.rs), cosmic-launcher and cosmic-applibrary
(i18n/en/*.ftl) at their default branches of 2026-11. None has been measured
on strict COSMIC frames yet; strings that come from neither source are marked
"unmeasured" where they are used.

Input is hardware key events and VNC pointer clicks. No guest execution.
"""
import json
from pathlib import Path
import re
import subprocess
import tempfile
import time

from lib.gnome_installer_driver import Unverified, click_unix, normal
from lib.cosmic_installer_driver import Screen as InstallerScreen

USER_PATTERN = r'[a-z][a-z0-9]{2,31}'
# Typed on the installer's account page and at the greeter; test-only.
DEFAULT_PASSWORD = 'harbor-sunset-4817'

# cosmic-greeter auth-error-* (i18n/en/cosmic_greeter.ftl), drawn under the
# password field (src/greeter.rs error_opt).
AUTH_ERRORS = ('authentication failed', 'incorrect password', 'access denied',
               'too many failed authentication attempts', 'account is unavailable or disabled')
# The greeter's fatal socket states (src/greeter.rs SocketState::NotSet and
# ::Error; "Opening GREETD_SOCK" is the transient Pending state).
GREETER_BROKEN = ('greetd sock variable not set', 'failed to open greetd sock')


# Buttons of cosmic-initial-setup's pages, whole OCR lines, in click order.
INITIAL_SETUP_BUTTONS = ('next', 'finish', 'done', 'get started')
INITIAL_SETUP_PAGES = 12


def classify(lines):
    text = {normal(line) for line in lines}
    joined = '\n'.join(text)
    # 'login failed' is not a cosmic-greeter string (unmeasured): kept from
    # the other greeters so any such text still fails closed.
    if 'login failed' in joined or any(error in joined for error in AUTH_ERRORS):
        return 'login-failed'
    if any(state in joined for state in GREETER_BROKEN):
        return 'greeter-broken'
    # cosmic-launcher's "Type to search apps or type “?” for more options..."
    # and cosmic-applibrary's "Type to search apps…": only a user session
    # runs either; the greeter draws no search field.
    # OCR prefixes the field's icon ("(2 Type to search apos or type for more
    # options.", skipjack run 43155952354, frame 04), so the match is on the
    # words, not the line start. The language page's own field says only
    # "Type to search...", which has no "ap" word.
    if any(re.search(r'type t[co] search ap\w*', line) for line in text):
        return 'session-launcher'
    if 'authenticating' in text:
        return 'authenticating'
    # cosmic-initial-setup runs on a new account's first login and sits over
    # the desktop until it is stepped through: skipjack run 42931450791 shows
    # "Accessibility setup" with a Next button (frames 04-12 of both legs),
    # and Super does nothing while it is up. Its other pages are unmeasured,
    # so any page with one of its buttons is stepped through (bounded).
    if text.intersection(INITIAL_SETUP_BUTTONS):
        return 'initial-setup'
    # The greeter: the selected user's full name (the user name when GECOS
    # is empty, daemon/src/lib.rs) over a secure input whose placeholder is
    # the PAM prompt. pam_unix's "Password:" is PAM's text, not the greeter's
    # (unmeasured).
    if 'password' in text:
        return 'greeter'
    return 'unknown'


class Screen(InstallerScreen):
    """The installer's COSMIC-dark OCR passes, classified for first boot."""

    def __init__(self, path, user=None):
        super().__init__(path)
        if user is not None and 'password' not in {normal(line) for line in self.lines}:
            self.lines = self.lines + self.prompt_reads(user)
        self.state = classify(self.lines)

    def prompt_reads(self, user):
        """Enlarged reads of the strip under each place user is drawn.

        cosmic-greeter draws the PAM prompt as the secure input's dim grey
        placeholder ("Password:") just under the selected user's name, and
        whole-frame OCR reads it at confidence 25, below ocr_rows' floor
        (skipjack run 42911846504, strict-plain-installed: name at
        797,256-900,270, input at 707,288-990,323). Cropped from 12px under
        the name, 400x50 at 300%, it reads at confidence 95."""
        reads = []
        for box in self.boxes(user):
            centre = (box[0] + box[2]) // 2
            left, top = max(0, centre - 200), min(self.height - 1, box[3] + 12)
            width, height = min(self.width, centre + 200) - left, min(self.height - top, 50)
            for threshold in ('60%', '70%'):
                with tempfile.NamedTemporaryFile(suffix='.png') as crop:
                    subprocess.run(['convert', str(self.path), '-crop', f'{width}x{height}+{left}+{top}',
                                    '+repage', '-resize', '300%', '-colorspace', 'gray',
                                    '-negate', '-threshold', threshold, crop.name],
                                   capture_output=True, timeout=20, check=True)
                    text = subprocess.run(['tesseract', crop.name, 'stdout', '--psm', '7'],
                                          capture_output=True, text=True, timeout=20).stdout
                # The input's lock and reveal icons flank the prompt and read
                # as glyphs ("@ Password: oO"): keep the prompt word alone.
                words = [word for word in text.split() if normal(word) == 'password']
                if len(words) == 1:
                    reads.append(words[0])
        return reads


def drive(outdir, phase, vnc, capture, keys, type_text, user, password,
          screen_factory=None, pointer=click_unix, sleep=time.sleep, clock=time.monotonic):
    # The greeter's prompt is read under the account's own name (Screen).
    screen_factory = screen_factory or (lambda path: Screen(path, user))
    evidence = {'driver': 'cosmic-first-boot', 'phase': phase, 'user': user,
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
        if screen.state == 'login-failed':
            raise Unverified('greeter rejected the GUI-created account password')
        if screen.state == 'greeter-broken':
            raise Unverified('greeter cannot reach greetd')
        return screen

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
        screen = wait_for(('greeter',), 'await-greeter', polls=60)
        # The installer leaves Full name empty, so the greeter shows the
        # user name itself (full_name falls back to name).
        if not screen.has(user):
            raise Unverified('greeter does not offer the GUI-created account')
        evidence['greeter_offers_account'] = True
        # cosmic-greeter focuses the password field of the selected user.
        secret = True
        type_text(password)
        keys('ret')
        secret = False
        sleep(20)
        pages = []
        for _ in range(12):
            # Super opens the launcher in COSMIC's default shortcuts; with the
            # initial setup up it does nothing, so the setup is stepped through
            # first and Super is sent again.
            keys('meta_l')
            sleep(3)
            while True:
                screen = observe('await-session')
                if screen.state != 'initial-setup':
                    break
                if len(pages) >= INITIAL_SETUP_PAGES:
                    raise Unverified('initial setup did not finish within its page bound')
                # Titles are kept as evidence: the first line that is not a button.
                pages.append(next((line for line in screen.lines
                                   if normal(line) not in INITIAL_SETUP_BUTTONS), ''))
                evidence['initial_setup_pages'] = pages
                label = next(b for b in INITIAL_SETUP_BUTTONS
                             if any(normal(line) == b for line in screen.lines))
                box = screen.box(label)
                point = ((box[0] + box[2]) // 2, (box[1] + box[3]) // 2)
                evidence['clicks'].append({'action': label, 'point': list(point)})
                if pointer(vnc, *point, screen.width, screen.height) is not True:
                    raise Unverified('pointer transport did not acknowledge release')
                sleep(3)
            if screen.state == 'session-launcher':
                keys('esc')
                # The launcher draws no user name: the session is the one the
                # greeter opened after the GUI-created account's password.
                evidence['session_observed'] = True
                evidence['completed'] = True
                return 0
            sleep(10)
        raise Unverified('no user session launcher within bound')
    except (Unverified, OSError, subprocess.SubprocessError, ValueError) as exc:
        evidence['error'] = str(exc)
        print(f'not ok - COSMIC first-boot {phase}: {exc}', flush=True)
        return 1
    finally:
        private.cleanup()
        Path(outdir, f'first-boot-{phase}.json').write_text(json.dumps(evidence, indent=2) + '\n')
        print(f'ok - COSMIC first-boot {phase} completed' if evidence['completed'] else
              f'# COSMIC first-boot {phase} not proven', flush=True)
