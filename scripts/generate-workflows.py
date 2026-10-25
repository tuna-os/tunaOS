#!/usr/bin/env python3
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import tunaos_config

import yaml
import os
import re


def orphan_wrappers(workflows, variant_ids):
    """Per-variant wrappers whose variant is not in tunaos.toml.

    This script writes one build-<id>.yml per variant and never removes one, so
    a fork that deletes a variant keeps a scheduled workflow that builds a
    variant the matrix no longer has. A wrapper is a job that calls
    build-variant.yml with a literal variant id (found by parsing the YAML, so
    quoting and layout do not matter); build-flavor.yml passes an expression
    and is not one.
    """
    orphans = []
    for path in sorted(Path(workflows).glob('build-*.yml')):
        try:
            document = yaml.safe_load(path.read_text(encoding='utf-8'))
        except yaml.YAMLError:
            continue
        for job in ((document or {}).get('jobs') or {}).values():
            if not isinstance(job, dict) or job.get('uses') != './.github/workflows/build-variant.yml':
                continue
            variant = (job.get('with') or {}).get('variant')
            # A literal id marks a per-variant wrapper; build-flavor.yml passes an expression.
            if isinstance(variant, str) and re.fullmatch(r'[a-z0-9-]+', variant) and variant not in variant_ids:
                orphans.append(path)
                break
    return orphans


def main():
    config = tunaos_config.matrix(tunaos_config.load())

    # Nightly schedule registry: keep this in lockstep with the
    # "Nightly schedule registry" comment block at the top of
    # .github/workflows/build-variant.yml. The ~2h stagger exists because the
    # org has a 20-concurrent-job ceiling; un-staggered crons queue against
    # each other (and the proving workflows) and starve everything. If you
    # add a variant or move a cron, update both places.
    SCHEDULES = {
        "yellowfin": "20 0 * * *",
        "albacore": "20 2 * * *",
        "gurnard": "20 4 * * *",
        "guppy": "20 6 * * *",
        "skipjack": "20 9 * * *",
        "bonito": "20 11 * * *",
        "marlin": "20 13 * * *",
        "bonito-rawhide": "20 15 * * *",
        "grouper": "20 17 * * *",
        "sailfin": "20 19 * * *",
        "flounder": "20 21 * * *",
        "hummingbird": "20 22 * * *",
        "flounder-sid": "20 23 * * *",
    }

    schedule_block = """  schedule:
    - cron: "{cron}"
"""

    # Least-privilege token for the called build-variant.yml: it reads the
    # repo, pushes images to GHCR, and signs with GitHub OIDC (keyless cosign).
    permissions_block = """permissions:
  contents: read
  packages: write
  id-token: write
"""

    template = """name: Build {name_cap}
{permissions}on:
{schedule}  workflow_dispatch:
    inputs:
      flavor:
        description: 'Flavor (all, base, gnome, kde, niri, etc.)'
        default: 'all'
        type: string

concurrency:
  group: build-{name}-${{{{ github.ref }}}}-${{{{ github.event_name == 'workflow_dispatch' && github.run_id || github.event_name }}}}
  cancel-in-progress: true

jobs:
  build:
    name: {emoji}-{name}
    uses: ./.github/workflows/build-variant.yml
    with:
      variant: '{name}'
      flavor: ${{{{ inputs.flavor || 'all' }}}}
    secrets:
      R2_ACCESS_KEY_ID: ${{{{ secrets.R2_ACCESS_KEY_ID }}}}
      R2_SECRET_ACCESS_KEY: ${{{{ secrets.R2_SECRET_ACCESS_KEY }}}}
      R2_ENDPOINT: ${{{{ secrets.R2_ENDPOINT }}}}
      R2_BUCKET: ${{{{ secrets.R2_BUCKET }}}}
"""

    # Experimental variants: manual dispatch only — no cron schedule.
    template_experimental = """name: Build {name_cap} [experimental]
{permissions}on:
  workflow_dispatch:
    inputs:
      flavor:
        description: 'Flavor (all, base, gnome, kde, niri, etc.)'
        default: 'all'
        type: string

concurrency:
  group: build-{name}-${{{{ github.ref }}}}-${{{{ github.event_name == 'workflow_dispatch' && github.run_id || github.event_name }}}}
  cancel-in-progress: true

jobs:
  build:
    name: {emoji}-{name}
    uses: ./.github/workflows/build-variant.yml
    with:
      variant: '{name}'
      flavor: ${{{{ inputs.flavor || 'all' }}}}
    secrets:
      R2_ACCESS_KEY_ID: ${{{{ secrets.R2_ACCESS_KEY_ID }}}}
      R2_SECRET_ACCESS_KEY: ${{{{ secrets.R2_SECRET_ACCESS_KEY }}}}
      R2_ENDPOINT: ${{{{ secrets.R2_ENDPOINT }}}}
      R2_BUCKET: ${{{{ secrets.R2_BUCKET }}}}
"""



    for variant in config.get('variants', []):
        name = variant.get('id')
        emoji = variant.get('emoji', '❓')
        name_cap = name.capitalize()
        experimental = variant.get('experimental', False)

        if experimental:
            workflow_content = template_experimental.format(
                name=name,
                name_cap=name_cap,
                emoji=emoji,
                permissions=permissions_block
            )
        else:
            cron = SCHEDULES.get(name)
            schedule = schedule_block.format(cron=cron) if cron else ""
            workflow_content = template.format(
                name=name,
                name_cap=name_cap,
                emoji=emoji,
                schedule=schedule,
                permissions=permissions_block
            )

        file_path = f'.github/workflows/build-{name}.yml'
        with open(file_path, 'w') as f:
            f.write(workflow_content)
        print(f"Generated {file_path}")

    orphans = orphan_wrappers('.github/workflows', {variant.get('id') for variant in config.get('variants', [])})
    if orphans:
        for path in orphans:
            print(f"::error::{path} builds a variant that is not in tunaos.toml. Delete the file, or restore the variant.", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
