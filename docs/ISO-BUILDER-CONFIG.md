# ISO Builder presentation configuration

Edit `[iso_builder]` in root `tunaos.toml` for TunaOS. Export it with:

```sh
python3 scripts/config.py generate-builder-config
python3 scripts/config.py check-builder-config
```

The exporter writes `docs/iso-builder.config.json`; this is not a second source.
`just check` and a test in pytest reject changes that do not match TOML.
`--output PATH` exports or checks another deployment artifact without a change to
source ownership. Consumers may generate a JavaScript projection for the browser from this JSON; they must check that projection for drift too.

Other projects can produce the same portable JSON from their own configuration.
They do not need a TunaOS matrix or repository at runtime. `iso-builder-config.schema.json` defines the shape. The dependency-free reference validator is
`scripts/lib/iso_builder_config.py:validate`; it adds unique-ID and reference
checks beyond JSON Schema. The primary projection also checks variant IDs and
that the configured default is a build-enabled matrix cell.

## Version 1 compatibility fields

The current primary config uses version 2, described below. The validator also
accepts version 1 with these fields. Unknown fields and versions are errors.

- `schema_version` is integer `1` for this compatibility contract.
- `preview_only` is a required boolean. `true` disables inspection, automatic
  inspection, and build entry points. `false` grants no new build permission.
- `brand` owns name, homepage, documentation, optional support/disclaimer and
  optional logo/favicon. Missing assets must clear assets from the previous project.
- `presentation` owns headline, intro and a CSS accent with six hex digits.
- `output` owns a volume label for the ISO in uppercase (maximum 32 characters).
  It also owns a filename prefix in lowercase (maximum 64 characters).
- `desktops` and `variants` define presentation lists in order. Desktop entries
  also own app defaults. IDs must be unique. App IDs must be unique and valid.
- `default_selection` is either a catalog cell (`variant`, `flavor`, `platform`)
  or an external image (`image`, `platform`). A catalog default must reference
  a configured desktop ID and variant ID. An image default follows the existing
  custom-image inspection path; configuration does not qualify it.
- `curated_app_sets` supplies app-list URLs and their explicit `brewfile` or
  `preinstall` format. Desktop references must exist in `desktops`.
- Optional `ddi_channels` preserves existing DDI choices: ID, image stem, name
  and desktop ID (or `none`). It cannot change the DDI transport endpoint.

Links use HTTPS with no credentials, whitespace, backslashes or custom ports.
Logo/favicon may instead use asset paths relative to the root (no `//`, `..`,
query, fragment or backslash). A configured URL does not authorize a new proxy,
relay, registry, Flatpak remote, icon host or arbitrary fetch mechanism.

## Consumer requirements

Load one deployment-owned, validated configuration. Do not accept config URLs
from query parameters. Missing, malformed or unsupported configuration must
show an explicit error and prevent builds; never substitute values from the stock brand.

CatalogSnapshot v1 remains the only authority for catalog target identity,
publication, availability, provenance and qualification. Intersect configured
variant/desktop choices with catalog-admitted choices. Do not synthesize catalog
entries from this file. Preserve catalog architecture and hardware gates. If a
configured default is absent from admitted choices, leave the selection empty
and explain why. Never silently select a different product.

Preview examples must use `preview_only = true` and an affiliation disclaimer.
They exercise the same UI engine, but do not claim installation support.

## Migration scope

This is the current ISO Builder presentation/default slice only. It does not
complete the migration of source brand values, installed desktop identity, wallpaper, installer
brand values, registry policy, or shared/base package migration. Those remain in
`PRIMARY-CONFIG-MIGRATION.md`; this slice does not claim a source contract for them.

## Guided selection v2

Version 2 replaces `variants` and desktop display text with `selection.facets`.
The `desktops` array retains only each ID and its default Flatpaks. This keeps
one editable source for labels and one for app policy. Existing v1 documents
remain accepted explicitly; a frozen fixture checks the v1 contract.
A v1 consumer must reject v2 and must not ignore the new fields.

`selection.paths` defines one to four question orders. `default_path` references
one of those IDs. `facets` contains the labels and ordered value subsets for
family, base, desktop, hardware, platform, graphics, edition, gaming_mode, channel or graphics_generation. A value can have a description and a card with safe `image_url`,
`image_alt` and optional plain-text `badge`. Paths and facet values have unique
IDs.

`recommendations` has at most eight leaf IDs, labels and reasons.
`default_selection` is either `{kind: "leaf", leaf_id: "..."}` or `{kind: "none"}`.
No image reference belongs in this presentation document.

`presentation.colors` is optional. It needs these colors in hex: background, surface,
text, muted, accent and accent_text. Consumers apply these as fixed theme tokens.
Optional border, hover_surface, focus and selected_surface tokens also use hex colors.
They never evaluate arbitrary CSS.

The optional `choice_style` accepts illustrated or thumbnail; illustrated is the default.
The optional `font_family` is system, inter or dm-sans; system is the default.
Fonts must come from reviewed local bundles with a verified license.
The config cannot supply a font URL.

 Existing asset URL restrictions apply to card
images. Selection text is plain single-line text with at most 2048 characters.

The primary `[flavor_metadata.<exact-flavor-id>]` tables own desktop and edition
semantics. They cover every primary flavor exactly; consumers must not split a
flavor name to infer its desktop. `scripts/config.py generate-builder-flavors`
exports the sorted portable `docs/iso-builder.flavors.json` artifact.
`check-builder-flavors` detects drift and does not write. The normal check runs both
builder drift gates. The metadata has schema_version 1, kind
`builder-flavor-metadata`, and flavors with ID, desktop and edition fields.

The repository for ISO Builder owns its CatalogSnapshot. It imports reviewed config
and flavor metadata bytes at an immutable source commit, then generates its
GuidedCatalog from that exact local snapshot. The source repository does not
copy a snapshot or fetch a moving branch.

Each leaf uses the existing targetKey. It derives base, platform and hardware
from the joined target. Desktop and edition come from the imported metadata
for that exact flavor.
The projection binds snapshotDigest. A mismatch causes an error. A flavor without metadata also causes an error.

The validator checks references within the portable config. The primary export also checks each default and recommendation. Each ID must
name a cell enabled for builds. Its base, platform, desktop and edition must
pass the configured filters. The deployment join checks other facets, including
hardware, and every referenced leaf against its actual guided catalog. An absent default or explicit
choice becomes a visible unavailable selection; it never selects another row.

Review selection needs availability and must meet the existing policy for offered images.
Execution must pass the existing gate for qualification. Recommendations grant
no qualification, and preview leaves never enter image inspection or build APIs.
