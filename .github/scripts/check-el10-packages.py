#!/usr/bin/env python3
"""Check EL10 package availability for packages mentioned in the upstream diff.

Spins up an AlmaLinux Kitten 10 container, enables EPEL 10 + CRB +
ublue-os/packages COPR + tuna-os/github-copr, then queries dnf for every
package candidate found in the diff's added lines.

Results are appended to GEMINI_TASK.md so the AI knows exactly which packages
can go in both blocks vs. the IS_FEDORA-only block.

For packages that are NOT available in EL10, a GitHub issue is opened as a
tracking item (deduplicated — skips if an open issue already exists).

Environment variables:
  GH_TOKEN      - GitHub token for issue creation
  REPO          - owner/repo
  SHORT_SHA     - 8-char upstream commit SHA (for issue context)
  URL           - upstream commit URL (for issue context)
  UPSTREAM_REPO - e.g. zirconium-dev/zirconium (for issue title/label)
  FLAVOR        - niri / gnome / kde (for issue label)
"""
import os
import pathlib
import re
import subprocess
import sys

GH_TOKEN = os.environ.get("GH_TOKEN", "")
REPO = os.environ.get("REPO", "")
SHORT_SHA = os.environ.get("SHORT_SHA", "unknown")
URL = os.environ.get("URL", "")
UPSTREAM_REPO = os.environ.get("UPSTREAM_REPO", "upstream")
FLAVOR = os.environ.get("FLAVOR", "unknown")

TASK_FILE = pathlib.Path("GEMINI_TASK.md")

# ── Extract package candidates from +lines in the diff ───────────────────────

content = TASK_FILE.read_text()

# Grab everything between "## Diff" and the next "## " heading
diff_text = re.search(r"## Diff\n(.*?)(?=\n## |\Z)", content, re.DOTALL)
diff_lines = diff_text.group(1).splitlines() if diff_text else []

PKG_RE = re.compile(r'\b([a-z][a-z0-9._+\-]{2,60})\b')

# Words that are definitely not package names
NOISE = {
    "the", "and", "for", "not", "are", "was", "has", "that", "this", "with",
    "from", "true", "false", "then", "else", "elif", "done", "esac", "exit",
    "echo", "sudo", "bash", "fish", "dnf", "rpm", "yum", "git", "apt", "var",
    "usr", "etc", "lib", "bin", "sbin", "tmp", "run", "dev", "sys", "proc",
    "boot", "root", "null", "set", "get", "put", "use", "new", "add", "all",
    "any", "can", "may", "let", "top", "end", "now", "type", "name", "path",
    "file", "line", "list", "item", "call", "read", "make", "copy", "move",
    "link", "test", "info", "base", "core", "main", "pass", "fail", "work",
    "help", "just", "only", "also", "very", "more", "most", "some", "each",
    "both", "even", "into", "over", "when", "than", "like", "after", "before",
    "while", "local", "export", "source", "return", "function", "install",
    "remove", "update", "enable", "disable", "start", "stop", "check", "build",
    "clean", "version", "package", "packages", "true", "false", "null", "yes",
    "copr", "repo", "enabled", "disabled", "quiet", "verbose", "args", "opts",
    "diff", "hash", "head", "tail", "grep", "sort", "uniq", "awk", "sed",
    "cat", "tee", "cut", "wc", "find", "xargs", "curl", "wget", "tar", "zip",
}

candidates = set()
for line in diff_lines:
    if not line.startswith("+"):
        continue
    stripped = line[1:].strip()
    if stripped.startswith("#"):
        continue
    # Skip lines that look like paths, URLs, or assignments
    if any(c in stripped for c in ["/", "http", "$", "=", "{"]):
        continue
    for m in PKG_RE.finditer(stripped):
        word = m.group(1)
        if word not in NOISE and not word.startswith("-") and len(word) >= 3:
            candidates.add(word)

if not candidates:
    print("No package candidates found in diff — skipping EL10 check")
    sys.exit(0)

pkg_list = sorted(candidates)
print(f"Checking {len(pkg_list)} package candidates in EL10+EPEL+CRB+COPRs:")
print("  " + ", ".join(pkg_list))

# ── Run check inside AlmaLinux Kitten 10 container ───────────────────────────

setup = " && ".join([
    "dnf install -y dnf-plugins-core epel-release --quiet --nogpgcheck 2>/dev/null",
    "crb enable --quiet 2>/dev/null || true",
    "dnf copr enable -y ublue-os/packages --quiet 2>/dev/null || true",
    "dnf copr enable -y tuna-os/github-copr --quiet 2>/dev/null || true",
    "dnf makecache --quiet 2>/dev/null || true",
])
query = "dnf repoquery --available --quiet " + " ".join(pkg_list) + " 2>/dev/null"

try:
    result = subprocess.run(
        ["docker", "run", "--rm", "almalinux:kitten", "bash", "-c",
         f"{setup} && {query}"],
        capture_output=True, text=True, timeout=300,
    )
except subprocess.TimeoutExpired:
    print("WARNING: Container check timed out — skipping availability report")
    sys.exit(0)
except FileNotFoundError:
    print("WARNING: Docker not available — skipping availability report")
    sys.exit(0)

# ── Parse results — repoquery outputs name-version.arch lines ────────────────

found_names = set()
for line in result.stdout.splitlines():
    line = line.strip()
    if not line:
        continue
    # Strip epoch:version-release.arch suffix: keep base name
    base = re.sub(r'[:-]\d.*$', '', line)
    base = re.sub(r'\.\w+$', '', base)  # strip .arch
    if base:
        found_names.add(base)

available, unavailable = [], []
for pkg in pkg_list:
    # Match if the package name is found exactly or as a prefix in found names
    if pkg in found_names or any(f == pkg or f.startswith(pkg + "-") for f in found_names):
        available.append(pkg)
    else:
        unavailable.append(pkg)

print(f"EL10 available ({len(available)}): {', '.join(available) or 'none'}")
print(f"EL10 unavailable ({len(unavailable)}): {', '.join(unavailable) or 'none'}")

# ── Append availability report to GEMINI_TASK.md ─────────────────────────────

lines = [
    "",
    "---",
    "",
    "## EL10 Package Availability Check",
    "",
    "Packages from the diff were queried against **AlmaLinux Kitten 10 + EPEL 10 + CRB + "
    "`ublue-os/packages` + `tuna-os/github-copr`**.",
    "",
    "**Port as much as possible.** Use this report to place packages correctly:",
    "",
]
if available:
    lines += [
        "### ✅ Available in EL10 — add to BOTH Fedora and EL10 blocks",
        "",
    ] + [f"- `{p}`" for p in available] + [""]
if unavailable:
    lines += [
        "### ❌ Not available in EL10 — add to `IS_FEDORA == true` block only",
        "",
    ] + [f"- `{p}`" for p in unavailable] + [""]

TASK_FILE.write_text(content + "\n".join(lines))

# ── Open tracking issues for EL10-unavailable packages (deduplicated) ────────

if not unavailable or not GH_TOKEN or not REPO:
    sys.exit(0)

# Ensure the label exists
subprocess.run(
    ["gh", "label", "create", "el10-gap",
     "--repo", REPO,
     "--description", "Package not available in EL10+EPEL — needs packaging or alternative",
     "--color", "E11D48"],
    capture_output=True,
    env={**os.environ, "GH_TOKEN": GH_TOKEN},
)

for pkg in unavailable:
    # Check for existing open issue to avoid duplicates
    existing = subprocess.run(
        ["gh", "issue", "list",
         "--repo", REPO,
         "--label", "el10-gap",
         "--state", "open",
         "--search", f"el10-gap {pkg}",
         "--json", "number",
         "--jq", "length"],
        capture_output=True, text=True,
        env={**os.environ, "GH_TOKEN": GH_TOKEN},
    ).stdout.strip()

    if existing != "0":
        print(f"  Issue already open for {pkg} — skipping")
        continue

    body = (
        f"## EL10 Packaging Gap: `{pkg}`\n\n"
        f"`{pkg}` is present in the upstream [`{UPSTREAM_REPO}`]"
        f"(https://github.com/{UPSTREAM_REPO}) at commit "
        f"[`{SHORT_SHA}`]({URL}) but is **not available** in "
        f"EL10 + EPEL 10 + CRB + `ublue-os/packages`.\n\n"
        f"### Impact\n\n"
        f"The `{FLAVOR}` flavor on EL10 variants (yellowfin / albacore / skipjack) "
        f"cannot include this package. It is currently added to the "
        f"`IS_FEDORA == true` block only.\n\n"
        f"### Options\n\n"
        f"- [ ] Package it in `tuna-os/github-copr`\n"
        f"- [ ] Find an EL10-compatible alternative\n"
        f"- [ ] Accept the Fedora-only status and document it\n"
    )

    result = subprocess.run(
        ["gh", "issue", "create",
         "--repo", REPO,
         "--title", f"📦 [el10-gap] `{pkg}` not available in EL10 (from {UPSTREAM_REPO}@{SHORT_SHA})",
         "--label", f"el10-gap,upstream-{FLAVOR}",
         "--body", body],
        capture_output=True, text=True,
        env={**os.environ, "GH_TOKEN": GH_TOKEN},
    )
    if result.returncode == 0:
        issue_url = result.stdout.strip()
        print(f"  Opened issue for {pkg}: {issue_url}")
    else:
        print(f"  Failed to open issue for {pkg}: {result.stderr.strip()}")
