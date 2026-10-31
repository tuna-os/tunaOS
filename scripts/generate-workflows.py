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
        except yaml.YAMLError as exc:
            raise SystemExit(f'{path}: not valid YAML, so it cannot be checked for a removed variant: {exc}') from exc
        for job in ((document or {}).get('jobs') or {}).values():
            if not isinstance(job, dict) or job.get('uses') != './.github/workflows/build-variant.yml':
                continue
            variant = (job.get('with') or {}).get('variant')
            # A literal id marks a per-variant wrapper; build-flavor.yml passes an expression.
            if isinstance(variant, str) and re.fullmatch(r'[a-z0-9-]+', variant) and variant not in variant_ids:
                orphans.append(path)
                break
    return orphans


# build-flavor.yml is hand-written except for this one line, which lists the
# variants its manual sweep fans out to.
FLAVOR_MATRIX = re.compile(r'^([ \t]+variant:[ \t]*)\[[^\]\n]*\][ \t]*$', re.M)


def flavor_sweep(variants):
    """Ids build-flavor.yml dispatches: every variant but an experimental one or a flavor_dispatch = false."""
    return [name for name, variant in variants.items()
            if variant.get('flavor_dispatch', not variant.get('experimental', False))]


def with_flavor_sweep(text, ids):
    """build-flavor.yml source with its `matrix.variant` list set to `ids`."""
    rewritten, count = FLAVOR_MATRIX.subn(lambda m: m.group(1) + '[' + ', '.join(ids) + ']', text)
    if count != 1:
        raise ValueError(f'expected one `variant: [...]` matrix line in build-flavor.yml, found {count}')
    return rewritten


# The Asahi sweeps are hand-written except for their one `flavor: [...]` matrix
# line each: the variants whose gnome-asahi image they test.
ASAHI_SWEEPS = (('.github/workflows/verify-asahi.yml', 'asahi_verify'),
                ('.github/workflows/asahi-hw-nightly.yml', 'asahi_hardware'))
ASAHI_MATRIX = re.compile(r'^([ \t]+flavor:[ \t]*)\[[^\]\n]*\][ \t]*$', re.M)


def asahi_sweep(variants, key):
    """Ids of the variants that set `key` (asahi_verify or asahi_hardware) to true."""
    return [name for name, variant in variants.items() if variant.get(key, False)]


def with_asahi_sweep(text, ids):
    """Asahi sweep workflow source with its `matrix.flavor` list set to `ids`."""
    rewritten, count = ASAHI_MATRIX.subn(lambda m: m.group(1) + '[' + ', '.join(ids) + ']', text)
    if count != 1:
        raise ValueError(f'expected one `flavor: [...]` matrix line in the Asahi sweep, found {count}')
    return rewritten


def main():
    primary = tunaos_config.load()
    config = tunaos_config.matrix(primary)
    options = primary['variants']

    # Nightly schedule: variants.<id>.schedule in tunaos.toml. Keep it in
    # lockstep with the "Nightly schedule registry" comment block at the top of
    # .github/workflows/build-variant.yml. The ~2h stagger exists because the
    # org has a 20-concurrent-job ceiling; un-staggered crons queue against
    # each other (and the proving workflows) and starve everything. If you
    # add a variant or move a cron, update both places.

    schedule_block = """  schedule:
    - cron: "{cron}"
"""

    # Least-privilege token for the called build-variant.yml: it reads the
    # repo, pushes images to GHCR, signs with GitHub OIDC (keyless cosign),
    # and dispatches live-overlay.yml after each Promote (actions: write; a
    # called job cannot hold a grant its caller lacks).
    permissions_block = """permissions:
  actions: read
  contents: read
  packages: write
  id-token: write
  actions: write
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
      TUNAOS_PUBLISH_USERNAME: ${{{{ secrets.TUNAOS_PUBLISH_USERNAME }}}}
      TUNAOS_PUBLISH_PASSWORD: ${{{{ secrets.TUNAOS_PUBLISH_PASSWORD }}}}
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
      TUNAOS_PUBLISH_USERNAME: ${{{{ secrets.TUNAOS_PUBLISH_USERNAME }}}}
      TUNAOS_PUBLISH_PASSWORD: ${{{{ secrets.TUNAOS_PUBLISH_PASSWORD }}}}
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
            cron = options[name].get('schedule')
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

    sweep_path = '.github/workflows/build-flavor.yml'
    with open(sweep_path, encoding='utf-8') as f:
        sweep_source = f.read()
    sweep = with_flavor_sweep(sweep_source, flavor_sweep(options))
    if sweep != sweep_source:
        with open(sweep_path, 'w', encoding='utf-8') as f:
            f.write(sweep)
        print(f"Generated {sweep_path}")

    for sweep_path, key in ASAHI_SWEEPS:
        with open(sweep_path, encoding='utf-8') as f:
            sweep_source = f.read()
        sweep = with_asahi_sweep(sweep_source, asahi_sweep(options, key))
        if sweep != sweep_source:
            with open(sweep_path, 'w', encoding='utf-8') as f:
                f.write(sweep)
            print(f"Generated {sweep_path}")

    orphans = orphan_wrappers('.github/workflows', {variant.get('id') for variant in config.get('variants', [])})
    if orphans:
        for path in orphans:
            print(f"::error::{path} builds a variant that is not in tunaos.toml. Delete the file, or restore the variant.", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
