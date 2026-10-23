"""Fail-closed GUI driver for the observed GNOME installer, using real pointer input.

Contract measured from bootc-installer 9f582fe0 and bundle sha256:04252eaf...
No guest execution, disk injection, or synthetic completion markers.
"""
import csv
import io
import json
from pathlib import Path
import re
import socket
import struct
import subprocess
import time
import tempfile
import os
import stat


class Unverified(RuntimeError):
    pass


def normal(text):
    return ' '.join(re.findall(r'[a-z0-9]+', text.lower()))


def classify(lines):
    text = '\n'.join(normal(line) for line in lines)
    if 'installation failed' in text:
        return 'failed'
    if 'no disks detected' in text:
        return 'no-disk'
    if 'save your recovery key' in text:
        return 'recovery'
    if 'type to search' in text:
        return 'overview'
    if (any(normal(line).endswith(' is installed') for line in lines)
            and 'restart now' in text and 'remove the installation media' in text
            and 'elapsed' not in text):
        return 'done'
    if ('installing' in [normal(line) for line in lines]
            and 'do not power off the computer' in text
            and any(re.search(r'\d+:\d{2} elapsed', line.lower()) for line in lines)):
        return 'progress'
    for state, headings in (
        ('summary', ('confirm installation', 'review your choices')),
        ('encryption', ('disk encryption',)),
        ('disk', ('install location', 'installation location')),
        ('welcome', ('welcome to ',)),
    ):
        if any(any(normal(line) == heading or (state == 'welcome' and normal(line).startswith(heading))
                   for line in lines) for heading in headings):
            return state
    return 'unknown'


def welcome_action(screen):
    """Exact pinned welcome ActionRow, distinct from the final Install button."""
    titles = [line for line in screen.lines if normal(line).startswith('welcome to ')]
    if len(titles) != 1:
        raise Unverified('welcome heading is absent or ambiguous')
    match = re.fullmatch(r'Welcome to ([A-Za-z0-9][A-Za-z0-9 ._-]{0,63})', titles[0])
    if not match:
        raise Unverified('unsupported welcome product heading')
    label = 'Install ' + match[1]
    title, action = screen.box(titles[0]), screen.box(label)
    description = screen.box('Installs to your internal disk.')
    power = screen.box('Power Off')
    # A full-size heading and ordered, aligned action rows establish this
    # foreground page. A shell overview thumbnail must not earn input.
    if not (20 <= title[3]-title[1] <= 40
            and abs((title[0]+title[2])/2-screen.width/2) <= screen.width*.15
            and screen.height*.15 <= title[1] <= screen.height*.5
            and 12 <= action[3]-action[1] <= 26
            and 20 <= action[1]-title[3] <= 100
            and title[0]-200 <= action[0] <= title[0]+50
            and 2 <= description[1]-action[3] <= 30
            and abs(description[0]-action[0]) <= 8
            and 15 <= power[1]-description[3] <= 70
            and abs(power[0]-action[0]) <= 40):
        raise Unverified('welcome action geometry does not prove a foreground installer')
    return label



def ocr_rows(tsv, strict=False):
    """Keep word geometry separately from line grouping; never infer a device."""
    if len(tsv) > 1024 * 1024:
        raise Unverified('OCR output exceeded bound')
    groups, kept = {}, []
    for word in csv.DictReader(io.StringIO(tsv), delimiter='\t'):
        if not word.get('text', '').strip():
            continue
        confidence = float(word['conf'])
        if not 40 <= confidence <= 100:
            if strict:
                raise Unverified('summary crop contains uncertain OCR words')
            continue
        kept.append(word)
        key = tuple(word[k] for k in ('block_num', 'par_num', 'line_num'))
        groups.setdefault(key, []).append(word)
    rows = []
    for words in groups.values():
        left = min(int(w['left']) for w in words)
        top = min(int(w['top']) for w in words)
        right = max(int(w['left']) + int(w['width']) for w in words)
        bottom = max(int(w['top']) + int(w['height']) for w in words)
        rows.append((' '.join(w['text'] for w in words), (left, top, right, bottom)))
    return kept, rows

class Screen:
    def __init__(self, path):
        self.path = Path(path)
        with self.path.open('rb') as source:
            header = source.read(24)
        if header[:8] != b'\x89PNG\r\n\x1a\n':
            raise Unverified('capture is not PNG')
        self.width, self.height = struct.unpack('!II', header[16:24])
        if not (640 <= self.width <= 1920 and 480 <= self.height <= 1200):
            raise Unverified('unsupported framebuffer dimensions')
        # Threshold measured against the light gray entry labels and purple header
        # in run 39619460539. Keep original pixels for control-state checks.
        with tempfile.NamedTemporaryFile(suffix='.png') as prepared:
            subprocess.run(['convert', str(path), '-colorspace', 'gray',
                            '-threshold', '90%', prepared.name],
                           capture_output=True, timeout=20, check=True)
            result = subprocess.run(['tesseract', prepared.name, 'stdout',
                                     '--psm', '11', 'tsv'],
                                    capture_output=True, text=True, timeout=30, check=True)
        self.words, self.rows = ocr_rows(result.stdout)
        self.lines = [row[0] for row in self.rows]
        self.state = classify(self.lines)
        self._pixels = None

    def box(self, label):
        boxes = [box for text, box in self.rows if normal(text) == normal(label)]
        if len(boxes) != 1:
            raise Unverified(f'expected one exact control label: {label}; got {len(boxes)}')
        return boxes[0]


    def summary_cards(self):
        """One measured OCR path, anchored to unique full-frame label words.

        The current contract is deliberately limited to the retained 1280x800
        layout. Unsupported geometry fails closed instead of probing crops.
        """
        if (self.width, self.height) != (1280, 800) or self.state != 'summary':
            raise Unverified('unsupported summary framebuffer or state')
        heading = self.box('Confirm installation')
        if not (20 <= heading[3]-heading[1] <= 40
                and abs((heading[0]+heading[2])/2-640) <= 80
                and 260 <= heading[1] <= 290):
            raise Unverified('summary heading does not prove the measured foreground layout')
        crops = {}
        for label, expected_y in (('Disk', 341), ('Encryption', 506)):
            anchors = [word for word in self.words if word['text'] == label]
            if len(anchors) != 1:
                raise Unverified('summary label word is absent or ambiguous')
            anchor = anchors[0]
            x, y, w, h = (int(anchor[key]) for key in ('left', 'top', 'width', 'height'))
            if not (abs(x-395) <= 4 and abs(y-expected_y) <= 4
                    and 10 <= h <= 18 and 20 <= w <= 90):
                raise Unverified('summary label anchor is outside the measured card layout')
            crops[label] = f'560x45+{x-5}+{y-6}'
        cards = {}
        for label, crop in crops.items():
            with tempfile.NamedTemporaryFile(suffix='.png') as prepared:
                # Unlike the full-frame navigation OCR, preserve antialiasing.
                # The thresholded retained card misreads the device path.
                subprocess.run(['convert', str(self.path), '-crop', crop, '+repage',
                                '-resize', '300%', '-colorspace', 'gray', prepared.name],
                               capture_output=True, timeout=20, check=True)
                result = subprocess.run(['tesseract', prepared.name, 'stdout',
                                         '--psm', '6', 'tsv'],
                                        capture_output=True, text=True, timeout=30, check=True)
            _, cards[label] = ocr_rows(result.stdout, strict=True)
        return cards

    def rgb(self, x, y):
        if self._pixels is None:
            result = subprocess.run(['convert', str(self.path), '-depth', '8', 'rgb:-'],
                                    capture_output=True, timeout=20, check=True)
            if len(result.stdout) != self.width * self.height * 3:
                raise Unverified('invalid pixel buffer')
            self._pixels = result.stdout
        if not (0 <= x < self.width and 0 <= y < self.height):
            raise Unverified('pixel coordinate outside capture')
        offset = (y * self.width + x) * 3
        return tuple(self._pixels[offset:offset+3])

    def switch(self, label):
        # Exact observed light-theme Adwaita card. Its switch is right-aligned
        # 250px from the heading centre. Reject layout/color ambiguity.
        heading = self.box('Disk Encryption')
        row = self.box(label)
        cx = (heading[0] + heading[2]) // 2 + 250
        cy = (row[1] + row[3]) // 2 + 7
        purple = gray = white = 0
        for y in range(cy-5, cy+6):
            for x in range(cx-19, cx+20):
                r, g, b = self.rgb(x, y)
                purple += int(r > 100 and b > 100 and g < r * .8 and b > g * 1.1)
                gray += int(205 <= r <= 235 and abs(r-g) < 4 and abs(g-b) < 4)
                white += int(min(r, g, b) > 245)
        if white < 30:
            raise Unverified(f'unrecognized switch geometry: {label}')
        if purple > 100 and gray < 30:
            return True
        if gray > 100 and purple < 30:
            return False
        raise Unverified(f'ambiguous switch state: {label}')

    def enabled(self, label):
        box = self.box(label)
        # Text is white; sample the button background immediately beside it.
        r, g, b = self.rgb(box[0]-7, (box[1]+box[3])//2)
        return r > 100 and b > 100 and g < r*.65 and b > g*1.1


def _read(sock, size, deadline=None):
    data = b''
    while len(data) < size:
        if deadline is not None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise Unverified('VNC transaction deadline exceeded')
            sock.settimeout(remaining)
        chunk = sock.recv(size-len(data))
        if not chunk:
            raise Unverified('VNC disconnected')
        data += chunk
    return data


def _send(sock, data, deadline):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise Unverified('VNC transaction deadline exceeded')
    sock.settimeout(remaining)
    sock.sendall(data)


def _pointer_barrier(sock, width, height, deadline):
    """Observe QEMU's first update reply after release, not guest activation."""
    # No earlier update request or pseudo-encoding is sent on this connection.
    # Stream order makes this reply a server-side processing barrier. QEMU
    # 8.2.2 otherwise handles HUP before IN and can discard a queued release.
    _send(sock, struct.pack('!BBHHHH', 3, 0, 0, 0, 1, 1), deadline)
    def read(size):
        return _read(sock, size, deadline)

    kind, _, rectangles = struct.unpack('!BBH', read(4))
    if kind != 0 or not 1 <= rectangles <= 4096:
        raise Unverified('VNC release response is not a bounded update')
    x, y, w, h, encoding = struct.unpack('!HHHHi', read(12))
    if encoding != 0 or not (w > 0 and h > 0 and x+w <= width and y+h <= height):
        raise Unverified('VNC release response rectangle is invalid')
    # The validated reply prefix is sufficient: the request was processed.
    # Pixel content and guest UI progress are not inferred from this barrier.
    return True


def click_unix(path, x, y, width, height):
    """RFB 3.8 pointer event over an owned local UNIX socket only."""
    if not (0 <= x < width <= 1920 and 0 <= y < height <= 1200):
        raise Unverified('invalid pointer coordinates')
    info = Path(path).lstat()
    if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.getuid():
        raise Unverified('VNC endpoint is not an owned UNIX socket')
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        deadline = time.monotonic() + 5
        sock.settimeout(5)
        def read(size):
            return _read(sock, size, deadline)
        sock.connect(str(path))
        if read(12) != b'RFB 003.008\n':
            raise Unverified('unsupported VNC protocol')
        _send(sock, b'RFB 003.008\n', deadline)
        count = read(1)[0]
        if not 0 < count <= 16 or 1 not in read(count):
            raise Unverified('local VNC does not offer no-auth transport')
        _send(sock, b'\x01', deadline)
        if read(4) != b'\0\0\0\0':
            raise Unverified('local VNC handshake failed')
        _send(sock, b'\x01', deadline)
        init = read(24)
        actual_width, actual_height = struct.unpack('!HH', init[:4])
        length = struct.unpack('!I', init[20:24])[0]
        if length > 4096 or (actual_width, actual_height) != (width, height):
            raise Unverified('VNC geometry differs from verified capture')
        read(length)
        # QEMU 8.2.2 initializes this client's absolute pointer mode in
        # set_encodings(), even with raw only (ui/vnc.c). Without it, a
        # fresh connection can treat these coordinates as relative motion.
        _send(sock, struct.pack('!BBHi', 2, 0, 1, 0), deadline)
        _send(sock, struct.pack('!BBHH', 5, 0, x, y), deadline)
        _send(sock, struct.pack('!BBHH', 5, 1, x, y), deadline)
        time.sleep(.1)
        _send(sock, struct.pack('!BBHH', 5, 0, x, y), deadline)
        return _pointer_barrier(sock, width, height, deadline)


BUNDLE_DIGEST = 'sha256:04252eaf80ee5675aa37bdb482847c77310efbee058dc63ba161a1d5991f9823'


def verify_summary_cards(cards, mode):
    """Exact label/value association, never a fuzzy path or whole-page match."""
    if mode not in ('plain', 'luks') or set(cards) != {'Disk', 'Encryption'}:
        raise Unverified('invalid summary card contract')
    expected = {'Disk': '/dev/vda (64 GiB)',
                'Encryption': 'No encryption' if mode == 'plain' else 'Passphrase'}
    for label, value in expected.items():
        rows = cards[label]
        if len(rows) != 2:
            raise Unverified('summary card has absent or ambiguous rows')
        title, subtitle = rows
        if (' '.join(title[0].split()) != label
                or ' '.join(subtitle[0].split()) != value):
            raise Unverified('summary card does not exactly match the intended target or encryption')
        a, b = title[1], subtitle[1]
        if not (all(len(box) == 4 and 0 <= box[0] < box[2] <= 1680
                    and 0 <= box[1] < box[3] <= 135 for box in (a, b))
                and 10 <= a[1] <= 25 and 25 <= a[3]-a[1] <= 50
                and 70 <= b[1] <= 90 and 25 <= b[3]-b[1] <= 45
                and 10 <= b[1]-a[3] <= 45 and abs(a[0]-b[0]) <= 8):
            raise Unverified('summary label/value row association is unverified')


def verify_summary(screen, mode):
    verify_summary_cards(screen.summary_cards(), mode)
    warning = 'Everything on /dev/vda will be erased. This cannot be undone.'
    warnings = [' '.join(line.split()) for line in screen.lines
                if 'will be erased' in line.lower()]
    if warnings != [warning]:
        raise Unverified('summary erase warning does not uniquely match the intended target')
    # Independent full-frame mode observation must agree with the card crop.
    expected = 'No encryption' if mode == 'plain' else 'Passphrase'
    screen.box(expected)
    if mode == 'luks' and any('tpm' in line.lower() or 'hardware backed' in normal(line)
                              for line in screen.lines):
        raise Unverified('summary selected hardware encryption instead of passphrase-only')


def drive(outdir, mode, vnc, capture, keys, type_text, installer_digest,
          password, screen_factory=Screen, pointer=click_unix, sleep=time.sleep,
          clock=time.monotonic):
    """Bounded ordered GUI transaction. Submit once; then observe only.

    Disk/image pages are intentionally auto-skipped for a single valid choice
    by the pinned frontend. The final summary is the required target proof.
    """
    evidence = {'driver': 'gnome-9f582fe0', 'installer_digest': installer_digest,
                'mode': mode, 'frames': [], 'transitions': [],
                'submitted': False, 'submit_attempted': False, 'accepted': False,
                'completed': False, 'clicks': []}
    deadline = clock() + 1200
    counter = 0

    def observe(label):
        nonlocal counter
        if clock() >= deadline or counter >= 128:
            raise Unverified('GUI observation deadline/frame bound exceeded')
        path = capture(counter, label)
        counter += 1
        if not path:
            raise Unverified('GUI capture unavailable')
        screen = screen_factory(path)
        evidence['frames'].append({'file': Path(path).name, 'state': screen.state,
                                   'text': screen.lines})
        if screen.state in ('no-disk', 'recovery', 'failed'):
            raise Unverified(f'invalid installer state: {screen.state}')
        if screen.state == 'overview':
            # Preserve both frames, but do not turn a launch-frontmost defect
            # into a qualified install by silently dismissing it.
            if not evidence['submitted']:
                keys('esc')
                after = capture(counter, 'overview-after-escape')
                counter += 1
                evidence['overview_after_escape'] = Path(after).name if after else None
            raise Unverified('installer launched behind positively identified shell overview')
        return screen

    def click(screen, label, enabled=False):
        box = screen.box(label)
        if enabled and not screen.enabled(label):
            raise Unverified(f'control is disabled or its state is unknown: {label}')
        action = ('welcome-install' if screen.state == 'welcome' else {
            'Encrypt this disk': 'encrypt-disk',
            'Use hardware-backed encryption': 'hardware-encryption',
            'Password': 'password-field', 'Confirm Password': 'confirm-password-field',
            'Next': 'next', 'Install': 'submit-install',
        }.get(label))
        if action is None:
            raise Unverified('unsupported diagnostic control')
        point = [(box[0]+box[2])//2, (box[1]+box[3])//2]
        attempt = {'action': action, 'state': screen.state, 'box': list(box),
                   'point': point, 'frame': [screen.width, screen.height],
                   'transport': 'uncertain'}
        evidence['clicks'].append(attempt)
        if action == 'submit-install':
            evidence['submit_attempted'] = True
        if pointer(vnc, *point, screen.width, screen.height) is not True:
            raise Unverified('pointer transport did not acknowledge release')
        attempt['transport'] = 'server-response'
        sleep(2)

    def transition(previous, expected):
        for _ in range(12):
            screen = observe('await-' + expected)
            if screen.state == expected:
                evidence['transitions'].append(expected)
                return screen
            if screen.state not in (previous, 'unknown'):
                raise Unverified(f'unexpected ordered transition: {previous} -> {screen.state}')
            sleep(3)
        raise Unverified(f'GUI did not transition from {previous} to {expected}')

    def toggle(screen, label, wanted):
        if screen.switch(label) != wanted:
            click(screen, label)
            screen = observe('verify-toggle')
        if screen.state != 'encryption' or screen.switch(label) != wanted:
            raise Unverified(f'toggle change not verified: {label}')
        return screen

    try:
        if installer_digest != BUNDLE_DIGEST:
            raise Unverified('unsupported installer bundle: measured UI contract digest differs')
        if mode not in ('plain', 'luks') or not re.fullmatch('[a-z0-9_.-]{8,64}', password):
            raise Unverified('unsupported mode or test-only passphrase format')
        screen = transition('unknown', 'welcome')
        action = welcome_action(screen)
        evidence['frontmost'] = True
        click(screen, action)
        screen = transition('welcome', 'encryption')
        screen = toggle(screen, 'Encrypt this disk', mode == 'luks')
        if mode == 'luks':
            screen = toggle(screen, 'Use hardware-backed encryption', False)
            # Both unique labels must be visible before typing any test data.
            screen.box('Password')
            screen.box('Confirm Password')
            for label in ('Password', 'Confirm Password'):
                click(screen, label)
                keys('ctrl-a')
                type_text(password)
                sleep(1)
                screen = observe('verify-field-' + label.lower().replace(' ', '-'))
                if screen.state != 'encryption':
                    raise Unverified('password input left the verified encryption page')
            # The exact frontend enables Next only for nonempty equal fields.
            if not any(normal(line) in ('weak make it longer or more complex',
                                        'fair consider making it longer',
                                        'strong passphrase') for line in screen.lines):
                raise Unverified('password strength feedback absent after field input')
        if screen.switch('Encrypt this disk') != (mode == 'luks'):
            raise Unverified('encryption mode changed during field input')
        if mode == 'luks' and screen.switch('Use hardware-backed encryption'):
            raise Unverified('hardware encryption unexpectedly enabled')
        click(screen, 'Next', enabled=True)
        screen = transition('encryption', 'summary')
        verify_summary(screen, mode)
        click(screen, 'Install', enabled=True)
        evidence['submitted'] = True
        screen = transition('summary', 'progress')
        evidence['accepted'] = True
        # No pointer/key events after accepted progress. Completion requires
        # the actual done page, never the progress tour's Installation Finished.
        for _ in range(80):
            sleep(10)
            screen = observe('await-completion')
            if screen.state == 'done':
                evidence['completed'] = True
                evidence['transitions'].append('done')
                return 0
            if screen.state not in ('progress', 'unknown'):
                raise Unverified(f'installation left progress unexpectedly: {screen.state}')
        raise Unverified('installer did not report completion within observation bound')
    except (Unverified, OSError, subprocess.SubprocessError, ValueError) as exc:
        evidence['error'] = str(exc)
        print('not ok - strict GNOME GUI transaction: ' + str(exc), flush=True)
        return 1
    finally:
        Path(outdir, 'walkthrough-gnome.json').write_text(json.dumps(evidence, indent=2)+'\n')
        print('ok - strict GNOME installer completed' if evidence['completed'] else
              '# no completed installation proven', flush=True)
