"""Fail-closed GUI driver for the observed GNOME installer, using real pointer input.

Contract measured from bootc-installer 23e47c51 and bundle sha256:ff28c254...
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


PROGRESS_TITLES = {
    'Checking your drive', 'Setting up your drive', 'Preparing the boot system',
    'Securing your drive', 'Formatting your drive', 'Almost ready',
    'Preparing data storage', 'Setting up auto-unlock', 'Installing your apps',
    'Configuring your system', 'Finishing up',
}


def progress_title(text):
    text = text.removesuffix('...').removesuffix('…')
    return text in PROGRESS_TITLES or bool(re.fullmatch(
        r'Installing [A-Z][A-Za-z0-9 ._-]{0,63}', text))


def verify_progress_rows(rows, heading):
    """Require independent same-frame title, warning, clock and percentage."""
    predicates = [progress_title,
                  lambda text: text == 'Do not power off the computer.',
                  lambda text: bool(re.fullmatch(r'(?:0|[1-9][0-9]{0,2}):[0-5][0-9] elapsed', text)),
                  lambda text: bool(re.fullmatch(r'(?:[0-9]|[1-9][0-9]|100)%', text))]
    bounds = [(5, 35, 15, 45, 90, 1500, 65, 100),
              (5, 35, 150, 185, 480, 610, 190, 220),
              (5, 35, 240, 275, 170, 390, 280, 315),
              (2280, 2420, 70, 105, 2450, 2495, 120, 155)]
    selected = []
    for predicate, limit in zip(predicates, bounds):
        matches = [(text, box) for text, box in rows if predicate(text)]
        if len(matches) != 1:
            raise Unverified('progress marker is absent or ambiguous')
        text, box = matches[0]
        if (len(box) != 4 or any(type(value) is not int for value in box)
                or not all(limit[2*i] <= box[i] <= limit[2*i+1] for i in range(4))):
            raise Unverified('progress marker geometry is not verified')
        selected.append(text)
    if selected[0] != heading:
        raise Unverified('progress title disagrees with full capture')
    return selected


def welcome_title_box(screen, observed, expected):
    """Cross-check fragmented full-frame OCR with one original-pixel heading crop."""
    title = screen.box(observed)
    if observed == expected:
        return title
    if (not getattr(screen, 'path', None)
            or not 20 <= title[3]-title[1] <= 40
            or abs((title[0]+title[2])/2-screen.width/2) > screen.width*.15
            or not screen.height*.15 <= title[1] <= screen.height*.5):
        raise Unverified('welcome product heading disagrees with the action')
    fragments = sorted((box for text, box in screen.rows if text != observed
                        and abs(box[1]-title[1]) <= 8 and abs(box[3]-title[3]) <= 8
                        and box[0] >= title[2]), key=lambda box: box[0])
    edge = title[2]
    if not fragments:
        raise Unverified('welcome heading is not a verified OCR fragment')
    for box in fragments:
        if not 0 <= box[0]-edge <= 64:
            raise Unverified('welcome heading fragments are absent or ambiguous')
        edge = box[2]
    left, right = max(0, title[0]-200), min(screen.width, screen.width-title[0]+200)
    top, bottom = max(0, title[1]-8), min(screen.height, title[3]+8)
    if not (0 < right-left <= screen.width and 20 <= bottom-top <= 56):
        raise Unverified('welcome heading crop is outside its measured bounds')
    with tempfile.NamedTemporaryFile(suffix='.png') as prepared:
        # Run 41255653588: full OCR split the heading, but this unmodified
        # 670x36 crop at (305,314) observed the complete published title.
        subprocess.run(['convert', str(screen.path), '-crop',
                        f'{right-left}x{bottom-top}+{left}+{top}', '+repage', prepared.name],
                       capture_output=True, timeout=20, check=True)
        result = subprocess.run(['tesseract', prepared.name, 'stdout', '--psm', '7', 'tsv'],
                                capture_output=True, text=True, timeout=30, check=True)
    _, rows = ocr_rows(result.stdout, strict=True)
    if len(rows) != 1 or rows[0][0] != expected:
        raise Unverified('welcome product heading disagrees with the action')
    box = rows[0][1]
    if not (0 <= box[0] < box[2] <= right-left and 0 <= box[1] < box[3] <= bottom-top):
        raise Unverified('welcome heading text is outside its crop')
    return (left+box[0], top+box[1], left+box[2], top+box[3])


def welcome_action(screen):
    """Exact pinned welcome ActionRow, distinct from the final Install button."""
    titles = [line for line in screen.lines if normal(line).startswith('welcome to ')]
    if len(titles) != 1:
        raise Unverified('welcome heading is absent or ambiguous')
    actions = [line for line in screen.lines
               if re.fullmatch(r'Install [A-Za-z0-9][A-Za-z0-9 ._-]{0,63}', line)]
    if len(actions) != 1:
        raise Unverified('welcome install action is absent or ambiguous')
    label = actions[0]
    action = screen.box(label)
    title = welcome_title_box(screen, titles[0], 'Welcome to ' + label.removeprefix('Install '))
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


def install_box_from_rows(rows, left, top):
    """Map one exact original-pixel destructive-action label to its capture."""
    if len(rows) != 1 or ' '.join(rows[0][0].split()) != 'Install':
        raise Unverified('final control label is absent, wrong or ambiguous')
    box = rows[0][1]
    if not (len(box) == 4 and all(type(value) is int for value in box)
            and 18 <= box[0] <= 28 and 61 <= box[2] <= 71
            and 9 <= box[1] <= 19 and 20 <= box[3] <= 30
            and 35 <= box[2]-box[0] <= 55 and 8 <= box[3]-box[1] <= 18):
        raise Unverified('final control text geometry is unverified')
    return (left + box[0], top + box[1], left + box[2], top + box[3])


def control_target(screen, label, enabled=False):
    """Resolve all local guards before recording or sending any input."""
    box = screen.box(label)
    if not (len(box) == 4 and all(type(value) is int for value in box)
            and 0 <= box[0] < box[2] <= screen.width
            and 0 <= box[1] < box[3] <= screen.height):
        raise Unverified('control box is outside the capture')
    if enabled and not screen.enabled(label):
        raise Unverified(f'control is disabled or its state is unknown: {label}')
    return box, [(box[0]+box[2])//2, (box[1]+box[3])//2]


def verify_restart_rows(rows):
    """Observe the measured done-page label; never click or infer a reboot."""
    if len(rows) != 1 or rows[0][0] != 'Restart now':
        raise Unverified('completion control label is absent or ambiguous')
    box = rows[0][1]
    bounds = ((30, 48), (20, 35), (280, 305), (50, 72))
    if (len(box) != 4 or any(type(value) is not int for value in box)
            or not all(low <= value <= high for value, (low, high) in zip(box, bounds))):
        raise Unverified('completion control geometry is unverified')
    return 'Restart now'

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
        self._summary_verified = False
        self._install_box_cache = None
        if self.state in ('unknown', 'done'):
            self.verify_completion_panel()
        if self.state == 'unknown':
            self.verify_progress_panel()

    def verify_completion_panel(self):
        """Same-frame installed title, media instruction and measured Restart label."""
        if self.state not in ('unknown', 'done'):
            return
        self.state = 'unknown'
        if (self.width, self.height) != (1280, 800):
            return
        exclusions = ('installation failed', 'save your recovery key', 'authentication',
                      'type to search', 'confirm installation', 'elapsed',
                      'do not power off', 'installation finished')
        if any(marker in normal(line) for marker in exclusions for line in self.lines):
            return
        if any(progress_title(line) for line in self.lines):
            return
        titles = [(text, box) for text, box in self.rows
                  if re.fullmatch(r'[A-Z][A-Za-z0-9 ._-]{0,63} is installed', text)]
        bare_instruction = 'Remove the installation media and restart the computer.'
        media = [(text, box) for text, box in self.rows
                 if 'remove the installation media' in normal(text)]
        restarts = [(text, box) for text, box in self.rows if 'restart now' in normal(text)]
        if len(titles) != 1 or len(media) != 1 or len(restarts) > 1:
            return
        instruction = media[0][0]
        # The observer bounds minutes to 999, as it does for progress clocks;
        # the frontend's divmod(elapsed, 60) itself has no minute ceiling.
        if not re.fullmatch(
                r'(?:Installed in (?!0:00\.)(?:0|[1-9][0-9]{0,2}):[0-5][0-9]\. )?'
                + re.escape(bare_instruction), instruction):
            return
        # Canonical Ubuntu 24 OCR measured timed widths 494–511 pixels.
        media_width = (370, 400) if instruction == bare_instruction else (490, 515)
        title, box = titles[0]
        mbox = media[0][1]
        if not (273 <= box[1] <= 281 and 22 <= box[3]-box[1] <= 32
                and abs((box[0]+box[2])/2-640) <= 4
                and 200 <= box[2]-box[0] <= 600
                and 310 <= mbox[1] <= 318 and 10 <= mbox[3]-mbox[1] <= 18
                and abs((mbox[0]+mbox[2])/2-640) <= 4
                and media_width[0] <= mbox[2]-mbox[0] <= media_width[1]):
            return
        # Anchor the text-only crop to the measured heading; reject unsupported
        # layout and dimmed/disabled/covered original pixels before OCR.
        cx, cy = self.width//2+72, box[1]+98
        background = [(220, 270), (1060, 270), (220, 410), (1060, 410),
                      (cx-77, cy), (cx+78, cy), (cx-72, cy-20), (cx+73, cy+20)]
        if any(any(abs(value-expected) > 4 for value, expected in zip(self.rgb(x, y), (250, 250, 251)))
               for x, y in background):
            return
        if any(any(abs(value-expected) > 4 for value, expected in zip(self.rgb(x, y), (145, 65, 172)))
               for x, y in ((cx-67, cy), (cx+68, cy))):
            return
        if restarts and (restarts[0][0] != 'Restart now' or not
                         (660 <= restarts[0][1][0] <= 680 and 365 <= restarts[0][1][1] <= 375
                          and 745 <= restarts[0][1][2] <= 765 and 375 <= restarts[0][1][3] <= 385)):
            return
        with tempfile.NamedTemporaryFile(suffix='.png') as prepared:
            subprocess.run(['convert', str(self.path), '-crop', f'110x30+{cx-55}+{cy-15}',
                            '+repage', '-resize', '300%', '-alpha', 'off',
                            '-colorspace', 'gray', '-negate', prepared.name],
                           capture_output=True, timeout=20, check=True)
            result = subprocess.run(['tesseract', prepared.name, 'stdout', '--psm', '7', 'tsv'],
                                    capture_output=True, text=True, timeout=30, check=True)
        try:
            _, rows = ocr_rows(result.stdout, strict=True)
            label = verify_restart_rows(rows)
        except Unverified:
            return
        self.completion_markers = [title, instruction, label]
        self.state = 'done'

    def verify_progress_panel(self):
        """One measured crop, not a fallback OCR sequence or completion proof."""
        if self.state != 'unknown' or (self.width, self.height) != (1280, 800):
            return
        exclusions = ('installation failed', 'is installed', 'restart now',
                      'remove the installation media', 'save your recovery key',
                      'authentication', 'type to search', 'confirm installation')
        if any(marker in normal(line) for marker in exclusions for line in self.lines):
            return
        titles = [(text, box) for text, box in self.rows if progress_title(text)]
        if len(titles) != 1:
            return
        heading, box = titles[0]
        if not (225 <= box[0] <= 240 and 670 <= box[1] <= 685
                and 300 <= box[2] <= 730 and 685 <= box[3] <= 705):
            return
        # A dimmed/background panel must not qualify through a foreground modal.
        if any(any(abs(value-expected) > 4 for value, expected in zip(self.rgb(x, y), (250, 250, 251)))
               for x, y in ((220, 670), (1060, 670), (220, 780), (1060, 780))):
            return
        with tempfile.NamedTemporaryFile(suffix='.png') as prepared:
            subprocess.run(['convert', str(self.path), '-crop', '840x110+225+665',
                            '+repage', '-resize', '300%', '-alpha', 'off',
                            '-colorspace', 'gray', prepared.name],
                           capture_output=True, timeout=20, check=True)
            result = subprocess.run(['tesseract', prepared.name, 'stdout', '--psm', '11', 'tsv'],
                                    capture_output=True, text=True, timeout=30, check=True)
        _, rows = ocr_rows(result.stdout)
        try:
            self.progress_markers = verify_progress_rows(rows, heading)
        except Unverified:
            return
        self.state = 'progress'

    def box(self, label):
        if label == 'Install':
            return self.install_box()
        boxes = [box for text, box in self.rows if normal(text) == normal(label)]
        if len(boxes) != 1:
            raise Unverified(f'expected one exact control label: {label}; got {len(boxes)}')
        return boxes[0]


    def summary_heading(self):
        """Require the published foreground page before any bounded card OCR."""
        if (self.width, self.height) != (1280, 800) or self.state != 'summary':
            raise Unverified('unsupported summary framebuffer or state')
        if any(normal(text) == 'install' for text, _ in self.rows):
            raise Unverified('unexpected additional full-frame Install control')
        heading = self.box('Confirm installation')
        summary = self.box('Summary')
        if not (20 <= heading[3]-heading[1] <= 40
                and abs((heading[0]+heading[2])/2-640) <= 4
                and 171 <= heading[1] <= 179
                and abs(summary[0]-352) <= 4
                and abs(summary[1]-heading[1]-141) <= 4
                and 10 <= summary[3]-summary[1] <= 18):
            raise Unverified('summary heading does not prove the measured foreground layout')
        anchors = [word for word in self.words if word['text'] == 'Encryption']
        if len(anchors) != 1:
            raise Unverified('summary label word is absent or ambiguous')
        anchor = anchors[0]
        x, y, w, h = (int(anchor[key]) for key in ('left', 'top', 'width', 'height'))
        if not (abs(x-395) <= 4 and abs(y-heading[1]-292) <= 4
                and 10 <= h <= 18 and 20 <= w <= 90):
            raise Unverified('summary label anchor is outside the measured card layout')
        return heading

    def summary_cards(self):
        """Read all destructive choices from the same published summary frame."""
        heading = self.summary_heading()
        cards = {}
        for label, offset in (('Target disk', 176), ('Filesystem', 231),
                              ('Encryption', 286), ('Image', 396)):
            crop = f'560x45+390+{heading[1]+offset}'
            with tempfile.NamedTemporaryFile(suffix='.png') as prepared:
                # Retain the measured summary pipeline, including antialiasing.
                # Raw full-frame OCR misreads /dev/vda and omits the image row.
                subprocess.run(['convert', str(self.path), '-crop', crop, '+repage',
                                '-resize', '300%', '-colorspace', 'gray', prepared.name],
                               capture_output=True, timeout=20, check=True)
                result = subprocess.run(['tesseract', prepared.name, 'stdout',
                                         '--psm', '6', 'tsv'],
                                        capture_output=True, text=True, timeout=30, check=True)
            _, cards[label] = ocr_rows(result.stdout, strict=True)
        return cards

    def summary_warning(self):
        heading = self.summary_heading()
        with tempfile.NamedTemporaryFile(suffix='.png') as prepared:
            subprocess.run(['convert', str(self.path), '-crop',
                            f'500x30+390+{heading[1]+65}', '+repage', prepared.name],
                           capture_output=True, timeout=20, check=True)
            result = subprocess.run(['tesseract', prepared.name, 'stdout',
                                     '--psm', '7', 'tsv'],
                                    capture_output=True, text=True, timeout=30, check=True)
        _, rows = ocr_rows(result.stdout, strict=True)
        return rows

    def install_box(self):
        """Read the exact destructive label only after full same-frame proof."""
        if not getattr(self, '_summary_verified', False):
            raise Unverified('final control needs the verified summary layout')
        heading = self.summary_heading()
        cx, cy = self.width//2, heading[1]+490
        left, top = cx-45, cy-20
        self._install_center = (cx, cy)
        if getattr(self, '_install_box_cache', None) is None:
            with tempfile.NamedTemporaryFile(suffix='.png') as prepared:
                subprocess.run(['convert', str(self.path), '-crop',
                                f'90x35+{left}+{top}', '+repage', prepared.name],
                               capture_output=True, timeout=20, check=True)
                result = subprocess.run(['tesseract', prepared.name, 'stdout',
                                         '--psm', '7', 'tsv'],
                                        capture_output=True, text=True, timeout=30, check=True)
            _, rows = ocr_rows(result.stdout, strict=True)
            self._install_box_cache = install_box_from_rows(rows, left, top)
        return self._install_box_cache

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
        if label == 'Install':
            # Published GTK destructive-action: disabled pills remain red-tinted.
            # Require its enabled fill AND dark-red glyphs in original pixels.
            cx, cy = self._install_center
            inside = ((cx-30, cy), (cx+30, cy), (cx, cy-14), (cx, cy+14))
            outside = ((cx-60, cy), (cx+60, cy), (cx, cy-26), (cx, cy+26))
            def matches(point, expected):
                return all(abs(actual-wanted) <= 4
                           for actual, wanted in zip(self.rgb(*point), expected))
            # Count glyph interiors, not font-rasterization-dependent points.
            # Real GTK sensitivity=false has zero such dark-red label pixels.
            dark_red = sum(170 <= r <= 210 and max(g, b) <= 35
                           for y in range(box[1], box[3])
                           for x in range(box[0], box[2])
                           for r, g, b in (self.rgb(x, y),))
            return (all(matches(point, (242, 213, 214)) for point in inside)
                    and all(matches(point, (250, 250, 251)) for point in outside)
                    and dark_red >= 80)
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


BUNDLE_DIGEST = 'sha256:ff28c254d0f0c3fc303cdcd2d7cae1632a55e6f92f1f887c4c6f00559d82417b'
IMAGE_REFERENCE = re.compile(r'[a-z0-9][a-z0-9./_-]*:[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}')


def image_ref_from_environment(environment):
    """Keep native provenance names separate from the media's tracking image."""
    kind = environment.get('TUNAOS_QUAL_EXECUTION_KIND')
    if kind == 'browser':
        key = 'TUNAOS_QUAL_SOURCE_REF'
    elif kind == 'native-qemu':
        key = 'TUNAOS_QUAL_INSTALLER_IMAGE_REF'
    else:
        raise Unverified('unsupported summary identity producer')
    value = environment.get(key)
    if not isinstance(value, str) or not IMAGE_REFERENCE.fullmatch(value):
        raise Unverified('missing or invalid bound installer image reference')
    return value


def verify_summary_cards(cards, mode, source_ref):
    """Exactly associate every destructive choice with the bound media source."""
    if (mode not in ('plain', 'luks')
            or set(cards) != {'Target disk', 'Filesystem', 'Encryption', 'Image'}
            or not isinstance(source_ref, str)
            or not IMAGE_REFERENCE.fullmatch(source_ref)):
        raise Unverified('invalid summary card contract')
    expected = {'Target disk': '/dev/vda (64 GiB)', 'Filesystem': 'XFS',
                'Encryption': 'No encryption' if mode == 'plain' else 'Passphrase',
                'Image': source_ref}
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


def verify_summary(screen, mode, source_ref):
    screen._summary_verified = False
    verify_summary_cards(screen.summary_cards(), mode, source_ref)
    warning = 'Everything on /dev/vda will be erased. This cannot be undone.'
    warnings = [' '.join(line.split()) for line in screen.lines
                if 'will be erased' in line.lower()]
    if (len(warnings) != 1
            or any(device != '/dev/vda' for device in re.findall(r'/dev/[A-Za-z0-9]+', warnings[0]))):
        raise Unverified('summary erase warning does not uniquely match the intended target')
    # The raw crop supplies exact device proof when full-frame thresholding
    # corrupts slash glyphs. Its original-pixel text must agree in full.
    rows = screen.summary_warning()
    if len(rows) != 1 or rows[0][0] != warning:
        raise Unverified('summary erase warning does not exactly match the intended target')
    box = rows[0][1]
    if not (len(box) == 4 and 0 <= box[0] <= 10 and 3 <= box[1] <= 13
            and 420 <= box[2] <= 446 and 17 <= box[3] <= 27
            and 10 <= box[3]-box[1] <= 20):
        raise Unverified('summary erase warning geometry is unverified')
    # Independent full-frame mode observation must agree with the card crop.
    expected = 'No encryption' if mode == 'plain' else 'Passphrase'
    screen.box(expected)
    if mode == 'luks' and any('tpm' in line.lower() or 'hardware backed' in normal(line)
                              for line in screen.lines):
        raise Unverified('summary selected hardware encryption instead of passphrase-only')
    screen._summary_verified = True


def drive(outdir, mode, vnc, capture, keys, type_text, installer_digest,
          password, source_ref, screen_factory=Screen, pointer=click_unix, sleep=time.sleep,
          clock=time.monotonic):
    """Bounded ordered GUI transaction. Submit once; then observe only.

    Disk/image pages are intentionally auto-skipped for a single valid choice
    by the pinned frontend. The final summary is the required target proof.
    """
    evidence = {'driver': 'gnome-23e47c51', 'installer_digest': installer_digest,
                'mode': mode, 'source_ref': source_ref, 'frames': [], 'transitions': [],
                'submitted': False, 'submit_attempted': False, 'accepted': False,
                'completed': False, 'clicks': []}
    deadline = clock() + 1200
    counter = 0
    private_frames = None
    entering_secret = False

    def observe(label):
        nonlocal counter
        if clock() >= deadline or counter >= 128:
            raise Unverified('GUI observation deadline/frame bound exceeded')
        if entering_secret:
            path = capture(counter, label, directory=private_frames.name)
        else:
            path = capture(counter, label)
        counter += 1
        if not path:
            raise Unverified('GUI capture unavailable')
        screen = screen_factory(path)
        # Password-entry captures are private scratch, never evidence frames or
        # OCR transcripts. Retain their files only until the summary is verified.
        evidence['frames'].append(
            {'state': screen.state, 'private': True} if entering_secret else
            {'file': Path(path).name, 'state': screen.state, 'text': screen.lines})
        if screen.state in ('no-disk', 'recovery', 'failed'):
            raise Unverified(f'invalid installer state: {screen.state}')
        if screen.state == 'overview':
            # Preserve both frames, but do not turn a launch-frontmost defect
            # into a qualified install by silently dismissing it.
            if not evidence['submitted'] and not entering_secret:
                keys('esc')
                after = capture(counter, 'overview-after-escape')
                counter += 1
                evidence['overview_after_escape'] = Path(after).name if after else None
            raise Unverified('installer launched behind positively identified shell overview')
        return screen

    def click(screen, label, enabled=False):
        box, point = control_target(screen, label, enabled)
        action = ('welcome-install' if screen.state == 'welcome' else {
            'Encrypt this disk': 'encrypt-disk',
            'Use hardware-backed encryption': 'hardware-encryption',
            'Password': 'password-field', 'Confirm Password': 'confirm-password-field',
            'Next': 'next', 'Install': 'submit-install',
        }.get(label))
        if action is None:
            raise Unverified('unsupported diagnostic control')
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
        if (not isinstance(source_ref, str)
                or not IMAGE_REFERENCE.fullmatch(source_ref)):
            raise Unverified('unsupported media source reference')
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
            private_frames = tempfile.TemporaryDirectory(prefix='tunaos-installer-entry-')
            entering_secret = True
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
        verify_summary(screen, mode, source_ref)
        click(screen, 'Install', enabled=True)
        evidence['submitted'] = True
        entering_secret = False
        if private_frames is not None:
            private_frames.cleanup()
            private_frames = None
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
        if private_frames is not None:
            private_frames.cleanup()
        Path(outdir, 'walkthrough-gnome.json').write_text(json.dumps(evidence, indent=2)+'\n')
        print('ok - strict GNOME installer completed' if evidence['completed'] else
              '# no completed installation proven', flush=True)
