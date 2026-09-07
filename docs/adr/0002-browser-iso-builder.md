# ADR 0002: In-browser ISO builder from existing GHCR bootc images

- Status: accepted (implemented — the builder is live)
- Date: 2026-07-17
- Last updated: 2026-08-08 (reflect post-prototype state; see Current state)
- Issue: [#667](https://github.com/tuna-os/tunaOS/issues/667)
- Implementation: [tuna-os/iso-builder](https://github.com/tuna-os/iso-builder),
  deployed at <https://iso.tunaos.org> (engine: tacklebox compiled to
  `GOOS=js GOARCH=wasm`, tuna-os/tacklebox#95)

## Context

TunaOS publishes a small ISO catalogue and wants every other
variant × flavor to be self-service **without maintaining anything new**:
the bootc images already exist on ghcr.io, and the user should be able to
take one and leave with bootable media from a web page — no terminal, no
app install, no extra published artifacts, no build servers.

## Constraints (verified 2026-07-17)

- **ghcr.io sends no `Access-Control-Allow-Origin` headers** on its token,
  manifest, or blob endpoints (tested directly). Browser JS cannot read
  its responses — this is structural and applies to every registry
  endpoint the builder needs. No client-side technique bypasses CORS.
- Real payload (yellowfin:gnome amd64): **65 layers, 3.5 GB compressed,
  all `tar+zstd`** (sailfin:kde: 65 layers, 1.8 GB). Unpacked roots run
  6–8 GB.
- Nothing in ISO authoring fundamentally needs root: squashfs/erofs
  creation, ESP (FAT) assembly, and ISO9660/El Torito wrapping are all
  userspace file authoring — portable to WASM in principle.

## Decision

**Build the ISO entirely in the browser, sourced directly from the
existing ghcr.io images.** The only server-side piece is a **stateless
CORS relay** (a Cloudflare Worker, ~60 lines; now `relay.tunaos.org` in
the iso-builder repo): a read-only relay for the registry endpoints,
that adds the CORS headers GHCR refuses to send. It stores nothing, has
no build pipeline, and never needs updating when images change. Blob
responses are content-addressed, so the relay lets the CDN's edge cache
absorb repeat pulls (free egress) and shield ghcr.io. The relay's
org-allowlist became a configurable registry allowlist once the builder
accepted arbitrary bootable container images, not just `tuna-os/*`.

Explicitly rejected alternatives:

- **Publishing anything extra** (shell/net-install ISOs, R2-mirrored OCI
  layouts, ORAS-wrapped ISOs): every one of them is a second artifact
  stream to build, gate, store, and keep in sync with GHCR — the exact
  maintenance this ADR exists to avoid.
- **Hosted build service**: servers to run, abuse to police, egress or
  compute to pay for.
- **Local CLI / fork-and-dispatch as the *primary* path**: requires a
  terminal or a GitHub account; both stay documented as fallbacks for
  air-gapped or exotic cases, nothing more.

## In-browser pipeline

| Stage | Mechanism | Status |
|---|---|---|
| 1. Pull | token → index → platform manifest → config → layer blobs, via the relay; digest-verify with WebCrypto | **Working** (tacklebox pure-Go core, tacklebox#95) |
| 2. Unpack | streaming zstd + tar walker with overlay whiteout handling | **Working** |
| 3. Live root | erofs authoring from the merged tree | **Working** (kernel-mount verified) |
| 4. Boot bits | extract kernel + initramfs from `/usr/lib/modules/<ver>/`, systemd-boot from the image's own payload; write the install recipe pointing back at the source image by digest | Working (recipe points at the source image; per-DE initramfs artifacts are a follow-up) |
| 5. Media | FAT ESP image + ISO9660/Rock Ridge/El Torito wrapper (pure-Go writer) | **Working** — the pure-Go writer produced a native ISO that boots to `login:` under QEMU/OVMF (validated by xorriso, kernel mount, and firmware boot) |
| 6. Deliver | stream to disk via File System Access API (`showSaveFilePicker`) / streamed download | **Working** |

Honest MVP limits (tracked in the iso-builder repo): the store is
memory-backed today (base images fit; desktop images need the OPFS
store); ISOs carry the image's stock initramfs unless a tbox initramfs
URL is supplied (cpio-append phase or CI-published per-variant
initramfs artifacts are the follow-up); flatpak preload is a manifest
the live environment consumes.

Browser floor: a File System Access-capable browser (Chromium today,
Firefox behind a flag) and disk headroom ~2× the ISO. Firefox/Safari
fallback: classic download of a streamed Blob, capped by memory — detect
and warn.

The recipe embedded in the ISO uses the same fisherman `bootcDirect`
contract the LUKS E2E exercises, with the image pinned by digest at build
time in the browser — what you clicked is what installs.

## Threat model notes

- The relay is GET/HEAD-only and restricted by an explicit registry
  allowlist. It forwards only `Authorization`/`Accept` — it cannot be used as
  a general relay, and it never sees credentials (public images, anonymous
  tokens).
- The page verifies every blob against its manifest digest before use
  (WebCrypto sha256), so a compromised shim or cache can corrupt but not
  substitute content unnoticed.
- Generated recipes retain the exact OCI reference supplied by the user but
  pin the resolved manifest digest. A crafted builder link can therefore not
  substitute a different image after inspection, and registry policy remains
  enforced by the relay allowlist.
- Client-built ISOs are the user's provenance; cosign signatures on the
  *image* still verify at install time, which is the trust anchor that
  matters.

## Resource estimates

- Relay: one Worker, free-tier scale; edge cache does the heavy lifting.
- User side per build: 1.8–3.5 GB download, minutes of WASM decompress/
  author time, and roughly 2× ISO disk headroom. Desktop images require the
  OPFS-backed store rather than the current memory-only path.
- Remaining engineering is incremental: per-image initramfs artifacts or
  cpio append, OPFS durability, and remora customization. The expensive
  format work (unpack, erofs, ESP, and ISO9660/El Torito authoring) is already
  complete and boot-verified.

## Current state (verified 2026-08-08)

- The builder graduated from this repo's `prototype/iso-builder/` (the
  directory is gone; a "moved" README stood in for it until 2026-09) into
  its own repository,
  [tuna-os/iso-builder](https://github.com/tuna-os/iso-builder), deployed
  at <https://iso.tunaos.org> — build, test, and deploy independently of
  the OS image pipeline.
- The engine is [tacklebox](https://github.com/tuna-os/tacklebox)'s
  pure-Go core compiled to WASM (tacklebox#95, merged): pull + unpack +
  erofs authoring run client-side. The pure-Go ISO9660/Rock Ridge/El
  Torito writer replaced the go-diskfs/xorriso path.
- Arbitrary bootable container images are accepted (any OCI URI), with
  desktop auto-detection from session files, per-DE flatpak preload
  defaults, URL parameters as the API (`?image= &flatpaks= &label=
  &initrd=`), and a streamed ISO download.
- Remora manifest integration (package/config customization through
  install) is tracked in tacklebox#99.

## MVP scope (as implemented)

- [x] Configurator page + working pull chain (prototype, then iso-builder).
- [x] Stateless CORS relay, deployed (`relay.tunaos.org`).
- [x] Digest verification of pulled blobs.
- [x] Stages 2–3: zstd/tar unpack + erofs live root (tacklebox WASM).
- [x] Stages 5: pure-Go ISO9660/ESP writer, boot-verified under QEMU/OVMF.
- [ ] Stage 4 follow-ups: per-DE initramfs artifacts / cpio-append phase.
- [ ] remora customization through install (tacklebox#99).
- [ ] OPFS store for desktop-size images (memory-backed store today).
- Out of scope: any new published ISO artifact; any stateful build service.
