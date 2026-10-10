"""Consumer demand is deterministic, platform-bound, and honest about gaps."""
from __future__ import annotations

import base64
import copy
import hashlib
import json
from pathlib import Path
import sys

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.contracts import base, consumer, evidence

REVISION = "1" * 40
POLICY_REVISION = "9" * 40
PROOF = {"url": "https://example.org/measured-baseline.json", "digest": "sha256:" + "a" * 64}
OCI_INDEX = "application/vnd.oci.image.index.v1+json"
OCI_IMAGE = "application/vnd.oci.image.manifest.v1+json"
OCI_CONFIG = "application/vnd.oci.image.config.v1+json"
TARGET = {"variant": "yellowfin", "flavor": "cosmic", "platform": "linux/amd64/v2",
          "cpuBaseline": "x86-64-v2", "hardwareScope": "generic"}


def encode_blob(document):
    """Construct independent OCI bytes, never through the implementation."""
    raw = json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
    return base64.b64encode(raw).decode(), "sha256:" + hashlib.sha256(raw).hexdigest(), len(raw)


def base_record(target=TARGET, *, descriptor_platform=None, config_platform=None, duplicate=False):
    platform = {"os": "linux", "architecture": "amd64", "variant": "v2"}
    if target["platform"] == "linux/arm64":
        platform = {"os": "linux", "architecture": "arm64", "variant": "v8"}
    elif target["platform"] == "linux/amd64":
        platform = {"os": "linux", "architecture": "amd64"}
    config_doc = {"os": platform["os"], "architecture": platform["architecture"]}
    config_doc.update(config_platform or {})
    config_bytes, config_digest, config_size = encode_blob(config_doc)
    child = {"schemaVersion": 2, "mediaType": OCI_IMAGE,
             "config": {"mediaType": OCI_CONFIG, "digest": config_digest, "size": config_size}, "layers": []}
    child_bytes, child_digest, child_size = encode_blob(child)
    descriptor = {"mediaType": OCI_IMAGE, "digest": child_digest, "size": child_size,
                  "platform": platform if descriptor_platform is None else descriptor_platform}
    index = {"schemaVersion": 2, "mediaType": OCI_INDEX, "manifests": [descriptor]}
    if duplicate:
        index["manifests"].append(copy.deepcopy(descriptor))
    index_bytes, index_digest, _ = encode_blob(index)
    reference = "quay.io/example/base:stable@" + index_digest
    return {"configuredReference": reference, "reference": "quay.io/example/base@" + child_digest,
            "indexDigest": index_digest, "childDigest": child_digest, "configDigest": config_digest,
            "platform": target["platform"], "cpuBaseline": target["cpuBaseline"],
            "indexBytes": index_bytes, "childBytes": child_bytes, "configBytes": config_bytes,
            "baselineEvidence": [copy.deepcopy(PROOF)]}


def stage_source(tmp_path, manifest, target=TARGET):
    directory = tmp_path / "manifests/desktops"
    directory.mkdir(parents=True)
    (directory / "cosmic.yaml").write_text(yaml.safe_dump(manifest, sort_keys=True))
    scripts = tmp_path / "build_scripts"
    scripts.mkdir()
    for name in ["10-base-packages.sh", "20-packages.sh", "26-packages-post.sh"]:
        (scripts / name).write_text("#!/bin/bash\ntrue\n")
    record = base_record(target)
    config = {"variants": [{"id": target["variant"], "base_image": record["configuredReference"],
                            "platforms": [target["platform"]],
                            "flavors": [{"id": target["flavor"], "build_image": True}]}]}
    (tmp_path / ".github").mkdir()
    (tmp_path / ".github/build-config.yml").write_text(yaml.safe_dump(config))
    return config, record


def resolve(tmp_path, manifest, target=TARGET):
    config, record = stage_source(tmp_path, manifest, target)
    return consumer.resolve_consumer(target, config, record, REVISION, tmp_path,
                                     copy.deepcopy(manifest), POLICY_REVISION)


def test_exact_base_child_and_config_are_bound_to_full_oci_platform():
    record = base_record()
    result = base.validate_base(record, TARGET, record["configuredReference"])
    assert result["observedPlatform"] == {"os": "linux", "architecture": "amd64", "variant": "v2"}
    assert result["reference"].startswith("quay.io/example/base@sha256:")
    assert result["reference"].endswith(result["childDigest"])
    assert result["indexDigest"] != result["childDigest"] != result["configDigest"]
    assert not {"indexBytes", "childBytes", "configBytes"} & set(result)


@pytest.mark.parametrize("change", [{"indexDigest": "sha256:" + "b" * 64},
                                   {"childBytes": base64.b64encode(b'{}').decode()},
                                   {"configBytes": base64.b64encode(b'{}').decode()},
                                   {"platform": "linux/amd64"}, {"cpuBaseline": "x86-64"},
                                   {"baselineEvidence": []},
                                   {"baselineEvidence": [{"url": "https://example.org/proof"}]},
                                   {"reference": "quay.io/other/base@sha256:" + "b" * 64},
                                   {"reference": "quay.io/example/base:latest"}])
def test_base_resolution_rejects_unbound_or_inconsistent_evidence(change):
    record = base_record()
    configured = record["configuredReference"]
    record.update(change)
    with pytest.raises(evidence.EvidenceError):
        base.validate_base(record, TARGET, configured)


@pytest.mark.parametrize("kwargs", [
    {"descriptor_platform": {"os": "linux", "architecture": "amd64"}},
    {"descriptor_platform": {"os": "linux", "architecture": "arm64", "variant": "v8"}},
    {"descriptor_platform": {"os": "windows", "architecture": "amd64", "variant": "v2"}},
    {"config_platform": {"architecture": "arm64"}},
    {"config_platform": {"variant": "v3"}},
    {"duplicate": True},
])
def test_validly_hashed_oci_bytes_cannot_hide_platform_mismatch_or_ambiguity(kwargs):
    record = base_record(**kwargs)
    with pytest.raises(evidence.EvidenceError):
        base.validate_base(record, TARGET, record["configuredReference"])


def test_ubuntu_arm64_retains_v8_descriptor_without_becoming_amd64():
    target = dict(TARGET, variant="grouper", platform="linux/arm64", cpuBaseline="armv8-a")
    record = base_record(target)
    result = base.validate_base(record, target, record["configuredReference"])
    assert result["platform"] == "linux/arm64"
    assert result["cpuBaseline"] == "armv8-a"
    assert result["observedPlatform"] == {"os": "linux", "architecture": "arm64", "variant": "v8"}


@pytest.mark.parametrize("platform,baseline", [("linux/amd64", "x86-64"), ("linux/arm64", "armv8-a")])
def test_single_manifest_root_binds_actual_native_platform(platform, baseline):
    target = dict(TARGET, variant="marlin", platform=platform, cpuBaseline=baseline)
    record = base_record(target)
    record.update(indexBytes=record["childBytes"], indexDigest=record["childDigest"],
                  configuredReference=record["reference"])
    result = base.validate_base(record, target, record["configuredReference"])
    assert result["indexDigest"] == result["childDigest"]
    assert result["observedPlatform"] == {"os": "linux", "architecture": platform.split('/')[1]}


def test_single_manifest_cannot_invent_v2_variant_from_baseline_claim():
    record = base_record()
    record.update(indexBytes=record["childBytes"], indexDigest=record["childDigest"],
                  configuredReference=record["reference"])
    with pytest.raises(evidence.EvidenceError):
        base.validate_base(record, TARGET, record["configuredReference"])


def test_single_manifest_cannot_hide_a_different_selected_child():
    target = dict(TARGET, variant="marlin", platform="linux/arm64", cpuBaseline="armv8-a")
    record = base_record(target)
    record.update(indexBytes=record["childBytes"], indexDigest=record["childDigest"],
                  configuredReference=record["reference"], childBytes=base64.b64encode(b'{}').decode())
    with pytest.raises(evidence.EvidenceError):
        base.validate_base(record, target, record["configuredReference"])


@pytest.mark.parametrize("variant,section,manager,expression,platform,baseline", [
    ("yellowfin", "el10", "dnf", "cosmic-session-1:1.0-2.el10", "linux/amd64/v2", "x86-64-v2"),
    ("grouper", "apt", "apt", "cosmic-session=1:1.0-2ubuntu1", "linux/arm64", "armv8-a"),
    ("marlin", "pacman", "pacman", "cosmic-session>=1.0", "linux/amd64", "x86-64"),
    ("sailfin", "zypper", "zypper", "cosmic-session>=1.0", "linux/amd64", "x86-64"),
    ("guppy", "emerge", "portage", ">=gui-wm/cosmic-session-1.0:0/1[wayland]", "linux/amd64", "x86-64"),
])
def test_native_expressions_are_preserved_without_inventing_providers(tmp_path, variant, section, manager, expression, platform, baseline):
    target = dict(TARGET, variant=variant, platform=platform, cpuBaseline=baseline)
    document = resolve(tmp_path, {"packages": {section: [expression]}}, target)
    assert document["packageManager"] == manager
    assert document["packageRequirements"] == [{"nativeExpression": expression, "manager": manager,
        "scope": "final", "required": True,
        "origins": [{"path": f"manifests/desktops/cosmic.yaml:packages.{section}", "phase": "desktop"}]}]
    assert document["approvedSources"] == []
    assert document["resolution"]["status"] == "incomplete"
    assert evidence.validate(document, "consumer-contract") == document


def test_merging_optional_request_preserves_requiredness_and_both_origins(tmp_path):
    doc = resolve(tmp_path, {"packages": {"el10": {"packages": ["cosmic-session"], "optional": ["cosmic-session"]}}})
    assert len(doc["packageRequirements"]) == 1
    item = doc["packageRequirements"][0]
    assert item["required"] is True
    assert item["origins"] == [
        {"path": "manifests/desktops/cosmic.yaml:packages.el10.packages", "phase": "desktop"},
        {"path": "manifests/desktops/cosmic.yaml:packages.el10.optional", "phase": "desktop"}]


def test_distinct_requested_sources_are_not_collapsed_to_a_factory_provider(tmp_path):
    manifest = {"packages": {"el10": {"packages": ["cosmic-session"], "copr": [
        {"repo": "legacy/a", "packages": ["cosmic-session"]},
        {"repo": "legacy/b", "packages": ["cosmic-session"]}]}}}
    doc = resolve(tmp_path, manifest)
    assert {item.get("requestedSource") for item in doc["packageRequirements"]} == {None, "legacy/a", "legacy/b"}
    assert all("provider" not in item for item in doc["packageRequirements"])
    assert doc["approvedSources"] == []
    assert doc["sourcePolicy"]["forbiddenNew"] == []
    assert evidence.validate(doc) == doc


def test_groups_exclusions_and_locks_stay_explicit_until_native_resolution(tmp_path):
    doc = resolve(tmp_path, {"packages": {"el10": {"groups": ["cosmic-desktop"],
        "group_options": "--with-optional", "group_exclude": ["legacy-theme"], "exclude": ["old-session"],
        "versionlock": ["cosmic-session-1:1.0-2.el10"]}}})
    assert doc["nativeGroups"] == [{"nativeId": "cosmic-desktop", "options": "--with-optional",
        "excludes": ["legacy-theme"], "origins": [{"path": "manifests/desktops/cosmic.yaml:packages.el10.groups", "phase": "desktop"}]}]
    assert doc["nativeExcludes"] == ["old-session"]
    assert doc["nativeVersionLocks"] == ["cosmic-session-1:1.0-2.el10"]
    assert "native-group-expansion-required" in {gap["code"] for gap in doc["resolution"]["unresolved"]}
    assert doc["resolution"]["status"] != "complete"
    assert evidence.validate(doc) == doc


def test_group_without_options_still_produces_schema_valid_incomplete_contract(tmp_path):
    doc = resolve(tmp_path, {"packages": {"el10": {"groups": ["cosmic-desktop"]}}})
    assert doc["resolution"]["status"] != "complete"
    assert evidence.validate(doc) == doc


def test_manifest_hook_and_overlay_gaps_are_explicit_and_inputs_are_bound(tmp_path):
    target = dict(TARGET, flavor="cosmic-hwe")
    manifest = {"packages": {"el10": {"packages": ["cosmic-session"], "pre_install": ["pkg_install helper"]}},
                "post_install": ["desktop/hook.sh"]}
    config, record = stage_source(tmp_path, manifest, target)
    (tmp_path / "build_scripts/desktop").mkdir()
    (tmp_path / "build_scripts/desktop/hook.sh").write_text("pkg_install hook-added\n")
    (tmp_path / "build_scripts/overlay").mkdir()
    (tmp_path / "build_scripts/overlay/hwe.sh").write_text("pkg_install kernel-new\n")
    doc = consumer.resolve_consumer(target, config, record, REVISION, tmp_path, manifest, POLICY_REVISION)
    codes = {gap["code"] for gap in doc["resolution"]["unresolved"]}
    assert {"shell-hook-observation-required", "overlay-demand-observation-required"} <= codes
    paths = {item["path"] for item in doc["inputs"]}
    assert {"build_scripts/desktop/hook.sh", "build_scripts/overlay/hwe.sh"} <= paths
    assert all("provider" not in item for item in doc["packageRequirements"])
    assert evidence.validate(doc) == doc


@pytest.mark.parametrize("hook", ["../outside.sh", "/tmp/outside.sh"])
def test_hook_path_cannot_escape_build_scripts(tmp_path, hook):
    manifest = {"packages": {"el10": ["cosmic-session"]}, "post_install": [hook]}
    with pytest.raises(evidence.EvidenceError):
        resolve(tmp_path, manifest)


def test_missing_hook_blocks_instead_of_disappearing(tmp_path):
    doc = resolve(tmp_path, {"packages": {"el10": ["cosmic-session"]}, "post_install": ["desktop/missing.sh"]})
    assert doc["resolution"]["status"] == "blocked"
    assert "missing-hook-script" in {gap["code"] for gap in doc["resolution"]["unresolved"]}


def test_unknown_repository_condition_blocks_the_required_target(tmp_path):
    manifest = {"packages": {"el10": {"packages": ["cosmic-session"], "repos": [
        {"name": "required", "baseurl": "https://repo.tunaos.org/el10", "condition": "mystery-os"}]}}}
    config, record = stage_source(tmp_path, manifest)
    result = consumer.resolve_all(config, {"yellowfin:cosmic:linux/amd64/v2": record}, REVISION, tmp_path,
                                  {"manifests/desktops/cosmic.yaml": manifest}, POLICY_REVISION)
    row = result["targets"][0]
    assert row["status"] == "blocked"
    assert row["contract"] is None
    assert "unsupported repository condition" in row["reasons"][0]["detail"]


def test_debian_override_replaces_the_generic_manifest(tmp_path):
    target = dict(TARGET, variant="flounder", platform="linux/arm64", cpuBaseline="armv8-a")
    generic = {"packages": {"apt": ["generic-wrong"]}}
    config, record = stage_source(tmp_path, generic, target)
    override = {"packages": {"apt": ["debian-only=1:2.0-1"]}}
    (tmp_path / "manifests/desktops/cosmic-debian.yaml").write_text(yaml.safe_dump(override))
    doc = consumer.resolve_consumer(target, config, record, REVISION, tmp_path, override, POLICY_REVISION)
    assert [item["nativeExpression"] for item in doc["packageRequirements"]] == ["debian-only=1:2.0-1"]
    assert "manifests/desktops/cosmic-debian.yaml" in {item["path"] for item in doc["inputs"]}


def test_arch_override_combines_with_cachyos_additions(tmp_path):
    target = dict(TARGET, variant="marlin", flavor="cosmic-cachyos", platform="linux/amd64", cpuBaseline="x86-64")
    generic = {"packages": {"pacman": ["generic-wrong"]}}
    config, record = stage_source(tmp_path, generic, target)
    override = {"packages": {"pacman": ["cosmic-session"], "cachyos": {"packages": ["linux-cachyos"]}}}
    (tmp_path / "manifests/desktops/cosmic-arch.yaml").write_text(yaml.safe_dump(override))
    doc = consumer.resolve_consumer(target, config, record, REVISION, tmp_path, override, POLICY_REVISION)
    assert sorted(item["nativeExpression"] for item in doc["packageRequirements"]) == ["cosmic-session", "linux-cachyos"]
    assert doc["resolution"]["status"] != "complete"


def test_required_empty_base_records_keep_all_269_real_targets_blocked():
    config = yaml.safe_load((ROOT / ".github/build-config.yml").read_text())
    result = consumer.resolve_all(config, {}, REVISION, ROOT)
    assert len(result["targets"]) == 269
    assert all(row["required"] and row["status"] == "blocked" and row["contract"] is None for row in result["targets"])
    assert all(row["reasons"][0]["code"] == "missing-base-record" for row in result["targets"])
    assert any(row["target"]["variant"] == "grouper" and row["target"]["platform"] == "linux/arm64" for row in result["targets"])


def test_policy_requires_pinned_revision_and_new_sources_are_blocked(tmp_path):
    manifest = {"packages": {"el10": {"packages": ["cosmic-session"], "copr": [{"repo": "new/source", "packages": ["extra"]}]}}}
    config, record = stage_source(tmp_path, manifest)
    doc = consumer.resolve_consumer(TARGET, config, record, REVISION, tmp_path, {"packages": {"el10": ["cosmic-session"]}}, POLICY_REVISION)
    assert doc["resolution"]["status"] == "blocked"
    assert "forbidden-new-package-source" in {gap["code"] for gap in doc["resolution"]["unresolved"]}
    inherited = consumer.resolve_consumer(TARGET, config, record, REVISION, tmp_path, manifest, None)
    assert inherited["resolution"]["status"] == "blocked"
    assert "missing-policy-revision" in {gap["code"] for gap in inherited["resolution"]["unresolved"]}


def test_contract_hash_is_repeatable_and_binds_hook_and_source_inputs(tmp_path):
    manifest = {"packages": {"el10": ["cosmic-session"]}}
    config, record = stage_source(tmp_path, manifest)
    first = consumer.resolve_consumer(TARGET, config, record, REVISION, tmp_path, manifest, POLICY_REVISION)
    second = consumer.resolve_consumer(copy.deepcopy(TARGET), copy.deepcopy(config), copy.deepcopy(record), REVISION, tmp_path, copy.deepcopy(manifest), POLICY_REVISION)
    assert second == first
    assert evidence.validate(first) == first
    (tmp_path / "build_scripts/20-packages.sh").write_text("#!/bin/bash\npkg_install additional\n")
    changed = consumer.resolve_consumer(TARGET, config, record, REVISION, tmp_path, manifest, POLICY_REVISION)
    assert changed["contractDigest"] != first["contractDigest"]
    assert changed["resolution"]["status"] != "complete"


@pytest.mark.parametrize("change,code", [
    ("manifest-missing", "missing-effective-manifest"),
    ("manager-missing", "missing-manager-section"),
    ("unknown-field", "unsupported-manifest-field"),
])
def test_missing_required_manifest_inputs_are_explicitly_blocked(tmp_path, change, code):
    manifest = {"packages": {"el10": ["cosmic-session"]}}
    if change == "manager-missing":
        manifest = {"packages": {"apt": ["wrong-manager"]}}
    elif change == "unknown-field":
        manifest = {"packages": {"el10": {"packages": ["cosmic-session"], "mystery_required_packages": ["lost"]}}}
    config, record = stage_source(tmp_path, manifest)
    if change == "manifest-missing":
        (tmp_path / "manifests/desktops/cosmic.yaml").unlink()
    doc = consumer.resolve_consumer(TARGET, config, record, REVISION, tmp_path, manifest, POLICY_REVISION)
    assert doc["resolution"]["status"] == "blocked"
    assert code in {gap["code"] for gap in doc["resolution"]["unresolved"]}
    assert evidence.validate(doc) == doc


def test_inline_install_hooks_cannot_disappear_from_explicit_observation_gaps(tmp_path):
    doc = resolve(tmp_path, {"packages": {"el10": ["cosmic-session"]},
                             "post_install_inline": ["pkg_install dynamically-added"]})
    assert any(gap["code"] == "shell-hook-observation-required" and "post_install_inline" in gap["detail"]
               for gap in doc["resolution"]["unresolved"])
    assert any("commandDigest" in hook and "post_install_inline" in hook["origin"] for hook in doc["hooks"])
    assert doc["resolution"]["status"] != "complete"


@pytest.mark.parametrize("revision", ["abc123", "A" * 40])
def test_policy_revision_is_an_immutable_lowercase_commit(tmp_path, revision):
    manifest = {"packages": {"el10": ["cosmic-session"]}}
    config, record = stage_source(tmp_path, manifest)
    with pytest.raises(evidence.EvidenceError, match="policy revision"):
        consumer.resolve_consumer(TARGET, config, record, REVISION, tmp_path, manifest, revision)


def test_baseline_copr_declaration_cannot_authorize_a_replacement_source(tmp_path):
    manifest = {"packages": {"el10": {"packages": ["cosmic-session"], "copr": [{"repo": "new/unapproved", "packages": ["extra"]}]}}}
    baseline = {"packages": {"el10": {"packages": ["cosmic-session"], "copr": [{"repo": "old/legacy", "packages": ["extra"]}]}}}
    config, record = stage_source(tmp_path, manifest)
    doc = consumer.resolve_consumer(TARGET, config, record, REVISION, tmp_path, baseline, POLICY_REVISION)
    assert doc["resolution"]["status"] == "blocked"
    assert doc["sourcePolicy"]["forbiddenNew"]


def test_base_required_record_cannot_claim_another_configured_index():
    record = base_record()
    with pytest.raises(evidence.EvidenceError):
        base.validate_base(record, TARGET, "quay.io/example/base:stable@sha256:" + "b" * 64)


def test_desktop_native_version_floor_is_an_explicit_resolution_input(tmp_path):
    doc = resolve(tmp_path, {"packages": {"el10": ["cosmic-session"]}, "minimum_version": "50"})
    assert any(gap["code"] == "native-desktop-version-floor-required"
               and gap["origin"] == "manifests/desktops/cosmic.yaml:minimum_version"
               and "50" in gap["detail"] for gap in doc["resolution"]["unresolved"])
    assert doc["resolution"]["status"] != "complete"


def test_unknown_top_level_manifest_field_blocks_instead_of_disappearing(tmp_path):
    doc = resolve(tmp_path, {"packages": {"el10": ["cosmic-session"]},
                             "mystery_required_behavior": "must-not-disappear"})
    assert doc["resolution"]["status"] == "blocked"
    assert any(gap["code"].startswith("unsupported-") and "mystery_required_behavior" in gap["detail"]
               for gap in doc["resolution"]["unresolved"])


@pytest.fixture
def public_registry(monkeypatch):
    """Substitute only HTTP transport; exercise the actual public resolver."""
    import io
    import urllib.request
    documents = {}
    requests = []
    class Registry:
        def open(self, request, timeout):
            requests.append((request.full_url, timeout, dict(request.header_items())))
            assert request.full_url in documents, 'unexpected metadata or layer request'
            return io.BytesIO(documents[request.full_url])
    monkeypatch.setattr(urllib.request, 'build_opener', lambda *handlers: Registry())
    return documents, requests


def registry_bytes(public_registry, target, *, single=True, config_platform=None):
    documents, requests = public_registry
    record = base_record(target, config_platform=config_platform)
    root_bytes = base64.b64decode(record['childBytes' if single else 'indexBytes'])
    reference = 'quay.io/example/base:stable'
    documents['https://quay.io/v2/example/base/manifests/stable'] = root_bytes
    if not single:
        documents['https://quay.io/v2/example/base/manifests/' + record['childDigest']] = base64.b64decode(record['childBytes'])
    documents['https://quay.io/v2/example/base/blobs/' + record['configDigest']] = base64.b64decode(record['configBytes'])
    return reference, record, root_bytes


@pytest.mark.parametrize('single', [True, False])
@pytest.mark.parametrize('platform,baseline,config', [
    ('linux/amd64', 'x86-64', {}),
    ('linux/arm64', 'armv8-a', {}),
    ('linux/arm64', 'armv8-a', {'variant': 'v8'}),
    ('linux/amd64/v2', 'x86-64-v2', {'variant': 'v2'}),
])
def test_public_resolver_fetches_exact_root_child_config_no_layers(public_registry, single, platform, baseline, config):
    target = dict(TARGET, variant='yellowfin' if platform.endswith('/v2') else 'marlin',
                  platform=platform, cpuBaseline=baseline)
    reference, fixture, root = registry_bytes(public_registry, target, single=single, config_platform=config)
    result = base.resolve_public_base(reference, target, [PROOF])
    assert result['reference'] == 'quay.io/example/base@' + fixture['childDigest']
    assert result['configBytes'] == fixture['configBytes']
    assert result['indexBytes'] == base64.b64encode(root).decode()
    assert result['indexDigest'] == 'sha256:' + hashlib.sha256(root).hexdigest()
    assert result['childDigest'] == fixture['childDigest']
    assert (result['indexBytes'] == result['childBytes']) is single
    assert len(public_registry[1]) == (2 if single else 3)
    assert all(request[1] == 30 for request in public_registry[1])


def test_public_single_root_missing_v2_is_rejected(public_registry):
    reference, _, _ = registry_bytes(public_registry, TARGET)
    with pytest.raises(evidence.EvidenceError):
        base.resolve_public_base(reference, TARGET, [PROOF])


@pytest.mark.parametrize('config', [
    {'os': 'windows'}, {'architecture': 'amd64'}, {'variant': 'v9'},
    {'architecture': True}, {'os': None}, {'variant': []},
])
def test_public_single_root_rejects_actual_config_platform_mismatch(public_registry, config):
    target = dict(TARGET, variant='marlin', platform='linux/arm64', cpuBaseline='armv8-a')
    reference, _, _ = registry_bytes(public_registry, target, config_platform=config)
    with pytest.raises(evidence.EvidenceError):
        base.resolve_public_base(reference, target, [PROOF])


@pytest.mark.parametrize('change', [
    {'schemaVersion': True}, {'schemaVersion': 2.0}, {'mediaType': []}, {'mediaType': {}},
    {'layers': None}, {'config': {'mediaType': OCI_CONFIG, 'digest': 'sha256:' + 'a' * 64, 'size': True}},
])
def test_public_single_root_rejects_malformed_manifest_types(public_registry, change):
    target = dict(TARGET, variant='marlin', platform='linux/amd64', cpuBaseline='x86-64')
    reference, _, raw = registry_bytes(public_registry, target)
    document = json.loads(raw); document.update(change)
    public_registry[0]['https://quay.io/v2/example/base/manifests/stable'] = json.dumps(document).encode()
    with pytest.raises(evidence.EvidenceError):
        base.resolve_public_base(reference, target, [PROOF])


@pytest.mark.parametrize('failure', ['size', 'config-digest', 'root-pin', 'duplicate', 'oversize', 'utf8'])
def test_public_single_root_rejects_unbound_or_unreadable_metadata(public_registry, failure):
    target = dict(TARGET, variant='marlin', platform='linux/amd64', cpuBaseline='x86-64')
    reference, fixture, raw = registry_bytes(public_registry, target)
    url = 'https://quay.io/v2/example/base/manifests/stable'
    if failure == 'size':
        doc = json.loads(raw); doc['config']['size'] += 1
        public_registry[0][url] = json.dumps(doc).encode()
    elif failure == 'config-digest':
        public_registry[0]['https://quay.io/v2/example/base/blobs/' + fixture['configDigest']] = b'{}'
    elif failure == 'root-pin':
        reference = 'quay.io/example/base@sha256:' + 'f' * 64
        public_registry[0]['https://quay.io/v2/example/base/manifests/sha256:' + 'f' * 64] = raw
    elif failure == 'duplicate':
        public_registry[0][url] = b'{"schemaVersion":2,"schemaVersion":2}'
    elif failure == 'oversize':
        public_registry[0][url] = b' ' * (4 * 1024 * 1024 + 1)
    else:
        public_registry[0][url] = b'\xff'
    with pytest.raises(evidence.EvidenceError):
        base.resolve_public_base(reference, target, [PROOF])
