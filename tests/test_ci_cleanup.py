"""`just ci-cleanup` removes what its own job created, and nothing else.

The failure these tests exist to prevent is a cleanup step that is too eager:
one that removes another job's container, a developer's image, or a directory
it never created. Every case drives scripts/ci-cleanup.py as a subprocess
against temporary state, with `podman`, `sudo` and `losetup` replaced by stubs
on PATH, so no real container storage or loop device is touched.
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ci-cleanup.py"
LABEL = "io.tunaos.ci.scope"

PODMAN_STUB = r'''#!/usr/bin/env python3
"""Podman stand-in: one JSON state file per storage ("user" or "root")."""
import json, os, sys

engine = os.environ.get("STUB_ENGINE", "user")
path = os.path.join(os.environ["STUB_DIR"], f"podman-{engine}.json")
state = json.load(open(path)) if os.path.exists(path) else {}
for key in ("container", "pod", "volume", "network", "image"):
    state.setdefault(key, {})
log = open(os.path.join(os.environ["STUB_DIR"], "calls.log"), "a")
log.write(engine + " " + " ".join(sys.argv[1:]) + "\n")
log.close()

def save():
    json.dump(state, open(path, "w"))

def labelled(kind, wanted):
    key, _, value = wanted.removeprefix("label=").partition("=")
    return [i for i, o in state[kind].items() if o.get("labels", {}).get(key) == value]

args = sys.argv[1:]
if args[:2] == ["ps", "-a"]:
    print("\n".join(labelled("container", args[3])))
elif args[:2] == ["pod", "ps"]:
    print("\n".join(labelled("pod", args[3])))
elif args[:2] == ["volume", "ls"]:
    print("\n".join(labelled("volume", args[3])))
elif args[:2] == ["network", "ls"]:
    print("\n".join(labelled("network", args[3])))
elif args[:1] == ["rm"]:
    state["container"].pop(args[-1], None); save()
elif args[:2] == ["pod", "rm"]:
    state["pod"].pop(args[-1], None); save()
elif args[:2] == ["volume", "rm"]:
    state["volume"].pop(args[-1], None); save()
elif args[:2] == ["network", "rm"]:
    state["network"].pop(args[-1], None); save()
elif args[:2] == ["image", "inspect"]:
    name = args[-1]
    if name not in state["image"]:
        sys.exit(125)
    print(state["image"][name])
elif args[:1] == ["rmi"]:
    state["image"].pop(args[1], None); save()
else:
    sys.exit(2)
'''

SUDO_STUB = r'''#!/bin/sh
# Non-interactive sudo that just runs the command; "root" podman storage.
[ "$1" = "-n" ] && shift
case "$1" in
  true) exit 0 ;;
  podman) STUB_ENGINE=root exec "$@" ;;
  *) exec "$@" ;;
esac
'''

LOSETUP_STUB = r'''#!/usr/bin/env python3
import json, os, sys
path = os.path.join(os.environ["STUB_DIR"], "loops.json")
loops = json.load(open(path)) if os.path.exists(path) else {}
args = sys.argv[1:]
if "-j" in args:
    backing = args[args.index("-j") + 1]
    print("\n".join(dev for dev, back in loops.items() if back == backing))
elif args[:1] == ["-d"]:
    loops.pop(args[1], None)
    json.dump(loops, open(path, "w"))
else:
    sys.exit(2)
'''


class Env:
    def __init__(self, tmp_path: Path):
        self.tmp = tmp_path
        self.stub = tmp_path / "stub"
        self.stub.mkdir()
        self.state_root = tmp_path / "state"
        self.runner_temp = tmp_path / "runner-temp"
        self.runner_temp.mkdir()
        self.workspace = tmp_path / "workspace"
        self.workspace.mkdir()
        for name, body in (("podman", PODMAN_STUB), ("sudo", SUDO_STUB), ("losetup", LOSETUP_STUB)):
            (self.stub / name).write_text(body)
            (self.stub / name).chmod(0o755)

    def env(self, job="build", attempt="1", suffix="", run_id="4242", **extra) -> dict[str, str]:
        env = {
            "PATH": f"{self.stub}:/usr/bin:/bin",
            "HOME": str(self.tmp),
            "STUB_DIR": str(self.stub),
            "RUNNER_TEMP": str(self.runner_temp),
            "GITHUB_WORKSPACE": str(self.workspace),
            "CI_STATE_ROOT": str(self.state_root),
            "GITHUB_RUN_ID": run_id,
            "GITHUB_RUN_ATTEMPT": attempt,
            "GITHUB_JOB": job,
        }
        if suffix:
            env["CI_SCOPE_SUFFIX"] = suffix
        env.update(extra)
        return env

    def run(self, *args: str, **kwargs) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, str(SCRIPT), *args], env=self.env(**kwargs), capture_output=True, text=True)

    def podman_state(self, engine="user") -> dict:
        path = self.stub / f"podman-{engine}.json"
        state = json.loads(path.read_text()) if path.exists() else {}
        for key in ("container", "pod", "volume", "network", "image"):
            state.setdefault(key, {})
        return state

    def seed_podman(self, engine="user", **kinds) -> None:
        state = self.podman_state(engine)
        for kind, objects in kinds.items():
            state[kind].update(objects)
        (self.stub / f"podman-{engine}.json").write_text(json.dumps(state))

    def mutating_calls(self) -> list[str]:
        log = self.stub / "calls.log"
        if not log.exists():
            return []
        return [line for line in log.read_text().splitlines() if " rm " in f" {line} " or " rmi " in f" {line} "]


@pytest.fixture
def ci(tmp_path):
    return Env(tmp_path)


def scope_of(ci: Env, **kwargs) -> str:
    result = ci.run("scope", **kwargs)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


# -- scope -------------------------------------------------------------------


def test_scope_separates_runs_attempts_jobs_and_matrix_cells(ci):
    scopes = {
        scope_of(ci),
        scope_of(ci, run_id="4243"),
        scope_of(ci, attempt="2"),
        scope_of(ci, job="test"),
        scope_of(ci, suffix="yellowfin-gnome"),
    }
    assert len(scopes) == 5


def test_outside_ci_nothing_is_owned_and_nothing_is_touched(ci):
    ci.seed_podman(container={"c1": {"labels": {LABEL: "anything"}}}, image={"localhost/x:y": "sha256:1"})
    env = ci.env()
    for name in ("GITHUB_RUN_ID", "CI_SCOPE"):
        env.pop(name, None)
    result = subprocess.run([sys.executable, str(SCRIPT), "run"], env=env, capture_output=True, text=True)
    assert result.returncode == 0 and "nothing is owned" in result.stdout
    assert "c1" in ci.podman_state()["container"] and "localhost/x:y" in ci.podman_state()["image"]
    assert not (ci.state_root).exists()
    assert subprocess.run([sys.executable, str(SCRIPT), "scope"], env=env).returncode == 1
    assert subprocess.run([sys.executable, str(SCRIPT), "labels"], env=env, capture_output=True, text=True).stdout == ""


def test_label_args_carry_the_scope(ci):
    scope = scope_of(ci)
    assert ci.run("labels").stdout.split("\n")[:2] == ["--label", f"{LABEL}={scope}"]


# -- idempotence -------------------------------------------------------------


def test_cleanup_with_nothing_to_clean_succeeds_repeatedly(ci):
    for _ in range(3):
        assert ci.run("run").returncode == 0


def test_cleanup_twice_after_real_work_is_still_clean(ci):
    scratch = Path(ci.run("scratch").stdout.strip())
    (scratch / "big.bin").write_text("x")
    assert ci.run("run").returncode == 0
    assert not scratch.exists()
    assert ci.run("run").returncode == 0


# -- containers / pods / volumes: label ownership ----------------------------


def test_only_objects_labelled_with_this_scope_are_removed(ci):
    mine = scope_of(ci)
    other_job = scope_of(ci, job="other")
    next_attempt = scope_of(ci, attempt="2")
    for engine in ("user", "root"):
        ci.seed_podman(
            engine,
            container={
                f"{engine}-mine": {"labels": {LABEL: mine}},
                f"{engine}-other-job": {"labels": {LABEL: other_job}},
                f"{engine}-other-attempt": {"labels": {LABEL: next_attempt}},
                f"{engine}-dev": {"labels": {}},
                f"{engine}-lookalike": {"labels": {LABEL: mine + "-extra"}},
            },
            pod={f"{engine}-pod-mine": {"labels": {LABEL: mine}}, f"{engine}-pod-dev": {"labels": {}}},
            volume={f"{engine}-vol-mine": {"labels": {LABEL: mine}}, f"{engine}-vol-dev": {"labels": {"keep": "me"}}},
            network={f"{engine}-net-mine": {"labels": {LABEL: mine}}},
        )
    result = ci.run("run")
    assert result.returncode == 0, result.stdout + result.stderr
    for engine in ("user", "root"):
        state = ci.podman_state(engine)
        assert set(state["container"]) == {f"{engine}-other-job", f"{engine}-other-attempt", f"{engine}-dev", f"{engine}-lookalike"}
        assert set(state["pod"]) == {f"{engine}-pod-dev"}
        assert set(state["volume"]) == {f"{engine}-vol-dev"}
        assert state["network"] == {}


def test_cleanup_never_runs_a_global_prune(ci):
    ci.seed_podman(container={"c": {"labels": {LABEL: scope_of(ci)}}})
    ci.run("run")
    calls = (ci.stub / "calls.log").read_text()
    assert "prune" not in calls and "system" not in calls
    assert "rm -f -t 5 c" in calls


def test_dry_run_removes_nothing(ci, tmp_path):
    scope = scope_of(ci)
    ci.seed_podman(container={"c": {"labels": {LABEL: scope}}}, image={"localhost/x:y": "sha256:1"})
    owned = ci.runner_temp / "owned"
    owned.mkdir()
    assert ci.run("own", "dir", str(owned)).returncode == 0
    assert ci.run("own", "image", "localhost/x:y").returncode == 0
    result = ci.run("run", DRY_RUN="1")
    assert result.returncode == 0 and "[dry-run]" in result.stdout
    assert "c" in ci.podman_state()["container"]
    assert "localhost/x:y" in ci.podman_state()["image"]
    assert owned.is_dir() and (ci.state_root / scope).is_dir()
    assert not ci.mutating_calls()


# -- images ------------------------------------------------------------------


def test_registered_image_is_removed_but_a_retagged_name_is_not(ci):
    ci.seed_podman(image={"localhost/mine:a": "sha256:aaa", "localhost/mine:b": "sha256:bbb", "localhost/dev:keep": "sha256:ddd"})
    assert ci.run("own", "image", "localhost/mine:a").returncode == 0
    assert ci.run("own", "image", "localhost/mine:b").returncode == 0
    # Someone re-points :b at a different image after we registered it.
    ci.seed_podman(image={"localhost/mine:b": "sha256:other"})
    result = ci.run("run")
    assert result.returncode == 0
    assert set(ci.podman_state()["image"]) == {"localhost/mine:b", "localhost/dev:keep"}
    assert "leaving it alone" in result.stdout


def test_an_image_in_root_storage_is_removed_from_root_storage_only(ci):
    ci.seed_podman("root", image={"localhost/r:1": "sha256:rrr"})
    ci.seed_podman("user", image={"localhost/r:1": "sha256:user"})
    assert ci.run("own", "image", "localhost/r:1", "--root").returncode == 0
    ci.run("run")
    assert ci.podman_state("root")["image"] == {}
    assert ci.podman_state("user")["image"] == {"localhost/r:1": "sha256:user"}


def test_an_image_that_does_not_exist_cannot_be_registered(ci):
    assert ci.run("own", "image", "localhost/ghost:1").returncode == 1
    assert not (ci.state_root).exists() or not any(ci.state_root.rglob("ledger-*.jsonl"))


# -- directories: marker-bound ownership -------------------------------------


def test_registered_dir_is_removed_and_siblings_are_not(ci):
    mine = ci.runner_temp / "mine"
    sibling = ci.runner_temp / "sibling"
    for d in (mine, sibling):
        (d / "deep").mkdir(parents=True)
        (d / "deep" / "f").write_text("x")
    assert ci.run("own", "dir", str(mine)).returncode == 0
    assert ci.run("run").returncode == 0
    assert not mine.exists()
    assert (sibling / "deep" / "f").read_text() == "x"


def test_a_dir_whose_marker_is_gone_is_refused_not_deleted(ci):
    victim = ci.runner_temp / "replaced"
    victim.mkdir()
    assert ci.run("own", "dir", str(victim)).returncode == 0
    # The path was removed and recreated by something else: no marker.
    shutil.rmtree(victim)
    victim.mkdir()
    (victim / "precious").write_text("not ours")
    result = ci.run("run")
    assert result.returncode == 1
    assert "REFUSED" in result.stdout
    assert (victim / "precious").read_text() == "not ours"


def test_a_dir_owned_by_another_job_cannot_be_registered_or_removed(ci):
    shared = ci.runner_temp / "shared"
    shared.mkdir()
    assert ci.run("own", "dir", str(shared), job="first").returncode == 0
    assert ci.run("own", "dir", str(shared), job="second").returncode == 1
    # The second job's cleanup leaves the first job's tree alone.
    assert ci.run("run", job="second").returncode == 0
    assert shared.is_dir()
    assert ci.run("run", job="first").returncode == 0
    assert not shared.exists()


@pytest.mark.parametrize("where", ["/etc", "/usr/lib", "/home", "/"])
def test_dirs_outside_the_job_roots_cannot_be_registered(ci, where):
    assert ci.run("own", "dir", where).returncode == 1
    assert Path(where).exists()


def test_the_roots_themselves_cannot_be_registered(ci):
    for root in (ci.runner_temp, ci.workspace):
        assert ci.run("own", "dir", str(root)).returncode == 1
        assert root.is_dir()


def test_a_symlink_cannot_be_registered_so_its_target_survives(ci):
    target = ci.tmp / "outside"
    target.mkdir()
    (target / "keep").write_text("x")
    link = ci.runner_temp / "link"
    link.symlink_to(target, target_is_directory=True)
    assert ci.run("own", "dir", str(link)).returncode == 1
    assert ci.run("run").returncode == 0
    assert (target / "keep").read_text() == "x"


def test_a_ledger_entry_pointing_at_a_symlink_is_refused(ci):
    scope = scope_of(ci)
    target = ci.tmp / "outside2"
    target.mkdir()
    (target / "keep").write_text("x")
    link = ci.runner_temp / "sneaky"
    link.symlink_to(target, target_is_directory=True)
    ledger = ci.state_root / scope / f"ledger-{os.geteuid()}.jsonl"
    ledger.parent.mkdir(parents=True)
    (ledger.parent / ".tunaos-ci-owned.json").write_text(json.dumps({"schema": 1, "scope": scope}))
    ledger.write_text(json.dumps({"kind": "dir", "path": str(link)}) + "\n")
    result = ci.run("run")
    assert result.returncode == 1 and "REFUSED" in result.stdout
    assert (target / "keep").read_text() == "x"


def test_scratch_is_removed_with_the_scope_but_other_scopes_survive(ci):
    mine = Path(ci.run("scratch").stdout.strip())
    theirs = Path(ci.run("scratch", job="other").stdout.strip())
    (mine / "a").write_text("1")
    (theirs / "b").write_text("2")
    assert ci.run("run").returncode == 0
    assert not mine.exists()
    assert (theirs / "b").read_text() == "2"


def test_a_tampered_scope_directory_is_refused(ci):
    scope = scope_of(ci)
    scratch = Path(ci.run("scratch").stdout.strip())
    (scratch / "keep").write_text("x")
    (ci.state_root / scope / ".tunaos-ci-owned.json").write_text(json.dumps({"scope": "someone-else"}))
    result = ci.run("run")
    assert result.returncode == 1 and "REFUSED" in result.stdout
    assert (scratch / "keep").read_text() == "x"


# -- processes: pidfile ownership --------------------------------------------


def spawn_fake_qemu(pidfile: Path, mention_pidfile=True) -> subprocess.Popen:
    argv = [sys.executable, "-c", "import time; time.sleep(120)"]
    if mention_pidfile:
        argv += ["-pidfile", str(pidfile)]
    proc = subprocess.Popen(argv, start_new_session=True)
    pidfile.write_text(f"{proc.pid}\n")
    return proc


def alive(proc: subprocess.Popen) -> bool:
    return proc.poll() is None


def test_a_registered_vm_is_stopped(ci):
    pidfile = ci.runner_temp / "qemu.pid"
    proc = spawn_fake_qemu(pidfile)
    try:
        assert ci.run("own", "pidfile", str(pidfile)).returncode == 0
        assert ci.run("run").returncode == 0
        deadline = time.monotonic() + 15
        while alive(proc) and time.monotonic() < deadline:
            time.sleep(0.1)
        assert not alive(proc)
    finally:
        if alive(proc):
            os.killpg(proc.pid, signal.SIGKILL)


def test_a_recycled_pid_is_never_signalled(ci):
    """The pidfile survived but its pid now belongs to an unrelated process."""
    pidfile = ci.runner_temp / "qemu.pid"
    bystander = spawn_fake_qemu(pidfile, mention_pidfile=False)
    try:
        assert ci.run("own", "pidfile", str(pidfile)).returncode == 0
        result = ci.run("run")
        assert result.returncode == 0 and "leaving it alone" in result.stdout
        time.sleep(0.3)
        assert alive(bystander)
    finally:
        os.killpg(bystander.pid, signal.SIGKILL)


def test_a_missing_pidfile_is_not_an_error(ci):
    assert ci.run("own", "pidfile", str(ci.runner_temp / "never-written.pid")).returncode == 0
    assert ci.run("run").returncode == 0


def test_dry_run_leaves_the_vm_running(ci):
    pidfile = ci.runner_temp / "qemu.pid"
    proc = spawn_fake_qemu(pidfile)
    try:
        ci.run("own", "pidfile", str(pidfile))
        result = ci.run("run", DRY_RUN="1")
        assert "would stop" in result.stdout
        time.sleep(0.3)
        assert alive(proc)
    finally:
        os.killpg(proc.pid, signal.SIGKILL)


# -- loop devices ------------------------------------------------------------


def test_loop_devices_backing_our_file_are_detached_and_others_are_not(ci):
    mine, theirs = ci.runner_temp / "disk.raw", ci.runner_temp / "other.raw"
    mine.write_text("")
    theirs.write_text("")
    (ci.stub / "loops.json").write_text(json.dumps({"/dev/loop3": str(mine), "/dev/loop5": str(mine), "/dev/loop4": str(theirs)}))
    assert ci.run("own", "loop", str(mine)).returncode == 0
    assert ci.run("run").returncode == 0
    assert json.loads((ci.stub / "loops.json").read_text()) == {"/dev/loop4": str(theirs)}


def test_dry_run_detaches_nothing(ci):
    mine = ci.runner_temp / "disk.raw"
    mine.write_text("")
    (ci.stub / "loops.json").write_text(json.dumps({"/dev/loop3": str(mine)}))
    assert ci.run("own", "loop", str(mine)).returncode == 0
    result = ci.run("run", DRY_RUN="1")
    assert "would detach /dev/loop3" in result.stdout
    assert json.loads((ci.stub / "loops.json").read_text()) == {"/dev/loop3": str(mine)}


@pytest.mark.parametrize("target", ["/dev/sda", "/dev/loop3", "relative.raw", "/etc/hostname"])
def test_only_a_file_under_the_job_roots_can_be_registered_as_loop_backing(ci, target):
    assert ci.run("own", "loop", target).returncode == 1


# -- the recipe --------------------------------------------------------------


@pytest.mark.skipif(shutil.which("just") is None, reason="just is not installed")
def test_the_recipe_runs_in_a_job_without_yq_and_cleans_up(ci):
    """Jobs that never installed yq must still be able to call the recipe."""
    scratch = Path(ci.run("scratch").stdout.strip())
    (scratch / "x").write_text("x")
    env = ci.env()
    just = shutil.which("just")
    env["PATH"] = f"{ci.stub}:/usr/bin:/bin"  # no yq anywhere on this PATH
    assert shutil.which("yq", path=env["PATH"]) is None
    result = subprocess.run([just, "--justfile", str(ROOT / "Justfile"), "ci-cleanup"], env=env, capture_output=True, text=True, cwd=ROOT)
    assert result.returncode == 0, result.stderr
    assert not scratch.exists()


# -- the shell helpers scripts source ----------------------------------------


def bash(ci: Env, snippet: str, **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", "-euo", "pipefail", "-c", f'. "{ROOT}/scripts/lib/ci-scope.sh"\n{snippet}'], env=ci.env(**kwargs), capture_output=True, text=True)


def test_shell_helpers_register_labels_and_directories(ci):
    work = ci.runner_temp / "work"
    work.mkdir()
    result = bash(ci, f'ci_labels=(); mapfile -t ci_labels < <(ci_label_args); printf "%s\\n" "${{ci_labels[@]}}"; ci_own_dir "{work}"')
    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["--label", f"{LABEL}={scope_of(ci)}"]
    assert ci.run("run").returncode == 0
    assert not work.exists()


def test_shell_helpers_are_silent_no_ops_outside_ci(ci):
    env = ci.env()
    env.pop("GITHUB_RUN_ID")
    work = ci.runner_temp / "work"
    work.mkdir()
    script = f'. "{ROOT}/scripts/lib/ci-scope.sh"; mapfile -t l < <(ci_label_args); echo "labels=${{#l[@]}}"; ci_own_dir "{work}"; ci_own_pidfile /x.pid; ci_own_loop "{work}/f"'
    result = subprocess.run(["bash", "-euo", "pipefail", "-c", script], env=env, capture_output=True, text=True)
    assert result.returncode == 0 and result.stdout.strip() == "labels=0"
    assert not (work / ".tunaos-ci-owned.json").exists() and not ci.state_root.exists()


def test_a_refused_registration_never_fails_the_calling_script(ci):
    """Registration is best effort: the creating script's own trap is the primary defence."""
    result = bash(ci, 'ci_own_dir /etc; ci_own_loop /dev/sda; echo survived')
    assert result.returncode == 0 and result.stdout.strip().endswith("survived")
