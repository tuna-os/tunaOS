# ADR 0002: Browser-based ISO builder — feasibility and staged architecture

- Status: proposed
- Date: 2026-07-17
- Issue: [#667](https://github.com/tuna-os/tunaOS/issues/667)
- Prototype: `prototype/iso-builder/index.html` (static configurator, no backend)

## Context

TunaOS intentionally publishes a small ISO catalogue (grouped dedup ISOs,
issue #455) and wants everything else self-service. The target experience:
**the browser takes a bootc image and makes an ISO** — pick any
variant × flavor on a web page and leave with bootable media, without
TunaOS operating build servers.

## Feasibility findings (verified 2026-07-17)

**GHCR cannot feed a browser.** Tested directly: `ghcr.io/token` and
`/v2/.../manifests/...` return 200 to non-browser clients but send **no
`Access-Control-Allow-Origin` header**, and the `Authorization` header
fails preflight. Browsers therefore cannot pull image layers from GHCR,
full stop. Any in-browser pipeline must be fed from a CORS-enabled origin.

**R2 is that origin.** Cloudflare R2 supports per-bucket CORS rules and
has **zero egress fees** — serving multi-GB layer sets to browsers costs
storage only, which is compatible with the R2 cost-reduction work. CI can
mirror what the builder needs with `rclone`/`oras` in the existing publish
workflows.

**The hard parts of full in-browser assembly are payload and authoring,
not privilege.** Everything tacklebox does can in principle be userspace
file authoring (no loop devices needed): but squashfs/erofs creation and
ISO9660/El Torito + ESP authoring have no maintained WASM ports today, and
streaming 3–8 GB through browser memory needs the File System Access API
and careful chunking. Real, but a project — not a blocker in principle.

## Decision: three stages toward the browser builder

### Stage A — ship now (the "oras hack")

Store prebuilt ISOs as plain R2 objects (today's `live-isos/` layout — an
ORAS artifact adds indirection with no browser benefit since R2 is already
HTTP+CORS) and let the page hand out the link. This is the current
pipeline; it is blocked only by the publish gate being red and the
download host misconfiguration (issue #543 — `download.tunaos.org`
currently 404s on every path).

### Stage B — the MVP browser builder: one shell ISO + in-browser recipe injection

The live ISO's installer is **fisherman driving `recipe.json`** — the
image to install is *data inside the ISO*, not baked structure. So:

1. CI publishes **one generic live/net-install ISO per arch** to R2
   (CORS on).
2. The browser fetches it, patches `recipe.json` to point at the chosen
   `ghcr.io/tuna-os/<variant>:<flavor>` (installer pulls it over the
   network at install time — the exact `bootcDirect` network-pull path the
   LUKS E2E exercises), and streams the result to disk via the File
   System Access API.
3. Patching one file inside an ISO9660 image is small, bounded work
   (rewrite one file's extents + path table, or reserve a fixed-size
   padded config region to make it a pure in-place overwrite) — JS/WASM
   scale, not squashfs scale.

**Every variant × flavor becomes buildable in-browser with a single
published shell ISO** (~1–2 GB fetch), which also collapses the published
catalogue further. This is the recommended MVP.

### Stage C — full offline assembly in the browser

Mirror per-flavor OCI layouts to R2; in-browser: pull layers, author the
dedup squashfs store and the hybrid ISO in WASM (`squashfs-tools-ng` or an
erofs writer compiled to WASM; a minimal ISO9660/ESP writer). Produces
fully *offline* installer ISOs client-side. Target state; start after
Stage B proves the streaming/download UX.

Interim fallbacks for combinations Stage B can't serve (e.g. air-gapped
installs) stay as today: local `build-iso-group.sh` / tacklebox, or
fork-and-dispatch on the user's own GitHub fork (free runners, their
provenance). The prototype page presents both.

## Threat model notes

- No tokens or secrets in the page; GHCR stays out of the browser path
  entirely (CORS makes this structural, not just policy).
- The R2 mirror is read-only, versioned by digest, and only ever contains
  artifacts CI signed/gated — the browser verifies digests before
  patching (sha256 in JS/WebCrypto is cheap).
- Recipe injection only interpolates values from the embedded
  variant/flavor allowlist — never free text — so a shared "builder link"
  cannot point a victim's installer at a hostile image.
- Client-built ISOs are the user's provenance; the page says so, and the
  shell ISO's own signature still covers everything except the recipe.

## Resource estimates

- Stage A: already-built pipeline + a CORS rule + fixing #543.
- Stage B: shell-ISO recipe surface in tacklebox (padded config region
  recommended), ~2–4 weeks of a browser ISO-patcher (JS + WebCrypto +
  File System Access), CI job to publish the shell ISO. R2 delta: one ISO
  per arch.
- Stage C: WASM ports of squashfs/ISO authoring + OCI-layout mirror job;
  months, not weeks. R2 delta: per-flavor layer storage (dedup helps —
  layers are shared across flavors).

## MVP scope (Stage B)

- [ ] tacklebox: reserve a padded, fixed-offset `recipe.json` region in
      the shell ISO so browser patching is a pure in-place overwrite.
- [ ] CI: publish `tunaos-shell-<arch>-latest.iso` to R2; enable bucket
      CORS for `tunaos.org` origins.
- [ ] Web: extend the prototype configurator with the fetch → patch →
      save pipeline and digest verification.
- [ ] E2E: boot a browser-patched ISO in the existing `iso-e2e.sh` disk
      gate to prove parity with CI-built ISOs.
