#!/usr/bin/env python3
import yaml
import os
import sys
import json
import argparse

from contracts.targets import coverage_document

def main():
    parser = argparse.ArgumentParser(description='Generate build wrappers and required coverage')
    parser.add_argument('--check', action='store_true', help='Reject generated file drift')
    args = parser.parse_args()
    changed = []

    def emit(path, body):
        if args.check:
            if not os.path.isfile(path) or open(path).read() != body:
                changed.append(path)
        else:
            with open(path, 'w') as output:
                output.write(body)
            print(f"Generated {path}")

    config_file = '.github/build-config.yml'
    if not os.path.exists(config_file):
        print(f"Error: {config_file} not found", file=sys.stderr)
        sys.exit(1)

    with open(config_file, 'r') as f:
        config = yaml.safe_load(f)

    # Generate commitments independently of actual workflow execution coverage.
    # PR narrowing and package-supply restrictions must remain visible gaps.
    coverage = coverage_document(config)
    coverage_path = 'required-targets.json'
    emit(coverage_path, json.dumps(coverage, indent=2, sort_keys=True) + '\n')

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

    template = """name: Build {name_cap}
on:
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
on:
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
                emoji=emoji
            )
        else:
            cron = SCHEDULES.get(name)
            schedule = schedule_block.format(cron=cron) if cron else ""
            workflow_content = template.format(
                name=name,
                name_cap=name_cap,
                emoji=emoji,
                schedule=schedule
            )

        file_path = f'.github/workflows/build-{name}.yml'
        emit(file_path, workflow_content)

    if changed:
        print('Generated files are stale: ' + ', '.join(changed), file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
