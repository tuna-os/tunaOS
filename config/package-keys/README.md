# Public lookup trust material

`debian-trixie.pgp` is the public Debian archive keyring from the exact flounder
base image in `config/package-observations/flounder-amd64.json`. Its SHA-256 is
`506b815cbb32d9b6066b4a2aa524071e071761e7e7f68c3ac74f3061ba852017`.
The observation records the verified OCI index, amd64 manifest, layer digest,
source files and keyring bytes. No image code was run to collect these files.

The catalog permits only the declared primary fingerprints, including valid
signing subkeys. Other certificates in this archive keyring do not become lookup
trust roots. Search never installs the file into system trust or imports it into
a user keyring. A key change needs a separate review; a failed signature does not
trigger key retrieval.

`tailscale-trixie.gpg` is the public package signing key served by the exact
source URL configured in `build_scripts/20-packages.sh`:
`https://pkgs.tailscale.com/stable/debian/trixie.noarmor.gpg`. Its SHA-256 is
`3e03dacf222698c60b8e2f990b809ca1b3e104de127767864284e6c228f1fb39`;
the allowed primary fingerprint is
`2596A99EAAB33821893C0A79458CA832957F5868`. The reviewed target observation
binds that source claim to the source-configuration files. The key remains
lookup-only and is never installed or imported. The collector fetches the
declared URL only to require byte identity with these reviewed bytes before
trusting metadata.

The Tailscale InRelease fixture under `tests/fixtures/package-catalog` was
retrieved from
`https://pkgs.tailscale.com/stable/debian/dists/trixie/InRelease` on
2026-10-24. Its SHA-256 is
`65b731b93c7cdbdd84d90bdc665b0162d34affda38e59b24423277b8b31a17b9`.
It is deterministic signature/format evidence, not a current freshness claim.

Debian's `debian-archive-keyring` copyright file states that the keys themselves
are not copyrighted. No GPL package support scripts are included here.
GnuPG is a separately installed native verifier; this repository does not vendor
or install it. Debian archive authentication and key provenance are described at:

- https://ftp-master.debian.org/keys.html
- https://manpages.debian.org/trixie/apt/apt-secure.8.en.html
- https://sources.debian.org/src/debian-archive-keyring/

The public InRelease fixture under `tests/fixtures/package-catalog` is the frozen
Debian trixie signed metadata with SHA-256
`0584fba32e13e0ab8285fb16c27adea1ec03a73669c18702821094fd6ca86675`.
It contains archive identity and checksum facts, not package payloads. Tests use
it for real signature/tamper checks without network access. It is not a freshness
claim: dynamic updates/security metadata must pass current signed expiry checks.
