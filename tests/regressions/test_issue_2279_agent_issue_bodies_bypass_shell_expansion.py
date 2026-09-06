"""tunaOS#2279: an agent-filed issue publicly shipped an environment dump.

The body recovered from tuna-os/corral#217 measured the failure: an agent put
Markdown in a double-quoted ``--body`` argument, and its backticks ran ``env``.
This test holds the actual documented command to literal stdin transport so a
later simplification cannot silently restore credential exposure.
"""

from __future__ import annotations

import os
import re
import subprocess
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GUIDE = ROOT / "docs" / "agents" / "issue-tracker.md"


def _create_example() -> str:
    body = GUIDE.read_text(encoding="utf-8")
    match = re.search(r"```bash\n(\s+gh issue create .*?\n\s+EOF)\n\s+```", body, re.DOTALL)
    assert match, "the agent guide must include an executable safe creation example"
    return textwrap.dedent(match.group(1))


def test_documented_create_command_preserves_shell_syntax_literally(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_gh = fake_bin / "gh"
    fake_gh.write_text(
        "#!/bin/sh\nprintf '%s\\n' \"$@\" > \"$CAPTURE_ARGS\"\ncat > \"$CAPTURE_BODY\"\n"
    )
    fake_gh.chmod(0o755)
    captured_body = tmp_path / "body"
    captured_args = tmp_path / "args"
    env = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "GH_TOKEN": "credential-that-must-not-be-expanded",
        "CAPTURE_BODY": str(captured_body),
        "CAPTURE_ARGS": str(captured_args),
    }

    subprocess.run(["bash", "-eu", "-c", _create_example()], env=env, check=True)

    body = captured_body.read_text()
    assert "`env`" in body
    assert "$GH_TOKEN" in body
    assert "$(command)" in body
    assert env["GH_TOKEN"] not in body
    assert captured_args.read_text().splitlines()[-2:] == ["--body-file", "-"]


def test_agent_docs_never_recommend_inline_markdown_arguments() -> None:
    offenders = []
    unsafe = re.compile(
        r"\bgh\s+issue\s+(?:create|comment|edit)\b.*\s--body(?:=|\s)"
        r"|\bgh\s+issue\s+close\b.*\s--comment(?:=|\s)"
    )
    for path in sorted((ROOT / "docs" / "agents").glob("*.md")):
        for line_number, line in enumerate(path.read_text().splitlines(), 1):
            if unsafe.search(line):
                offenders.append(f"{path.relative_to(ROOT)}:{line_number}: {line.strip()}")
    assert not offenders, "Markdown must use --body-file, never a shell argument:\n" + "\n".join(offenders)


def test_safety_rule_names_every_expansion_form() -> None:
    guide = GUIDE.read_text()
    assert "<<'EOF'" in guide
    for dangerous in ("Backticks", "$(...)", "$VARIABLE"):
        assert dangerous in guide
