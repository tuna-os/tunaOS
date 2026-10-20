"""Run the shared fork-contract fixtures against TunaOS adapters.

The fixtures are synthetic conformance inputs. They prove adapter compatibility
and rejection behavior, not a built image, frontend runtime, or installation.
"""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/fork-contracts-v1"
CASES = json.loads((FIXTURES / "cases.json").read_text(encoding="utf-8"))


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load adapter module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


INTENT = _load_module(ROOT / "scripts/resolve-fork-config.py", "fork_intent_fixture")
PROVENANCE = _load_module(ROOT / "scripts/iso_media_provenance.py", "iso_provenance_fixture")
CAPABILITIES = _load_module(ROOT / "scripts/installer-capabilities.py", "installer_capabilities_fixture")


def _case(name):
    try:
        return next(case for case in CASES["cases"] if case["name"] == name)
    except StopIteration:
        available = sorted(case["name"] for case in CASES["cases"])
        raise KeyError(f"unknown fixture case {name!r}; available={available}") from None


def _document(relative):
    return json.loads((FIXTURES / relative).read_text(encoding="utf-8"))


def _stub_x86_64_uname(tools: Path) -> None:
    uname = tools / "uname"
    uname.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "-m" ]; then echo x86_64; else\n'
        "  for candidate in /usr/bin/uname /bin/uname; do\n"
        '    [ -x "$candidate" ] && exec "$candidate" "$@"\n'
        "  done\n"
        "  exit 127\n"
        "fi\n"
    )
    uname.chmod(0o755)


def _normalized_intent(plan):
    return {
        "consumers_integrated": plan["consumers_integrated"],
        "image_intent": plan["image_intent"],
        "mode": plan["mode"],
        "package_resolution": plan["package_resolution"],
        "plan_version": plan["plan_version"],
        "selected_cells": [
            {
                "variant": cell["variant"],
                "flavor": cell["flavor"],
                "platform": cell["platform"],
                "intent": cell["intent"],
            }
            for cell in plan["cells"]
            if cell["selected"]
        ],
    }


@pytest.mark.parametrize(
    "name",
    [
        "intent-valid-inherited-overrides",
        "intent-rejects-unknown-field",
        "intent-rejects-missing-field",
        "intent-rejects-unsupported-version",
        "intent-rejects-inherited-package-conflict",
    ],
)
def test_fork_intent_fixture_cases_are_executable(name):
    case = _case(name)
    path = FIXTURES / case["input"]
    config = yaml.load(path.read_text(encoding="utf-8"), Loader=INTENT.UniqueLoader)
    if "normalized" in case:
        plan = INTENT.resolve(config, path.parent, ROOT)
        assert _normalized_intent(plan) == _document(case["normalized"])
        return
    with pytest.raises(INTENT.ConfigError) as caught:
        INTENT.resolve(config, path.parent, ROOT)
    assert str(caught.value) == case["expected_rejection"]


def _run_branding(relative, tmp_path):
    context = tmp_path / "context"
    manifest = context / "manifests/fork-config.json"
    manifest.parent.mkdir(parents=True)
    shutil.copy2(FIXTURES / relative, manifest)

    # The mismatch fixture is intentionally stable on every runner. The
    # adapter's real uname check is still exercised; only its architecture fact
    # is controlled for a deterministic cross-platform vector.
    tools = tmp_path / "tools"
    tools.mkdir()
    _stub_x86_64_uname(tools)
    env = os.environ.copy()
    env.update(
        {
            "PATH": os.pathsep.join(filter(None, (str(tools), env.get("PATH", "")))),
            "IMAGE_NAME_VARIANT": "yellowfin",
            "TUNAOS_IMAGE_FLAVOR": "gnome",
            "PKG_MGR": "dnf",
        }
    )
    return subprocess.run(
        [
            "bash",
            "-c",
            'set -euo pipefail; source "$1"; tunaos_validate_fork_branding "$2"',
            "fixture",
            str(ROOT / "build_scripts/lib/fork-branding.sh"),
            str(context),
        ],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


@pytest.mark.parametrize(
    "name",
    [
        "branding-valid-normalizes",
        "branding-rejects-platform-mismatch",
        "branding-rejects-unknown-field",
    ],
)
def test_branding_fixture_cases_run_the_shell_adapter(name, tmp_path):
    case = _case(name)
    result = _run_branding(case["input"], tmp_path)
    if "normalized" in case:
        assert result.returncode == 0, result.stderr
        assert json.loads((tmp_path / "context/manifests/fork-config.json").read_text(encoding="utf-8")) == _document(case["normalized"])
    else:
        assert result.returncode != 0
        assert case["expected_rejection"] in result.stderr


def _run_packages(relative, tmp_path, *, refresh=True):
    context = tmp_path / "context"
    manifest = context / "manifests/fork-config.json"
    manifest.parent.mkdir(parents=True)
    shutil.copy2(FIXTURES / relative, manifest)
    root = tmp_path / "root"
    root.mkdir()
    tools = tmp_path / "tools"
    tools.mkdir()
    _stub_x86_64_uname(tools)
    refresh_body = "return 0" if refresh else "return 1"
    command = f"""
set -euo pipefail
source "$1"
pkg_refresh() {{ {refresh_body}; }}
pkg_install() {{
    for package in "$@"; do
        [[ "$package" != missing ]]
    done
}}
tunaos_apply_fork_packages "$2" "$3"
"""
    env = os.environ.copy()
    env.update(
        {
            "PKG_MGR": "dnf",
            "IMAGE_NAME_VARIANT": "yellowfin",
            "TUNAOS_IMAGE_FLAVOR": "gnome",
            "PATH": os.pathsep.join(filter(None, (str(tools), env.get("PATH", "")))),
        }
    )
    return subprocess.run(
        [
            "bash",
            "-c",
            command,
            "fixture",
            str(ROOT / "build_scripts/lib/fork-packages.sh"),
            str(context),
            str(root),
        ],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    ), root


@pytest.mark.parametrize(
    "name",
    ["packages-valid-records-optional-miss", "packages-rejects-unavailable-offline-source"],
)
def test_package_fixture_cases_run_transaction_adapter(name, tmp_path):
    case = _case(name)
    result, root = _run_packages(case["input"], tmp_path, refresh="offline" not in name)
    receipt = root / "usr/share/tunaos/fork-config/packages/yellowfin--gnome--linux-amd64.json"
    if "normalized" in case:
        assert result.returncode == 0, result.stderr
        assert json.loads(receipt.read_text(encoding="utf-8")) == _document(case["normalized"])
    else:
        assert result.returncode != 0
        assert case["expected_rejection"] in result.stderr
        assert not receipt.exists()


def _set_path(document, path, value):
    current = document
    for item in path[:-1]:
        current = current[item]
    current[path[-1]] = value


def _provenance_bundle():
    source = ROOT / "tests/fixtures/iso-media-provenance-v2"
    cases = json.loads((source / "cases.json").read_text(encoding="utf-8"))
    return {
        "browser_bytes": cases["browserReceiptUtf8"].encode(),
        "native_bytes": cases["nativeReceiptUtf8"].encode(),
        "browser": json.loads(cases["browserReceiptUtf8"]),
        "native": json.loads(cases["nativeReceiptUtf8"]),
        "context": copy.deepcopy(cases["expectedContext"]),
        "transport": copy.deepcopy(cases["observedTransport"]),
        "media": (source / cases["mediaFile"]).read_bytes(),
    }, cases


def _digest(data):
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _refresh_provenance_receipts(bundle):
    browser_bytes = json.dumps(
        bundle["browser"], sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode() + b"\n"
    bundle["browser_bytes"] = browser_bytes
    bundle["native"]["browserReceiptSha256"] = _digest(browser_bytes)
    native_bytes = json.dumps(
        bundle["native"], sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode() + b"\n"
    bundle["native_bytes"] = native_bytes
    for role in ("context", "transport"):
        bundle[role]["browserProducer"]["receiptSha256"] = _digest(browser_bytes)
        bundle[role]["nativeProducer"]["receiptSha256"] = _digest(native_bytes)


@pytest.mark.parametrize(
    "name", ["evidence-rejects-image-digest-substitution", "evidence-rejects-platform-substitution"]
)
def test_evidence_fixture_vectors_run_v2_checker(name):
    case = _case(name)
    bundle, provenance_cases = _provenance_bundle()
    vector = next(vector for vector in provenance_cases["bindingCases"] if vector["name"] == case["vector"])
    for change in vector["changes"]:
        _set_path(bundle[change["document"]], change["path"], change["value"])
    if vector.get("refreshReceiptHashes"):
        _refresh_provenance_receipts(bundle)
    with pytest.raises(PROVENANCE.ContractError):
        PROVENANCE.check_consistency(
            bundle["browser_bytes"],
            bundle["native_bytes"],
            bundle["media"],
            bundle["context"],
            bundle["transport"],
        )
    assert case["expected"] == "reject"


def test_capability_registry_is_closed_and_fails_without_a_fallback():
    path = FIXTURES / _case("frontends-name-backend-and-unsupported-operations")["input"]
    registry = CAPABILITIES.load(path)
    assert {frontend["id"] for frontend in registry["frontends"]} == {
        "gnome", "kde", "cosmic", "niri", "xfce"
    }
    assert {
        frontend["repository"] for frontend in registry["frontends"]
    } == {"tuna-os/bootc-installer"}
    assert {
        frontend["path"] for frontend in registry["frontends"]
    } == {"bootc_installer", "frontends/kde", "frontends/cosmic",
          "frontends/niri", "frontends/xfce"}
    for frontend in registry["frontends"]:
        for operation in frontend["capabilities"]:
            CAPABILITIES.require_capability(registry, frontend["id"], operation)
        for operation in frontend["unsupported"]:
            with pytest.raises(CAPABILITIES.CapabilityError, match="unsupported operation"):
                CAPABILITIES.require_capability(registry, frontend["id"], operation)


def test_capability_registry_rejects_invalid_app_id(tmp_path):
    path = FIXTURES / _case("frontends-name-backend-and-unsupported-operations")["input"]
    registry = json.loads(path.read_text(encoding="utf-8"))
    registry["frontends"][0]["app_id"] = None
    invalid = tmp_path / "capabilities.json"
    invalid.write_text(json.dumps(registry))

    with pytest.raises(CAPABILITIES.CapabilityError, match=r"app_id: expected nonempty string"):
        CAPABILITIES.load(invalid)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("repository", None, r"repository: expected nonempty string"),
        ("capabilities", [" install"], r"capabilities: expected"),
        ("unsupported", ["install"], r"operation both supported and unsupported"),
        ("id", "kde", r"duplicate frontend"),
        ("backend", "missing", r"unknown backend"),
    ],
)
def test_capability_registry_rejects_invalid_contract_fields(tmp_path, field, value, message):
    path = FIXTURES / _case("frontends-name-backend-and-unsupported-operations")["input"]
    registry = json.loads(path.read_text(encoding="utf-8"))
    registry["frontends"][0][field] = value
    invalid = tmp_path / f"capabilities-{field}.json"
    invalid.write_text(json.dumps(registry))

    with pytest.raises(CAPABILITIES.CapabilityError, match=message):
        CAPABILITIES.load(invalid)


def test_capability_registry_rejects_missing_backend_operation(tmp_path):
    path = FIXTURES / _case("frontends-name-backend-and-unsupported-operations")["input"]
    registry = json.loads(path.read_text(encoding="utf-8"))
    registry["frontends"][0]["capabilities"].remove("fisherman-recipe")
    invalid = tmp_path / "capabilities-missing-operation.json"
    invalid.write_text(json.dumps(registry))

    with pytest.raises(CAPABILITIES.CapabilityError, match="backend operations not declared"):
        CAPABILITIES.load(invalid)


def test_capability_cli_rejects_unsupported_operation():
    path = FIXTURES / _case("frontends-name-backend-and-unsupported-operations")["input"]
    result = subprocess.run(
        [
            "python3",
            str(ROOT / "scripts/installer-capabilities.py"),
            str(path),
            "--frontend",
            "gnome",
            "--require",
            "fisherman-encryption-modes",
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 2
    assert "unsupported operation" in result.stderr


def test_fixture_index_is_versioned_and_paths_are_synchronized():
    assert CASES["fixture_family"] == "tunaos-fork-contracts"
    assert CASES["schema_version"] == 1
    contract_ids = {contract["id"] for contract in CASES["contracts"]}
    assert contract_ids == {
        "fork-intent",
        "fork-branding-input",
        "fork-package-receipt",
        "iso-media-provenance",
        "installer-capabilities",
    }
    for case in CASES["cases"]:
        assert case["contract"] in contract_ids
        for field in ("input", "normalized", "fixture"):
            if field in case:
                assert (FIXTURES / case[field]).is_file(), (case["name"], field)
