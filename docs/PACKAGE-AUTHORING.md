# Offline package authoring

`scripts/config-packages.py` searches indexes from native repositories and adds exact
package names to explicit policies in `tunaos.toml`. One invocation resolves all
selected targets before it changes anything. It uses the build configuration
validator and existing package-group expansion. It preserves comments, order
and unrelated configuration through an optional lossless editor with a version pin.

This is the first **offline, index-backed** slice of the plan in
[PRIMARY-CONFIG-MIGRATION.md](PRIMARY-CONFIG-MIGRATION.md). It is not automatic
repository discovery, all-base verification or an installation solver. It never
runs a package manager, downloads an index, installs a package, or executes an
ebuild. You can still edit TOML manually.

## Install and choose the exact scope

```sh
python3 -m pip install -r requirements-package-authoring.txt
python3 scripts/config-packages.py search htop \
  --target gnome:apt --index gnome:apt=/path/to/apt-receipt.json
python3 scripts/config-packages.py add htop \
  --target gnome:apt --index gnome:apt=/path/to/apt-receipt.json \
  --target gnome:emerge --index gnome:emerge=/path/to/gentoo-receipt.json \
  --dry-run
```

Review the printed native resolutions, source receipts and diff. Repeat with
`--write` instead of `--dry-run` to validate and replace the file atomically.
Without either flag, `add` only previews. Use `--config /path/to/tunaos.toml` for
a fork or a local copy. A repeat command makes no change. This also applies when a package group
already has the exact name.

A target is an **existing desktop profile and native family**, not a variant.
For Arch-specific Tuna Desktop, select `tuna-arch:pacman`, not `tuna:pacman`:
the runtime resolver prefers the `-arch` profile. Debian may similarly select a
`-debian` profile. Inspect the declarations and runtime selection before you edit.
The command does not create, infer or skip targets.

Every target needs its own receipt assignment. Choose a shared apt or EL policy
only if you intend to affect that shared scope.
The command does not prove coverage of the other consumers of that policy.

This change does not add `htop` to the shipped config. A Gentoo
index with only `sys-process/htop` for the basename `htop` resolves to that
full atom. Two categories with that basename are an error; select an exact atom
with `--native gnome:emerge=sys-process/htop`.

For an actual cross-base rename,
use `--native TARGET=verified-native-name`; it must exist in that target's index.
Ordinary add matches are exact names. Search finds partial names and preserves case. Similar names never become
automatic mappings.

## Supply a repository-index receipt

Get metadata through your existing trusted repository synchronization and
signature-verification process. Use the same release and architecture as the
intended build. Do not use a host package list as evidence for another base.
Then create a JSON receipt beside the downloaded metadata, for example:

```json
{
  "schema_version": 1,
  "family": "apt",
  "format": "apt-packages",
  "repository": "https://deb.debian.org/debian/dists/trixie/main/binary-amd64/Packages.xz",
  "release": "trixie",
  "architecture": "amd64",
  "retrieved_at": "2026-10-21T00:00:00Z",
  "path": "Packages.xz",
  "sha256": "REPLACE_WITH_SHA256_OF_THE_EXACT_DOWNLOADED_BYTES"
}
```

Replace the timestamp with the time of retrieval in UTC; get the digest with
`sha256sum Packages.xz` (or `shasum -a 256 Packages.xz` on macOS). Paths are relative
to the receipt, or absolute. Supply every field shown. An unknown field or schema version causes an error.

The command checks family/format, supported native
architecture, timestamp and byte digest. It prints source, release, architecture,
retrieval time and hash with results. Receipts older than seven days, or dated in
the future, fail; `--max-age-days N` explicitly changes the age budget.

These receipts are **operator assertions, not signed attestations**. SHA-256
binds the bytes to the receipt; it does not authenticate the publisher, prove
freshness, or bind the URL/release to the config. The operator must check trust and signatures. This command does not fetch remote URLs.
A new timestamp does not refresh an index.

## Native index support and limits

| Policy families | Format | Input | Architecture selection |
|---|---|---|---|
| `apt` | `apt-packages` | Debian/Ubuntu `Packages`, optionally gzip/xz/bzip2 | `amd64` or `arm64`, plus `all` |
| `fedora`, `rawhide`, `hummingbird`, `eln`, `el10`, `zypper` | `rpm-primary` | RPM-MD `primary.xml`, optionally gzip/xz/bzip2 | `x86_64` or `aarch64`, plus `noarch` |
| `pacman`, `cachyos` | `pacman-db` | Repository `.db` tar, optionally gzip/xz/bzip2 | `x86_64` or `aarch64`, plus `any` |
| `emerge` | `gentoo-tree` | Repository tree tar with `category/package/package-version.ebuild` entries | `source` only; no keyword/architecture claim |

The command reads archives in memory without extraction. It limits compressed and
decompressed inputs to 128 MiB. Limit the scope of large snapshots upstream.
Malformed or empty indexes fail.

Receipts have a 64 KiB limit; configs have an 8 MiB limit.
All inputs must be regular files. Convert unsupported codecs (including zstd) with trusted local tools before you
create the receipt.

RPM source packages and foreign-architecture binaries do not count as matches.
A Gentoo ebuild's presence does not prove stable keywords, masks, USE flags, binary
availability or dependency solvability. No adapter verifies dependencies, package
versions, repository priority, signatures or installability.

All native-format readers have synthetic fixture tests, including category
ambiguity, wrong architecture, malformed sources and atomic failure. These tests
are not live repository or built-image qualification. In particular, a match in
Fedora says nothing about Hummingbird or EL10; each needs its own measured index.
Automatic configured-repository collection, multi-repository coverage, per-cell
release/platform binding, portable intent mappings and transaction checks remain
future work. This command deliberately makes no claim that all configured bases
can install an added package.

## Write safety

Resolution, TOML parse/schema validation and semantic comparison finish before
any write. Failed targets do not leave partial updates. Reconcile the exclusions manually.

DNF policies also check name globs from shared
package groups. Other native families keep literal-name checks.
Escape or locale-class syntax in DNF exclusions needs a native check.
The editor rejects that syntax.

The command preserves the original mode.
It flushes a temporary file in the same directory, then atomically renames it.
It also flushes the directory.

The edited output must fit the same 8 MiB limit.

A persistent hidden `.NAME.packages.lock` serializes these commands.
Do not remove that lock while a command runs.

If the command detects a concurrent edit, it fails. Generate a fresh preview.
Other editors do not honor this advisory lock; do not edit concurrently.
Use a trusted parent directory. This is not protection against hostile
writes by another process with the same user ID.
The command refuses symlink and hard-linked config targets.

An error can occur after rename if the filesystem cannot guarantee a durable write.
The error then states `file replaced; durability unconfirmed`.
Inspect the config before you retry.
