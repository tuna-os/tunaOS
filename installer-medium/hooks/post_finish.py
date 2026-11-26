"""Text edits that finish an install from the medium (tunaOS#4907).

Pure functions plus one `apply` entry point over a mounted installed root and
its ESP. Ports the file-editing half of Utah's utah-sysinstall-post:

- new filesystem UUIDs replace the old ones in boot entries, crypttab, fstab;
- the live entry (any entry whose options carry `tunaos.live`) is removed,
  and the GRUB or systemd-boot default that named it is dropped;
- an entry that finds its root through gpt-auto (no `root=` karg) is left
  alone: nothing in it names a UUID, and adding `root=` would pin the disk.
  That gap is what failed dakota#1920.
"""

import json
import re
import sys
from pathlib import Path

LIVE_KARG = "tunaos.live"
UUID_RE = re.compile(r"^[0-9a-fA-F-]{8,36}$")


def options_of(entry_text):
    """The kernel arguments of a BLS or Type #1 entry."""
    for line in entry_text.splitlines():
        key, _, value = line.partition(" ")
        if key == "options":
            return value.split()
    return []


def is_live_entry(entry_text):
    return LIVE_KARG in options_of(entry_text)


def has_root_karg(entry_text):
    """False for a gpt-auto entry: no `root=` and no `mount.usr=`."""
    return any(a.startswith(("root=", "mount.usr=")) for a in options_of(entry_text))


def rewrite_uuids(text, mapping):
    """Replace each old UUID with its new one, case-insensitively."""
    for old, new in mapping.items():
        if not UUID_RE.match(old) or not UUID_RE.match(new):
            raise ValueError(f"not a UUID: {old!r} -> {new!r}")
        text = re.sub(re.escape(old), new, text, flags=re.IGNORECASE)
    return text


def luks_karg(entry_text, luks_uuid):
    """Add rd.luks.uuid to an entry that names its root, once.

    A gpt-auto entry is returned unchanged: systemd-gpt-auto-generator finds
    the LUKS partition by its type UUID.
    """
    if not luks_uuid or not has_root_karg(entry_text):
        return entry_text
    want = f"rd.luks.uuid={luks_uuid}"
    out = []
    for line in entry_text.splitlines():
        key, _, value = line.partition(" ")
        if key == "options":
            args = [a for a in value.split() if not a.startswith("rd.luks.uuid=")]
            line = " ".join(["options"] + args + [want])
        out.append(line)
    return "\n".join(out) + "\n"


def crypttab_line(luks_uuid, tpm2):
    """The installed system's crypttab entry for the LUKS2 root."""
    opts = "tpm2-device=auto" if tpm2 else "discard"
    return f"root UUID={luks_uuid} none {opts}\n"


def drop_grub_default(custom_cfg):
    """custom.cfg without the live default (`set default=...medium-live`)."""
    kept = [
        line
        for line in custom_cfg.splitlines()
        if not (line.strip().startswith("set default=") and "medium-live" in line)
    ]
    return "\n".join(kept) + "\n" if kept else ""


def drop_loader_default(loader_conf, live_ids):
    """loader.conf without a `default` that names a live entry."""
    out = []
    for line in loader_conf.splitlines():
        key, _, value = line.partition(" ")
        if key == "default" and any(value.strip().startswith(i) for i in live_ids):
            continue
        out.append(line)
    return "\n".join(out) + "\n" if out else ""


def drop_saved_entry(grubenv, live_ids):
    """A grubenv block without a saved_entry naming a live entry."""
    size = len(grubenv)
    lines = [
        line
        for line in grubenv.split("\n")
        if line
        and not line.startswith("#")
        and not (
            line.startswith("saved_entry=")
            and any(i in line.partition("=")[2] for i in live_ids)
        )
    ]
    body = "# GRUB Environment Block\n" + "".join(f"{line}\n" for line in lines)
    return body + "#" * max(size - len(body), 0)


def apply(root, esp, mapping, luks_uuid=None, tpm2=False, dry_run=False):
    """Edit the installed tree. Returns a report dict."""
    root, esp = Path(root), Path(esp)
    report = {"removed": [], "rewritten": [], "gpt_auto": [], "crypttab": None}

    def write(path, text):
        report["rewritten"].append(str(path))
        if not dry_run:
            path.write_text(text)

    entry_dirs = [root / "boot/loader/entries", esp / "loader/entries"]
    live_ids = []
    for d in entry_dirs:
        for f in sorted(d.glob("*.conf")) if d.is_dir() else []:
            text = f.read_text()
            if is_live_entry(text):
                live_ids.append(f.stem)
                report["removed"].append(str(f))
                if not dry_run:
                    f.unlink()
                continue
            if not has_root_karg(text):
                report["gpt_auto"].append(str(f))
            new = luks_karg(rewrite_uuids(text, mapping), luks_uuid)
            if new != text:
                write(f, new)

    for p in (root / "boot/grub2/custom.cfg",):
        if p.is_file():
            new = drop_grub_default(p.read_text())
            if new:
                write(p, new)
            elif not dry_run:
                p.unlink()
    for p in (root / "boot/grub2/grubenv", root / "boot/grub/grubenv"):
        if p.is_file():
            write(p, drop_saved_entry(p.read_text(), live_ids or ["medium-live"]))
    for p in (esp / "loader/loader.conf", root / "boot/loader/loader.conf"):
        if p.is_file():
            write(p, drop_loader_default(p.read_text(), live_ids or ["medium-live"]))

    for rel in ("etc/fstab", "etc/crypttab"):
        for p in sorted(root.glob(f"ostree/deploy/*/deploy/*/{rel}")) + [root / rel]:
            if p.is_file():
                text = p.read_text()
                new = rewrite_uuids(text, mapping)
                if new != text:
                    write(p, new)
    if luks_uuid:
        line = crypttab_line(luks_uuid, tpm2)
        report["crypttab"] = line
        ct = root / "etc/crypttab"
        if ct.parent.is_dir():
            write(ct, line)
    return report


def main(argv):
    if len(argv) < 4:
        raise SystemExit(
            "usage: post_finish.py ROOT ESP MAPPING.json [--luks UUID] [--tpm2] [--dry-run]"
        )
    root, esp, mapping = argv[1], argv[2], json.loads(Path(argv[3]).read_text())
    luks = argv[argv.index("--luks") + 1] if "--luks" in argv else None
    print(json.dumps(apply(root, esp, mapping, luks, "--tpm2" in argv, "--dry-run" in argv), indent=1))


if __name__ == "__main__":
    main(sys.argv)
