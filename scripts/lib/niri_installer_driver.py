"""Fail-closed GUI driver for the bundled Niri installer (org.tunaos.InstallerNiri).

Contract read from the QML the measured bundle was built from: the
tunaos.org/flatpak `niri` image of org.tunaos.InstallerNiri says "Built from
23e47c51a9b1e5857772445d58ed91cf20522e64" (tuna-os/bootc-installer, the only
niri build that remote serves), so frontends/niri/ui/installer.qml at that
commit, NOT the dev branch (whose Source and Session pages, 96b89485 and
bootc-installer #334, ship in no bundle yet). A Quickshell window whose top bar reads
"Step N of 7 · <Page>" on every page (Welcome, Disk, Encryption, Account,
Confirm, Installing, Done) and whose hint bar repeats "Continue"/"Back" (or
"Install" on Confirm) under the page. Page buttons are right-aligned, so the
page's own control is the rightmost read of its label. On live media the
welcome page says "Install this system — no download required." and the
recipe's empty image installs the running system. The Account page is where
the installed system's only user is created (the recipe's `user` block): on
Niri that is the GUI account path the receipt's gui_account_created stands
for, proven afterwards by the greeter login (scripts/lib/niri_first_boot.py).

Input is VNC pointer clicks and HMP key events. No guest execution.
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
TARGET_DISK = '/dev/vda'
ENCRYPTION = {'plain': 'No encryption', 'luks': 'Passphrase'}
# installer.qml pageNames (the 9-page bundle), as normal() reads the top bar.
PAGES = ('welcome', 'session', 'source', 'disk', 'encryption', 'account', 'confirm', 'installing', 'done')
STEP_BAR = re.compile(r'^step \d+ of \d+ (' + '|'.join(PAGES) + r')$')
# The neutral product name the QML shows until the backend's detect answers.
NEUTRAL_PRODUCT = 'Linux'
# Account grid: labels in column 0, fields 24px (Theme.spacingXL) right of the
# widest label; aim this far into the 300px field.
FIELD_INSET = 24 + 80
# The measured UI contract: the live overlay's InstallerNiri receipt
# (org.tunaos.live-overlay.installer on ghcr.io/tuna-os/live-overlay:marlin-niri;
# overlays sha256:94cdc39d7c05… and sha256:72656408de3d… of 2026-11-10 both
# record this commit), the deployed form of the 23e47c51 bundle above.
# A different bundle is unmeasured.
BUNDLE_DIGEST = 'sha256:6db50c28b57485f9845d0009eef162fc2f3c9392a51b744153cde93aa8d59192'
# The welcome line live media draws (isLive): the install takes the running
# system, not a download.
LIVE_LINE = 'Install this system — no download required.'



def echo_frame(name, label, state, lines):
    text = ' | '.join(str(line) for line in lines)[:400]
    print(f'# frame {name} {label} state={state}: {text}', flush=True)

def classify(lines):
    text = [normal(line) for line in lines]
    joined = '\n'.join(text)
    if 'installation failed' in joined:
        return 'failed'
    if 'does not meet the minimum requirements' in joined:
        return 'requirements'
    pages = {m.group(1) for m in (STEP_BAR.match(line) for line in text) if m}
    if len(pages) == 1:
        page = pages.pop()
        return 'progress' if page == 'installing' else page
    # Top bar unread (or two pages mid-slide): the page's own heading.
    if any(line.endswith(' is installed') for line in text) and 'restart now' in text:
        return 'done'
    if 'do not power off the computer' in joined:
        return 'progress'
    if 'confirm installation' in text and 'summary' in text:
        return 'confirm'
    if 'session' in text and 'keyboard and language' in text:
        return 'session'
    if 'what do you want to install' in text:
        return 'source'
    if 'your account' in text and 'the account you sign in with' in joined:
        return 'account'
    if 'disk encryption' in text and 'encryption protects your files' in joined:
        return 'encryption'
    if 'destination' in text:
        return 'disk'
    if 'get started' in text and any(line.startswith('welcome to ') for line in text):
        return 'welcome'
    return 'unknown'


class Screen:
    """OCR rows of one PNG capture, classified into installer pages."""

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
        # DMS dark palette (Theme.qml: surface #141218, text #e6e0e9): light
        # text on dark fills. The low threshold keeps the dark label on the
        # lilac primary button; 2x reads device paths whose slashes 1x garbles.
        for ops, scale in (('-negate -threshold 50%', 1), ('-negate -threshold 25%', 1),
                           ('-negate -threshold 50%', 2)):
            rows.extend((text, tuple(v // scale for v in box)) for text, box
                        in ocr_rows(self._ocr(ops.split(), 11, scale=scale))[1])
        self.rows = rows
        self.lines = [row[0] for row in rows]
        self.state = classify(self.lines)

    def _ocr(self, ops, psm, scale=1):
        with tempfile.NamedTemporaryFile(suffix='.png') as prepared:
            subprocess.run(['convert', str(self.path), '-resize', f'{scale * 100}%',
                            '-colorspace', 'gray', *ops, prepared.name],
                           capture_output=True, timeout=20, check=True)
            return subprocess.run(['tesseract', prepared.name, 'stdout', '--psm', str(psm), 'tsv'],
                                  capture_output=True, text=True, timeout=30, check=True).stdout

    def matching(self, accept):
        """Every distinct row whose normal() text satisfies accept (passes merged)."""
        def holds(outer, inner):
            cx, cy = (inner[0] + inner[2]) // 2, (inner[1] + inner[3]) // 2
            return outer[0] <= cx <= outer[2] and outer[1] <= cy <= outer[3]

        found = []
        for text, box in self.rows:
            if not accept(normal(text)):
                continue
            same = [seen for seen in found if holds(seen[1], box) or holds(box, seen[1])]
            if not same:
                found.append((text, box))
            elif (box[2] - box[0]) * (box[3] - box[1]) < (same[0][1][2] - same[0][1][0]) * (same[0][1][3] - same[0][1][1]):
                found[found.index(same[0])] = (text, box)
        for _, box in found:
            if not (0 <= box[0] < box[2] <= self.width and 0 <= box[1] < box[3] <= self.height):
                raise Unverified('control box is outside the capture')
        return sorted(found, key=lambda row: (row[1][1], row[1][0]))

    def boxes(self, label):
        want = normal(label)
        return [box for _, box in self.matching(lambda text: text == want)]

    def box(self, label):
        found = self.boxes(label)
        if len(found) != 1:
            raise Unverified(f'expected one exact control label: {label}; got {len(found)}')
        return found[0]

    def button(self, label):
        """The page's own button: right-aligned, so the rightmost read.

        The hint bar under the page repeats Continue/Back/Install at the
        left edge; it must never be the target."""
        found = self.boxes(label)
        if not found:
            raise Unverified(f'no {label} button on the page')
        rightmost = max(found, key=lambda b: b[2])
        if len(found) > 1 and sorted(b[2] for b in found)[-2] >= rightmost[2] - 40:
            raise Unverified(f'ambiguous {label} button')
        return rightmost

    def has(self, label):
        return any(normal(text) == normal(label) for text in self.lines)

    def contains(self, phrase):
        want = normal(phrase)
        return any(want in normal(text) for text in self.lines)

    def value_right(self, label):
        """The value a Summary grid row draws right of its label."""
        top = self.box(label)
        mid = (top[1] + top[3]) // 2
        values = {' '.join(text.split()) for text, box in self.rows
                  if box[0] > top[2] and abs((box[1] + box[3]) // 2 - mid) <= 10
                  and normal(text) != normal(label)}
        if len(values) != 1:
            raise Unverified(f'summary row {label} has absent or ambiguous value: {sorted(values)}')
        return values.pop()


def product_from_welcome(screen):
    for line in screen.lines:
        match = re.fullmatch(r'Welcome to (\S+)', ' '.join(line.split()))
        if match:
            return match.group(1)
    raise Unverified('welcome page does not name the product')


def drive(outdir, mode, vnc, capture, keys, type_text, installer_digest, password, user, user_password,
          screen_factory=Screen, pointer=click_unix, sleep=time.sleep, clock=time.monotonic):
    """Bounded ordered GUI transaction. Submit once; then observe only."""
    evidence = {'driver': 'niri-installer', 'installer_digest': installer_digest,
                'mode': mode, 'user': user, 'frames': [],
                'transitions': [], 'clicks': [], 'submitted': False, 'accepted': False,
                'account_created': False, 'completed': False}
    deadline = clock() + 1200
    counter = 0
    private = None

    def observe(label):
        nonlocal counter
        if clock() >= deadline or counter >= 128:
            raise Unverified('GUI observation deadline/frame bound exceeded')
        secret = private is not None
        path = capture(counter, label, directory=private.name) if secret else capture(counter, label)
        counter += 1
        if not path:
            raise Unverified('GUI capture unavailable')
        screen = screen_factory(path)
        evidence['frames'].append({'state': screen.state, 'private': True} if secret else
                                  {'file': Path(path).name, 'state': screen.state,
                                   'text': screen.lines})
        # Uncalibrated driver: every public frame's OCR text goes to the log
        # too, so a run can be calibrated from its job log alone.
        if not secret:
            echo_frame(Path(path).name, label, screen.state, screen.lines)
        if screen.state == 'failed':
            raise Unverified('installer reported failure')
        if screen.state == 'requirements':
            raise Unverified('installer requirements gate blocks the guest (RAM/CPU/UEFI)')
        # The live user's niri config is the package's skel copy
        # (live-iso/common/src/desktop-niri.sh); upstream niri opens its
        # "Important Hotkeys" overlay at session start unless the config says
        # skip-at-startup, on top of the installer. Any key closes it; the
        # installer binds no Escape.
        if screen.contains('Important Hotkeys'):
            evidence['hotkey_overlay_dismissed'] = evidence.get('hotkey_overlay_dismissed', 0) + 1
            keys('esc')
            sleep(2)
            return observe(label)
        return screen

    def click_at(screen, action, box, point):
        evidence['clicks'].append({'action': action, 'state': screen.state,
                                   'box': list(box), 'point': list(point)})
        if pointer(vnc, *point, screen.width, screen.height) is not True:
            raise Unverified('pointer transport did not acknowledge release')
        sleep(2)

    def click(screen, action, box):
        click_at(screen, action, box, ((box[0] + box[2]) // 2, (box[1] + box[3]) // 2))

    def fill_at(screen, action, box, point, value):
        if not (0 <= point[0] < screen.width and 0 <= point[1] < screen.height):
            raise Unverified('field point is outside the capture')
        click_at(screen, action, box, point)
        keys('ctrl-a')
        type_text(value)
        sleep(1)

    def transition(previous, expected, polls=12):
        for _ in range(polls):
            screen = observe('await-' + expected)
            if screen.state == expected:
                evidence['transitions'].append(expected)
                return screen
            # The StackLayout swaps pages; a mid-redraw frame reads unknown.
            if screen.state not in (previous, 'unknown'):
                raise Unverified(f'unexpected ordered transition: {previous} -> {screen.state}')
            sleep(3)
        raise Unverified(f'GUI did not transition from {previous} to {expected}')

    def next_page(screen, expected, label='Continue'):
        click(screen, normal(label), screen.button(label))
        return transition(screen.state, expected)

    def transition_slow(screen, expected):
        # Session's Continue runs the host's setters before it advances.
        click(screen, 'continue', screen.button('Continue'))
        return transition(screen.state, expected, polls=30)

    try:
        if installer_digest != BUNDLE_DIGEST:
            raise Unverified(f'unsupported installer bundle: measured UI contract digest differs ({installer_digest or "none"})')
        if mode not in ENCRYPTION or not re.fullmatch('[a-z0-9_.-]{8,64}', password):
            raise Unverified('unsupported mode or test-only passphrase format')
        if not re.fullmatch(USER_PATTERN, user) or not re.fullmatch('[a-z0-9_.-]{8,64}', user_password):
            raise Unverified('unsupported test account or password format')

        screen = transition('unknown', 'welcome', polls=40)
        # The title is neutral ("Welcome to Linux") until detect delivers
        # the branding; the done page must later name the same product.
        for _ in range(10):
            product = product_from_welcome(screen)
            if product != NEUTRAL_PRODUCT:
                break
            sleep(3)
            screen = observe('await-branding')
            if screen.state != 'welcome':
                raise Unverified(f'welcome page left before branding: {screen.state}')
        else:
            raise Unverified('installer never resolved the product name')
        evidence['product'] = product
        evidence['frontmost'] = True
        # isLive: the recipe's empty image installs the running system.
        if not screen.contains(LIVE_LINE):
            raise Unverified('welcome page does not offer to install the running live system')

        screen = next_page(screen, 'session', 'Get started')
        # Session: keyboard, language and time zone keep the live session's
        # values; Continue applies them (applySession) and moves on.
        screen = transition_slow(screen, 'source')
        # Source: nothing is selected until a row is clicked. Live media
        # offers the running system as "Install <product>".
        live_row = screen.matching(lambda text: text == normal('Install ' + product))
        if len(live_row) != 1:
            raise Unverified(f'expected one live source row "Install {product}"; got {len(live_row)}')
        click(screen, 'source install ' + normal(product), live_row[0][1])
        screen = observe('verify-source')
        if screen.state != 'source':
            raise Unverified('source choice left the source page')
        screen = next_page(screen, 'disk')
        # Get started starts discover-disks; the list fills when it answers.
        for _ in range(10):
            target = screen.matching(lambda text: text.startswith(normal(TARGET_DISK) + ' ')
                                     or text == normal(TARGET_DISK))
            if target or not screen.contains('Scanning for disks'):
                break
            sleep(3)
            screen = observe('await-disks')
            if screen.state != 'disk':
                raise Unverified(f'disk page left while scanning: {screen.state}')
        if len(target) != 1:
            raise Unverified(f'expected one disk row naming {TARGET_DISK}; got {len(target)}')
        click(screen, 'disk ' + TARGET_DISK, target[0][1])
        screen = observe('verify-disk')
        if screen.state != 'disk' or not screen.contains(f'Everything on {TARGET_DISK} will be erased'):
            raise Unverified('disk selection did not name the intended target')
        screen = next_page(screen, 'encryption')

        choice = ENCRYPTION[mode]
        # Once chosen, "Passphrase" is also the passphrase card's title,
        # below the list: the list row is the topmost.
        options = screen.boxes(choice)
        if not options:
            raise Unverified(f'encryption choice {choice} is not offered')
        click(screen, 'encryption ' + normal(choice), options[0])
        screen = observe('verify-encryption')
        if screen.state != 'encryption':
            raise Unverified('encryption choice left the encryption page')
        if mode == 'luks':
            first, again = screen.boxes('Enter passphrase'), screen.boxes('Confirm passphrase')
            if len(first) != 1 or len(again) != 1:
                raise Unverified('passphrase fields did not appear for the passphrase choice')
            private = tempfile.TemporaryDirectory(prefix='tunaos-niri-installer-')
            for action, box in (('field enter passphrase', first[0]), ('field confirm passphrase', again[0])):
                fill_at(screen, action, box, ((box[0] + box[2]) // 2, (box[1] + box[3]) // 2), password)
            screen = observe('verify-passphrase')
            if screen.state != 'encryption':
                raise Unverified('passphrase input left the encryption page')
            if screen.contains('Passphrases do not match'):
                raise Unverified('installer reports the passphrases differ')
        elif screen.has('Enter passphrase') or screen.has('Confirm passphrase'):
            raise Unverified('plain mode shows passphrase fields')
        screen = next_page(screen, 'account')
        if private is not None:
            private.cleanup()
            private = None

        labels = {label: screen.box(label) for label in ('Username', 'Password', 'Password again')}
        field_x = max(box[2] for box in labels.values()) + FIELD_INSET

        def field_point(label):
            box = labels[label]
            return (field_x, (box[1] + box[3]) // 2)

        fill_at(screen, 'field username', labels['Username'], field_point('Username'), user)
        screen = observe('verify-username')
        if screen.state != 'account' or not screen.has(user):
            raise Unverified('typed username is not shown on the account page')
        # fisherman's username rules, in the copy's words (validate_username_*).
        if any(normal(line).startswith(('use only', 'use 32', 'start the username', 'this username'))
               for line in screen.lines):
            raise Unverified('installer rejects the username')
        private = tempfile.TemporaryDirectory(prefix='tunaos-niri-installer-')
        fill_at(screen, 'field password', labels['Password'], field_point('Password'), user_password)
        fill_at(screen, 'field password again', labels['Password again'], field_point('Password again'),
                user_password)
        screen = observe('verify-password')
        if screen.state != 'account':
            raise Unverified('password input left the account page')
        if screen.contains('Passwords do not match'):
            raise Unverified('installer reports the account passwords differ')
        screen = next_page(screen, 'confirm')
        private.cleanup()
        private = None

        observed = {label: screen.value_right(label) for label in ('Target disk', 'Encryption', 'Username')}
        evidence['confirm'] = observed
        expected = {'Target disk': TARGET_DISK, 'Encryption': choice, 'Username': user}
        if {k: normal(v) for k, v in observed.items()} != {k: normal(v) for k, v in expected.items()}:
            raise Unverified(f'confirm page does not match the intended install: {observed}')
        # The Session step's picks and the generated hostname ride the
        # recipe; recorded as evidence, the install does not depend on them.
        for label in ('Filesystem', 'Language', 'Keyboard', 'Timezone', 'Hostname'):
            try:
                evidence['confirm'][label] = screen.value_right(label)
            except Unverified:
                evidence['confirm'][label] = None
        if not evidence['confirm']['Filesystem']:
            raise Unverified('confirm page does not name the filesystem')
        image = screen.value_right('Image')
        evidence['confirm']['Image'] = image
        if 'this system no download' not in normal(image):
            raise Unverified('confirm page does not install the running live system')
        if not screen.contains(f'Everything on {TARGET_DISK} will be erased. This cannot be undone.'):
            raise Unverified('confirm erase warning does not name the intended target')
        click(screen, 'install', screen.button('Install'))
        evidence['submitted'] = True
        screen = transition('confirm', 'progress')
        if not screen.contains('Installing ' + product):
            raise Unverified('progress page does not name the verified product')
        evidence['accepted'] = True
        evidence['account_created'] = True  # account step accepted, install submitted
        for _ in range(120):
            sleep(10)
            screen = observe('await-completion')
            if screen.state == 'done':
                if not screen.has(f'{product} is installed') or not screen.has('Restart now'):
                    raise Unverified('done page does not report this product installed')
                evidence['transitions'].append('done')
                evidence['completed'] = True
                return 0
            if screen.state not in ('progress', 'unknown'):
                raise Unverified(f'installation left progress unexpectedly: {screen.state}')
        raise Unverified('installer did not report completion within observation bound')
    except (Unverified, OSError, subprocess.SubprocessError, ValueError) as exc:
        evidence['error'] = str(exc)
        print('not ok - strict Niri GUI transaction: ' + str(exc), flush=True)
        return 1
    finally:
        if private is not None:
            private.cleanup()
        Path(outdir, 'walkthrough-niri.json').write_text(json.dumps(evidence, indent=2) + '\n')
        print('ok - strict Niri installer completed' if evidence['completed'] else
              '# no completed Niri installation proven', flush=True)
