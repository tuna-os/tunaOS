#!/usr/bin/env python3
import yaml
import os
import sys

def main():
    config_file = '.github/build-config.yml'
    if not os.path.exists(config_file):
        print(f"Error: {config_file} not found", file=sys.stderr)
        sys.exit(1)

    with open(config_file, 'r') as f:
        config = yaml.safe_load(f)

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

    for variant in config.get('variants', []):
        name = variant.get('id')
        emoji = variant.get('emoji', '❓')
        name_cap = name.capitalize()
        
        workflow_content = template.format(
            name=name,
            name_cap=name_cap,
            emoji=emoji
        )
        
        file_path = f'.github/workflows/build-{name}.yml'
        with open(file_path, 'w') as f:
            f.write(workflow_content)
        print(f"Generated {file_path}")

if __name__ == "__main__":
    main()
