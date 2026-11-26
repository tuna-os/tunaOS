"""The post-install edits (tunaOS#4907): new UUIDs, live entry gone, gpt-auto kept."""

import importlib.util
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOOKS = ROOT / "installer-medium/hooks"
spec = importlib.util.spec_from_file_location("post_finish", HOOKS / "post_finish.py")
pf = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pf)

OLD, NEW = "11111111-2222-3333-4444-555555555555", "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
LUKS = "99999999-8888-7777-6666-555555555555"
DEPLOY = f"title T\nversion 5\noptions rw root=UUID={OLD} quiet\n"
LIVE = f"title Live\nversion 1005\noptions ro tunaos.live root=UUID={OLD}\n"
GPT_AUTO = "title T\nlinux /k\noptions quiet rhgb\n"


def tree(tmp_path):
    root, esp = tmp_path / "root", tmp_path / "esp"
    (root / "boot/loader/entries").mkdir(parents=True)
    (esp / "loader/entries").mkdir(parents=True)
    (root / "etc").mkdir()
    (root / "boot/loader/entries/deploy.conf").write_text(DEPLOY)
    (root / "boot/loader/entries/medium-live.conf").write_text(LIVE)
    (esp / "loader/entries/auto.conf").write_text(GPT_AUTO)
    (esp / "loader/loader.conf").write_text("default medium-live\ntimeout 5\n")
    (root / "etc/fstab").write_text(f"UUID={OLD} / btrfs defaults 0 0\n")
    return root, esp


def test_live_entry_removed_and_uuid_rewritten(tmp_path):
    root, esp = tree(tmp_path)
    rep = pf.apply(root, esp, {OLD: NEW}, luks_uuid=LUKS)
    assert not (root / "boot/loader/entries/medium-live.conf").exists()
    deploy = (root / "boot/loader/entries/deploy.conf").read_text()
    assert f"root=UUID={NEW}" in deploy and OLD not in deploy
    assert f"rd.luks.uuid={LUKS}" in deploy
    assert (esp / "loader/loader.conf").read_text() == "timeout 5\n"
    assert NEW in (root / "etc/fstab").read_text()
    assert (root / "etc/crypttab").read_text() == f"root UUID={LUKS} none discard\n"
    assert len(rep["removed"]) == 1


def test_gpt_auto_entry_is_left_without_a_root_karg(tmp_path):
    root, esp = tree(tmp_path)
    rep = pf.apply(root, esp, {OLD: NEW}, luks_uuid=LUKS)
    assert (esp / "loader/entries/auto.conf").read_text() == GPT_AUTO
    assert rep["gpt_auto"] == [str(esp / "loader/entries/auto.conf")]


def test_dry_run_changes_nothing(tmp_path):
    root, esp = tree(tmp_path)
    pf.apply(root, esp, {OLD: NEW}, dry_run=True)
    assert (root / "boot/loader/entries/medium-live.conf").exists()
    assert OLD in (root / "boot/loader/entries/deploy.conf").read_text()


def test_tpm2_crypttab_and_no_duplicate_luks_karg():
    assert "tpm2-device=auto" in pf.crypttab_line(LUKS, True)
    once = pf.luks_karg(DEPLOY, LUKS)
    assert pf.luks_karg(once, LUKS).count("rd.luks.uuid=") == 1


def test_grub_default_and_grubenv_drop_the_live_entry():
    assert pf.drop_grub_default('set default="medium-live"\nset x=1\n') == "set x=1\n"
    env = "# GRUB Environment Block\nsaved_entry=medium-live\nkernelopts=a\n" + "#" * 200
    out = pf.drop_saved_entry(env, ["medium-live"])
    assert "saved_entry" not in out and "kernelopts=a" in out and len(out) == len(env)


def test_bad_uuid_is_refused():
    try:
        pf.rewrite_uuids("x", {"zz": "yy"})
    except ValueError:
        return
    raise AssertionError("expected ValueError")


def test_hooks_are_executable_and_shell_parses():
    for h in sorted((HOOKS / "post.d").iterdir()):
        assert h.stat().st_mode & 0o111, h
        subprocess.run(["bash", "-n", str(h)], check=True)
