"""tunaOS#4047: installs relabelled under the broken aliases kept default_t homes.

tunaos-var-home-restorecon.service ran `restorecon -RF /var/home` once and
touched /var/lib/tunaos/var-home-relabeled, guarded by
ConditionPathExists=!that marker. On the EL GNOME images that one relabel ran
under selinux-policy 43.1's reversed `/var/home /home` alias, so it labelled
every home default_t and wrote the marker. Upgrading to an image with the
aliases fixed (PR #4107) never relabelled again: sshd still could not read
~/.ssh/authorized_keys and GNOME still got EACCES under ~/.local/share.

What this holds: the unit, run the way systemd runs it (its Condition* lines
against a fixture root, then its ExecStart lines in order), relabels /var/home
when there is no marker, relabels once when the marker predates the fix and the
homes are default_t, does nothing when the current marker is present and the
labels are right, relabels a default_t home even under the current marker,
refuses to relabel while the policy itself says default_t (the relabel that
caused #4047), keeps the marker when restorecon fails, and orders itself before
user logins. restorecon, matchpathcon and the label read are fakes that model
a policy and the on-disk labels; everything else is the shipped unit and
script.

Falsification: behavioural -- with the old unit,
`test_an_old_marker_with_default_t_homes_relabels_once` fails because the
unit is skipped on the old marker and the homes stay default_t, and
`test_a_broken_policy_is_never_applied` fails because the old unit relabels
everything to default_t without looking.
"""

from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SYSTEM_FILES = ROOT / "system_files"
UNIT = SYSTEM_FILES / "usr/lib/systemd/system/tunaos-var-home-restorecon.service"
MARKER = "/var/lib/tunaos/var-home-relabeled"

# The policy as matchpathcon reports it: FAKE_POLICY=fixed gives the types the
# corrected aliases give, FAKE_POLICY=broken is the 43.1 shape (default_t).
_MATCHPATHCON = r'''#!/usr/bin/env python3
import os, re, sys
args = [a for a in sys.argv[1:] if a != "-n"]
path = args[-1]
home = os.environ["TUNAOS_VAR_HOME"].rstrip("/")
rel = path[len(home) + 1:]
if os.environ.get("FAKE_POLICY") == "broken":
    t = "default_t"
elif path == home:
    t = "home_root_t"
elif not path.startswith(home + "/"):
    t = "default_t"
elif "/" not in rel:
    t = "user_home_dir_t"
elif re.match(r"[^/]+/\.ssh(/|$)", rel):
    t = "ssh_home_t"
elif re.match(r"[^/]+/\.local/share(/|$)", rel):
    t = "data_home_t"
else:
    t = "user_home_t"
print(f"unconfined_u:object_r:{t}:s0")
'''

# On-disk labels live in FAKE_LABELS (path<TAB>context), standing in for the
# security.selinux xattr. Only `stat -c %C` is faked.
_STAT = r'''#!/usr/bin/env python3
import os, sys
args = sys.argv[1:]
if args[:2] != ["-c", "%C"]:
    os.execvp("/usr/bin/stat", ["stat", *args])
path = args[-1]
labels = dict(l.split("\t", 1) for l in open(os.environ["FAKE_LABELS"]).read().splitlines() if l)
if path not in labels or not os.path.lexists(path):
    sys.exit(1)
print(labels[path])
'''

# restorecon: records its argv, then sets every label under its targets to what
# matchpathcon says, printing restorecon -v's `Relabeled` lines.
_RESTORECON = r'''#!/usr/bin/env python3
import os, subprocess, sys
with open(os.environ["FAKE_RESTORECON_LOG"], "a") as log:
    log.write(" ".join(sys.argv[1:]) + "\n")
if os.environ.get("FAKE_RESTORECON_FAIL"):
    sys.exit(255)
verbose = any(a.startswith("-") and "v" in a for a in sys.argv[1:])
targets = [a for a in sys.argv[1:] if not a.startswith("-")]
db = os.environ["FAKE_LABELS"]
labels = dict(l.split("\t", 1) for l in open(db).read().splitlines() if l)
for target in targets:
    for d, dirs, files in os.walk(target):
        for p in [d] + [os.path.join(d, f) for f in files]:
            want = subprocess.run(["matchpathcon", "-n", p], capture_output=True, text=True).stdout.strip()
            if labels.get(p) != want:
                if verbose:
                    print(f"Relabeled {p} from {labels.get(p)} to {want}")
                labels[p] = want
with open(db, "w") as f:
    f.write("".join(f"{k}\t{v}\n" for k, v in labels.items()))
'''


class Machine:
    """A fixture root with homes, on-disk labels and fake SELinux tools."""

    def __init__(self, tmp_path: Path, *, policy: str = "fixed") -> None:
        self.root = tmp_path / "root"
        self.bin = tmp_path / "bin"
        self.bin.mkdir()
        for name, body in (
            ("matchpathcon", _MATCHPATHCON),
            ("stat", _STAT),
            ("restorecon", _RESTORECON),
        ):
            (self.bin / name).write_text(body)
            (self.bin / name).chmod(0o755)
        self.labels_db = tmp_path / "labels.tsv"
        self.restorecon_log = tmp_path / "restorecon.log"
        self.restorecon_log.write_text("")
        self.home = self.root / "var/home"
        for p in (
            "alice/.ssh/authorized_keys",
            "alice/.local/share/gnome-shell/application_state",
            "alice/Documents/notes.txt",
            "bob/.bashrc",
        ):
            f = self.home / p
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text("x\n")
        self.env = {
            "PATH": f"{self.bin}:{os.environ['PATH']}",
            "TUNAOS_VAR_HOME": str(self.home),
            "TUNAOS_RELABEL_MARKER": str(self.root) + MARKER,
            "FAKE_POLICY": policy,
            "FAKE_LABELS": str(self.labels_db),
            "FAKE_RESTORECON_LOG": str(self.restorecon_log),
        }
        self.set_all("default_t")

    def paths(self) -> list[Path]:
        return [self.home, *sorted(self.home.rglob("*"))]

    def expected(self, p: Path) -> str:
        return subprocess.run(
            ["matchpathcon", "-n", str(p)],
            env={**self.env, "FAKE_POLICY": "fixed"},
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()

    def set_all(self, label_type: str | None) -> None:
        """Every path default_t (what the broken relabel wrote) or, with None, correct."""
        rows = []
        for p in self.paths():
            ctx = self.expected(p) if label_type is None else f"system_u:object_r:{label_type}:s0"
            rows.append(f"{p}\t{ctx}\n")
        self.labels_db.write_text("".join(rows))

    def set_label(self, p: Path, label_type: str) -> None:
        labels = self.labels()
        labels[str(p)] = f"system_u:object_r:{label_type}:s0"
        self.labels_db.write_text("".join(f"{k}\t{v}\n" for k, v in labels.items()))

    def labels(self) -> dict[str, str]:
        return dict(
            line.split("\t", 1) for line in self.labels_db.read_text().splitlines() if line
        )

    def default_t_paths(self) -> list[str]:
        return [p for p, ctx in self.labels().items() if ":default_t:" in ctx]

    def restorecon_calls(self) -> list[str]:
        return self.restorecon_log.read_text().splitlines()

    def marker(self) -> Path:
        return Path(str(self.root) + MARKER)

    def write_old_marker(self) -> None:
        # What the first version of the unit left: `touch`, no content.
        self.marker().parent.mkdir(parents=True, exist_ok=True)
        self.marker().write_text("")


def _unit() -> dict[str, list[tuple[str, str]]]:
    sections: dict[str, list[tuple[str, str]]] = {}
    current = ""
    for raw in UNIT.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", ";")):
            continue
        if line.startswith("["):
            current = line.strip("[]")
            sections.setdefault(current, [])
            continue
        key, _, value = line.partition("=")
        sections[current].append((key.strip(), value.strip()))
    return sections


def _values(section: list[tuple[str, str]], key: str) -> list[str]:
    return [w for k, v in section if k == key for w in v.split()]


def _host_path(m: Machine, arg: str) -> str:
    return str(m.root) + arg if arg.startswith("/var/") else arg


def _executable(path: str, m: Machine) -> str:
    shipped = SYSTEM_FILES / path.lstrip("/")
    if shipped.is_file():
        return str(shipped)
    fake = m.bin / Path(path).name
    if fake.exists():
        return str(fake)
    found = shutil.which(Path(path).name)
    assert found, f"ExecStart needs {path}, which neither the repo nor the host provides"
    return found


def start(m: Machine) -> tuple[str, str]:
    """Start the unit as systemd would on the fixture root.

    Returns (result, journal) where result is skipped, success or failed.
    ConditionSecurity=selinux holds: the fixture is an SELinux system.
    """
    unit = _unit()
    for key, value in unit["Unit"]:
        if not key.startswith("Condition"):
            continue
        negate = value.startswith("!")
        target = value.lstrip("!")
        if key == "ConditionSecurity":
            holds = target == "selinux"
        elif key == "ConditionPathExists":
            holds = os.path.lexists(_host_path(m, target))
        elif key == "ConditionPathIsDirectory":
            holds = os.path.isdir(_host_path(m, target))
        else:
            raise AssertionError(f"the simulator does not model {key}; extend it")
        if holds == negate:
            return "skipped", f"{key}={value} not met"
    for state in _values(unit["Service"], "StateDirectory"):
        (m.root / "var/lib" / state).mkdir(parents=True, exist_ok=True)
    journal = []
    for key, value in unit["Service"]:
        if key != "ExecStart":
            continue
        ignore = value.startswith("-")
        argv = shlex.split(value.lstrip("-@:+!"))
        argv = [_executable(argv[0], m), *(_host_path(m, a) for a in argv[1:])]
        r = subprocess.run(argv, env=m.env, capture_output=True, text=True)
        journal.append(r.stdout + r.stderr)
        if r.returncode != 0 and not ignore:
            return "failed", "".join(journal)
    return "success", "".join(journal)


def _generation(m: Machine) -> str | None:
    text = m.marker().read_text() if m.marker().exists() else None
    if text is None:
        return None
    found = re.search(r"^generation=(\S+)$", text, re.M)
    return found.group(1) if found else ""


def test_a_fresh_install_relabels_var_home_and_writes_the_marker(tmp_path: Path) -> None:
    m = Machine(tmp_path)
    result, journal = start(m)
    assert result == "success", journal
    assert m.default_t_paths() == []
    # Bounded: one recursive relabel, of /var/home and nothing else.
    assert m.restorecon_calls() == [f"-RF -v {m.home}"]
    assert _generation(m) not in (None, ""), journal
    assert "no marker" in journal
    assert re.search(r"relabelled \d+ file\(s\)", journal), journal


def test_an_old_marker_with_default_t_homes_relabels_once(tmp_path: Path) -> None:
    # The upgraded install from #4047: empty marker, every home default_t.
    m = Machine(tmp_path)
    m.write_old_marker()
    result, journal = start(m)
    assert result == "success", journal
    assert m.default_t_paths() == [], journal
    assert len(m.restorecon_calls()) == 1
    assert _generation(m), "the relabel must record the generation it was done for"
    assert "predates" in journal

    # The next boot finds the current marker and correct labels.
    result, journal = start(m)
    assert result == "success", journal
    assert len(m.restorecon_calls()) == 1, "relabelled again on the second boot"
    assert "nothing to do" in journal


def test_an_old_marker_relabels_even_where_the_probed_paths_look_right(tmp_path: Path) -> None:
    # The owner already ran the manual workaround on ~/.ssh and ~/.local/share,
    # but the rest of each home is still the default_t the broken relabel
    # wrote. The per-boot probe cannot see that; the marker generation must.
    m = Machine(tmp_path)
    m.write_old_marker()
    for p in m.paths():
        rel = p.relative_to(m.home).parts
        if len(rel) <= 1 or rel[1] in (".ssh", ".local"):
            m.set_label(p, m.expected(p).split(":")[2])
    notes = m.home / "alice/Documents/notes.txt"
    assert ":default_t:" in m.labels()[str(notes)]

    result, journal = start(m)
    assert result == "success", journal
    assert m.restorecon_calls() == [f"-RF -v {m.home}"]
    assert ":user_home_t:" in m.labels()[str(notes)]
    assert _generation(m)


def test_the_current_marker_with_correct_labels_is_a_no_op(tmp_path: Path) -> None:
    m = Machine(tmp_path)
    assert start(m)[0] == "success"  # writes the current marker
    marker_before = m.marker().read_text()
    labels_before = m.labels()
    m.restorecon_log.write_text("")

    result, journal = start(m)
    assert result == "success", journal
    assert m.restorecon_calls() == []
    assert m.marker().read_text() == marker_before
    assert m.labels() == labels_before
    assert "nothing to do" in journal


def test_a_default_t_home_is_relabelled_even_under_the_current_marker(tmp_path: Path) -> None:
    m = Machine(tmp_path)
    assert start(m)[0] == "success"
    m.restorecon_log.write_text("")
    keys = m.home / "alice/.ssh/authorized_keys"
    m.set_label(keys, "default_t")

    result, journal = start(m)
    assert result == "success", journal
    assert m.restorecon_calls() == [f"-RF -v {m.home}"]
    assert ":ssh_home_t:" in m.labels()[str(keys)]
    assert f"default_t on disk: {keys}" in journal


def test_wrong_labels_that_are_not_default_t_do_not_force_a_relabel(tmp_path: Path) -> None:
    # The per-boot check looks for the #4047 signature only; a type an admin
    # set deliberately (chcon) is not this service's business once the marker
    # is current.
    m = Machine(tmp_path)
    assert start(m)[0] == "success"
    m.restorecon_log.write_text("")
    m.set_label(m.home / "alice/Documents", "httpd_user_content_t")
    assert start(m)[0] == "success"
    assert m.restorecon_calls() == []


def test_a_broken_policy_is_never_applied(tmp_path: Path) -> None:
    # The policy still maps homes to default_t (the 43.1 shape): relabelling
    # now is exactly what caused #4047.
    m = Machine(tmp_path, policy="broken")
    m.set_all(None)
    result, journal = start(m)
    assert result == "failed", journal
    assert m.restorecon_calls() == []
    assert m.default_t_paths() == []
    assert not m.marker().exists()
    assert "refusing to relabel" in journal


def test_a_failed_relabel_does_not_write_the_marker(tmp_path: Path) -> None:
    m = Machine(tmp_path)
    m.write_old_marker()
    m.env["FAKE_RESTORECON_FAIL"] = "1"
    result, journal = start(m)
    assert result == "failed", journal
    assert m.marker().read_text() == "", "a failed relabel recorded success"
    assert "FAIL" in journal

    # The next boot, with restorecon working, finishes the job.
    del m.env["FAKE_RESTORECON_FAIL"]
    result, journal = start(m)
    assert result == "success", journal
    assert m.default_t_paths() == []
    assert _generation(m)


def test_no_var_home_is_skipped(tmp_path: Path) -> None:
    m = Machine(tmp_path)
    shutil.rmtree(m.home)
    result, _ = start(m)
    assert result == "skipped"
    assert m.restorecon_calls() == []


@pytest.mark.parametrize(
    "login",
    [
        # Clears /run/nologin: console and SSH logins wait for it.
        "systemd-user-sessions.service",
        "display-manager.service",
    ],
)
def test_the_relabel_finishes_before_logins(login: str) -> None:
    unit = _unit()
    assert login in _values(unit["Unit"], "Before")
    # Pulled into every boot that allows logins, not only graphical ones.
    assert "multi-user.target" in _values(unit["Install"], "WantedBy")
    # /var must be mounted first, and nothing it orders before may wait on a
    # default dependency that waits on it.
    assert "local-fs.target" in _values(unit["Unit"], "After")
    assert _values(unit["Unit"], "DefaultDependencies") == ["no"]
