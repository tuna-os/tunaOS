#!/usr/bin/env python3
"""Stage bounded, allowlisted ISO diagnostics without VM disks or media."""
import json
import fnmatch
import os
from pathlib import Path
import stat
import sys

MAX_FILE = 16 * 1024 * 1024
MAX_TOTAL = 128 * 1024 * 1024
MAX_FILES = 256
MAX_CANDIDATES = 1024
MAX_SKIPPED = 64
MAX_NAME = 240
DIRECTORIES = {'': ('serial.log', 'strict-*.log', 'current-phase.txt', 'boot-diagnostics.txt'),
               'walkthrough-plain': ('*.png', '*.json'),
               'walkthrough-luks': ('*.png', '*.json')}


SUMMARY_STATES = frozenset(('unknown', 'welcome', 'encryption', 'disk', 'summary',
                            'progress', 'done', 'overview', 'failed', 'no-disk', 'recovery'))
MAX_SUMMARY_BYTES = 1024 * 1024
MAX_SUMMARY_FRAMES = 128


SUMMARY_ACTIONS = frozenset(('welcome-install', 'encrypt-disk', 'hardware-encryption',
                             'password-field', 'confirm-password-field', 'next', 'submit-install'))


def safe_click(value):
    """Never copy free-form labels, OCR, errors, or typed data into job logs."""
    invalid = {'diagnostic': 'invalid'}
    if not isinstance(value, dict):
        return invalid
    action, state = value.get('action'), value.get('state')
    transport = value.get('transport')
    if (not isinstance(action, str) or action not in SUMMARY_ACTIONS
            or not isinstance(state, str) or state not in SUMMARY_STATES
            or transport not in ('uncertain', 'server-response')):
        return invalid
    frame, box, point = (value.get(key) for key in ('frame', 'box', 'point'))
    if any(not isinstance(values, list) or len(values) != size
           or any(type(item) is not int for item in values)
           for values, size in ((frame,2),(box,4),(point,2))):
        return invalid
    width, height = frame
    left, top, right, bottom = box
    if not (640 <= width <= 1920 and 480 <= height <= 1200
            and 0 <= left < right <= width and 0 <= top < bottom <= height
            and point == [(left+right)//2, (top+bottom)//2]):
        return invalid
    return dict(action=action, state=state, transport=transport,
                frame=frame, box=box, point=point)


def walkthrough_summary(root, mode):
    """Return allowlisted observations only, never OCR text or qualification."""
    if mode not in ('plain', 'luks'):
        return {'mode': 'invalid', 'diagnostic': 'unavailable'}
    result = {'mode': mode, 'diagnostic': 'unavailable'}
    path = Path(root) / ('walkthrough-' + mode) / 'walkthrough-gnome.json'
    try:
        with path.open('rb') as source:
            raw = source.read(MAX_SUMMARY_BYTES + 1)
        if len(raw) > MAX_SUMMARY_BYTES:
            return result
        value = json.loads(raw)
        if not isinstance(value, dict):
            return result
        frames, transitions = value.get('frames'), value.get('transitions')
        clicks = value.get('clicks', [])
        if (not isinstance(frames, list) or len(frames) > MAX_SUMMARY_FRAMES
                or not isinstance(transitions, list) or len(transitions) > MAX_SUMMARY_FRAMES
                or not isinstance(clicks, list) or len(clicks) > 32):
            return result
        def state(item):
            return item if isinstance(item, str) and item in SUMMARY_STATES else 'invalid'
        result.update(diagnostic='available',
                      states=[state(frame.get('state')) if isinstance(frame, dict)
                              else 'invalid' for frame in frames],
                      transitions=[state(item) for item in transitions],
                      clicks=[safe_click(item) for item in clicks])
        for key in ('frontmost', 'submit_attempted', 'submitted', 'accepted', 'completed'):
            item = value.get(key)
            result[key] = item if type(item) is bool else None
        return result
    except (OSError, ValueError, RecursionError):
        return result


def candidates(root, report):
    # Bound enumeration itself, even when a directory contains unrelated files.
    for directory, patterns in DIRECTORIES.items():
        parent = root / directory
        if not parent.is_dir() or parent.is_symlink():
            continue
        with os.scandir(parent) as entries:
            for entry in entries:
                if report['enumerated'] >= MAX_CANDIDATES:
                    report['enumeration_truncated'] = True
                    return
                report['enumerated'] += 1
                if any(fnmatch.fnmatchcase(entry.name, pattern) for pattern in patterns):
                    yield Path(entry.path)



def collect(root):
    root = Path(root)
    root.mkdir(exist_ok=True)
    if root.is_symlink():
        raise ValueError('diagnostic root must not be a symlink')
    dest = root / 'strict-diagnostics'
    if dest.exists() or dest.is_symlink():
        raise ValueError('diagnostic staging directory already exists')
    dest.mkdir()
    total = count = 0
    skipped = []
    report = dict(enumerated=0, enumeration_truncated=False, skipped_count=0,
                  skipped_report_truncated=False)
    for path in candidates(root, report):
        relative = path.relative_to(root)
        size = path.lstat().st_size
        if (len(str(relative)) > MAX_NAME
                or any(p.is_symlink() for p in (path, *path.parents) if p != root.parent)
                or not stat.S_ISREG(path.lstat().st_mode)
                or size > MAX_FILE or total + size > MAX_TOTAL or count >= MAX_FILES):
            report['skipped_count'] += 1
            if len(skipped) < MAX_SKIPPED:
                skipped.append(str(relative)[:MAX_NAME])
            else:
                report['skipped_report_truncated'] = True
            continue
        target = dest / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        # The producer job has finished writing these files before staging.
        with path.open('rb') as source, target.open('xb') as output:
            remaining = min(MAX_FILE, MAX_TOTAL - total)
            while chunk := source.read(min(1024 * 1024, remaining + 1)):
                if len(chunk) > remaining:
                    raise ValueError('diagnostic grew beyond byte budget')
                output.write(chunk)
                total += len(chunk)
                remaining -= len(chunk)
        count += 1
    (dest / 'collection.json').write_text(json.dumps(dict(files=count, bytes=total, skipped=skipped, **report), indent=2))

    # Read staged files only; this output does not change the strict verdict.
    for mode in ('plain', 'luks'):
        print('GNOME diagnostic: ' + json.dumps(walkthrough_summary(dest, mode), sort_keys=True))


if __name__ == '__main__':
    collect(sys.argv[1])
