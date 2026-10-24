# Primary TunaOS configuration migration

Status: design and migration history, not a copyable configuration interface.
Issue [#3668](https://github.com/tuna-os/tunaOS/issues/3668) records the adopted ownership boundary.
For implemented fields and commands, read [CONFIG-WIRING.md](CONFIG-WIRING.md).
Related work: RFC 013, issue #3433 and delivery epic #3474.

## Goal

TunaOS itself uses `tunaos.toml`. A person changes that same file to choose
variants, packages, image names and brand assets. There is no catalog for stock values beneath a customization file. Assets remain local referenced files.
The compiler emits the formats that build and installer consumers need.

The maintainer selected TOML on 2026-10-20. This changes RFC 013's earlier
choice to keep legacy sources authoritative and add optional fork deltas.
The strict validators and consumer tests from that work remain useful.
The name `tunaos.toml` alone would not make those deltas meet the new requirement.

## Source ownership

Status is for `main`. The validator on `main` rejects the fields of an open PR
under #3668; do not copy them into `tunaos.toml` yet.

| Fork-facing value | Status on main | TOML owner | Consumer or generated adapter |
|---|---|---|---|
| Publish registry and namespace | Implemented (#3736) | `[build.publish]` | `scripts/lib/publish-destination.sh`; non-owner CI credentials are F1b (#3801) |
| Image names: aliases, publish name, tag suffix | Implemented | `variants.<id>` `aliases`, `publish_name`, `tag_suffix` | Generated matrix `.github/build-config.yml` |
| Variant IDs, emoji, bases, platforms, flavor order and holds | Implemented | `variants`, `[[variants.<id>.flavors]]` | Generated matrix at the existing path |
| ISO groups, sibling images and Tuna Desktop admission records | Implemented | `iso_groups`, `sibling_images`, `tuna_rollout` | The same generated matrix, with all metadata retained |
| Desktop package profiles, family overrides, optional/excluded sets and repository policy | Implemented | `package_groups`, `desktops` | Generated `manifests/desktops/*.yaml` consumed by `install-desktop.sh` |
| Variant base-image pins | Implemented | `variants.<id>.base_image` | `scripts/get-base-image.sh`; Renovate edits the TOML pin |
| Default Flatpak applications | Implemented (#3553) | `[flatpak_preinstall]` | Generated `build_scripts/desktop/flatpak-preinstall.tsv` |
| ISO Builder presentation and defaults | Implemented | `[iso_builder]`, `flavor_metadata` | Generated `docs/iso-builder.*.json` |
| Project name, ID, CPE vendor, URLs, variant codenames | Open PR: F3a (#3681) | `[project]`, `[defaults.branding]`, `variants.<id>.codename` | Today: `90-image-info.sh` and `build_scripts/lib/variant-identity.tsv` |
| Variant accent, GNOME accent, base label | Open PR: F3b (#3700) | `variants.<id>.branding` | Today: framework identity/brand sources |
| Marks, lettermarks, Plymouth themes, wallpaper aliases | Open PR: F3c/F3d (#3701, #3705) | `branding.plymouth` plus generated artwork | Today: asset naming and `build_scripts/desktop/select-wallpaper.sh` |
| Installer name and logo | Open PR: F3e (#3708) | Project name; logo is the in-image variant mark | Today: installer customization sources |
| Image-wide package additions over inherited base lists | Open PR: F4 (#3739) | `[defaults.packages]`, `variants.<id>.packages` (`add`, `optional`, `repositories`) | Today: framework base package scripts |
| Image-wide package removals | Rejected (F4b, #3803) | none | No protected-removal design yet |

Execution scripts, Containerfiles and checks remain code. Tool/download pins in
`image-versions.yaml`, registry mirrors in `registry-map.yaml` and the Flatpak
remote setup also remain framework inputs; they are not migration targets.
The planned additions do not replace the inherited stock base packages.
Credentials are not
configuration data. Do not put shell commands, remote includes or secret values in TOML. Existing trusted post-install steps become named, validated operations;
this migration does not add arbitrary hooks.

## Utah reference

Follow the readable package contract in
[Utah packages/utah.toml](https://github.com/projectbluefin/utah/blob/main/packages/utah.toml).
Its named groups contain plain package lists, required versions and comments
that explain choices. Its installer resolves an ordered contract and the image
verifier checks that same result. Use that pattern for native package families
and named desktop profiles here, without a generic operation DSL.

Utah is an overlay on a separate Bluefin manifest. TunaOS must own its defaults
in the same primary file. Utah also reads separate repository files and names
its install sections in code. TunaOS must validate every declared section and
project the repository settings too; an unknown group must not become inert
configuration that looks supported.

## Readable shape

The example below shows current values, not a complete build configuration.
The complete file must contain every existing cell and policy. Omitted variant
flavors here are not a proposal to disable them. Sections marked "open PR" use
the shapes in those PRs and fail validation on `main` today.

```toml
schema_version = 1

# Implemented. Omitted in stock TunaOS; a fork sets both keys.
[build.publish]
registry = "quay.io"
namespace = "acme"

# Open PR: F3a (#3681).
[project]
name = "TunaOS"
id = "tunaos"
cpe_vendor = "jamesreilly"

# Open PR: F3a (#3681).
[defaults.branding]
homepage = "https://github.com/tuna-os/tunaos"
documentation = "https://github.com/tuna-os/tunaos/tree/main/docs"
support = "https://github.com/tuna-os/tunaos/issues/"
bug_report = "https://github.com/tuna-os/tunaos/issues/"

# Open PR: F4 (#3739). Native names must be valid for every selected family.
[defaults.packages]
add = []

# Implemented, except codename (F3a) and branding (F3b/F3d), which are open PRs.
[variants.yellowfin]
emoji = "🐠"
description = "Based on AlmaLinux Kitten 10"
codename = "Thunnus albacares"
base_image = "quay.io/almalinuxorg/almalinux-bootc:10-kitten@sha256:fabe22d605a5638cb1fbf2df38d6d9b9ace35f15cb1c10c7db87d475a039d58a"
aliases = ["almalinux-kitten"]
platforms = ["linux/amd64", "linux/amd64/v2", "linux/arm64"]
branding = { accent = "#FFC702", gnome_accent = "yellow", base = "AlmaLinux Kitten", homage = "the yellow petal of the AlmaLinux flower", plymouth = "tropical-fish" }

# Open PR: F4 (#3739). Native RPM additions for this variant only.
[variants.yellowfin.packages]
add = []

# Implemented. Package profiles keep native package names and list order.
[desktops.gnome-debian]
display_manager = "gdm3"

[desktops.gnome-debian.packages.apt]
required = [
  "gnome-core", "gnome-disk-utility", "gnome-system-monitor", "nautilus",
  "xdg-desktop-portal-gnome", "xdg-desktop-portal-gtk", "xdg-user-dirs-gtk",
  "libglib2.0-dev-bin",
]
```

The order of desktop package lists matters: `include` groups expand first, then
local entries, without deduplication. The image-wide `packages` tables from
#3739 only add packages over the inherited base lists; the validator rejects
removals until F4b. Do not
silently reinterpret an existing ordered package list as a set. Family-specific
package names stay family-specific. Selection never enables a held or
unsupported cell.

## Ordered migration

1. Record the ownership map and schema in the RFC/spec/plan. Inventory every
   relevant legacy reader and writer, including Renovate and workflow scripts.
2. Move the complete matrix into TOML. Generate the old adapter without losing
   any value, order, flag, alias, ISO group or rollout record. Generate with
   `python3 scripts/config.py generate`; `just check` runs the read-only drift
   checks. The matrix and desktop adapters are git-ignored and regenerated at
   build setup. Both local and CI builds validate the source before consumption.
3. Move desktop profiles and add configurable image-wide package additions in reviewed groups.
   Compare the complete resolved package/repository operation sequence to the
   old path for every supported family and cell. Keep tool/download pins and
   registry mirrors in their existing framework files.
4. Move actual image identity, artwork and installer defaults. TunaOS's own
   values pass through the same compiler and consumers as customized values.
   Reuse the reviewed mechanisms in consumers and check final writers. No stock-only bypass remains.
5. Replace preview-only commands with the primary config interface. Preserve an explicit command to migrate legacy config and clear errors for incompatible inputs.
   Retire the obsolete source files and fork-only documentation.
6. Qualify representative built images, installer frontends and real installs.
   Keep failures and absent proof visible for each artifact. Only then mark delivery done.

Step 2 is only a matrix migration. It does not complete the user's requirement
while package defaults or brand assets have another source.
Do not claim this goal is complete through the unchanged customization stack.

## Compatibility and verification

Keep support for configuration tools on Python 3.10+.
Every host uses the pure Tomli 2.3.2 source bundled in `scripts/lib/_vendor/tomli`.
This release keeps TOML 1.0 and adds limits for key depth and nested values.
The [reviewed parser source](https://github.com/hukkin/tomli/blob/d326dd59d8e10d621cba4de3ee110a7db6324ddd/src/tomli/_parser.py)
sets both limits. Python 3.15's `tomllib` accepts TOML 1.1, so it is not a fallback.

Config reads need no pip install, special environment, or network access.
The source includes the MIT license and exact file hashes.
See [parser updates](VENDORED-PARSER.md) for the explicit update procedure.
If the checkout is incomplete, the read fails with an error.
It does not select a host parser.

Target image builds read generated YAML or JSON with shell helpers and yq.
For Debian, the helper checks a hash of the TOML source bytes without a parser.
The host prepares these adapters before the container build starts.
The Python 3.10 and 3.15 jobs run the same grammar and parse-limit tests.

Keep the TOML 1.0 grammar shared with Python 3.11. The edit layer must preserve comments and reparse its output through this core.
Generated JSON/YAML remains consumable by target images without Python or TOML
libraries. Do not assume EL10, old Debian or a user's Mac has `tomllib`.

Each base-image pin has one authoritative entry under its variant; Renovate edits
that TOML entry. Tool/download pins stay in `image-versions.yaml` and mirrors in
`registry-map.yaml`, outside TOML. Generate adapters from the TOML source at
build setup. No bot commit of derived files is necessary.

Required tests include full matrix value/order equality, full flavor-route
and base-image resolution equality, package sequence equality, and unchanged
brand/installer asset bytes. Test unknown keys, wrong types, duplicate TOML
keys, invalid selectors, absolute asset paths, paths outside the asset root and unsupported inputs.
An invalid file must fail before package changes or publication. Generation must be deterministic and atomic. A read-only check must detect output drift.

Add mutation tests that prove edits to TunaOS's TOML change the correct fields in generated output.
The gate must detect edits to generated files.
There is no hidden fallback to a separate stock catalog on parse failure.

Existing frozen qualification artifacts remain bound to their original source
receipts. Source equivalence is not boot, install or Secure Boot qualification.

## Authoring tools

The maintainer also requested tools to find packages and edit configuration
across different bases. Keep support for manual edits. Add a small CLI over the same parser, schema and resolver that builds use.
Do not create a second config implementation. This is a later workstream, not extra scope for matrix parity.

- Inspect the effective variant/desktop/platform configuration and explain
  which shared or scoped value selected each setting.
- Search the repositories configured for a chosen base version and
  architecture. Show source repository, native package name and metadata
  freshness. A match in an index proves availability, not transaction solvability.
- Support `tunaos config add htop`. Resolve intent against every supported base, version and architecture in the configuration.
  Then write the correct native names into shared or scoped configuration. A repeat command makes no change.
  If a required mapping is unavailable or ambiguous, fail with actionable results.
  Do not partly edit the file or guess a Gentoo atom from a name.
  Use exact package names, unique matches in measured categories and verified mappings as evidence.
  Different native names do not force the user to edit each base.
- Preserve TOML comments and unrelated layout. Show a diff before an edit.
  Validate the edited file and write it atomically.
- Expose a separate transaction-resolution check that uses the same resolved
  package contract as installation. Do not install packages during a search.

Survey existing TunaOS package-query, resolver and validation tooling first.
Native dnf, apt, pacman, zypper and portage adapters must state their support
limits. Never infer a portable package name from string similarity alone.

See the [package command guide](PACKAGE-AUTHORING.md) for the first
index-backed implementation. It edits explicit existing policy
sections using supplied native indexes. Automatic configured-repository discovery
and per-variant transaction verification remain outside that first slice.

## Local migration experiment (not production code)

Against main `83362754`, a read-only prototype translated all 14 variants,
155 declared flavor records and 15 desktop manifests into a single TOML
document. The parse and projection preserved all matrix values, variant and flavor order, and every desktop-manifest value.
An emoji change for Yellowfin reached its generated adapter. The parser rejected duplicates of TOML keys and tables.

This proves a lossless data representation is possible. It does not prove
package operations, runtime consumers, asset bytes or installed-image parity.
The experiment is outside the repository's production build paths. The experiment changed no image inputs or build entrypoints.

## Matrix semantics retained in phase 1

Variant platforms are defaults. A flavor can specify other supported platforms.
For example, Skipjack GNOME includes `linux/amd64/v2` beyond its variant defaults.

Aliases provide other names for images. Shared aliases are valid only when
the complete tags differ, as with Fedora and Fedora Rawhide. An alias cannot
replace a canonical variant name or a declared publish name.

ISO live flavors and offline payloads are separate lists. A GNOME NVIDIA live
image can carry non-NVIDIA GNOME in its offline store. Both lists must name
flavors that exist in the matrix.

## ISO Builder presentation slice

`[iso_builder]` now owns the bounded browser presentation and default choices.
See [ISO Builder configuration](ISO-BUILDER-CONFIG.md) for export, validation,
drift checks and catalog authority boundaries. This does not move installed
image identity, artwork or installer appearance into primary configuration.

The Marlin GDM override also belongs to `[desktops.tuna-arch]`. Its generated
adapter has the same precedence as the former tracked YAML. The regression
fixture at commit `aa9810e9` preserves the complete package and hook contract;
other Tuna Desktop cells retain their existing display manager.
