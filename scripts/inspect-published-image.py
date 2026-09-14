#!/usr/bin/env python3
"""Read a published image's files straight from the registry.

Written for tunaOS#2485, which stalled on "the next step is a `podman run`
against ghcr.io/tuna-os/skipjack:gnome and ghcr.io/tuna-os/albacore:gnome".
This environment has no container runtime, and every question that gets asked
of a red cell — what mode is that file, what does it actually contain, did the
package land at all — is answerable over plain HTTPS against the registry.

Two paths, picked per layer:

  zstd:chunked   Each layer carries an embedded table of contents, located by
                 the `io.github.containers.zstd-chunked.manifest-position`
                 annotation. Range-GET that, and you have every path in the
                 layer with its mode, uid, gid, size, xattrs and byte offsets,
                 without reading the layer. A 320 MB layer costs a 584 KB read.

  everything else  Stream the blob through zstd/gzip into tarfile in `r|` mode
                 and read headers as they go. Slower, nothing hits disk, and
                 xattrs arrive as PAX SCHILY.xattr.* records.

Usage:
    scripts/inspect-published-image.py ls   <image> <prefix>
    scripts/inspect-published-image.py stat <image> <path>
    scripts/inspect-published-image.py cat  <image> <path>

    <image> is repo:tag, e.g. tuna-os/skipjack:gnome (ghcr.io is implied).
    <path>  is the in-image path without a leading slash, e.g.
            etc/selinux/targeted/contexts/dbus_contexts

Examples:
    # the #2485 comparison, in two commands
    scripts/inspect-published-image.py stat tuna-os/skipjack:gnome \\
        etc/selinux/targeted/contexts/dbus_contexts
    scripts/inspect-published-image.py stat tuna-os/albacore:gnome \\
        etc/selinux/targeted/contexts/dbus_contexts
"""

from __future__ import annotations

import argparse
import gzip
import io
import json
import subprocess
import sys
import tarfile
import time
from concurrent.futures import ThreadPoolExecutor

REGISTRY = "ghcr.io"

ACCEPT = ",".join((
    "application/vnd.oci.image.manifest.v1+json",
    "application/vnd.docker.distribution.manifest.v2+json",
    "application/vnd.oci.image.index.v1+json",
    "application/vnd.docker.distribution.manifest.list.v2+json",
))

TOC_POSITION = "io.github.containers.zstd-chunked.manifest-position"


def _curl(*args: str, binary: bool = False, attempts: int = 3):
    """curl with -L, retried. The redirect matters: ghcr.io sends blob requests
    on to a storage host that rejects a forwarded GitHub bearer token, so curl
    dropping the Authorization header across hosts is the behaviour we want,
    not a problem to work around.

    The retry is not decoration. A range read of a 320 MB layer comes back as
    curl exit 18 (partial transfer) often enough to lose a layer per run, and a
    lost layer here reads as "the file is not in the image" — the one answer
    this script must never give wrongly.
    """
    for attempt in range(attempts):
        try:
            out = subprocess.run(["curl", "-sSL", "--retry", "2", *args],
                                 capture_output=True, check=True).stdout
            return out if binary else out.decode()
        except subprocess.CalledProcessError:
            # Re-raise from inside the handler on the last attempt: a bare
            # `raise` keeps the traceback, and there is no path here that can
            # reach the end of the loop holding nothing to raise.
            if attempt + 1 >= attempts:
                raise
            time.sleep(2 ** attempt)
    raise ValueError(f"attempts must be at least 1, got {attempts}")


def token(repo: str) -> str:
    url = f"https://{REGISTRY}/token?scope=repository:{repo}:pull&service={REGISTRY}"
    return json.loads(_curl(url))["token"]


def manifest(repo: str, ref: str, tok: str) -> dict:
    return json.loads(_curl(
        "-H", f"Authorization: Bearer {tok}", "-H", f"Accept: {ACCEPT}",
        f"https://{REGISTRY}/v2/{repo}/manifests/{ref}"))


def amd64_manifest(repo: str, ref: str, tok: str) -> dict:
    """Resolve an index to its amd64 manifest; pass a plain manifest through."""
    m = manifest(repo, ref, tok)
    if "manifests" not in m:
        return m
    for entry in m["manifests"]:
        if entry.get("platform", {}).get("architecture") == "amd64":
            return manifest(repo, entry["digest"], tok)
    raise SystemExit(f"{repo}:{ref} has no amd64 manifest")


def blob_range(repo: str, digest: str, start: int, length: int, tok: str) -> bytes:
    return _curl("-H", f"Authorization: Bearer {tok}",
                 "-H", f"Range: bytes={start}-{start + length - 1}",
                 f"https://{REGISTRY}/v2/{repo}/blobs/{digest}", binary=True)


def _unzstd(raw: bytes) -> bytes:
    import zstandard
    # stream_reader, not decompress(): these frames carry no content size in
    # the header, and decompress() refuses without one.
    return zstandard.ZstdDecompressor().stream_reader(io.BytesIO(raw)).read()


def layer_toc(repo: str, layer: dict, tok: str) -> dict | None:
    """The zstd:chunked table of contents, or None for a layer without one."""
    pos = (layer.get("annotations") or {}).get(TOC_POSITION)
    if not pos:
        return None
    offset, clen, _ulen, _kind = (int(x) for x in pos.split(":"))
    return json.loads(_unzstd(blob_range(repo, layer["digest"], offset, clen, tok)))


def toc_entries(toc: dict | None) -> list[dict]:
    """`entries` can be absent or explicitly null; both mean no entries."""
    return (toc.get("entries") if toc else None) or []


def _norm(name: str) -> str:
    return name.lstrip("./").rstrip("/")


def toc_read(repo: str, layer: dict, entries: list[dict], path: str,
             tok: str) -> bytes:
    """Assemble one file's bytes from its TOC entry AND its chunk entries.

    A large file is stored as a `reg` entry followed by trailing `chunk`
    entries, each with its own byte range. Reading only the `reg` range
    succeeds, decompresses cleanly, and hands back a plausible file missing its
    tail — which is how a 374,034-byte file_contexts first measured 49,094 and
    briefly looked like the answer to tunaOS#2485. Read the whole run, and
    check the result against the declared size.
    """
    out, size, collecting = b"", None, False
    for entry in entries:
        if _norm(entry.get("name", "")) != path:
            if collecting:
                break
            continue
        if entry.get("type") == "reg":
            if collecting:      # the next file of the same name: stop
                break
            collecting, size = True, entry.get("size")
        elif not collecting:
            continue
        if "offset" in entry and "endOffset" in entry:
            out += _unzstd(blob_range(repo, layer["digest"], entry["offset"],
                                      entry["endOffset"] - entry["offset"], tok))
    if size is not None and len(out) != size:
        raise SystemExit(
            f"{path}: assembled {len(out)} bytes but the TOC declares {size}; "
            "refusing to hand back a partial file")
    return out


def stream_layer(repo: str, layer: dict, tok: str, want: set[str]):
    """Yield (metadata, reader) for each wanted path in a layer with no TOC."""
    import zstandard
    proc = subprocess.Popen(
        ["curl", "-sSL", "-H", f"Authorization: Bearer {tok}",
         f"https://{REGISTRY}/v2/{repo}/blobs/{layer['digest']}"],
        stdout=subprocess.PIPE)
    try:
        raw = (zstandard.ZstdDecompressor().stream_reader(proc.stdout)
               if "zstd" in layer["mediaType"] else gzip.GzipFile(fileobj=proc.stdout))
        tar = tarfile.open(fileobj=raw, mode="r|")
        for member in tar:
            if _norm(member.name) in want:
                yield {
                    "name": member.name,
                    "mode": oct(member.mode),
                    "uid": member.uid,
                    "gid": member.gid,
                    "size": member.size,
                    "xattrs": {k: v for k, v in member.pax_headers.items()
                               if k.startswith("SCHILY.xattr.")},
                }, (tar.extractfile(member) if member.isreg() else None)
    finally:
        proc.kill()


def find(repo: str, ref: str, match, jobs: int = 10):
    """[(layer index, layer, entry-or-None, metadata)] for every match.

    Later layers override earlier ones in an overlay, so a path present in more
    than one layer is reported more than once, newest last. Which one wins is
    the caller's call to make and worth seeing.
    """
    tok = token(repo)
    man = amd64_manifest(repo, ref, tok)
    hits: list[tuple] = []

    def scan(item):
        index, layer = item
        try:
            entries = toc_entries(layer_toc(repo, layer, tok))
        except Exception as exc:                       # noqa: BLE001
            print(f"layer {index}: {type(exc).__name__}: {exc}", file=sys.stderr)
            return []
        return [(index, layer, e, None) for e in entries if match(_norm(e.get("name", "")))]

    with ThreadPoolExecutor(max_workers=jobs) as pool:
        for result in pool.map(scan, list(enumerate(man["layers"]))):
            hits += result
    return tok, man, sorted(hits, key=lambda h: h[0])


def _describe(entry: dict) -> str:
    mode = entry.get("mode")
    return (f"{oct(mode)[-4:] if mode else '----'} "
            f"{entry.get('type', '?'):5} {str(entry.get('size', '')):>9}  "
            f"{entry.get('name')}"
            + (f"  xattrs={entry['xattrs']}" if entry.get("xattrs") else ""))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("action", choices=("ls", "stat", "cat"))
    ap.add_argument("image", help="repo:tag, e.g. tuna-os/skipjack:gnome")
    ap.add_argument("path", help="in-image path, no leading slash")
    args = ap.parse_args()

    repo, _, ref = args.image.rpartition(":")
    if not repo:
        return ap.error("image must be repo:tag")
    target = _norm(args.path)

    match = ((lambda n: n.startswith(target)) if args.action == "ls"
             else (lambda n: n == target))
    tok, man, hits = find(repo, ref, match)

    if not hits:
        # A layer with no TOC has to be streamed; only worth it once the cheap
        # path has come up empty.
        found = False
        for index, layer in enumerate(man["layers"]):
            if layer_toc(repo, layer, tok) is not None:
                continue
            for meta, reader in stream_layer(repo, layer, tok, {target}):
                found = True
                if args.action == "cat" and reader is not None:
                    sys.stdout.buffer.write(reader.read())
                else:
                    print(f"[layer {index}] {json.dumps(meta)}")
        if not found:
            print(f"{args.path}: not found in {args.image}", file=sys.stderr)
            return 1
        return 0

    for index, layer, entry, _ in hits:
        # A file is one `reg` entry plus its trailing `chunk` entries, and
        # find() returns every one of them. Acting on a chunk would re-read the
        # whole file once per chunk: `cat file_contexts` returned 5,236,476
        # bytes for a 374,034-byte file that way, the same 14 times over.
        if entry.get("type") == "chunk":
            continue
        if args.action == "cat":
            sys.stdout.buffer.write(
                toc_read(repo, layer, toc_entries(layer_toc(repo, layer, tok)),
                         target, tok))
        elif args.action == "stat":
            print(f"[layer {index}] {json.dumps(entry, indent=1)}")
        else:
            print(f"[layer {index}] {_describe(entry)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
