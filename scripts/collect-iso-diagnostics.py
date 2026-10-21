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


if __name__ == '__main__':
    collect(sys.argv[1])
