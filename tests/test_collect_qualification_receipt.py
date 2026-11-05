"""scripts/collect-qualification-receipt.py admits only authenticated receipts.

The collector runs as a real subprocess. Only the network is replaced: a fake
`gh` on PATH serves the iso-builder run, its artifact list, the artifact
download, and the `gh attestation verify` result. Everything else (receipt
validation, tunaos.toml platform lookup, the receipt file, and the printed
TOML) is the real code path.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import textwrap
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
COLLECTOR = ROOT / "scripts" / "collect-qualification-receipt.py"
FIXTURE = ROOT / "tests" / "fixtures" / "browser-iso-qualification-v1" / "receipt.json"
POLICY_SPEC = importlib.util.spec_from_file_location(
    "iso_delivery_policy_collector", ROOT / "scripts" / "iso-delivery-policy.py")
POLICY = importlib.util.module_from_spec(POLICY_SPEC)
assert POLICY_SPEC.loader
POLICY_SPEC.loader.exec_module(POLICY)
RECEIPT = POLICY.qualification_receipt
sys.path.insert(0, str(ROOT / "scripts"))
from lib import tunaos_config

RUN_ID = 19000000001
SHA = "3333333333333333333333333333333333333333"
ISO_ARTIFACT_ID = 4400000001

FAKE_GH = textwrap.dedent("""\
    #!/usr/bin/env python3
    import hashlib, json, os, shutil, sys
    from pathlib import Path
    state = Path(os.environ["FAKE_GH_STATE"])
    args = sys.argv[1:]
    with (state / "calls.jsonl").open("a") as log:
        log.write(json.dumps(args) + "\\n")
    if args[0] == "api":
        path = next(a for a in args if a.startswith("repos/"))
        name = "artifacts.jsonl" if "/artifacts" in path else "run.json"
        sys.stdout.write((state / name).read_text())
    elif args[:2] == ["run", "download"]:
        source = state / "artifacts" / args[args.index("--name") + 1]
        if not source.is_dir():
            sys.exit("no artifact")
        shutil.copytree(source, args[args.index("--dir") + 1], dirs_exist_ok=True)
    elif args[:2] == ["attestation", "verify"]:
        attested = (state / "attested-digest").read_text().strip()
        if hashlib.sha256(Path(args[2]).read_bytes()).hexdigest() != attested:
            sys.exit("subject digest mismatch")
        sys.stdout.write((state / "attestation.json").read_text())
    else:
        sys.exit("unexpected gh call: " + " ".join(args))
""")


def _flavor(arm64: bool) -> tuple[str, str]:
    """A real ISO flavor whose platforms include (or omit) linux/arm64."""
    matrix = tunaos_config.matrix(tunaos_config.load())
    for variant in matrix["variants"]:
        for flavor in variant["flavors"]:
            platforms = flavor.get("platforms", variant.get("platforms", []))
            if (flavor.get("build_image") is True and flavor.get("build_iso") is True
                    and "linux/amd64" in platforms and ("linux/arm64" in platforms) == arm64):
                return variant["id"], flavor["id"]
    raise AssertionError(f"tunaos.toml has no ISO flavor with arm64={arm64}")


def _receipt(variant: str, flavor: str, attempt: int = 1) -> dict:
    receipt = json.loads(FIXTURE.read_text(encoding="utf-8"))
    image = f"ghcr.io/tuna-os/{variant}:{flavor}"
    receipt["target"].update(variant=variant, flavor=flavor, image=image)
    for mode in receipt["modes"].values():
        mode["target_imgref"] = image
    receipt["producer"].update(runAttempt=attempt,
                               isoArtifactName=f"iso-{variant}-{flavor}-run{RUN_ID}-a{attempt}")
    return receipt


class Fake:
    def __init__(self, tmp_path: Path, variant: str, flavor: str):
        self.state = tmp_path / "gh-state"
        self.receipts = tmp_path / "receipts"
        self.slug = f"{variant}-{flavor}"
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        (bin_dir / "gh").write_text(FAKE_GH)
        (bin_dir / "gh").chmod(0o755)
        self.env = dict(os.environ, PATH=f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
                        FAKE_GH_STATE=str(self.state))
        self.state.mkdir()
        self.run = {
            "id": RUN_ID, "path": ".github/workflows/ci.yml", "head_branch": "main",
            "event": "workflow_dispatch", "status": "completed", "conclusion": "success",
            "head_sha": SHA, "repository": {"full_name": "tuna-os/iso-builder"},
            "head_repository": {"full_name": "tuna-os/iso-builder"},
        }
        self.artifacts: list[dict] = []
        self.publish(_receipt(variant, flavor), attempt=1)

    def publish(self, receipt: dict, attempt: int) -> bytes:
        iso_id = ISO_ARTIFACT_ID + attempt - 1
        receipt["producer"]["isoArtifactId"] = iso_id
        name = f"qualification-receipt-{self.slug}-run{RUN_ID}-a{attempt}"
        folder = self.state / "artifacts" / name
        folder.mkdir(parents=True)
        (folder / "receipt.json").write_bytes(RECEIPT.canonical(receipt))
        (folder / "bundle.jsonl").write_text("{}\n")
        self.artifacts += [
            {"id": 5500000000 + attempt, "name": name, "expired": False},
            {"id": iso_id, "name": f"iso-{self.slug}-run{RUN_ID}-a{attempt}", "expired": False},
        ]
        self.attest(folder / "receipt.json", attempt)
        return (folder / "receipt.json").read_bytes()

    def attest(self, receipt_file: Path, attempt: int,
               invocation: str | None = None) -> None:
        (self.state / "attested-digest").write_text(hashlib.sha256(receipt_file.read_bytes()).hexdigest())
        uri = invocation or f"https://github.com/tuna-os/iso-builder/actions/runs/{RUN_ID}/attempts/{attempt}"
        (self.state / "attestation.json").write_text(json.dumps([
            {"verificationResult": {"signature": {"certificate": {"runInvocationURI": uri}}}}]))

    def collect(self) -> subprocess.CompletedProcess[str]:
        (self.state / "run.json").write_text(json.dumps(self.run))
        (self.state / "artifacts.jsonl").write_text("".join(json.dumps(a) + "\n" for a in self.artifacts))
        return subprocess.run(
            [sys.executable, str(COLLECTOR), str(RUN_ID), self.slug, "--receipts-dir", str(self.receipts)],
            env=self.env, text=True, capture_output=True, check=False)

    def calls(self) -> list[list[str]]:
        path = self.state / "calls.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def written(self) -> list[Path]:
        return sorted(self.receipts.glob("*.json")) if self.receipts.exists() else []


def _entries(stdout: str) -> list[dict]:
    body = "\n".join(line for line in stdout.splitlines() if not line.startswith("#"))
    return tomllib.loads(f"cutover_targets = [\n{body}\n]")["cutover_targets"]


@pytest.mark.parametrize("arm64", [False, True], ids=["amd64-only", "with-arm64-twin"])
def test_collects_an_authenticated_receipt(tmp_path, arm64):
    variant, flavor = _flavor(arm64)
    fake = Fake(tmp_path, variant, flavor)
    result = fake.collect()
    assert result.returncode == 0, result.stderr

    [path] = fake.written()
    data = path.read_bytes()
    evidence = RECEIPT.digest(data)
    assert path.name == evidence.removeprefix("sha256:") + ".json"
    assert data == (fake.state / "artifacts" / f"qualification-receipt-{fake.slug}-run{RUN_ID}-a1"
                    / "receipt.json").read_bytes()

    entries = _entries(result.stdout)
    platforms = ["linux/amd64", "linux/arm64"] if arm64 else ["linux/amd64"]
    assert [e["platform"] for e in entries] == platforms
    for entry in entries:
        assert (entry["variant"], entry["flavor"], entry["evidence"]) == (variant, flavor, evidence)
        POLICY.check_receipt(entry, fake.receipts)

    verify = next(c for c in fake.calls() if c[:2] == ["attestation", "verify"])
    for flag, value in (("--repo", "tuna-os/iso-builder"),
                        ("--signer-workflow", "tuna-os/iso-builder/.github/workflows/ci.yml"),
                        ("--source-ref", "refs/heads/main"), ("--source-digest", SHA)):
        assert verify[verify.index(flag) + 1] == value
    assert verify[verify.index("--bundle") + 1].endswith("bundle.jsonl")


def test_uses_the_newest_attempt(tmp_path):
    variant, flavor = _flavor(False)
    fake = Fake(tmp_path, variant, flavor)
    newer = fake.publish(_receipt(variant, flavor, attempt=2), attempt=2)
    result = fake.collect()
    assert result.returncode == 0, result.stderr
    assert [p.read_bytes() for p in fake.written()] == [newer]


def _refuse(fake: Fake) -> None:
    result = fake.collect()
    assert result.returncode == 1
    assert result.stdout == ""
    assert fake.written() == []


@pytest.mark.parametrize("field, value", [
    ("head_branch", "feature"),
    ("event", "pull_request"),
    ("conclusion", "failure"),
    ("path", ".github/workflows/other.yml"),
    ("head_sha", "not-a-commit"),
])
def test_refuses_an_unqualified_run(tmp_path, field, value):
    fake = Fake(tmp_path, *_flavor(False))
    fake.run[field] = value
    _refuse(fake)


def test_refuses_a_fork_run(tmp_path):
    fake = Fake(tmp_path, *_flavor(False))
    fake.run["head_repository"] = {"full_name": "someone/iso-builder"}
    _refuse(fake)


def test_refuses_a_receipt_the_attestation_does_not_cover(tmp_path):
    fake = Fake(tmp_path, *_flavor(False))
    (fake.state / "attested-digest").write_text("0" * 64)
    _refuse(fake)


def test_refuses_an_attestation_from_another_run_attempt(tmp_path):
    fake = Fake(tmp_path, *_flavor(False))
    receipt_file = next((fake.state / "artifacts").glob("*/receipt.json"))
    fake.attest(receipt_file, 1, f"https://github.com/tuna-os/iso-builder/actions/runs/{RUN_ID}/attempts/2")
    _refuse(fake)


def test_refuses_a_missing_receipt_artifact(tmp_path):
    fake = Fake(tmp_path, *_flavor(False))
    fake.artifacts = [a for a in fake.artifacts if not a["name"].startswith("qualification-receipt-")]
    _refuse(fake)


def test_refuses_an_expired_receipt_artifact(tmp_path):
    fake = Fake(tmp_path, *_flavor(False))
    for artifact in fake.artifacts:
        artifact["expired"] = True
    _refuse(fake)


def test_refuses_a_receipt_whose_iso_artifact_is_not_in_the_run(tmp_path):
    fake = Fake(tmp_path, *_flavor(False))
    fake.artifacts = [a for a in fake.artifacts if not a["name"].startswith("iso-")]
    _refuse(fake)


@pytest.mark.parametrize("mutate", [
    pytest.param(lambda r: r["modes"]["luks"].update(gui_login=False), id="gui-login-false"),
    pytest.param(lambda r: r["modes"].pop("plain"), id="plain-missing"),
    pytest.param(lambda r: r["producer"].update(runId=RUN_ID + 1,
                                                isoArtifactName=r["producer"]["isoArtifactName"].replace(
                                                    str(RUN_ID), str(RUN_ID + 1))), id="other-run"),
    pytest.param(lambda r: r["producer"].update(sha="4" * 40), id="other-commit"),
    pytest.param(lambda r: r.update(qualification="diagnostic"), id="diagnostic"),
])
def test_refuses_an_invalid_receipt(tmp_path, mutate):
    variant, flavor = _flavor(False)
    fake = Fake(tmp_path, variant, flavor)
    receipt = _receipt(variant, flavor)
    receipt["producer"]["isoArtifactId"] = ISO_ARTIFACT_ID
    mutate(receipt)
    receipt_file = next((fake.state / "artifacts").glob("*/receipt.json"))
    receipt_file.write_bytes(RECEIPT.canonical(receipt))
    fake.attest(receipt_file, 1)
    _refuse(fake)


def test_refuses_a_flavor_tunaos_does_not_build(tmp_path):
    fake = Fake(tmp_path, "nonesuch", "gnome")
    _refuse(fake)
