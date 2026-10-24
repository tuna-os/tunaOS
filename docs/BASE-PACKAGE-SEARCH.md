# Search configured target packages

The optional `package_catalogs` table in `tunaos.toml` describes read-only,
trusted package-index collectors. It does not change image builds, package
policy, or installer trust.

The supported adapter covers the complete configured repository set for the
`flounder` `base`, `kde`, and `xfce` targets on `linux/amd64`: the three
repositories observed in the pinned Debian trixie base plus the Tailscale
repository added by `build_scripts/20-packages.sh`. Those desktop profiles add
no repositories. GnuPG must already be installed; the command never installs it.

```sh
python3 scripts/search-base-packages.py htop \
  --catalog debian-trixie --variant flounder --flavor kde \
  --release trixie --platform linux/amd64
```

All four sources must authenticate before the command prints any result. Each
source reports its role, metadata URL, signed release, native architecture,
signed and retrieval timestamps, metadata and index SHA-256 digests, signers,
and freshness result. The Tailscale source also reports the fetched declaration
and trust-key digests after both match the reviewed bytes. A missing source,
stale metadata, changed image or configuration file, invalid signature, wrong
release or architecture, partial index, or unsupported target fails the whole
search. There is no add or write option.

`configuration_observed_at` identifies the reviewed extraction that binds the
collector to the effective target. The observation pins
`Containerfile.debian`, `build_scripts/20-packages.sh`,
`build_scripts/desktop/install-desktop.sh`, `scripts/build-image-inner.sh`, and
`image-versions.yaml`; inventories copied APT source/trust files under
`system_files`; and records the resolved digest-pinned common image whose
`/system_files/shared` tree is copied into the target. The collector also reads
the selected desktop policy from the same parsed `tunaos.toml`. A changed source
path, source script, copied inventory, common image, enabled target, or
applicable desktop repository requires a reviewed observation and adapter
update. Catalog assertions alone do not make a repository part of an
authenticated target.

## Native adapter inventory

Offline package-index parsing and trusted collection are separate capabilities.
The authoring parser can read all formats below, but only the listed collector
may fetch and authenticate configured repositories.

| Native manager | Index format | Trusted configured-source collector |
|---|---|---|
| apt | Debian `Packages` | Supported for reviewed flounder trixie `base`/`kde`/`xfce`, amd64 |
| dnf | RPM `primary.xml` | Unsupported; no repository-set/trust adapter |
| pacman | repository database | Unsupported; no repository-set/trust adapter |
| zypper | RPM `primary.xml` | Unsupported; no repository-set/trust adapter |
| portage | Gentoo ebuild tree | Unsupported; no repository-set/trust adapter and ebuilds are never executed |

Other Flounder flavors also fail closed. `tuna` adds Tideforge, NVIDIA flavors
enable additional Debian components, disabled GNOME is not an enabled build
target, and Asahi mutates sources in an overlay. Each needs its own reviewed
source-set coverage before the collector may claim a complete target.

## Scope

Output reports `coverage: configured-target`,
`cell_coverage_complete: true`, and `add_supported: false`. Complete means that
the collector authenticated every package repository configured for the
selected target; it does not mean that dependencies solve, a transaction
succeeds, a package is installed, or an image boots. Search never invokes apt,
installs packages, executes ebuilds, or edits configuration. Transaction and
installed-package receipts remain separate downstream checks.

The bootc toolchain and other downloaded build artifacts are not package
repositories and are outside this index collector. A later overlay or a runtime
repository is likewise not silently attributed to these stage-1/stage-2
targets.

## Trust and freshness

The base observation binds the immutable OCI index, platform manifest, layer
identities, source-file inventory, OS identity, and Debian public key bytes.
The target observation binds the reviewed build-source extraction and source
configuration files. Both observations are hash-pinned in `tunaos.toml`; they
are reviewed extraction claims, not signatures.

Repository metadata is independently verified against vendored public key
bytes and full primary fingerprints. See
[public key provenance](../config/package-keys/README.md). For the mutable
Tailscale endpoints, search performs bounded reads of the declaration and
public key and requires byte identity with the reviewed hashes before trusting
the signed metadata. It never imports fetched keys into a user keyring or
changes system trust.

Acquisition uses bounded HTTPS reads restricted to reviewed hosts. Debian
indexes use signed SHA-256 by-hash paths. Tailscale does not publish by-hash, so
its direct `Packages.gz` paths must match the size and SHA-256 in the verified
InRelease. XZ output/dictionary and gzip output have explicit limits. Every
source completes before any output is emitted.

Debian stable metadata can omit `Valid-Until`; the base observation pins its
exact signed envelope. Debian updates and security require signed expiry and
expire no later than seven days after signed `Date`. Tailscale publishes no
`Valid-Until`; its signed `Date` has a seven-day maximum age. All sources reject
dates over ten seconds in the future. Correct local time is required.

## Refresh contract

After an image or effective package-source configuration change, lookup fails
until its observations are reviewed and refreshed. Structural configuration
validation and image builds do not perform network or freshness checks.

Refresh is intentionally manual: inspect the exact OCI image and effective
source inventory, verify public trust material, authenticate all metadata, and
record the new identities. A source or key change needs separate review. A
failed signature never triggers key retrieval. The collector has no write or
automatic trust-refresh path.
