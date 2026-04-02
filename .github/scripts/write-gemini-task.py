#!/usr/bin/env python3
"""Write GEMINI_TASK.md by combining a porting guide with a commit diff.

All inputs come from environment variables:
  PROMPT_FILE  - path to the porting guide markdown file
  SHA          - full commit SHA
  SHORT_SHA    - 8-char short SHA
  SUBJECT      - commit subject line
  AUTHOR       - commit author name
  DATE         - commit date (ISO 8601)
  URL          - commit URL
  FULL_MSG     - full commit message
  DIFF         - rendered diff string
"""
import os
import pathlib

prompt_file = os.environ.get("PROMPT_FILE", ".github/prompts/zirconium-port.md")
sha = os.environ.get("SHA", "")
short_sha = os.environ.get("SHORT_SHA", "")
subject = os.environ.get("SUBJECT", "")
author = os.environ.get("AUTHOR", "")
date = os.environ.get("DATE", "")
url = os.environ.get("URL", "")
full_msg = os.environ.get("FULL_MSG", "")
diff = os.environ.get("DIFF", "")

guide = pathlib.Path(prompt_file).read_text()

lines = [
    guide,
    "",
    "---",
    "",
    "## Commit Details",
    "",
    f"SHA: {sha}",
    f"SHORT_SHA: {short_sha}",
    f"SUBJECT: {subject}",
    f"AUTHOR: {author}",
    f"DATE: {date}",
    f"URL: {url}",
    "",
    "## Full Commit Message",
    "",
    "```",
    full_msg,
    "```",
    "",
    "## Diff",
    "",
    diff,
    "",
]

content = "\n".join(lines)
pathlib.Path("GEMINI_TASK.md").write_text(content)
print(f"GEMINI_TASK.md written ({len(content)} chars)")
