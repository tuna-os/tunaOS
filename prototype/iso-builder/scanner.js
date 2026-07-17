// Stage 2 of the in-browser ISO builder (ADR 0002): stream OCI layers
// (tar+zstd) and walk their tar structure without ever holding a layer in
// memory. Shared between the page (inlined, global `fzstd`) and the Node
// verification harness (`node test-scan.mjs`).
//
// Exposes: scanImage({base, org, img, ref, arch, fzstd, onProgress})
//   → { kernel, initramfs, layerIndex, layersScanned, bytesDownloaded,
//       entriesSeen, version, layers, totalCompressed }
// Resolves as soon as both vmlinuz and initramfs are located (aborting the
// in-flight layer fetch), or after all layers are scanned.

(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.ociScanner = factory();
})(typeof self !== "undefined" ? self : globalThis, function () {
  "use strict";

  const dec = new TextDecoder();

  function cstr(bytes, off, len) {
    let end = off;
    const max = off + len;
    while (end < max && bytes[end] !== 0) end++;
    return dec.decode(bytes.subarray(off, end));
  }

  function octal(bytes, off, len) {
    const s = cstr(bytes, off, len).trim();
    if (!s) return 0;
    // GNU base-256 extension for sizes > 8GB (first byte 0x80)
    if (bytes[off] & 0x80) {
      let v = 0;
      for (let i = off + 1; i < off + len; i++) v = v * 256 + bytes[i];
      return v;
    }
    return parseInt(s, 8) || 0;
  }

  // Incremental tar walker: feed() decompressed chunks; emits one onEntry
  // per file header. Handles GNU longnames ('L') and skips pax headers.
  class TarScanner {
    constructor(onEntry, shouldCapture) {
      this.shouldCapture = shouldCapture || null;
      this.onFile = null;
      this.pending = [];
      this.pendingLen = 0;
      this.skip = 0; // bytes of body (incl. padding) left to discard
      this.capture = null; // {kind} when the *body* of a meta entry is needed
      this.captured = [];
      this.longname = null;
      this.onEntry = onEntry;
      this.done = false;
    }

    take(n) {
      // Return exactly n bytes from the pending queue, or null.
      if (this.pendingLen < n) return null;
      const out = new Uint8Array(n);
      let got = 0;
      while (got < n) {
        const head = this.pending[0];
        const want = n - got;
        if (head.length <= want) {
          out.set(head, got);
          got += head.length;
          this.pending.shift();
        } else {
          out.set(head.subarray(0, want), got);
          this.pending[0] = head.subarray(want);
          got += want;
        }
      }
      this.pendingLen -= n;
      return out;
    }

    discard(n) {
      let left = n;
      while (left > 0 && this.pending.length) {
        const head = this.pending[0];
        if (head.length <= left) {
          left -= head.length;
          this.pendingLen -= head.length;
          this.pending.shift();
        } else {
          this.pending[0] = head.subarray(left);
          this.pendingLen -= left;
          left = 0;
        }
      }
      return n - left; // bytes actually discarded
    }

    feed(chunk) {
      if (this.done) return;
      this.pending.push(chunk);
      this.pendingLen += chunk.length;

      for (;;) {
        if (this.skip > 0) {
          if (this.capture) {
            const got = this.take(Math.min(this.skip, this.pendingLen));
            if (!got || got.length === 0) return;
            this.captured.push(got);
            this.skip -= got.length;
          } else {
            this.skip -= this.discard(this.skip);
          }
          if (this.skip > 0) return;
          if (this.capture) {
            const body = concat(this.captured);
            if (this.capture.kind === "L") {
              // strip padding + trailing NULs
              let end = this.capture.size;
              this.longname = dec.decode(body.subarray(0, end)).replace(/\0+$/, "");
            } else if (this.capture.kind === "F" && this.onFile) {
              this.onFile(this.capture.name, body.subarray(0, this.capture.size));
            }
            this.capture = null;
            this.captured = [];
          }
          continue;
        }

        const hdr = this.take(512);
        if (!hdr) return;
        if (hdr.every((b) => b === 0)) { this.done = true; return; }

        const type = String.fromCharCode(hdr[156] || 48);
        const size = octal(hdr, 124, 12);
        const padded = Math.ceil(size / 512) * 512;

        if (type === "L") {
          this.capture = { kind: "L", size };
          this.skip = padded;
          continue;
        }

        let name = this.longname || cstr(hdr, 0, 100);
        this.longname = null;
        const prefix = cstr(hdr, 345, 155);
        if (prefix) name = prefix + "/" + name;

        if (type === "0" || type === "\0" || type === "5" || type === "2" || type === "1") {
          this.onEntry({ name, size, type });
          if ((type === "0" || type === "\0") && this.shouldCapture && this.shouldCapture(name)) {
            this.capture = { kind: "F", name, size };
          }
        }
        this.skip = padded;
      }
    }
  }

  function concat(parts) {
    const total = parts.reduce((s, p) => s + p.length, 0);
    const out = new Uint8Array(total);
    let off = 0;
    for (const p of parts) { out.set(p, off); off += p.length; }
    return out;
  }

  const KERNEL_RE = /^(\.\/)?usr\/lib\/modules\/([^/]+)\/vmlinuz$/;
  const INITRD_RE = /^(\.\/)?usr\/lib\/modules\/([^/]+)\/initramfs\.img$/;

  // captureBoot: also pull vmlinuz + initramfs.img bodies into memory
  // (result.files = { vmlinuz, initramfs }); completion then requires both
  // bodies, not just their headers.
  async function scanImage({ base, org = "tuna-os", img, ref, arch = "amd64", fzstd, captureBoot = false, onProgress = () => {} }) {
    const tokRes = await fetch(`${base}/token?scope=repository:${org}/${img}:pull`);
    if (!tokRes.ok) throw new Error(`token HTTP ${tokRes.status}`);
    const token = (await tokRes.json()).token;
    const mAccept = {
      headers: {
        Authorization: `Bearer ${token}`,
        Accept: "application/vnd.oci.image.index.v1+json, application/vnd.oci.image.manifest.v1+json",
      },
    };

    let manifest = await (await fetch(`${base}/v2/${org}/${img}/manifests/${ref}`, mAccept)).json();
    if (manifest.manifests) {
      const m = manifest.manifests.find((x) => x.platform.architecture === arch && !x.platform.variant)
        || manifest.manifests[0];
      manifest = await (await fetch(`${base}/v2/${org}/${img}/manifests/${m.digest}`, mAccept)).json();
    }
    if (!manifest.layers) throw new Error("no layers in manifest");
    const totalCompressed = manifest.layers.reduce((s, l) => s + l.size, 0);

    const found = { kernel: null, initramfs: null, layerIndex: -1, version: null };
    const files = {};
    const complete = () => captureBoot
      ? !!(files.vmlinuz && files.initramfs)
      : !!(found.kernel && found.initramfs);
    let bytesDownloaded = 0;
    let entriesSeen = 0;

    // Scan back-to-front: overlay semantics make the topmost (last) layer's
    // kernel the effective one, and kernels land in late layers in practice —
    // reverse order finds the right answer with a fraction of the download.
    for (let step = 0; step < manifest.layers.length; step++) {
      const i = manifest.layers.length - 1 - step;
      const layer = manifest.layers[i];
      if (!/zstd|gzip|tar$/.test(layer.mediaType)) continue;
      const gzip = /gzip/.test(layer.mediaType);
      const plain = /tar$/.test(layer.mediaType) && !/zstd|gzip/.test(layer.mediaType);

      const ctrl = new AbortController();
      const scanner = new TarScanner((e) => {
        entriesSeen++;
        const k = e.name.match(KERNEL_RE);
        const r = e.name.match(INITRD_RE);
        if (k) { found.kernel = { path: e.name, size: e.size }; found.version = k[2]; found.layerIndex = i; }
        if (r) { found.initramfs = { path: e.name, size: e.size }; found.layerIndex = i; }
        if (complete()) { scanner.done = true; ctrl.abort(); }
      }, captureBoot ? (name) => KERNEL_RE.test(name) || INITRD_RE.test(name) : null);
      scanner.onFile = (name, body) => {
        if (KERNEL_RE.test(name)) files.vmlinuz = body;
        else if (INITRD_RE.test(name)) files.initramfs = body;
        if (complete()) { scanner.done = true; ctrl.abort(); }
      };

      let feed;
      let flush = () => {};
      if (plain) {
        feed = (c) => scanner.feed(c);
      } else if (gzip && typeof DecompressionStream !== "undefined") {
        // handled below via stream piping
      } else {
        const dz = new fzstd.Decompress((data) => scanner.feed(data));
        feed = (c) => dz.push(c);
        flush = () => { try { dz.push(new Uint8Array(0), true); } catch (_) { /* aborted mid-frame */ } };
      }

      try {
        const res = await fetch(`${base}/v2/${org}/${img}/blobs/${layer.digest}`, {
          headers: { Authorization: `Bearer ${token}` },
          signal: ctrl.signal,
        });
        if (!res.ok) throw new Error(`blob HTTP ${res.status}`);

        let stream = res.body;
        if (gzip && typeof DecompressionStream !== "undefined") {
          stream = stream.pipeThrough(new DecompressionStream("gzip"));
          feed = (c) => scanner.feed(c);
        }
        const reader = stream.getReader();
        for (;;) {
          const { done, value } = await reader.read();
          if (done) break;
          bytesDownloaded += gzip ? 0 : value.length;
          feed(value);
          onProgress({ layer: i, layers: manifest.layers.length, bytesDownloaded, entriesSeen, found });
          if (scanner.done) { ctrl.abort(); break; }
        }
        flush();
      } catch (e) {
        if (!complete()) throw e;
      }
      if (complete()) break;
    }

    return {
      ...found,
      files,
      layersScanned: found.layerIndex >= 0 ? found.layerIndex + 1 : manifest.layers.length,
      bytesDownloaded,
      entriesSeen,
      layers: manifest.layers.length,
      totalCompressed,
    };
  }

  return { scanImage, TarScanner };
});
