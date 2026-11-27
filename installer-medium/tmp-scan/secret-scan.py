#!/usr/bin/python3
"""TEMPORARY: stop when a mounted medium partition holds a file with a
secret pattern that the allowlist does not name by sha256 and path.

usage: secret-scan.py MOUNTPOINT ALLOWLIST [RUN_SSH_PUBKEY_BASE64]
exit 1 on a file outside the list; the run's own SSH key is never allowed.

Patterns: a PEM private key (header and base64 body), GitHub tokens, the
Actions token variables and an AWS access key id. The scan reads the files,
not the raw image: a byte scan of the image gives no path (run 45753417496:
"aws key 35", "actions id token 4" with no file to check).
"""
import hashlib
import os
import re
import sys

PEM = re.compile(
    rb"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----\r?\n(?:[A-Za-z0-9-]+: [^\n]*\r?\n)*\r?\n?[A-Za-z0-9+/=]{40,}"
)
HARD = {
    "pem private key": (b"PRIVATE KEY-----", PEM),
    "ghp token": (b"ghp_", re.compile(rb"ghp_[A-Za-z0-9]{30}")),
    "ghs token": (b"ghs_", re.compile(rb"ghs_[A-Za-z0-9]{30}")),
    "github_pat": (b"github_pat_", re.compile(rb"github_pat_[A-Za-z0-9_]{20}")),
    "actions runtime token": (b"ACTIONS_RUNTIME_TOKEN", None),
    "actions id token": (b"ACTIONS_ID_TOKEN_REQUEST", None),
    "aws key id": (b"AKIA", re.compile(rb"AKIA[0-9A-Z]{16}")),
}
CHUNK, OVERLAP = 16 << 20, 8192
NORMAL = [
    (re.compile(r"^/ostree/deploy/[^/]+/deploy/[^/]+(/.*)$"), r"\1"),
    (re.compile(r"^/ostree/deploy/[^/]+/var(/.*)$"), r"/var\1"),
]
FLATPAK = re.compile(r"^/var/lib/flatpak/(?:runtime|app)/([^/]+)/[^/]+/[^/]+/[^/]+/files(/.*)$")
OBJECT = re.compile(r"^(/ostree/repo|/var/lib/flatpak/repo|/sysroot/ostree/repo)/objects/")


def normal(path):
    for rx, rep in NORMAL:
        if rx.match(path):
            path = rx.sub(rep, path)
    m = FLATPAK.match(path)
    if m:
        return f"flatpak:{m.group(1)}{m.group(2)}"
    if OBJECT.match(path):
        return "object"
    return path


def scan(full, hard):
    """sha256 of the file and the pattern names found in it."""
    digest, found, tail = hashlib.sha256(), set(), b""
    with open(full, "rb") as fh:
        while True:
            block = fh.read(CHUNK)
            if not block:
                break
            digest.update(block)
            data = tail + block
            for name, (needle, rx) in hard.items():
                if name not in found and needle in data and (rx is None or rx.search(data)):
                    found.add(name)
            tail = data[-OVERLAP:]
    return digest.hexdigest(), found


def main():
    root, allow_path = sys.argv[1], sys.argv[2]
    hard = dict(HARD)
    if len(sys.argv) > 3 and sys.argv[3]:
        hard["run ssh key"] = (sys.argv[3].encode(), None)
    allow = {}
    for line in open(allow_path):
        line = line.split("#", 1)[0].strip()
        if line:
            digest, path = line.split(None, 1)
            allow.setdefault(digest, set()).add(path)
    bad = files = 0
    dev = os.stat(root).st_dev
    for top, dirs, names in os.walk(root):
        dirs[:] = [d for d in dirs if os.lstat(os.path.join(top, d)).st_dev == dev]
        for name in names:
            full = os.path.join(top, name)
            if os.path.islink(full) or not os.path.isfile(full):
                continue
            try:
                digest, found = scan(full, hard)
            except OSError as err:
                print(f"BLOCKED unreadable {full}: {err}")
                bad += 1
                continue
            files += 1
            if not found:
                continue
            rel = "/" + os.path.relpath(full, root)
            norm = normal(rel)
            ok = "run ssh key" not in found and digest in allow and (norm in allow[digest] or norm == "object")
            print(f"{'ALLOWED' if ok else 'BLOCKED'} {digest} {norm} ({rel}) [{', '.join(sorted(found))}]")
            bad += not ok
    print(f"{files} files read under {root}, {bad} blocked")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
