# ADR 0002: In-browser ISO builder from existing GHCR bootc images

- Status: proposed
- Date: 2026-07-17
- Issue: [#667](https://github.com/tuna-os/tunaOS/issues/667)
- Prototype: `prototype/iso-builder/` (static page + stateless CORS shim;
  pull chain — token → index → manifest → config — working)

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
CORS shim** (`prototype/iso-builder/worker/cors-shim.js`, ~60 lines of
Cloudflare Worker): a read-only relay for the three GHCR endpoints,
restricted to `tuna-os/*` images, that adds the CORS headers GHCR
refuses to send. It stores nothing, has no build pipeline, and never
needs updating when images change. Blob responses are content-addressed,
so the Worker lets Cloudflare's edge cache absorb repeat pulls (free
egress) and shield ghcr.io.

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
| 1. Pull | token → index → platform manifest → config → layer blobs, via the shim; digest-verify with WebCrypto | **Working** (prototype demo; verified against real images) |
| 2. Unpack | streaming zstd (fzstd, 8.4 KB inlined) + incremental tar walker, layers scanned topmost-first | **Working** (kernel + initramfs located in ~13 s / 349 MB of sailfin:kde, verified in headless Chromium cross-origin through the deployed shim) |
| 3. Live root | pure-JS EROFS writer (`erofs.js`, uncompressed FLAT_PLAIN + compact inodes) | **Writer working** — browser-authored images pass `fsck.erofs`, kernel-mount, and diff-identical to `mkfs.erofs` output; remaining: full-rootfs unpack (whiteouts, hardlinks, xattrs) to feed it |
| 4. Boot bits | extract kernel + initramfs from `/usr/lib/modules/<ver>/`, systemd-boot from the image's own payload; write fisherman `recipe.json` pointing back at the source image by digest | straightforward once 2 exists |
| 5. Media | FAT ESP image + ISO9660/El Torito wrapper (JS/WASM writer) | bounded, well-specified formats |
| 6. Deliver | stream to disk via File System Access API (`showSaveFilePicker`) — memory stays at chunk scale, not ISO scale | standard |

Browser floor: a File System Access-capable browser (Chromium today,
Firefox behind a flag) and disk headroom ~2× the ISO. Firefox/Safari
fallback: classic download of a streamed Blob, capped by memory — detect
and warn.

The recipe embedded in the ISO uses the same fisherman `bootcDirect`
contract the LUKS E2E exercises, with the image pinned by digest at build
time in the browser — what you clicked is what installs.

## Threat model notes

- The shim is GET/HEAD-only, org-allowlisted (`tuna-os/*`), and forwards
  only `Authorization`/`Accept` — it cannot be used as a general relay,
  and it never sees credentials (public images, anonymous tokens).
- The page verifies every blob against its manifest digest before use
  (WebCrypto sha256), so a compromised shim or cache can corrupt but not
  substitute content unnoticed.
- Generated recipes only interpolate allowlisted variant/flavor values
  and digests the page resolved itself — a crafted "builder link" cannot
  aim the installer at a foreign image.
- Client-built ISOs are the user's provenance; cosign signatures on the
  *image* still verify at install time, which is the trust anchor that
  matters.

## Resource estimates

- Shim: one Worker, free tier scale; edge cache does the heavy lifting.
- User side per build: 1.8–3.5 GB download, minutes of WASM decompress/
  author time, ~2× ISO disk headroom.
- Engineering: stage 2 ≈ days (zstd WASM builds exist; tar is trivial);
  stages 3+5 are the real work — an erofs writer and a minimal
  ISO9660+ESP writer in WASM/JS; weeks-to-months, incrementally
  shippable (each stage demos on its own).

## MVP scope

- [x] Configurator page + working stage-1 pull chain (prototype).
- [x] Stateless CORS shim (`worker/cors-shim.js`), ready to deploy.
- [x] Shim deployed (temporary preview account, claimable — permanent
      home: `npx wrangler deploy` from `worker/` after `wrangler login`);
      digest verification still to wire.
- [x] Stage 2: streaming zstd + tar walk extracts the kernel version from
      any variant:flavor in-browser.
- [ ] Stage 3–5: erofs + ESP + ISO writers; boot the result in the
      existing `iso-e2e.sh` disk gate to prove parity with CI ISOs.
- Out of scope: any new published artifact; any stateful service.
