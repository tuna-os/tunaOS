"""scripts/generate-catalog-snapshot.py: the ISO builder's CatalogSnapshot v1.

The generator must cover every built target in tunaos.toml exactly once, give
the same bytes for the same inputs, select the exact OCI platform from an
index, and admit `qualified` only from a committed receipt whose image digest
is the target's current one.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import random
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "generate_catalog_snapshot", ROOT / "scripts" / "generate-catalog-snapshot.py")
GEN = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(GEN)
sys.path.insert(0, str(ROOT / "scripts"))
from lib import tunaos_config  # noqa: E402
from lib.publish_destination import publish_destination  # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "browser-iso-qualification-v1" / "receipt.json"
# Committed receipts are the canonical encoding (scripts/lib/qualification_receipt.py).
RECEIPT = json.loads(FIXTURE.read_text())
RECEIPT_BYTES = json.dumps(RECEIPT, sort_keys=True, separators=(",", ":")).encode()
RECEIPT_DIGEST = "sha256:" + hashlib.sha256(RECEIPT_BYTES).hexdigest()
STAMP = "2026-11-05T00:00:00Z"
REVISION = "tunaos.toml@" + "0" * 40


def digest(char: str) -> str:
    return "sha256:" + char * 64


def run_offline(tmp_path: Path, prior: dict, capsys, name: str = "out.json") -> tuple[str, str]:
    prior_path = tmp_path / f"prior-{name}"
    prior_path.write_text(json.dumps(prior))
    out = tmp_path / name
    assert GEN.main(["--offline", "--prior", str(prior_path), "--generated-at", STAMP,
                     "--producer-revision", REVISION, "--output", str(out)]) == 0
    return out.read_text(), capsys.readouterr().err


def empty_prior() -> dict:
    return {"schemaVersion": 1, "kind": "catalog-snapshot", "generatedAt": STAMP, "targets": []}


def test_every_built_target_appears_once_with_its_publication(tmp_path, capsys):
    body, err = run_offline(tmp_path, empty_prior(), capsys)
    doc = json.loads(body)
    destination = publish_destination()
    expected = {}
    for variant in tunaos_config.matrix(tunaos_config.load())["variants"]:
        for flavor in variant["flavors"]:
            if flavor.get("build_image") is not True:
                continue
            for platform in flavor.get("platforms", variant["platforms"]):
                tag = f"{flavor['id']}-{variant['tag_suffix']}" if variant.get("tag_suffix") else flavor["id"]
                name = variant.get("publish_name") or variant["id"]
                expected[f"{variant['id']}:{flavor['id']}:{platform}"] = f"{destination}/{name}:{tag}"
    keys = [entry["targetKey"] for entry in doc["targets"]]
    assert keys == sorted(expected)
    assert {entry["targetKey"]: entry["publication"]["ref"] for entry in doc["targets"]} == expected
    assert all(entry["scheduled"] and entry["required"] for entry in doc["targets"])
    # Offline with no prior knowledge, nothing is claimed available and every
    # target is reported as undetermined.
    assert not any(entry["availability"]["available"] for entry in doc["targets"])
    assert err.count("availability undetermined:") == len(expected)


def test_same_inputs_give_the_same_bytes_and_canonical_digests(tmp_path, capsys):
    destination = publish_destination()
    prior = empty_prior()
    prior["targets"] = [{
        "targetKey": key,
        "publication": {"ref": f"{destination}/{ref}"},
        "availability": {"available": True},
        "resolvedInputs": {"platformManifestDigest": digest(char), "indexDigest": digest("e"),
                           "configDigest": digest("f")},
        "facts": {"digest": digest(char), "desktop": "gnome", "kernelVer": "6.12", "bootc": True,
                  "hasSdBoot": False, "layerCount": 65, "compressedSize": 1, "pkgManager": "dnf",
                  "repoFamily": "fedora"},
        "qualification": {"status": "unqualified"},
    } for key, ref, char in (("yellowfin:gnome:linux/amd64", "yellowfin:gnome", "a"),
                             ("yellowfin:gnome:linux/amd64/v2", "yellowfin:gnome", "b"),
                             ("bonito:kde:linux/arm64", "bonito:kde", "c"))]
    first, _ = run_offline(tmp_path, prior, capsys, "first.json")
    random.Random(7).shuffle(prior["targets"])
    second, _ = run_offline(tmp_path, prior, capsys, "second.json")
    assert first == second
    doc = json.loads(first)
    assert first == json.dumps(doc, indent=2, sort_keys=True) + "\n"
    canonical = json.dumps(doc["targets"], sort_keys=True, separators=(",", ":")).encode()
    assert doc["snapshotDigest"] == "sha256:" + hashlib.sha256(canonical).hexdigest()
    assert (doc["generatedAt"], doc["producerRevision"]) == (STAMP, REVISION)
    by_key = {entry["targetKey"]: entry for entry in doc["targets"]}
    kept = by_key["yellowfin:gnome:linux/amd64"]
    assert kept["availability"]["available"] is True
    assert kept["resolvedInputs"]["platformManifestDigest"] == digest("a")
    assert kept["facts"]["kernelVer"] == "6.12"
    assert by_key["yellowfin:gnome:linux/amd64/v2"]["availability"]["ociPlatform"] == {
        "architecture": "amd64", "os": "linux", "variant": "v2"}
    assert by_key["skipjack:gnome:linux/amd64"]["target"]["cpuBaseline"] == "x86-64-v3"


# ── registry selection ───────────────────────────────────────────────────────


def manifest(layers: int) -> bytes:
    return json.dumps({"schemaVersion": 2, "config": {"digest": digest("9")},
                       "layers": [{"size": 10} for _ in range(layers)]}).encode()


def fake_registry(platform_manifests: dict[str, bytes], index_entries: list[dict]):
    descriptors = [{"digest": GEN.sha256(raw), "platform": platform}
                   for platform, raw in zip(index_entries, platform_manifests.values())]
    index = json.dumps({"mediaType": "application/vnd.oci.image.index.v1+json",
                        "manifests": descriptors + [{"digest": digest("0"),
                                                     "platform": {"os": "unknown", "architecture": "unknown"}}]}).encode()
    by_digest = {GEN.sha256(raw): raw for raw in platform_manifests.values()}

    def fetch(ref: str, config: bool) -> bytes | None:
        if "@" not in ref:
            return index if ref.endswith(":kde") else None
        found = by_digest.get(ref.rsplit("@", 1)[1])
        if found is None:
            return None
        if config:
            return json.dumps({"config": {"Labels": {"containers.bootc": "1"}}}).encode()
        return found
    return fetch, index


def test_index_selection_never_confuses_amd64_with_its_v2_build():
    manifests = {"amd64": manifest(3), "v2": manifest(4), "arm64": manifest(5)}
    fetch, index = fake_registry(manifests, [
        {"os": "linux", "architecture": "amd64"},
        {"os": "linux", "architecture": "amd64/v2"},  # podman's manifest-list spelling
        {"os": "linux", "architecture": "arm64", "variant": "v8"},
    ])
    plain = GEN.resolve(fetch, "r/fish", index, "linux/amd64")
    v2 = GEN.resolve(fetch, "r/fish", index, "linux/amd64/v2")
    arm = GEN.resolve(fetch, "r/fish", index, "linux/arm64")
    assert (plain["layerCount"], v2["layerCount"], arm["layerCount"]) == (3, 4, 5)
    assert plain["platformManifestDigest"] != v2["platformManifestDigest"]
    assert plain["indexDigest"] == GEN.sha256(index) and plain["bootc"] is True
    assert plain["compressedSize"] == 30
    assert GEN.resolve(fetch, "r/fish", index, "linux/amd64/v3") is None


def test_registry_absence_and_failures_are_distinguished():
    fetch, _ = fake_registry({"amd64": manifest(1)}, [{"os": "linux", "architecture": "amd64"}])
    records = GEN.built_targets(matrix(), "r")
    observed = GEN.observe_registry(records, fetch, 2)
    assert observed["fish:base:linux/amd64"] is None  # tag absent
    assert observed["fish:kde:linux/amd64"]["layerCount"] == 1
    assert observed["fish:kde:linux/arm64"] is None  # platform absent from the index

    def broken(ref: str, config: bool) -> bytes | None:
        raise GEN.Inconclusive("timeout")
    assert all(isinstance(v, GEN.Inconclusive) for v in GEN.observe_registry(records, broken, 2).values())


# ── receipts and qualification ───────────────────────────────────────────────


def matrix() -> dict:
    return {"variants": [{
        "id": "fish", "platforms": ["linux/amd64"],
        "flavors": [
            {"id": "base", "build_image": True},
            {"id": "kde", "build_image": True, "platforms": ["linux/amd64", "linux/amd64/v2", "linux/arm64"]},
            {"id": "gnome-asahi", "build_image": True, "platforms": ["linux/arm64"]},
            {"id": "xfce", "build_image": False},
        ]}]}


def receipts_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "receipts"
    directory.mkdir()
    data = RECEIPT_BYTES
    (directory / f"{hashlib.sha256(data).hexdigest()}.json").write_bytes(data)
    return directory


def snapshot(tmp_path: Path, amd64_digest: str) -> dict[str, dict]:
    def seen(char: str) -> dict:
        return {"available": True, "indexDigest": digest("e"), "platformManifestDigest": char,
                "configDigest": digest("f"), "layerCount": 1, "compressedSize": 1, "bootc": True}
    observed = {
        "fish:base:linux/amd64": seen(digest("a")),
        "fish:kde:linux/amd64": seen(amd64_digest),
        "fish:kde:linux/amd64/v2": seen(digest("b")),
        "fish:kde:linux/arm64": seen(digest("c")),
        "fish:gnome-asahi:linux/arm64": seen(digest("d")),
    }
    doc = GEN.build_snapshot(matrix(), destination="ghcr.io/tuna-os", observed=observed,
                             receipts=GEN.committed_receipts(receipts_dir(tmp_path)), prior=None,
                             probes={}, managers={"fish": "zypper"}, generated_at=STAMP,
                             producer_revision=REVISION)
    return {entry["targetKey"]: entry for entry in doc["targets"]}


def test_matching_receipt_qualifies_amd64_and_its_arm64_twin_only(tmp_path):
    receipt = RECEIPT
    receipt_digest = RECEIPT_DIGEST
    by_key = snapshot(tmp_path, receipt["target"]["imageDigest"])
    assert set(by_key) == {"fish:base:linux/amd64", "fish:kde:linux/amd64", "fish:kde:linux/amd64/v2",
                           "fish:kde:linux/arm64", "fish:gnome-asahi:linux/arm64"}
    amd64 = by_key["fish:kde:linux/amd64"]
    q = amd64["qualification"]
    assert q["status"] == "qualified" and q["receiptDigest"] == receipt_digest
    assert q["isoDigest"] == receipt["iso"]["sha256"] and q["qualifiedAt"] == receipt["qualifiedAt"]
    assert q["receiptSchema"] == "BrowserIsoQualificationReceipt/v1" and q["buildOrigin"] == "browser"
    assert q["producer"] == {key: receipt["producer"][key] for key in
                             ("repository", "workflow", "ref", "sha", "runId", "runAttempt")}
    # The receipt has no browser profile; the generator invents none.
    assert q["browser"] is None and q["browserBuildReceiptDigest"] is None and q["resources"] is None
    assert amd64["resolvedInputs"] == {
        "configDigest": digest("f"), "indexDigest": digest("e"),
        "platformManifestDigest": receipt["target"]["imageDigest"],
        "liveOverlayBaseDigest": receipt["inputs"]["source"], "liveOverlayDigest": receipt["inputs"]["overlay"],
        "installerRevision": receipt["inputs"]["installer"], "engineRevision": receipt["inputs"]["engine"]}
    twin = by_key["fish:kde:linux/arm64"]
    assert twin["qualification"] == q
    assert twin["resolvedInputs"]["liveOverlayDigest"] is None
    assert by_key["fish:kde:linux/amd64/v2"]["qualification"]["reason"] == "platform-has-no-receipt-basis"
    assert by_key["fish:base:linux/amd64"]["qualification"]["status"] == "unsupported"
    assert by_key["fish:gnome-asahi:linux/arm64"]["qualification"]["status"] == "unsupported"


def test_receipt_for_an_older_image_is_stale_on_both_platforms(tmp_path):
    receipt_digest = RECEIPT_DIGEST
    by_key = snapshot(tmp_path, digest("7"))
    for key in ("fish:kde:linux/amd64", "fish:kde:linux/arm64"):
        q = by_key[key]["qualification"]
        assert (q["status"], q["reason"], q["receiptDigest"]) == (
            "unqualified", "stale-qualification-receipt", receipt_digest)
        assert by_key[key]["resolvedInputs"]["liveOverlayDigest"] is None


def test_no_receipt_and_no_descriptor_stay_unqualified():
    q, bound = GEN.qualify({"variant": "fish", "flavor": "kde", "platform": "linux/amd64",
                            "hardwareScope": "generic"}, digest("1"), digest("1"), [], None)
    assert (q["status"], q["reason"], bound) == ("unqualified", "no-qualification-receipt", None)
    q, _ = GEN.qualify({"variant": "fish", "flavor": "kde", "platform": "linux/amd64",
                        "hardwareScope": "generic"}, None, None, [], None)
    assert q["reason"] == "missing-platform-descriptor"


def test_local_only_finding_lapses_with_the_bytes_it_measured():
    target = {"variant": "fish", "flavor": "kde", "platform": "linux/amd64", "hardwareScope": "generic"}
    prior = {"qualification": {"status": "local-only", "reason": "exceeds-wasm32-memory-ceiling"},
             "resolvedInputs": {"platformManifestDigest": digest("1")}}
    assert GEN.qualify(target, digest("1"), digest("1"), [], prior)[0]["status"] == "local-only"
    assert GEN.qualify(target, digest("2"), digest("2"), [], prior)[0]["status"] == "unqualified"


def test_probe_facts_bind_to_the_amd64_index_they_were_read_from():
    target = {"variant": "fish", "flavor": "kde", "platform": "linux/amd64"}
    seen = {"available": True, "indexDigest": digest("e"), "platformManifestDigest": digest("1"),
            "layerCount": 1, "compressedSize": 1, "bootc": True}
    probe = {"tuna-os/fish:kde": {"digest": digest("e"), "kernelVer": "6.12", "desktop": "kde",
                                  "hasSdBoot": True, "pkgManager": "", "repoFamily": ""}}
    facts = GEN.build_facts(target, seen, probe, "tuna-os", "emerge")
    assert (facts["kernelVer"], facts["hasSdBoot"]) == ("6.12", True)
    # The build route, not the probe, names the package manager.
    assert (facts["pkgManager"], facts["repoFamily"]) == ("emerge", "gentoo")
    moved = dict(seen, indexDigest=digest("d"))
    assert GEN.build_facts(target, moved, probe, "tuna-os", "emerge")["kernelVer"] == ""
    arm = GEN.build_facts(dict(target, platform="linux/arm64"), seen, probe, "tuna-os", "emerge")
    assert (arm["hasSdBoot"], arm["pkgManager"]) == (False, "emerge")


@pytest.mark.parametrize("bad", ["not json", json.dumps({"schema": "nope"})])
def test_an_invalid_committed_receipt_stops_generation(tmp_path, bad):
    directory = tmp_path / "receipts"
    directory.mkdir()
    data = bad.encode()
    (directory / f"{hashlib.sha256(data).hexdigest()}.json").write_bytes(data)
    with pytest.raises(GEN.CatalogError):
        GEN.committed_receipts(directory)


@pytest.mark.parametrize("stderr,expected", [
    ("reading manifest x in ghcr.io/tuna-os/fish: manifest unknown", None),
    ("Requesting bearer token: received unexpected HTTP status: 403 Forbidden", GEN.Inconclusive),
    ("pinging container registry ghcr.io: dial tcp: lookup ghcr.io: i/o timeout", GEN.Inconclusive),
])
def test_skopeo_failures_are_absent_only_for_a_missing_manifest(tmp_path, stderr, expected):
    fake = tmp_path / "skopeo"
    fake.write_text(f"#!/bin/sh\necho 'level=fatal msg=\"{stderr}\"' >&2\nexit 1\n")
    fake.chmod(0o755)
    fetch = GEN.skopeo_fetch(str(fake))
    if expected is None:
        assert fetch("ghcr.io/tuna-os/fish:x", False) is None
    else:
        with pytest.raises(expected):
            fetch("ghcr.io/tuna-os/fish:x", False)
