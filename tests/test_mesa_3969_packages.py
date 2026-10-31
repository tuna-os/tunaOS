"""Source-only metadata/spec and transfer-integrity tests; no RPM, GPG or builds."""

import copy
import importlib.util
import json
import os
import sys
import signal
import time
from pathlib import Path
import zipfile

import pytest


HERE = Path(__file__).resolve().parent / "manual"
SOURCE_RPM = "mesa-25.2.7-4.el10.alma.5.src.rpm"
VENDOR_SPEC = """Name: mesa
%global ver 25.2.7
Version: %{ver}
Release: 4.el10.alma.5
# Preserve vendor patch ordering and all build/check policy.
Patch11: 0001-device-select-add-a-layer-setting-to-disable-device-.patch
Patch12: 0002-zink-use-device-select-layer-settings-to-disable-dev.patch
Patch13: 0001-gallivm-handle-u16-correct-on-const-loads.patch
Patch14: 0001-Revert-dri-fix-__DRI_IMAGE_FORMAT-to-PIPE_FORMAT-map.patch
Patch1001: cd129dbf8af2d16b1243f2ce287ff69c6a5dc557.patch

%description
Vendor Mesa fixture.
%prep
%autosetup -n %{name}-%{ver} -p1
%build
%meson -Dplatforms=x11,wayland
%check
%meson_test
"""
CANDIDATE_DECLARATION = (
    "Patch1002: c9b298660774291478323c5ef148362d9b136c3b.patch\n"
)


@pytest.fixture
def packages(monkeypatch):
    """Load adjacent modules without leaving a sys.path/sys.modules mutation."""
    def load(name):
        spec = importlib.util.spec_from_file_location(name, HERE / f"{name}.py")
        if spec is None or spec.loader is None:
            raise ImportError(f"cannot load {name} from {HERE}")
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, name, module)
        spec.loader.exec_module(module)
        return module

    load("mesa_3969")
    module = load("mesa_3969_packages")

    def forbidden(*args, **kwargs):
        raise AssertionError("pure package tests must not execute tools or download inputs")

    monkeypatch.setattr(module, "run", forbidden)
    monkeypatch.setattr(module.subprocess, "run", forbidden)
    monkeypatch.setattr(module.urllib.request, "urlopen", forbidden)
    return module


def inventory_record(name="mesa-dri-drivers", *, header="a" * 64, **changes):
    record = {
        "name": name,
        "epoch": 2,
        "version": "25.2.7",
        "release": "4.el10.alma.5",
        "arch": "x86_64",
        "source_rpm": SOURCE_RPM,
        "header_sha256": header,
    }
    record.update(changes)
    return record


def package_record(name="mesa-dri-drivers", *, arm="control", **changes):
    record = inventory_record(name, header="b" * 64 if arm == "control" else "c" * 64)
    record.update(
        path=f"rpms/{arm}/{name}-25.2.7-4.el10.alma.5.x86_64.rpm",
        sha256="d" * 64 if arm == "control" else "e" * 64,
        bytes=128,
    )
    record.update(changes)
    return record


def inventory_of(record):
    return {key: value for key, value in record.items() if key not in {"path", "sha256", "bytes"}}


@pytest.fixture
def pair():
    # libgbm belongs to Mesa despite lacking the prefix; libGLU does not.
    baseline = [
        inventory_record(),
        inventory_record("libgbm"),
        inventory_record("mesa-libGLU", epoch=0, version="9.0.3", release="7.el10",
                         source_rpm="mesa-libGLU-9.0.3-7.el10.src.rpm", header="f" * 64),
        inventory_record("bash", epoch=0, version="5.2.26", release="6.el10",
                         source_rpm="bash-5.2.26-6.el10.src.rpm", header="1" * 64),
        inventory_record("gpg-pubkey", epoch=0, version="1234abcd", release="12345678",
                         arch="(none)", source_rpm=None, header=None),
    ]
    names = ["mesa-dri-drivers", "libgbm", "mesa-devel", "mesa-filesystem"]
    control = [package_record(name, arch="noarch" if name == "mesa-filesystem" else "x86_64")
               for name in names]
    candidate = [package_record(name, arm="candidate",
                                arch="noarch" if name == "mesa-filesystem" else "x86_64")
                 for name in names]
    return baseline, control, candidate


def test_candidate_spec_adds_only_ordered_patch_and_preserves_vendor_policy(packages):
    transformed = packages.candidate_spec(VENDOR_SPEC)
    before, after = VENDOR_SPEC.split("\n\n%description", 1)
    assert transformed == before + "\n" + CANDIDATE_DECLARATION + "\n%description" + after
    # Applying the transformation twice must refuse, not add another patch.
    with pytest.raises(packages.LabError, match="patch chain drift"):
        packages.candidate_spec(transformed)


@pytest.mark.parametrize("old,new", [
    ("Patch11:", "Patch15:"),
    ("Patch12: 0002-zink-use-device-select-layer-settings-to-disable-dev.patch\n", ""),
    ("Patch13: 0001-gallivm-handle-u16-correct-on-const-loads.patch",
     "Patch13: substituted.patch"),
    ("Patch1001:", "Patch1002:"),
    ("\n%description", "\nPatch1002: collision.patch\n%description"),
    ("\n%description", "\nPatch11: duplicate.patch\n%description"),
    ("\n%description", "\nPatch: unexpected.patch\n%description"),
    ("%global ver 25.2.7", "%global ver 25.2.8"),
    ("%global ver 25.2.7", "%global ver 25.2.7\n%global ver 25.2.8"),
    ("%autosetup -n %{name}-%{ver} -p1", ""),
    ("%autosetup -n %{name}-%{ver} -p1", "%autosetup -n %{name}-%{ver} -p0"),
    ("%autosetup -n %{name}-%{ver} -p1", "%autosetup -n %{name}-%{ver} -p1 -N"),
    ("%autosetup -n %{name}-%{ver} -p1", "%autosetup -n %{name}-%{ver} -p1\n%autosetup -p1"),
])
def test_candidate_spec_refuses_vendor_drift_and_patch_collisions(packages, old, new):
    with pytest.raises(packages.LabError):
        packages.candidate_spec(VENDOR_SPEC.replace(old, new))


def test_candidate_spec_refuses_reordered_original_patch_chain(packages):
    lines = VENDOR_SPEC.splitlines(keepends=True)
    first = next(index for index, line in enumerate(lines) if line.startswith("Patch11:"))
    lines[first], lines[first + 1] = lines[first + 1], lines[first]
    with pytest.raises(packages.LabError, match="patch chain drift"):
        packages.candidate_spec("".join(lines))


def test_query_records_preserve_nonzero_epoch_and_absent_public_key_metadata(packages):
    text = (
        "mesa-dri-drivers\t2\t25.2.7\t4.el10.alma.5\tx86_64\t"
        + SOURCE_RPM + "\t" + "a" * 64 + "\n"
        "gpg-pubkey\t(none)\t1234abcd\t12345678\t(none)\t(none)\t(none)\n"
        "bash\t0\t5.2.26\t6.el10\tx86_64\t\t\n"
    )
    assert packages._records(text) == [
        inventory_record("bash", epoch=0, version="5.2.26", release="6.el10",
                         source_rpm=None, header=None),
        inventory_record("gpg-pubkey", epoch=0, version="1234abcd", release="12345678",
                         arch="(none)", source_rpm=None, header=None),
        inventory_record(),
    ]


@pytest.mark.parametrize("text", [
    "", "\n", "mesa\t0\t25.2.7\n",
    "mesa\t0\t25.2.7\t4\tx86_64\t(none)\t(none)\textra\n",
    "mesa\t-1\t25.2.7\t4\tx86_64\t(none)\t(none)\n",
    "mesa\tTrue\t25.2.7\t4\tx86_64\t(none)\t(none)\n",
    "mesa\t4294967296\t25.2.7\t4\tx86_64\t(none)\t(none)\n",
    "mesa\t0\t25.2.7\t4\tx86_64\t(none)\tdeadbeef\n",
    "mesa\t0\t25.2.7\t4\tx86_64\t(none)\t" + "A" * 64 + "\n",
])
def test_query_records_refuse_malformed_rows_epochs_and_header_digests(packages, text):
    with pytest.raises(packages.LabError):
        packages._records(text)


@pytest.mark.parametrize("change", [
    {"epoch": True}, {"epoch": -1}, {"epoch": 2**32},
    {"arch": "(none)"}, {"name": "../mesa"},
    {"source_rpm": "../mesa.src.rpm"}, {"header_sha256": "0" * 63},
    {"unknown": "field"},
])
def test_inventory_refuses_invalid_schema_without_repairing_it(packages, change):
    with pytest.raises(packages.LabError):
        packages.validate_inventory([inventory_record(**change)])


def test_inventory_rejects_duplicate_identity_even_with_different_headers(packages):
    with pytest.raises(packages.LabError, match="duplicate inventory identity"):
        packages.validate_inventory([inventory_record(), inventory_record(header="b" * 64)])


def test_inventory_normalizes_order_without_mutating_or_aliasing_input(packages):
    original = [inventory_record("z-output"), inventory_record("a-output")]
    snapshot = copy.deepcopy(original)
    result = packages.validate_inventory(original)
    assert [item["name"] for item in result] == ["a-output", "z-output"]
    result[0]["header_sha256"] = "b" * 64
    assert original == snapshot


def test_pair_matches_complete_sets_but_selects_only_exact_installed_source_closure(packages, pair):
    baseline, control, candidate = pair
    snapshot = copy.deepcopy(pair)
    selected = packages.validate_pair(control, list(reversed(candidate)), list(reversed(baseline)))
    assert selected == {
        "control": [control[1], control[0]],
        "candidate": [candidate[1], candidate[0]],
    }
    assert pair == snapshot
    assert {record["name"] for record in selected["control"]} == {"libgbm", "mesa-dri-drivers"}


@pytest.mark.parametrize("arm", ["control", "candidate"])
@pytest.mark.parametrize("operation", ["missing", "extra", "duplicate", "epoch", "version", "release", "arch", "source", "header"])
def test_pair_refuses_incomplete_incoherent_or_invalid_output_sets(packages, pair, arm, operation):
    baseline, control, candidate = pair
    outputs = control if arm == "control" else candidate
    # mesa-devel is not installed; it still must be present and coherent in both full sets.
    if operation == "missing":
        outputs.pop(2)
    elif operation == "extra":
        outputs.append(package_record("unexpected-output", arm=arm))
    elif operation == "duplicate":
        outputs.append(dict(outputs[2]))
    else:
        field, value = {
            "epoch": ("epoch", 0), "version": ("version", "25.2.8"),
            "release": ("release", "5.el10"), "arch": ("arch", "aarch64"),
            "source": ("source_rpm", "mesa-25.2.8-1.el10.src.rpm"),
            "header": ("header_sha256", None),
        }[operation]
        outputs[2][field] = value
    with pytest.raises(packages.LabError):
        packages.validate_pair(control, candidate, baseline)


@pytest.mark.parametrize("field,value", [
    ("epoch", 0), ("version", "25.2.6"), ("release", "3.el10"),
    ("arch", "i686"), ("source_rpm", "mesa-25.2.6-3.el10.src.rpm"),
    ("source_rpm", None), ("header_sha256", None),
])
def test_closure_refuses_baseline_source_evra_or_missing_header_drift(packages, pair, field, value):
    baseline, control, _ = pair
    baseline[0][field] = value
    with pytest.raises(packages.LabError):
        packages.select_closure(baseline, control)


def test_closure_refuses_other_mesa_version_even_for_output_not_in_current_build(packages, pair):
    baseline, control, _ = pair
    baseline.append(inventory_record("old-mesa-output", source_rpm="mesa-24.0.0-1.el10.src.rpm"))
    with pytest.raises(packages.LabError, match="source/version drift"):
        packages.select_closure(baseline, control)


def test_closure_requires_some_installed_package_from_pinned_source(packages, pair):
    baseline, control, _ = pair
    unrelated = [record for record in baseline if record["source_rpm"] != SOURCE_RPM]
    with pytest.raises(packages.LabError, match="no packages"):
        packages.select_closure(unrelated, control)


def installed_arm(baseline, selected):
    replacement = {record["name"]: inventory_of(record) for record in selected}
    return [copy.deepcopy(replacement.get(record["name"], record)) for record in baseline]


@pytest.mark.parametrize("arm", ["control", "candidate"])
def test_installed_exact_selected_headers_allow_unchanged_unrelated_and_public_key_records(packages, pair, arm):
    baseline, control, candidate = pair
    selected = packages.select_closure(baseline, control if arm == "control" else candidate)
    installed = installed_arm(baseline, selected)
    # Include a successful validation plus a negative control: success must actually check headers.
    assert packages.validate_installed(baseline, list(reversed(installed)), selected) is None
    installed[0]["header_sha256"] = "9" * 64
    with pytest.raises(packages.LabError, match="installed headers differ"):
        packages.validate_installed(baseline, installed, selected)


@pytest.mark.parametrize("mode", ["unchanged-baseline", "wrong-arm", "mixed-arms"])
def test_same_nevra_is_not_proof_of_the_selected_arm(packages, pair, mode):
    baseline, control, candidate = pair
    selected = packages.select_closure(baseline, candidate)
    if mode == "unchanged-baseline":
        installed = copy.deepcopy(baseline)
    else:
        control_selected = packages.select_closure(baseline, control)
        installed = installed_arm(baseline, control_selected)
        if mode == "mixed-arms":
            installed[0] = inventory_of(candidate[0])
    with pytest.raises(packages.LabError, match="installed headers differ"):
        packages.validate_installed(baseline, installed, selected)


@pytest.mark.parametrize("target", ["bash", "mesa-libGLU", "gpg-pubkey"])
@pytest.mark.parametrize("field,value", [
    ("epoch", 1), ("version", "999"), ("release", "999"),
    ("source_rpm", "substituted-1-1.src.rpm"), ("header_sha256", "9" * 64),
])
def test_installed_rejects_every_unrelated_identity_or_header_change(packages, pair, target, field, value):
    baseline, control, _ = pair
    selected = packages.select_closure(baseline, control)
    installed = installed_arm(baseline, selected)
    next(record for record in installed if record["name"] == target)[field] = value
    with pytest.raises(packages.LabError, match="installed headers differ"):
        packages.validate_installed(baseline, installed, selected)


@pytest.mark.parametrize("operation", ["remove-unrelated", "add-unrelated", "install-extra-output", "remove-selected"])
def test_installed_rejects_added_or_removed_packages(packages, pair, operation):
    baseline, control, _ = pair
    selected = packages.select_closure(baseline, control)
    installed = installed_arm(baseline, selected)
    if operation == "remove-unrelated":
        installed = [record for record in installed if record["name"] != "bash"]
    elif operation == "add-unrelated":
        installed.append(inventory_record("extra", source_rpm=None, header=None))
    elif operation == "install-extra-output":
        installed.append(inventory_of(control[2]))
    else:
        installed = [record for record in installed if record["name"] != "libgbm"]
    with pytest.raises(packages.LabError, match="installed headers differ"):
        packages.validate_installed(baseline, installed, selected)


@pytest.mark.parametrize("operation", ["missing", "extra", "duplicate"])
def test_installed_validator_requires_exact_transaction_source_closure(packages, pair, operation):
    baseline, control, _ = pair
    selected = packages.select_closure(baseline, control)
    installed = installed_arm(baseline, selected)
    if operation == "missing":
        selected.pop()
    elif operation == "extra":
        selected.append(control[2])
    else:
        selected.append(dict(selected[0]))
    with pytest.raises(packages.LabError):
        packages.validate_installed(baseline, installed, selected)


@pytest.fixture
def draft_transfer(packages, monkeypatch, tmp_path):
    """Real transfer files, explicitly not native RPM/OCI/signature fixtures."""
    core = sys.modules["mesa_3969"]
    name = "test_mesa_3969_source_smoke"
    spec = importlib.util.spec_from_file_location(name, HERE / f"{name}.py")
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {name} from {HERE}")
    smoke = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, smoke)
    spec.loader.exec_module(smoke)
    producer = {
        "repository_id": core.REPOSITORY_ID, "repository": core.REPOSITORY,
        "head_sha": "a" * 40, "run_id": 3969001, "run_attempt": 1,
        "workflow_id": 3969, "job_id": 701,
    }
    manifest, members = smoke.synthetic_bundle(core.INPUTS, producer)
    manifest["files"] = []
    transfer = tmp_path / "transfer"
    transfer.mkdir(mode=0o700)
    for name, data in members.items():
        path = transfer / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    core.write_json(transfer / "manifest.json", manifest)
    return core, transfer, manifest, members


def archive_transfer(transfer, output):
    """Archive bytes actually on disk, not an independently invented inventory."""
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as archive:
        for path in sorted(transfer.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(transfer).as_posix())
    return output


def test_unsealed_draft_is_rejected_by_package_and_archive_consumers(
    packages, draft_transfer, tmp_path,
):
    core, transfer, manifest, members = draft_transfer
    before = (transfer / "manifest.json").read_bytes()
    # Every payload exists: the empty inventory alone prevents verification,
    # before the fixture's forbidden RPM/GPG commands can be reached.
    assert {path.relative_to(transfer).as_posix() for path in transfer.rglob("*")
            if path.is_file()} == {"manifest.json", *members}
    with pytest.raises(packages.LabError, match="bounded file inventory required"):
        packages.verify_transfer(transfer)
    archive = archive_transfer(transfer, tmp_path / "unsealed.zip")
    with pytest.raises(core.LabError, match="bounded file inventory required"):
        core.verify_archive(archive, manifest["producer"])
    assert (transfer / "manifest.json").read_bytes() == before


@pytest.mark.parametrize("late_file", ["baseline.oci.tar", "build-report.json"])
def test_finalization_requires_export_and_report_before_sealing(
    draft_transfer, tmp_path, late_file,
):
    core, transfer, manifest, members = draft_transfer
    path = transfer / late_file
    path.unlink()
    before = (transfer / "manifest.json").read_bytes()
    with pytest.raises(core.LabError, match="transfer member inventory incomplete"):
        core.seal_transfer(transfer)
    assert (transfer / "manifest.json").read_bytes() == before
    path.write_bytes(members[late_file])
    sealed = core.seal_transfer(transfer)
    archive = archive_transfer(transfer, tmp_path / "complete.zip")
    consumed = core.verify_archive(archive, manifest["producer"])
    assert consumed == sealed
    inventory = {row["path"]: row for row in consumed["files"]}
    assert set(inventory) == set(members)
    assert inventory[late_file]["bytes"] == len(members[late_file])
    with zipfile.ZipFile(archive) as zipped:
        assert zipped.read(late_file) == members[late_file]


@pytest.mark.parametrize("late_file", ["baseline.oci.tar", "build-report.json"])
def test_finalization_consumer_rejects_same_size_export_or_report_change(
    draft_transfer, tmp_path, late_file,
):
    core, transfer, manifest, members = draft_transfer
    core.seal_transfer(transfer)
    original = members[late_file]
    changed = bytes([original[0] ^ 1]) + original[1:]
    assert len(changed) == len(original)
    (transfer / late_file).write_bytes(changed)
    archive = archive_transfer(transfer, tmp_path / "changed.zip")
    with pytest.raises(core.LabError, match="member size/hash mismatch"):
        core.verify_archive(archive, manifest["producer"])


@pytest.mark.parametrize("omitted_cost", ["manifest", "zip-overhead"])
def test_producer_seal_refuses_archive_consumer_would_reject_before_upload(
    draft_transfer, tmp_path, monkeypatch, omitted_cost,
):
    core, transfer, manifest, members = draft_transfer
    sealed = core.seal_transfer(transfer)
    manifest_bytes = (transfer / "manifest.json").read_bytes()
    archive = archive_transfer(transfer, tmp_path / "transport.zip")
    assert core.verify_archive(archive, manifest["producer"]) == sealed
    payload_bytes = sum(len(data) for data in members.values())
    cap = payload_bytes
    if omitted_cost == "zip-overhead":
        cap += len(manifest_bytes)
    assert payload_bytes <= cap < archive.stat().st_size
    assert sum(row["bytes"] for row in sealed["files"]) < core.MAX_UNPACKED
    # Scale the transport boundary, not file sizes or hashes; the real ZIP
    # independently demonstrates why payload-only admission is insufficient.
    monkeypatch.setattr(core, "MAX_ARCHIVE", cap)
    with pytest.raises(core.LabError, match="archive exceeds limit"):
        core.verify_archive(archive, manifest["producer"])
    core.write_json(transfer / "manifest.json", manifest)
    draft_bytes = (transfer / "manifest.json").read_bytes()
    with pytest.raises(core.LabError, match="archive"):
        core.seal_transfer(transfer)
    assert (transfer / "manifest.json").read_bytes() == draft_bytes
    assert {name: (transfer / name).read_bytes() for name in members} == members


@pytest.fixture
def local_identity():
    """Local provenance DATA only; no execution authority or native artifacts."""
    return {
        "schema_version": 1, "kind": "mesa3969-local-build",
        "operation_id": "b" * 32, "head_sha": "a" * 40,
        "owner_uid": int(os.environ.get("SUDO_UID", os.geteuid())) if os.geteuid() == 0 else os.geteuid(),
        "host": os.uname().nodename, "started_at": 1, "checkout": str(HERE.parents[1].resolve()),
    }


@pytest.fixture
def local_draft_transfer(draft_transfer, local_identity):
    core, transfer, manifest, members = draft_transfer
    manifest.pop("producer")
    manifest.update(kind="mesa3969-local-inputs", local=local_identity)
    manifest["baseline"]["image_tag"] = (
        f"localhost/mesa-3969-local-{local_identity['operation_id']}-"
        f"{local_identity['head_sha'][:8]}-build-labbase:once"
    )
    (transfer / "manifest.json").unlink()
    core.write_json(transfer / "local-manifest.json", manifest)
    return core, transfer, manifest, members


def test_build_provenance_is_exclusive_and_local_namespace_has_no_actions_identity(
    packages, draft_transfer, local_identity, tmp_path,
):
    _, _, hosted_manifest, _ = draft_transfer
    producer = hosted_manifest["producer"]
    with pytest.raises(packages.LabError, match="exactly one"):
        packages.Build(tmp_path)
    with pytest.raises(packages.LabError, match="exactly one"):
        packages.Build(tmp_path, producer, local=local_identity)
    local = packages.Build(tmp_path, local=local_identity)
    hosted = packages.Build(tmp_path, producer)
    assert local.namespace == "local-" + local_identity["operation_id"]
    assert local.head == local_identity["head_sha"]
    assert local.label == local.namespace + "-" + local.head
    assert local.manifest_name == "local-manifest.json"
    assert local.report["kind"] == "mesa3969-local-build-report"
    assert local.report["local"] == local_identity
    assert "producer" not in local.report and local.producer is None
    assert hosted.namespace == str(producer["run_id"])
    assert hosted.manifest_name == "manifest.json"
    assert hosted.report["producer"] == producer and "local" not in hosted.report
    # Constructing provenance descriptors does not create scratch state.
    assert not (tmp_path / "work").exists()


@pytest.mark.parametrize("change", [
    {"run_id": 3969001}, {"kind": "mesa3969-inputs"},
    {"operation_id": "B" * 32}, {"head_sha": "a" * 39},
])
def test_local_build_descriptor_rejects_hosted_or_malformed_identity_before_effects(
    packages, local_identity, tmp_path, change,
):
    with pytest.raises(packages.LabError):
        packages.Build(tmp_path, local={**local_identity, **change})
    assert not (tmp_path / "work").exists()


def test_local_native_build_rejects_a_different_checkout_before_effects(
    packages, local_identity, tmp_path,
):
    with pytest.raises(packages.LabError, match="checkout differs"):
        packages.Build(tmp_path, local={**local_identity, "checkout": str(tmp_path.resolve())})
    assert not (tmp_path / "work").exists()


@pytest.mark.parametrize("confirmation", ["", "RUN_MESA_3969_ONCE", "BUILD_MESA3969_LOCAL_ONLY "])
def test_local_entry_refuses_unapproved_confirmation_before_tools_or_scratch(
    packages, tmp_path, confirmation,
):
    scratch = tmp_path / "must-not-be-created"
    with pytest.raises(packages.LabError):
        packages.local_build("a" * 40, scratch, confirmation)
    assert not scratch.exists()


def test_local_draft_never_reaches_native_verifier(packages, local_draft_transfer, local_identity):
    core, transfer, _, _ = local_draft_transfer
    before = (transfer / "local-manifest.json").read_bytes()
    with pytest.raises(core.LabError, match="bounded file inventory required"):
        packages.verify_local_transfer(transfer, local_identity)
    assert (transfer / "local-manifest.json").read_bytes() == before
    assert not (transfer / "manifest.json").exists()


def test_local_sealing_is_distinct_and_hosted_consumers_reject_even_renamed_manifest(
    packages, local_draft_transfer, local_identity, tmp_path,
):
    core, transfer, _, _ = local_draft_transfer
    sealed = core.seal_local_transfer(transfer, local_identity)
    assert core.validate_local_manifest(sealed, local_identity) == sealed
    assert "producer" not in sealed
    assert not (transfer / "manifest.json").exists()
    with pytest.raises(core.LabError):
        core.validate_manifest(sealed)
    with pytest.raises(core.LabError):
        core.validate_producer(local_identity)
    # Merely renaming local data must not turn it into a hosted transfer.
    (transfer / "local-manifest.json").rename(transfer / "manifest.json")
    with pytest.raises(core.LabError):
        packages.verify_transfer(transfer)
    archive = archive_transfer(transfer, tmp_path / "renamed-local.zip")
    with pytest.raises(core.LabError):
        core.verify_archive(archive)


@pytest.mark.parametrize("field,value", [
    ("operation_id", "c" * 32), ("head_sha", "d" * 40), ("host", "foreign-host"),
])
def test_local_native_verifier_rejects_foreign_expected_owner_before_tools(
    packages, local_draft_transfer, local_identity, field, value,
):
    core, transfer, _, _ = local_draft_transfer
    core.seal_local_transfer(transfer, local_identity)
    with pytest.raises(core.LabError):
        packages.verify_local_transfer(transfer, {**local_identity, field: value})


def test_local_seal_keeps_native_rpm_verification_mandatory(
    packages, local_draft_transfer, local_identity,
):
    core, transfer, _, _ = local_draft_transfer
    core.seal_local_transfer(transfer, local_identity)
    before = {path.relative_to(transfer).as_posix(): path.read_bytes()
              for path in transfer.rglob("*") if path.is_file()}
    # Synthetic metadata can be sealed, but is not a native RPM/signature pass.
    # The real verifier reaches the forbidden RPM tool rather than returning success.
    with pytest.raises(AssertionError, match="pure package tests must not execute tools"):
        packages.verify_local_transfer(transfer, local_identity)
    assert {path.relative_to(transfer).as_posix(): path.read_bytes()
            for path in transfer.rglob("*") if path.is_file()} == before


@pytest.mark.parametrize("member,mutation", [
    ("baseline.oci.tar", "missing"),
    ("build-report.json", "same-size"),
    ("baseline-inventory.json", "same-size-json"),
])
def test_local_native_verification_checks_all_sealed_payload_before_rpm_tools(
    packages, local_draft_transfer, local_identity, member, mutation,
):
    core, transfer, _, _ = local_draft_transfer
    core.seal_local_transfer(transfer, local_identity)
    manifest_before = (transfer / "local-manifest.json").read_bytes()
    path = transfer / member
    if mutation == "missing":
        path.unlink()
    else:
        original = path.read_bytes()
        changed = b"\n[]" if mutation == "same-size-json" else bytes([original[0] ^ 1]) + original[1:]
        assert len(changed) == len(original)
        if mutation == "same-size-json":
            assert json.loads(changed) == json.loads(original)
        path.write_bytes(changed)
    # The fixture forbids actual RPM/GPG commands. A missing non-RPM file,
    # unread build report or semantically equal inventory still invalidates
    # the sealed byte contract before those commands can run.
    with pytest.raises(core.LabError):
        packages.verify_local_transfer(transfer, local_identity)
    assert (transfer / "local-manifest.json").read_bytes() == manifest_before


def test_owned_build_cleanup_continues_after_malformed_and_foreign_inspection(
    packages, local_identity, tmp_path, monkeypatch,
):
    build = packages.Build(tmp_path, local=local_identity)
    build.containers = ["missing", "foreign", "malformed"]
    build.images = ["owned-removal-fails"]
    calls = []

    def storage_failure(args, **kwargs):
        """Negative cleanup adapter only; never models a successful native build."""
        calls.append(args)
        _, kind, operation, name = args[:4]
        if operation == "inspect":
            if name == "missing":
                return packages.subprocess.CompletedProcess(args, 125, "", "no such container")
            if name == "malformed":
                return packages.subprocess.CompletedProcess(args, 0, "not-json", "")
            labels = {"io.tunaos.mesa3969": "foreign" if name == "foreign" else build.label}
            value = {"Labels": labels} if kind == "image" else {"Config": {"Labels": labels}}
            return packages.subprocess.CompletedProcess(args, 0, packages.json.dumps([value]), "")
        if operation == "exists" and name == "missing":
            return packages.subprocess.CompletedProcess(args, 1)
        if operation == "rm" and name == "--force":
            assert args[4] == "owned-removal-fails"
            return packages.subprocess.CompletedProcess(args, 125, "", "removal failed")
        raise AssertionError(f"unexpected storage action: {args}")

    monkeypatch.setattr(packages.subprocess, "run", storage_failure)
    errors = build.cleanup_objects()
    assert len(errors) == 3
    assert any("malformed" in error for error in errors)
    assert any("unowned container: foreign" in error for error in errors)
    assert any("failed owned image removal" in error for error in errors)
    removals = [args for args in calls if args[2] == "rm"]
    assert removals == [["podman", "image", "rm", "--force", "owned-removal-fails"]]


@pytest.mark.parametrize("extra", ["private-key.asc", "local-owner.json", "gnupg/private-keys-v1.d/key.key"])
def test_local_sealing_refuses_private_or_owner_material_in_transfer(
    local_draft_transfer, local_identity, extra,
):
    core, transfer, _, _ = local_draft_transfer
    before = (transfer / "local-manifest.json").read_bytes()
    path = transfer / extra
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("deliberate non-secret boundary fixture\n")
    with pytest.raises(core.LabError):
        core.seal_local_transfer(transfer, local_identity)
    assert (transfer / "local-manifest.json").read_bytes() == before


@pytest.fixture
def real_packages(monkeypatch):
    """The module with its real run()/subprocess; no tool-execution guard."""
    for name in ("mesa_3969", "mesa_3969_packages"):
        spec = importlib.util.spec_from_file_location(name, HERE / f"{name}.py")
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, name, module)
        spec.loader.exec_module(module)
    return sys.modules["mesa_3969_packages"]


def test_streamed_command_failure_reports_the_build_log_tail(real_packages, tmp_path):
    # Build steps stream into build.raw.log; a failure used to raise an empty
    # "command podman failed (1): ", hiding which step broke.
    with (tmp_path / "build.raw.log").open("w") as log:
        with pytest.raises(real_packages.LabError) as failure:
            real_packages.run(["sh", "-c", "echo step-that-broke; exit 3"], output=log)
    assert "(3)" in str(failure.value)
    assert "log tail:" in str(failure.value) and "step-that-broke" in str(failure.value)


def test_local_deadline_interrupts_work_and_restores_the_alarm(real_packages):
    previous = signal.getsignal(signal.SIGALRM)
    started = time.monotonic()
    with pytest.raises(real_packages.LabError, match="deadline"):
        with real_packages.local_deadline(0.2):
            time.sleep(10)
    assert time.monotonic() - started < 5
    assert signal.getsignal(signal.SIGALRM) == previous
    assert signal.getitimer(signal.ITIMER_REAL) == (0.0, 0.0)
