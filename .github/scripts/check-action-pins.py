#!/usr/bin/env python3
"""Reject mutable third-party GitHub Actions references.

A ref passes when it is a full commit SHA, or when it is a tag or branch
that .github/workflows/actions.lock locks to a commit (`gh actions-lock`
writes the lockfile; the actions-security workflow verifies it). A
workflow ref must be listed for that workflow; a composite action ref must
be a locked dependency. Cross-repository reusable workflow calls are not
covered by the lockfile and must stay SHA-pinned.
"""

from pathlib import Path
import re
import sys


USES_RE = re.compile(r"^\s*(?:-\s*)?uses:\s*(\S+)")
SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")
LOCKFILE = Path(".github/workflows/actions.lock")
LOCK_KEY_RE = re.compile(r"^    '?([^'\s]+?)'?:(?:\s*\[\])?$")
LOCK_ITEM_RE = re.compile(r"^        - '?([^'\s]+?)'?$")


def read_lockfile() -> tuple[dict[str, set[str]], set[str]]:
    """Per-workflow locked refs and all locked dependencies.

    The lockfile is machine-generated YAML with a fixed layout, so a line
    parser is enough and keeps this gate free of third-party imports.
    """
    workflows: dict[str, set[str]] = {}
    dependencies: set[str] = set()
    if not LOCKFILE.is_file():
        return workflows, dependencies
    section = None
    current: set[str] | None = None
    for line in LOCKFILE.read_text().splitlines():
        if line and not line.startswith(" "):
            section = line.split(":", 1)[0]
            current = None
            continue
        key = LOCK_KEY_RE.match(line)
        if key and section == "workflows":
            current = workflows.setdefault(key.group(1), set())
        elif key and section == "dependencies":
            dependencies.add(key.group(1).lower())
        item = LOCK_ITEM_RE.match(line)
        if item and section == "workflows" and current is not None:
            current.add(item.group(1).lower())
    return workflows, dependencies


def lock_key(name: str, ref: str) -> str:
    """`owner/repo/sub/path@ref` -> `owner/repo@ref`, as the lockfile keys it."""
    return "/".join(name.split("/")[:2]).lower() + "@" + ref.lower()


def main() -> int:
    errors: list[str] = []
    locked_workflows, locked_dependencies = read_lockfile()
    for path in sorted(Path(".github").rglob("*.yml")) + sorted(
        Path(".github").rglob("*.yaml")
    ):
        for line_number, line in enumerate(path.read_text().splitlines(), 1):
            match = USES_RE.match(line)
            if not match:
                continue

            reference = match.group(1)
            # Same-repository actions and workflows are versioned with this
            # repository: `./` from the checkout, `$/` from the workflow commit.
            if reference.startswith(("./", "$/", "docker://")):
                continue

            if "@" not in reference:
                errors.append(f"{path}:{line_number}: missing immutable SHA: {reference}")
                continue

            name, ref = reference.rsplit("@", 1)
            if SHA_RE.fullmatch(ref):
                continue

            key = lock_key(name, ref)
            if "/.github/workflows/" in name:
                locked = False
            elif path.parent == LOCKFILE.parent:
                locked = key in locked_workflows.get(path.as_posix(), set())
            else:
                locked = key in locked_dependencies
            if not locked:
                errors.append(f"{path}:{line_number}: mutable action ref: {reference}")

    if errors:
        print(
            "GitHub Actions must use full commit SHAs or refs locked in "
            f"{LOCKFILE} (run `gh actions-lock`):",
            file=sys.stderr,
        )
        print("\n".join(errors), file=sys.stderr)
        return 1

    print("All third-party GitHub Actions are pinned to full commit SHAs or locked refs.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
