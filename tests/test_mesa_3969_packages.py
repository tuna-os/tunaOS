"""Pure metadata/spec tests for the held Mesa lab; no RPM, GPG or builds."""

import copy
import importlib.util
import sys
from pathlib import Path

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
