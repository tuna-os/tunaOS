# Primary Flatpak declarations

`tunaos.toml` owns the image's intended Flatpak list in `flatpak_preinstall`.
Its schema version is 1. Only the stable branch is supported in this slice. `common` is an ordered list of app ID and branch pairs;
`desktop_additions` maps a desktop ID to more pairs.

Unknown fields and duplicate IDs are invalid. Each desktop must exist in the primary configuration. An empty policy
stays empty. There is no stock fallback.

Run `python3 scripts/config.py generate-flatpak-policy` after an edit. This writes
`build_scripts/desktop/flatpak-preinstall.tsv`. The recipe reads this generated
adapter and installs the effective desktop policy at
`/usr/share/flatpak/tunaos-preinstall-policy.tsv`. The image verifier reads that
file. Independent tests assert the declarations from the previous recipe. These tests
catch an error shared by the generator and its consumers.

The migration preserves Bazaar and Firefox for every desktop using the operation,
plus Extension Manager for GNOME. It does not add new image packages. The KCM script no longer writes a duplicate
Bazaar declaration.

Existing preinstall declarations from other scripts still take precedence. The verifier
checks for branch mismatches. The Hummingbird exception stays unchanged. The service is
enabled only where it exists, with the same warning when it does not.

The builder's portable version 2 contract keeps `default_flatpaks`. The compiler
gets its stock values from this policy. Do not edit another copy under
`iso_builder.desktops`. Editor suggestions are not stock defaults. For a new collection of editors, add separate configuration and label it optional.

## What this list proves

These are image declarations, not installed inventory. The recipe now
writes ID, branch and IsRuntime=false. It declares no verified remote origin or
CollectionID. The adapter must not turn those IDs into executable Flathub
identities. Inspect the selected image for its suggestions. The source cannot prove what an
older image digest contains.

Native application capabilities and bundled installer roles also need verified
image facts. Package intent alone is not proof of a usable terminal. Explicit
live/target customization belongs to the consumer for runtime intent. This
source change neither applies those requests nor removes installed apps.

## Generated files and checks

`check-flatpak-policy` compares the bytes in the adapter and refuses symlinks. The normal
check recipe runs it beside `check-builder-config`. Both generated files have one
primary source to edit. The installed TSV is outside `preinstall.d`, so it is
not another preinstall request. These generator and shell tests do not prove an image build, boot or deployment.
