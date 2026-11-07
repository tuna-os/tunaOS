#!/usr/bin/env python3
"""Generate the browser ISO builder's CatalogSnapshot v1 from tunaos.toml.

tuna-os/iso-builder resolves every buildable target from
app/public/catalog-snapshot.json (a byte-identical copy lives at
native/catalog-snapshot.json). This script is the producer of that file:

  targets         one entry per tunaos.toml `build_image = true` flavor and
                  each of its platforms (a flavor's `platforms` replaces the
                  variant's), keyed `<variant>:<flavor>:<platform>`.
  publication     <publish destination>/<publish_name or id>:<flavor>[-<tag_suffix>],
                  the rule scripts/published-image-ref.sh applies.
  availability    registry mode reads the published OCI index with skopeo and
                  selects the descriptor for the exact platform (linux/amd64
                  never matches the amd64/v2 entry). Offline mode keeps the
                  prior snapshot's availability, digests and facts.
  qualification   `unsupported` for base and hardware-specific flavors;
                  `qualified` only when a committed BrowserIsoQualificationReceipt/v1
                  (iso-qualification/receipts/) names the variant/flavor and the
                  registry still holds its linux/amd64 imageDigest. The amd64
                  target builds that receipt image: resolvedInputs pin
                  platformManifestDigest (and liveOverlayBaseDigest) to it after
                  the tag moves on, while facts.digest records the tag's current
                  digest. A receipt for the current digest wins over an older one.
                  A linux/arm64 target is never qualified: an amd64 receipt
                  proves nothing about an arm64 install or boot, so it is
                  `unqualified` with `platform-has-no-receipt-basis` until a
                  receipt from an arm64 guest exists (RECEIPT_BASIS in
                  scripts/iso-delivery-policy.py).
                  A receipt whose image is gone gives `stale-qualification-receipt`.
                  A receipt image or index the registry cannot be asked about
                  (offline, or a failed lookup) counts as present only when the
                  prior snapshot resolved it; otherwise the target is
                  `qualification-receipt-image-undetermined`.

The same inputs always give the same bytes: targets are sorted, JSON is
key-sorted, and the only clock reading is the registry-mode default of
--generated-at. A qualified entry carries only facts the receipt holds; the
receipt has no browser profile, so `browser` and `browserBuildReceiptDigest`
stay null.

Usage:
  generate-catalog-snapshot.py --output catalog-snapshot.json [--prior OLD] [--facts catalog-facts.json]
  generate-catalog-snapshot.py --offline --prior OLD --output catalog-snapshot.json

Registry mode records the digests, layer count, compressed size and bootc label
of each target; the package manager comes from the variant's Containerfile
route. `--facts` takes the catalog-facts.json artifact of
.github/workflows/catalog-facts.yml (`gh run download -R tuna-os/tunaOS -n
catalog-facts <run>`). Its kernel, desktop and systemd-boot facts apply to a
linux/amd64 target only while its digest equals that target's current index
digest.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import qualification_receipt, tunaos_config
from lib.publish_destination import publish_destination

ROOT = Path(__file__).resolve().parents[1]
_POLICY_SPEC = importlib.util.spec_from_file_location(
    "iso_delivery_policy_for_catalog", ROOT / "scripts" / "iso-delivery-policy.py")
assert _POLICY_SPEC and _POLICY_SPEC.loader
_POLICY = importlib.util.module_from_spec(_POLICY_SPEC)
_POLICY_SPEC.loader.exec_module(_POLICY)
# The platforms a receipt can qualify (those with a guest that booted it).
# Only these targets pin a receipt image; every other platform has no basis.
BASIS_PLATFORMS = frozenset(_POLICY.RECEIPT_BASIS)
# Copied from a prior snapshot's resolvedInputs when the registry is not asked.
PIN_KEYS = ("configDigest", "indexDigest", "platformManifestDigest")

# platform -> (OCI architecture, OCI variant, CPU baseline)
PLATFORMS = {
    "linux/amd64": ("amd64", None, "x86-64"),
    "linux/amd64/v2": ("amd64", "v2", "x86-64-v2"),
    "linux/amd64/v3": ("amd64", "v3", "x86-64-v3"),
    "linux/arm64": ("arm64", None, "armv8-a"),
}
# CentOS Stream 10 and ELN are compiled for x86-64-v3 even when the OCI
# platform is plain amd64 (https://www.centos.org/centos10/).
NATIVE_V3_VARIANTS = frozenset({"skipjack", "wahoo"})
# OCI platform variants that mean "no variant" for that architecture.
BASELINE_VARIANTS = {"amd64": {None, "v1"}, "arm64": {None, "v8"}}
INDEX_TYPES = frozenset({
    "application/vnd.oci.image.index.v1+json",
    "application/vnd.docker.distribution.manifest.list.v2+json",
})
# The OCI distribution error codes for a missing tag or repository. Anything
# else (403 for an unknown GHCR package, timeouts) is inconclusive.
ABSENT_MARKERS = ("manifest unknown", "name unknown")
STATUSES = ("qualified", "local-only", "unqualified", "unsupported")
# Package manager (tunaos_config.ROUTE_MANAGERS) -> the family name the ISO
# builder's package search and catalog-facts.yml use.
REPO_FAMILIES = {"dnf": "fedora", "zypper": "opensuse", "pacman": "arch", "apt": "debian", "emerge": "gentoo"}

Fetch = Callable[[str, bool], "bytes | None"]


class CatalogError(RuntimeError):
    """The snapshot cannot be generated truthfully from these inputs."""


class Inconclusive(RuntimeError):
    """A registry lookup failed for a reason other than an absent manifest."""


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("utf-8")


def sha256(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def hardware_scope(flavor: str) -> str:
    tokens = flavor.split("-")
    if "asahi" in tokens:
        return "apple-silicon"
    if "t2" in tokens:
        return "apple-t2"
    return "generic"


def cpu_baseline(variant: str, platform: str) -> str:
    if platform == "linux/amd64" and variant in NATIVE_V3_VARIANTS:
        return "x86-64-v3"
    return PLATFORMS[platform][2]


def is_base(flavor: str) -> bool:
    return flavor == "base" or flavor.startswith("base-")


def default_desktop(flavor: str) -> str:
    return "" if is_base(flavor) else flavor.split("-")[0]


def built_targets(matrix: dict[str, Any], destination: str) -> list[dict[str, Any]]:
    """Every built <variant>:<flavor>:<platform> with its publication."""
    records = []
    for variant in matrix["variants"]:
        variant_id = variant["id"]
        name = variant.get("publish_name") or variant_id
        suffix = variant.get("tag_suffix") or ""
        repository = f"{destination}/{name}"
        for flavor in variant["flavors"]:
            if flavor.get("build_image") is not True:
                continue
            flavor_id = flavor["id"]
            platforms = flavor.get("platforms", variant.get("platforms"))
            if not platforms:
                raise CatalogError(f"{variant_id}:{flavor_id} builds no platform")
            tag = f"{flavor_id}-{suffix}" if suffix else flavor_id
            for platform in platforms:
                if platform not in PLATFORMS:
                    raise CatalogError(f"{variant_id}:{flavor_id}: unknown platform {platform!r}")
                records.append({
                    "target": {
                        "variant": variant_id,
                        "flavor": flavor_id,
                        "platform": platform,
                        "cpuBaseline": cpu_baseline(variant_id, platform),
                        "hardwareScope": hardware_scope(flavor_id),
                    },
                    "required": True,
                    "scheduled": True,
                    "publication": {"repository": repository, "tag": tag},
                })
    records.sort(key=lambda r: target_key(r["target"]))
    keys = [target_key(r["target"]) for r in records]
    if len(set(keys)) != len(keys):
        raise CatalogError("tunaos.toml lists one target twice")
    return records


def target_key(target: dict[str, str]) -> str:
    return f"{target['variant']}:{target['flavor']}:{target['platform']}"


def oci_platform(platform: str) -> dict[str, str | None]:
    arch, variant, _ = PLATFORMS[platform]
    return {"architecture": arch, "os": "linux", "variant": variant}


# ── registry ────────────────────────────────────────────────────────────────


def skopeo_fetch(skopeo: str) -> Fetch:
    """Raw manifest (or config, when `config`) bytes; None when the tag is absent."""
    def fetch(ref: str, config: bool) -> bytes | None:
        argv = [skopeo, "inspect", "--raw", "--retry-times", "3"]
        if config:
            argv.append("--config")
        result = subprocess.run([*argv, f"docker://{ref}"], capture_output=True, check=False)
        if result.returncode == 0:
            return result.stdout
        message = result.stderr.decode("utf-8", "replace").strip()
        if any(marker in message.lower() for marker in ABSENT_MARKERS):
            return None
        last = message.splitlines()[-1][-300:] if message else f"skopeo exited {result.returncode}"
        raise Inconclusive(f"{ref}: {last}")
    return fetch


def _platform_of(entry: dict[str, Any]) -> tuple[str | None, str | None, str | None]:
    os_name = entry.get("os")
    arch = entry.get("architecture")
    variant = entry.get("variant")
    if isinstance(arch, str) and "/" in arch:
        # podman writes a v2 manifest list entry as architecture "amd64/v2".
        arch, _, variant = arch.partition("/")
    return os_name, arch, variant


def _matches(entry: dict[str, Any], platform: str) -> bool:
    os_name, arch, variant = _platform_of(entry)
    want_arch, want_variant, _ = PLATFORMS[platform]
    if os_name != "linux" or arch != want_arch:
        return False
    if want_variant is None:
        return variant in BASELINE_VARIANTS[want_arch]
    return variant == want_variant


def _json(data: bytes, what: str) -> dict[str, Any]:
    try:
        value = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise Inconclusive(f"{what} is not JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise Inconclusive(f"{what} is not a JSON object")
    return value


def resolve(fetch: Fetch, repository: str, index_raw: bytes, platform: str) -> dict[str, Any] | None:
    """Descriptor facts for one platform of a published tag, or None if absent."""
    top = _json(index_raw, f"{repository} manifest")
    if top.get("mediaType") in INDEX_TYPES or "manifests" in top:
        index_digest: str | None = sha256(index_raw)
        found = [d for d in top.get("manifests") or [] if _matches(d.get("platform") or {}, platform)]
        if not found:
            return None
        if len(found) > 1:
            raise Inconclusive(f"{repository} index lists {platform} {len(found)} times")
        digest = found[0].get("digest")
        manifest_raw = fetch(f"{repository}@{digest}", False)
        if manifest_raw is None:
            return None
        if sha256(manifest_raw) != digest:
            raise Inconclusive(f"{repository}@{digest} bytes do not hash to their digest")
    else:
        index_digest = None
        manifest_raw = index_raw
        digest = sha256(manifest_raw)
    manifest = _json(manifest_raw, f"{repository}@{digest}")
    config_raw = fetch(f"{repository}@{digest}", True)
    if config_raw is None:
        return None
    config = _json(config_raw, f"{repository}@{digest} config")
    if index_digest is None and not _matches(config, platform):
        return None
    layers = manifest.get("layers") or []
    labels = (config.get("config") or {}).get("Labels") or {}
    return {
        "indexDigest": index_digest,
        "platformManifestDigest": digest,
        "configDigest": (manifest.get("config") or {}).get("digest"),
        "layerCount": len(layers),
        "compressedSize": sum(int(layer.get("size") or 0) for layer in layers),
        "bootc": labels.get("containers.bootc") == "1",
    }


def observe_registry(records: list[dict[str, Any]], fetch: Fetch, jobs: int
                     ) -> dict[str, dict[str, Any] | None | Inconclusive]:
    """targetKey -> descriptor facts, None (absent) or the Inconclusive error."""
    refs = sorted({f"{r['publication']['repository']}:{r['publication']['tag']}" for r in records})

    def get_index(ref: str) -> bytes | None | Inconclusive:
        try:
            return fetch(ref, False)
        except Inconclusive as exc:
            return exc

    with ThreadPoolExecutor(max_workers=jobs) as pool:
        indexes = dict(zip(refs, pool.map(get_index, refs)))

    def get_target(record: dict[str, Any]) -> tuple[str, dict[str, Any] | None | Inconclusive]:
        pub = record["publication"]
        key = target_key(record["target"])
        index_raw = indexes[f"{pub['repository']}:{pub['tag']}"]
        if index_raw is None or isinstance(index_raw, Inconclusive):
            return key, index_raw
        try:
            return key, resolve(fetch, pub["repository"], index_raw, record["target"]["platform"])
        except Inconclusive as exc:
            return key, exc

    with ThreadPoolExecutor(max_workers=jobs) as pool:
        return dict(pool.map(get_target, records))


def receipt_images(records: list[dict[str, Any]],
                   receipts: dict[tuple[str, str], list[tuple[str, dict[str, Any]]]],
                   observed: dict[str, dict[str, Any] | None]) -> list[tuple[str, str]]:
    """(repository@imageDigest, platform) of each receipt image the tag no longer publishes."""
    wanted = set()
    for record in records:
        target = record["target"]
        if target["platform"] not in BASIS_PLATFORMS:
            continue
        current = (observed.get(target_key(target)) or {}).get("platformManifestDigest")
        for _, receipt in receipts.get((target["variant"], target["flavor"]), []):
            proven = receipt["target"]
            if proven["platform"] == target["platform"] and proven["imageDigest"] != current:
                wanted.add((f"{record['publication']['repository']}@{proven['imageDigest']}",
                            target["platform"]))
    return sorted(wanted)


def observe_receipt_images(wanted: list[tuple[str, str]], fetch: Fetch, jobs: int
                           ) -> dict[str, dict[str, Any] | None | Inconclusive]:
    """repository@digest -> its platform manifest facts, None (absent) or the Inconclusive error."""
    def get(item: tuple[str, str]) -> tuple[str, dict[str, Any] | None | Inconclusive]:
        ref, platform = item
        repository, _, image = ref.partition("@")
        try:
            raw = fetch(ref, False)
            if raw is None:
                return ref, None
            if sha256(raw) != image:
                raise Inconclusive(f"{ref} bytes do not hash to their digest")
            found = resolve(fetch, repository, raw, platform)
        except Inconclusive as exc:
            return ref, exc
        # A receipt proves one platform manifest; an index or another platform
        # under that digest is not the image it proved.
        if found is None or found["indexDigest"] is not None:
            return ref, None
        return ref, found

    with ThreadPoolExecutor(max_workers=jobs) as pool:
        return dict(pool.map(get, wanted))


def under(refs: dict[str, Any], repository: str) -> dict[str, Any]:
    """digest -> value for the repository@digest keys of one repository."""
    prefix = f"{repository}@"
    return {ref[len(prefix):]: value for ref, value in refs.items() if ref.startswith(prefix)}


# ── facts, receipts, qualification ──────────────────────────────────────────


def prior_observation(entry: dict[str, Any] | None, publication_ref: str) -> dict[str, Any] | None:
    """What a prior snapshot observed for the same publication, if anything."""
    if not entry or (entry.get("publication") or {}).get("ref") != publication_ref:
        return None
    available = (entry.get("availability") or {}).get("available") is True
    facts = entry.get("facts") or {}
    # facts.digest is the tag's digest; a pinned entry's resolvedInputs
    # describe its receipt image instead.
    digest = facts.get("digest")
    if not available or not isinstance(digest, str):
        return {"available": False}
    inputs = entry.get("resolvedInputs") or {}
    same = inputs.get("platformManifestDigest") == digest
    return {
        "available": True,
        "indexDigest": inputs.get("indexDigest") if same else None,
        "platformManifestDigest": digest,
        "configDigest": inputs.get("configDigest") if same else None,
        "facts": {key: facts.get(key) for key in FACT_KEYS},
    }


def prior_pins(prior: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    """repository@digest -> the resolvedInputs a prior snapshot built that image from."""
    pins = {}
    for entry in (prior or {}).get("targets") or []:
        inputs = entry.get("resolvedInputs") or {}
        repository = (entry.get("publication") or {}).get("repository")
        image = inputs.get("platformManifestDigest")
        if isinstance(repository, str) and isinstance(image, str):
            pins[f"{repository}@{image}"] = {key: inputs.get(key) for key in PIN_KEYS}
    return pins


FACT_KEYS = ("bootc", "compressedSize", "desktop", "digest", "hasSdBoot",
             "kernelVer", "layerCount", "pkgManager", "repoFamily")


def build_facts(target: dict[str, str], observed: dict[str, Any] | None,
                probes: dict[str, dict[str, Any]], namespace: str, manager: str) -> dict[str, Any]:
    if observed is None or not observed.get("available"):
        return {"bootc": False, "compressedSize": 0, "desktop": default_desktop(target["flavor"]),
                "digest": None, "hasSdBoot": False, "kernelVer": "", "layerCount": 0,
                "pkgManager": "", "repoFamily": ""}
    if "facts" in observed:  # offline: keep the prior facts as they were
        return dict(observed["facts"])
    facts = {
        "bootc": observed["bootc"],
        "compressedSize": observed["compressedSize"],
        "desktop": default_desktop(target["flavor"]),
        "digest": observed["platformManifestDigest"],
        "hasSdBoot": False,
        "kernelVer": "",
        "layerCount": observed["layerCount"],
        # The variant's Containerfile route fixes its package manager.
        "pkgManager": manager,
        "repoFamily": REPO_FAMILIES.get(manager, ""),
    }
    probe = probes.get(f"{namespace}/{target['variant']}:{target['flavor']}")
    # catalog-facts.yml probes the amd64 image of the index it names; its
    # facts describe no other platform and no other index.
    if (probe and target["platform"] == "linux/amd64" and observed["indexDigest"]
            and probe.get("digest") == observed["indexDigest"]):
        facts.update(
            desktop=str(probe.get("desktop") or facts["desktop"]),
            hasSdBoot=probe.get("hasSdBoot") is True,
            kernelVer=str(probe.get("kernelVer") or ""),
        )
    return facts


def committed_receipts(receipts_dir: Path) -> dict[tuple[str, str], list[tuple[str, dict[str, Any]]]]:
    """(variant, flavor) -> [(receipt digest, receipt)], newest first."""
    found: dict[tuple[str, str], list[tuple[str, dict[str, Any]]]] = {}
    for path in sorted(receipts_dir.glob("*.json")):
        evidence = f"sha256:{path.stem}"
        try:
            receipt = qualification_receipt.load(evidence, receipts_dir)
        except qualification_receipt.ReceiptError as exc:
            raise CatalogError(f"{path}: {exc}") from exc
        target = receipt["target"]
        found.setdefault((target["variant"], target["flavor"]), []).append((evidence, receipt))
    for entries in found.values():
        entries.sort(key=lambda item: (item[1]["qualifiedAt"], item[0]), reverse=True)
    return found


def unqualified(reason: str, status: str = "unqualified") -> dict[str, Any]:
    return {"browser": None, "qualifiedAt": None, "reason": reason, "receiptDigest": None,
            "resources": None, "status": status}


def qualified(evidence: str, receipt: dict[str, Any]) -> dict[str, Any]:
    producer = receipt["producer"]
    return {
        "browser": None,
        "browserBuildReceiptDigest": None,
        "buildOrigin": "browser",
        "isoDigest": receipt["iso"]["sha256"],
        "producer": {key: producer[key] for key in
                     ("repository", "workflow", "ref", "sha", "runId", "runAttempt")},
        "qualifiedAt": receipt["qualifiedAt"],
        "reason": None,
        "receiptDigest": evidence,
        "receiptImageDigest": receipt["target"]["imageDigest"],
        "receiptPlatform": receipt["target"]["platform"],
        "receiptSchema": receipt["schema"],
        "resources": None,
        "status": "qualified",
    }


def lapsed(reason: str, evidence: str, receipt: dict[str, Any]) -> dict[str, Any]:
    held = unqualified(reason)
    held.update(qualifiedAt=receipt["qualifiedAt"], receiptDigest=evidence)
    return held


def choose_receipt(proven: list[tuple[str, dict[str, Any]]], basis_digest: str | None,
                   pins: dict[str, dict[str, Any] | None]
                   ) -> tuple[str, str, dict[str, Any], dict[str, Any] | None] | None:
    """(kind, receipt digest, receipt, pinned basis image) the basis target builds.

    kind is `current` (the tag still publishes the receipt image), `pinned`
    (the tag moved on; the newest receipt image the registry still holds) or
    `undetermined`. None when no receipt image is left. `pins` maps a receipt
    image digest to its inputs, to None when the registry no longer holds it,
    and lacks it when that is undetermined.
    """
    for evidence, receipt in proven:
        if receipt["target"]["imageDigest"] == basis_digest:
            return "current", evidence, receipt, None
    for evidence, receipt in proven:
        image = receipt["target"]["imageDigest"]
        if image not in pins:
            return "undetermined", evidence, receipt, None
        if pins[image] is not None:
            return "pinned", evidence, receipt, pins[image]
    return None


def qualify(target: dict[str, str], digest: str | None,
            receipts: list[tuple[str, dict[str, Any]]], prior: dict[str, Any] | None,
            pins: dict[str, dict[str, Any] | None]
            ) -> tuple[dict[str, Any], dict[str, Any] | None, dict[str, Any] | None]:
    """(qualification, receipt inputs to bind, pinned image inputs) for one target.

    `pins` holds the target's receipt images (see choose_receipt). The pinned
    image is None while the target builds the tag's current image.
    """
    if target["hardwareScope"] != "generic" or is_base(target["flavor"]):
        return unqualified("hardware-scope-unsupported", "unsupported"), None, None
    if digest is None:
        return unqualified("missing-platform-descriptor"), None, None
    if target["platform"] not in BASIS_PLATFORMS:
        # A receipt proves the platform of the guest that booted it; an amd64
        # receipt says nothing about an arm64 install, so no receipt qualifies it.
        return unqualified("platform-has-no-receipt-basis"), None, None
    proven = [item for item in receipts if item[1]["target"]["platform"] == target["platform"]]
    choice = choose_receipt(proven, digest, pins)
    if choice is not None:
        kind, evidence, receipt, pin = choice
        if kind == "undetermined":
            return lapsed("qualification-receipt-image-undetermined", evidence, receipt), None, None
        # The receipt proves those bytes, not the tag.
        return qualified(evidence, receipt), receipt["inputs"], pin
    if receipts:
        evidence, receipt = receipts[0]
        return lapsed("stale-qualification-receipt", evidence, receipt), None, None
    prior_q = (prior or {}).get("qualification") or {}
    prior_digest = ((prior or {}).get("resolvedInputs") or {}).get("platformManifestDigest")
    if prior_q.get("status") == "local-only" and prior_digest == digest:
        # A local-only finding measures these exact bytes; it lapses with them.
        return dict(prior_q), None, None
    return unqualified("no-qualification-receipt"), None, None


# ── snapshot ────────────────────────────────────────────────────────────────


def build_snapshot(matrix: dict[str, Any], *, destination: str,
                   observed: dict[str, dict[str, Any] | None],
                   receipts: dict[tuple[str, str], list[tuple[str, dict[str, Any]]]],
                   pins: dict[str, dict[str, Any] | None],
                   prior: dict[str, Any] | None, probes: dict[str, dict[str, Any]],
                   managers: dict[str, str], generated_at: str, producer_revision: str) -> dict[str, Any]:
    """`pins` maps repository@digest of a receipt image to its inputs or None
    (see choose_receipt)."""
    records = built_targets(matrix, destination)
    coverage = sha256(canonical(records))
    namespace = destination.partition("/")[2]
    prior_by_key = {e.get("targetKey"): e for e in (prior or {}).get("targets") or []}
    digests = {key: (obs or {}).get("platformManifestDigest") if (obs or {}).get("available") else None
               for key, obs in observed.items()}
    entries = []
    for record in records:
        target = record["target"]
        key = target_key(target)
        pub = record["publication"]
        obs = observed.get(key)
        available = bool(obs and obs.get("available"))
        digest = digests.get(key)
        qualification, bound, pin = qualify(
            target, digest, receipts.get((target["variant"], target["flavor"]), []),
            prior_by_key.get(key), under(pins, pub["repository"]))
        # A pinned target builds its receipt image; facts keep describing the tag.
        source = pin or (obs if available else None)
        entries.append({
            "availability": {"available": available, "ociPlatform": oci_platform(target["platform"])},
            "facts": build_facts(target, obs, probes, namespace, managers.get(target["variant"], "")),
            "publication": {"ref": f"{pub['repository']}:{pub['tag']}", **pub},
            "qualification": qualification,
            "required": record["required"],
            "resolvedInputs": {
                "configDigest": source.get("configDigest") if source else None,
                "engineRevision": bound["engine"] if bound else None,
                "indexDigest": source.get("indexDigest") if source else None,
                "installerRevision": bound["installer"] if bound else None,
                "liveOverlayBaseDigest": bound["source"] if bound else None,
                "liveOverlayDigest": bound["overlay"] if bound else None,
                "platformManifestDigest": source["platformManifestDigest"] if source else None,
            },
            "scheduled": record["scheduled"],
            "target": target,
            "targetKey": key,
        })
    return {
        "coverageDigest": coverage,
        "generatedAt": generated_at,
        "kind": "catalog-snapshot",
        "producerRevision": producer_revision,
        "schemaVersion": 1,
        "snapshotDigest": sha256(canonical(entries)),
        "targets": entries,
    }


def render(snapshot: dict[str, Any]) -> str:
    return json.dumps(snapshot, indent=2, sort_keys=True, ensure_ascii=True) + "\n"


def load_prior(path: Path) -> dict[str, Any]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CatalogError(f"cannot read prior snapshot {path}: {exc}") from exc
    if (not isinstance(doc, dict) or doc.get("schemaVersion") != 1
            or doc.get("kind") != "catalog-snapshot" or not isinstance(doc.get("targets"), list)):
        raise CatalogError(f"{path} is not a CatalogSnapshot v1 document")
    return doc


def load_probes(path: Path | None) -> dict[str, dict[str, Any]]:
    if path is None:
        return {}
    try:
        images = json.loads(path.read_text(encoding="utf-8"))["images"]
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise CatalogError(f"cannot read catalog facts {path}: {exc}") from exc
    if not isinstance(images, dict):
        raise CatalogError(f"{path}: images must be an object")
    return images


def producer_revision_default() -> str:
    head = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"],
                          capture_output=True, text=True, check=False).stdout.strip()
    if len(head) != 40:
        raise CatalogError("cannot read the tunaOS commit; pass --producer-revision")
    return f"tunaos.toml@{head}"


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", type=Path, default=ROOT / "tunaos.toml")
    parser.add_argument("--offline", action="store_true",
                        help="keep the --prior snapshot's availability, digests and facts; read no registry")
    parser.add_argument("--prior", type=Path,
                        help="previous catalog-snapshot.json (required with --offline)")
    parser.add_argument("--facts", type=Path, help="catalog-facts.json from catalog-facts.yml")
    parser.add_argument("--receipts-dir", type=Path, default=qualification_receipt.RECEIPTS_DIR)
    parser.add_argument("--generated-at", help="YYYY-MM-DDTHH:MM:SSZ (default: now; offline: the prior's)")
    parser.add_argument("--producer-revision", help="default: tunaos.toml@<HEAD commit>")
    parser.add_argument("--output", type=Path, help="write here instead of stdout")
    parser.add_argument("--jobs", type=int, default=8)
    parser.add_argument("--skopeo", default="skopeo")
    args = parser.parse_args(argv)
    if args.offline and args.prior is None:
        parser.error("--offline needs --prior")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        config = tunaos_config.load(args.config)
        matrix = tunaos_config.matrix(config)
        destination = publish_destination()
        prior = load_prior(args.prior) if args.prior else None
        prior_by_key = {e.get("targetKey"): e for e in (prior or {}).get("targets") or []}
        records = built_targets(matrix, destination)
        receipts = committed_receipts(args.receipts_dir)
        fetch = skopeo_fetch(args.skopeo)
        if args.offline:
            live: dict[str, Any] = {}
        else:
            live = observe_registry(records, fetch, max(1, args.jobs))
        observed: dict[str, dict[str, Any] | None] = {}
        undetermined = []
        for record in records:
            key = target_key(record["target"])
            pub = record["publication"]
            result = live.get(key) if not args.offline else Inconclusive("offline")
            if isinstance(result, Inconclusive):
                kept = prior_observation(prior_by_key.get(key), f"{pub['repository']}:{pub['tag']}")
                if kept is None:
                    undetermined.append(f"{key}: {result}")
                observed[key] = kept
            else:
                observed[key] = None if result is None else {"available": True, **result}
        wanted = receipt_images(records, receipts, observed)
        live_pins = {} if args.offline else observe_receipt_images(wanted, fetch, max(1, args.jobs))
        kept_pins = prior_pins(prior)
        pins: dict[str, dict[str, Any] | None] = {}
        unresolved = []
        for ref, _ in wanted:
            found = live_pins.get(ref) if not args.offline else Inconclusive("offline")
            if isinstance(found, Inconclusive):
                if ref in kept_pins:
                    pins[ref] = kept_pins[ref]
                else:
                    unresolved.append(f"{ref}: {found}")
            elif found is None:
                pins[ref] = None
            else:
                # A by-digest read sees no index; keep the one a prior snapshot
                # resolved this image through, if any.
                pins[ref] = {"configDigest": found["configDigest"],
                             "indexDigest": (kept_pins.get(ref) or {}).get("indexDigest"),
                             "platformManifestDigest": found["platformManifestDigest"]}
        generated_at = args.generated_at or (
            prior["generatedAt"] if args.offline and prior
            else datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
        snapshot = build_snapshot(
            matrix, destination=destination, observed=observed,
            receipts=receipts, pins=pins, prior=prior,
            probes=load_probes(args.facts), generated_at=generated_at,
            managers=tunaos_config.variant_managers(config, list(config["variants"])),
            producer_revision=args.producer_revision or producer_revision_default())
    except (CatalogError, tunaos_config.ConfigError) as exc:
        print(f"generate-catalog-snapshot: {exc}", file=sys.stderr)
        return 1
    body = render(snapshot)
    if args.output:
        args.output.write_text(body, encoding="utf-8")
    else:
        sys.stdout.write(body)
    counts = {status: 0 for status in STATUSES}
    for entry in snapshot["targets"]:
        counts[entry["qualification"]["status"]] += 1
    available = sum(entry["availability"]["available"] for entry in snapshot["targets"])
    print(f"{len(snapshot['targets'])} targets, {available} available: "
          + ", ".join(f"{n} {s}" for s, n in counts.items()), file=sys.stderr)
    for line in undetermined:
        print(f"availability undetermined: {line}", file=sys.stderr)
    for line in unresolved:
        print(f"receipt image undetermined: {line}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
