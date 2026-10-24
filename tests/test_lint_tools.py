from __future__ import annotations

import importlib.util
import json
import stat
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "toolchain" / "lint-tools.json"
SCRIPT = ROOT / "scripts" / "lint_tools.py"

spec = importlib.util.spec_from_file_location("lint_tools", SCRIPT)
assert spec and spec.loader
lint_tools = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lint_tools)


def _contract() -> dict:
    return lint_tools._load_contract(CONTRACT)


def _fake_tool(path: Path, output: str) -> None:
    path.write_text(f"#!/bin/sh\nprintf '%s\\n' '{output}'\n", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _matching_tool_dir(tmp_path: Path) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    outputs = {
        # Verbatim first lines of the real `actionlint -version` (1.7.12,
        # release asset): the version is a bare line, not "actionlint version".
        "actionlint": "1.7.12\ninstalled by downloading from release page",
        "shellcheck": "ShellCheck\nversion: 0.11.0",
        "just": "just 1.59.0",
        "shfmt": "v3.14.1",
    }
    for name, output in outputs.items():
        _fake_tool(tmp_path / name, output)
    return tmp_path


def test_reviewed_contract_covers_every_supported_host() -> None:
    contract = _contract()

    assert tuple(contract["tools"]) == lint_tools.REQUIRED_TOOLS
    for tool in contract["tools"].values():
        assert set(tool["assets"]) == set(contract["platforms"])
        for asset in tool["assets"].values():
            assert len(asset["sha256"]) == 64
            int(asset["sha256"], 16)
            assert lint_tools._release_url(tool, asset).startswith(
                f"https://github.com/{tool['repository']}/releases/download/"
            )


def test_matching_versions_are_accepted(tmp_path: Path, capsys) -> None:
    lint_tools.verify(_contract(), _matching_tool_dir(tmp_path))

    output = capsys.readouterr().out
    assert "actionlint 1.7.12" in output
    assert "shellcheck 0.11.0" in output
    assert "just 1.59.0" in output
    assert "shfmt 3.14.1" in output


def test_explicit_bin_dir_never_falls_back_to_path(
    tmp_path: Path, monkeypatch
) -> None:
    """An incomplete install must fail even when PATH has a matching copy."""
    on_path = _matching_tool_dir(tmp_path / "path")
    monkeypatch.setenv("PATH", str(on_path))
    install_dir = _matching_tool_dir(tmp_path / "install")
    (install_dir / "shfmt").unlink()

    with pytest.raises(lint_tools.ContractError) as raised:
        lint_tools.verify(_contract(), install_dir)

    assert f"shfmt: missing in {install_dir}" in str(raised.value)


def test_wrong_version_fails_with_expected_and_observed_values(tmp_path: Path) -> None:
    tools = _matching_tool_dir(tmp_path)
    _fake_tool(tools / "actionlint", "1.7.7")

    with pytest.raises(lint_tools.ContractError) as raised:
        lint_tools.verify(_contract(), tools)

    message = str(raised.value)
    assert "actionlint: expected 1.7.12, got 1.7.7" in message
    assert "Run 'just setup'" in message


def test_install_rejects_an_asset_with_the_wrong_digest(
    tmp_path: Path, monkeypatch
) -> None:
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    monkeypatch.setattr(lint_tools, "_host_platform", lambda: "linux-x86_64")
    monkeypatch.setattr(lint_tools, "_download", lambda _url, _output: "0" * 64)

    with pytest.raises(lint_tools.ContractError, match="SHA-256 mismatch"):
        lint_tools.install(contract, tmp_path)

    assert not any(tmp_path.iterdir())


def test_homebrew_shfmt_version_format_is_accepted(tmp_path: Path) -> None:
    """Release assets print `v3.14.1`; the Homebrew build prints `3.14.1`.

    Both are shfmt 3.14.1. Rejecting the second reported
    "expected 3.14.1, got 3.14.1", which is a contract bug, not drift.
    """
    tools = _matching_tool_dir(tmp_path)
    _fake_tool(tools / "shfmt", "3.14.1")

    lint_tools.verify(_contract(), tools)
