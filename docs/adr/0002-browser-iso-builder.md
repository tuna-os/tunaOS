# ADR 0002: In-browser ISO builder from existing GHCR bootc images

- Status: accepted (implemented — the builder is live)
- Date: 2026-07-17
- Last updated: 2026-08-08 (reflect post-prototype state; see Current state)
- Issue: [#667](https://github.com/tuna-os/tunaOS/issues/667)
- Implementation: [tuna-os/iso-builder](https://github.com/tuna-os/iso-builder),
  deployed at <https://iso.tunaos.org> (engine: tacklebox compiled to
  `GOOS=js GOARCH=wasm`, tuna-os/tacklebox#95)

## Context

TunaOS publishes a small ISO catalogue. It wants every other
variant × flavor to be self-service **with no new maintenance work**. The
bootc images are already on ghcr.io. The user should be able to take one
image and leave with bootable media from a web page. That means no terminal,
no app install, no extra published artifacts, and no build servers.

## Constraints (verified 2026-07-17)

- **ghcr.io sends no `Access-Control-Allow-Origin` headers** on its token,
  manifest, or blob endpoints (tested directly). Browser JS cannot read
  its responses — this is structural and applies to every registry
  endpoint the builder needs. No technique on the client side can bypass CORS.
- Real payload (yellowfin:gnome amd64): **65 layers, 3.5 GB compressed,
  all `tar+zstd`** (sailfin:kde: 65 layers, 1.8 GB). Unpacked roots run
  6–8 GB.
- Nothing in the creation of an ISO fundamentally needs root. The steps are
  squashfs/erofs creation, ESP (FAT) assembly, and the ISO9660/El Torito
  wrapper — all userspace file operations. In principle they port to WASM.

## Decision

**Build the ISO entirely in the browser, sourced directly from the
existing ghcr.io images**. The only server-side piece is a **stateless
CORS relay** (a Cloudflare Worker, ~60 lines; now `relay.tunaos.org` in
the iso-builder repo). The relay is read-only, it serves the registry
endpoints, and it adds the CORS headers that GHCR refuses to send. It
stores nothing, has no build pipeline, and never needs an update when
images change. Blob responses are content-addressed, so the relay lets the
CDN's edge cache absorb the repeat pulls (free egress) and shield ghcr.io.
The relay's org-allowlist became a configurable registry allowlist once the
builder accepted any bootable container image, and not only `tuna-os/*`.

Explicitly rejected alternatives:

- **To publish anything extra** — shell/net-install ISOs, R2-mirrored OCI
  layouts, ORAS-wrapped ISOs. Each one is a second artifact stream to
  build, gate, store, and keep in sync with GHCR. That is the exact
  maintenance this ADR exists to avoid.
- **Hosted build service**: servers to run, abuse to police, egress or
  compute to pay for.
- **Local CLI / fork-and-dispatch as the *primary* path**: needs a
  terminal or a GitHub account. Both stay documented as fallbacks for
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
memory-backed today. Base images fit, but desktop images need the OPFS
store. ISOs carry the image's stock initramfs unless the user supplies a
tbox initramfs URL. The follow-up is a cpio-append phase, or per-variant
initramfs artifacts that CI publishes. Flatpak preload is a manifest the
live environment consumes.

Browser floor: a browser with support for File System Access (Chromium
today, Firefox behind a flag) and disk headroom ~2× the ISO. Firefox/Safari
fallback: classic download of a streamed Blob, capped by memory — detect
and warn.

The recipe embedded in the ISO uses the same fisherman `bootcDirect`
contract the LUKS E2E exercises. The browser pins the image by digest at
build time — what you clicked is what installs.

## Threat model notes

- The relay is GET/HEAD-only and restricted by an explicit registry
  allowlist. It forwards only `Authorization`/`Accept` — it cannot be used as
  a general relay, and it never sees credentials (public images, anonymous
  tokens).
- The page verifies every blob against its manifest digest before use
  (WebCrypto sha256). A compromised shim or cache can corrupt content, but
  it cannot substitute other content without detection.
- Generated recipes keep the exact OCI reference that the user supplied,
  but they pin the resolved manifest digest. A crafted builder link,
  therefore, cannot substitute a different image after inspection. The relay
  allowlist still enforces registry policy.
- Client-built ISOs are the user's provenance. Cosign signatures on the
  *image* still verify at install time, which is the trust anchor that
  matters.

## Resource estimates

- Relay: one Worker, free-tier scale; the edge cache does the heavy work.
- User side per build: 1.8–3.5 GB download and roughly 2× ISO disk
  headroom. The WASM decompress and author steps take minutes. Desktop
  images need the OPFS-backed store instead of the current memory-only path.
- Remaining engineering is incremental: per-image initramfs artifacts or
  cpio append, OPFS durability, and remora customization. The expensive
  format work (unpack, erofs, ESP, and the ISO9660/El Torito writer) is
  already complete and boot-verified.

## Current state (verified 2026-08-08)

- The builder graduated from this repo's `prototype/iso-builder/` into
  its own repository,
  [tuna-os/iso-builder](https://github.com/tuna-os/iso-builder), deployed
  at <https://iso.tunaos.org>. The directory is gone; a "moved" README
  stood in for it until 2026-09. The builder can now build, test, and
  deploy independently of the OS image pipeline.
- The engine is [tacklebox](https://github.com/tuna-os/tacklebox)'s
  pure-Go core compiled to WASM (tacklebox#95, merged): pull, unpack, and
  erofs creation run client-side. The pure-Go ISO9660/Rock Ridge/El
  Torito writer replaced the go-diskfs/xorriso path.
- The builder accepts any bootable container image (any OCI URI). It
  auto-detects the desktop from session files and applies flatpak preload
  defaults per DE. URL parameters are the API (`?image= &flatpaks= &label=
  &initrd=`), and the ISO download streams.
- tacklebox#99 tracks the Remora manifest integration (package/config
  customization through install).

## MVP scope (as implemented)

- [x] Configurator page + pull chain that works (prototype, then iso-builder).
- [x] Stateless CORS relay, deployed (`relay.tunaos.org`).
- [x] Digest verification of pulled blobs.
- [x] Stages 2–3: zstd/tar unpack + erofs live root (tacklebox WASM).
- [x] Stages 5: pure-Go ISO9660/ESP writer, boot-verified under QEMU/OVMF.
- [ ] Stage 4 follow-ups: per-DE initramfs artifacts / cpio-append phase.
- [ ] remora customization through install (tacklebox#99).
- [ ] OPFS store for desktop-size images (memory-backed store today).
- Out of scope: any new published ISO artifact; any stateful build service.
