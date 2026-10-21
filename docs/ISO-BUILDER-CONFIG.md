# ISO Builder presentation configuration v1

Edit `[iso_builder]` in root `tunaos.toml` for TunaOS. Export it with:

```sh
python3 scripts/config.py generate-builder-config
python3 scripts/config.py check-builder-config
```

The exporter writes `docs/iso-builder.config.json`; this is not a second source.
`just check` and a test in pytest reject changes that do not match TOML.
`--output PATH` exports or checks another deployment artifact without a change to
source ownership. Stock outputs stay inside the resolved checkout, including when
the checkout path is a symlink. An explicit output path selects its own directory.
Both modes reject symlinks and nonregular files at the final output path.

Consumers may generate a JavaScript projection for the browser from this JSON; they must check that projection for drift too.

Other projects can produce the same portable JSON from their own configuration.
They do not need a TunaOS matrix or repository at runtime. `iso-builder-config.schema.json` defines the shape. The dependency-free reference validator is
`scripts/lib/iso_builder_config.py:validate`; it adds unique-ID and reference
checks beyond JSON Schema. The primary projection also checks variant IDs and
that the configured default is a build-enabled matrix cell.

## Fields and boundaries

- `schema_version` is integer `1`; unknown fields and versions are errors.
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
Hosts use ASCII DNS names or canonical dotted IPv4. Use punycode for international
names. The contract does not support IPv6 or encoded hosts.
DNS labels have at most 63 characters; the host has at most 253.
The optional port is 443.

The contract allows HTTPS paths, queries, and fragments.
See [RFC 3986](https://www.rfc-editor.org/rfc/rfc3986#section-3.2.2) for decimal IPv4 syntax.
Other numeric forms that browsers normalize do not pass validation.
The pattern also rejects whitespace as defined by either Python or ECMAScript.

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

## Image reference syntax

Image defaults use the path and DNS label rules from [distribution/reference v0.6.0](https://github.com/distribution/reference/blob/v0.6.0/regexp.go).
The existing portable scope stays lowercase DNS or IPv4 hosts, with optional numeric ports. IPv6 and uppercase hosts remain outside this scope.

A tag, a SHA-256 digest, or both are required. Path atoms can contain letters and digits.
One or two underscores and repeated hyphens can separate these atoms.

The shared fixture at `tests/fixtures/builder-config-image-references.json` checks Python, JSON Schema and browser validation.
Syntax checks do not grant registry access or qualify an image.
