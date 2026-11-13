"""Fail-closed GUI driver for the bundled COSMIC installer (org.tunaos.InstallerCosmic).

Contract read from tuna-os/bootc-installer frontends/cosmic: the wizard order
is Page::ORDER (main.rs:118) filtered by page_visible (main.rs:615), and every
heading and label is a constant in ui.rs `mod copy` or a branding key in
copy-defaults.json. On live media fisherman's probe sets live_image, so Image
(main.rs:620) and Network (main.rs:621) are skipped; Requirements shows only
while a hardware gate stands (main.rs:617) and Tour only with carousel slides
(main.rs:623). Companion has no condition and is always walked. The walk is:

    welcome, language, keyboard, timezone, disk, options, account,
    [tour], companion, confirm, progress, done

The account page is where the installed system's only user is created: on
COSMIC that is the GUI account path the receipt's gui_account_created stands
for, proven afterwards by the greeter login (scripts/lib/cosmic_first_boot.py).
An image that brings its own user skips the account page (main.rs:622); that
is an unexpected transition here and fails closed.

The frames are NOT yet measured on the strict harness: BUNDLE_DIGEST is None,
so every run is driven (its frames calibrate the contract) and fails closed.

Input is VNC pointer clicks and HMP key events. No guest execution.
"""
import difflib
import json
from pathlib import Path
import re
import struct
import subprocess
import tempfile
import time

from lib.gnome_installer_driver import Unverified, click_unix, normal, ocr_rows
from lib.kde_installer_driver import Screen as KdeScreen, device_text, disk_row

USER_PATTERN = r'[a-z][a-z0-9]{2,31}'
TARGET_DISK = '/dev/vda'
# encryption_<type>_label (copy-defaults.json:12, :14) for none / luks-passphrase.
ENCRYPTION = {'plain': 'No encryption', 'luks': 'Passphrase'}
# ui.rs:72 CONFIRM_LIVE_SUFFIX: the confirm Image row on live media is the
# booted image (or "this system") followed by this suffix (ui.rs:525).
LIVE_IMAGE_SUFFIX = ' (this system — no download)'
# Placeholders drawn inside an empty input (ui.rs:46, :48, :59, :63, :65).
# A settings item draws its control at the row's right edge, so the
# placeholder's OCR box is the one point known to be inside the input.
PASSPHRASE_HINT = 'Required to unlock at boot'
CONFIRM_HINT = 'Type it again'
USERNAME_HINT = 'Lowercase, for example alex'
PASSWORD_HINT = 'Required'
# The measured UI contract: the live overlay's InstallerCosmic receipt
# (org.tunaos.live-overlay.installer). Every page from welcome through the
# progress page was walked and verified on this bundle in both modes
# (grouper run 42877983500, walkthrough-{plain,luks} frames 00-19); the
# install itself then failed in fisherman's Installing OS step on that base
# (tunaOS#4485). A different bundle is unmeasured.
BUNDLE_DIGEST = 'sha256:735ea3881ba71bf42d24fdd495f6e31cc6e9c595e024e1f9565fa11fb9e4c22c'


def classify(lines):
    """Pages by their own headings (ui.rs `mod copy`, copy-defaults.json)."""
    text = {normal(line) for line in lines}
    joined = '\n'.join(text)
    if 'installation failed' in joined:  # done_failed_title
        return 'failed'
    if ('restart now' in text and any(line.endswith(' is installed') for line in text)
            and 'remove the installation media and restart the computer' in text):
        return 'done'
    if 'do not power off the computer' in joined:  # progress_note
        return 'progress'
    # The note is drawn in warning orange, which OCR can miss on the dark
    # theme (grouper run 42865163583): the "Installing <product>…" heading
    # over fisherman's own log also marks the progress page.
    if (any(re.fullmatch(r'installing \S+', line) for line in text)
            and any(line.startswith('fisherman ') for line in text)):
        return 'progress'
    if 'exit installer' in text:  # EXIT_TITLE
        return 'exit-dialog'
    # The window can open smaller than its request, so a page's lower rows
    # may sit below the fold: classify on what the top of each page shows.
    if 'confirm installation' in text and ({'summary', 'target disk'} & text):
        return 'confirm'
    # ui.rs:135-143. The subtitle wraps in a narrow window, so OCR passes
    # can interleave its halves: any of the page's own fixed lines will do.
    if 'use your phone' in text and ('open the link on your phone' in joined or 'pairing code' in text
                                     or 'on this computer' in text or 'copy link' in text
                                     or 'waiting for your phone' in joined
                                     or 'the phone form could not start' in joined):
        return 'companion'
    if 'create your account' in text and 'you will sign in with this account' in joined:
        return 'account'
    if 'sensible defaults are already chosen' in joined:
        return 'options'
    if 'select a disk' in text and 'everything on the disk you pick will be erased' in joined:
        return 'disk'
    if 'the installer needs the network to fetch images' in joined:
        return 'network'
    if 'search then pick where you are' in joined:
        return 'timezone'
    if 'the keyboard layout of the installed system' in joined:
        return 'keyboard'
    if 'the language of the installed system' in joined:
        return 'language'
    # Newer bundle copy (albacore-cosmic, iso-builder run 43430186507: "Step 4
    # of 14 - Language", subtitle "Changes this session and the installed
    # system."). The page heading says which one it is.
    if 'changes this session and the installed system' in joined:
        if 'language' in text:
            return 'language'
        if 'keyboard' in text or 'keyboard layout' in text:
            return 'keyboard'
        if 'timezone' in text or 'time zone' in text:
            return 'timezone'
    # The same bundle read through the CI framebuffer's OCR noise (marlin-cosmic,
    # iso-builder run 43438099209): the subtitle comes out as "this ce / on anc
    # the merallad system" on every pass, so the heading and the page's own
    # step badge ("Step 4 of 14 - Language") decide. Language lists locales,
    # Keyboard lists layout codes, Time zone has its search field.
    badge = next((m.group(1) for m in (re.fullmatch(r'step \d+ of(?: \d+)? (language|keyboard|time ?zone)', line)
                                       for line in text) if m), None)
    if badge in ('language', 'keyboard') or (badge or '').startswith('time'):
        return 'timezone' if badge.startswith('time') else badge
    if 'language' in text and 'utf' in joined and 'keyboard' not in text:
        return 'language'
    if 'keyboard' in text and len({'us', 'gb', 'fr', 'de', 'es', 'it', 'br'} & text) >= 2:
        return 'keyboard'
    if 'what to install onto the disk' in joined:
        return 'image'
    if 'this computer does not meet a requirement' in joined:
        return 'requirements'
    if 'welcome this assistant will guide you through installing' in joined:
        return 'welcome'
    if 'tour' in text and 'continue' in text:
        return 'tour'
    return 'unknown'


class Screen(KdeScreen):
    """OCR rows of one PNG capture, classified into COSMIC installer pages."""

    # COSMIC dark (main.rs:66 pins it for captures; the live session's
    # default is dark too): light text on dark fills, read negated. 25% keeps
    # labels on the accent (suggested) and red (destructive) buttons; 65%
    # keeps the dimmer placeholder text inside empty inputs; the plain pass
    # reads dark text an accent fill may carry; 2x reads device paths whose
    # slashes 1x garbles. Calibration is unmeasured on strict frames.
    PASSES = (('-negate -threshold 50%', 1), ('-negate -threshold 25%', 1),
              ('-negate -threshold 65%', 1), ('-threshold 50%', 1),
              ('-negate -threshold 50%', 2))

    def __init__(self, path):
        self.path = Path(path)
        with self.path.open('rb') as source:
            header = source.read(24)
        if header[:8] != b'\x89PNG\r\n\x1a\n':
            raise Unverified('capture is not PNG')
        self.width, self.height = struct.unpack('!II', header[16:24])
        # The strict harness's framebuffer is 1280x800.
        if not (640 <= self.width <= 1920 and 480 <= self.height <= 1200):
            raise Unverified('unsupported framebuffer dimensions')
        rows = []
        for ops, scale in self.PASSES:
            rows.extend((text, tuple(v // scale for v in box)) for text, box
                        in ocr_rows(self._ocr(ops.split(), 11, scale=scale))[1])
        rows.extend(self.accent_rows())
        self.rows = rows
        self.lines = [row[0] for row in rows]
        self.state = classify(self.lines)

    def accent_rows(self):
        """Labels drawn on solid accent fills, read crop by crop.

        COSMIC's suggested button is dark text on a light cyan fill (#76ADC2 on
        grouper, run 42772245038). Whole-frame thresholds lose it among the
        wallpaper, so find solid saturated fills of button size at quarter
        scale and OCR each interior on its own. A fill only yields a row; it
        is never a control unless its text is the exact label asked for."""
        step = 4
        w, h = self.width // step, self.height // step
        raw = subprocess.run(['convert', str(self.path), '-sample', f'{w}x{h}!', '-depth', '8', 'rgb:-'],
                             capture_output=True, timeout=120, check=True).stdout
        if len(raw) != w * h * 3:
            raise Unverified('accent scan read an unexpected frame size')
        mask = set()
        for i in range(w * h):
            r, g, b = raw[3 * i:3 * i + 3]
            if max(r, g, b) - min(r, g, b) >= 50 and max(r, g, b) >= 120:
                mask.add((i % w, i // w))
        rows = []
        while mask:
            seed = mask.pop()
            todo, component = [seed], [seed]
            while todo:
                x, y = todo.pop()
                for point in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                    if point in mask:
                        mask.remove(point)
                        todo.append(point)
                        component.append(point)
            left, right = min(p[0] for p in component), max(p[0] for p in component)
            top, bottom = min(p[1] for p in component), max(p[1] for p in component)
            bw, bh = (right - left + 1) * step, (bottom - top + 1) * step
            if not (48 <= bw <= 400 and 20 <= bh <= 72):
                continue
            if len(component) < .6 * (right - left + 1) * (bottom - top + 1):
                continue
            box = (left * step, top * step, (right + 1) * step, (bottom + 1) * step)
            for ops in (('-threshold', '50%'), ('-negate', '-threshold', '50%')):
                with tempfile.NamedTemporaryFile(suffix='.png') as crop:
                    subprocess.run(['convert', str(self.path), '-crop',
                                    f'{bw - 8}x{bh - 8}+{box[0] + 4}+{box[1] + 4}', '+repage',
                                    '-resize', '300%', '-colorspace', 'gray', *ops, crop.name],
                                   capture_output=True, timeout=20, check=True)
                    text = subprocess.run(['tesseract', crop.name, 'stdout', '--psm', '7'],
                                          capture_output=True, text=True, timeout=20).stdout.strip()
                if normal(text):
                    rows.append((text, box))
        return rows

    def matching(self, pattern):
        """Every distinct place a whole OCR line matches pattern (passes merged)."""
        def holds(outer, inner):
            cx, cy = (inner[0] + inner[2]) // 2, (inner[1] + inner[3]) // 2
            return outer[0] <= cx <= outer[2] and outer[1] <= cy <= outer[3]

        found = []
        for text, box in self.rows:
            if not re.fullmatch(pattern, ' '.join(text.split())):
                continue
            if not any(holds(seen, box) or holds(box, seen) for seen in found):
                found.append(box)
        for box in found:
            if not (0 <= box[0] < box[2] <= self.width and 0 <= box[1] < box[3] <= self.height):
                raise Unverified('control box is outside the capture')
        return sorted(found, key=lambda b: (b[1], b[0]))

    def line_reads(self, box, right=None, left=20):
        """Enlarged line reads of the row that box sits on, from the window's
        left edge to just past box. A maximized window draws a disk row's grey
        "path · size · bus" subtitle that whole-frame OCR reads only as its
        size ("64 GiB", grouper run 42803755249)."""
        upper = max(0, box[1] - 6)
        width = min(self.width - left, (right if right is not None else box[2] + 200) - left)
        height = min(self.height - upper, box[3] - box[1] + 12)
        reads = []
        if width <= 0 or height <= 0:
            return reads
        for ops in (['-negate'], ['-negate', '-threshold', '55%'], ['-negate', '-threshold', '35%']):
            with tempfile.NamedTemporaryFile(suffix='.png') as crop:
                subprocess.run(['convert', str(self.path), '-crop', f'{width}x{height}+{left}+{upper}',
                                '+repage', '-resize', '400%', '-colorspace', 'gray', *ops, crop.name],
                               capture_output=True, timeout=20, check=True)
                text = subprocess.run(['tesseract', crop.name, 'stdout', '--psm', '7'],
                                      capture_output=True, text=True, timeout=20).stdout
            text = ' '.join(text.split())
            if text:
                reads.append(text)
        return reads

    def value_beside(self, label, accept=None):
        """The value a settings item draws on the label's row, to its right.
        A maximized window puts the value far right, where whole-frame OCR can
        split it into fragments ("/dev/vda" read as 'id', 'la', grouper run
        42841652621): failing one acceptable value, read the strip right of
        the label enlarged and take the read accept() admits."""
        left = self.box(label)
        middle = (left[1] + left[3]) // 2
        values = {' '.join(text.split()) for text, box in self.rows
                  if box[0] > left[2] + 16 and box[1] <= middle <= box[3]
                  and normal(text) != normal(label)}
        if len(values) == 1 and (accept is None or accept(next(iter(values)))):
            return values.pop()
        reads = self.line_reads(left, left=left[2] + 16, right=self.width - 40)
        admitted = [read for read in reads if accept is None or accept(read)]
        if admitted and (accept is not None or len(set(admitted)) == 1):
            return admitted[0]
        raise Unverified(f'confirm row {label} has absent or ambiguous value: '
                         f'{sorted(values)} reads {reads!r}')


def names_warning(line, warning):
    """line is the erase warning, read alone or behind the warning icon, which
    OCR reads as a letter or two ("A Everything on /dev/vda will be erased.",
    grouper run 42854588117)."""
    text, wanted = device_text(line), warning.lower()
    if text.endswith(wanted) and len(text[:-len(wanted)].strip()) <= 2:
        return True
    # OCR sometimes drops the device path and garbles a letter (marlin-cosmic,
    # iso-builder run 43356213629: "A Everything on will be erased. This cannat
    # be undone."). The page's Target disk row is verified separately, so take
    # a close read of the warning with the device removed, provided the line
    # names no device of its own.
    if '/dev/' in text:
        return False
    stripped = re.sub(r' ?/dev/\S+', '', wanted)
    body = text[-len(stripped) - 3:] if len(text) > len(stripped) + 3 else text
    return len(text.strip()) >= len(stripped) - 3 and \
        difflib.SequenceMatcher(None, body.strip(), stripped).ratio() >= 0.9


_SIZE = re.compile(r'\d+(?:\.\d+)? ?[kmgt]i?b')


def hint_box(screen, hint):
    """The one empty input drawing hint. A maximized window narrows the
    inputs, so a long placeholder is drawn cut short ("Required to unlock at",
    grouper run 42818685545): failing an exact match, take the one place OCR
    read a prefix of hint at least ten characters long."""
    found = screen.boxes(hint)
    if len(found) == 1:
        return found[0]
    if found:
        raise Unverified(f'expected one exact control label: {hint}; got {len(found)}')
    want = normal(hint)
    cut = sorted((box for text, box in screen.rows
                  if len(normal(text)) >= 10 and want.startswith(normal(text))), key=lambda b: b[1])
    places = [b for i, b in enumerate(cut) if i == 0 or b[1] - cut[i - 1][1] > 10]
    if len(places) != 1:
        raise Unverified(f'expected one exact control label: {hint}; got {len(places)}')
    return places[0]


def target_row(screen):
    """The one disk row for TARGET_DISK. Whole-frame OCR first (kde's
    disk_row). When it finds none, read enlarged lines: first the line of any
    size cell OCR did see, then every strip of the list between the page
    heading and Back. A maximized window draws the "path · size · bus"
    subtitle small and grey, and CI's tesseract read none of it (grouper runs
    42803755249, 42812628057). One cluster or Unverified."""
    try:
        return disk_row(screen)
    except Unverified:
        pass

    def is_target(reads):
        return any(device_text(read).startswith(TARGET_DISK + ' ') for read in reads)

    hits = [box for text, box in screen.rows
            if _SIZE.search(normal(text)) and is_target(screen.line_reads(box))]
    if not hits:
        heads = [box for text, box in screen.rows if normal(text) == normal('Select a disk')]
        backs = [box for text, box in screen.rows if normal(text) == 'back']
        if heads and backs:
            top = max(b[3] for b in heads) + 20
            bottom = min(min(b[1] for b in backs) - 20, top + 300)
            for y in range(top, max(top, bottom - 24), 12):
                strip = (20, y, 680, y + 18)
                if is_target(screen.line_reads(strip, right=680)):
                    hits.append(strip)
    boxes = sorted(hits, key=lambda b: b[1])
    clusters = [b for i, b in enumerate(boxes) if i == 0 or b[1] - boxes[i - 1][1] > 30]
    if len(clusters) != 1:
        seen = sorted({' '.join(text.split()) for text, _ in screen.rows})[:40]
        raise Unverified(f'expected one disk row for {TARGET_DISK}; got {len(clusters)}; rows {seen!r}')
    return (20, clusters[0][1], clusters[0][2], clusters[0][3])


def product_from_welcome(screen):
    # ui.rs:26 WELCOME_BODY with {product} = branding::name().
    for line in screen.lines:
        match = re.fullmatch(r'Welcome\. This assistant will guide you through installing (\S+(?: \S+)*?) '
                             r'onto this computer\.?', ' '.join(line.split()))
        if match:
            return match.group(1)
    raise Unverified('welcome page does not name the product')


def drive(outdir, mode, vnc, capture, keys, type_text, installer_digest, password, user, user_password,
          screen_factory=Screen, pointer=click_unix, sleep=time.sleep, clock=time.monotonic):
    """Bounded ordered GUI transaction. Submit once; then observe only."""
    evidence = {'driver': 'cosmic-installer', 'installer_digest': installer_digest,
                'mode': mode, 'user': user, 'frames': [],
                'transitions': [], 'clicks': [], 'submitted': False, 'accepted': False,
                'account_created': False, 'completed': False}
    deadline = clock() + 2400
    counter = 0
    private = None

    def observe(label):
        nonlocal counter
        if clock() >= deadline or counter >= 256:
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
            diag_dump(screen)
            raise Unverified('installer reported failure')
        return screen

    def diag_dump(screen):
        # DIAGNOSTIC ONLY (branch diag/decosmic2-log, never merged): the failed page
        # drops the install log, so open the dock terminal and print the persisted
        # install log, memory, disk and kernel/journal evidence into screenshots.
        nonlocal counter
        names = {' ': 'spc', '/': 'slash', '|': 'shift-backslash', ';': 'semicolon',
                 '$': 'shift-4', '-': 'minus', '.': 'dot', ',': 'comma', '=': 'equal',
                 '_': 'shift-minus', '\n': 'ret', '>': 'shift-dot', '&': 'shift-7'}

        def typed(text):
            for ch in text:
                key = names.get(ch) or (ch if ch.islower() or ch.isdigit() else
                                        'shift-' + ch.lower() if ch.isalpha() else None)
                if key is None:
                    raise ValueError(repr(ch))
                keys(key)
        try:
            click_at(screen, 'diag terminal', (615, 744, 655, 784), (635, 764))
            sleep(6)
            steps = [
                ('log', 'clear;tail -n 32 .local/state/tuna-installer/install.log|cut -c1-120\n'),
                ('mem', 'clear;free -m;df -h /var/tmp /var/lib /run /|cut -c1-90\n'),
                ('dmesg', 'clear;sudo dmesg|grep -i -e oom -e kill -e error|tail -n 22|cut -c1-120\n'),
                ('journal', 'clear;sudo journalctl -b --no-pager|grep -i -e fisherman -e bootc -e skopeo -e podman -e enospc|tail -n 24|cut -c1-150\n'),
                ('log2', 'clear;ls -la .local/state/tuna-installer/;grep -n -i -e error -e fail -e killed -e space .local/state/tuna-installer/install.log|tail -n 20|cut -c1-140\n'),
            ]
            for label, command in steps:
                typed(command)
                sleep(8)
                path = capture(counter, 'diag-' + label)
                counter += 1
                evidence['frames'].append({'file': Path(path).name if path else None, 'state': 'diag-' + label})
        except Exception as exc:  # diagnostic must never mask the failure
            print('# diag dump failed: ' + repr(exc), flush=True)

    def click_at(screen, action, box, point):
        evidence['clicks'].append({'action': action, 'state': screen.state,
                                   'box': list(box), 'point': list(point)})
        # Hover first: a dropdown's popup item ignored a press that arrived
        # with the pointer's first motion over it (grouper run 42795766717).
        if pointer(vnc, *point, screen.width, screen.height, click=False) is not True:
            raise Unverified('pointer transport did not acknowledge the move')
        sleep(1)
        if pointer(vnc, *point, screen.width, screen.height) is not True:
            raise Unverified('pointer transport did not acknowledge release')
        # Park the pointer on the wallpaper at the screen's left edge: left
        # over a button it hides that button's label from the next read
        # ("Corjtinue", grouper run 42779226693, where Continue sits exactly
        # where Get started was).
        if pointer(vnc, 2, screen.height // 2, screen.width, screen.height, click=False) is not True:
            raise Unverified('pointer transport did not acknowledge the move')
        sleep(2)

    def scroll_down(screen, notches=8):
        """Wheel the page's scroll area to its end: on the 1280x800 strict
        framebuffer the window opens below its 1000x700 request, and the
        options page's Encryption section sits below the fold (grouper run
        42788383562). Scrolling past the end is harmless."""
        # Back is always enabled and sits under the scroll area's left edge
        # (Continue is disabled until a passphrase is typed).
        anchor = screen.box('Back')
        point = (min(screen.width - 1, anchor[0] + 300), max(0, anchor[1] - 150))
        evidence['clicks'].append({'action': 'scroll down', 'state': screen.state,
                                   'box': list(anchor), 'point': list(point)})
        for _ in range(notches):
            if pointer(vnc, *point, screen.width, screen.height, buttons=16) is not True:
                raise Unverified('pointer transport did not acknowledge the wheel')
        if pointer(vnc, 2, screen.height // 2, screen.width, screen.height, click=False) is not True:
            raise Unverified('pointer transport did not acknowledge the move')
        sleep(2)

    def follow_log(screen, notches=30):
        """Wheel the progress page's install log toward its end. The log
        never scrolls itself, and the failed page drops it ("the install log
        above has the details"): grouper run 42877983500 failed with only
        the log's first lines ever on screen (tunaOS#4485). Diagnosis only:
        the log is read-only text, and no other page is touched. The
        maximized page's log card spans x 33-1240, y 275-628 of the 1280x800
        framebuffer (grouper run 42877983500, walkthrough-plain frame 19), so
        the screen's centre is inside it."""
        if screen.state != 'progress':
            return
        point = (screen.width // 2, screen.height // 2)
        evidence['clicks'].append({'action': 'follow log', 'state': screen.state,
                                   'box': [0, 0, screen.width, screen.height], 'point': list(point)})
        for _ in range(notches):
            if pointer(vnc, *point, screen.width, screen.height, buttons=16) is not True:
                raise Unverified('pointer transport did not acknowledge the wheel')
        if pointer(vnc, 2, screen.height // 2, screen.width, screen.height, click=False) is not True:
            raise Unverified('pointer transport did not acknowledge the move')

    def click(screen, label, box=None):
        box = box or screen.box(label)
        click_at(screen, normal(label) or label, box,
                 ((box[0] + box[2]) // 2, (box[1] + box[3]) // 2))

    def fill(screen, hint, value, field):
        """Focus the empty input drawing hint, replace its text with value."""
        box = hint_box(screen, hint)
        click_at(screen, 'field ' + field, box, ((box[0] + box[2]) // 2, (box[1] + box[3]) // 2))
        keys('ctrl-a')
        type_text(value)
        sleep(1)

    def transition(previous, expected, polls=12):
        expected = (expected,) if isinstance(expected, str) else expected
        for _ in range(polls):
            screen = observe('await-' + '-or-'.join(expected))
            if screen.state in expected:
                evidence['transitions'].append(screen.state)
                return screen
            if screen.state not in (previous, 'unknown'):
                raise Unverified(f'unexpected ordered transition: {previous} -> {screen.state}')
            sleep(3)
        raise Unverified(f'GUI did not transition from {previous} to {"/".join(expected)}')

    def next_page(screen, expected, label='Continue'):
        click(screen, label)
        return transition(screen.state, expected)

    def settled(label, state):
        screen = observe(label)
        if screen.state != state:
            raise Unverified(f'{label}: left the {state} page ({screen.state})')
        return screen

    try:
        # An unmeasured bundle is still driven, so its frames can calibrate
        # the next contract, but it can never pass: the result fails closed.
        evidence['bundle_measured'] = BUNDLE_DIGEST is not None and installer_digest == BUNDLE_DIGEST
        if mode not in ENCRYPTION or not re.fullmatch('[a-z0-9_.-]{8,64}', password):
            raise Unverified('unsupported mode or test-only passphrase format')
        if not re.fullmatch(USER_PATTERN, user) or not re.fullmatch('[a-z0-9_.-]{8,64}', user_password):
            raise Unverified('unsupported test account or password format')
        screen = transition('unknown', 'welcome', polls=40)
        product = product_from_welcome(screen)
        evidence['product'] = product
        evidence['frontmost'] = True
        # Maximize (COSMIC's Super+M): on the 1280x800 framebuffer the window
        # opens below its 1000x700 request and pages scroll. Harmless if the
        # shortcut differs; the page must still be the welcome page.
        keys('meta_l-m')
        sleep(2)
        screen = settled('verify-maximized', 'welcome')
        # welcome_button (copy-defaults.json:7); live media skips Image.
        # Language, keyboard and timezone show only when the bundle offers
        # them: the grouper bundle goes straight from welcome to the disk
        # ("Step 2 of 7", grouper run 42779226693). Those that show keep
        # their order; the defaults stand and Continue never waits on them.
        preflight = ('language', 'keyboard', 'timezone', 'disk')
        screen = next_page(screen, preflight, label='Get started')
        while screen.state != 'disk':
            screen = next_page(screen, preflight[preflight.index(screen.state) + 1:])
        # Live media skips Network.
        # Each disk row is its title over "path · size · bus" (ui.rs:489); the
        # whole row selects it. Entering the page re-probes, so wait it out.
        # OCR reads the subtitle's slashes as i/l/| ("idevivda - 64 GiB"),
        # so match through device_text and take the one clustered row.
        row = None
        for _ in range(10):
            try:
                row = target_row(screen)
                break
            except Unverified:
                sleep(3)
                screen = settled('await-disk-rows', 'disk')
        if row is None:
            row = target_row(screen)
        click_at(screen, 'disk ' + TARGET_DISK, row,
                 ((row[0] + row[2]) // 2, (row[1] + row[3]) // 2))
        screen = next_page(settled('verify-disk', 'disk'), 'options')
        choice = ENCRYPTION[mode]
        scroll_down(screen)
        screen = settled('verify-options-scrolled', 'options')
        if mode == 'luks':
            # Disk encryption is a dropdown showing the current label
            # (default none, model.rs:92); its popup lists every choice.
            click(screen, ENCRYPTION['plain'])
            screen = settled('verify-encryption-menu', 'options')
            click(screen, choice)
            screen = settled('verify-encryption', 'options')
            scroll_down(screen)
            screen = settled('verify-encryption-scrolled', 'options')
            if len(screen.boxes(choice)) != 2 or not screen.has('Confirm passphrase'):
                raise Unverified('passphrase fields did not appear for the passphrase choice')
            private = tempfile.TemporaryDirectory(prefix='tunaos-cosmic-installer-')
            fill(screen, PASSPHRASE_HINT, password, 'passphrase')
            fill(screen, CONFIRM_HINT, password, 'confirm passphrase')
            screen = settled('verify-passphrase', 'options')
            if any('do not match' in normal(line) for line in screen.lines):
                raise Unverified('installer reports the passphrases differ')
        else:
            if not screen.has(choice):
                raise Unverified('options page does not show the no-encryption default')
            if screen.has('Confirm passphrase'):
                raise Unverified('plain mode shows passphrase fields')
        screen = next_page(screen, 'account')
        if private is not None:
            private.cleanup()
            private = None
        fill(screen, USERNAME_HINT, user, 'username')
        screen = settled('verify-username', 'account')
        if not (screen.has(user) or any(
                user in read.split()
                for read in screen.line_reads(screen.near_box('Username'), right=screen.width - 40))):
            raise Unverified('typed username is not shown on the account page')
        private = tempfile.TemporaryDirectory(prefix='tunaos-cosmic-installer-')
        fill(screen, PASSWORD_HINT, user_password, 'password')
        fill(screen, CONFIRM_HINT, user_password, 'confirm password')
        screen = settled('verify-password', 'account')
        if any('do not match' in normal(line) for line in screen.lines):
            raise Unverified('installer reports the passwords differ')
        # The tour and the phone companion page are both optional: a live
        # image with no tour and no companion form goes from the account
        # straight to the summary (grouper run 42827262301).
        after_account = ('tour', 'companion', 'confirm')
        screen = next_page(screen, after_account)
        private.cleanup()
        private = None
        if screen.state == 'confirm':
            # The summary draws no secret (ui.rs confirm()); observe it again
            # outside the private directory so its frame is kept as evidence.
            screen = settled('verify-confirm', 'confirm')
        for _ in range(12):  # the tour's Continue steps through its slides
            if screen.state != 'tour':
                break
            screen = next_page(screen, after_account)
        if screen.state == 'tour':
            raise Unverified('tour did not end within bound')
        if screen.state == 'companion':
            screen = next_page(screen, 'confirm')
        # Rows below the fold are read after one scroll; every row must be
        # read on some frame, and the erase warning on one of them.
        confirm_accepts = {
            'Target disk': lambda value: device_text(value) == TARGET_DISK,
            'Encryption': lambda value: normal(value) == normal(choice),
            'Username': lambda value: user in value.split(),
            'Image': lambda value: normal(value).endswith(normal(LIVE_IMAGE_SUFFIX)),
        }
        observed, seen_lines = {}, list(screen.lines)
        for attempt in range(2):
            for label in ('Target disk', 'Encryption', 'Username', 'Image'):
                if label not in observed and screen.has(label):
                    observed[label] = screen.value_beside(label, accept=confirm_accepts[label])
            if len(observed) == 4:
                break
            if attempt == 0:
                scroll_down(screen)
                screen = settled('verify-confirm-scrolled', 'confirm')
                seen_lines += screen.lines
        if len(observed) != 4:
            raise Unverified(f'confirm rows not all shown: {sorted(observed)}')
        evidence['confirm'] = dict(observed)
        observed['Target disk'] = device_text(observed['Target disk'])
        expected = {'Target disk': TARGET_DISK, 'Encryption': choice, 'Username': user}
        if ({label: observed[label] for label in expected} != expected
                or not normal(observed['Image']).endswith(normal(LIVE_IMAGE_SUFFIX))):
            raise Unverified(f'confirm page does not match the intended install: {observed}')
        warning = f'Everything on {TARGET_DISK} will be erased. This cannot be undone.'
        if not any(names_warning(line, warning) for line in seen_lines):
            raise Unverified('confirm erase warning does not name the intended target')
        click(screen, 'Install')
        evidence['submitted'] = True
        screen = transition('confirm', 'progress')
        if not any(normal(line).startswith('installing ' + normal(product)) for line in screen.lines):
            raise Unverified('progress page does not name the verified product')
        evidence['accepted'] = True
        evidence['account_created'] = True  # account page accepted, install submitted
        for _ in range(120):
            follow_log(screen)
            sleep(10)
            screen = observe('await-completion')
            if screen.state == 'done':
                if not screen.has(f'{product} is installed'):
                    raise Unverified('done page names a different product')
                evidence['transitions'].append('done')
                evidence['completed'] = True
                if not evidence['bundle_measured']:
                    if BUNDLE_DIGEST is None:
                        raise Unverified('unmeasured installer bundle: no UI contract digest is pinned '
                                         f'(observed {installer_digest or "none"})')
                    raise Unverified('unsupported installer bundle: measured UI contract digest differs '
                                     f'(observed {installer_digest or "none"})')
                return 0
            if screen.state not in ('progress', 'unknown'):
                raise Unverified(f'installation left progress unexpectedly: {screen.state}')
        raise Unverified('installer did not report completion within observation bound')
    except (Unverified, OSError, subprocess.SubprocessError, ValueError) as exc:
        evidence['error'] = str(exc)
        print('not ok - strict COSMIC GUI transaction: ' + str(exc), flush=True)
        return 1
    finally:
        if private is not None:
            private.cleanup()
        Path(outdir, 'walkthrough-cosmic.json').write_text(json.dumps(evidence, indent=2) + '\n')
        print('ok - strict COSMIC installer completed' if evidence['completed'] and evidence.get('bundle_measured') else
              '# no completed COSMIC installation proven', flush=True)
