# Primary TunaOS configuration migration

Status: draft for review. This is not a completed configuration interface.
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

Status is for this stack. It includes the open F3 and F4 pull requests that the
text names, and it assumes they merge first. A value counts as owned by `tunaos.toml` only
when a validator, a generated adapter and a consumer exist for it.

| Fork-facing value | Status | TOML owner | Consumer or generated adapter |
|---|---|---|---|
| Publish registry and namespace | Implemented (F1 #3736) | `[build.publish]` | `scripts/lib/publish-destination.sh`; image-info records the destination |
| Image names: aliases, publish name, tag suffix | Implemented | `variants.<id>` `aliases`, `publish_name`, `tag_suffix` | Generated matrix `.github/build-config.yml` |
| Variant IDs, emoji, bases, platforms, flavor order and holds | Implemented | `variants`, `[[variants.<id>.flavors]]`, `base_image` | Generated matrix; `scripts/get-base-image.sh` |
| ISO groups, sibling images and Tuna Desktop admission records | Implemented | `iso_groups`, `sibling_images`, `tuna_rollout` | The same generated matrix, with all metadata retained |
| Desktop package profiles, family overrides, optional/excluded sets and repository policy | Implemented | `package_groups`, `desktops` | Generated `manifests/desktops/*.yaml` consumed by `install-desktop.sh` |
| Default Flatpak applications | Implemented (F2 #3553) | `[flatpak_preinstall]` | Generated `build_scripts/desktop/flatpak-preinstall.tsv` |
| ISO Builder presentation and defaults | Implemented | `[iso_builder]`, `flavor_metadata` | Generated `docs/iso-builder.*.json` |
| Project name, ID, CPE vendor, URLs, variant codenames | Implemented (F3a #3681) | `[project]`, `[defaults.branding]`, `variants.<id>.codename` | Generated `build_scripts/lib/identity.env`; `90-image-info.sh` |
| Variant accent, GNOME accent, base label, splash theme name | Implemented (F3b #3700, F3d #3705) | `variants.<id>.branding` | Generated `variant-identity.tsv` |
| Marks, lettermarks and fastfetch letters | Implemented (F3c #3701) | derived from `emoji`, project name and `branding.accent` | Committed outputs of `scripts/branding/*.py`, checked in CI |
| Installer name | Implemented (F3e #3708) | `[project]` `name`; the logo is the variant mark | `90-image-info.sh` recipe and slide text |
| Image-wide package additions over inherited base lists | Implemented (F4 #3739) | `[defaults.packages]`, `variants.<id>.packages` (`add`, `optional`, `repositories`) | Generated `image-packages.tsv`; `build_scripts/lib/image-packages.sh` |
| Image-wide package removals | Rejected by the validator (F4b #3803) | none | No protected-removal design yet |

### Still owned outside `tunaos.toml`

A bounded search found these fork-facing values outside the file. The search
does not prove completeness. Each value needs more work or an explicit decision.
None of them has migrated.

| Where | What | Why it is outside |
|---|---|---|
| `system_files/etc/bootc-installer/recipe.json:7-8` | Installer `imgref` / `local_imgref` default to `ghcr.io/tuna-os/tunaos:latest` | Not derived from `[build.publish]`: `90-image-info.sh:267-272` rewrites display text only and leaves `imgref` alone. ISO group builds write their own recipe with resolved image refs (`scripts/build-iso-group.sh:149-172`), so this default matters to the installer inside an installed image; no other rewrite was found |
| `system_files/etc/bootc-installer/recipe.json:26` | Installer help text names `repo.tunaos.org` | Literal text |
| `system_files/usr/libexec/tunaos-countme:19` | Adoption-count endpoint `countme.tunaos.org` | Hard-coded in the installed client |
| `system_files/etc/xdg/kscreenlockerrc:4` | KDE lock-screen wallpaper directory `TunaOS` | Literal path |
| `build_scripts/desktop/select-wallpaper.sh:24` | Wallpapers are chosen by file name (`<variant>-<desktop>.jpg`) | An asset convention with no TOML key. The retired preview's single shared-wallpaper override has no replacement |
| `build_scripts/10-base-packages.sh:28` and `20-packages.sh` | The inherited base package lists | Framework code (#3667): a fork adds over them, it does not replace or remove them |
| `image-versions.yaml:1`, `registry-map.yaml:1` | Tool and download pins, package ceilings, registry mirrors | Framework inputs; Renovate edits them |
| `build_scripts/desktop/tuna-flatpak-remote.sh:32` | Flathub remote setup | Framework mechanism; only the application set is in TOML |
| `scripts/build-image-inner.sh:148` | Layer-cache key hashes `build_scripts/**/*.sh` only | The generated `.env`/`.tsv` adapters are not in it, so a TOML-only edit may reuse a stale layer on a warm cache. The retired preview avoided this with `--no-cache`; the primary path never had that protection. Needs a maintainer decision because widening the key invalidates every warm cache once |
| `just/custom-overlay.just:7`, `custom/` | Personal overlay on a published image, with package removals and hooks | Kept deliberately: it is the only path for removals and hooks, which `tunaos.toml` refuses. It is not a fork-config interface |

Execution scripts, Containerfiles and checks remain code. Credentials are not
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

The example below is a schema sketch with current values, not a complete build
configuration. The complete file must contain every existing cell and policy.
Omitted variant flavors here are not a proposal to disable them. A variant's
`branding` is one inline table (accent, GNOME accent, base label, homage and
boot splash). Wallpapers and logos are not keys: they are files at fixed paths
under `system_files/`.

```toml
schema_version = 1

[project]
name = "TunaOS"
id = "tunaos"
cpe_vendor = "jamesreilly"

[build.publish]   # optional; omitted, CI publishes to ghcr.io/<repository owner>
registry = "ghcr.io"
namespace = "tuna-os"

[defaults.branding]
homepage = "https://github.com/tuna-os/tunaos"
documentation = "https://github.com/tuna-os/tunaos/tree/main/docs"
support = "https://github.com/tuna-os/tunaos/issues/"
bug_report = "https://github.com/tuna-os/tunaos/issues/"

[defaults.packages]
# Shared additions (implemented, #3668 F4): add, optional, repositories.
# Native names must be valid for every variant's package manager.
# add = ["htop"]
[variants.yellowfin]
emoji = "🐠"
description = "Based on AlmaLinux Kitten 10"
codename = "Thunnus albacares"
branding = { accent = "#FFC702", gnome_accent = "yellow", base = "AlmaLinux Kitten", homage = "the yellow petal of the AlmaLinux flower", plymouth = "tropical-fish" }
aliases = ["almalinux-kitten"]
platforms = ["linux/amd64", "linux/amd64/v2", "linux/arm64"]
base_image = "quay.io/almalinuxorg/almalinux-bootc:10-kitten@sha256:fabe22d605a5638cb1fbf2df38d6d9b9ace35f15cb1c10c7db87d475a039d58a"

[variants.yellowfin.packages]
# Put native RPM additions here rather than applying them to apt/portage cells.
# add = ["tree"]
# Package profiles preserve native package names and the current list order.
[desktops.gnome-debian]
display_manager = "gdm3"

[desktops.gnome-debian.packages]
apt = [
  "gnome-core", "gnome-disk-utility", "gnome-system-monitor", "nautilus",
  "xdg-desktop-portal-gnome", "xdg-desktop-portal-gtk", "xdg-user-dirs-gtk",
  "libglib2.0-dev-bin",
]
```

Common values live in defaults. Variant, desktop and exact-cell sections may
override declared fields. Scalar values replace more general values. Lists
must have explicit replace/add/remove semantics; do not silently reinterpret
an existing ordered package list as a set. Family-specific package names stay
family-specific. Selection never enables a held or unsupported cell.

## Protected package removal

Image-wide additions may move through the primary package resolver, but
removals remain rejected. A removal can cascade through boot, init, package
manager, desktop/session, networking or update/recovery dependencies. No static
list of denied packages can cover those packages across native families.

The [F4b specification for protected removal](../.spektacular/specs/20261024100000-protected-native-package-removal.md)
defines the approval boundary and the protected set from the contract. It also
defines qualification of native transactions per family, adversarial fixtures
and per-cell evidence. All of these must exist before a removal can be enabled.
The tool derives the protected set from the effective package and runtime
contracts in the exact build root, and no second package catalog holds it. The
gate fails closed on missing or stale evidence. Proof of image build, boot,
install, update and recovery stays separate from source tests and solver
dry-runs.

## Ordered migration

1. Record the ownership map and schema in the RFC/spec/plan. Inventory every
   relevant legacy reader and writer, including Renovate and workflow scripts.
2. Move the complete matrix into TOML. Generate the old adapter without losing
   any value, order, flag, alias, ISO group or rollout record. Add a read-only
   drift gate and `just config-generate` / `just config-check`. The generator marks the adapter as derived. Both local and CI builds validate it before consumption.
3. Move all desktop profiles and base/shared package policy, in reviewed groups.
   Compare the complete resolved package/repository operation sequence to the
   old path for every supported family and cell. Migrate the pins/mirror
   writers and Renovate at the same boundary as their generated adapters.
4. Move actual image identity, artwork and installer defaults. TunaOS's own
   values pass through the same compiler and consumers as customized values.
   Reuse the reviewed mechanisms in consumers and check final writers. No stock-only bypass remains.
5. Replace preview-only commands with the primary config interface. Preserve an explicit command to migrate legacy config and clear errors for incompatible inputs.
   Retire the obsolete source files and fork-only documentation. #3807 did this;
   see the steps to convert a [legacy fork config](#migrating-a-legacy-fork-config).
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

Each base-image pin has one authoritative entry under its variant. Shared external inputs and tools have separate named entries.
These entries do not repeat the base digest of any variant. Renovate edits the owning TOML entry. At runtime, generate adapters from that source. No bot commit of derived files is necessary.

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
the other cells of Tuna Desktop keep their existing display manager.

## Migrating a legacy fork config

The YAML preview (`resolve-fork-config.py`, `prepare-fork-config.py`, the
`examples/fork` templates, `manifests/fork-config.json` and the
`fork-branding.sh` / `fork-packages.sh` consumers) no longer exists. Nothing
reads its files. A legacy file (`schema_version: 1`, `catalog.sha256`, `image`,
`targets`, `global`, `overrides`) converts with one command:

```sh
python3 scripts/config.py migrate-fork-config --legacy OLD.yaml           # print the diff
python3 scripts/config.py migrate-fork-config --legacy OLD.yaml --write   # replace tunaos.toml
```

It needs PyYAML, reads `tunaos.toml` from the checkout (`--root` selects another),
applies the legacy delta to it and prints a unified diff. The primary file has no
catalog beneath it, so the migration edits the file itself.

| Legacy field | Becomes |
|---|---|
| `image.registry`, `image.namespace` | `[build.publish]` |
| `global.branding.homepage`, `documentation`, `support` | the same keys in `[defaults.branding]` |
| `global.packages.add`, `optional`, `repositories` | `[defaults.packages]` |
| `overrides.variants.<id>.packages` | `[variants.<id>.packages]` |
| `catalog.sha256` | dropped after a shape check; **not** verified against the checkout |

The command refuses everything else. It prints an `ERROR:` that names the field,
exits non-zero and changes no file. It refuses `targets` (the build filter of the
preview; prune with `build_image = false`, see
[ROLL_YOUR_OWN.md](ROLL_YOUR_OWN.md)), `branding.name`, `logo` and `wallpaper`.
It refuses brand data below the global layer, package layers for one desktop or
one exact cell, and every non-empty `remove` list. Unknown keys, wrong types,
duplicate YAML keys, a wrong `schema_version` and a missing `catalog` fail the
same way.

The primary validator parses the result. It checks each package name against
the package manager of its variant. A legacy global `add = ["htop"]` that the
Gentoo variant cannot install fails, and the command does not write it.

The output is deterministic. It keeps every comment and the layout of the rest of
the file. The command inserts new tables after the keys they extend and replaces
URL lines in place. The edited text must parse to exactly the original document
plus the legacy fields. If it does not, the command writes nothing.

Limits: the command drops an inline comment on a replaced value line. It refuses
a package table that already exists with different contents and does not merge
it. `bug_report` has no legacy field and keeps its value. The conversion changes
configuration only. It is no evidence that an image builds, boots or installs
(#3474).

## F5: Fork recipe and conformance gate (#3806)

**Scope**: configuration resolution of a fork that edits only `tunaos.toml` and
asset files. **Does not include**: image builds, installs or boot qualification
(#3474).

`tests/test_fork_recipe_conformance.py` forks the real `tunaos.toml` with text
edits that a person would make: publish destination, project name, homepage,
package additions for one variant, and one Flatpak. It runs the tools of the
repository on the result. These are `scripts/config.py validate`, the
`generate-*` adapter writers and the shell publish-destination resolver. The
test asserts these points:

1. **Stock does not change**: every committed adapter (`identity.env`,
   `variant-identity.tsv`, `variant-aliases.tsv`, `image-packages.tsv`,
   `flatpak-preinstall.tsv`) equals a fresh render of `tunaos.toml`. Stock has no
   publish table or package additions.
2. **The fork differs**: destination, identity, package rows and Flatpak list
   change as edited. Only the variant that declared the packages gets them.
3. **Undo the edits**: the stock bytes and adapters come back exactly.
4. **Code is not configuration**: the test rejects a `[hooks]` table, shell
   metacharacters or URLs in package names, and `remove` lists. It checks each
   package name against the package manager of its variant.
5. **Assets travel with the config**: `check-drawn-artwork` reports a new
   boot-splash theme name as missing until its theme files exist.

Native names in `[defaults.packages]` must be valid for every variant's package
manager, so the sample scopes them to a dnf variant. The test does not build an
image, and it is not yet a CI-only gate: it runs with the rest of `tests/`.

### Conformance boundaries

**#3806 owns** the fixture and the resolution assertions above. **#3474 owns**
image build, install and boot proof for the Yellowfin (RPM) and Grouper (APT)
reference journeys.
