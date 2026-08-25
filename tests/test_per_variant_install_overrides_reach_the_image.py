"""hummingbird must ship an ext4 root drop-in, and the hook must deliver it.

`bootc install to-disk` ABORTS for hummingbird: it probes unsealed, takes
`type = "xfs"` from 00-tunaos.toml, and BIOS grub2-install cannot read the
xfs this base's mkfs.xfs writes. bootupctl installs the BIOS component
unconditionally, so the whole install fails -- on UEFI hardware too. Six
consecutive nightly Gates died on it (run 32786338463, gnome Gate job
97638679623) and hummingbird:gnome was never promoted.

The CI-only knob (TUNAOS_QCOW2_FILESYSTEM) fixes the gate's own qcow2 and
NOTHING ELSE: an ISO install reads the config from inside the image. So a
green gate with no drop-in would hand users an installer that cannot
finish -- a pass that means the opposite of what it looks like. These
tests hold the drop-in and the hook that carries it.

The hook is tested by RUNNING it against a fake context, not by grepping
the Containerfile, because its real failure mode is applying nothing while
exiting 0.
"""

import os
import subprocess
import textwrap
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DROPIN = ROOT / "system_files_overrides" / "hummingbird" / "usr" / "lib" / "bootc" / "install" / "50-hummingbird.toml"
HOOK = ROOT / "build_scripts" / "92-variant-customizations.sh"
BASE = ROOT / "system_files" / "usr" / "lib" / "bootc" / "install" / "00-tunaos.toml"


def test_hummingbird_ships_an_ext4_root_dropin():
    assert DROPIN.is_file(), f"missing {DROPIN.relative_to(ROOT)}"
    text = DROPIN.read_text()
    assert "[install.filesystem.root]" in text, text
    assert 'type = "ext4"' in text, text


def test_the_dropin_outsorts_the_xfs_default():
    """bootc reads the directory in sort order; a lower name would lose."""
    assert BASE.is_file()
    assert 'type = "xfs"' in BASE.read_text(), "the default this must override changed"
    assert sorted([BASE.name, DROPIN.name])[-1] == DROPIN.name, (
        f"{DROPIN.name} must sort after {BASE.name} or the xfs default wins"
    )


def test_the_containerfile_runs_the_hook_after_the_arch_one():
    cf = (ROOT / "Containerfile.el10").read_text()
    assert "92-variant-customizations.sh" in cf, "hook is never invoked"
    assert cf.index("91-arch-customizations.sh") < cf.index("92-variant-customizations.sh"), (
        "variant overrides must run after arch overrides so a variant can win"
    )


def _run_hook(tmp_path, variant_env, overrides_variant):
    """Run the hook against a fake /run/context, returning (rc, out, landed)."""
    ctx = tmp_path / "context"
    (ctx / "build_scripts").mkdir(parents=True)
    src = ctx / "overrides" / overrides_variant / "usr" / "lib" / "bootc" / "install"
    src.mkdir(parents=True)
    (src / "50-x.toml").write_text('[install.filesystem.root]\ntype = "ext4"\n')

    dest = tmp_path / "rootfs"
    dest.mkdir()
    # Stub lib.sh: copy_systemfiles_for into $dest instead of /.
    (ctx / "build_scripts" / "lib.sh").write_text(textwrap.dedent(f"""
        canonical_variant() {{ echo "$1"; }}
        copy_systemfiles_for() {{ cp -rf "{ctx}/overrides/$1/." "{dest}/"; }}
        run_buildscripts_for() {{ :; }}
    """))

    hook = ctx / "build_scripts" / "92-variant-customizations.sh"
    hook.write_text(HOOK.read_text().replace("/run/context", str(ctx)))
    hook.chmod(0o755)

    env = dict(os.environ)
    env.pop("IMAGE_NAME_VARIANT", None)
    if variant_env is not None:
        env["IMAGE_NAME_VARIANT"] = variant_env
    p = subprocess.run([str(hook)], capture_output=True, text=True, env=env)
    landed = (dest / "usr/lib/bootc/install/50-x.toml").is_file()
    return p.returncode, p.stdout + p.stderr, landed


def test_the_hook_applies_the_override_for_the_matching_variant(tmp_path):
    rc, out, landed = _run_hook(tmp_path, "hummingbird", "hummingbird")
    assert rc == 0, out
    assert landed, f"override did not reach the rootfs:\n{out}"


def test_the_hook_is_a_noop_for_a_variant_with_no_overrides(tmp_path):
    rc, out, landed = _run_hook(tmp_path, "yellowfin", "hummingbird")
    assert rc == 0, out
    assert not landed, "yellowfin must not pick up hummingbird's override"
    assert "No variant overrides" in out, out


def test_the_hook_fails_loudly_when_the_variant_is_unknown(tmp_path):
    """Silently skipping every override is how this bug survived six nights."""
    rc, out, landed = _run_hook(tmp_path, None, "hummingbird")
    assert rc != 0, f"unset IMAGE_NAME_VARIANT must fail, not skip:\n{out}"
    assert "IMAGE_NAME_VARIANT" in out
    assert not landed
