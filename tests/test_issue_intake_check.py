"""Bot-filed placeholder issues must be caught; real findings must not be.

TRIAGE-POLICY.md section 1 (#2133) admits an automated finding only when it
has no unresolved template text and a body worth reading. After the policy
merged, #2406, #2407 and #2509 still arrived as unfilled templates, so
scripts/check-issue-intake.py checks them on arrival. These cases use the
real shapes from that queue.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check-issue-intake.py"
WORKFLOW = ROOT / ".github" / "workflows" / "issue-intake-check.yml"

FOOTER = """
---
*Filed by sec-check agent (ACMM L6 — full mode)*
---
🐝 **Hive Agent**: `security` | **Instance:** `hive-school-tunaos` | **SHA:** `unknown`

— hive: agent=sec-check backend=codex model=gpt-5.6-sol codex=0.146.0
"""

PLACEHOLDER_2406 = """## Security Finding

**Severity**: critical/high/medium/low
**Type**: <CVE/secret-exposure/permission-issue/unsafe-pattern>

<description of the vulnerability>

## Impact

<what an attacker could do, what data is at risk>
""" + FOOTER

REAL_FINDING = """## Security Finding

`ddiFetcher.open` accepts any base that starts with `http://`. Verified
2026-10-02 against main at abc1234: `<details>` and <https://example.com>
and <a href="x">link</a> are HTML, not template text.

```text
Usage: tool <input file> <output dir>
```

## Recommendation

Reject `http://` bases and add a regression test.
""" + FOOTER


def _check(tmp_path: Path, title: str, body: str) -> subprocess.CompletedProcess:
    body_file = tmp_path / "body.md"
    body_file.write_text(body, encoding="utf-8")
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--title", title, "--body-file", str(body_file)],
        capture_output=True, text=True,
    )


def test_a_placeholder_title_and_body_are_caught(tmp_path: Path) -> None:
    result = _check(
        tmp_path, "[sec-check] <specific description of the vulnerability>", PLACEHOLDER_2406
    )
    assert result.returncode == 1
    assert "title has template text `<specific description of the vulnerability>`" in result.stdout
    assert "`<CVE/secret-exposure/permission-issue/unsafe-pattern>`" in result.stdout
    assert "`<description of the vulnerability>`" in result.stdout


def test_a_footer_only_body_is_caught(tmp_path: Path) -> None:
    """#2133 itself was filed with nothing above the hive footer."""
    result = _check(tmp_path, "[strategist] Automation intake lacks quality gate", FOOTER)
    assert result.returncode == 1
    assert "body is empty apart from the hive footer" in result.stdout


def test_a_real_finding_passes(tmp_path: Path) -> None:
    """HTML tags, autolinks and angle brackets inside code are not template text."""
    result = _check(tmp_path, "[sec-check] http:// base accepted by ddiFetcher", REAL_FINDING)
    assert result.returncode == 0, result.stdout
    assert result.stdout == ""


def test_the_workflow_never_closes_and_never_interpolates_untrusted_text() -> None:
    """The policy forbids automated closure; title and body are attacker-controlled."""
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "gh issue close" not in text
    assert "state=closed" not in text
    doc = yaml.safe_load(text)
    for step in doc["jobs"]["check"]["steps"]:
        run = step.get("run", "")
        assert "github.event.issue.title" not in run
        assert "github.event.issue.body" not in run
