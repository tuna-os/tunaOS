"""Per-target delivery cutover gate for R2 ISO uploads and retention pruning.

`.github/delivery-cutover.json` records which {variant, flavor, platform}
targets have qualified for delivery cutover and which R2 objects must survive
pruning afterwards. These tests pin the gate's behavior, not its wiring:

- empty policy == today's behavior (uploads proceed, prune deletes as today);
- a target is cut over only with a digest-bound evidence entry that is still
  a member of the current catalog (plus snapshot staleness when supplied);
- group closure needs every LIVE + OFFLINE member target cut over;
- retained_inventory() ordering/dedup, annotate-matrix defaults;
- retained dated ISOs + sidecars survive the ordered prune-filter replay
  while non-retained dated objects still delete.

No workflow runs, no R2 operations: everything here reads the policy and
build-config data files and replays filter semantics in-process (plus one
`--retained` subprocess whose output format the prune workflow depends on).
"""

from __future__ import annotations

import fnmatch
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "delivery-cutover.py"
POLICY_FILE = ROOT / ".github" / "delivery-cutover.json"
PRUNE_WF = ROOT / ".github" / "workflows" / "prune-r2.yml"


def _load_delivery_cutover():
    spec = importlib.util.spec_from_file_location(
        "delivery_cutover", ROOT / "scripts" / "delivery-cutover.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


DC = _load_delivery_cutover()

DIGEST = "sha256:" + "ab" * 32
OTHER_DIGEST = "sha256:" + "cd" * 32


def make_entry(variant, flavor, platform, digest=DIGEST,
               qualified_at="2026-10-01T00:00:00Z"):
    """One well-formed cutover entry for a target."""
    return {
        "target": {"variant": variant, "flavor": flavor, "platform": platform},
        "evidence": {"receiptDigest": digest, "qualifiedAt": qualified_at},
        "preset": "test-preset",
    }


def make_policy(entries, retained=None):
    return {
        "schemaVersion": 1,
        "kind": "delivery-cutover",
        "cutover": list(entries),
        "retained": list(retained or []),
    }


@pytest.fixture(scope="module")
def config():
    return DC.load_config()


def full_group_entries(config, variant, suffix):
    """Every member x platform target of a group, in gate order."""
    live, offline = DC.group_members(config, variant, suffix)
    entries = []
    for flavor in dict.fromkeys(live + offline):
        for platform in DC.required_platforms_for(config, variant, flavor):
            entries.append(make_entry(variant, flavor, platform))
    return entries


# The empty initial policy is today's behavior.
def test_initial_policy_is_empty():
    policy = json.loads(POLICY_FILE.read_text(encoding="utf-8"))
    assert policy["cutover"] == []
    assert policy["retained"] == []


def test_empty_policy_cuts_over_nothing(config):
    """With no entries every gate evaluates to current behavior."""
    policy = make_policy([])
    assert DC.is_cut_over(policy, "bonito", "gnome", "linux/amd64", config=config) is False
    assert DC.is_cut_over(policy, "yellowfin", "kde-nvidia", "linux/amd64", config=config) is False
    live, offline = DC.group_members(config, "yellowfin", "kde")
    assert (live, offline) != ([], [])
    assert DC.group_covered(policy, "yellowfin", "kde", live, offline, config=config) is False
    assert DC.retained_inventory(policy) == []
    matrix = {"include": [
        {"variant": "bonito", "flavor": "gnome", "platform": "linux/amd64"},
        {"variant": "yellowfin", "flavor": "kde-nvidia", "platform": "linux/amd64"},
    ]}
    annotated = DC.annotate_matrix(matrix, policy, config)
    assert [row["cutover"] for row in annotated["include"]] == [False, False]


# is_cut_over: present + bound + catalog member.
@pytest.mark.parametrize(
    "variant,flavor,platform",
    [
        ("bonito", "gnome", "linux/amd64"),
        ("bonito", "gnome", "linux/arm64"),
        ("yellowfin", "kde-nvidia", "linux/amd64"),
        # The v2 baseline is its own platform identity, not an amd64 alias.
        ("yellowfin", "kde", "linux/amd64/v2"),
        ("yellowfin", "kde", "linux/arm64"),
    ],
)
def test_is_cut_over_true_matrix(config, variant, flavor, platform):
    policy = make_policy([make_entry(variant, flavor, platform)])
    snapshot = _qualified_snapshot(
        receipt_digest=DIGEST,
        variant=variant,
        flavor=flavor,
        platform=platform,
    )
    assert DC.is_cut_over(
        policy, variant, flavor, platform, config=config, snapshot=snapshot
    ) is True


def test_is_cut_over_needs_a_matching_entry(config):
    """An entry for one target says nothing about its neighbors."""
    policy = make_policy([make_entry("bonito", "gnome", "linux/amd64")])
    assert DC.is_cut_over(policy, "bonito", "gnome", "linux/arm64", config=config) is False
    assert DC.is_cut_over(policy, "bonito", "kde", "linux/amd64", config=config) is False
    assert DC.find_entry(policy, "bonito", "gnome", "linux/arm64") is None


def test_is_cut_over_rejects_unbound_evidence(config):
    """The receipt digest must be well-formed and carry a qualification time."""
    bad_digest = make_policy([
        make_entry("bonito", "gnome", "linux/amd64", digest="not-a-digest")
    ])
    assert DC.is_cut_over(bad_digest, "bonito", "gnome", "linux/amd64", config=config) is False
    missing_time = make_policy([
        make_entry("bonito", "gnome", "linux/amd64", qualified_at="")
    ])
    assert DC.is_cut_over(missing_time, "bonito", "gnome", "linux/amd64", config=config) is False
    missing_evidence = make_policy([
        {"target": {"variant": "bonito", "flavor": "gnome", "platform": "linux/amd64"},
         "preset": "test-preset"}
    ])
    assert DC.is_cut_over(missing_evidence, "bonito", "gnome", "linux/amd64", config=config) is False


def test_is_cut_over_requires_current_catalog_membership(config):
    """A valid identity that the current catalog does not require stays out."""
    key = "bonito:kde-nvidia:linux/arm64"
    assert key not in DC.catalog_target_keys(config)
    policy = make_policy([{
        "target": {"variant": "bonito", "flavor": "kde-nvidia", "platform": "linux/arm64"},
        "evidence": {"receiptDigest": DIGEST, "qualifiedAt": "2026-10-01T00:00:00Z"},
        "preset": "test-preset",
    }])
    # The entry is present and bound; only catalog membership fails.
    assert DC.find_entry(policy, "bonito", "kde-nvidia", "linux/arm64") is not None
    assert DC.is_cut_over(policy, "bonito", "kde-nvidia", "linux/arm64", config=config) is False


# Snapshot staleness.
def _qualified_snapshot(*, receipt_digest, status="qualified",
                        installer="rev-pin-1", engine="rev-pin-1",
                        variant="bonito", flavor="gnome", platform="linux/amd64"):
    """A minimal valid CatalogSnapshot v1 covering one target.

    Hand-built (rather than via catalog_snapshot) so the qualification can be
    qualified: the real builder needs live OCI descriptors to qualify
    anything, which is exactly what unit scope must not require.
    """
    from contracts.targets import _canonical_json, _oci_platform, hardware_scope

    pm_digest = "sha256:" + "01" * 32
    target = {
        "variant": variant,
        "flavor": flavor,
        "platform": platform,
        "cpuBaseline": (
            "x86-64-v2" if platform == "linux/amd64/v2"
            else "x86-64" if platform == "linux/amd64"
            else "armv8-a"
        ),
        "hardwareScope": hardware_scope(flavor),
    }
    if status == "qualified":
        qualification = {
            "status": "qualified",
            "reason": None,
            "qualifiedAt": "2026-10-01T00:00:00Z",
            "receiptDigest": receipt_digest,
            "browser": None,
            "resources": None,
        }
    else:
        qualification = {
            "status": status,
            "reason": "local-only-target" if status == "local-only" else "untested-snapshot",
            "qualifiedAt": "2026-10-01T00:00:00Z",
            "receiptDigest": receipt_digest,
            "browser": None,
            "resources": None,
        }
    entries = [{
        "target": target,
        "targetKey": f"{variant}:{flavor}:{platform}",
        "required": True,
        "scheduled": True,
        "publication": {
            "repository": f"ghcr.io/tuna-os/{variant}",
            "tag": flavor,
            "ref": f"ghcr.io/tuna-os/{variant}:{flavor}",
        },
        "availability": {"available": True, "ociPlatform": _oci_platform(platform)},
        "resolvedInputs": {
            "platformManifestDigest": pm_digest,
            "indexDigest": "sha256:" + "02" * 32,
            "configDigest": None,
            "liveOverlayDigest": None,
            "liveOverlayBaseDigest": None,
            "installerRevision": installer,
            "engineRevision": engine,
        },
        "facts": {
            "digest": pm_digest,
            "desktop": "gnome",
            "kernelVer": "",
            "hasSdBoot": False,
            "pkgManager": "",
            "repoFamily": "",
            "layerCount": 0,
            "compressedSize": 0,
            "bootc": True,
        },
        "qualification": qualification,
    }]
    return {
        "schemaVersion": 1,
        "kind": "catalog-snapshot",
        "producerRevision": "test",
        "generatedAt": "2026-10-01T00:00:00Z",
        "coverageDigest": "sha256:" + "03" * 32,
        "snapshotDigest": "sha256:" + __import__("hashlib").sha256(
            _canonical_json(entries)).hexdigest(),
        "targets": entries,
    }

def _qualified_snapshot_for_entries(entries):
    from contracts.targets import _canonical_json

    if not entries:
        raise ValueError("snapshot needs at least one target")
    targets = []
    for entry in entries:
        target = entry["target"]
        evidence = entry.get("evidence", {})
        targets.append(
            _qualified_snapshot(
                receipt_digest=evidence.get("receiptDigest", DIGEST),
                variant=target["variant"],
                flavor=target["flavor"],
                platform=target["platform"],
            )["targets"][0]
        )
    targets.sort(key=lambda item: item["targetKey"])
    snapshot = _qualified_snapshot(
        receipt_digest=DIGEST,
        variant=targets[0]["target"]["variant"],
        flavor=targets[0]["target"]["flavor"],
        platform=targets[0]["target"]["platform"],
    )
    snapshot["targets"] = targets
    snapshot["snapshotDigest"] = "sha256:" + __import__("hashlib").sha256(
        _canonical_json(targets)
    ).hexdigest()
    return snapshot


def test_snapshot_with_matching_digest_stays_cut_over(config):
    policy = make_policy([make_entry("bonito", "gnome", "linux/amd64")])
    snapshot = _qualified_snapshot(receipt_digest=DIGEST)
    assert DC.is_cut_over(
        policy, "bonito", "gnome", "linux/amd64", config=config, snapshot=snapshot
    ) is True


def test_snapshot_with_moved_receipt_digest_downgrades(config):
    """The snapshot's digest winning over the policy entry is the staleness
    signal: qualification moved on, the old entry must not gate on it."""
    policy = make_policy([make_entry("bonito", "gnome", "linux/amd64")])
    snapshot = _qualified_snapshot(receipt_digest=OTHER_DIGEST)
    assert DC.is_cut_over(
        policy, "bonito", "gnome", "linux/amd64", config=config, snapshot=snapshot
    ) is False


def test_untested_snapshot_cuts_over_nothing(config):
    """A fresh catalog snapshot with no receipts qualifies nothing, so even a
    present + bound + catalog-member entry is not cut over under it."""
    from contracts.targets import catalog_snapshot

    policy = make_policy([make_entry("bonito", "gnome", "linux/amd64")])
    snapshot = catalog_snapshot(config)
    assert DC.is_cut_over(
        policy, "bonito", "gnome", "linux/amd64", config=config, snapshot=snapshot
    ) is False


def test_moved_pins_downgrade_a_qualified_snapshot(config):
    """downgrade_stale_targets is the mechanism the snapshot path relies on:
    inputs that moved since qualification rewrite the entry to unqualified,
    and the gate then reports not cut over."""
    from contracts.targets import downgrade_stale_targets

    policy = make_policy([make_entry("bonito", "gnome", "linux/amd64")])
    snapshot = _qualified_snapshot(receipt_digest=DIGEST)
    downgraded = downgrade_stale_targets(
        snapshot, current_pins={"installerRevision": "rev-pin-2", "engineRevision": "rev-pin-1"}
    )
    entry = next(
        e for e in downgraded["targets"] if e["targetKey"] == "bonito:gnome:linux/amd64"
    )
    assert entry["qualification"]["status"] == "unqualified"
    assert entry["qualification"]["reason"] == "stale-qualification-receipt"
    assert DC.is_cut_over(
        policy, "bonito", "gnome", "linux/amd64", config=config, snapshot=downgraded
    ) is False
    # Control: unchanged pins leave the qualification (and the gate) intact.
    steady = downgrade_stale_targets(
        snapshot, current_pins={"installerRevision": "rev-pin-1", "engineRevision": "rev-pin-1"}
    )
    steady_entry = next(
        e for e in steady["targets"] if e["targetKey"] == "bonito:gnome:linux/amd64"
    )
    assert steady_entry["qualification"]["status"] == "qualified"
    assert DC.is_cut_over(
        policy, "bonito", "gnome", "linux/amd64", config=config, snapshot=steady
    ) is True


# Group closure: every LIVE + OFFLINE member target.
def test_group_members_resolve_live_and_offline(config):
    live, offline = DC.group_members(config, "yellowfin", "kde")
    assert live == ["kde-nvidia"]
    assert offline == ["kde", "kde-hwe", "kde-nvidia"]


def test_group_members_intersect_with_variant_flavors(config):
    """bonito has no kde-hwe, so its kde group shrinks instead of failing."""
    live, offline = DC.group_members(config, "bonito", "kde")
    assert live == ["kde-nvidia"]
    assert "kde-hwe" not in offline


def test_group_aliases_resolve_the_flagship_suffix(config):
    assert DC.group_members(config, "bonito", "") == DC.group_members(config, "bonito", "default")
    assert DC.group_members(config, "bonito", "") == DC.group_members(config, "bonito", "flagship")


def test_group_members_rejects_unknown_group(config):
    with pytest.raises(ValueError):
        DC.group_members(config, "bonito", "no-such-desktop")


def test_group_covered_needs_every_member_target(config):
    entries = full_group_entries(config, "yellowfin", "kde")
    policy = make_policy(entries)
    live, offline = DC.group_members(config, "yellowfin", "kde")
    snapshot = _qualified_snapshot_for_entries(entries)
    assert DC.group_covered(
        policy, "yellowfin", "kde", live, offline,
        config=config, snapshot=snapshot,
    ) is True


def test_group_covered_false_on_empty_members(config):
    assert DC.group_covered(make_policy([]), "yellowfin", "kde", [], [], config=config) is False


@pytest.mark.parametrize("drop", [0, 2, 4])
def test_group_covered_partial_closure_is_not_covered(config, drop):
    """One missing member target anywhere in the member x platform matrix
    keeps the group publishing; first-match order is irrelevant here, only
    completeness counts."""
    entries = full_group_entries(config, "yellowfin", "kde")
    assert len(entries) == 5
    del entries[drop]
    policy = make_policy(entries)
    live, offline = DC.group_members(config, "yellowfin", "kde")
    assert DC.group_covered(policy, "yellowfin", "kde", live, offline, config=config) is False


def test_group_covered_counts_offline_members(config):
    """Covering only the live (boot) flavors is not closure: the offline
    store members ride the same ISO and must qualify too."""
    live, offline = DC.group_members(config, "yellowfin", "kde")
    assert offline != live
    live_only = [
        make_entry("yellowfin", flavor, platform)
        for flavor in live
        for platform in DC.required_platforms_for(config, "yellowfin", flavor)
    ]
    assert live_only
    policy = make_policy(live_only)
    assert DC.group_covered(policy, "yellowfin", "kde", live, offline, config=config) is False


# retained_inventory: ordering and dedup.
def test_retained_inventory_sorts_and_dedups():
    policy = make_policy([], retained=[
        "bonito-gnome-20260914.iso.sigstore.json",
        "bonito-gnome-20260914.iso",
        "bonito-gnome-20260914.iso",
        "bonito-gnome-20260914.iso.sha256",
    ])
    assert DC.retained_inventory(policy) == [
        "bonito-gnome-20260914.iso",
        "bonito-gnome-20260914.iso.sha256",
        "bonito-gnome-20260914.iso.sigstore.json",
    ]


def test_retained_inventory_drops_non_basenames():
    policy = {"cutover": [], "retained": ["a.iso", "live-isos/a.iso", "", None, 123, "b.iso"]}
    assert DC.retained_inventory(policy) == ["a.iso", "b.iso"]


def test_retained_cli_emits_exclude_rules(tmp_path):
    """The prune workflow splices these lines into `--filter` flags, so the
    `- <name>` shape is a contract, not formatting."""
    policy_path = tmp_path / "policy.json"
    policy_path.write_text(json.dumps(make_policy([], retained=["b.iso", "a.iso"])), encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--retained", "--policy", str(policy_path)],
        capture_output=True, text=True, check=False,
    )
    assert proc.returncode == 0
    assert proc.stdout.splitlines() == ["- a.iso", "- b.iso"]


def test_retained_cli_empty_policy_emits_nothing():
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--retained"],
        capture_output=True, text=True, check=False,
    )
    assert proc.returncode == 0
    assert proc.stdout == ""


# annotate-matrix.
def test_annotate_matrix_marks_only_cut_over_rows(config):
    policy = make_policy([make_entry("bonito", "gnome", "linux/amd64")])
    matrix = {"include": [
        {"variant": "bonito", "flavor": "gnome", "platform": "linux/amd64"},
        {"variant": "bonito", "flavor": "gnome", "platform": "linux/arm64"},
        {"variant": "yellowfin", "flavor": "kde-nvidia", "platform": "linux/amd64"},
    ]}
    snapshot = _qualified_snapshot(receipt_digest=DIGEST)
    annotated = DC.annotate_matrix(matrix, policy, config, snapshot=snapshot)
    assert [row["cutover"] for row in annotated["include"]] == [True, False, False]
    # The original rows survive untouched apart from the stamp.
    assert annotated["include"][0]["variant"] == "bonito"


def test_annotate_matrix_defaults_missing_platform(config):
    """Callers without a platform axis (publish-isos) annotate on the
    default platform, matching the amd64 default downstream."""
    policy = make_policy([make_entry("bonito", "gnome", "linux/amd64")])
    matrix = {"include": [{"variant": "bonito", "flavor": "gnome"}]}
    snapshot = _qualified_snapshot(receipt_digest=DIGEST)
    assert DC.annotate_matrix(
        matrix, policy, config, snapshot=snapshot
    )["include"][0]["cutover"] is True
    flipped = DC.annotate_matrix(
        matrix, policy, config, default_platform="linux/arm64", snapshot=snapshot
    )
    assert flipped["include"][0]["cutover"] is False


def test_annotate_matrix_rejects_bad_shape(config):
    with pytest.raises(ValueError):
        DC.annotate_matrix({"include": "not-a-list"}, make_policy([]), config)
    with pytest.raises(ValueError):
        DC.annotate_matrix({"include": ["not-a-mapping"]}, make_policy([]), config)


# Prune protection: dynamic retained rules replayed with first-match-wins.
RETAINED_DATED = [
    "bonito-gnome-20260914.iso",
    "bonito-gnome-20260914.iso.sha256",
    "bonito-gnome-20260914.iso.sigstore.json",
]


def _iso_prune_block():
    """The live-isos delete step's run block with shell comments removed.

    Comments quote past filter spellings as prose; parsing them as rules
    would test documentation instead of behavior.
    """
    doc = yaml.safe_load(PRUNE_WF.read_text(encoding="utf-8"))
    for step in doc["jobs"]["prune"]["steps"]:
        run = step.get("run", "")
        if "rclone delete" in run and "live-isos" in run:
            return "\n".join(
                line for line in run.splitlines() if not line.lstrip().startswith("#")
            )
    raise AssertionError("no live-isos prune step found")


def _static_prune_rules(code):
    rules = []
    for match in re.finditer(r'--filter "([+-]) ([^"]+)"', code):
        sign, pattern = match.groups()
        rules.append(("include" if sign == "+" else "exclude", pattern))
    return rules


def _verdict(name, rules):
    """First matching rule wins; matches rclone's ordered --filter form."""
    for kind, pattern in rules:
        if fnmatch.fnmatch(name, pattern):
            return "keep" if kind == "exclude" else "delete"
    return "keep" if any(kind == "include" for kind, _ in rules) else "delete"


def _prune_rules_with_retained(tmp_path):
    """Static rules from the workflow plus the dynamic retained rules the
    workflow splices in, in the position the workflow splices them."""
    policy_path = tmp_path / "policy.json"
    policy_path.write_text(
        json.dumps(make_policy([], retained=RETAINED_DATED)), encoding="utf-8"
    )
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--retained", "--policy", str(policy_path)],
        capture_output=True, text=True, check=False,
    )
    assert proc.returncode == 0
    dynamic = []
    for line in proc.stdout.splitlines():
        sign, _, pattern = line.partition(" ")
        dynamic.append(("include" if sign == "+" else "exclude", pattern))
    assert dynamic == [("exclude", name) for name in sorted(RETAINED_DATED)]

    code = _iso_prune_block()
    static = _static_prune_rules(code)
    latest = next(i for i, rule in enumerate(static) if rule == ("exclude", "*-latest*"))
    return static[: latest + 1] + dynamic + static[latest + 1 :]


def test_retained_rules_land_between_pointers_and_deletes():
    """The KEPT splice must sit after the latest-pointer exclusion and
    before the delete rules: first-match order keeps pointers, then retained
    objects, then prunes the rest."""
    code = _iso_prune_block()
    # Scope to the FLAGS formation: the dry-run echo above quotes
    # "${KEPT[@]}" again, which must not count as the splice position.
    flags = code[code.index("FLAGS=("):]
    latest_pos = flags.index('--filter "- *-latest*"')
    kept_pos = flags.index('"${KEPT[@]}"')
    deletes_pos = flags.index('--filter "+ *.iso"')
    assert latest_pos < kept_pos < deletes_pos


@pytest.mark.parametrize("name", RETAINED_DATED)
def test_prune_keeps_retained_dated_objects(tmp_path, name):
    rules = _prune_rules_with_retained(tmp_path)
    assert _verdict(name, rules) == "keep", f"prune would delete retained {name!r}"


@pytest.mark.parametrize(
    "name",
    [
        "bonito-gnome-latest.iso",
        "bonito-gnome-latest-arm64.iso",
        "bonito-gnome-latest-arm64.iso.sha256",
        "bonito-gnome-latest-arm64.iso.sigstore.json",
    ],
)
def test_prune_still_keeps_latest_pointers(tmp_path, name):
    rules = _prune_rules_with_retained(tmp_path)
    assert _verdict(name, rules) == "keep"


@pytest.mark.parametrize(
    "name",
    [
        "bonito-gnome-20260915.iso",
        "bonito-gnome-20260915.iso.sha256",
        "bonito-gnome-20260915.iso.sigstore.json",
        "yellowfin-kde-20260915-arm64.iso",
    ],
)
def test_prune_still_deletes_non_retained_dated_objects(tmp_path, name):
    """The other way to get this wrong: keep everything and prune nothing."""
    rules = _prune_rules_with_retained(tmp_path)
    assert _verdict(name, rules) == "delete", f"prune would keep {name!r} forever"
