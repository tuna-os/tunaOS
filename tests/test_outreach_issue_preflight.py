"""The outreach preflight must search delivered work and the full issue history."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check-outreach-duplicate.sh"


def _fake_gh(tmp_path: Path) -> tuple[Path, Path]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    args_file = tmp_path / "gh-args"
    gh = bin_dir / "gh"
    gh.write_text(
        "#!/bin/sh\n"
        'printf "%s\\n" "$@" > "$GH_ARGS"\n'
        'printf "%s" "${GH_OUTPUT:-}"\n'
    )
    gh.chmod(0o755)
    return bin_dir, args_file


def _run(tmp_path: Path, query: str, gh_output: str = "") -> subprocess.CompletedProcess[str]:
    bin_dir, args_file = _fake_gh(tmp_path)
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bin_dir}:{env['PATH']}",
            "GH_ARGS": str(args_file),
            "GH_OUTPUT": gh_output,
        }
    )
    return subprocess.run(
        [str(SCRIPT), query],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_preflight_blocks_material_already_in_the_outreach_ledger(tmp_path: Path) -> None:
    result = _run(tmp_path, "CNCF / bootc showcase")

    assert result.returncode == 1
    assert "ADOPTION-OUTREACH-STATUS.md" in result.stdout
    assert "canonical tracker" in result.stdout


def test_preflight_blocks_an_issue_match_and_searches_open_and_closed(tmp_path: Path) -> None:
    result = _run(
        tmp_path,
        "unique campaign phrase",
        "#123 [CLOSED] unique campaign phrase — https://example.invalid/123\n",
    )

    assert result.returncode == 1
    assert "#123 [CLOSED]" in result.stdout
    args = (tmp_path / "gh-args").read_text().splitlines()
    assert args[args.index("--state") + 1] == "all"
    assert args[args.index("--label") + 1] == "outreach"
    assert "unique campaign phrase in:title" in args


def test_preflight_allows_a_target_with_no_existing_evidence(tmp_path: Path) -> None:
    result = _run(tmp_path, "target-with-no-existing-evidence-2792")

    assert result.returncode == 0
    assert "No matching ledger row" in result.stdout
