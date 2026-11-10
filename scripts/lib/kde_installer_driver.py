"""Fail-closed GUI driver for the bundled KDE installer (org.tunaos.InstallerKde).

Contract read from tuna-os/bootc-installer frontends/kde (Wizard.qml step
model: welcome, disk, encryption, account, confirm, progress, done) and
measured on the strict harness's 1280x800 Breeze-dark captures. The account
step is where the installed system's only user is created: on Plasma that is
the GUI account path the receipt's gui_account_created stands for, proven
afterwards by the greeter login (scripts/lib/kde_first_boot.py).

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
# The live media installs the running container: the confirm page's Image
# row says so instead of naming a reference (confirm/main.qml).
LIVE_IMAGE = 'the running live system'
# shared/branding/copy-defaults.json welcome_button; the grouper bundle
# (run 42763004792) draws it as "Get started" with a trailing arrow.
WELCOME_BUTTON = 'Get started'
ENCRYPTION = {'plain': 'No encryption', 'luks': 'Passphrase'}
# A FormCard text field draws its label above the input; the input's
# interior sits this far below the label's OCR box (measured, 1280x800).
FIELD_BELOW_LABEL = 26
# The measured UI contract: the live overlay's InstallerKde receipt
# (org.tunaos.live-overlay.installer). A different bundle is unmeasured.
BUNDLE_DIGEST = 'sha256:9b1de9b1c2088dff9ff40751337968667511c32ffa3b8005e0426299f8653ce0'


def classify(lines):
    text = {normal(line) for line in lines}
    joined = '\n'.join(text)
    if 'installation failed' in joined:
        return 'failed'
    if 'restart now' in text and any(line.endswith(' is installed') for line in text):
        return 'done'
    if 'do not power off the computer' in joined:
        return 'progress'
    if {'target disk', 'filesystem', 'encryption', 'hostname', 'image'} <= text:
        return 'confirm'
    if 'create the account you will sign in with' in joined:
        return 'account'
    if 'encryption protects your files' in joined:
        return 'encryption'
    if 'choose the disk where' in joined:
        return 'disk'
    if 'this wizard will guide you through' in joined:
        return 'welcome'
    return 'unknown'


# Breeze's labels at this size: OCR reads "rn" as "m" ("Usemame", grouper
# run 42776467083). Fold both sides so the exact-label match still holds.
def fold(text):
    return normal(text).replace('rn', 'm')


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
        # Breeze dark: light text on dark fills. The low threshold keeps
        # white labels on the highlighted (blue) default button and selected
        # rows; 2x reads device paths whose slashes 1x garbles.
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

    def boxes(self, label, below=0):
        """Every distinct place OCR read exactly label (passes merged)."""
        def holds(outer, inner):
            cx, cy = (inner[0] + inner[2]) // 2, (inner[1] + inner[3]) // 2
            return outer[0] <= cx <= outer[2] and outer[1] <= cy <= outer[3]

        found = []
        for text, box in self.rows:
            if fold(text) != fold(label) or box[1] < below:
                continue
            same = [seen for seen in found if holds(seen, box) or holds(box, seen)]
            if not same:
                found.append(box)
            elif (box[2] - box[0]) * (box[3] - box[1]) < (same[0][2] - same[0][0]) * (same[0][3] - same[0][1]):
                found[found.index(same[0])] = box
        for box in found:
            if not (0 <= box[0] < box[2] <= self.width and 0 <= box[1] < box[3] <= self.height):
                raise Unverified('control box is outside the capture')
        return sorted(found, key=lambda b: (b[1], b[0]))

    def box(self, label, below=0):
        found = self.boxes(label, below)
        if len(found) != 1:
            raise Unverified(f'expected one exact control label: {label}; got {len(found)}')
        return found[0]

    def has(self, label):
        return any(fold(text) == fold(label) for text in self.lines)

    def value_below(self, label):
        """The FormTextDelegate description drawn under a confirm-page label."""
        top = self.box(label)
        candidates = [(box[1], text) for text, box in self.rows
                      if 0 < box[1] - top[3] <= 30 and abs(box[0] - top[0]) <= 8
                      and normal(text) != normal(label)]
        values = {' '.join(text.split()) for _, text in candidates}
        if len(values) != 1:
            raise Unverified(f'confirm row {label} has absent or ambiguous value: {sorted(values)}')
        return values.pop()


# Breeze's small grey path text: OCR reads the slashes of "/dev/vda" as i, l
# or | ("idevivda + 64 GiB + virtlO", grouper run 42769339506). Only those
# confusions are forgiven, and only around the fixed words dev and vda.
_SLASH = r'[/il1|]'
_DEVICE = re.compile(r'(?<![a-z0-9])' + _SLASH + r'?dev' + _SLASH + r'v?da(?![a-z0-9])')


def device_text(text):
    """text with every OCR spelling of TARGET_DISK written as TARGET_DISK."""
    return _DEVICE.sub(TARGET_DISK, ' '.join(text.split()).lower())


def disk_row(screen):
    """The one disk row for TARGET_DISK: its title (the path when the model is
    unknown, as on virtio) or its subtitle "<path> • <size> • <bus>"."""
    boxes = sorted((box for text, box in screen.rows
                    if (seen := device_text(text)) == TARGET_DISK or seen.startswith(TARGET_DISK + ' ')),
                   key=lambda b: b[1])
    # A title and its subtitle (and repeated OCR passes) sit within 30 px:
    # one cluster is one disk row.
    clusters = [b for i, b in enumerate(boxes) if i == 0 or b[1] - boxes[i - 1][1] > 30]
    if len(clusters) != 1:
        raise Unverified(f'expected one disk row for {TARGET_DISK}; got {len(clusters)}')
    return clusters[0]


def product_from_welcome(screen):
    for line in screen.lines:
        match = re.fullmatch(r'This wizard will guide you through installing (\S+) onto this computer\.?',
                             ' '.join(line.split()))
        if match:
            return match.group(1)
    raise Unverified('welcome page does not name the product')


def drive(outdir, mode, vnc, capture, keys, type_text, installer_digest, password, user, user_password,
          screen_factory=Screen, pointer=click_unix, sleep=time.sleep, clock=time.monotonic):
    """Bounded ordered GUI transaction. Submit once; then observe only."""
    evidence = {'driver': 'kde-installer', 'installer_digest': installer_digest,
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
        if screen.state == 'failed':
            raise Unverified('installer reported failure')
        return screen

    def click_at(screen, action, box, point):
        evidence['clicks'].append({'action': action, 'state': screen.state,
                                   'box': list(box), 'point': list(point)})
        if pointer(vnc, *point, screen.width, screen.height) is not True:
            raise Unverified('pointer transport did not acknowledge release')
        sleep(2)

    def click(screen, label, box=None):
        box = box or screen.box(label)
        click_at(screen, normal(label) or label, box,
                 ((box[0] + box[2]) // 2, (box[1] + box[3]) // 2))

    def fill(screen, label, value, box=None):
        """Focus the field drawn under label, replace its text with value."""
        box = box or screen.box(label)
        point = ((box[0] + box[2]) // 2, box[3] + FIELD_BELOW_LABEL)
        if not point[1] < screen.height:
            raise Unverified('field below label is outside the capture')
        click_at(screen, 'field ' + normal(label), box, point)
        keys('ctrl-a')
        type_text(value)
        sleep(1)

    def transition(previous, expected, polls=12):
        for _ in range(polls):
            screen = observe('await-' + expected)
            if screen.state == expected:
                evidence['transitions'].append(expected)
                return screen
            # The wizard slides pages; a mid-animation frame reads unknown.
            if screen.state not in (previous, 'unknown'):
                raise Unverified(f'unexpected ordered transition: {previous} -> {screen.state}')
            sleep(3)
        raise Unverified(f'GUI did not transition from {previous} to {expected}')

    def next_page(screen, expected, label='Next'):
        # The button draws an arrow icon beside its label; normal() drops it.
        click(screen, label)
        return transition(screen.state, expected)

    try:
        # An unmeasured bundle is still driven, so its frames can calibrate
        # the next contract, but it can never pass: the result fails closed.
        evidence['bundle_measured'] = installer_digest == BUNDLE_DIGEST
        if mode not in ENCRYPTION or not re.fullmatch('[a-z0-9_.-]{8,64}', password):
            raise Unverified('unsupported mode or test-only passphrase format')
        if not re.fullmatch(USER_PATTERN, user) or not re.fullmatch('[a-z0-9_.-]{8,64}', user_password):
            raise Unverified('unsupported test account or password format')
        screen = transition('unknown', 'welcome', polls=40)
        product = product_from_welcome(screen)
        evidence['product'] = product
        evidence['frontmost'] = True
        # Welcome's button carries the product copy (welcome_button).
        screen = next_page(screen, 'disk', label=WELCOME_BUTTON)
        click(screen, TARGET_DISK, box=disk_row(screen))
        screen = next_page(observe('verify-disk'), 'encryption')
        choice = ENCRYPTION[mode]
        # 'Passphrase' is both a radio label and, once chosen, the first
        # field's label: the radio is the topmost.
        click(screen, choice, box=screen.boxes(choice)[0] if screen.boxes(choice) else None)
        screen = observe('verify-encryption')
        if screen.state != 'encryption':
            raise Unverified('encryption choice left the encryption page')
        if mode == 'luks':
            fields = screen.boxes('Passphrase')
            if len(fields) != 2:
                raise Unverified('passphrase fields did not appear for the passphrase choice')
            confirm = screen.box('Confirm passphrase')
            private = tempfile.TemporaryDirectory(prefix='tunaos-kde-installer-')
            fill(screen, 'Passphrase', password, box=fields[1])
            fill(screen, 'Confirm passphrase', password, box=confirm)
            screen = observe('verify-passphrase')
            if screen.state != 'encryption':
                raise Unverified('passphrase input left the encryption page')
            if any('do not match' in normal(line) for line in screen.lines):
                raise Unverified('installer reports the passphrases differ')
        elif screen.has('Confirm passphrase'):
            raise Unverified('plain mode shows passphrase fields')
        screen = next_page(screen, 'account')
        if private is not None:
            private.cleanup()
            private = None
        fill(screen, 'Username', user)
        screen = observe('verify-username')
        if screen.state != 'account' or not screen.has(user):
            raise Unverified('typed username is not shown on the account page')
        private = tempfile.TemporaryDirectory(prefix='tunaos-kde-installer-')
        fill(screen, 'Password', user_password)
        fill(screen, 'Confirm password', user_password)
        screen = observe('verify-password')
        if screen.state != 'account':
            raise Unverified('password input left the account page')
        screen = next_page(screen, 'confirm')
        private.cleanup()
        private = None
        observed = {label: screen.value_below(label)
                    for label in ('Target disk', 'Encryption', 'Username', 'Image')}
        evidence['confirm'] = dict(observed)
        observed['Target disk'] = device_text(observed['Target disk'])
        expected = {'Target disk': TARGET_DISK, 'Encryption': choice,
                    'Username': user, 'Image': LIVE_IMAGE}
        if observed != expected:
            raise Unverified(f'confirm page does not match the intended install: {observed}')
        warning = f'Everything on {TARGET_DISK} will be erased. This cannot be undone.'
        if not any(device_text(line) == warning.lower() for line in screen.lines):
            raise Unverified('confirm erase warning does not name the intended target')
        click(screen, 'Install')
        evidence['submitted'] = True
        screen = transition('confirm', 'progress')
        if not any(normal(line).startswith('installing ' + normal(product)) for line in screen.lines):
            raise Unverified('progress page does not name the verified product')
        evidence['accepted'] = True
        evidence['account_created'] = True  # account step accepted, install submitted
        for _ in range(120):
            sleep(10)
            screen = observe('await-completion')
            if screen.state == 'done':
                if not screen.has(f'{product} is installed'):
                    raise Unverified('done page names a different product')
                evidence['transitions'].append('done')
                evidence['completed'] = True
                if not evidence['bundle_measured']:
                    raise Unverified('unsupported installer bundle: measured UI contract digest differs '
                                     f'(observed {installer_digest or "none"})')
                return 0
            if screen.state not in ('progress', 'unknown'):
                raise Unverified(f'installation left progress unexpectedly: {screen.state}')
        raise Unverified('installer did not report completion within observation bound')
    except (Unverified, OSError, subprocess.SubprocessError, ValueError) as exc:
        evidence['error'] = str(exc)
        print('not ok - strict KDE GUI transaction: ' + str(exc), flush=True)
        return 1
    finally:
        if private is not None:
            private.cleanup()
        Path(outdir, 'walkthrough-kde.json').write_text(json.dumps(evidence, indent=2) + '\n')
        print('ok - strict KDE installer completed' if evidence['completed'] and evidence.get('bundle_measured') else
              '# no completed KDE installation proven', flush=True)
