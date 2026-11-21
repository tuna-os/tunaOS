#!/usr/bin/env python3
"""Branding assertions over the OCR text the first-boot drivers already keep.

Runtime branding contract, strict harness side: on the installed system's
Initial Setup frames (GNOME, Pantheon, COSMIC) and post-login frames, the
variant's product name (os-release PRETTY_NAME, `${IMAGE_NAME^}` in
build_scripts/90-image-info.sh) must be the product named wherever a screen
names one, and no upstream distro name may appear, except in the attribution
"built on <Base>" (docs/BRANDING.md: "A variant is TunaOS first. It also shows
the distro it is built on"). On GNOME Initial Setup the Next / "Start Using"
pills must also be filled with the variant accent (`accent`); drivers that do
not sample a pill's pixels record the accent as not-measured.

Drivers call attach() once, in the block that writes first-boot-<phase>.json;
it records a `branding_ocr` object there and never changes the driver's exit
status. scripts/iso-e2e.sh reads that object back (`verdict`) and applies
TUNAOS_STRICT_BRANDING=report|block. The product name and accent reach the
driver as TUNAOS_BRANDING_PRODUCT / TUNAOS_BRANDING_ACCENT (from tunaos.toml).

CLI:
    branding_ocr.py product VARIANT   -> prints the PRETTY_NAME, exit 1 if unknown
    branding_ocr.py accent VARIANT    -> prints the expected GIS pill #rrggbb
    branding_ocr.py verdict FILE      -> `result=<ok|fail|absent> findings=<..|->`
"""
from __future__ import annotations

import difflib
import json
import os
import re
import sys
from pathlib import Path

MODES = ('report', 'block')
# Contract denylist: case-insensitive whole-word match, multi-word names
# match across any run of whitespace (OCR joins and splits spaces freely).
DENYLIST = ('ubuntu', 'debian', 'fedora', 'centos', 'almalinux', 'alma linux', 'kitten',
            'rocky', 'rhel', 'red hat', 'redhat', 'opensuse', 'suse', 'gentoo',
            'arch linux', 'archlinux', 'elementary', 'bluefin', 'aurora', 'bazzite',
            'universal blue')
DENY_PATTERNS = tuple(
    (name, re.compile(r'(?<![a-z0-9])' + r'\s+'.join(map(re.escape, name.split())) + r'(?![a-z0-9])',
                      re.IGNORECASE))
    for name in DENYLIST)
# Words a "built on <Base>" attribution may carry after "built on": the
# denylisted names' own words plus the base-name suffixes 90-image-info.sh
# writes (BASE_OS_NAME "Enterprise Linux", "Fedora Hummingbird", "Fedora ELN")
# and release words. At most four are consumed, so "built on Fedora" cannot
# hide an unrelated upstream name later on the same line.
BASE_WORDS = frozenset(word for name in DENYLIST for word in name.split()) | frozenset((
    'linux', 'stream', 'enterprise', 'os', 'eln', 'hummingbird', 'leap', 'tumbleweed', 'sid',
    'lts', 'rawhide'))
ATTRIBUTION_WORDS = 4
# Desktop names are not product names: "Welcome to KDE Plasma" names the
# desktop, so a naming phrase starting with one is not a product mismatch.
DESKTOP_NAMES = frozenset(('gnome', 'kde', 'plasma', 'cosmic', 'xfce', 'pantheon', 'niri'))
# Phrases that name the product on screen. GNOME Initial Setup's Setup
# Complete page ("<NAME> is ready to be used.", "Start Using <NAME>",
# g_get_os_info(NAME)); gnome-tour and Ubuntu's welcome window ("Welcome to
# <NAME>"), both replayed in tests/test_gnome_first_boot.py.
NAMING_PATTERNS = (
    re.compile(r'(?P<name>.{1,64}?) is ready to be used\.?', re.IGNORECASE),
    re.compile(r'start using (?P<name>.{1,64}?)[!.]?', re.IGNORECASE),
    re.compile(r'welcome to (?P<name>.{1,64}?)[!.]?', re.IGNORECASE),
)
# A naming read agrees with the product when the product is one of its words,
# or its first word is within one OCR slip of the product (difflib ratio
# 0.8: "Yellowfn" against "Yellowfin" is 0.94, "Fedora" against "Yellowfin"
# is 0.27). The bound is a heuristic; no misread product line has been
# measured on a strict frame yet.
PRODUCT_RATIO = 0.8
# OCR reliability. A frame whose OCR produced fewer than three distinct words
# of four or more letters is blank, blanked ("Display output is not active"
# still has three, and names no distro) or noise; denylist hits on it are not
# asserted. A line that is nothing but a denylisted token of four letters or
# fewer ("rhel", "suse") is also ignored: tesseract turns icon glyphs and
# wallpaper texture into short all-letter tokens, and a real product string
# names the distro inside longer text. Both bounds are heuristics, not
# measured misreads.
RELIABLE_WORDS = 3
SHORT_TOKEN = 4
# Greeter and failure states are pre-login: they are not post-login frames
# even when they appear after the password was submitted (a retry).
GREETER_STATES = frozenset(('greeter', 'greeter-password', 'greeter-select', 'greeter-username',
                            'greeter-disabled', 'greeter-broken', 'login-failed', 'authenticating'))
FINDING_TOKEN_RE = re.compile(r'[^A-Za-z0-9._#-]+')
# GNOME Initial Setup's suggested-action pills (Next, "Start Using <NAME>")
# must be drawn in the variant accent (tunaOS#4408). libadwaita's named
# accents (tunaos.toml branding.gnome_accent; the same names
# 90-image-info.sh writes as TUNAOS_GNOME_ACCENT); Ubuntu bases draw GIS with
# Yaru, whose orange is #E95420. Yaru's other accents are not mapped: no
# Ubuntu-based GNOME variant uses one, so they fall back to libadwaita's.
GNOME_ACCENT_RGB = {'blue': '#3584e4', 'teal': '#2190a4', 'green': '#3a944a',
                    'yellow': '#c88800', 'orange': '#ed5b00', 'red': '#e62d42',
                    'pink': '#d56199', 'purple': '#9141ac', 'slate': '#6f8396'}
YARU_ACCENT_RGB = {'orange': '#e95420'}
# Within 30 per channel of the expected accent (antialiasing and VNC
# capture shift a flat fill by a few units; the nearest wrong accent, yellow
# against orange, differs by 37 in green and 99 in red).
ACCENT_TOLERANCE = 30
# The fills GIS drew before the fix (gnome_first_boot.Screen._slate_action):
# slate on Skipjack and Bonito (run 41947529681), sage on Grouper (run
# 42318386139). Seen within 14 per channel they are named in the record.
REJECTED_FILLS = {'slate': (111, 131, 150), 'sage': (101, 123, 105)}


def strict_mode(value):
    """TUNAOS_STRICT_BRANDING; unset means report, anything unknown is an error."""
    mode = value or 'report'
    if mode not in MODES:
        raise ValueError(f'TUNAOS_STRICT_BRANDING must be report or block, got {value!r}')
    return mode


def strip_attribution(line):
    """The line without its "built on <Base>" attribution."""
    tokens = line.split()
    kept = []
    index = 0
    while index < len(tokens):
        if (tokens[index].lower() == 'built' and index + 1 < len(tokens)
                and tokens[index + 1].lower().strip(',.:;') == 'on'):
            index += 2
            consumed = 0
            while index < len(tokens) and consumed < ATTRIBUTION_WORDS:
                word = tokens[index].lower().strip(',.:;()!')
                if word not in BASE_WORDS and not re.fullmatch(r'\d[\w.]*', word):
                    break
                index += 1
                consumed += 1
            continue
        kept.append(tokens[index])
        index += 1
    return ' '.join(kept)


def reliable(lines):
    words = {word.lower() for line in lines for word in re.findall(r'[A-Za-z]{4,}', line)}
    return len(words) >= RELIABLE_WORDS


def denylisted(lines):
    found = set()
    for line in lines:
        text = strip_attribution(line)
        bare = text.strip(' .,:;!?()[]|').lower()
        for name, pattern in DENY_PATTERNS:
            if not pattern.search(text):
                continue
            if bare == name and len(name) <= SHORT_TOKEN:
                continue
            found.add(name)
    return sorted(found)


def _word(product, text):
    return re.search(r'(?<![a-z0-9])' + re.escape(product) + r'(?![a-z0-9])', text,
                     re.IGNORECASE) is not None


def named_products(lines):
    names = []
    for line in lines:
        for pattern in NAMING_PATTERNS:
            match = pattern.fullmatch(line.strip())
            if match is None:
                continue
            name = match.group('name').strip()
            words = name.lower().split()
            if words and words[0] not in DESKTOP_NAMES:
                names.append(name)
            break
    return names


def agrees(name, product):
    if _word(product, name):
        return True
    first = name.split()[0].lower() if name.split() else ''
    return difflib.SequenceMatcher(None, first, product.lower()).ratio() >= PRODUCT_RATIO


def evaluate(lines, product):
    """Pure check of one frame's OCR lines; product may be None (unresolved)."""
    lines = [str(line) for line in lines]
    names = named_products(lines)
    trusted = reliable(lines)
    seen = None
    if product:
        seen = any(_word(product, line) for line in lines) or any(agrees(n, product) for n in names)
    return {
        'reliable': trusted,
        'product_seen': seen,
        'product_named': names,
        'denylisted': denylisted(lines) if trusted else [],
        'product_mismatch': bool(product and names and not any(agrees(n, product) for n in names)),
    }


def frame_kind(index, frame, setup_states, session_states, post_login_from):
    if frame.get('private') or 'text' not in frame:
        return None
    state = frame.get('state')
    if state in setup_states:
        return 'initial-setup'
    if state in session_states:
        return 'post-login'
    if post_login_from is not None and index >= post_login_from and state not in GREETER_STATES:
        return 'post-login'
    return None


def evaluate_frames(frames, product, setup_states=(), session_states=(), post_login_from=None):
    records, findings = [], []
    for index, frame in enumerate(frames):
        kind = frame_kind(index, frame, frozenset(setup_states), frozenset(session_states),
                          post_login_from)
        if kind is None:
            continue
        result = evaluate(frame.get('text', []), product)
        record = {'file': frame.get('file'), 'state': frame.get('state'), 'kind': kind}
        record.update({key: result[key] for key in
                       ('reliable', 'product_seen', 'product_named', 'denylisted')})
        records.append(record)
        if result['denylisted']:
            findings.append({'file': frame.get('file'), 'check': 'denylist',
                             'names': result['denylisted']})
        if result['product_mismatch']:
            findings.append({'file': frame.get('file'), 'check': 'product',
                             'names': result['product_named']})
    return {
        'product': product,
        'frames': records,
        'product_named_frames': sum(1 for record in records if record['product_named']),
        'findings': findings,
        'result': 'fail' if findings else 'ok',
    }


def hex_rgb(value):
    value = value.lstrip('#')
    return tuple(int(value[index:index + 2], 16) for index in (0, 2, 4))


def dominant_rgb(raw):
    """The fill of a pill crop (8-bit RGB bytes): the most common colour,
    bucketed to 16 levels per channel so antialiased label edges do not split
    it, averaged over that bucket's exact pixels. White label strokes cover
    less of a filled pill than its fill does; an unfilled (disabled) button
    yields the page colour, which then fails the accent check."""
    if not raw or len(raw) % 3:
        raise ValueError('pill crop is not RGB')
    buckets = {}
    for offset in range(0, len(raw), 3):
        pixel = raw[offset:offset + 3]
        buckets.setdefault((pixel[0] >> 4, pixel[1] >> 4, pixel[2] >> 4), []).append(pixel)
    pixels = max(buckets.values(), key=len)
    return tuple(round(sum(p[channel] for p in pixels) / len(pixels)) for channel in range(3))


def near(rgb, reference, tolerance):
    return all(abs(a - b) <= tolerance for a, b in zip(rgb, reference))


def evaluate_accent(samples, expected):
    """branding_ocr.accent from the pill fills a driver sampled. The "Start
    Using" pill is always enabled, so it decides when sampled; otherwise the
    per-channel median of the Next samples (a lone disabled Next cannot
    decide alone). No samples: not-measured, never a pass or a fail."""
    record = {'expected': expected, 'observed_rgb': None, 'ok': None, 'status': 'not-measured',
              'samples': samples}
    if not samples:
        return record
    start = [s['rgb'] for s in samples if str(s.get('label', '')).startswith('Start Using')]
    pool = start[-1:] or [s['rgb'] for s in samples]
    observed = [sorted(rgb[channel] for rgb in pool)[len(pool) // 2] for channel in range(3)]
    record.update(observed_rgb=observed, status='measured')
    rejected = next((name for name, rgb in REJECTED_FILLS.items() if near(observed, rgb, 14)), None)
    if rejected:
        record['rejected'] = rejected
    if expected:
        record['ok'] = near(observed, hex_rgb(expected), ACCENT_TOLERANCE) and not rejected
    elif rejected:
        record['ok'] = False
    return record


def attach(evidence, setup_states=(), session_states=(), environ=None):
    """Record evidence['branding_ocr'] from the frames already in evidence.
    Post-login frames are the session states plus every non-greeter frame
    after evidence['post_login_from_frame'] (set when the password was
    submitted). Never raises on frame content and never fails the driver."""
    environ = os.environ if environ is None else environ
    summary = evaluate_frames(evidence.get('frames', []),
                              environ.get('TUNAOS_BRANDING_PRODUCT') or None,
                              setup_states, session_states,
                              evidence.get('post_login_from_frame'))
    accent = evaluate_accent(evidence.get('accent_samples', []),
                             environ.get('TUNAOS_BRANDING_ACCENT') or None)
    summary['accent'] = accent
    if accent['ok'] is False:
        observed = '#{:02x}{:02x}{:02x}'.format(*accent['observed_rgb'])
        summary['findings'].append({'file': None, 'check': 'accent', 'names': [observed]})
        summary['result'] = 'fail'
    summary['mode'] = environ.get('TUNAOS_STRICT_BRANDING') or 'report'
    evidence['branding_ocr'] = summary
    print(f"# branding_ocr {verdict_line(summary)} product={summary['product'] or '-'} "
          f"frames={len(summary['frames'])}", flush=True)
    return summary


def accent_state(accent):
    """ok | fail | unchecked (sampled, no expected accent) | not-measured."""
    if not isinstance(accent, dict) or accent.get('status') != 'measured':
        return 'not-measured'
    return {True: 'ok', False: 'fail'}.get(accent.get('ok'), 'unchecked')


def verdict_line(summary):
    if not isinstance(summary, dict) or summary.get('result') not in ('ok', 'fail'):
        return 'result=absent findings=- accent=not-measured'
    names = []
    for finding in summary.get('findings', []):
        for name in finding.get('names', []):
            token = f"{finding.get('check')}:{FINDING_TOKEN_RE.sub('_', str(name))}"
            if token not in names:
                names.append(token)
    return (f"result={summary['result']} findings={','.join(names) or '-'} "
            f"accent={accent_state(summary.get('accent'))}")


def _config(root=None):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from lib import tunaos_config
    root = Path(root) if root else tunaos_config.ROOT
    return tunaos_config, tunaos_config.load(root / 'tunaos.toml')


def product_name(variant, root=None):
    module, config = _config(root)
    return module.display_names(config).get(variant)


def expected_accent(variant, root=None):
    """The #rrggbb GIS should draw its pills in for variant, or None."""
    _, config = _config(root)
    branding = config.get('variants', {}).get(variant, {}).get('branding')
    if not branding:
        return None
    name = branding['gnome_accent']
    if branding['base'].startswith('Ubuntu') and name in YARU_ACCENT_RGB:
        return YARU_ACCENT_RGB[name]
    return GNOME_ACCENT_RGB.get(name)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) == 2 and argv[0] in ('product', 'accent'):
        value = (product_name if argv[0] == 'product' else expected_accent)(argv[1])
        if not value:
            print(f'error: no {argv[0]} for variant {argv[1]!r} in tunaos.toml', file=sys.stderr)
            return 1
        print(value)
        return 0
    if len(argv) == 2 and argv[0] == 'verdict':
        try:
            evidence = json.loads(Path(argv[1]).read_text())
        except (OSError, ValueError):
            evidence = {}
        print(verdict_line(evidence.get('branding_ocr') if isinstance(evidence, dict) else None))
        return 0
    print('usage: branding_ocr.py product VARIANT | verdict FILE', file=sys.stderr)
    return 2


if __name__ == '__main__':
    sys.exit(main())
