"""Read-only launcher contracts with stub Podman; not full-image evidence."""
import importlib.util
import json
from pathlib import Path
import subprocess

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("qualify_optional", ROOT / "scripts/qualify-fork-optional-removal.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    ancestor = tmp_path / "ancestor.json"
    ancestor.write_text(json.dumps({"variant": "grouper", "flavor": "gnome", "platform": "linux/amd64"}))
    output = tmp_path / "proof"
    calls = []
    monkeypatch.setattr(MODULE.PREPARE.COMPILER, "source_receipt", lambda root: {"sha256": "a" * 64})

    def prepare(config, destination, root):
        value = yaml.safe_load(config.read_text())
        assert value["global"] == {"packages": {"remove": ["fastfetch"]}}
        assert "branding" not in value["global"]
        context = destination / "grouper--gnome--linux-amd64"
        (context / "manifests").mkdir(parents=True)
        (context / "manifests/fork-config.json").write_text(json.dumps({**value, "sources": value["catalog"]}))
        return [{"context": context.name}]
    monkeypatch.setattr(MODULE.PREPARE, "prepare", prepare)
    monkeypatch.setattr(MODULE.subprocess, "check_output", lambda args, **kwargs: json.dumps([{"Id": "sha256:" + "b" * 64}]))

    def run(args, **kwargs):
        if args[:3] == ["podman", "container", "exists"]:
            return subprocess.CompletedProcess(args, 1)
        calls.append(args)
        for name in ("ancestor-package-receipt", "package-receipt", "stock-baseline", "native-removal-receipt"):
            (output / "evidence" / (name + ".json")).write_text("{}\n")
        return subprocess.CompletedProcess(args, 0, "native proof output", "")
    monkeypatch.setattr(MODULE.subprocess, "run", run)
    return ancestor, output, calls


def test_disposable_child_uses_immutable_id_and_distinct_context(fixture):
    ancestor, output, calls = fixture
    result = MODULE.qualify("localhost/example:grouper", "grouper", ancestor, output)
    assert result["status"] == "passed"
    assert result["scope"] == "disposable-package-contract-only"
    assert result["identity_qualification"] == result["boot_qualification"] == "not-run"
    assert result["installation"] == "not-run"
    assert result["proof_manifest_sha256"] != result["ancestor_manifest_sha256"]
    assert calls[0][:3] == ["podman", "run", "--pull=never"]
    assert "--network=none" in calls[0]
    assert result["container_cleanup"] == "verified-absent"
    assert "sha256:" + "b" * 64 in calls[0]
    assert "localhost/example:grouper" not in calls[0]
    assert "--privileged" not in calls[0]
    assert len(result["evidence_sha256"]) == 4


def test_failure_never_reports_success(fixture, monkeypatch):
    ancestor, output, _ = fixture
    monkeypatch.setattr(MODULE.subprocess, "run", lambda *args, **kwargs: subprocess.CompletedProcess(args, 1, "", "refused"))
    with pytest.raises(ValueError, match="native package proof failed"):
        MODULE.qualify("image", "grouper", ancestor, output)
    assert json.loads((output / "proof.json").read_text())["status"] == "failed"


def test_zero_exit_without_required_receipts_is_not_proof(fixture, monkeypatch):
    ancestor, output, _ = fixture
    monkeypatch.setattr(MODULE.subprocess, "run", lambda *args, **kwargs: subprocess.CompletedProcess(args, 0, "", ""))
    with pytest.raises(ValueError, match="native package proof failed"):
        MODULE.qualify("image", "grouper", ancestor, output)


def test_existing_output_is_never_reused(fixture):
    ancestor, output, calls = fixture
    output.mkdir()
    with pytest.raises(ValueError, match="new directory"):
        MODULE.qualify("image", "grouper", ancestor, output)
    assert calls == []


def test_receipt_ancestry_checked_before_exact_child_move():
    script = MODULE.CHILD
    assert script.index('.manifest_sha256 == $digest') < script.index('mv "$receipt"')
    assert script.index('mv "$receipt"') < script.index('tunaos_apply_fork_packages')
    assert '\nrm ' not in script
    assert 'TUNAOS_FORK_REMOVAL_QUALIFICATION' not in script
    assert 'tunaos_finalize_fork_packages /run/context gnome /' in script


def test_timeout_cleans_only_owned_child_and_finalizes_failure(fixture, monkeypatch):
    ancestor, output, _ = fixture
    calls = []
    state = {"exists": True}

    def run(args, **kwargs):
        calls.append(args)
        if args[:2] == ["podman", "run"]:
            state["name"] = args[args.index("--name") + 1]
            raise subprocess.TimeoutExpired(args, 1800, output=b"partial", stderr=b"timeout")
        if args[:3] == ["podman", "container", "exists"]:
            return subprocess.CompletedProcess(args, 0 if state["exists"] else 1)
        assert args == ["podman", "rm", "--force", state["name"]]
        state["exists"] = False
        return subprocess.CompletedProcess(args, 0)

    def inspect(args, **kwargs):
        if args[:3] == ["podman", "image", "inspect"]:
            return json.dumps([{"Id": "b" * 64}])
        return json.dumps([{"Config": {"Labels": {"org.tunaos.package-proof": state["name"]}}}])
    monkeypatch.setattr(MODULE.subprocess, "run", run)
    monkeypatch.setattr(MODULE.subprocess, "check_output", inspect)
    with pytest.raises(ValueError, match="native package proof failed"):
        MODULE.qualify("image", "grouper", ancestor, output)
    result = json.loads((output / "proof.json").read_text())
    assert result["status"] == "failed"
    assert result["container_cleanup"] == "verified-absent"
    assert not state["exists"]
    assert (output / "stdout.log").read_text() == "partial"


def test_symlinked_output_ancestor_is_rejected(fixture, tmp_path):
    ancestor, _, _ = fixture
    link = tmp_path / "link"
    link.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError, match="ancestors"):
        MODULE.qualify("image", "grouper", ancestor, link / "new")


def test_duplicate_ancestry_key_is_rejected(fixture):
    ancestor, output, _ = fixture
    ancestor.write_text('{"variant":"grouper","variant":"yellowfin"}')
    with pytest.raises(ValueError, match="duplicate JSON key"):
        MODULE.qualify("image", "grouper", ancestor, output)
