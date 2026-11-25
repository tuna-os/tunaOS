#!/usr/bin/env python3
"""Read the installer probe's inputs from published images (tunaOS#4905).

Usage: installer-medium/evidence/scan-images.py [--cell CELL]... [--first CELL]...
           [--jobs N] [--cache DIR] [--out installer-medium/evidence/images.json]

For each medium candidate cell (every variant:flavor in tunaos.toml that
builds an image and has a desktop frontend, plus tromso:kde) the script reads
the image manifest and streams each layer from the registry. It keeps only the
paths that live-iso/common/src/installer-recipe-backend.sh reads: the bootupd
and EFI payload names, the systemd-boot binary names, the kernel directories
below usr/lib/modules, and the text of prepare-root.conf and os-release. It also keeps
the name of a signed systemd-boot binary (`.efi.signed`) for tunaOS#4955. It
then rebuilds that tree, runs the real probe with the btrfs opt-in, and writes
one record per cell with the image digest and the read date. A cell whose
image is absent or unreadable gets `unverified` with the reason. Nothing is
pulled to disk; a per-layer cache makes shared layers cost one read.

Only this script uses the network. scripts/lib/installer_medium.py and the
tests read the checked-in images.json.
"""

import argparse
import concurrent.futures
import datetime
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PROBE = ROOT / "live-iso/common/src/installer-recipe-backend.sh"
ACCEPT = ", ".join(
    (
        "application/vnd.oci.image.index.v1+json",
        "application/vnd.oci.image.manifest.v1+json",
        "application/vnd.docker.distribution.manifest.list.v2+json",
        "application/vnd.docker.distribution.manifest.v2+json",
    )
)
NAMES = re.compile(
    r"usr/lib/bootupd/updates/EFI\.json"
    r"|usr/lib/bootupd/updates/EFI/[^/]+/grub[^/]*\.efi"
    r"|usr/lib/efi/grub2/(.*/)?grub[^/]*\.efi"
    r"|usr/lib/efi/shim/(.*/)?shim[^/]*\.efi"
    r"|usr/lib/systemd/boot/efi/(.*/)?systemd-boot[^/]*\.efi(\.signed)?"
)
TEXTS = ("usr/lib/ostree/prepare-root.conf", "usr/lib/os-release", "etc/os-release")
KERNEL = re.compile(r"usr/lib/modules/([^/]+)(/.*)?")
# A whiteout matters when it removes a tracked path or one of its parents.
ROOTS = ("usr/lib/bootupd", "usr/lib/efi", "usr/lib/systemd/boot", "usr/lib/modules", "usr/lib/ostree", *TEXTS)
OS_KEYS = ("ID", "ID_LIKE", "VERSION_ID", "VARIANT_ID")


def config_module():
    spec = importlib.util.spec_from_file_location("c", ROOT / "scripts/lib/tunaos_config.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fetch(url, headers, method="GET"):
    request = urllib.request.Request(url, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read(), response.headers


def token(registry, repo):
    if registry != "ghcr.io":
        raise RuntimeError(f"no anonymous token flow for {registry}")
    body, _ = fetch(f"https://ghcr.io/token?scope=repository:{repo}:pull", {})
    return json.loads(body)["token"]


def manifest(registry, repo, reference):
    body, _ = fetch(
        f"https://{registry}/v2/{repo}/manifests/{reference}",
        {"Authorization": f"Bearer {token(registry, repo)}", "Accept": ACCEPT},
    )
    return json.loads(body), "sha256:" + hashlib.sha256(body).hexdigest()


def related(path):
    return any(path == r or path.startswith(r + "/") or r.startswith(path + "/") for r in ROOTS)


def read_layer(registry, repo, layer, cache):
    """The tracked entries of one layer: [kind, path, value] rows in tar order."""
    digest = layer["digest"]
    cached = cache / (digest.replace(":", "-") + ".json")
    if cached.exists():
        return json.loads(cached.read_text())
    media = layer.get("mediaType", "")
    unpack = ["zstd", "-dc"] if "zstd" in media else ["gzip", "-dc"]
    curl = subprocess.Popen(
        ["curl", "-sSfL", "--retry", "3", "-H", f"Authorization: Bearer {token(registry, repo)}",
         f"https://{registry}/v2/{repo}/blobs/{digest}"],
        stdout=subprocess.PIPE,
    )
    plain = subprocess.Popen(unpack, stdin=curl.stdout, stdout=subprocess.PIPE)
    curl.stdout.close()
    rows = []
    with tarfile.open(fileobj=plain.stdout, mode="r|") as archive:
        for member in archive:
            path = member.name.lstrip("./").rstrip("/")
            base = os.path.basename(path)
            parent = os.path.dirname(path)
            if base == ".wh..wh..opq":
                if related(parent):
                    rows.append(["opaque", parent, ""])
            elif base.startswith(".wh."):
                gone = os.path.join(parent, base[4:])
                if related(gone):
                    rows.append(["whiteout", gone, ""])
            elif path in TEXTS:
                if member.isreg():
                    rows.append(["text", path, archive.extractfile(member).read(65536).decode("utf-8", "replace")])
                elif member.issym() or member.islnk():
                    rows.append(["link", path, member.linkname])
            elif NAMES.fullmatch(path) and (member.isreg() or member.islnk() or member.issym()):
                rows.append(["file", path, ""])
            else:
                kernel = KERNEL.fullmatch(path)
                if kernel and (kernel.group(2) or member.isdir()):
                    rows.append(["kernel", "usr/lib/modules/" + kernel.group(1), ""])
    if plain.wait() != 0 or curl.wait() != 0:
        raise RuntimeError(f"layer {digest} did not download or unpack")
    seen, unique = set(), []
    for row in rows:
        if tuple(row) not in seen:
            seen.add(tuple(row))
            unique.append(row)
    temporary = cached.with_suffix(f".{os.getpid()}.{hash(digest) & 0xFFFF}.tmp")
    temporary.write_text(json.dumps(unique))
    temporary.replace(cached)
    return unique


def merge(layers):
    """Apply the layers in order; return {path: [kind, value]} of the final tree."""
    tree = {}
    for rows in layers:
        for kind, path, _ in rows:
            if kind in ("whiteout", "opaque"):
                for known in [p for p in tree if p == path or p.startswith(path + "/")]:
                    if kind == "whiteout" or known != path:
                        del tree[known]
        for kind, path, value in rows:
            if kind not in ("whiteout", "opaque"):
                tree[path] = [kind, value]
    return tree


def os_release(text):
    keep = []
    for line in text.splitlines():
        if line.partition("=")[0] in OS_KEYS:
            keep.append(line)
    return "\n".join(keep) + "\n"


def facts_of(tree):
    """The probe's inputs, small enough to check in."""
    texts = {}
    for path in TEXTS:
        kind, value = tree.get(path, [None, None])
        if kind == "link":
            target = os.path.normpath(os.path.join(os.path.dirname(path), value)).lstrip("/")
            kind, value = tree.get(target, [None, None])
        if kind == "text":
            texts[path] = value
    facts = {
        "files": sorted(p for p, (kind, _) in tree.items() if kind == "file"),
        "kernels": sorted(os.path.basename(p) for p, (kind, _) in tree.items() if kind == "kernel"),
    }
    if "usr/lib/ostree/prepare-root.conf" in texts:
        facts["prepare_root_conf"] = texts["usr/lib/ostree/prepare-root.conf"]
    release = texts.get("usr/lib/os-release", texts.get("etc/os-release"))
    if release is not None:
        facts["os_release"] = os_release(release)
    return facts


def build_tree(facts, root):
    """Rebuild the probe's view of an image from its recorded facts."""
    root = Path(root)
    for rel in facts.get("files", []):
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_bytes(b"")
    for kernel in facts.get("kernels", []):
        (root / "usr/lib/modules" / kernel).mkdir(parents=True, exist_ok=True)
    if "prepare_root_conf" in facts:
        (root / "usr/lib/ostree").mkdir(parents=True, exist_ok=True)
        (root / "usr/lib/ostree/prepare-root.conf").write_text(facts["prepare_root_conf"])
    if "os_release" in facts:
        (root / "usr/lib").mkdir(parents=True, exist_ok=True)
        (root / "usr/lib/os-release").write_text(facts["os_release"])
    return root


def run_probe(facts):
    """Run the real probe on the facts. Returns (result, error)."""
    with tempfile.TemporaryDirectory() as tmp:
        done = subprocess.run(
            ["bash", str(PROBE), str(build_tree(facts, tmp))],
            capture_output=True, text=True,
            env={**os.environ, "TUNAOS_INSTALLER_ALLOW_BTRFS": "1"},
        )
    if done.returncode != 0:
        return None, " ".join(done.stderr.split())[:200]
    return dict(line.split("=", 1) for line in done.stdout.splitlines()), None


def plan(cell, ref, arch, today):
    """Read the manifests of one cell. Returns (record, registry, repo, layers)."""
    record = {"cell": cell, "image": ref, "read": today}
    registry, _, rest = ref.partition("/")
    repo, _, tag = rest.partition(":")
    try:
        index, digest = manifest(registry, repo, tag)
    except urllib.error.HTTPError as error:
        record["unverified"] = f"image not published: {ref} answered HTTP {error.code}"
        return record, registry, repo, []
    except Exception as error:  # noqa: BLE001 - every failure becomes a reason
        record["unverified"] = f"image not readable: {type(error).__name__}: {error}"[:200]
        return record, registry, repo, []
    record["digest"] = digest
    try:
        image = index
        if "manifests" in index:
            choices = [m for m in index["manifests"] if m.get("platform", {}).get("os") == "linux"]
            wanted = [m for m in choices if m["platform"].get("architecture") == arch] or choices
            if not wanted:
                record["unverified"] = "image index has no linux manifest"
                return record, registry, repo, []
            record["platform"] = "linux/" + wanted[0]["platform"]["architecture"]
            record["manifest"] = wanted[0]["digest"]
            image, _ = manifest(registry, repo, wanted[0]["digest"])
        else:
            record["platform"] = "linux/" + arch
        return record, registry, repo, image["layers"]
    except Exception as error:  # noqa: BLE001
        record["unverified"] = f"manifest not readable: {type(error).__name__}: {error}"[:200]
        return record, registry, repo, []


def read_layer_job(job):
    """Process-pool entry: (digest, rows) or (digest, error text)."""
    registry, repo, layer, cache = job
    try:
        return layer["digest"], read_layer(registry, repo, layer, Path(cache))
    except Exception as error:  # noqa: BLE001
        return layer["digest"], f"{type(error).__name__}: {error}"[:200]


def finish(record, layers, read):
    """Complete one record from its layers' tracked entries."""
    failed = [read[layer["digest"]] for layer in layers if isinstance(read[layer["digest"]], str)]
    if failed:
        record["unverified"] = f"layers not readable: {failed[0]}"
        return record
    record["facts"] = facts_of(merge([read[layer["digest"]] for layer in layers]))
    probe, error = run_probe(record["facts"])
    if probe is None:
        record["unverified"] = f"probe cannot classify the image: {error}"
    else:
        record["probe"] = probe
    return record


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cell", action="append", default=[])
    parser.add_argument("--jobs", type=int, default=os.cpu_count() or 4)
    parser.add_argument("--cache", type=Path, default=Path(tempfile.gettempdir()) / "medium-evidence-cache")
    parser.add_argument("--out", type=Path, default=HERE / "images.json")
    parser.add_argument("--first", action="append", default=[], help="a cell to read before the others")
    args = parser.parse_args(argv)
    # Read the table without config validation: validation needs the evidence
    # this script writes.
    with open(ROOT / "tunaos.toml", "rb") as handle:
        primary = tomllib.load(handle)
    medium = config_module().installer_medium_policy()
    candidates = medium.scan_candidates(primary)
    if args.cell:
        unknown = set(args.cell) - {c["cell"] for c in candidates}
        if unknown:
            parser.error(f"not a medium candidate: {sorted(unknown)}")
        candidates = [c for c in candidates if c["cell"] in args.cell]
    args.cache.mkdir(parents=True, exist_ok=True)
    today = datetime.date.today().isoformat()
    previous = {}
    if args.out.exists():
        previous = {r["cell"]: r for r in json.loads(args.out.read_text())["images"]}
    # Manifests first (threads: network only), then each distinct layer once
    # (processes: the tar walk is CPU-bound). Layers go in cell order, so the
    # first cells finish first, and the file is rewritten as each cell
    # completes: a scan that stops early keeps what it read.
    order = {name: i for i, name in enumerate(args.first)}
    candidates.sort(key=lambda c: order.get(c["cell"], len(order)))
    with concurrent.futures.ThreadPoolExecutor(16) as pool:
        plans = list(pool.map(lambda c: plan(c["cell"], c["image"], c["arch"], today), candidates))
    jobs, waiting = {}, {}
    for number, (_, registry, repo, layers) in enumerate(plans):
        for layer in layers:
            jobs.setdefault(layer["digest"], (registry, repo, layer, str(args.cache)))
            waiting.setdefault(layer["digest"], set()).add(number)
    left = [len({layer["digest"] for layer in layers}) for _, _, _, layers in plans]

    def write(record):
        previous[record["cell"]] = record
        print(f"{record['cell']}: {record.get('probe') or record.get('unverified')}", file=sys.stderr, flush=True)
        args.out.write_text(
            json.dumps({"schema_version": 1, "images": [previous[c] for c in sorted(previous)]}, indent=1) + "\n"
        )

    for record, _, _, layers in plans:
        if not layers:
            write(record)
    read = {}
    with concurrent.futures.ProcessPoolExecutor(args.jobs) as pool:
        futures = [pool.submit(read_layer_job, job) for job in jobs.values()]
        for future in concurrent.futures.as_completed(futures):
            digest, rows = future.result()
            read[digest] = rows
            for number in waiting[digest]:
                left[number] -= 1
                if left[number] == 0:
                    record, _, _, layers = plans[number]
                    write(finish(record, layers, read))
    return 0


if __name__ == "__main__":
    sys.exit(main())
