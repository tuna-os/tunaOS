#!/usr/bin/env python3
"""Fallback porter using GitHub Models (gpt-4o) when Gemini quota is exceeded.

Reads GEMINI_TASK.md + relevant build files, sends to GitHub Models API,
executes the returned bash script to apply changes, then commits.

Environment variables:
  GH_TOKEN      - GitHub token (GITHUB_TOKEN from Actions)
  SHORT_SHA     - 8-char commit SHA (for commit message)
  BUILD_SCRIPT  - path to the flavor build script (e.g. build_scripts/niri.sh)
  OVERRIDES_DIR - path to flavor overrides dir (e.g. system_files_overrides/niri)
  COMMIT_PREFIX - optional commit message prefix (default: port(niri))
"""
import json
import os
import pathlib
import subprocess
import urllib.request

GH_TOKEN = os.environ["GH_TOKEN"]
SHORT_SHA = os.environ.get("SHORT_SHA", "unknown")
BUILD_SCRIPT = os.environ.get("BUILD_SCRIPT", "build_scripts/niri.sh")
OVERRIDES_DIR = os.environ.get("OVERRIDES_DIR", "system_files_overrides/niri")
COMMIT_PREFIX = os.environ.get("COMMIT_PREFIX", "port(niri)")

print("Gemini quota exceeded — falling back to GitHub Models (gpt-4o)")

task = pathlib.Path("GEMINI_TASK.md").read_text()

build_sh = pathlib.Path(BUILD_SCRIPT).read_text() if pathlib.Path(BUILD_SCRIPT).exists() else "(not found)"

overrides_parts = []
overrides_path = pathlib.Path(OVERRIDES_DIR)
if overrides_path.exists():
    for f in sorted(overrides_path.rglob("*")):
        if f.is_file():
            try:
                overrides_parts.append(f"=== {f} ===\n{f.read_text()}")
            except Exception:
                overrides_parts.append(f"=== {f} === (binary)")
overrides_content = "\n\n".join(overrides_parts) if overrides_parts else "(empty)"

prompt = f"""You are porting an upstream commit into a Linux bootc image build system.

{task}

CURRENT {BUILD_SCRIPT}:
{build_sh}

CURRENT {OVERRIDES_DIR}/ files:
{overrides_content}

OUTPUT REQUIREMENTS:
Return ONLY a bash script (no markdown fences, no explanation, no ```bash wrapper) that \
applies the necessary changes using standard commands (cat, tee, mkdir -p, sed, etc).
The script will be executed directly with bash.
If no changes are needed, output exactly: echo 'No changes needed'"""

payload = json.dumps({
    "model": "gpt-4o",
    "messages": [{"role": "user", "content": prompt}],
    "max_tokens": 4096,
}).encode()

req = urllib.request.Request(
    "https://models.inference.ai.azure.com/chat/completions",
    data=payload,
    headers={
        "Authorization": f"Bearer {GH_TOKEN}",
        "Content-Type": "application/json",
    },
)

with urllib.request.urlopen(req) as resp:
    data = json.loads(resp.read())

script = data["choices"][0]["message"]["content"].strip()

# Strip markdown fences if the model added them anyway
if script.startswith("```"):
    lines = script.splitlines()
    script = "\n".join(lines[1:-1] if lines[-1] == "```" else lines[1:])

print("--- Script from GitHub Models ---")
print(script)
print("--- Applying ---")

result = subprocess.run(["bash", "-e"], input=script.encode(), capture_output=False)
if result.returncode != 0:
    print(f"Script exited with code {result.returncode}")
    raise SystemExit(result.returncode)

# Stage and commit any changes
subprocess.run(["git", "add", "-A"], check=True)
staged = subprocess.run(["git", "diff", "--staged", "--quiet"]).returncode
if staged != 0:
    msg = f"{COMMIT_PREFIX}: [{SHORT_SHA}] (via GitHub Copilot fallback)"
    subprocess.run(["git", "commit", "-m", msg], check=True)
    print("Changes committed.")
else:
    print("No file changes to commit.")
