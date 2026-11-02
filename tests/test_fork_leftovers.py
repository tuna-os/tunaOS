"""Fork-facing values that used to be written in code: Asahi sweeps, changelog links.

tunaos.toml and GITHUB_REPOSITORY are the sources; the stock repository must
keep exactly the output it had, and a fork's edit must change it. The guard at
the bottom fails on a new `tuna-os` / `tunaos.org` literal in these files unless
it is listed with the reason a fork keeps it.
"""
from __future__ import annotations

import importlib.util
import re
import shutil
import subprocess
import sys
import types
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parents[1]


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


config = load("fork_leftovers_config", "scripts/lib/tunaos_config.py")
generator = load("fork_leftovers_generator", "scripts/generate-workflows.py")

# The `flavor:` lists verify-asahi.yml and asahi-hw-nightly.yml held by hand.
STOCK_VERIFY = {"bonito", "grouper", "albacore", "yellowfin", "sailfin", "skipjack"}
STOCK_HARDWARE = {"bonito", "grouper"}


def stock():
    return config.load()


def listed(path):
    document = yaml.safe_load((ROOT / path).read_text(encoding="utf-8"))
    return document["jobs"]["sweep"]["strategy"]["matrix"]["flavor"]


# ── Asahi sweeps ─────────────────────────────────────────────────────────────

def test_stock_asahi_sweeps_are_the_lists_the_workflows_used_to_hold():
    variants = stock()["variants"]
    assert set(generator.asahi_sweep(variants, "asahi_verify")) == STOCK_VERIFY
    assert set(generator.asahi_sweep(variants, "asahi_hardware")) == STOCK_HARDWARE


@pytest.mark.parametrize("path,key,expected", (
    (".github/workflows/verify-asahi.yml", "asahi_verify", STOCK_VERIFY),
    (".github/workflows/asahi-hw-nightly.yml", "asahi_hardware", STOCK_HARDWARE)))
def test_committed_asahi_sweep_is_what_the_generator_writes(path, key, expected):
    text = (ROOT / path).read_text(encoding="utf-8")
    ids = generator.asahi_sweep(stock()["variants"], key)
    assert generator.with_asahi_sweep(text, ids) == text
    matrix = listed(path)
    assert set(matrix) == expected and len(matrix) == len(expected)


def test_every_asahi_sweep_variant_exists_and_hardware_is_a_subset_of_verify():
    variants = stock()["variants"]
    verify = set(generator.asahi_sweep(variants, "asahi_verify"))
    assert set(generator.asahi_sweep(variants, "asahi_hardware")) <= verify <= set(variants)


def test_asahi_rewrite_replaces_only_the_flavor_line():
    text = "a: 1\n        flavor: [x, y]\nb: 2\n"
    assert generator.with_asahi_sweep(text, ["p", "q"]) == "a: 1\n        flavor: [p, q]\nb: 2\n"
    for broken in ("a: 1\n", "        flavor: [x]\n        flavor: [y]\n"):
        with pytest.raises(ValueError, match="expected one"):
            generator.with_asahi_sweep(broken, ["p"])


@pytest.mark.parametrize("key", ("asahi_verify", "asahi_hardware"))
def test_asahi_keys_must_be_booleans(key):
    import copy
    document = copy.deepcopy(stock())
    document["variants"]["yellowfin"][key] = "yes"
    with pytest.raises(config.ConfigError, match=key):
        config.validate(document)


def test_asahi_keys_stay_out_of_the_build_matrix():
    for variant in config.matrix(stock())["variants"]:
        assert not {"asahi_verify", "asahi_hardware"} & set(variant)


def test_a_fork_edits_only_tunaos_toml_for_its_asahi_sweeps(tmp_path):
    """Run the real generator over a copy of the repository with an edited tunaos.toml."""
    shutil.copytree(ROOT / "scripts", tmp_path / "scripts", ignore=shutil.ignore_patterns("__pycache__"))
    (tmp_path / ".github/workflows").mkdir(parents=True)
    for name in ("build-flavor.yml", "verify-asahi.yml", "asahi-hw-nightly.yml"):
        shutil.copy(ROOT / ".github/workflows" / name, tmp_path / ".github/workflows" / name)
    edited = (ROOT / "tunaos.toml").read_text(encoding="utf-8")
    # Drop sailfin from the verify sweep; put albacore on the hardware sweep.
    edited = edited.replace('[variants.sailfin]\nemoji = "⛵"\nasahi_verify = true\n', '[variants.sailfin]\nemoji = "⛵"\n', 1)
    edited = edited.replace('[variants.albacore]\nemoji = "🐟"\nasahi_verify = true\n',
                            '[variants.albacore]\nemoji = "🐟"\nasahi_verify = true\nasahi_hardware = true\n', 1)
    assert edited != (ROOT / "tunaos.toml").read_text(encoding="utf-8")
    (tmp_path / "tunaos.toml").write_text(edited, encoding="utf-8")
    subprocess.run([sys.executable, "scripts/generate-workflows.py"], cwd=tmp_path, check=True, capture_output=True)

    verify = listed_in(tmp_path, "verify-asahi.yml")
    assert set(verify) == STOCK_VERIFY - {"sailfin"}
    assert set(listed_in(tmp_path, "asahi-hw-nightly.yml")) == STOCK_HARDWARE | {"albacore"}


def listed_in(root, name):
    document = yaml.safe_load((root / ".github/workflows" / name).read_text(encoding="utf-8"))
    return document["jobs"]["sweep"]["strategy"]["matrix"]["flavor"]


# ── Changelog commit links ───────────────────────────────────────────────────

def test_changelog_commit_links_follow_the_repository_being_released(monkeypatch):
    module = load("fork_leftovers_changelogs", ".github/changelogs.py")
    monkeypatch.setattr(module, "subprocess", types.SimpleNamespace(
        run=lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout=b"abc123def abc123d fix: a thing\n"),
        PIPE=subprocess.PIPE))
    labels = lambda rev: {"x": {"Labels": {"org.opencontainers.image.revision": rev}}}

    monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
    stock_text = module.get_commits(labels("a"), labels("b"), ".")
    assert stock_text == (
        "### Commits\n| Hash | Subject |\n| --- | --- |\n"
        "| **[abc123d](https://github.com/tuna-os/albacore-lts/commit/abc123def)** | fix: a thing |\n\n")

    monkeypatch.setenv("GITHUB_REPOSITORY", "acme/os")
    fork_text = module.get_commits(labels("a"), labels("b"), ".")
    assert "(https://github.com/acme/os/commit/abc123def)" in fork_text
    assert "tuna-os" not in fork_text


# ── Guard ────────────────────────────────────────────────────────────────────

# Files whose literals this guard owns: the release card, changelog and SBOM
# identity, the two Asahi sweeps, the builder VM and the recipes' sample args.
GUARDED = (
    ".github/workflows/generate-changelog-release.yml", ".github/changelogs.py",
    "scripts/packages_to_spdx.py", ".github/workflows/verify-asahi.yml",
    ".github/workflows/asahi-hw-nightly.yml", "tunaos-builder.yaml", "Justfile", "just/*.just",
)
LITERAL = re.compile(r"tuna-os|tunaos\.org", re.I)

# (file, text on the offending line) -> why a fork keeps it. Comments are not scanned.
ALLOWED = {
    (".github/changelogs.py", 'STOCK_COMMIT_REPOSITORY = "tuna-os/albacore-lts"'):
        "what the commit link was before it followed GITHUB_REPOSITORY; used only when that is unset "
        "(a local run), so stock output is byte-identical",
    ("tunaos-builder.yaml", "https://github.com/tuna-os/tunaos.git"):
        "a static VM definition: neither lima nor corral expands environment into it. "
        "scripts/corral-build.sh re-points origin to CORRAL_REPO/GITHUB_REPOSITORY before building; "
        "a lima-only fork edits this URL",
    ("tunaos-builder.yaml", "https://github.com/tuna-os/corral.git"):
        "corral is TunaOS's own build-cluster tool, a dependency a fork may keep, not the fork's repository",
}


def literal_lines():
    hits = []
    for pattern in GUARDED:
        for path in sorted(ROOT.glob(pattern)):
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if LITERAL.search(line) and not line.lstrip().startswith("#"):
                    hits.append((path.relative_to(ROOT).as_posix(), number, line.strip()))
    return hits


def unexplained(hits):
    return [hit for hit in hits if not any(hit[0] == name and needle in hit[2] for name, needle in ALLOWED)]


def test_no_new_tuna_os_literal_outside_the_allow_list():
    bad = unexplained(literal_lines())
    assert not bad, (
        "a TunaOS identity literal was written where a fork would have to edit it. Derive it from "
        "tunaos.toml, GITHUB_REPOSITORY(_OWNER) or scripts/publish-destination.sh, or allow-list it "
        "in tests/test_fork_leftovers.py with the reason:\n"
        + "\n".join(f"  {name}:{number}: {line}" for name, number, line in bad))


def test_every_allow_list_entry_still_matches_a_line():
    hits = literal_lines()
    stale = [entry for entry in ALLOWED if not any(entry[0] == name and entry[1] in line for name, _, line in hits)]
    assert not stale, f"allow-list entries that match no line: {stale}"


def test_the_guard_catches_a_new_literal():
    assert unexplained([("just/utilities.just", 1, "x=ghcr.io/tuna-os/foo")])
    assert unexplained([(".github/changelogs.py", 2, 'URL = "https://tunaos.org/docs"')])
    assert not unexplained([(".github/changelogs.py", 3, 'STOCK_COMMIT_REPOSITORY = "tuna-os/albacore-lts"')])
