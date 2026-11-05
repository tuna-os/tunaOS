"""scripts/generate-catalog-snapshot.py: the ISO builder's CatalogSnapshot v1.

The generator must cover every built target in tunaos.toml exactly once, give
the same bytes for the same inputs, select the exact OCI platform from an
index, and admit `qualified` only from a committed receipt whose image the
registry still holds. A linux/amd64 target builds that receipt image after
its tag moves on; its linux/arm64 twin qualifies only while the tag still
publishes it.
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


def pin_of(image: str, config: str = digest("8"), index: str | None = None) -> dict:
    return {"configDigest": config, "indexDigest": index, "platformManifestDigest": image}


def snapshot(tmp_path: Path, amd64_digest: str, pins: dict | None = None,
             siblings: dict | None = None) -> dict[str, dict]:
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
                             receipts=GEN.committed_receipts(receipts_dir(tmp_path)), pins=pins or {},
                             siblings=siblings or {}, prior=None, probes={}, managers={"fish": "zypper"},
                             generated_at=STAMP, producer_revision=REVISION)
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


def test_moved_tag_keeps_amd64_on_its_receipt_image_and_arm64_on_its_index_twin(tmp_path):
    image = RECEIPT["target"]["imageDigest"]
    index_ref = f"ghcr.io/tuna-os/fish@{digest('5')}"
    by_key = snapshot(tmp_path, digest("7"),
                      {f"ghcr.io/tuna-os/fish@{image}": pin_of(image, index=digest("5"))},
                      {"linux/arm64": {index_ref: pin_of(digest("6"), digest("4"), digest("5"))}})
    amd64 = by_key["fish:kde:linux/amd64"]
    q = amd64["qualification"]
    assert (q["status"], q["receiptDigest"], q["receiptImageDigest"]) == ("qualified", RECEIPT_DIGEST, image)
    # The build pins the bytes the receipt proved; facts keep describing the tag.
    assert amd64["resolvedInputs"] == {
        "configDigest": digest("8"), "indexDigest": digest("5"), "platformManifestDigest": image,
        "liveOverlayBaseDigest": image, "liveOverlayDigest": RECEIPT["inputs"]["overlay"],
        "installerRevision": RECEIPT["inputs"]["installer"], "engineRevision": RECEIPT["inputs"]["engine"]}
    assert amd64["facts"]["digest"] == digest("7") and amd64["availability"]["available"] is True
    # The receipt names no arm64 image: the twin builds the arm64 image of the
    # index that published the receipt image, not the moved tag's.
    twin = by_key["fish:kde:linux/arm64"]
    assert twin["qualification"] == q
    assert twin["resolvedInputs"] == {
        "configDigest": digest("4"), "indexDigest": digest("5"), "platformManifestDigest": digest("6"),
        "liveOverlayBaseDigest": None, "liveOverlayDigest": None,
        "installerRevision": None, "engineRevision": None}
    assert twin["facts"]["digest"] == digest("c")


@pytest.mark.parametrize("index,siblings,reason", [
    (None, {}, "stale-qualification-receipt-index-unknown"),
    (digest("5"), {f"ghcr.io/tuna-os/fish@{digest('5')}": None}, "stale-qualification-receipt-index-unavailable"),
    (digest("5"), {}, "qualification-receipt-image-undetermined"),
])
def test_arm64_twin_without_its_receipt_index_lapses(tmp_path, index, siblings, reason):
    image = RECEIPT["target"]["imageDigest"]
    by_key = snapshot(tmp_path, digest("7"), {f"ghcr.io/tuna-os/fish@{image}": pin_of(image, index=index)},
                      {"linux/arm64": siblings})
    assert by_key["fish:kde:linux/amd64"]["qualification"]["status"] == "qualified"
    twin = by_key["fish:kde:linux/arm64"]
    q = twin["qualification"]
    assert (q["status"], q["reason"], q["receiptDigest"]) == ("unqualified", reason, RECEIPT_DIGEST)
    assert twin["resolvedInputs"]["platformManifestDigest"] == digest("c")


def test_receipt_image_gone_from_the_registry_is_stale_on_both_platforms(tmp_path):
    image = RECEIPT["target"]["imageDigest"]
    by_key = snapshot(tmp_path, digest("7"), {f"ghcr.io/tuna-os/fish@{image}": None})
    for key in ("fish:kde:linux/amd64", "fish:kde:linux/arm64"):
        q = by_key[key]["qualification"]
        assert (q["status"], q["reason"], q["receiptDigest"]) == (
            "unqualified", "stale-qualification-receipt", RECEIPT_DIGEST)
        assert by_key[key]["resolvedInputs"]["liveOverlayDigest"] is None
    assert by_key["fish:kde:linux/amd64"]["resolvedInputs"]["platformManifestDigest"] == digest("7")


def test_undetermined_receipt_image_is_neither_qualified_nor_stale(tmp_path):
    by_key = snapshot(tmp_path, digest("7"))
    q = by_key["fish:kde:linux/amd64"]["qualification"]
    assert (q["status"], q["reason"], q["receiptDigest"]) == (
        "unqualified", "qualification-receipt-image-undetermined", RECEIPT_DIGEST)
    assert by_key["fish:kde:linux/amd64"]["resolvedInputs"]["platformManifestDigest"] == digest("7")


def test_a_receipt_for_the_current_image_wins_over_a_newer_pinned_one():
    target = {"variant": "fish", "flavor": "kde", "platform": "linux/amd64", "hardwareScope": "generic"}
    older = json.loads(json.dumps(RECEIPT))
    newer = json.loads(json.dumps(RECEIPT))
    newer["qualifiedAt"] = "2026-11-05T09:30:00Z"
    newer["target"]["imageDigest"] = newer["inputs"]["source"] = digest("2")
    receipts = [("sha256:" + "b" * 64, newer), ("sha256:" + "a" * 64, older)]
    current = older["target"]["imageDigest"]
    q, bound, pin = GEN.qualify(target, current, current, receipts, None, {digest("2"): pin_of(digest("2"))}, {})
    assert (q["receiptDigest"], bound["source"], pin) == ("sha256:" + "a" * 64, current, None)
    q, bound, pin = GEN.qualify(target, digest("7"), digest("7"), receipts, None,
                                {digest("2"): pin_of(digest("2")), current: pin_of(current)}, {})
    assert (q["receiptDigest"], bound["source"], pin["platformManifestDigest"]) == (
        "sha256:" + "b" * 64, digest("2"), digest("2"))


def test_no_receipt_and_no_descriptor_stay_unqualified():
    q, bound, pin = GEN.qualify({"variant": "fish", "flavor": "kde", "platform": "linux/amd64",
                                 "hardwareScope": "generic"}, digest("1"), digest("1"), [], None, {}, {})
    assert (q["status"], q["reason"], bound, pin) == ("unqualified", "no-qualification-receipt", None, None)
    q, _, _ = GEN.qualify({"variant": "fish", "flavor": "kde", "platform": "linux/amd64",
                           "hardwareScope": "generic"}, None, None, [], None, {}, {})
    assert q["reason"] == "missing-platform-descriptor"


def test_local_only_finding_lapses_with_the_bytes_it_measured():
    target = {"variant": "fish", "flavor": "kde", "platform": "linux/amd64", "hardwareScope": "generic"}
    prior = {"qualification": {"status": "local-only", "reason": "exceeds-wasm32-memory-ceiling"},
             "resolvedInputs": {"platformManifestDigest": digest("1")}}
    assert GEN.qualify(target, digest("1"), digest("1"), [], prior, {}, {})[0]["status"] == "local-only"
    assert GEN.qualify(target, digest("2"), digest("2"), [], prior, {}, {})[0]["status"] == "unqualified"


def test_receipt_images_are_read_by_digest_as_one_platform_manifest():
    amd64 = json.dumps({"schemaVersion": 2, "config": {"digest": digest("8")}, "layers": []}).encode()
    arm64 = json.dumps({"schemaVersion": 2, "config": {"digest": digest("6")}, "layers": [{}]}).encode()
    index = json.dumps({"mediaType": "application/vnd.oci.image.index.v1+json", "manifests": [
        {"digest": GEN.sha256(amd64), "platform": {"os": "linux", "architecture": "amd64"}}]}).encode()
    blobs = {GEN.sha256(raw): raw for raw in (amd64, arm64, index)}
    arches = {GEN.sha256(amd64): "amd64", GEN.sha256(arm64): "arm64"}

    def fetch(ref: str, config: bool) -> bytes | None:
        image = ref.rsplit("@", 1)[1]
        if image == digest("5"):
            raise GEN.Inconclusive("timeout")
        if config:
            return json.dumps({"os": "linux", "architecture": arches[image]}).encode()
        return blobs.get(image)

    refs = [f"r/fish@{image}" for image in (GEN.sha256(amd64), GEN.sha256(arm64), GEN.sha256(index),
                                            digest("4"), digest("5"))]
    seen = GEN.observe_receipt_images([(ref, "linux/amd64") for ref in refs], fetch, 2)
    assert (seen[refs[0]]["platformManifestDigest"], seen[refs[0]]["configDigest"]) == (
        GEN.sha256(amd64), digest("8"))
    assert seen[refs[1]] is None and seen[refs[2]] is None and seen[refs[3]] is None
    assert isinstance(seen[refs[4]], GEN.Inconclusive)


def yellowfin_receipt(directory: Path, image: str, qualified_at: str) -> str:
    receipt = json.loads(json.dumps(RECEIPT))
    ref = f"{publish_destination()}/yellowfin:kde"
    receipt["target"].update(variant="yellowfin", flavor="kde", image=ref, imageDigest=image)
    receipt["inputs"]["source"] = image
    receipt["qualifiedAt"] = qualified_at
    for mode in receipt["modes"].values():
        mode.update(source_digest=image, booted_digest=image, target_imgref=ref)
    data = json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode()
    (directory / f"{hashlib.sha256(data).hexdigest()}.json").write_bytes(data)
    return "sha256:" + hashlib.sha256(data).hexdigest()


def test_registry_runs_pin_both_platforms_to_the_receipt_index(tmp_path, monkeypatch):
    def platform_manifest(config: str) -> bytes:
        return json.dumps({"schemaVersion": 2, "config": {"digest": config}, "layers": [{"size": 7}]}).encode()

    def image_index(amd64: bytes, arm64: bytes) -> bytes:
        return json.dumps({"mediaType": "application/vnd.oci.image.index.v1+json", "manifests": [
            {"digest": GEN.sha256(amd64), "platform": {"os": "linux", "architecture": "amd64"}},
            {"digest": GEN.sha256(arm64), "platform": {"os": "linux", "architecture": "arm64", "variant": "v8"}},
        ]}).encode()
    old, old_arm = platform_manifest(digest("1")), platform_manifest(digest("3"))
    new, new_arm = platform_manifest(digest("2")), platform_manifest(digest("4"))
    old_index, new_index = image_index(old, old_arm), image_index(new, new_arm)
    blobs = {GEN.sha256(raw): raw for raw in (old, old_arm, new, new_arm, old_index, new_index)}
    arm64 = {GEN.sha256(old_arm), GEN.sha256(new_arm)}
    tag = {"index": old_index}
    repository = f"{publish_destination()}/yellowfin"

    def fetch(ref: str, config: bool) -> bytes | None:
        if ref == f"{repository}:kde":
            return tag["index"]
        if not ref.startswith(f"{repository}@"):
            return None
        image = ref.rsplit("@", 1)[1]
        if config and image in blobs:
            return json.dumps({"os": "linux", "architecture": "arm64" if image in arm64 else "amd64",
                               "config": {"Labels": {"containers.bootc": "1"}}}).encode()
        return blobs.get(image)

    monkeypatch.setattr(GEN, "skopeo_fetch", lambda _: fetch)
    receipts = tmp_path / "receipts"
    receipts.mkdir()
    evidence = yellowfin_receipt(receipts, GEN.sha256(old), "2026-11-04T09:30:00Z")

    def run(name: str, *extra: str) -> dict[str, dict]:
        out = tmp_path / name
        assert GEN.main(["--receipts-dir", str(receipts), "--generated-at", STAMP,
                         "--producer-revision", REVISION, "--output", str(out), *extra]) == 0
        return {entry["targetKey"]: entry for entry in json.loads(out.read_text())["targets"]}

    day0 = run("day0.json")  # the tag still publishes the receipt image
    assert day0["yellowfin:kde:linux/amd64"]["resolvedInputs"]["indexDigest"] == GEN.sha256(old_index)
    assert day0["yellowfin:kde:linux/arm64"]["qualification"]["status"] == "qualified"

    tag["index"] = new_index  # the daily build moves the tag
    day1 = run("day1.json", "--prior", str(tmp_path / "day0.json"))
    amd64, twin = day1["yellowfin:kde:linux/amd64"], day1["yellowfin:kde:linux/arm64"]
    assert (amd64["qualification"]["status"], amd64["qualification"]["receiptDigest"]) == ("qualified", evidence)
    assert {key: amd64["resolvedInputs"][key] for key in GEN.PIN_KEYS} == {
        "configDigest": digest("1"), "indexDigest": GEN.sha256(old_index),
        "platformManifestDigest": GEN.sha256(old)}
    assert amd64["resolvedInputs"]["liveOverlayBaseDigest"] == GEN.sha256(old)
    assert amd64["facts"]["digest"] == GEN.sha256(new)
    assert twin["qualification"] == amd64["qualification"]
    assert {key: twin["resolvedInputs"][key] for key in GEN.PIN_KEYS} == {
        "configDigest": digest("3"), "indexDigest": GEN.sha256(old_index),
        "platformManifestDigest": GEN.sha256(old_arm)}
    assert twin["facts"]["digest"] == GEN.sha256(new_arm)

    offline = run("offline.json", "--offline", "--prior", str(tmp_path / "day1.json"))
    assert offline["yellowfin:kde:linux/amd64"] == amd64 and offline["yellowfin:kde:linux/arm64"] == twin

    # No snapshot saw the index that published the receipt image.
    blind = run("blind.json")
    assert blind["yellowfin:kde:linux/amd64"]["qualification"]["status"] == "qualified"
    assert blind["yellowfin:kde:linux/amd64"]["resolvedInputs"]["indexDigest"] is None
    assert blind["yellowfin:kde:linux/arm64"]["qualification"]["reason"] == "stale-qualification-receipt-index-unknown"
    assert blind["yellowfin:kde:linux/arm64"]["resolvedInputs"]["platformManifestDigest"] == GEN.sha256(new_arm)

    del blobs[GEN.sha256(old_index)]
    gone_index = run("gone-index.json", "--prior", str(tmp_path / "day0.json"))
    assert gone_index["yellowfin:kde:linux/amd64"]["qualification"]["status"] == "qualified"
    assert (gone_index["yellowfin:kde:linux/arm64"]["qualification"]["reason"]
            == "stale-qualification-receipt-index-unavailable")

    # A receipt image the registry no longer holds makes both targets stale.
    del blobs[GEN.sha256(old)]
    gone = run("gone.json", "--prior", str(tmp_path / "day0.json"))
    for key in ("yellowfin:kde:linux/amd64", "yellowfin:kde:linux/arm64"):
        q = gone[key]["qualification"]
        assert (q["status"], q["reason"], q["receiptDigest"]) == ("unqualified", "stale-qualification-receipt", evidence)
    assert gone["yellowfin:kde:linux/amd64"]["resolvedInputs"]["platformManifestDigest"] == GEN.sha256(new)


def test_an_index_that_did_not_publish_the_receipt_image_has_no_twin():
    amd64, arm64 = manifest(1), manifest(2)
    index = json.dumps({"mediaType": "application/vnd.oci.image.index.v1+json", "manifests": [
        {"digest": GEN.sha256(amd64), "platform": {"os": "linux", "architecture": "amd64"}},
        {"digest": GEN.sha256(arm64), "platform": {"os": "linux", "architecture": "arm64"}}]}).encode()
    blobs = {GEN.sha256(raw): raw for raw in (amd64, arm64, index)}

    def fetch(ref: str, config: bool) -> bytes | None:
        return b"{}" if config else blobs.get(ref.rsplit("@", 1)[1])
    ref = f"r/fish@{GEN.sha256(index)}"
    seen = GEN.observe_siblings([(ref, "linux/arm64", "linux/amd64", GEN.sha256(amd64))], fetch, 1)
    assert seen[(ref, "linux/arm64")]["platformManifestDigest"] == GEN.sha256(arm64)
    assert seen[(ref, "linux/arm64")]["indexDigest"] == GEN.sha256(index)
    other = GEN.observe_siblings([(ref, "linux/arm64", "linux/amd64", digest("9"))], fetch, 1)
    assert other[(ref, "linux/arm64")] is None


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
