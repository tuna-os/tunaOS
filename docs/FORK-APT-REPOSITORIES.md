# Fork APT repositories

Keep the existing three-field RPM declarations. For APT, use an explicit source
with suites, components and the SHA256 of the downloaded public key:

```yaml
packages:
  repositories:
    - type: apt
      id: tools
      url: https://packages.example.org/debian
      key_url: https://packages.example.org/signing-key.asc
      key_sha256: <64 lowercase hex digits from a reviewed key>
      suites: [noble, noble-updates]
      components: [main]
```

This is a schema example, not a live package source. Scope it to an APT
variant. The host rejects this type on RPM, Arch and Portage routes. Untyped RPM
sources do not become APT sources. Do not use flat repositories, remote includes, PPA
shorthand, unsigned sources and inline apt options.

Unknown keys fail. Lists must be nonempty with unique literal tokens.

The adapter downloads the key over HTTPS with size and time limits. Redirects
must also use HTTPS. It checks the exact hash before conversion with GnuPG.
The image needs curl and GnuPG; missing tools fail before source writes.
The adapter checks collisions for all sources and keys before it writes files.
It refuses symlinks and existing files with different bytes.

Each source gets `/etc/apt/sources.list.d/fork-<id>.sources`. Its `Signed-By`
field names only `/usr/share/keyrings/fork-<id>.gpg`. There is no global key
import. APT still checks signatures on repository metadata and package hashes.
A key hash pins the trusted key bytes; it does not pin the mutable package index.
Receipts retain the complete declaration and key hash.

## Strict fork transactions

Fork refreshes set `APT::Update::Error-Mode=any` and reject insecure metadata.
Fork installs use `--no-remove` and reject unauthenticated packages. If refresh fails, the adapter blocks installation and recovery. A failed install blocks the legacy recovery with forced dependencies and install retry. Required failures stop the build;
optional install failures remain explicit misses in the receipt. A failure to
verify or refresh a repository is fatal, including for optional packages.

The overrides apply only inside fork transactions. This change does not alter
stock wrappers or endorse their recovery policy. Other package families need
their own native solver evidence. Tests exercise the source files, key pin
failures, collisions, symlinks, closed schemas and failure propagation. Stub
transport and GnuPG tests are not evidence of a signed repository in a real image.
Keep the image and native gates for signature qualification.

Portage still needs a reviewed overlay identity, sync method and trust contract.
Arch still needs its contract for signed databases and keys. The compiler rejects
these repository declarations without any silent no-op.

The native test uses GnuPG and APT with a signed local fixture. It accepts a
valid signature and rejects altered metadata. It relocates the generated paths
and uses file transport in a private APT configuration. It needs a socket for the GnuPG agent; restricted executors skip it. HTTPS transport and real image
acceptance still need separate evidence.
