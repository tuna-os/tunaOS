#!/usr/bin/env python3
"""The installer probe's inputs of one image, and the OCI label that carries them (tunaOS#4905).

Usage: installer-medium/evidence/probe_facts.py ROOTFS [--facts]

ROOTFS is the root directory of an image: a `podman image mount` path, or an
unpacked tree. The script reads the paths that
live-iso/common/src/installer-recipe-backend.sh reads, runs that probe on
them, and prints one line, `org.tunaos.installer.probe=<JSON>`, for
`--label`. With --facts it prints the facts as indented JSON. It exits 1 and
prints no label when the facts break a limit or the probe cannot classify the
image: an image with no label is correct, an image with a wrong label is not.

scan-images.py imports this module. It reads the label from the image config
and falls back to the layer scan. installer-medium/docs/probe-label.md has
the design.
"""

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PROBE = ROOT / "live-iso/common/src/installer-recipe-backend.sh"

LABEL = "org.tunaos.installer.probe"
# Raise this number when NAMES, TEXTS, KERNEL or OS_KEYS change: a label of
# another schema then falls back to the layer scan.
LABEL_SCHEMA = 1
MAX_LABEL = 16 << 10

NAMES = re.compile(
    r"usr/lib/bootupd/updates/EFI\.json"
    r"|usr/lib/bootupd/updates/EFI/[^/]+/grub[^/]*\.efi"
    r"|usr/lib/efi/grub2/(.*/)?grub[^/]*\.efi"
    r"|usr/lib/efi/shim/(.*/)?shim[^/]*\.efi"
    r"|usr/lib/systemd/boot/efi/(.*/)?systemd-boot[^/]*\.efi(\.signed)?"
)
# Directories that can hold a NAMES path.
NAME_ROOTS = ("usr/lib/bootupd/updates", "usr/lib/efi/grub2", "usr/lib/efi/shim", "usr/lib/systemd/boot/efi")
TEXTS = ("usr/lib/ostree/prepare-root.conf", "usr/lib/os-release", "etc/os-release")
KERNEL = re.compile(r"usr/lib/modules/([^/]+)(/.*)?")
OS_KEYS = ("ID", "ID_LIKE", "VERSION_ID", "VARIANT_ID")
MAX_TEXT = 65536

# Limits for facts that come from a label. The probe sources os-release in
# bash and build_tree() writes each file path, so a label is checked before
# either one sees it.
FACT_KEYS = ("files", "kernels", "prepare_root_conf", "os_release")
MAX_FILES = 64
MAX_KERNELS = 16
MAX_PATH = 256
MAX_CONF = 4096
# A grub2 directory carries the RPM epoch: `1:2.12-66.fc44`.
SEGMENT = re.compile(r"[A-Za-z0-9_+~][A-Za-z0-9._+~:-]*")
OS_LINE = re.compile(r"(ID|ID_LIKE|VERSION_ID|VARIANT_ID)=(\"[A-Za-z0-9._+ -]*\"|'[A-Za-z0-9._+ -]*'|[A-Za-z0-9._+-]*)")


def os_release(text):
    """The os-release lines the probe and the resolver read."""
    keep = []
    for line in text.splitlines():
        if line.partition("=")[0] in OS_KEYS:
            keep.append(line)
    return "\n".join(keep) + "\n"


def _real_dir(root, rel):
    """True when each part of rel below root is a directory and not a link.

    A linked directory can point out of the tree, at the build host. The
    layer scan sees no path below a link, so a linked directory is absent.
    """
    path = Path(root)
    for part in Path(rel).parts:
        path = path / part
        if path.is_symlink() or not path.is_dir():
            return False
    return True


def _text(root, rel):
    """The text of one TEXTS path, with one link level followed inside the tree."""
    path = root / rel
    if not _real_dir(root, os.path.dirname(rel)):
        return None
    if path.is_symlink():
        target = os.path.normpath(os.path.join(os.path.dirname(rel), os.readlink(path))).lstrip("/")
        # The layer scan follows a link only to another tracked text.
        if target not in TEXTS:
            return None
        path = root / target
        if path.is_symlink() or not _real_dir(root, os.path.dirname(target)):
            return None
    if not path.is_file():
        return None
    with open(path, "rb") as handle:
        return handle.read(MAX_TEXT).decode("utf-8", "replace")


def facts_from_rootfs(root):
    """The probe's inputs, read from an image root directory.

    The result equals what scan-images.py gets from the layers of the same
    image: the same paths, the same link rule, the same os-release keys.
    """
    root = Path(root)
    files = []
    for base in NAME_ROOTS:
        if not _real_dir(root, base):
            continue
        for parent, dirs, names in os.walk(root / base):
            linked = [d for d in dirs if os.path.islink(os.path.join(parent, d))]
            for name in names + linked:
                rel = os.path.relpath(os.path.join(parent, name), root)
                if NAMES.fullmatch(rel):
                    files.append(rel)
    kernels = []
    if _real_dir(root, "usr/lib/modules"):
        kernels = [e.name for e in os.scandir(root / "usr/lib/modules") if e.is_dir(follow_symlinks=False)]
    facts = {"files": sorted(set(files)), "kernels": sorted(kernels)}
    conf = _text(root, TEXTS[0])
    if conf is not None:
        facts["prepare_root_conf"] = conf
    release = _text(root, TEXTS[1])
    if release is None:
        release = _text(root, TEXTS[2])
    if release is not None:
        facts["os_release"] = os_release(release)
    return facts


def check_facts(facts):
    """None when the facts are safe to rebuild as a tree, else the reason."""
    if not isinstance(facts, dict) or set(facts) - set(FACT_KEYS):
        return f"facts: expected only the fields {list(FACT_KEYS)}"
    files, kernels = facts.get("files"), facts.get("kernels")
    if not isinstance(files, list) or len(files) > MAX_FILES:
        return f"facts.files: expected a list of at most {MAX_FILES} paths"
    for path in files:
        if (
            not isinstance(path, str)
            or len(path) > MAX_PATH
            or not NAMES.fullmatch(path)
            or not all(SEGMENT.fullmatch(part) for part in path.split("/"))
        ):
            return f"facts.files: {str(path)[:80]!r} is not a tracked path"
    if not isinstance(kernels, list) or len(kernels) > MAX_KERNELS:
        return f"facts.kernels: expected a list of at most {MAX_KERNELS} names"
    for kernel in kernels:
        if not isinstance(kernel, str) or len(kernel) > MAX_PATH or not SEGMENT.fullmatch(kernel):
            return f"facts.kernels: {str(kernel)[:80]!r} is not a kernel release"
    if files != sorted(set(files)) or kernels != sorted(set(kernels)):
        return "facts: files and kernels must be sorted and unique"
    conf = facts.get("prepare_root_conf", "")
    if not isinstance(conf, str) or len(conf) > MAX_CONF or "\x00" in conf:
        return f"facts.prepare_root_conf: expected at most {MAX_CONF} characters of text"
    release = facts.get("os_release", "")
    if not isinstance(release, str) or len(release) > MAX_CONF:
        return "facts.os_release: expected a short text"
    for line in release.splitlines():
        if not OS_LINE.fullmatch(line):
            return f"facts.os_release: {line[:80]!r} is not a plain {'/'.join(OS_KEYS)} line"
    if release and not release.endswith("\n"):
        return "facts.os_release: expected a final newline"
    return None


def build_tree(facts, root):
    """Rebuild the probe's view of an image from its recorded facts."""
    root = Path(root)
    for rel in facts.get("files", []):
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_bytes(b"")
    for kernel in facts.get("kernels", []):
        (root / "usr/lib/modules" / kernel).mkdir(parents=True, exist_ok=True)
    if "prepare_root_conf" in facts:
        (root / "usr/lib/ostree").mkdir(parents=True, exist_ok=True)
        (root / "usr/lib/ostree/prepare-root.conf").write_text(facts["prepare_root_conf"])
    if "os_release" in facts:
        (root / "usr/lib").mkdir(parents=True, exist_ok=True)
        (root / "usr/lib/os-release").write_text(facts["os_release"])
    return root


def run_probe(facts):
    """Run the real probe on the facts. Returns (result, error)."""
    with tempfile.TemporaryDirectory() as tmp:
        done = subprocess.run(
            ["bash", str(PROBE), str(build_tree(facts, tmp))],
            capture_output=True, text=True, check=False,
            env={**os.environ, "TUNAOS_INSTALLER_ALLOW_BTRFS": "1"},
        )
    if done.returncode != 0:
        return None, " ".join(done.stderr.split())[:200]
    return dict(line.split("=", 1) for line in done.stdout.splitlines()), None


def encode_label(facts):
    """The label value for the facts: compact JSON with the schema number."""
    reason = check_facts(facts)
    if reason:
        raise ValueError(reason)
    value = json.dumps({"schema": LABEL_SCHEMA, "facts": facts}, separators=(",", ":"), sort_keys=True)
    if len(value) > MAX_LABEL:
        raise ValueError(f"label is {len(value)} characters; the limit is {MAX_LABEL}")
    return value


def decode_label(value):
    """(facts, None) from a label value, or (None, reason) when it is not usable."""
    if not isinstance(value, str) or not value:
        return None, f"no {LABEL} label"
    if len(value) > MAX_LABEL:
        return None, f"label is {len(value)} characters; the limit is {MAX_LABEL}"
    try:
        document = json.loads(value)
    except ValueError:
        return None, "label is not JSON"
    if not isinstance(document, dict) or type(document.get("schema")) is not int:
        return None, "label has no schema number"
    if document["schema"] != LABEL_SCHEMA:
        return None, f"label schema {document['schema']} is not schema {LABEL_SCHEMA}"
    if set(document) != {"schema", "facts"}:
        return None, "label: expected the fields schema and facts"
    reason = check_facts(document["facts"])
    if reason:
        return None, reason
    # The key order of a layer scan record, so images.json has one shape.
    return {key: document["facts"][key] for key in FACT_KEYS if key in document["facts"]}, None


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    as_facts = "--facts" in args
    args = [a for a in args if a != "--facts"]
    if len(args) != 1 or args[0].startswith("-"):
        print(__doc__.split("\n\n")[1], file=sys.stderr)
        return 2
    if not os.path.isdir(os.path.join(args[0], "usr")):
        print(f"probe-facts: {args[0]} is not an image root: it has no usr directory", file=sys.stderr)
        return 1
    facts = facts_from_rootfs(args[0])
    try:
        value = encode_label(facts)
    except ValueError as error:
        print(f"probe-facts: no label: {error}", file=sys.stderr)
        return 1
    probe, error = run_probe(facts)
    if probe is None:
        print(f"probe-facts: no label: the probe cannot classify the image: {error}", file=sys.stderr)
        return 1
    print(f"probe-facts: {' '.join(f'{k}={v}' for k, v in probe.items())}", file=sys.stderr)
    print(json.dumps(facts, indent=1) if as_facts else f"{LABEL}={value}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
