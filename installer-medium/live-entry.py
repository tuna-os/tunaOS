"""Live boot entries for the installer medium (tunaOS#4907, #4913).

GRUB/ostree cells get a BLS variant of the deployment entry with `ro
tunaos.live` in place of `rw` (medium-live-root.service overlays the root),
porting Utah's medium.py. systemd-boot cells get a Type #1 variant with one
more initrd (the live-only cpio carrying setup-root-conf.toml), porting
Dakota's medium.py. Both writers are pure text transforms, tested in
tests/test_installer_medium_live_entry.py.
"""

import sys
from pathlib import Path

LIVE_KARG = "tunaos.live"
LIVE_TITLE = "TunaOS Live (try or install)"
VERSION_BUMP = 1000
GRUBENV_SIZE = 1024
GRUBENV_HEADER = "# GRUB Environment Block\n"
LIVE_SORT_KEY = "0-medium-live"


LIVE_LOCALE = "en_US.UTF-8"


def has_locale(deploy_root, locale=LIVE_LOCALE):
    """True when the deployed image ships `locale` (archive or directory)."""
    root = Path(deploy_root)
    name = locale.replace("UTF-8", "utf8")
    if (root / "usr/lib/locale" / name).is_dir():
        return True
    archive = root / "usr/lib/locale/locale-archive"
    if archive.is_file():
        data = archive.read_bytes()
        return locale.encode() in data or name.encode() in data
    return False


def locale_karg(deploy_root):
    """`locale.LANG=` for the live entry, or "" when the image lacks the locale.

    Without it the live session runs C.UTF-8: gnome-initial-setup selects the
    first keyboard layout (Dari) and COSMIC lists one language (#5010).
    """
    return f"locale.LANG={LIVE_LOCALE}" if has_locale(deploy_root) else ""


def live_entry(entry, extra_kargs=None):
    """The live variant of a BLS or Type #1 entry's text."""
    extra = list(extra_kargs or [])
    out = []
    saw_options = False
    for line in entry.splitlines():
        key, _, value = line.partition(" ")
        value = value.strip()
        if key == "title":
            line = f"title {LIVE_TITLE}"
        elif key == "version" and value.isdigit():
            line = f"version {int(value) + VERSION_BUMP}"
        elif key == "sort-key":
            line = f"sort-key {LIVE_SORT_KEY}"
        elif key == "options":
            saw_options = True
            args = [a for a in value.split() if a not in ("rw", "ro", LIVE_KARG)]
            line = " ".join(["options"] + args + ["ro", LIVE_KARG] + extra)
        elif key == "initrd" and extra_kargs is None:
            pass
        out.append(line)
    if not saw_options:
        raise ValueError("entry has no options line")
    return "\n".join(out) + "\n"


def with_live_initrd(entry_text, initrd_path):
    """Append a live-only initrd line to a Type #1 entry."""
    lines = entry_text.splitlines()
    options_at = next(i for i, line in enumerate(lines) if line.startswith("options"))
    lines.insert(options_at, f"initrd {initrd_path}")
    return "\n".join(lines) + "\n"


def grubenv(current, entry_id):
    """A GRUB environment block whose saved_entry is entry_id."""
    keep = [
        line
        for line in current.split("\n")
        if line and not line.startswith("#") and not line.startswith("saved_entry=")
    ]
    body = GRUBENV_HEADER + "".join(f"{line}\n" for line in keep + [f"saved_entry={entry_id}"])
    if len(body) > GRUBENV_SIZE:
        raise ValueError(f"grubenv content exceeds {GRUBENV_SIZE} bytes")
    return body + "#" * (GRUBENV_SIZE - len(body))


def loader_conf(current, entry_id, timeout="5"):
    """A systemd-boot loader.conf with the live entry default."""
    out = []
    for line in current.splitlines():
        key, _, _ = line.partition(" ")
        if key not in ("default", "timeout"):
            out.append(line)
    out += [f"default {entry_id}", f"timeout {timeout}"]
    return "\n".join(out) + "\n"


def entry_paths(entry_text):
    """(kernel, [initrds]) paths from a linux/initrd entry."""
    kernel, initrds = None, []
    for line in entry_text.splitlines():
        key, _, value = line.partition(" ")
        if key == "linux":
            kernel = value.strip()
        elif key == "initrd":
            initrds.append(value.strip())
    return kernel, initrds


def main(argv):
    command, path = argv[1], argv[2]
    if command == "locale-karg":
        print(locale_karg(path))
        return
    out_path = argv[3]
    text = Path(path).read_text()
    if command == "live-entry":
        result = live_entry(text, sys.argv[4:])
    elif command == "grubenv":
        result = grubenv(text, sys.argv[4])
    elif command == "loader-conf":
        result = loader_conf(text, sys.argv[4], sys.argv[5] if len(sys.argv) > 5 else "5")
    else:
        raise SystemExit(f"live-entry.py: unknown command {command}")
    Path(out_path).write_text(result)


if __name__ == "__main__":
    if len(sys.argv) < 4 and not (len(sys.argv) == 3 and sys.argv[1] == "locale-karg"):
        raise SystemExit(
            "usage: live-entry.py {live-entry|grubenv|loader-conf|locale-karg} IN OUT [ARGS...]"
        )
    main(sys.argv)
