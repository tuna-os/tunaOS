"""Fail-closed GUI driver for the installed system's first boot and GDM login.

Contract read from the shipped image (gnome-initial-setup-50.0, gdm-50.0,
vendor.conf skips only the software page): with no account on the installed
disk, GDM starts GNOME Initial Setup, whose About You and password pages
create the account; "Start Using <product>" opens that account's session.
The next boot must offer that account at the GDM greeter, and only a user
session draws the shell overview's "Type to search" entry.

Input is hardware key events and VNC pointer clicks. No guest execution.
"""
import json
from pathlib import Path
import re
import struct
import subprocess
import tempfile
import time

from lib.gnome_installer_driver import Unverified, accent_fill, click_unix, normal, ocr_rows

USER_PATTERN = r'[a-z][a-z0-9]{2,31}'
# Offline time-zone choice: an unambiguous libgweather result for "london".
TIMEZONE_CITY = 'London, East and South East England, United Kingdom'
# GIS rejects a password containing the user name; this one is test-only.
DEFAULT_PASSWORD = 'harbor-sunset-4817'


class Screen:
    """OCR rows of one PNG capture, classified into first-boot states."""

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
        # GIS draws dark text on light pages; GDM light on dark. The 2x pass
        # at 80% reads entry text exactly ("tunaose2e" is "tunaose2¢" at 1x)
        # and grey placeholders ("Confirm Password").
        for ops, scale in (('-threshold 60%', 1), ('-negate -threshold 60%', 1),
                           ('-threshold 80%', 2)):
            rows.extend((text, tuple(v // scale for v in box)) for text, box
                        in ocr_rows(self._ocr(ops.split(), 11, scale=scale))[1])
        # GIS's window is 1024px wide and centred; wallpaper beside it must not
        # join the action's run across the window's edge.
        rows.extend(self._slate_action(0, 120, x_span=(self.width // 2 - 512, self.width // 2 + 512)))
        if any(normal(line) == 'setup complete' for line, _ in rows):
            # "Start Using <product>" is the same slate fill, as a pill in the body.
            rows.extend(self._slate_action(120, self.height - 120, keep_unread=True,
                                           x_span=(self.width // 2 - 200, self.width // 2 + 200)))
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

    def _slate_action(self, band_top, band_height, keep_unread=False, x_span=None):
        """GIS's enabled actions (Next, Start Using) are white text on a solid
        fill that full-frame thresholds drop: slate srgb(111,131,150) on
        Skipjack and Bonito (run 41947529681), muted olive srgb(101,123,105) on
        Grouper (run 42318386139; its configured accent is orange, so the
        accent not reaching Initial Setup is a product finding, tunaOS#4408,
        which this finder deliberately does not police). Find a solid fill in
        one horizontal band and OCR only its inside."""
        raw = subprocess.run(['convert', str(self.path), '-crop',
                              f'{self.width}x{band_height}+0+{band_top}',
                              '+repage', '-depth', '8', 'rgb:-'],
                             capture_output=True, timeout=20, check=True).stdout
        if len(raw) != self.width * band_height * 3:
            raise Unverified('invalid pixel band buffer')
        def fill(x, y):
            offset = ((y - band_top) * self.width + x) * 3
            r, g, b = raw[offset:offset + 3]
            slate = abs(r - 111) <= 14 and abs(g - 131) <= 14 and abs(b - 150) <= 14
            # GIS draws its action in a muted, mid-dark fill on some products:
            # grouper's is srgb(101,123,105). Grey UI (white, near-black, light
            # grey: chroma < 18) never qualifies, and wallpaper blobs fail the
            # size bounds below.
            muted = max(r, g, b) - min(r, g, b) >= 18 and 60 <= (r + g + b) / 3 <= 190
            return slate or muted or accent_fill((r, g, b))

        # A button row has long contiguous fill runs; scattered wallpaper pixels
        # of the same hue never do. Label strokes split a row's run, so bridge
        # non-fill gaps up to 20px (one glyph plus spacing). A row keeps EVERY
        # run: wallpaper of the same hue can share a row with the pill and, as
        # the last run, would hide it (Bonito's water, run 42211241130), and
        # runs are linked vertically into rectangles.
        x_lo, x_hi = x_span or (0, self.width)
        rects = []   # [left, top, right, bottom, last_y]
        for y in range(band_top, band_top + band_height):
            row, start, last = [], None, None
            for x in range(x_lo, x_hi + 1):
                if x < x_hi and fill(x, y):
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
            if not (30 <= right - left <= 320 and 18 <= bottom - top <= 60):
                continue
            # Inset past the rounded ends (a pill's radius is half its
            # height): edge pixels lower OCR confidence.
            pad = max(6, (bottom - top) // 2)
            inset = (right - left - 2 * pad, bottom - top - 12, left + pad, top + 6)
            text = ' '.join(row[0] for row in ocr_rows(self._ocr(
                ['-threshold', '80%', '-negate'], 7, inset, 3))[1])
            if text.strip() or keep_unread:
                found.append((text, (left, top, right, bottom)))
        return found

    def box(self, label, below=0):
        """Exactly one box for label, ignoring anything above y=below (the
        GIS header repeats page titles such as "Password")."""
        def holds(outer, inner):
            cx, cy = (inner[0] + inner[2]) // 2, (inner[1] + inner[3]) // 2
            return outer[0] <= cx <= outer[2] and outer[1] <= cy <= outer[3]

        boxes = []
        for text, box in self.rows:
            if normal(text) != normal(label) or box[1] < below:
                continue
            # Several OCR passes see the same control, sometimes as the whole
            # row (GDM's avatar + name): one place, the tightest box.
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

    def has(self, label):
        return any(normal(text) == normal(label) for text in self.lines)

    def start_action(self):
        """The one slate pill in the Setup Complete body, whether or not OCR
        read its label: the product name comes from 'X is ready to be used.'."""
        product = sorted({m.group(1) for line in self.lines
                          if (m := re.fullmatch(r'(.{1,64}) is ready to be used\.?', line))})
        pills = sorted({box for _, box in self.rows
                        if box[1] >= 120 and 150 <= box[2] - box[0] <= 320 and 30 <= box[3] - box[1] <= 60})
        if len(product) != 1 or len(pills) != 1:
            raise Unverified(f'expected one product line and one action pill; got {len(product)}, {len(pills)}')
        return f'Start Using {product[0]}', pills[0]


def classify(lines):
    text = {normal(line) for line in lines}
    joined = '\n'.join(text)
    if any(line.startswith('start using ') for line in text):
        return 'setup-complete'
    # The slate pill's white label is not always read (bonito:gnome run
    # 42211241130 saw 'All done!' and 'Bonito is ready to be used.' only).
    if 'setup complete' in text and any(line.startswith('all done') for line in text):
        return 'setup-complete'
    if 'about you' in text or 'full name' in text:
        return 'account'
    if 'set a password' in joined or 'confirm password' in joined:
        return 'password'
    # Welcome lists languages; with no /etc/locale.conf "Unspecified" is
    # preselected and the Typing page then offers no layout (Next disabled).
    # OCR appends the dropdown arrow ("Unspecified v", bonito:gnome 42185431380).
    if 'english' in text and any(re.fullmatch(r'unspecified( \S)?', line) for line in text):
        return 'language'
    # Offline there is no location: Time Zone keeps Next disabled until a
    # city is chosen from its search.
    if 'time zone' in text and 'next' not in text:
        return 'timezone'
    if 'next' in text:
        return 'setup-page'
    # gnome-tour (Fedora-based products) opens over the first Overview and dims
    # it (bonito:gnome run 42233302612): a user presses Skip.
    if 'skip' in text and any(line.startswith('welcome to ') for line in text):
        return 'tour'
    # Optional GIS pages whose only header action is Skip (Ubuntu Pro on grouper,
    # run 42374980522): a user presses Skip. The Previous button proves it is a
    # GIS page, not the tour (which has no Previous).
    if 'skip' in text and 'previous' in text:
        return 'skip-page'
    if 'type to search' in joined:  # OCR reads the search icon as "Q"
        return 'session'
    if 'password' in text:
        return 'greeter-password'
    return 'unknown'


def drive(outdir, phase, vnc, capture, keys, type_text, user, password,
          screen_factory=Screen, pointer=click_unix, sleep=time.sleep, clock=time.monotonic):
    """phase=setup creates the account in GNOME Initial Setup; phase=login
    proves the greeter offers it and that its password opens a session."""
    evidence = {'driver': 'gnome-first-boot-gis50', 'phase': phase, 'user': user,
                'frames': [], 'clicks': [], 'pages': [], 'completed': False}
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

    def click(screen, label, below=0, box=None):
        box = box or screen.box(label, below)
        point = [(box[0] + box[2]) // 2, (box[1] + box[3]) // 2]
        evidence['clicks'].append({'label': label, 'state': screen.state,
                                   'box': list(box), 'point': point})
        if pointer(vnc, *point, screen.width, screen.height) is not True:
            raise Unverified('pointer transport did not acknowledge release')
        # A pointer left on a label or the slate Next fill hides it from OCR.
        pointer(vnc, screen.width - 2, screen.height - 2, screen.width, screen.height, click=False)
        sleep(2)

    def wait_for(states, label, polls=40):
        for _ in range(polls):
            screen = observe(label)
            if screen.state in states:
                return screen
            sleep(5)
        raise Unverified(f'no {"/".join(states)} frame within bound')

    def wait_for_timezone_commit(label='after-timezone-next', polls=18):
        # Committing the time zone can take many seconds with no network
        # (offline location lookup) while every re-observe still shows the
        # time zone page — and that page is itself a watched state, so the
        # plain wait below would return the mid-commit frame instantly and
        # the timezone branch would mistake patience for loss, then click
        # into the still-committing page. Poll until the page actually
        # leaves it (about 90s at 5s cadence). A hung page raises at once
        # instead of burning the polls (grouper:gnome run 42530591039).
        for _ in range(polls):
            screen = observe(label)
            if any('not responding' in normal(line) for line in screen.lines):
                raise Unverified('initial setup stopped responding during the time-zone commit')
            if screen.state != 'timezone':
                return screen
            sleep(5)
        return screen

    try:
        if phase not in ('setup', 'login'):
            raise Unverified('unsupported first-boot phase')
        if not re.fullmatch(USER_PATTERN, user) or not re.fullmatch('[a-z0-9_.-]{8,64}', password):
            raise Unverified('unsupported test account or password format')
        if phase == 'setup':
            pages = ('language', 'timezone', 'setup-page', 'skip-page', 'account', 'password', 'setup-complete')
            screen = wait_for(pages, 'await-setup')
            for _ in range(16):
                evidence['pages'].append(screen.state)
                if any('not responding' in normal(line) for line in screen.lines):
                    # A hung page answers nothing further: grouper:gnome run
                    # 42530591039 wedged Initial Setup on the time-zone page
                    # and the shell raised its "is not responding" dialog.
                    # Clicking into that only adds input to a dead app, so
                    # fail with the dialog as the evidence instead of the
                    # next control error.
                    raise Unverified('initial setup stopped responding')
                if screen.state == 'setup-complete':
                    product = next((line for line in screen.lines
                                    if normal(line).startswith('start using ')), None)
                    if product:
                        click(screen, product)
                    else:
                        label, pill = screen.start_action()
                        click(screen, label, box=pill)
                    screen = wait_for(('session', 'tour'), 'await-session')
                    if screen.state == 'tour':
                        click(screen, 'Skip')
                        evidence['tour_skipped'] = True
                        screen = wait_for(('session',), 'after-tour')
                    evidence['completed'] = True
                    return 0
                if screen.state == 'language':
                    # A user picks a language; English selects English (US) typing.
                    click(screen, 'English')
                    sleep(2)
                    screen = observe('verify-language')
                    if screen.state not in ('language', 'setup-page') or not screen.has('Next'):
                        raise Unverified('language page lost its Next action after selection')
                    evidence['language'] = 'English'
                elif screen.state == 'timezone':
                    if screen.has(TIMEZONE_CITY) and not screen.has('London, Kiribati'):
                        # The city is displayed as chosen but the advance was
                        # lost: grouper:gnome runs 42488951825 and 42518150255
                        # reached the selected page (city, map pin, Next) on
                        # plain and LUKS legs and the Next click did not
                        # advance. The displayed name is not a result row, and
                        # its box can resolve below the field onto the map:
                        # run 42530591039 clicked (598,516), hung Initial Setup
                        # with an offline map click, and the shell raised its
                        # "is not responding" dialog. So never click the field
                        # here: step back with Previous and come forward again
                        # onto a page the first-time path below already knows
                        # how to drive. Bound the redos so a guest that never
                        # advances still fails closed.
                        evidence['timezone_retries'] = evidence.get('timezone_retries', 0) + 1
                        if evidence['timezone_retries'] > 2:
                            raise Unverified('time zone city not accepted')
                        click(screen, 'Previous')
                        screen = wait_for(pages, 'after-lost-timezone')
                        continue
                    elif screen.has(TIMEZONE_CITY):
                        # Result rows are showing (the filter named the city but
                        # nothing is chosen yet): re-confirm the row, and bound
                        # the retries so a guest that never advances still
                        # fails closed.
                        evidence['timezone_retries'] = evidence.get('timezone_retries', 0) + 1
                        if evidence['timezone_retries'] > 2:
                            raise Unverified('time zone city not accepted')
                    else:
                        type_text('london')
                        sleep(3)
                        screen = observe('timezone-results')
                    click(screen, TIMEZONE_CITY)
                    sleep(2)
                    screen = observe('verify-timezone')
                    if screen.state != 'setup-page' or not screen.has(TIMEZONE_CITY):
                        raise Unverified('time zone city not accepted')
                    evidence['timezone_city'] = TIMEZONE_CITY
                elif screen.state == 'account':
                    # Full Name has focus; GIS derives the username from it.
                    keys('ctrl-a')
                    type_text(user)
                    sleep(2)
                    screen = observe('verify-account')
                    if screen.state != 'account' or not screen.has(user):
                        raise Unverified('typed account name not shown on About You')
                    evidence['account_name_observed'] = True
                elif screen.state == 'password':
                    secret = True
                    # A fresh page focuses Password, whose small floating
                    # label OCR misses (run 41976637118); once it holds text
                    # the label is readable and is clicked. Tab lands on a
                    # reveal icon, so Confirm is always clicked. ctrl-a makes
                    # a retry replace. Next enabled afterwards is the proof.
                    try:
                        click(screen, 'Password', below=100)
                    except Unverified:
                        pass
                    keys('ctrl-a')
                    type_text(password)
                    click(screen, 'Confirm Password')
                    keys('ctrl-a')
                    type_text(password)
                    sleep(2)
                    screen = observe('verify-password')
                    if screen.state != 'password':
                        raise Unverified('password input left the password page')
                    if not screen.has('Next'):
                        raise Unverified('Initial Setup did not accept the password (Next disabled)')
                elif screen.state == 'setup-page' and screen.has('Typing') and evidence.get('language'):
                    if not screen.has('English (US)'):
                        raise Unverified('Typing page does not offer English (US) after English')
                elif screen.state not in ('setup-page', 'skip-page'):
                    raise Unverified(f'unexpected first-boot state: {screen.state}')
                previous = screen.state
                from_selected_timezone = previous == 'setup-page' and screen.has(TIMEZONE_CITY)
                click(screen, 'Skip' if screen.state == 'skip-page' else 'Next')
                secret = False
                if from_selected_timezone:
                    screen = wait_for_timezone_commit()
                screen = wait_for(pages, 'after-' + previous, polls=12)
            raise Unverified('initial setup did not complete within page bound')
        screen = wait_for(('greeter-password', 'unknown'), 'await-greeter')
        if not screen.has(user):
            # GDM lists accounts before the password prompt opens.
            screen = wait_for(('unknown', 'greeter-password'), 'await-user-list', polls=12)
            if not screen.has(user):
                raise Unverified('GDM greeter does not offer the GUI-created account')
        evidence['greeter_offers_account'] = True
        if screen.state != 'greeter-password':
            click(screen, user)
        secret = True
        type_text(password)
        keys('ret')
        secret = False
        sleep(5)
        screen = wait_for(('session',), 'await-session')
        evidence['completed'] = True
        return 0
    except (Unverified, OSError, subprocess.SubprocessError, ValueError, StopIteration) as exc:
        evidence['error'] = str(exc)
        print(f'not ok - GNOME first-boot {phase}: {exc}', flush=True)
        return 1
    finally:
        private.cleanup()
        Path(outdir, f'first-boot-{phase}.json').write_text(json.dumps(evidence, indent=2) + '\n')
        print(f'ok - GNOME first-boot {phase} completed' if evidence['completed'] else
              f'# GNOME first-boot {phase} not proven', flush=True)
