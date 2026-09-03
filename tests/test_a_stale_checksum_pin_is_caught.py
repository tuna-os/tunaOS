#!/usr/bin/env python3
"""Unit tests for scripts/check-download-checksums.py.

The script exists because Renovate can bump a pinned version and cannot bump
the sibling `_sha256` map, which is how chezmoi ended up pinned at v2.72.0
with v2.71.0's hashes. check-download-checksums.yml runs it on every PR that
touches image-versions.yaml or install-remora.sh, and nightly.

The gate had no tests of its own. Its failure mode is the quiet one: a regex
that stops matching, or a checksums file whose format shifts, makes the
script exit non-zero for a reason that has nothing to do with a stale pin --
or, worse, a `--fix` that rewrites the wrong span of the file it is editing.

Nothing here reaches the network: `fetch_published` is the module's only
door outside and it is either mocked at `urllib.request.urlopen` (to pin the
parsing of a published checksums.txt) or replaced wholesale (to drive
`main`). The two real pins in PINS are exercised against fixture copies of
the files they read, so a rename of REMORA_SHA256 or of the chezmoi mapping
key fails here rather than in CI.
"""

from __future__ import annotations

import importlib.util
import io
import sys
import urllib.error
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "check-download-checksums.py"
_spec = importlib.util.spec_from_file_location("check_download_checksums", _SCRIPT)
cdc = importlib.util.module_from_spec(_spec)
sys.modules["check_download_checksums"] = cdc
_spec.loader.exec_module(cdc)

A = "a" * 64
B = "b" * 64
C = "c" * 64

REMORA_SH = f"""\
#!/usr/bin/env bash
REMORA_VERSION="v0.4.2"
case "$ARCH" in
amd64) REMORA_SHA256="{A}" ;;
arm64) REMORA_SHA256="{B}" ;;
esac
"""

VERSIONS_YAML = f"""\
versions:
  chezmoi: "v2.72.0"
chezmoi_sha256:
  amd64: "{A}"
  arm64: "{B}"
"""


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """A tree holding the two real pinned files, with REPO_ROOT pointed at it."""
    (tmp_path / "build_scripts").mkdir()
    (tmp_path / "build_scripts" / "install-remora.sh").write_text(REMORA_SH)
    (tmp_path / "image-versions.yaml").write_text(VERSIONS_YAML)
    monkeypatch.setattr(cdc, "REPO_ROOT", tmp_path)
    return tmp_path


def pin(name: str) -> cdc.Pin:
    return next(p for p in cdc.PINS if p.name == name)


# ── The regexes, against the shapes the real files use ──────────────────────

@pytest.mark.parametrize("name,expected", [("remora", "v0.4.2"), ("chezmoi", "v2.72.0")])
def test_the_version_regex_finds_the_pinned_tag(repo, name, expected):
    assert cdc.find_version(pin(name)) == expected


@pytest.mark.parametrize("name", ["remora", "chezmoi"])
@pytest.mark.parametrize("arch,expected", [("amd64", A), ("arm64", B)])
def test_the_checksum_regex_finds_each_arch(repo, name, arch, expected):
    _, pinned = cdc.find_checksum(pin(name), arch)
    assert pinned == expected


def test_a_missing_version_is_a_named_failure_not_a_traceback(repo):
    (repo / "image-versions.yaml").write_text("versions:\n  something-else: \"v1\"\n")

    with pytest.raises(SystemExit) as exc:
        cdc.find_version(pin("chezmoi"))
    assert "could not find chezmoi's version" in str(exc.value)


def test_a_missing_checksum_is_a_named_failure(repo):
    (repo / "build_scripts" / "install-remora.sh").write_text('REMORA_VERSION="v0.4.2"\n')

    with pytest.raises(SystemExit) as exc:
        cdc.find_checksum(pin("remora"), "amd64")
    assert "could not find remora's amd64 checksum" in str(exc.value)


def test_a_64_hex_hash_is_required(repo):
    """A truncated or placeholder hash must not be accepted as a pin."""
    (repo / "build_scripts" / "install-remora.sh").write_text(
        'REMORA_VERSION="v0.4.2"\namd64) REMORA_SHA256="deadbeef" ;;\n'
    )

    with pytest.raises(SystemExit):
        cdc.find_checksum(pin("remora"), "amd64")


# ── fetch_published: parsing a real checksums.txt, and its error doors ───────

class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


def test_published_checksums_are_parsed_into_asset_to_hash(monkeypatch):
    body = f"{A}  remora-linux-amd64\n{B}  remora-linux-arm64\n"
    monkeypatch.setattr(cdc.urllib.request, "urlopen", lambda *a, **k: _Resp(body.encode()))

    assert cdc.fetch_published(pin("remora"), "v0.4.2") == {
        "remora-linux-amd64": A,
        "remora-linux-arm64": B,
    }


def test_the_binary_star_marker_is_stripped(monkeypatch):
    """sha256sum -b writes `<hash> *<file>`; goreleaser output varies."""
    body = f"{A} *chezmoi_2.72.0_linux_amd64.deb\n"
    monkeypatch.setattr(cdc.urllib.request, "urlopen", lambda *a, **k: _Resp(body.encode()))

    got = cdc.fetch_published(pin("chezmoi"), "v2.72.0")
    assert got == {"chezmoi_2.72.0_linux_amd64.deb": A}


def test_lines_that_are_not_hash_and_name_are_ignored(monkeypatch):
    body = f"# a header comment\n\n{A}  remora-linux-amd64\ngarbage with three fields here\n"
    monkeypatch.setattr(cdc.urllib.request, "urlopen", lambda *a, **k: _Resp(body.encode()))

    assert cdc.fetch_published(pin("remora"), "v0.4.2") == {"remora-linux-amd64": A}


def test_the_url_substitutes_both_the_tag_and_the_bare_number(monkeypatch):
    """chezmoi's checksums file is named by the version without its `v`."""
    seen = {}

    def _urlopen(url, timeout=None):
        seen["url"] = url
        return _Resp(b"")

    monkeypatch.setattr(cdc.urllib.request, "urlopen", _urlopen)
    cdc.fetch_published(pin("chezmoi"), "v2.72.0")

    assert seen["url"].endswith("/download/v2.72.0/chezmoi_2.72.0_checksums.txt")


def test_a_404_says_the_release_may_not_exist(monkeypatch):
    def _raise(*a, **k):
        raise urllib.error.HTTPError("u", 404, "Not Found", {}, None)

    monkeypatch.setattr(cdc.urllib.request, "urlopen", _raise)

    with pytest.raises(SystemExit) as exc:
        cdc.fetch_published(pin("remora"), "v9.9.9")
    assert "(404)" in str(exc.value)
    assert "does not exist" in str(exc.value)


def test_an_unreachable_host_is_reported_as_such(monkeypatch):
    def _raise(*a, **k):
        raise urllib.error.URLError("name resolution failed")

    monkeypatch.setattr(cdc.urllib.request, "urlopen", _raise)

    with pytest.raises(SystemExit) as exc:
        cdc.fetch_published(pin("remora"), "v0.4.2")
    assert "cannot reach" in str(exc.value)


# ── main(): the verdicts, and what --fix writes ─────────────────────────────

@pytest.fixture
def published(monkeypatch):
    """Replace the network door with a per-pin dict of asset -> hash."""
    table: dict[str, dict[str, str]] = {}
    monkeypatch.setattr(cdc, "fetch_published", lambda p, v: table[p.name])
    return table


@pytest.fixture
def only_remora(monkeypatch):
    monkeypatch.setattr(cdc, "PINS", [pin("remora")])


def test_matching_pins_exit_zero(repo, published, only_remora, capsys, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["check-download-checksums.py"])
    published["remora"] = {"remora-linux-amd64": A, "remora-linux-arm64": B}

    assert cdc.main() == 0
    out = capsys.readouterr().out
    assert "all checksum pins match" in out
    assert out.count("ok   remora") == 2


def test_a_stale_pin_fails_and_names_the_fix(repo, published, only_remora, capsys, monkeypatch):
    """The Renovate case: the version moved, the hash did not."""
    monkeypatch.setattr(sys, "argv", ["check-download-checksums.py"])
    published["remora"] = {"remora-linux-amd64": C, "remora-linux-arm64": B}

    assert cdc.main() == 1
    out = capsys.readouterr().out
    assert "FAIL remora amd64" in out
    assert "--fix" in out
    # The file is untouched without --fix.
    assert A in (repo / "build_scripts" / "install-remora.sh").read_text()


def test_an_asset_that_no_longer_exists_is_its_own_failure(
    repo, published, only_remora, capsys, monkeypatch
):
    """Upstream renaming its assets must not read as a checksum mismatch."""
    monkeypatch.setattr(sys, "argv", ["check-download-checksums.py"])
    published["remora"] = {"remora_linux_amd64": A, "remora-linux-arm64": B}

    assert cdc.main() == 1
    out = capsys.readouterr().out
    assert "publishes no asset named remora-linux-amd64" in out
    assert "naming may have changed upstream" in out


def test_fix_rewrites_only_the_hash_and_leaves_the_file_intact(
    repo, published, only_remora, capsys, monkeypatch
):
    monkeypatch.setattr(sys, "argv", ["check-download-checksums.py", "--fix"])
    published["remora"] = {"remora-linux-amd64": C, "remora-linux-arm64": B}

    assert cdc.main() == 0
    text = (repo / "build_scripts" / "install-remora.sh").read_text()
    assert f'amd64) REMORA_SHA256="{C}" ;;' in text
    # Everything else survives: the other arch, the version, the shell syntax.
    assert f'arm64) REMORA_SHA256="{B}" ;;' in text
    assert 'REMORA_VERSION="v0.4.2"' in text
    assert text.startswith("#!/usr/bin/env bash")
    assert "rewrote 1 checksum" in capsys.readouterr().out


def test_fix_rewrites_the_yaml_mapping_without_disturbing_it(repo, published, capsys, monkeypatch):
    """The same span-replacement has to work on YAML, not just a case arm."""
    monkeypatch.setattr(cdc, "PINS", [pin("chezmoi")])
    monkeypatch.setattr(sys, "argv", ["check-download-checksums.py", "--fix"])
    published["chezmoi"] = {
        "chezmoi_2.72.0_linux_amd64.deb": A,
        "chezmoi_2.72.0_linux_arm64.deb": C,
    }

    assert cdc.main() == 0
    text = (repo / "image-versions.yaml").read_text()
    assert f'  arm64: "{C}"' in text
    assert f'  amd64: "{A}"' in text
    assert '  chezmoi: "v2.72.0"' in text


def test_only_selects_a_single_pin(repo, published, capsys, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["check-download-checksums.py", "--only", "remora"])
    published["remora"] = {"remora-linux-amd64": A, "remora-linux-arm64": B}
    # chezmoi is left out of `published` entirely: touching it would KeyError.

    assert cdc.main() == 0
    out = capsys.readouterr().out
    assert "remora" in out
    assert "chezmoi" not in out
