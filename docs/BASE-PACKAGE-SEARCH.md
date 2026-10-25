# Search configured target packages

The optional `package_catalogs` table in `tunaos.toml` describes read-only,
trusted package-index collectors. It does not change image builds, package
policy, or installer trust.

The supported adapter covers the whole repository set of the `flounder` `base`,
`kde`, and `xfce` targets on `linux/amd64`. That set is the three repositories
seen in the Debian trixie base (pinned), and the Tailscale repository that
`build_scripts/20-packages.sh` adds. Those desktop profiles add
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

`configuration_observed_at` names the reviewed extraction that binds the
collector to the effective target. The observation pins
`Containerfile.debian`, the invoked `build_scripts/10-base-packages.sh`, the
sourced `build_scripts/lib.sh`, `build_scripts/20-packages.sh` and
`build_scripts/desktop/install-desktop.sh` by file hash.

It pins two more inputs by extract hash, not file hash. The extract of
`scripts/build-image-inner.sh` is everything before its rechunk pass. The
extract of `image-versions.yaml` is the `common` image entry. Renovate edits the
other keys of that file daily, and no flounder stage uses them to set a package
source. `tests/test_package_catalogs.py` lists every reader of the file and
fails when a new one appears.

The observation lists
the APT source and trust files under `system_files`. It records the common image,
pinned by digest, whose `/system_files/shared` tree the build copies into the
target.

The collector also
reads the selected desktop policy from the same parsed `tunaos.toml`. If a
source path, source script, copied file, common image, enabled target, or
desktop repository changes, the observation and adapter need a reviewed update.
Catalog assertions alone do not make a repository part of an authenticated
target.

## Native adapter inventory

A package-index reader and trusted collection are separate
capabilities. The offline parser can read all formats below, but only the
listed collector may fetch and authenticate configured repositories.

| Native manager | Index format | Trusted configured-source collector |
|---|---|---|
| apt | Debian `Packages` | Supported for reviewed flounder trixie `base`/`kde`/`xfce`, amd64 |
| dnf | RPM `primary.xml` | Unsupported; no repository-set/trust adapter |
| pacman | repository database | Unsupported; no repository-set/trust adapter |
| zypper | RPM `primary.xml` | Unsupported; no repository-set/trust adapter |
| portage | Gentoo ebuild tree | Unsupported; no repository-set/trust adapter and ebuilds are never executed |

Other Flounder flavors also fail closed. `tuna` adds Tideforge. NVIDIA flavors
enable more Debian components. Disabled GNOME is not an enabled build target.
Asahi changes sources in an overlay. Each needs its own reviewed source-set
coverage before the collector may claim a complete target.

## Scope

Output reports `coverage: configured-target`,
`cell_coverage_complete: true`, and `add_supported: false`. Complete means that
the collector authenticated every package repository configured for the
selected target. It does not mean that dependencies solve, a transaction
succeeds, a package is installed, or an image boots. Search never invokes apt,
installs packages, executes ebuilds, or edits configuration. Transaction and
installed-package receipts remain separate downstream checks.

The bootc toolchain and other downloaded build artifacts are not package
repositories and are outside this index collector. A later overlay or a runtime
repository is likewise not silently attributed to these stage-1/stage-2
targets.

## Trust and freshness

The base observation binds the immutable OCI index, platform manifest, layer
identities, source-file inventory, OS identity, and the bytes of the Debian
public keys. The target observation binds the reviewed build-source extraction
and source configuration files. Both observations are hash-pinned in
`tunaos.toml`. Reviewers checked both extractions; they are claims, not
signatures.

The collector checks metadata of the repositories against the bytes of
vendored public keys and full primary fingerprints. See
[public key provenance](../config/package-keys/README.md). For the mutable
Tailscale endpoints, search does bounded reads of the declaration and public
key. It needs byte identity with the reviewed hashes before it accepts the
signed metadata. It never imports fetched keys into a user key store or
changes system trust.

Acquisition uses bounded HTTPS reads restricted to reviewed hosts. Debian
indexes use by-hash paths with signed SHA-256 digests. Tailscale does not
publish by-hash, so its direct `Packages.gz` paths must match the size and
SHA-256 in the verified InRelease. XZ output/dictionary and gzip output have
explicit limits. The collector emits output only after every source completes.

Debian stable metadata can omit `Valid-Until`; the base observation pins its
exact signed envelope. Debian updates and security metadata must have a signed
expiry, no later than seven days after the signed `Date`. Tailscale publishes no
`Valid-Until`; its signed `Date` has a seven-day maximum age. All sources reject
dates over ten seconds in the future. Correct local time is required.

## Refresh contract

After a change to the image or the effective package-source configuration,
lookup fails until a reviewer refreshes the observations. Structural
configuration validation and image builds do no network or freshness checks.

Refresh is intentionally manual. Inspect the exact OCI image and effective
source inventory, check the public trust material, authenticate all metadata, and
record the new identities. A source or key change needs separate review. A
failed signature never triggers key retrieval. The collector has no write or
automatic trust-refresh path.

A Renovate bump of any other `image-versions.yaml` key, or an edit to the
rechunk pass of `scripts/build-image-inner.sh`, needs no refresh. A bump of
the `common` digest, or an edit to the build-input part of that script,
needs a refresh. Compute the extract hashes with the `_CONFIGURATION_EXTRACTS`
functions in `scripts/lib/package_catalogs.py`, update `observed_at` and the
`target_observation_sha256` pin in `tunaos.toml`, and run
`python3 -m pytest tests/test_package_catalogs.py tests/test_search_base_packages.py`.
