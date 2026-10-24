# Primary configuration wiring

Edit `tunaos.toml`. Its comments describe the implemented schema, not the
future interface in [the migration plan](PRIMARY-CONFIG-MIGRATION.md).
The repeated variant and desktop records share the contracts at the start
of their sections. Unknown fields are errors; they do not enable features.

## Inputs and consumers

| Input | Generated adapter / reader | Effect |
|---|---|---|
| `build`, `variants`, `iso_groups`, `sibling_images`, `tuna_rollout` | `scripts/lib/tunaos_config.py:matrix` → `.github/build-config.yml` | Build selection and reporting; not proof of publication or boot qualification |
| `build.publish` | `scripts/lib/publish-destination.sh`, `.github/workflows/build-variant.yml` | Registry/namespace selection; credentials and permissions remain separate |
| Variant `base_image` | `scripts/get-base-image.sh` | Base image used by the build; Renovate edits the TOML pin |
| Variant/flavor IDs and stages | `scripts/resolve-flavor.sh`, `.github/workflows/build-variant.yml` | Existing Containerfile routing and workflow stages; adding a name does not implement a new route |
| `package_groups`, `desktops` | `scripts/lib/tunaos_packages.py:desktop_outputs` → `manifests/desktops/*.yaml` → `build_scripts/desktop/install-desktop.sh` | Desktop packages, repositories, greeter and named operations during image construction |
| `flavor_metadata` | `scripts/config.py generate-builder-flavors` → `docs/iso-builder.flavors.json` | Exact desktop/edition labels, not inferred from suffixes |
| `iso_builder` | `scripts/config.py generate-builder-config` → `docs/iso-builder.config.json` | Browser presentation and default choices; catalog evidence still controls availability |
| `flatpak_preinstall` | `scripts/config.py generate-flatpak-policy` → `build_scripts/desktop/flatpak-preinstall.tsv` → `build_scripts/desktop/flatpak-preinstall.sh` | Image preinstall declarations; not a new remote or installed inventory |
| `package_catalogs` | `scripts/search-base-packages.py`, `scripts/lib/package_catalogs.py`, `scripts/lib/signed_apt.py` | Signed Debian Trixie amd64 base-index search only; no config write or package transaction |

Run `python3 scripts/config.py validate` before generation. Run
`python3 scripts/config.py generate` for the matrix and desktop adapters.
The three other export commands above have corresponding `check-*` commands.
`just check` runs generation and those drift checks. Do not hand-edit adapters.

The contract for Debian packages hashes the **TOML bytes**, including comments. A comment edit therefore changes that provenance hash even when the
resolved package list and generated matrix are identical. Regenerate the contract;
do not copy an old receipt to the new source. Source parity is not image validation.

## Package fields and limits

Package names differ between native families. The family schema is in
`scripts/lib/tunaos_packages.py:validate`. With `expand`, included lists come before local entries, without deduplication. The installer selects an
existing `-debian` or `-arch` profile instead of the generic profile, not on top of it.

Repository records have different shapes:

- apt: `name`, `uri`, `suite`, `keyring_url`, optional `condition`.
  Conditions are `ubuntu`, `debian-sid` or `debian-trixie`.
- cachyos: `name`, `url`.
- RPM families and zypper: `name`, `baseurl`, optional positive `priority`
  and boolean `unsigned`. Only the local mounts from reviewed OCI images can use unsigned sources.
  This is not a remote trust bypass.
- apt PPA: `repo` in `ppa:owner/archive` form and `condition="ubuntu"`.
- RPM-family COPR: `repo` in `owner/project` form, `packages`, optional `options`.
  The installer enables the source for listed add-ons, not an entire desktop stack.

Package requests are not installed-inventory evidence. In particular, the DNF
consumer has best-effort groups, optional packages and COPR paths, and Hummingbird
records requests for unavailable packages. Validate the built image as well as the source.
IDs for trusted operations expand through `scripts/lib/desktop_operations.json`;
the config cannot define a new shell operation. Keep repository credentials out
of URLs and this public file.

## Editing without losing comments

Use [the package editor](PACKAGE-AUTHORING.md) for existing desktop-family
policy targets. It uses the pinned `tomlkit` editor, validates the edited document
with the shared parser and writes atomically after a concurrent-edit check.
`add` previews by default; review its diff before `--write`. A repeated addition
is a no-op. Search receipts are not proofs of transaction solvability.

Renovate's `tunaos.toml` custom regex manager in `renovate.json` matches the
`base_image` assignment only. Keep each assignment on one line, with its quoted
`name:tag@sha256:digest` shape. Comments may precede the assignment or follow its
final quote. The regression checks the configured match boundary and digest
replacement; it is not an execution of Renovate's remote service.

Do not round-trip the primary file through JSON/YAML or a generic TOML serializer:
those formats/editors need not preserve comments. Generated adapters intentionally
do not carry all source comments. There is no CLI to update every field.

## Still outside this interface

The main schema documented here does not accept identity for the installed project, variant
artwork, installer appearance or image-wide package additions/removals.
See #3668 for this work; proposed fields in stacked PRs are not a usable
main-branch contract. Do not add `[project]`, `[defaults.branding]` or
`[defaults.packages]` based on a design sketch.

Build mechanisms, Containerfiles, tool/download pins in `image-versions.yaml`,
registry mirrors in `registry-map.yaml`, credentials and CI permissions remain
separate. An edit to this TOML does not reconfigure an already installed machine,
create registry credentials, publish an ISO, or qualify a new hardware target.
