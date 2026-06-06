#!/usr/bin/env python3
"""Generate per-variant build workflow files from .github/build-config.yml.

Each variant gets a thin wrapper workflow that calls the shared
build-variant.yml reusable workflow with the variant name.

Uses stdlib only — no external dependencies.
Output files: .github/workflows/build-{variant}.yml
"""

import re
import sys
from pathlib import Path

WORKFLOW_TEMPLATE = """\
name: Build {name}
on:
  schedule:
    - cron: "0 1 * * *"
  workflow_dispatch:
    inputs:
      flavor:
        description: 'Flavor (all, base, gnome, kde, niri, etc.)'
        default: 'all'
        type: string

concurrency:
  group: build-{variant}-${{{{ github.ref }}}}
  cancel-in-progress: true

jobs:
  build:
    name: {emoji}-{variant}
    uses: ./.github/workflows/build-variant.yml
    with:
      variant: '{variant}'
      flavor: ${{{{ inputs.flavor || 'all' }}}}
    secrets: inherit
"""


def parse_variants(config_text: str) -> list[dict]:
    """Extract variant id + emoji from build-config.yml.

    Variants are the top-level entries under 'variants:' (indent 2).
    Flavors are nested under each variant (indent 6+) and are skipped.
    """
    variants = []
    lines = config_text.splitlines()

    i = 0
    while i < len(lines):
        line = lines[i]

        # Variant entry: starts with "  - id:" (2-space indent)
        m = re.match(r"^  - id:\s+(\S+)", line)
        if m:
            vid = m.group(1)
            emoji = "❓"

            # Look ahead for emoji (within the same variant block, indent 4)
            j = i + 1
            while j < len(lines):
                next_line = lines[j]
                # Stop if we hit another top-level variant or end of variants
                if re.match(r"^  - id:\s+", next_line):
                    break
                if re.match(r"^\S", next_line) and not next_line.startswith("  "):
                    break
                m_emoji = re.match(r'^\s{4}emoji:\s*"(.+)"', next_line)
                if m_emoji:
                    emoji = m_emoji.group(1)
                    break
                j += 1

            variants.append({"id": vid, "emoji": emoji})

        i += 1

    return variants


def generate_workflow(variant_id: str, variant_emoji: str) -> str:
    name = variant_id.capitalize()
    return WORKFLOW_TEMPLATE.format(
        name=name,
        variant=variant_id,
        emoji=variant_emoji,
    )


def main():
    repo_root = Path(__file__).resolve().parent.parent
    config_path = repo_root / ".github" / "build-config.yml"
    workflows_dir = repo_root / ".github" / "workflows"

    config_text = config_path.read_text()
    variants = parse_variants(config_text)

    if not variants:
        print("ERROR: no variants found in build-config.yml", file=sys.stderr)
        sys.exit(1)

    for variant in variants:
        vid = variant["id"]
        emoji = variant.get("emoji", "❓")
        content = generate_workflow(vid, emoji)
        out_path = workflows_dir / f"build-{vid}.yml"
        out_path.write_text(content)
        print(f"Wrote {out_path.relative_to(repo_root)}")

    print(f"Generated {len(variants)} workflow files.")


if __name__ == "__main__":
    main()
