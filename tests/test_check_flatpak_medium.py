"""The Flatpak set baked into a live medium equals the generated policy (tunaOS#4907).

Falsification: adding, dropping or re-branching an app on either side fails
with a diff that names the app. The real-policy test runs the production
generator output (flatpak-preinstall.sh) through the checker, so the medium
recipe and the checker cannot drift from tunaos.toml.
"""
import importlib.util
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/check-flatpak-medium.py"
spec = importlib.util.spec_from_file_location("check_flatpak_medium", SCRIPT)
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)

TSV = "# header\n*\tio.github.kolunmi.Bazaar\tstable\n*\torg.mozilla.firefox\tstable\ngnome\tcom.mattjakeman.ExtensionManager\tstable\n"
COMMON = ["io.github.kolunmi.Bazaar", "org.mozilla.firefox"]


def run(*args):
    return subprocess.run(["python3", "-I", str(SCRIPT), *args], capture_output=True, text=True)


def policy(tmp_path):
    path = tmp_path / "policy.tsv"
    path.write_text(TSV)
    return str(path)


def preinstall_dir(tmp_path, apps, extra=""):
    directory = tmp_path / "preinstall.d"
    directory.mkdir()
    body = "".join(f"[Flatpak Preinstall {app}]\nBranch=stable\nIsRuntime=false\n\n" for app in apps)
    (directory / "tunaos-medium.preinstall").write_text(body + extra)
    return str(directory)


def test_gnome_set_matches(tmp_path):
    result = run("--desktop", "gnome", "--policy", policy(tmp_path),
                 "--preinstall-dir", preinstall_dir(tmp_path, COMMON + ["com.mattjakeman.ExtensionManager"]))
    assert result.returncode == 0, result.stderr


def test_kde_set_excludes_gnome_addition(tmp_path):
    ok = run("--desktop", "kde", "--policy", policy(tmp_path), "--app", COMMON[0], "--app", COMMON[1])
    assert ok.returncode == 0, ok.stderr
    bad = run("--desktop", "kde", "--policy", policy(tmp_path), "--app", COMMON[0], "--app", COMMON[1],
              "--app", "com.mattjakeman.ExtensionManager")
    assert bad.returncode == 1
    assert "not declared in tunaos.toml: com.mattjakeman.ExtensionManager" in bad.stderr


def test_missing_app_is_named(tmp_path):
    result = run("--desktop", "gnome", "--policy", policy(tmp_path),
                 "--preinstall-dir", preinstall_dir(tmp_path, COMMON))
    assert result.returncode == 1
    assert "missing from the medium: com.mattjakeman.ExtensionManager (stable)" in result.stderr


def test_extra_app_is_named(tmp_path):
    result = run("--desktop", "kde", "--policy", policy(tmp_path),
                 "--preinstall-dir", preinstall_dir(tmp_path, COMMON + ["org.gimp.GIMP"]))
    assert result.returncode == 1
    assert "not declared in tunaos.toml: org.gimp.GIMP" in result.stderr


def test_wrong_branch_is_named(tmp_path):
    directory = tmp_path / "preinstall.d"
    directory.mkdir()
    (directory / "a.preinstall").write_text(
        "[Flatpak Preinstall io.github.kolunmi.Bazaar]\nBranch=beta\n\n"
        "[Flatpak Preinstall org.mozilla.firefox]\nBranch=stable\n")
    result = run("--desktop", "kde", "--policy", policy(tmp_path), "--preinstall-dir", str(directory))
    assert result.returncode == 1
    assert "wrong branch: io.github.kolunmi.Bazaar declared stable, baked beta" in result.stderr


def test_runtime_sections_are_ignored(tmp_path):
    extra = "[Flatpak Preinstall org.gnome.Platform]\nBranch=49\nIsRuntime=true\n"
    result = run("--desktop", "kde", "--policy", policy(tmp_path),
                 "--preinstall-dir", preinstall_dir(tmp_path, COMMON, extra))
    assert result.returncode == 0, result.stderr


def test_bad_input_is_exit_2(tmp_path):
    assert run("--desktop", "kde", "--policy", policy(tmp_path), "--preinstall-dir", str(tmp_path / "nope")).returncode == 2
    assert run("--desktop", "kde", "--policy", str(tmp_path / "nope.tsv"), "--app", "x.y.z").returncode == 2


def test_production_recipe_output_matches_real_policy(tmp_path):
    """flatpak-preinstall.sh writes what the checker accepts, for every desktop."""
    env = {**os.environ, "TUNAOS_SYSTEMD_SYSTEM_DIR": str(tmp_path / "units")}
    for desktop in ["gnome", "kde", "cosmic", "niri", "xfce", "pantheon"]:
        target = tmp_path / desktop / "preinstall.d"
        subprocess.run(
            ["bash", str(ROOT / "build_scripts/desktop/flatpak-preinstall.sh")],
            check=True, capture_output=True,
            env={**env, "TUNAOS_PREINSTALL_DIR": str(target), "DESKTOP_FLAVOR": desktop},
        )
        result = run("--desktop", desktop, "--preinstall-dir", str(target))
        assert result.returncode == 0, result.stderr


def test_flatpak_list_output_is_parsed():
    out = "io.github.kolunmi.Bazaar\tstable\norg.mozilla.firefox\tstable\n"
    assert checker.parse_flatpak_list(out) == {"io.github.kolunmi.Bazaar": "stable", "org.mozilla.firefox": "stable"}


def test_store_is_read_not_the_declared_list(tmp_path, monkeypatch):
    # The store holds only one of the two declared apps: the check must fail.
    monkeypatch.setattr(checker, "baked_from_store", lambda store: {"io.github.kolunmi.Bazaar": "stable"})
    store = tmp_path / "flatpak"
    store.mkdir()
    pol = policy(tmp_path)
    assert checker.main(["--desktop", "kde", "--policy", pol, "--store", str(store)]) == 1


def test_missing_store_is_exit_2(tmp_path):
    assert run("--desktop", "kde", "--policy", policy(tmp_path), "--store", str(tmp_path / "none")).returncode == 2


def test_the_cell_installer_app_is_not_a_policy_app(tmp_path, monkeypatch):
    # bonito:xfce run 45902212282: the store holds org.tunaos.InstallerXfce
    # (install-frontend.sh, pinned by pin.env) next to the fixed set.
    monkeypatch.setattr(checker, "baked_from_store", lambda store: {
        **{app: "stable" for app in COMMON}, "org.tunaos.InstallerXfce": "master"})
    store = tmp_path / "flatpak"
    store.mkdir()
    pol = policy(tmp_path)
    args = ["--desktop", "xfce", "--policy", pol, "--store", str(store)]
    assert checker.main(args) == 1
    assert checker.main([*args, "--installer", "org.tunaos.InstallerXfce"]) == 0
    # Only that app: another undeclared app still fails.
    monkeypatch.setattr(checker, "baked_from_store", lambda store: {
        **{app: "stable" for app in COMMON}, "org.tunaos.InstallerXfce": "master", "org.example.Extra": "stable"})
    assert checker.main([*args, "--installer", "org.tunaos.InstallerXfce"]) == 1
