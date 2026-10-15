#!/usr/bin/env python3
"""Flag an automation-filed issue that skipped the admission gate.

TRIAGE-POLICY.md section 1 (#2133) says an automated finding is admissible
only when it is complete: no unresolved template text and no empty body.
The policy merged on 2026-08-29 (#2134), but bot-filed placeholders kept
arriving after it -- #2406 and #2407 on 09-08, #2509 on 09-13 -- because a
written rule does not stop a run that never reads it. This is the backstop
on the receiving side.

Two signals, both cheap and both seen in the queue:

  * template text left in place: `<specific description of the
    vulnerability>`, `<component or package path>`,
    `<CVE/secret-exposure/permission-issue/unsafe-pattern>`;
  * a body that is only the hive footer (#2133 itself was filed that way).

This is a REPORT. The policy forbids automated closure, so the workflow
that calls this only labels and comments; a maintainer or the filing agent
decides what happens next.

Usage:
    TITLE=... BODY=... scripts/check-issue-intake.py
    scripts/check-issue-intake.py --title "..." --body-file body.md

Exit status: 0 when the issue passes, 1 when it has findings.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

# A template slot: letters first, then words joined by spaces, slashes or
# hyphens, and at least one separator. That excludes HTML (`<details>`,
# `<a href="...">`, `<br/>`) and autolinks (`<https://...>`), which have
# no space or carry `=`, `:` or quotes.
PLACEHOLDER = re.compile(r"<([A-Za-z][A-Za-z0-9,'-]*(?:[ /][A-Za-z0-9,'-]+)+)>")

# Code is quoted, not template text: a finding about a template may cite one.
FENCE = re.compile(r"^(```|~~~).*?^\1[^\n]*$", re.M | re.S)
INLINE_CODE = re.compile(r"`[^`\n]*`")

# The hive signature block: a rule, the agent banner, the backend line, and
# the "Filed by" credit. None of it is part of the finding.
FOOTER_LINE = re.compile(
    r"^\s*(?:-{3,}|\*Filed by .*\*|🐝 \*\*Hive Agent\*\*.*|— hive:.*)\s*$"
)

# Fewer characters than this, once the footer is gone, cannot hold the
# evidence and next step the policy asks for.
MIN_BODY_CHARS = 40


def _strip_code(text: str) -> str:
    return INLINE_CODE.sub("", FENCE.sub("", text))


def placeholders(text: str) -> list[str]:
    """Unresolved template slots in TEXT, in order, without duplicates."""
    seen: list[str] = []
    for match in PLACEHOLDER.finditer(_strip_code(text)):
        slot = f"<{match.group(1)}>"
        if slot not in seen:
            seen.append(slot)
    return seen


def substance(body: str) -> str:
    """BODY without the hive footer and blank lines."""
    lines = [line for line in body.splitlines() if not FOOTER_LINE.match(line)]
    return "\n".join(line for line in lines if line.strip()).strip()


def findings(title: str, body: str) -> list[str]:
    out = [f"title has template text `{slot}`" for slot in placeholders(title)]
    out += [f"body has template text `{slot}`" for slot in placeholders(body)]
    if len(substance(body)) < MIN_BODY_CHARS:
        out.append("body is empty apart from the hive footer")
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--title", default=os.environ.get("TITLE", ""))
    parser.add_argument("--body-file", type=Path)
    args = parser.parse_args(argv)

    body = (
        args.body_file.read_text(encoding="utf-8")
        if args.body_file
        else os.environ.get("BODY", "")
    )
    found = findings(args.title, body)
    for item in found:
        print(f"- {item}")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
