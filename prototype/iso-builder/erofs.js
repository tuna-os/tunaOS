// Stage 3 of the in-browser ISO builder (ADR 0002): a pure-JS EROFS image
// writer. Uncompressed only (EROFS_INODE_FLAT_PLAIN), compact 32-byte
// inodes, no xattrs — the minimum the kernel mounts, which is all the live
// root's first cut needs. Format per Linux fs/erofs/erofs_fs.h (v6.8).
//
// Input: a flat list of entries
//   { path: "usr/bin/foo", type: "file",    mode?, uid?, gid?, data: Uint8Array }
//   { path: "usr/bin",     type: "dir",     mode?, uid?, gid? }
//   { path: "bin",         type: "symlink", mode?, target: "usr/bin" }
// Intermediate directories are created implicitly. Output: Uint8Array.
//
// Shared between the page (global `erofsWriter`) and Node tests.

(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.erofsWriter = factory();
})(typeof self !== "undefined" ? self : globalThis, function () {
  "use strict";

  const BLKSZ = 4096;
  const BLKBITS = 12;
  const SB_MAGIC = 0xe0f5e1e2;
  const SB_OFFSET = 1024;
  const SLOT = 32; // compact inode size; nid unit

  const S_IFDIR = 0o040000, S_IFREG = 0o100000, S_IFLNK = 0o120000;
  const FT = { file: 1, dir: 2, symlink: 7 };

  const enc = new TextEncoder();

  function normalize(entries) {
    // Build a tree; auto-create missing parent dirs.
    const rootNode = { type: "dir", mode: 0o755, uid: 0, gid: 0, children: new Map() };
    const dirOf = (parts) => {
      let n = rootNode;
      for (const p of parts) {
        if (!n.children.has(p)) {
          n.children.set(p, { type: "dir", mode: 0o755, uid: 0, gid: 0, children: new Map() });
        }
        n = n.children.get(p);
        if (n.type !== "dir") throw new Error(`not a directory: ${p}`);
      }
      return n;
    };
    for (const e of entries) {
      const parts = e.path.replace(/^\/+|\/+$/g, "").split("/").filter(Boolean);
      if (!parts.length) continue;
      const name = parts.pop();
      const parent = dirOf(parts);
      if (e.type === "dir") {
        const existing = parent.children.get(name);
        if (existing && existing.type === "dir") {
          existing.mode = e.mode ?? existing.mode;
          existing.uid = e.uid ?? existing.uid;
          existing.gid = e.gid ?? existing.gid;
        } else {
          parent.children.set(name, { type: "dir", mode: e.mode ?? 0o755, uid: e.uid ?? 0, gid: e.gid ?? 0, children: new Map() });
        }
      } else if (e.type === "file") {
        parent.children.set(name, { type: "file", mode: e.mode ?? 0o644, uid: e.uid ?? 0, gid: e.gid ?? 0, data: e.data || new Uint8Array(0) });
      } else if (e.type === "symlink") {
        parent.children.set(name, { type: "symlink", mode: e.mode ?? 0o777, uid: e.uid ?? 0, gid: e.gid ?? 0, data: enc.encode(e.target || "") });
      } else {
        throw new Error(`unsupported entry type: ${e.type}`);
      }
    }
    return rootNode;
  }

  // Pack a sorted child list into self-contained directory blocks.
  // Returns { bytes: Uint8Array, size } — size is exact used bytes (the
  // kernel derives the last name's length from the directory inode size).
  function packDir(children /* [{name, nid, ft}] sorted */) {
    const blocks = [];
    let i = 0;
    while (i < children.length) {
      // Greedy fill: how many entries fit in this block?
      let k = 0, used = 0;
      while (i + k < children.length) {
        const nameLen = enc.encode(children[i + k].name).length;
        if (used + 12 + nameLen > BLKSZ) break;
        used += 12 + nameLen;
        k++;
      }
      if (k === 0) throw new Error(`name too long: ${children[i].name}`);
      const blk = new Uint8Array(BLKSZ);
      const dv = new DataView(blk.buffer);
      let nameoff = 12 * k;
      for (let j = 0; j < k; j++) {
        const c = children[i + j];
        const nb = enc.encode(c.name);
        dv.setBigUint64(12 * j, BigInt(c.nid), true);
        dv.setUint16(12 * j + 8, nameoff, true);
        blk[12 * j + 10] = c.ft;
        blk.set(nb, nameoff);
        nameoff += nb.length;
      }
      blocks.push({ blk, used: nameoff });
      i += k;
    }
    if (!blocks.length) blocks.push({ blk: new Uint8Array(BLKSZ), used: 0 });
    const size = (blocks.length - 1) * BLKSZ + blocks[blocks.length - 1].used;
    const bytes = new Uint8Array(blocks.length * BLKSZ);
    blocks.forEach((b, n) => bytes.set(b.blk, n * BLKSZ));
    return { bytes, size };
  }

  function build(entries, { volumeName = "tunaos-live", buildTime = Math.floor(Date.now() / 1000) } = {}) {
    const rootNode = normalize(entries);

    // Parent / name links (needed for ".." and dirent names).
    (function link(n) {
      if (n.type !== "dir") return;
      for (const [name, c] of n.children) {
        c.parent = n;
        c.nameInParent = name;
        link(c);
      }
    })(rootNode);

    // Flatten: collect nodes depth-first, assign nids sequentially.
    const nodes = [];
    (function walk(n) {
      n.nid = nodes.length;
      nodes.push(n);
      if (n.type === "dir") {
        n.sorted = [...n.children.keys()].sort().map((name) => n.children.get(name));
        for (const c of n.sorted) walk(c);
      }
    })(rootNode);

    // nlink for dirs = 2 + subdirectory count.
    for (const n of nodes) {
      n.nlink = n.type === "dir" ? 2 + n.sorted.filter((c) => c.type === "dir").length : 1;
    }

    // Directory payloads need child nids — all assigned above.
    for (const n of nodes) {
      if (n.type === "dir") {
        const list = [
          { name: ".", nid: n.nid, ft: FT.dir },
          { name: "..", nid: (n.parent ?? n).nid, ft: FT.dir },
          ...n.sorted.map((c) => ({ name: c.nameInParent, nid: c.nid, ft: FT[c.type] })),
        ].sort((a, b) => (a.name < b.name ? -1 : a.name > b.name ? 1 : 0));
        const { bytes, size } = packDir(list);
        n.data = bytes;
        n.size = size;
      } else {
        n.size = n.data.length;
      }
    }

    // Layout: block 0 = sb; meta area = inode slots; then data blocks.
    const metaBlk = 1;
    const metaBytes = nodes.length * SLOT;
    const metaBlocks = Math.ceil(metaBytes / BLKSZ);
    let nextBlk = metaBlk + metaBlocks;
    for (const n of nodes) {
      n.blkaddr = n.size > 0 ? nextBlk : 0;
      nextBlk += Math.ceil((n.type === "dir" ? n.data.length : n.size) / BLKSZ);
    }
    const totalBlocks = nextBlk;

    const img = new Uint8Array(totalBlocks * BLKSZ);
    const dv = new DataView(img.buffer);

    // Superblock.
    const sb = SB_OFFSET;
    dv.setUint32(sb + 0, SB_MAGIC, true);
    dv.setUint32(sb + 4, 0, true); // checksum unused (no SB_CHKSUM feature)
    dv.setUint32(sb + 8, 0, true); // feature_compat
    img[sb + 12] = BLKBITS;
    img[sb + 13] = 0;
    dv.setUint16(sb + 14, rootNode.nid, true);
    dv.setBigUint64(sb + 16, BigInt(nodes.length), true); // inos
    dv.setBigUint64(sb + 24, BigInt(buildTime), true);
    dv.setUint32(sb + 32, 0, true); // build_time_nsec
    dv.setUint32(sb + 36, totalBlocks, true);
    dv.setUint32(sb + 40, metaBlk, true); // meta_blkaddr
    dv.setUint32(sb + 44, 0, true); // xattr_blkaddr
    // uuid[16] at +48: leave zero. volume_name[16] at +64:
    img.set(enc.encode(volumeName).subarray(0, 15), sb + 64);
    dv.setUint32(sb + 80, 0, true); // feature_incompat
    img[sb + 88] = BLKBITS; // dirblkbits

    // Inodes + data.
    for (const n of nodes) {
      const off = metaBlk * BLKSZ + n.nid * SLOT;
      const mode =
        n.type === "dir" ? S_IFDIR | (n.mode & 0o7777) :
        n.type === "symlink" ? S_IFLNK | (n.mode & 0o7777) :
        S_IFREG | (n.mode & 0o7777);
      dv.setUint16(off + 0, 0 /* compact | FLAT_PLAIN */, true);
      dv.setUint16(off + 2, 0, true); // no xattrs
      dv.setUint16(off + 4, mode, true);
      dv.setUint16(off + 6, n.nlink, true);
      dv.setUint32(off + 8, n.size, true);
      dv.setUint32(off + 16, n.blkaddr, true); // i_u.raw_blkaddr
      dv.setUint32(off + 20, n.nid + 1, true); // i_ino (stat only)
      dv.setUint16(off + 24, n.uid, true);
      dv.setUint16(off + 26, n.gid, true);
      if (n.size > 0) img.set(n.type === "dir" ? n.data : n.data, n.blkaddr * BLKSZ);
    }

    return img;
  }

  return { build, BLKSZ };
});
