# Search upstream base-image packages

The optional `package_catalogs` table in `tunaos.toml` describes sources for the
search tool. It does not change image builds or installer trust.
The first adapter is for Debian trixie in the pinned flounder base on `linux/amd64`.
It needs an installed GnuPG executable. The command does not install tools.

```sh
python3 scripts/search-base-packages.py htop --catalog debian-trixie \
  --variant flounder --release trixie --platform linux/amd64
```

The command shows names from all three declared repositories.
All sources must pass checks before the command prints a result. A missing source,
expired metadata, changed image digest, invalid signature, or unsupported target
fails the search. There is no add or write option. Index presence does not prove
that a package can be installed, that dependencies resolve, or that an image boots.

## Scope and remaining work

Coverage is `base-image-only`. Output reports `cell_coverage_complete: false` and
`add_supported: false`. It does not qualify a built desktop or a shared package
policy. The existing offline receipt-backed editor remains a separate command.

`build_scripts/20-packages.sh` adds Tailscale's trixie repository and downloads its
key during the Debian build. This search does not cover that repository. A full
resolver must model and verify this source and its trust ownership first.
`Containerfile.debian` also copies shared files from the selected common image.
The GNOME stage copies its Bluefin files.

The inspected shared layer had no apt sources or key files. This observation does
not cover future digests, environment overrides, GNOME files, or later build
scripts. A full resolver must account for desktop sources and later overlays
before it can enable add.

Other families, releases, and architectures fail closed. They need native
metadata adapters, explicit trust provenance, source observations, and tests.
The tool does not infer names from similar names. Gentoo needs category-qualified
names in the offline editor.

## Trust and freshness

The reviewed observation binds the immutable OCI index, platform manifest,
layer identities, source-file inventory, OS identity, and public key bytes.
The configuration pins its hash. Reviewers verify these extraction claims;
the observation has no signature. The verifier checks signatures from repositories
against the pinned public keys and full primary fingerprints.
See [public key provenance](../config/package-keys/README.md).

Acquisition uses bounded HTTPS reads and native paths with SHA-256 hashes.
XZ expansion and decoder memory have limits. The verifier has an isolated home.
The adapter accepts the observed RSA and EdDSA algorithms with SHA-2 digests.
Network requests use a thirty-second socket timeout and elapsed-time checks
between reads. This does not impose a hard deadline on the whole request.

The tool never fetches keys or changes system trust. All declared sources must
finish successfully. Trust the configuration and its parent directory before use.
The tool does not protect against hostile filesystem changes by the same user.

Debian stable metadata can omit `Valid-Until`. The observation pins its exact
signed envelope without an arbitrary age limit. This does not prove that a newer
point release is unavailable. Updates and security need signed expiry and expire
no later than seven days after their signed date.

The tool also enforces any signed expiry on base metadata. It rejects dates over
ten seconds in the future. Correct local time is necessary. Fresh repository
metadata does not prove that the installed base image has received updates.

## Refresh contract

After an image change, lookup fails until you refresh its observation.
Structural configuration validation and builds do not check network or freshness.
This first slice has no automatic refresh command. Refresh needs an explicit
reviewed change to the config and observation.

Inspect the exact new OCI image and source inventory. Verify its public trust
material, authenticate all declared metadata, and record the hashes. A source or
key change needs separate review. A failed signature must never cause the tool
to replace keys automatically.

A future refresh command should emit a preview-bound patch and receipt.
The apply step must revalidate the exact original config, image, source inventory,
and signed metadata. An explicit write flag authorizes that exact patch; it does
not establish that a person reviewed it. Trust and source identity changes must
remain separate.
