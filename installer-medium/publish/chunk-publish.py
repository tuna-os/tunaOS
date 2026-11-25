#!/usr/bin/env python3
"""Publish the hybrid medium as a signed installer OCI image (tunaOS#4907).

Usage: chunk-publish.py CELL ISO LAYOUTDIR [--dry-run] [--sign] [--partitions FILE] [--receipt FILE]

Chunks ISO into zstd layers of at most installer_medium.chunk_bytes raw bytes
(contract v1 caps a chunk at 256 MiB) and writes an OCI layout directory: one
layer per chunk in disk order, a config blob with the whole-image sha256 and
chunk table, and annotations naming the base image digest and sysext pin.
This matches the contract in tuna-os/tacklebox#511 that `tacklebox
write-medium` reads; the Go `medium.BuildLayout` there is the reference
producer (tacklebox#512) and this script emits the same schema. With --sign,
cosign signs the manifest digest (CI provides the key); otherwise the script
prints the digest to sign.

tacklebox write-medium proves the bytes: it checks each layer digest,
decompresses, checks each raw chunk sha256, writes in disk order, and
compares the whole stream with the config sha256.

--receipt names the qualification receipt of the run. Its sha256 goes into the
annotation org.tunaos.installer.receipt-sha256. The workflow attests the same
value (predicate https://tunaos.dev/installer/receipt/v1), and the verifier
of tuna-os/tacklebox accepts an image only when the two agree.
"""

import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

CHUNK_MEDIA_TYPE = "application/vnd.tunaos.installer.chunk.v1+zstd"
CONFIG_MEDIA_TYPE = "application/vnd.tunaos.installer.config.v1+json"
SCHEMA_VERSION = 1
MAX_CHUNK_BYTES = 256 << 20

ROOT = Path(__file__).resolve().parents[2]


def load_config():
    spec = importlib.util.spec_from_file_location("c", ROOT / "scripts/lib/tunaos_config.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def plan(total_size, chunk_bytes):
    """(offset, length) pairs tiling total_size with no gap or overlap."""
    if chunk_bytes <= 0 or chunk_bytes > MAX_CHUNK_BYTES:
        raise ValueError(f"chunk size {chunk_bytes} outside 1..{MAX_CHUNK_BYTES}")
    chunks, offset = [], 0
    while offset < total_size:
        length = min(chunk_bytes, total_size - offset)
        chunks.append((offset, length))
        offset += length
    return chunks


def main(argv):
    argv = list(argv)
    receipt = ""
    if "--receipt" in argv:
        at = argv.index("--receipt")
        receipt = "sha256:" + hashlib.sha256(Path(argv[at + 1]).read_bytes()).hexdigest()
        del argv[at : at + 2]
    args = [a for a in argv[1:] if not a.startswith("--")]
    flags = {a for a in argv[1:] if a.startswith("--")}
    if len(args) != 3:
        raise SystemExit(
            "usage: chunk-publish.py CELL ISO LAYOUTDIR [--dry-run] [--sign] [--partitions FILE]"
            " [--receipt FILE]"
        )
    cell, iso_path, layout = args
    iso = Path(iso_path)
    config_module = load_config()
    primary = config_module.load(ROOT / "tunaos.toml")
    medium = config_module.installer_medium_policy()
    row = medium.cell(primary, cell)
    chunk_bytes = primary["installer_medium"]["chunk_bytes"]
    _ = row

    base_image = subprocess.run(
        [str(ROOT / "installer-medium/resolve-cell-image.sh"), cell],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    # A dry run from build-medium.sh names an image that does not exist yet.
    total_size = 0 if "--dry-run" in flags and not iso.exists() else iso.stat().st_size
    chunks = plan(total_size, chunk_bytes)
    if "--dry-run" in flags:
        print(f"chunks: {len(chunks)} x up to {chunk_bytes} bytes for {total_size} byte image")
        print(f"config: {CONFIG_MEDIA_TYPE} schemaVersion={SCHEMA_VERSION}")
        print(f"annotations: cell={cell} base-image={base_image}")
        print("(dry run: no layout written)")
        return 0

    out = Path(layout)
    blobs = out / "blobs" / "sha256"
    blobs.mkdir(parents=True, exist_ok=True)
    whole = hashlib.sha256()
    table, layers = [], []
    with open(iso, "rb") as f:
        for offset, length in chunks:
            raw = f.read(length)
            if len(raw) != length:
                raise SystemExit(f"chunk-publish: short read at {offset}")
            whole.update(raw)
            digest = "sha256:" + hashlib.sha256(raw).hexdigest()
            compressed = subprocess.run(
                ["zstd", "-q", "-c"], input=raw, capture_output=True, check=True
            ).stdout
            blob_digest = "sha256:" + hashlib.sha256(compressed).hexdigest()
            (blobs / blob_digest.removeprefix("sha256:")).write_bytes(compressed)
            table.append({"offset": offset, "length": length, "sha256": digest})
            layers.append(
                {
                    "mediaType": CHUNK_MEDIA_TYPE,
                    "digest": blob_digest,
                    "size": len(compressed),
                    "annotations": {"org.tunaos.installer.chunk": str(len(table) - 1)},
                }
            )
    partitions = []
    if "--partitions" in flags:
        index = argv.index("--partitions")
        partitions = json.loads(Path(argv[index + 1]).read_text())
    config = {
        "schemaVersion": SCHEMA_VERSION,
        "totalSize": total_size,
        "sha256": "sha256:" + whole.hexdigest(),
        "chunks": table,
        "partitions": partitions,
        "bootModes": ["uefi", "usb", "cdrom"],
    }
    config_blob = json.dumps(config).encode()
    config_digest = "sha256:" + hashlib.sha256(config_blob).hexdigest()
    (blobs / config_digest.removeprefix("sha256:")).write_bytes(config_blob)
    manifest = {
        "schemaVersion": 2,
        "mediaType": "application/vnd.oci.image.manifest.v1+json",
        "config": {
            "mediaType": CONFIG_MEDIA_TYPE,
            "digest": config_digest,
            "size": len(config_blob),
        },
        "layers": layers,
        "annotations": {
            "org.tunaos.installer.cell": cell,
            "org.tunaos.installer.base-image": base_image,
            "org.tunaos.installer.systemd-ref": primary["installer_medium"]["systemd_ref"],
        },
    }
    if receipt:
        manifest["annotations"]["org.tunaos.installer.receipt-sha256"] = receipt
    manifest_blob = json.dumps(manifest).encode()
    manifest_digest = "sha256:" + hashlib.sha256(manifest_blob).hexdigest()
    (blobs / manifest_digest.removeprefix("sha256:")).write_bytes(manifest_blob)
    (out / "index.json").write_text(
        json.dumps(
            {
                "schemaVersion": 2,
                "manifests": [
                    {
                        "mediaType": "application/vnd.oci.image.manifest.v1+json",
                        "digest": manifest_digest,
                        "size": len(manifest_blob),
                    }
                ],
            }
        )
    )
    (out / "oci-layout").write_text('{"imageLayoutVersion":"1.0.0"}')
    print(manifest_digest)
    if "--sign" in flags:
        subprocess.run(
            [
                "cosign",
                "sign-blob",
                "--yes",
                "--digest",
                manifest_digest,
                "--output-signature",
                str(out / "cosign.sig"),
            ],
            check=True,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
