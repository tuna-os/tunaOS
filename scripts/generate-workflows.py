#!/usr/bin/env python3
"""Generate build-config.yml from per-variant fragments, then produce
per-variant CI workflow files.

Fragments live in .github/build-config/:
  global.yml       — shared config (global_platforms)
  yellowfin.yml    — Yellowfin variant + flavors
  albacore.yml     — Albacore variant + flavors
  skipjack.yml     — Skipjack variant + flavors
  bonito.yml       — Bonito variant + flavors

Adding a variant = create one file in build-config/ + re-run this script.

Usage:
  python3 scripts/generate-workflows.py
"""

import yaml
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILD_CONFIG_DIR = os.path.join(REPO_ROOT, ".github", "build-config")
OUTPUT_CONFIG = os.path.join(REPO_ROOT, ".github", "build-config.yml")


def compose_config() -> dict:
    """Read global.yml + all variant YAMLs, compose into one config dict."""
    global_path = os.path.join(BUILD_CONFIG_DIR, "global.yml")
    if not os.path.exists(global_path):
        print(f"Error: {global_path} not found", file=sys.stderr)
        sys.exit(1)

    with open(global_path) as f:
        config = yaml.safe_load(f) or {}

    variant_files = sorted(
        f for f in os.listdir(BUILD_CONFIG_DIR)
        if f.endswith(".yml") and f != "global.yml"
    )

    if not variant_files:
        print("Error: no variant YAMLs found in build-config/", file=sys.stderr)
        sys.exit(1)

    variants = []
    for vf in variant_files:
        with open(os.path.join(BUILD_CONFIG_DIR, vf)) as f:
            variant = yaml.safe_load(f)
        variants.append(variant)

    config["variants"] = variants

    # Add stage diagram comment (helpful for newcomers)
    config["_comment"] = (
        "Generated from .github/build-config/*.yml fragments.\n"
        "Stage diagram:\n"
        "  Stage 1: base\n"
        "    ├── Stage 2: base-hwe, base-nvidia\n"
        "    └── Stage 2: gnome, kde, niri, cosmic, gnome50\n"
        "      ├── Stage 3: *-hwe (layer on base-hwe)\n"
        "      └── Stage 3: *-nvidia (layer on base-nvidia)\n"
        "        └── Stage 4: gnome-nvidia-hwe (layer on gnome-hwe)\n"
    )

    return config


def write_config(config: dict) -> None:
    """Write composed config to build-config.yml with leading comment."""
    comment = config.pop("_comment", "")
    with open(OUTPUT_CONFIG, "w") as f:
        for line in comment.strip().split("\n"):
            f.write(f"# {line}\n")
        f.write("\n")
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)
    print(f"  build-config.yml ({len(config.get('variants', []))} variants)")


def generate_workflows(config: dict) -> None:
    """Generate per-variant workflow YAMLs from variant list."""
    template = """name: Build {name_cap}
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
  group: build-{name}-${{{{ github.ref }}}}
  cancel-in-progress: true

jobs:
  build:
    name: {emoji}-{name}
    uses: ./.github/workflows/build-variant.yml
    with:
      variant: '{name}'
      flavor: ${{{{ inputs.flavor || 'all' }}}}
    secrets: inherit
"""
    workflows_dir = os.path.join(REPO_ROOT, ".github", "workflows")

    for variant in config.get("variants", []):
        name = variant["id"]
        emoji = variant.get("emoji", "?")
        name_cap = name.capitalize()

        content = template.format(name=name, name_cap=name_cap, emoji=emoji)
        file_path = os.path.join(workflows_dir, f"build-{name}.yml")
        with open(file_path, "w") as f:
            f.write(content)
        print(f"  .github/workflows/build-{name}.yml")


def main():
    os.chdir(REPO_ROOT)
    print("Composing build-config.yml from fragments...")
    config = compose_config()
    write_config(config)
    print("\nGenerating workflow files...")
    generate_workflows(config)
    print("\nDone.")


if __name__ == "__main__":
    main()
