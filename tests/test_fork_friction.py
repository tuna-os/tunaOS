"""What a newcomer forking TunaOS hits, run against the real validators.

Each test here comes from a measured step of the "Acme OS" walk-through in
docs/ROLL_YOUR_OWN.md: fork, edit only tunaos.toml and asset files, run the
config tools. Nothing here builds, installs or boots an image; every test runs
the repository's own resolvers and validators on real tunaos.toml content.

Covered:
- `config.py generate-all` writes every generated adapter, and on stock
  tunaos.toml it reproduces every committed generated file byte for byte;
- a fork's drift errors name the one command that fixes them;
- the errors a forker is most likely to meet (pruning variants, a shared
  package that is not portable, a bad Flatpak entry) name the offending value;
- a variant removed from tunaos.toml cannot leave its scheduled workflow behind;
- check-artwork.py names its missing dependency, and `--write` cannot delete
  committed artwork when a generator fails.
"""
from __future__ import annotations

import copy
import importlib.util
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    assert spec is not None and spec.loader is not None, f"cannot load {relative}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


config = load("fork_friction_config", "scripts/lib/tunaos_config.py")
checker = load("fork_friction_checker", "scripts/branding/check-artwork.py")
workflows = load("fork_friction_workflows", "scripts/generate-workflows.py")

GENERATED = (
    ".github/build-config.yml",
    "build_scripts/lib/identity.env",
    "build_scripts/lib/variant-identity.tsv",
    "build_scripts/lib/variant-aliases.tsv",
    "build_scripts/lib/image-packages.tsv",
    "build_scripts/desktop/flatpak-preinstall.tsv",
    "docs/iso-builder.config.json",
    "docs/iso-builder.flavors.json",
)
CHECKS = ("check-identity", "check-variant-identity", "check-variant-aliases", "check-image-packages",
          "check-flatpak-policy", "check-builder-config", "check-builder-flavors")

# The Acme OS edits from the walk-through: its own name, destination, accents,
# a Flatpak, and added packages for one RPM and one APT variant.
ACME_EDITS = (
    ('global_platforms = ["linux/amd64", "linux/arm64"]\n',
     'global_platforms = ["linux/amd64", "linux/arm64"]\n\n[build.publish]\nregistry = "quay.io"\nnamespace = "acme"\n'),
    ('name = "TunaOS"\nid = "tunaos"\ncpe_vendor = "jamesreilly"', 'name = "Acme OS"\nid = "acmeos"\ncpe_vendor = "acme"'),
    ('homepage = "https://github.com/tuna-os/tunaos"\n', 'homepage = "https://acme.example/os"\n'),
    ('website = "https://tunaos.org"\ndocs_url = "https://tunaos.org/docs"\n',
     'website = "https://acme.example"\ndocs_url = "https://acme.example/docs"\n'),
    ('countme_endpoint = "https://countme.tunaos.org/v1/report"\ncountme_metrics_url = "https://tunaos.org/metrics"\n',
     'countme_endpoint = ""\n'),
    ('remote_url = "https://tunaos.org/flatpak/tuna-os.flatpakrepo"\n',
     'remote_url = "https://acme.example/flatpak/acme.flatpakrepo"\n'),
    ('codename = "Thunnus albacares"\nbranding = { accent = "#FFC702", gnome_accent = "yellow",',
     'codename = "Wile E"\nbranding = { accent = "#E87D0D", gnome_accent = "orange",'),
    ('platforms = ["linux/amd64", "linux/amd64/v2", "linux/arm64"]\n\n[[variants.yellowfin.flavors]]',
     'platforms = ["linux/amd64", "linux/amd64/v2", "linux/arm64"]\n\n[variants.yellowfin.packages]\nadd = ["tree"]\n\n[[variants.yellowfin.flavors]]'),
    ('platforms = ["linux/amd64", "linux/arm64"]\n\n[[variants.grouper.flavors]]',
     'platforms = ["linux/amd64", "linux/arm64"]\n\n[variants.grouper.packages]\nadd = ["htop"]\n\n[[variants.grouper.flavors]]'),
    ('  { id = "org.mozilla.firefox", branch = "stable" },\n]',
     '  { id = "org.mozilla.firefox", branch = "stable" },\n  { id = "org.gnome.Calculator", branch = "stable" },\n]'),
)


def fork_root(tmp_path, edits=()):
    """A checkout holding only tunaos.toml and the committed generated files."""
    text = (ROOT / "tunaos.toml").read_text(encoding="utf-8")
    for old, new in edits:
        assert text.count(old) == 1, old
        text = text.replace(old, new)
    (tmp_path / "tunaos.toml").write_text(text, encoding="utf-8")
    for relative in GENERATED:
        (tmp_path / relative).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, tmp_path / relative)
    return tmp_path


def run_config(root, *arguments):
    return subprocess.run([sys.executable, str(ROOT / "scripts/config.py"), *arguments, "--root", str(root)],
                          capture_output=True, text=True)


def test_generate_all_reproduces_every_committed_file_on_stock(tmp_path):
    """Stock parity: the one command a fork runs writes exactly what TunaOS commits."""
    shutil.copyfile(ROOT / "tunaos.toml", tmp_path / "tunaos.toml")
    for directory in ("build_scripts/lib", "build_scripts/desktop", "docs", ".github"):
        (tmp_path / directory).mkdir(parents=True)
    result = run_config(tmp_path, "generate-all")
    assert result.returncode == 0, result.stderr
    written = {p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*") if p.is_file()} - {"tunaos.toml"}
    assert set(GENERATED) <= written
    assert any(name.startswith("manifests/desktops/") for name in written)
    for relative in sorted(written):
        assert (tmp_path / relative).read_bytes() == (ROOT / relative).read_bytes(), relative


def test_a_forks_drift_error_names_the_command_that_fixes_it(tmp_path):
    root = fork_root(tmp_path, ACME_EDITS)
    for check in CHECKS:
        failing = run_config(root, check)
        if failing.returncode == 0:
            continue  # this edit did not change that file
        assert failing.stderr.startswith("ERROR:"), failing.stderr
        assert "python3 scripts/config.py generate" in failing.stderr, (check, failing.stderr)
    drifted = [c for c in CHECKS if run_config(root, c).returncode]
    assert {"check-identity", "check-variant-identity", "check-image-packages", "check-flatpak-policy", "check-builder-config"} <= set(drifted)
    result = run_config(root, "generate-all")
    assert result.returncode == 0, result.stderr
    for check in CHECKS:
        assert run_config(root, check).returncode == 0, check
    identity = (root / "build_scripts/lib/identity.env").read_text(encoding="utf-8")
    assert "TUNAOS_PROJECT_NAME='Acme OS'" in identity and "TUNAOS_PROJECT_ID=acmeos" in identity
    packages = (root / "build_scripts/lib/image-packages.tsv").read_text(encoding="utf-8")
    assert "yellowfin\tdnf\tadd\ttree\n" in packages and "grouper\tapt\tadd\thtop\n" in packages
    assert "org.gnome.Calculator" in (root / "build_scripts/desktop/flatpak-preinstall.tsv").read_text(encoding="utf-8")


def test_generate_all_refuses_a_single_output_file(tmp_path):
    root = fork_root(tmp_path)
    result = subprocess.run([sys.executable, str(ROOT / "scripts/config.py"), "generate-all", "--root", str(root),
                             "--output", str(tmp_path / "one-file")], capture_output=True, text=True)
    assert result.returncode == 2
    assert "generate-all writes every generated file in place" in result.stderr


def stock():
    return copy.deepcopy(config.load())


def prune_to(document, keep):
    """What deleting every other variant's tables from tunaos.toml leaves behind."""
    for name in [n for n in document["variants"] if n not in keep]:
        del document["variants"][name]
        document["tuna_rollout"].pop(name, None)
    return document


def test_pruning_variants_names_the_flavor_metadata_to_remove():
    with pytest.raises(config.ConfigError) as error:
        config.validate(prune_to(stock(), ("yellowfin", "grouper")))
    message = str(error.value)
    assert "flavor_metadata must cover exact primary flavor IDs" in message
    assert "remove ['cosmic-cachyos'" in message and "'pantheon'" in message
    assert "missing []" in message


def test_a_missing_flavor_metadata_table_is_named():
    document = stock()
    del document["flavor_metadata"]["gnome-asahi"]
    with pytest.raises(config.ConfigError, match=r"missing \['gnome-asahi'\]; remove \[\]"):
        config.validate(document)


def test_pruning_walks_to_a_valid_file_one_named_table_at_a_time():
    """The documented removal checklist, applied in the order the validator asks for it."""
    keep = ("yellowfin", "grouper")
    document = prune_to(stock(), keep)
    surviving = {f["id"] for v in document["variants"].values() for f in v["flavors"]}
    document["flavor_metadata"] = {k: v for k, v in document["flavor_metadata"].items() if k in surviving}
    with pytest.raises(config.ConfigError) as error:
        config.validate(document)
    assert "iso_builder.selection.facets 'base' lists ['albacore'" in str(error.value)
    facets = {facet["id"]: facet for facet in document["iso_builder"]["selection"]["facets"]}
    facets["base"]["values"] = [v for v in facets["base"]["values"] if v["id"] in keep]
    with pytest.raises(config.ConfigError) as error:
        config.validate(document)
    assert "iso_builder.selection.facets 'edition' lists ['cachyos', 't2']" in str(error.value)
    metadata = document["flavor_metadata"].values()
    for facet, used in (("desktop", {m["desktop"] for m in metadata}), ("edition", {m["edition"] for m in metadata})):
        facets[facet]["values"] = [v for v in facets[facet]["values"] if v["id"] in used]
    with pytest.raises(config.ConfigError) as error:
        config.validate(document)
    assert "package_catalogs: debian-trixie: catalog refers to unknown variant 'flounder'" in str(error.value)
    document["package_catalogs"] = {}
    config.validate(document)


def test_a_default_leaf_that_no_longer_exists_is_named():
    document = stock()
    document["iso_builder"]["default_selection"]["leaf_id"] = "yellowfin:gnome:linux/riscv64"
    with pytest.raises(config.ConfigError, match=r"'yellowfin:gnome:linux/riscv64' \(iso_builder default_selection"):
        config.validate(document)


def test_a_default_leaf_hidden_by_a_facet_names_the_value():
    document = stock()
    facets = {facet["id"]: facet for facet in document["iso_builder"]["selection"]["facets"]}
    facets["platform"]["values"] = [v for v in facets["platform"]["values"] if v["id"] != "linux/amd64/v2"]
    with pytest.raises(config.ConfigError, match=r"do not list \['platform=linux/amd64/v2'\]"):
        config.validate(document)


def test_an_unknown_key_error_does_not_print_an_empty_missing_list():
    document = stock()
    document["variants"]["yellowfin"]["packages"] = {"adds": ["tree"]}
    with pytest.raises(config.ConfigError) as error:
        config.validate(document)
    assert str(error.value).endswith("variants.yellowfin.packages: unknown keys ['adds']")


def test_a_shared_package_that_one_variant_cannot_install_blames_defaults_not_the_variant():
    document = stock()
    document["defaults"]["packages"] = {"add": ["htop"]}
    with pytest.raises(config.ConfigError) as error:
        config.image_packages(document)
    message = str(error.value)
    assert message.startswith("defaults.packages: 'htop' is not a valid package name for emerge")
    assert "variant guppy builds with" in message and "(use category/name)" in message
    assert "[defaults.packages] reaches every variant" in message


def test_a_variant_package_error_still_blames_the_variant():
    document = stock()
    document["variants"]["grouper"]["packages"] = {"add": ["Htop"]}
    with pytest.raises(config.ConfigError, match=r"^variants.grouper.packages: 'Htop' is not a valid package name for apt"):
        config.image_packages(document)


@pytest.mark.parametrize("mutate, expected", [
    (lambda p: p["common"].append({"id": "Calculator", "branch": "stable"}),
     "flatpak_preinstall.common[2] ('Calculator'): invalid Flatpak app ID"),
    (lambda p: p["common"].append({"id": "org.gnome.Calculator", "branch": "beta"}),
     "flatpak_preinstall.common[2] ('org.gnome.Calculator'): branch 'beta' is not supported"),
    (lambda p: p["common"].append({"id": "org.mozilla.firefox", "branch": "stable"}),
     "flatpak_preinstall.common[2] ('org.mozilla.firefox'): duplicate app declaration"),
    (lambda p: p["desktop_additions"].update(gnomee=[]),
     "flatpak_preinstall.desktop_additions.gnomee: unknown desktop"),
    (lambda p: p["desktop_additions"]["gnome"].append({"id": "org.mozilla.firefox", "branch": "stable"}),
     "flatpak_preinstall.desktop_additions.gnome: duplicates an app already in flatpak_preinstall.common: ['org.mozilla.firefox']"),
])
def test_a_bad_flatpak_entry_says_where_and_which(mutate, expected):
    document = stock()
    mutate(document["flatpak_preinstall"])
    with pytest.raises(config.ConfigError) as error:
        config.validate(document)
    assert expected in str(error.value)


def test_the_checker_names_its_missing_dependency_instead_of_a_traceback():
    script = (f"import sys, runpy; sys.modules['uharfbuzz'] = None; sys.argv = ['check-artwork.py']; "
              f"runpy.run_path({str(ROOT / 'scripts/branding/check-artwork.py')!r}, run_name='__main__')")
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)
    assert result.returncode == 1
    assert "Artwork generation needs " in result.stderr and "uharfbuzz" in result.stderr.splitlines()[0]
    assert "-m pip install -r requirements-branding.txt" in result.stderr
    assert "Traceback" not in result.stderr


def test_a_failed_generator_leaves_committed_artwork_untouched(tmp_path, monkeypatch, capsys):
    """--write used to delete the committed marks first; a fork's emoji without a drawing then lost them all."""
    share = tmp_path / "share"
    for name in checker.SETS:
        (share / name).mkdir(parents=True)
        (share / name / "yellowfin.svg").write_text("committed")
    monkeypatch.setattr(checker, "SHARE", share)
    monkeypatch.setattr(checker, "REPO", tmp_path)
    monkeypatch.setattr(checker, "missing_requirements", lambda: [])

    def failing_generator(root):
        raise subprocess.CalledProcessError(1, [sys.executable, "make-logos.py"])

    monkeypatch.setattr(checker, "generate", failing_generator)
    monkeypatch.setattr(sys, "argv", ["check-artwork.py", "--write"])
    assert checker.main() == 1
    assert "make-logos.py failed (see above); committed artwork is unchanged." in capsys.readouterr().err
    for name in checker.SETS:
        assert (share / name / "yellowfin.svg").read_text() == "committed"


def test_write_replaces_committed_artwork_only_after_generation_succeeds(tmp_path, monkeypatch, capsys):
    share = tmp_path / "share"
    for name in checker.SETS:
        (share / name).mkdir(parents=True)
        (share / name / "stale.svg").write_text("stale")
    monkeypatch.setattr(checker, "SHARE", share)
    monkeypatch.setattr(checker, "REPO", tmp_path)
    monkeypatch.setattr(checker, "missing_requirements", lambda: [])

    def generator(root):
        for name in checker.SETS:
            (root / name).mkdir()
            (root / name / "fresh.svg").write_text("fresh")

    monkeypatch.setattr(checker, "generate", generator)
    monkeypatch.setattr(sys, "argv", ["check-artwork.py", "--write"])
    assert checker.main() == 0
    for name in checker.SETS:
        assert sorted(p.name for p in (share / name).iterdir()) == ["fresh.svg"]


def test_every_stock_wrapper_belongs_to_a_stock_variant():
    ids = {variant["id"] for variant in config.matrix(config.load())["variants"]}
    assert workflows.orphan_wrappers(ROOT / ".github/workflows", ids) == []


def test_a_wrapper_for_a_removed_variant_is_reported_and_shared_workflows_are_not(tmp_path):
    """Pruning guppy from tunaos.toml leaves build-guppy.yml, with its nightly cron, behind."""
    for name in ("build-guppy.yml", "build-yellowfin.yml", "build-flavor.yml", "build-variant.yml"):
        shutil.copyfile(ROOT / ".github/workflows" / name, tmp_path / name)
    ids = {variant["id"] for variant in config.matrix(config.load())["variants"]} - {"guppy"}
    assert [p.name for p in workflows.orphan_wrappers(tmp_path, ids)] == ["build-guppy.yml"]


def test_wrapper_detection_does_not_depend_on_yaml_formatting(tmp_path):
    """Double quotes, key order and extra keys must not hide a wrapper for a removed variant."""
    (tmp_path / "build-guppy.yml").write_text(
        'name: Build guppy\njobs:\n  build:\n    with:\n      variant: "guppy"\n      extra: 1\n'
        '    uses: ./.github/workflows/build-variant.yml\n    secrets: inherit\n', encoding="utf-8")
    (tmp_path / "build-flavor.yml").write_text(
        "jobs:\n  build:\n    uses: ./.github/workflows/build-variant.yml\n    with:\n"
        "      variant: ${{ inputs.variant }}\n", encoding="utf-8")
    assert [p.name for p in workflows.orphan_wrappers(tmp_path, {"yellowfin"})] == ["build-guppy.yml"]
    assert workflows.orphan_wrappers(tmp_path, {"yellowfin", "guppy"}) == []


def test_a_wrapper_that_is_not_valid_yaml_is_reported_not_skipped(tmp_path):
    (tmp_path / "build-guppy.yml").write_text("jobs: [unclosed\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="build-guppy.yml: not valid YAML"):
        workflows.orphan_wrappers(tmp_path, {"yellowfin"})
