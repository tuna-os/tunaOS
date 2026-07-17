// Stage 4 of the in-browser ISO builder (ADR 0002): reconstruct the final
// rootfs of an OCI image by streaming its layers bottom-to-top and applying
// overlay semantics — whiteouts (.wh.<name>), opaque directories
// (.wh..wh..opq), replacement, hardlinks, symlinks, and device nodes.
//
// Bodies go through a pluggable content store so the tree itself stays
// metadata-sized:
//   store = { put(path, bytes) -> ref (may be async), get(ref) -> bytes }
// MemStore keeps bytes in memory (tests, subtree builds); the browser can
// substitute an OPFS-backed store for full roots.
//
// Shared between the page (global `ociUnpack`) and Node tests.

(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.ociUnpack = factory();
})(typeof self !== "undefined" ? self : globalThis, function () {
  "use strict";

  const scannerMod =
    typeof module === "object" && module.exports
      ? require("./scanner.js")
      : (typeof self !== "undefined" ? self : globalThis).ociScanner;

  function MemStore() {
    return {
      put: (_path, bytes) => bytes,
      get: (ref) => ref,
    };
  }

  const norm = (p) => p.replace(/^\.\//, "").replace(/^\/+/, "").replace(/\/+$/, "");

  function newDir(mode = 0o755, uid = 0, gid = 0) {
    return { type: "dir", mode, uid, gid, children: new Map() };
  }

  // Walk to the parent dir of `path`, creating intermediate dirs.
  function parentOf(tree, path) {
    const parts = path.split("/");
    const name = parts.pop();
    let n = tree;
    for (const p of parts) {
      let c = n.children.get(p);
      if (!c || c.type !== "dir") {
        c = newDir();
        n.children.set(p, c);
      }
      n = c;
    }
    return { parent: n, name };
  }

  async function unpackImage({
    base, org = "tuna-os", img, ref, arch = "amd64", fzstd,
    store = MemStore(),
    wantBody = () => true,
    onProgress = () => {},
  }) {
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

    const tree = newDir();
    const stats = { layers: manifest.layers.length, entries: 0, files: 0, dirs: 0, symlinks: 0, hardlinks: 0, devices: 0, whiteouts: 0, opaques: 0, bodyBytes: 0, bytesDownloaded: 0, elided: 0 };
    const pendingPuts = [];

    const applyEntry = (e) => {
      stats.entries++;
      const path = norm(e.name);
      if (!path) {
        if (e.type === "5") { tree.mode = e.mode || tree.mode; tree.uid = e.uid; tree.gid = e.gid; }
        return;
      }
      const { parent, name } = parentOf(tree, path);

      if (name === ".wh..wh..opq") {
        // Opaque marker: everything from lower layers in this dir disappears.
        parent.children.clear();
        stats.opaques++;
        return;
      }
      if (name.startsWith(".wh.")) {
        parent.children.delete(name.slice(4));
        stats.whiteouts++;
        return;
      }

      switch (e.type) {
        case "5": {
          const existing = parent.children.get(name);
          if (existing && existing.type === "dir") {
            existing.mode = e.mode; existing.uid = e.uid; existing.gid = e.gid;
          } else {
            parent.children.set(name, newDir(e.mode, e.uid, e.gid));
          }
          break;
        }
        case "0": {
          const node = { type: "file", mode: e.mode, uid: e.uid, gid: e.gid, size: e.size, ref: null, elided: false };
          if (!wantBody(path)) { node.elided = true; stats.elided++; }
          parent.children.set(name, node);
          break;
        }
        case "1": // hardlink: resolve lazily at export (target may still change)
          parent.children.set(name, { type: "hard", linkTo: norm(e.linkname || "") });
          break;
        case "2":
          parent.children.set(name, { type: "symlink", mode: 0o777, uid: e.uid, gid: e.gid, target: e.linkname || "" });
          break;
        case "3": case "4":
          parent.children.set(name, { type: e.type === "3" ? "chardev" : "blockdev", mode: e.mode, uid: e.uid, gid: e.gid, rdev: (e.devmajor << 8) | (e.devminor & 0xff) | ((e.devminor & ~0xff) << 12) });
          stats.devices++;
          break;
        case "6":
          parent.children.set(name, { type: "fifo", mode: e.mode, uid: e.uid, gid: e.gid });
          stats.devices++;
          break;
      }
    };

    for (let i = 0; i < manifest.layers.length; i++) {
      const layer = manifest.layers[i];
      const gzip = /gzip/.test(layer.mediaType);
      const plain = /tar$/.test(layer.mediaType) && !/zstd|gzip/.test(layer.mediaType);

      const scanner = new scannerMod.TarScanner(applyEntry, (name) => {
        const p = norm(name);
        return p && !p.split("/").pop().startsWith(".wh.") && wantBody(p);
      });
      scanner.onFile = (name, body) => {
        const path = norm(name);
        stats.bodyBytes += body.length;
        const r = store.put(path, body.slice());
        if (r && typeof r.then === "function") {
          pendingPuts.push(r.then((resolved) => { setRef(tree, path, resolved); }));
        } else {
          setRef(tree, path, r);
        }
      };

      let feed, flush = () => {};
      if (plain) feed = (c) => scanner.feed(c);
      else if (!gzip) {
        const dz = new fzstd.Decompress((data) => scanner.feed(data));
        feed = (c) => dz.push(c);
        flush = () => { try { dz.push(new Uint8Array(0), true); } catch (_) { /* stream end */ } };
      }

      const res = await fetch(`${base}/v2/${org}/${img}/blobs/${layer.digest}`, { headers: { Authorization: `Bearer ${token}` } });
      if (!res.ok) throw new Error(`blob ${i} HTTP ${res.status}`);
      let stream = res.body;
      if (gzip) {
        stream = stream.pipeThrough(new DecompressionStream("gzip"));
        feed = (c) => scanner.feed(c);
      }
      const reader = stream.getReader();
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        if (!gzip) stats.bytesDownloaded += value.length;
        feed(value);
        onProgress({ layer: i, layers: manifest.layers.length, ...stats });
      }
      flush();
    }
    await Promise.all(pendingPuts);

    // Tally node kinds on the final tree.
    (function count(n) {
      for (const c of n.children.values()) {
        if (c.type === "dir") { stats.dirs++; count(c); }
        else if (c.type === "file") stats.files++;
        else if (c.type === "symlink") stats.symlinks++;
        else if (c.type === "hard") stats.hardlinks++;
      }
    })(tree);

    return { tree, stats, store };
  }

  function setRef(tree, path, ref) {
    const { parent, name } = parentOf(tree, path);
    const n = parent.children.get(name);
    if (n && n.type === "file") n.ref = ref;
  }

  // Convert (a subtree of) the final tree into erofs.js entries.
  // filter(path, node) decides inclusion; bodies come from the store.
  // Hardlinks whose target survives the filter become 'link' entries;
  // otherwise they materialize as a copy of the target's bytes.
  function toErofsEntries(tree, store, { filter = () => true } = {}) {
    const entries = [];
    const included = new Set();
    (function walk(n, prefix) {
      for (const [name, c] of [...n.children.entries()].sort()) {
        const path = prefix ? `${prefix}/${name}` : name;
        if (!filter(path, c)) continue;
        if (c.type === "dir") {
          entries.push({ path, type: "dir", mode: c.mode, uid: c.uid, gid: c.gid });
          included.add(path);
          walk(c, path);
        } else if (c.type === "file") {
          if (c.elided) continue;
          entries.push({ path, type: "file", mode: c.mode, uid: c.uid, gid: c.gid, data: store.get(c.ref) || new Uint8Array(0) });
          included.add(path);
        } else if (c.type === "symlink") {
          entries.push({ path, type: "symlink", uid: c.uid, gid: c.gid, target: c.target });
        } else if (c.type === "hard") {
          entries.push({ path, type: "link", linkTo: c.linkTo });
        } else if (c.type === "chardev" || c.type === "blockdev" || c.type === "fifo") {
          entries.push({ path, type: c.type, mode: c.mode, uid: c.uid, gid: c.gid, rdev: c.rdev || 0 });
        }
      }
    })(tree, "");
    // Fix up hardlinks: target must be included, else drop the link (its
    // bytes were captured under the target path only).
    return entries.filter((e) => e.type !== "link" || included.has(e.linkTo));
  }

  return { unpackImage, toErofsEntries, MemStore };
});
