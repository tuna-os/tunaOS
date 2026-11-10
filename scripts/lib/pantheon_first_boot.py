"""Fail-closed GUI driver for the installed Pantheon system's first boot and greeter login.

On Pantheon (gurnard:pantheon), LightDM manages the display and launches
io.elementary.greeter. The bundled installer creates no account. With no user
in LightDM's list, io.elementary.greeter 8.1.2 (src/MainWindow.vala load_users)
launches io.elementary.initial-setup 8.0.1, whose pages are, offline: Select a
Language, Select Keyboard Layout, Connect Network (Skip), Create an Account
(Full Name; Username generated from it; Choose a Password; Confirm Password;
Finish Setup). On Finish Setup it creates the account and quits; the greeter's
user_added handler shows the new account's card.

phase=setup drives Initial Setup to create the account, then logs in to it at
the greeter; phase=login proves the next boot offers that account and that its
password opens a session.

Input is hardware key events and VNC pointer clicks. No guest execution.
"""
import json
import re
import struct
import subprocess
import tempfile
import time
from pathlib import Path

from lib.gnome_installer_driver import (
    Unverified,
    accent_fill,
    click_unix,
    echo_last_frames,
    normal,
    ocr_rows,
)

USER_PATTERN = r'[a-z][a-z0-9]{2,31}'
# Typed at Initial Setup and the greeter; test-only.
DEFAULT_PASSWORD = 'harbor-sunset-4817'


def display_inactive(lines):
    """QEMU's own placeholder when the guest has switched its scanout off."""
    return any(normal(line).startswith('display output is not active') for line in lines)


def classify(lines):
    text = {normal(line) for line in lines}
    joined = '\n'.join(text)
    if any(k in joined for k in ('unable to launch initial setup',
                                 'could not create this account',
                                 'couldn t get permission to create an account')):
        return 'setup-error'
    if any(k in joined for k in ('login failed', 'incorrect password', 'authentication failure')):
        return 'login-failed'
    # Initial Setup pages, by their page titles (initial-setup 8.0.1
    # src/Views/*.vala). The language title rotates through languages every
    # 3s, so the language page is also known by its English list rows.
    if 'create an account' in text or ('full name' in text and 'confirm password' in text):
        return 'setup-account'
    if 'connect network' in text or 'connect a network cable' in text:
        return 'setup-network'
    if 'select keyboard layout' in text or any(line.startswith('type to test your layout') for line in text):
        return 'setup-keyboard'
    if 'select a language' in text or {'spanish', 'russian', 'german'} <= text \
            or {'australia', 'canada', 'united states'} <= text:
        return 'setup-language'
    # The io.elementary.greeter: user card/avatar and its password prompt.
    if 'password' in text and ('log in' in text or 'pantheon' in text or 'elementary' in text
                               or 'guest' in text or 'session' in text
                               or any('password' in line for line in text)):
        return 'greeter'
    return 'unknown'


class Screen:
    """OCR rows (text, box) of one PNG capture, classified into first-boot states."""

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
        # Initial Setup draws dark text on a light window; the greeter light
        # text on the wallpaper. The 2x pass reads entry text exactly.
        for ops, scale in (('-threshold 60%', 1), ('-negate -threshold 60%', 1),
                           ('-threshold 80%', 2)):
            rows.extend((text, tuple(v // scale for v in box)) for text, box
                        in ocr_rows(self._ocr(ops.split(), 11, scale=scale))[1])
        self.accent_rows = self._accent_fills()
        rows.extend(self.accent_rows)
        self.rows = rows
        self.lines = [row[0] for row in rows]
        self.state = classify(self.lines)

    def _ocr(self, ops, psm, crop=None, scale=1):
        geometry = ['-crop', '{}x{}+{}+{}'.format(*crop), '+repage'] if crop else []
        with tempfile.NamedTemporaryFile(suffix='.png') as prepared:
            subprocess.run(['convert', str(self.path), *geometry, '-resize', f'{scale * 100}%',
                            '-colorspace', 'gray', *ops, prepared.name],
                           capture_output=True, timeout=20, check=True)
            return subprocess.run(['tesseract', prepared.name, 'stdout', '--psm', str(psm), 'tsv'],
                                  capture_output=True, text=True, timeout=30, check=True).stdout

    def _accent_fills(self):
        """Initial Setup's suggested actions (Select, Skip, Finish Setup) and
        its selected list row (English…) are white text on the accent fill,
        which full-frame thresholds drop. Find solid accent rectangles and
        OCR only their inside.

        UNMEASURED on a VM frame: no shipped image has Initial Setup yet
        (tunaOS#4486). The size bounds come from an Xvfb render of
        initial-setup 8.0.1 at 1280x800, where Select/Skip are 86x34 and the
        selected English row is 400x38. Recalibrate them from the first real
        installed-boot frames."""
        raw = subprocess.run(['convert', str(self.path), '-depth', '8', 'rgb:-'],
                             capture_output=True, timeout=20, check=True).stdout
        if len(raw) != self.width * self.height * 3:
            raise Unverified('invalid pixel buffer')
        rects = []   # [left, top, right, bottom, last_y]
        for y in range(self.height):
            base = y * self.width * 3
            row, start, last = [], None, None
            for x in range(self.width + 1):
                if x < self.width and accent_fill(raw[base + 3 * x:base + 3 * x + 3]):
                    # Label strokes split a run: bridge gaps up to 20px.
                    if start is None or x - last > 20:
                        if start is not None and last + 1 - start >= 30:
                            row.append((start, last + 1))
                        start = x
                    last = x
            if start is not None and last + 1 - start >= 30:
                row.append((start, last + 1))
            for lo, hi in row:
                for rect in rects:
                    if rect[4] == y - 1 and lo < rect[2] and hi > rect[0]:
                        rect[0], rect[2], rect[3], rect[4] = min(rect[0], lo), max(rect[2], hi), y + 1, y
                        break
                else:
                    rects.append([lo, y, hi, y + 1, y])
        found = []
        for left, top, right, bottom, _ in rects:
            if not (30 <= right - left <= 480 and 18 <= bottom - top <= 60):
                continue
            inset = (right - left - 12, bottom - top - 8, left + 6, top + 4)
            text = ' '.join(row[0] for row in ocr_rows(self._ocr(
                ['-negate', '-threshold', '50%'], 7, inset, 3))[1])
            if text.strip():
                found.append((text, (left, top, right, bottom)))
        return found

    def box(self, label, accent=False):
        """Exactly one box for label; several OCR passes may see the same
        control, so overlapping boxes count once (the tightest)."""
        def holds(outer, inner):
            cx, cy = (inner[0] + inner[2]) // 2, (inner[1] + inner[3]) // 2
            return outer[0] <= cx <= outer[2] and outer[1] <= cy <= outer[3]

        boxes = []
        # accent=True: only a label read inside an accent fill, i.e. an
        # enabled suggested action (an insensitive one is drawn grey).
        for text, box in (self.accent_rows if accent else self.rows):
            if normal(text) != normal(label):
                continue
            same = [seen for seen in boxes if holds(seen, box) or holds(box, seen)]
            if not same:
                boxes.append(box)
            elif (box[2] - box[0]) * (box[3] - box[1]) < (same[0][2] - same[0][0]) * (same[0][3] - same[0][1]):
                boxes[boxes.index(same[0])] = box
        if len(boxes) != 1:
            raise Unverified(f'expected one exact control label: {label}; got {len(boxes)}')
        box = boxes[0]
        if not (0 <= box[0] < box[2] <= self.width and 0 <= box[1] < box[3] <= self.height):
            raise Unverified('control box is outside the capture')
        return box

    def count(self, label):
        """Distinct places OCR read exactly this label."""
        seen = []
        for text, box in self.rows:
            if normal(text) == normal(label):
                cx, cy = (box[0] + box[2]) // 2, (box[1] + box[3]) // 2
                if not any(abs(cx - x) <= 12 and abs(cy - y) <= 12 for x, y in seen):
                    seen.append((cx, cy))
        return len(seen)

    def has(self, text):
        target = normal(text)
        return any(normal(line) == target or target in normal(line) for line in self.lines)


def drive(outdir, phase, vnc, capture, keys, type_text, user, password,
          screen_factory=Screen, pointer=click_unix, sleep=time.sleep, clock=time.monotonic):
    evidence = {'driver': 'pantheon-first-boot-is801', 'phase': phase, 'user': user,
                'frames': [], 'clicks': [], 'pages': [], 'completed': False}
    deadline = clock() + 1200
    counter = 0
    private = tempfile.TemporaryDirectory(prefix='tunaos-first-boot-')
    secret = False

    def observe(label):
        nonlocal counter
        if clock() >= deadline or counter >= 128:
            raise Unverified('first-boot observation deadline/frame bound exceeded')
        path = capture(counter, label, directory=private.name) if secret else capture(counter, label)
        counter += 1
        if not path:
            raise Unverified('GUI capture unavailable')
        screen = screen_factory(path)
        evidence['frames'].append({'state': screen.state, 'private': True} if secret else
                                  {'file': Path(path).name, 'state': screen.state,
                                   'text': screen.lines})
        if screen.state == 'setup-error':
            raise Unverified('Initial Setup reported it cannot create the account')
        return screen

    def send_keys(*names):
        evidence.setdefault('keys', []).extend(names)
        keys(*names)

    def click(screen, label, accent=False):
        box = screen.box(label, accent)
        point = [(box[0] + box[2]) // 2, (box[1] + box[3]) // 2]
        evidence['clicks'].append({'label': label, 'state': screen.state,
                                   'box': list(box), 'point': point})
        if pointer(vnc, *point, screen.width, screen.height) is not True:
            raise Unverified('pointer transport did not acknowledge release')
        # A pointer left on a label hides it from OCR.
        pointer(vnc, screen.width - 2, screen.height - 2, screen.width, screen.height, click=False)
        sleep(2)

    def wait_for(states, label, polls=40, until=None):
        for _ in range(polls):
            screen = observe(label)
            if screen.state in states and (until is None or until(screen)):
                return screen
            if screen.state == 'login-failed':
                raise Unverified('greeter rejected the account password')
            if display_inactive(screen.lines):
                # A blanked screen wakes when the pointer moves; a dead one
                # still fails closed after the same polls.
                evidence['display_wakes'] = evidence.get('display_wakes', 0) + 1
                pointer(vnc, screen.width // 2, screen.height // 2, screen.width, screen.height, click=False)
                pointer(vnc, screen.width - 2, screen.height - 2, screen.width, screen.height, click=False)
            sleep(5)
        raise Unverified(f'no {"/".join(states)} frame within bound')

    def page(screen):
        evidence['pages'].append(screen.state)

    def initial_setup():
        nonlocal secret
        screen = wait_for(('setup-language', 'greeter'), 'await-initial-setup', polls=60)
        if screen.state == 'greeter':
            # The account must come from the product's own first-boot GUI.
            raise Unverified('greeter offered a login before Initial Setup created the account')
        page(screen)
        # Activating "English" lists its countries with the main one
        # (United States) selected; Select then commits en_US.
        click(screen, 'English', accent=True)
        screen = wait_for(('setup-language',), 'language-countries', polls=6,
                          until=lambda s: s.has('United States') and s.has('Languages'))
        click(screen, 'Select', accent=True)
        screen = wait_for(('setup-keyboard',), 'await-keyboard', polls=12)
        page(screen)
        # en_US preselects the "us" layout; Select lists its variants with
        # Default selected, and Select again commits it.
        click(screen, 'Select', accent=True)
        screen = wait_for(('setup-keyboard',), 'keyboard-variants', polls=6,
                          until=lambda s: s.has('Input Language'))
        click(screen, 'Select', accent=True)
        screen = wait_for(('setup-network', 'setup-account'), 'await-network-or-account', polls=12)
        if screen.state == 'setup-network':
            # Offline by construction: the network page offers Skip.
            page(screen)
            click(screen, 'Skip', accent=True)
            screen = wait_for(('setup-account',), 'await-account', polls=12)
        page(screen)
        # Full Name has focus when the page opens; Username is generated from
        # it, so a Full Name equal to the account name yields exactly that
        # account name, and the greeter card (which shows the full name)
        # names it too. Two exact reads (both entries) prove where it went.
        type_text(user)
        sleep(2)
        screen = wait_for(('setup-account',), 'verify-account-name', polls=6,
                          until=lambda s: s.count(user) >= 2)
        evidence['account_name_observed'] = True
        secret = True
        send_keys('tab', 'tab')
        type_text(password)
        send_keys('tab')
        type_text(password)
        sleep(2)
        screen = observe('verify-passwords')
        if screen.state != 'setup-account':
            raise Unverified('password input left the verified account page')
        if screen.has('Passwords do not match'):
            raise Unverified('Initial Setup reports the passwords differ')
        click(screen, 'Finish Setup', accent=True)
        secret = False
        evidence['account_submitted'] = True

    try:
        if phase not in ('setup', 'login'):
            raise Unverified('unsupported first-boot phase')
        if not re.fullmatch(USER_PATTERN, user) or not re.fullmatch('[a-z0-9_.-]{8,64}', password):
            raise Unverified('unsupported test account or password format')
        if phase == 'setup':
            initial_setup()
        screen = wait_for(('greeter',), 'await-greeter', polls=60)
        if not screen.has(user):
            raise Unverified('greeter does not offer the expected account')
        evidence['greeter_offers_account'] = True
        secret = True
        type_text(password)
        send_keys('ret')
        secret = False
        sleep(20)
        # The image ships no applications menu (no wingpanel indicator
        # package at all; streamed gurnard:pantheon amd64 sha256:ea40deed
        # layers), so Meta opens nothing and the panel draws no text. A user
        # session does run gnome-settings-daemon's media-keys plugin
        # (pantheon-org.gnome.SettingsDaemon.MediaKeys autostart);
        # elementary-default-settings 8.1.1 binds its terminal action to
        # <Super>t under Pantheon (default-settings.gschema.override), and
        # io.elementary.terminal is the x-terminal-emulator alternative. Its
        # prompt names the account the session belongs to. UNMEASURED: no
        # installed Pantheon session frame has been captured yet.
        prompt = re.compile(rf'{re.escape(user)}\s*@\s*[a-z0-9][a-z0-9-]*\s*:\s*~\s*\$')
        for attempt in range(12):
            if attempt % 4 == 0:
                send_keys('meta_l-t')
            sleep(5)
            screen = observe('await-session')
            if any(prompt.search(line.lower()) for line in screen.lines):
                evidence['session_user_observed'] = True
                evidence['completed'] = True
                return 0
            if screen.state == 'login-failed':
                raise Unverified('greeter rejected the account password')
            sleep(5)
        raise Unverified('no terminal prompt of the account within bound')
    except (Unverified, OSError, subprocess.SubprocessError, ValueError) as exc:
        evidence['error'] = str(exc)
        print(f'not ok - Pantheon first-boot {phase}: {exc}', flush=True)
        echo_last_frames(evidence['frames'])
        return 1
    finally:
        private.cleanup()
        Path(outdir, f'first-boot-{phase}.json').write_text(json.dumps(evidence, indent=2) + '\n')
        print(f'ok - Pantheon first-boot {phase} completed' if evidence['completed'] else
              f'# Pantheon first-boot {phase} not proven', flush=True)
