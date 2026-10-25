"""Migration of legacy fork-config files into tunaos.toml (#3807).

`scripts/config.py migrate-fork-config` is the one route from the retired
preview format to the primary file. These tests run the real command on real
legacy files and check the output bytes, the primary resolvers' view of that
output, and that every input it cannot convert fails loudly.

Fixture provenance (tests/fixtures/legacy-fork-config/):
  stock.yaml    output of `scripts/resolve-fork-config.py --init-template
                examples/fork/stock.template.yaml` at 6a7b019b, unedited.
  harbor.yaml   the same tool on examples/fork/harbor.template.yaml, unedited.
                It uses `targets` and a shared wallpaper, neither convertible.
  harbor-scoped.yaml  harbor's image, URLs and packages, with the targets and
                wallpaper removed and `htop` scoped to the two variants the
                targets named, so the primary package rules accept it.
  assets/harbor-wallpaper.jpg  the template's wallpaper.
The `catalog.sha256` pins are the receipt of 6a7b019b's sources and are not
verified by the migration.
"""
from __future__ import annotations

import difflib
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parent))
from test_publish_destination import config, resolve  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/legacy-fork-config"
PIN = "46841c62f73c140c4a48a524915dd3bcb2508d49285f3b3098118815cef21abb"


def migrate(root, legacy, *extra):
    return subprocess.run([sys.executable, str(ROOT / "scripts/config.py"), "migrate-fork-config",
                           "--root", str(root), "--legacy", str(legacy), *extra],
                          capture_output=True, text=True)


@pytest.fixture
def fork(tmp_path):
    root = tmp_path / "fork"
    root.mkdir()
    (root / "tunaos.toml").write_bytes((ROOT / "tunaos.toml").read_bytes())
    return root


def legacy(tmp_path, document, name="legacy.yaml"):
    path = tmp_path / name
    path.write_text(yaml.safe_dump({"schema_version": 1, "catalog": {"sha256": PIN}, **document}, sort_keys=False))
    return path


def changed_lines(before, after):
    return [line for line in difflib.unified_diff(before.splitlines(), after.splitlines(), lineterm="", n=0)
            if line[:1] in "+-" and not line.startswith(("+++", "---"))]


def test_fixtures_are_the_unedited_legacy_tool_output_and_the_documented_derivative():
    stock = yaml.safe_load((FIXTURES / "stock.yaml").read_text())
    assert stock == {"schema_version": 1, "catalog": {"sha256": PIN}}
    harbor = yaml.safe_load((FIXTURES / "harbor.yaml").read_text())
    assert harbor["catalog"]["sha256"] == PIN
    # The asset the real harbor file names sits beside it, as the legacy format required.
    assert (FIXTURES / harbor["global"]["branding"]["wallpaper"]).read_bytes().startswith(b"\xff\xd8\xff")
    scoped = yaml.safe_load((FIXTURES / "harbor-scoped.yaml").read_text())
    assert scoped["image"] == harbor["image"]
    assert {k: v for k, v in scoped["global"]["branding"].items()} == \
        {k: v for k, v in harbor["global"]["branding"].items() if k != "wallpaper"}
    assert scoped["overrides"]["variants"]["yellowfin"]["packages"] == \
        {"add": harbor["global"]["packages"]["add"], "optional": harbor["overrides"]["variants"]["yellowfin"]["packages"]["optional"]}
    assert scoped["overrides"]["variants"]["grouper"]["packages"] == {"add": harbor["global"]["packages"]["add"]}
    assert "targets" not in scoped and "wallpaper" not in scoped["global"]["branding"]


def test_stock_intent_migrates_to_the_same_bytes(fork):
    before = (fork / "tunaos.toml").read_bytes()
    result = migrate(fork, FIXTURES / "stock.yaml", "--write")
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    assert (fork / "tunaos.toml").read_bytes() == before


def test_harbor_scoped_output_bytes(fork):
    before = (fork / "tunaos.toml").read_text(encoding="utf-8")
    result = migrate(fork, FIXTURES / "harbor-scoped.yaml", "--write")
    assert result.returncode == 0, result.stderr
    after = (fork / "tunaos.toml").read_text(encoding="utf-8")
    assert changed_lines(before, after) == [
        '+',
        '+[build.publish]',
        '+registry = "localhost"',
        '+namespace = "harbor-preview"',
        '-homepage = "https://github.com/tuna-os/tunaos"',
        '-documentation = "https://github.com/tuna-os/tunaos/tree/main/docs"',
        '-support = "https://github.com/tuna-os/tunaos/issues/"',
        '+homepage = "https://example.org/harbor"',
        '+documentation = "https://example.org/harbor/docs"',
        '+support = "https://example.org/harbor/support"',
        '+',
        '+[variants.yellowfin.packages]',
        '+add = ["htop"]',
        '+optional = ["fastfetch"]',
        '+',
        '+[variants.grouper.packages]',
        '+add = ["htop"]',
    ]
    # Comments and layout survive: only the lines above differ, and the new
    # tables sit directly after the keys they extend.
    assert 'global_platforms = ["linux/amd64", "linux/arm64"]\n\n[build.publish]\n' in after
    assert '# Friendly alias: same digest also published as ghcr.io/tuna-os/<alias>:<flavor>' in after
    assert after.count("\n#") == before.count("\n#")
    # Run again on the migrated file: nothing is left to change.
    again = migrate(fork, FIXTURES / "harbor-scoped.yaml")
    assert again.returncode == 0 and again.stdout == ""


def test_output_is_deterministic_idempotent_and_previewed_without_writing(fork, tmp_path):
    source = (fork / "tunaos.toml").read_bytes()
    first = migrate(fork, FIXTURES / "harbor-scoped.yaml")
    second = migrate(fork, FIXTURES / "harbor-scoped.yaml")
    assert first.returncode == second.returncode == 0
    assert first.stdout == second.stdout and first.stdout.startswith("--- ")
    assert (fork / "tunaos.toml").read_bytes() == source  # no --write, no change
    assert migrate(fork, FIXTURES / "harbor-scoped.yaml", "--write").returncode == 0
    written = (fork / "tunaos.toml").read_bytes()
    assert migrate(fork, FIXTURES / "harbor-scoped.yaml", "--write").returncode == 0
    assert (fork / "tunaos.toml").read_bytes() == written


def test_the_primary_resolvers_see_the_migrated_values(fork, tmp_path):
    assert migrate(fork, FIXTURES / "harbor-scoped.yaml", "--write").returncode == 0
    migrated = config.load(fork / "tunaos.toml")
    adapter = tmp_path / "build-config.yml"
    adapter.write_text(config.render(migrated), encoding="utf-8")
    assert resolve(adapter) == "localhost harbor-preview"
    rows = config.render_image_packages(migrated).splitlines()
    assert "yellowfin\tdnf\tadd\thtop" in rows and "yellowfin\tdnf\toptional\tfastfetch" in rows
    assert "grouper\tapt\tadd\thtop" in rows
    assert not any(row.startswith(("guppy", "sailfin", "marlin")) for row in rows[1:] if "\thtop" in row)
    identity = config.render_identity(migrated)
    assert "https://example.org/harbor/support" in identity
    validate = subprocess.run([sys.executable, str(ROOT / "scripts/config.py"), "validate", "--root", str(fork)],
                              capture_output=True, text=True)
    assert validate.returncode == 0, validate.stderr


def test_variant_repositories_are_written_as_tables(fork, tmp_path):
    repo = {"id": "acme", "url": "https://repo.example.org/el", "key_url": "https://repo.example.org/key.gpg"}
    path = legacy(tmp_path, {"overrides": {"variants": {"yellowfin": {"packages": {"repositories": [repo], "add": ["htop"]}}}}})
    result = migrate(fork, path, "--write")
    assert result.returncode == 0, result.stderr
    migrated = config.load(fork / "tunaos.toml")
    assert migrated["variants"]["yellowfin"]["packages"] == {"add": ["htop"], "repositories": [repo]}
    assert "yellowfin\tdnf\trepository\tacme\thttps://repo.example.org/el\thttps://repo.example.org/key.gpg" in \
        config.render_image_packages(migrated)


REJECTED = [
    ("wallpaper", {"global": {"branding": {"wallpaper": "assets/w.jpg"}}}, "global.branding.wallpaper"),
    ("name", {"global": {"branding": {"name": "Acme"}}}, "global.branding.name"),
    ("logo", {"global": {"branding": {"logo": "assets/l.svg"}}}, "global.branding.logo"),
    ("variant URL", {"overrides": {"variants": {"yellowfin": {"branding": {"homepage": "https://a.example"}}}}},
     "overrides.variants.yellowfin.branding.homepage"),
    ("desktop scope", {"overrides": {"desktops": {"gnome": {"packages": {"add": ["htop"]}}}}}, "overrides.desktops.gnome"),
    ("cell scope", {"overrides": {"cells": {"yellowfin:gnome": {"packages": {"add": ["htop"]}}}}},
     "overrides.cells.yellowfin:gnome"),
    ("removal", {"global": {"packages": {"remove": ["bash"]}}}, "global.packages.remove"),
    ("variant removal", {"overrides": {"variants": {"yellowfin": {"packages": {"remove": ["bash"]}}}}},
     "overrides.variants.yellowfin.packages.remove"),
    ("targets", {"targets": {"variants": ["yellowfin"]}}, "targets:"),
    ("unknown top-level key", {"imgae": {"registry": "localhost", "namespace": "x"}}, "unknown keys ['imgae']"),
    ("unknown layer key", {"global": {"hooks": {}}}, "unknown keys ['hooks']"),
    ("unknown package key", {"global": {"packages": {"pin": ["htop"]}}}, "unknown keys ['pin']"),
    ("incomplete image", {"image": {"registry": "localhost"}}, "missing keys ['namespace']"),
    ("not a list", {"global": {"packages": {"add": "htop"}}}, "global.packages.add: expected a list"),
    ("duplicate package", {"global": {"packages": {"add": ["htop", "htop"]}}}, "distinct nonempty strings"),
    ("invalid registry", {"image": {"registry": "Quay.io", "namespace": "acme"}}, "build.publish.registry"),
    ("invalid URL", {"global": {"branding": {"homepage": "http://insecure.example"}}}, "defaults.branding.homepage"),
    ("unsafe package", {"overrides": {"variants": {"yellowfin": {"packages": {"add": ["htop; reboot"]}}}}},
     "not a plain native package name"),
    ("manager mismatch", {"overrides": {"variants": {"guppy": {"packages": {"add": ["htop"]}}}}},
     "not a valid package name for emerge"),
    ("unknown variant", {"overrides": {"variants": {"nosuchfish": {"packages": {"add": ["htop"]}}}}}, "nosuchfish"),
]


@pytest.mark.parametrize("label,document,message", REJECTED, ids=[row[0] for row in REJECTED])
def test_unconvertible_legacy_input_fails_loudly_and_changes_nothing(fork, tmp_path, label, document, message):
    before = (fork / "tunaos.toml").read_bytes()
    result = migrate(fork, legacy(tmp_path, document), "--write")
    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr.startswith("ERROR: ")
    assert message in result.stderr
    assert (fork / "tunaos.toml").read_bytes() == before


def test_the_real_harbor_file_is_refused_with_every_reason(fork):
    before = (fork / "tunaos.toml").read_bytes()
    result = migrate(fork, FIXTURES / "harbor.yaml", "--write")
    assert result.returncode == 1 and result.stdout == ""
    assert "targets:" in result.stderr
    assert "global.branding.wallpaper" in result.stderr
    assert (fork / "tunaos.toml").read_bytes() == before


def test_harbors_global_package_is_refused_where_a_variant_cannot_install_it(fork, tmp_path):
    harbor = yaml.safe_load((FIXTURES / "harbor.yaml").read_text())
    del harbor["targets"], harbor["global"]["branding"]["wallpaper"]
    path = tmp_path / "harbor-core.yaml"
    path.write_text(yaml.safe_dump(harbor, sort_keys=False))
    result = migrate(fork, path)
    assert result.returncode == 1
    assert "defaults.packages: 'htop' is not a valid package name for emerge, which variant guppy builds with" in result.stderr


@pytest.mark.parametrize("text,message", [
    ("", "expected a mapping"),
    ("schema_version: 2\ncatalog:\n  sha256: " + PIN + "\n", "schema_version: expected integer 1"),
    ("schema_version: 1\n", "missing keys ['catalog']"),
    ("schema_version: 1\ncatalog:\n  sha256: nothex\n", "catalog.sha256: expected a lowercase SHA-256"),
    ("schema_version: 1\nschema_version: 1\ncatalog:\n  sha256: " + PIN + "\n", "duplicate or non-string key"),
    ("schema_version: [1\n", "not valid YAML"),
])
def test_malformed_legacy_files_are_rejected(fork, tmp_path, text, message):
    path = tmp_path / "bad.yaml"
    path.write_text(text)
    result = migrate(fork, path)
    assert result.returncode == 1 and result.stdout == ""
    assert message in result.stderr


def test_a_missing_legacy_file_is_an_error(fork, tmp_path):
    result = migrate(fork, tmp_path / "absent.yaml")
    assert result.returncode == 1 and "absent.yaml" in result.stderr


def test_an_existing_different_package_table_is_never_merged(fork, tmp_path):
    source = (fork / "tunaos.toml").read_text(encoding="utf-8")
    anchor = 'platforms = ["linux/amd64", "linux/amd64/v2", "linux/arm64"]\n\n[[variants.yellowfin.flavors]]'
    assert source.count(anchor) == 1
    (fork / "tunaos.toml").write_text(source.replace(
        anchor, anchor.replace("\n\n[[", '\n\n[variants.yellowfin.packages]\nadd = ["tree"]\n\n[[')), encoding="utf-8")
    before = (fork / "tunaos.toml").read_bytes()
    result = migrate(fork, FIXTURES / "harbor-scoped.yaml", "--write")
    assert result.returncode == 1
    assert "already defines [variants.yellowfin.packages] differently" in result.stderr
    assert (fork / "tunaos.toml").read_bytes() == before


def test_a_primary_file_that_cannot_hold_the_values_is_refused(fork, tmp_path):
    source = (fork / "tunaos.toml").read_text(encoding="utf-8")
    start = source.index("[defaults.branding]")
    end = source.index("[[iso_groups]]")
    (fork / "tunaos.toml").write_text(source[:start] + source[end:], encoding="utf-8")
    result = migrate(fork, legacy(tmp_path, {"global": {"branding": {"homepage": "https://a.example"}}}))
    assert result.returncode == 1
    assert "defaults" in result.stderr


def test_the_command_requires_a_legacy_file(fork):
    result = subprocess.run([sys.executable, str(ROOT / "scripts/config.py"), "migrate-fork-config",
                             "--root", str(fork)], capture_output=True, text=True)
    assert result.returncode == 2
    assert "migrate-fork-config requires --legacy" in result.stderr


def test_a_host_without_pyyaml_gets_an_install_hint_not_a_traceback(fork):
    shim = ("import runpy, sys; sys.modules['yaml'] = None; "
            f"sys.argv = ['config.py', 'migrate-fork-config', '--root', {str(fork)!r}, '--legacy', {str(FIXTURES / 'stock.yaml')!r}]; "
            f"sys.path.insert(0, {str(ROOT / 'scripts')!r}); runpy.run_path({str(ROOT / 'scripts/config.py')!r}, run_name='__main__')")
    result = subprocess.run([sys.executable, "-c", shim], capture_output=True, text=True)
    assert result.returncode == 1
    assert "migrate-fork-config needs yaml: python3 -m pip install PyYAML" in result.stderr
    assert "Traceback" not in result.stderr


RETIRED = ("resolve-fork-config", "prepare-fork-config", "fork-config.json", "fork-branding", "fork-packages",
           "fork-assets", "examples/fork", "FORK-CONFIG-PREVIEW", "FORK-BRANDING.md")
# Code and CI only. The migration module and this file name the retired format on purpose.
SCANNED = ("scripts/", "build_scripts/", "just/", ".github/workflows/", "Containerfile", "Justfile", "tests/", "system_files/",
           "live-iso/", "services/")
# Two tests assert that a leftover payload is ignored and never written.
EXEMPT = ("scripts/lib/legacy_fork_config.py", "tests/test_legacy_fork_migration.py", "tests/fixtures/legacy-fork-config/",
          "tests/test_primary_packages.py", "tests/test_identity_publish_integration.py")


def test_no_tracked_code_reads_a_retired_preview_interface():
    tracked = subprocess.check_output(["git", "-C", str(ROOT), "ls-files", "-z"], text=True).split("\0")
    offenders = []
    for name in filter(None, tracked):
        if not name.startswith(SCANNED) or name.startswith(EXEMPT) or not (ROOT / name).is_file():
            continue
        text = (ROOT / name).read_bytes().decode("utf-8", "ignore")
        offenders += [f"{name}: {token}" for token in RETIRED if token in text]
    assert offenders == []


def test_the_retired_commands_and_inputs_are_gone():
    for name in ("scripts/resolve-fork-config.py", "scripts/prepare-fork-config.py",
                 "build_scripts/lib/fork-branding.sh", "build_scripts/lib/fork-packages.sh",
                 "examples/fork", "docs/FORK-CONFIG-PREVIEW.md", "docs/FORK-BRANDING.md"):
        assert not (ROOT / name).exists(), name
