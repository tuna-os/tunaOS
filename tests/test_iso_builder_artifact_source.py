"""The iso-builder-artifact source: a browser-built ISO through the strict harness.

Run 40241323712 in tuna-os/iso-builder retained a 9.4 GB browser-built ISO as
chunked GitHub artifacts. This source lets the current strict harness boot those
exact bytes. It is a diagnostic path: the browser catalog gate refuses the
target, so every output is labelled `diagnostic-unqualified`.

Two kinds of test, both against real code:

- the workflow file is parsed (source choice, inputs, ordering, labels, and that
  the strict policy steps are untouched);
- scripts/iso-builder-artifact-inputs.py runs on the real measurements and
  manifest of that run, with a sparse file of the real ISO size.

Falsification: dropping the overlay check, defaulting an identity to the ISO
hash, running the strict step before verification, or leaving an output
unlabelled each fails an assertion below.
"""

from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/iso-builder-artifact-inputs.py"
FIXTURES = ROOT / "tests/fixtures/iso-builder-artifact"
WORKFLOW = yaml.safe_load((ROOT / ".github/workflows/iso-e2e.yml").read_text())
ON = WORKFLOW.get(True, WORKFLOW.get("on"))
STEPS = WORKFLOW["jobs"]["e2e"]["steps"]
SOURCE = "iso-builder-artifact"

RUN_ID = "40241323712"
PRODUCER_SHA = "d14a830c7f9c0451c68dc82e79ec55df9bc2aac0"
EXPECTED = "sha256:dc792ede43f95f33761fdec33277c65adbaf8e43265443562ec64294aa81994c"
ISO_SIZE = 9437833216
INSTALLER = "sha256:33a3a05589b6a1d9f279ce77a8902a9d6843d85252b7a39d3aadfe37533c1dc5"


def norm(value) -> str:
    return " ".join(str(value).split())


def index(prefix: str) -> int:
    return next(i for i, s in enumerate(STEPS) if s.get("name", "").startswith(prefix))


def step(prefix: str) -> dict:
    return STEPS[index(prefix)]


# ---- workflow wiring ----------------------------------------------------------------


def test_source_choice_and_inputs_are_dispatch_only_and_optional_by_default():
    inputs = ON["workflow_dispatch"]["inputs"]
    assert SOURCE in inputs["source"]["options"] or any(o.startswith(SOURCE) for o in inputs["source"]["options"])
    assert inputs["source"]["default"] == "r2-latest"
    for name in ("iso_builder_run_id", "iso_builder_artifact", "iso_builder_evidence_artifact",
                 "iso_builder_attempt", "iso_builder_sha", "iso_expected_sha256", "qual_installer_digest"):
        assert inputs[name]["type"] == "string", name
        assert "iso-builder-artifact only" in inputs[name]["description"], name
    # Declared for workflow_call only so conditions can name them (and optional); no caller may select the
    # source, which test_strict_qualification_wiring pins, and a PR or the schedule passes no inputs.
    for name in ("iso_builder_run_id", "iso_builder_artifact", "iso_builder_evidence_artifact",
                 "iso_builder_sha", "iso_expected_sha256", "qual_installer_digest"):
        assert ON["workflow_call"]["inputs"][name]["required"] is False, name
    assert "pull_request" in ON and "inputs" not in ON["pull_request"]
    # No overlay or engine override exists: those come only from the retained evidence.
    assert "qual_overlay_digest" not in inputs and "qual_engine_digest" not in inputs


def test_every_source_step_is_gated_on_the_source_and_the_filter():
    for prefix in ("Check iso-builder run and artifact metadata", "Download iso-builder ISO chunks",
                   "Download iso-builder browser evidence", "Verify and reassemble the iso-builder ISO"):
        cond = norm(step(prefix)["if"])
        assert "inputs.source == 'iso-builder-artifact'" in cond, prefix
        assert "steps.filter.outputs.skip != 'true'" in cond, prefix
        assert "(diagnostic-unqualified)" in step(prefix)["name"], prefix


def test_order_inputs_then_downloads_then_verify_then_strict_then_label_then_collect():
    names = [s.get("name", "") for s in STEPS]
    order = [
        "Check iso-builder run and artifact metadata",
        "Download iso-builder ISO chunks",
        "Download iso-builder browser evidence",
        "Verify and reassemble the iso-builder ISO",
        "Run strict offline GUI qualification",
        "Label outputs diagnostic-unqualified",
        "Stage bounded strict diagnostics",
        "Collect evidence",
        "Report strict leg verdicts",
    ]
    positions = [next(i for i, n in enumerate(names) if n.startswith(p)) for p in order]
    assert positions == sorted(positions)
    assert len(set(positions)) == len(positions)


def test_downloads_are_cross_repo_with_the_default_token_and_pinned_action():
    for prefix, name_input, path in (("Download iso-builder ISO chunks", "iso_builder_artifact", "iso-builder-chunks"),
                                     ("Download iso-builder browser evidence", "iso_builder_evidence_artifact", "iso-builder-evidence")):
        s = step(prefix)
        assert s["uses"].startswith("actions/download-artifact@9000827ccba6bdab643e8b6fd33ac0654aef8333")
        w = s["with"]
        assert w["repository"] == "tuna-os/iso-builder"
        assert w["run-id"] == "${{ inputs.iso_builder_run_id }}"
        assert w["artifact-ids"] == "${{ fromJSON(steps.iso_builder_metadata.outputs.artifacts)[%d].id }}" % (
            0 if name_input == "iso_builder_artifact" else 1
        )
        assert w["path"] == path
        assert w["github-token"] == "${{ github.token }}"
        assert "secrets." not in yaml.safe_dump(s)
    assert WORKFLOW["permissions"]["actions"] == "read"
    metadata = step("Check iso-builder run and artifact metadata")
    assert metadata["id"] == "iso_builder_metadata"
    assert metadata["env"]["GH_TOKEN"] == "${{ github.token }}"
    assert "--run-metadata run.json" in metadata["run"]
    assert "--artifacts-metadata artifacts.json" in metadata["run"]


def test_verify_step_pins_the_helper_checks_the_hash_and_frees_the_chunks_before_the_guests():
    run = step("Verify and reassemble")["run"]
    assert "raw.githubusercontent.com/tuna-os/iso-builder/${PRODUCER_SHA}/scripts/retain-iso-artifact.py" in run
    assert "verify" in run and '--expected-sha256 "$EXPECTED_SHA256"' in run
    assert run.index("retain-iso-artifact.py verify") < run.index("rm -rf iso-builder-chunks") < run.index("iso-builder-artifact-inputs.py derive")
    assert "sha256sum --check --strict iso-e2e-out/media.sha256" in run
    assert "--out-label iso-e2e-out/diagnostic-unqualified.json" in run
    # Exactly one measurements file, or the run stops.
    assert "-eq 1" in run
    assert "QUAL_OVERLAY" not in run and "QUAL_ENGINE" not in run  # derived by the script, never by shell defaults


def test_strict_policy_steps_are_unchanged_by_the_new_source():
    strict = step("Run strict offline GUI qualification")
    cond = norm(strict["if"])
    assert "inputs.source == 'native-artifact'" in cond and "inputs.source == 'iso-builder-artifact'" in cond
    run = strict["run"]
    assert "--strict-offline-gui" in run and "--timeout 600" in run
    assert 'exit "$rc"' in run and "continue-on-error" not in strict
    assert strict["timeout-minutes"] == 60
    for forbidden in ("grub", "GRUB", "threshold", "--no-strict", "--published", "FISHERMAN_OVERRIDE", "TBOX_E2E_IMAGE",
                      "TUNAOS_PUBLISHED_STRICT", "sendkey", "vncdo"):
        assert forbidden not in run, forbidden
    assert "TUNAOS_QUAL_BROWSER_NAME,TUNAOS_QUAL_BROWSER_VERSION" in run
    # Readiness stays the default and is excluded for both strict sources.
    readiness = norm(step("Run readiness e2e")["if"])
    assert "inputs.source != 'native-artifact'" in readiness and "inputs.source != 'iso-builder-artifact'" in readiness
    assert "--strict-offline-gui" not in step("Run readiness e2e")["run"]
    # The native-only resolver, fetch and validator never run for this source.
    assert "iso-builder-artifact" not in norm(step("Resolve immutable ISO qualification inputs")["if"])
    assert "iso-builder-artifact" not in norm(step("Fetch exact native ISO artifact")["if"])
    assert "inputs.source != 'iso-builder-artifact'" in norm(step("Validate strict qualification evidence")["if"])


def test_the_per_leg_verdict_reporter_runs_for_the_source_even_after_a_failed_leg():
    verdict = step("Report strict leg verdicts")
    cond = norm(verdict["if"])
    assert cond.startswith("always()") and "inputs.source == 'iso-builder-artifact'" in cond
    assert "summarize-strict-legs.py iso-e2e-out" in verdict["run"]
    # A failed leg still fails the job.
    assert "steps.strict.outputs.rc || steps.e2e.outputs.rc" in norm(step("Fail on e2e error")["if"])


def test_outputs_are_labelled_and_the_evidence_file_cannot_be_read_as_a_qualification():
    label = step("Label outputs diagnostic-unqualified")
    assert norm(label["if"]).startswith("always()") and "inputs.source == 'iso-builder-artifact'" in norm(label["if"])
    assert "mv iso-e2e-out/qualification-evidence.json iso-e2e-out/diagnostic-unqualified-evidence.json" in label["run"]
    upload = step("Upload artifacts")
    assert "-diagnostic-unqualified" in upload["with"]["name"] and "inputs.source == 'iso-builder-artifact'" in upload["with"]["name"]
    for path in ("iso-e2e-out/diagnostic-unqualified.json", "iso-e2e-out/diagnostic-unqualified-evidence.json",
                 "iso-e2e-out/iso-builder-build-measurements.json", "iso-e2e-out/iso-builder-artifact-manifest.json"):
        assert path in upload["with"]["path"], path
    # No ISO or chunk is ever uploaded.
    assert ".iso" not in upload["with"]["path"].replace("diagnostic", "")
    assert "iso-builder-chunks" not in upload["with"]["path"]


def test_the_job_budget_covers_downloads_verification_and_the_strict_step():
    timeout = norm(WORKFLOWS_JOB()["timeout-minutes"])
    assert "inputs.source == 'iso-builder-artifact' && 160" in timeout
    assert timeout.endswith("&& 90 || 30)) }}")  # the default path keeps its budget
    budget = sum(step(p)["timeout-minutes"] for p in (
        "Download iso-builder ISO chunks", "Download iso-builder browser evidence",
        "Verify and reassemble", "Run strict offline GUI qualification"))
    assert budget <= 160 - 10  # leaves room for setup, diagnostics and evidence steps


def WORKFLOWS_JOB() -> dict:
    return WORKFLOW["jobs"]["e2e"]


# ---- the script, on the real measurements of run 40241323712 -----------------------


@pytest.fixture
def case(tmp_path):
    iso = tmp_path / "skipjack-gnome.iso"
    with iso.open("wb") as f:
        f.truncate(ISO_SIZE)  # sparse: the real size, no disk used
    measurements = json.loads((FIXTURES / "build-measurements.json").read_text())
    manifest = json.loads((FIXTURES / "manifest.json").read_text())
    return tmp_path, iso, measurements, manifest


def derive(tmp_path, iso, measurements, manifest, **over):
    (tmp_path / "m.json").write_text(json.dumps(measurements))
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    args = {
        "run-id": RUN_ID, "artifact": f"iso-skipjack-gnome-run{RUN_ID}-a1",
        "evidence-artifact": f"browser-evidence-skipjack-gnome-run{RUN_ID}-a1",
        "producer-sha": PRODUCER_SHA, "expected-sha256": EXPECTED, "installer-digest": INSTALLER,
        "variant": "skipjack", "flavor": "gnome", "platform": "linux/amd64",
    }
    args.update({k.replace("_", "-"): v for k, v in over.items()})
    cmd = [sys.executable, str(SCRIPT), "derive", "--iso", str(iso), "--measurements", str(tmp_path / "m.json"),
           "--manifest", str(tmp_path / "manifest.json"), "--out-env", str(tmp_path / "env"), "--out-label", str(tmp_path / "label.json")]
    for k, v in args.items():
        cmd += [f"--{k}", v]
    return subprocess.run(cmd, text=True, capture_output=True)


def test_real_run_yields_the_measured_identities_and_never_the_iso_hash(case):
    tmp_path, iso, m, mf = case
    r = derive(tmp_path, iso, m, mf)
    assert r.returncode == 0, r.stderr
    env = dict(line.split("=", 1) for line in (tmp_path / "env").read_text().splitlines())
    assert env == {
        "TUNAOS_QUAL_MEDIA_DIGEST": EXPECTED,
        "TUNAOS_QUAL_SOURCE_DIGEST": "sha256:5f2ac8b1f6fd33c7314199bc0af4cdf362ea2ed9fefe952c668e0343148c7fa9",
        "TUNAOS_QUAL_OVERLAY_DIGEST": "sha256:c86293fb3e9d65a91261cf52fe34bde9e9f0aa684046eaf03e022eb3688fd328",
        "TUNAOS_QUAL_ENGINE_DIGEST": "sha256:9c047c41d3304ea6d76507cb9c15b223c1649a5ef9acb0b6d1b48c8751fcd606",
        "TUNAOS_QUAL_PLATFORM": "linux/amd64",
        "TUNAOS_QUAL_BROWSER_NAME": "HeadlessChrome",
        "TUNAOS_QUAL_BROWSER_VERSION": "156.0.8078.4",
        "STRICT_PUBLISHED_MEDIA": "1",
        "TUNAOS_QUAL_DIAGNOSTIC": "diagnostic-unqualified",
        "TUNAOS_QUAL_DIAGNOSTIC": "diagnostic-unqualified",
    }
    for key in ("TUNAOS_QUAL_OVERLAY_DIGEST", "TUNAOS_QUAL_ENGINE_DIGEST", "TUNAOS_QUAL_SOURCE_DIGEST"):
        assert env[key] != EXPECTED


def test_label_file_says_diagnostic_unqualified_and_records_where_each_identity_came_from(case):
    tmp_path, iso, m, mf = case
    assert derive(tmp_path, iso, m, mf).returncode == 0
    label = json.loads((tmp_path / "label.json").read_text())
    assert label["qualification"] == "diagnostic-unqualified" and label["label"] == "diagnostic, unqualified build"
    assert "qualified" not in {label["qualification"]}
    assert label["producer"] == {"repository": "tuna-os/iso-builder", "runId": RUN_ID, "runAttempt": "1", "sha": PRODUCER_SHA}
    ids = label["identities"]
    assert ids["overlay"]["origin"] == "engineBuildResult.observedInputs.overlay.manifestDigest"
    assert ids["overlay"]["baseAnnotationMatched"] is False  # the real run reported false; surfaced, not hidden
    assert ids["installer"]["value"] is None
    assert ids["installerExpectation"]["value"] == INSTALLER
    assert "operator supplied" in ids["installerExpectation"]["origin"]
    assert "not the browser's" in label["browserResourceProfile"]


def test_without_an_installer_digest_the_env_omits_it_and_the_label_says_so(case):
    tmp_path, iso, m, mf = case
    assert derive(tmp_path, iso, m, mf, installer_digest="").returncode == 0
    assert "INSTALLER" not in (tmp_path / "env").read_text()
    assert json.loads((tmp_path / "label.json").read_text())["identities"]["installer"]["value"] is None


def mutate(path, value):
    def apply(doc):
        node = doc
        for key in path[:-1]:
            node = node[key]
        if value is DELETE:
            del node[path[-1]]
        else:
            node[path[-1]] = value
        return doc
    return apply


DELETE = object()
BAD = "sha256:" + "A" * 64

MEASUREMENT_FAILURES = [
    ("overlay digest missing", mutate(["engineBuildResult", "observedInputs", "overlay", "manifestDigest"], DELETE), "overlay.manifestDigest"),
    ("overlay digest malformed", mutate(["engineBuildResult", "observedInputs", "overlay", "manifestDigest"], BAD), "overlay.manifestDigest"),
    ("overlay not applied", mutate(["engineBuildResult", "observedInputs", "overlay", "status"], "absent"), "not 'applied'"),
    ("overlay equals the ISO hash", mutate(["engineBuildResult", "observedInputs", "overlay", "manifestDigest"], EXPECTED), "placeholder"),
    ("engine equals the ISO hash", mutate(["loadedWasm", "sha256"], EXPECTED), "placeholder"),
    ("no engine build result", mutate(["engineBuildResult"], None), "engineBuildResult"),
    ("source digest missing", mutate(["engineBuildResult", "observedInputs", "source", "manifestDigest"], DELETE), "source.manifestDigest"),
    ("wasm hash missing", mutate(["loadedWasm", "sha256"], DELETE), "loadedWasm.sha256"),
    ("bytes written differ", mutate(["engineBuildResult", "bytesWritten"], 1), "bytesWritten"),
    ("measured ISO hash differs", mutate(["iso", "sha256"], "sha256:" + "b" * 64), "browser measurement"),
    ("measured ISO size differs", mutate(["iso", "sizeBytes"], 1), "browser measurement"),
    ("not labelled diagnostic-unqualified", mutate(["qualification"], "not-assessed"), "not 'diagnostic-unqualified'"),
    ("claims qualified", mutate(["qualification"], "qualified"), "not 'diagnostic-unqualified'"),
    ("label block missing", mutate(["diagnosticUnqualified"], DELETE), "label block"),
    ("other image", mutate(["diagnosticUnqualified", "image"], "tuna-os/yellowfin:gnome"), "not tuna-os/skipjack:gnome"),
    ("other platform", mutate(["diagnosticUnqualified", "platform"], "linux/arm64"), "platform"),
    ("browser unparseable", mutate(["browser", "product"], "Netscape"), "Chromium product"),
]


@pytest.mark.parametrize("name,change,message", MEASUREMENT_FAILURES, ids=[c[0] for c in MEASUREMENT_FAILURES])
def test_measurement_problems_fail_closed_before_any_guest_boots(case, name, change, message):
    tmp_path, iso, m, mf = case
    r = derive(tmp_path, iso, change(copy.deepcopy(m)), mf)
    assert r.returncode != 0 and message in r.stderr, r.stderr
    assert not (tmp_path / "env").exists() and not (tmp_path / "label.json").exists()


MANIFEST_FAILURES = [
    ("other run", mutate(["producer", "runId"], "1"), "producer run or commit"),
    ("other commit", mutate(["producer", "sha"], "0" * 40), "producer run or commit"),
    ("other repository", mutate(["producer", "repository"], "evil/iso-builder"), "produced by"),
    ("qualified label", mutate(["qualification"], "qualified"), "not 'diagnostic-unqualified'"),
    ("other ISO hash", mutate(["iso", "sha256"], "sha256:" + "c" * 64), "manifest ISO identity"),
    ("other kind", mutate(["kind"], "something-else"), "candidate-iso-artifact-manifest"),
]


@pytest.mark.parametrize("name,change,message", MANIFEST_FAILURES, ids=[c[0] for c in MANIFEST_FAILURES])
def test_manifest_problems_fail_closed(case, name, change, message):
    tmp_path, iso, m, mf = case
    r = derive(tmp_path, iso, m, change(copy.deepcopy(mf)))
    assert r.returncode != 0 and message in r.stderr, r.stderr


def test_a_reassembled_file_of_another_size_or_a_different_expected_hash_is_refused(case):
    tmp_path, iso, m, mf = case
    with iso.open("r+b") as f:
        f.truncate(ISO_SIZE - 1)
    assert derive(tmp_path, iso, m, mf).returncode != 0
    with iso.open("r+b") as f:
        f.truncate(ISO_SIZE)
    r = derive(tmp_path, iso, m, mf, expected_sha256="sha256:" + "d" * 64)
    assert r.returncode != 0 and "differs" in r.stderr
    assert derive(tmp_path, tmp_path / "missing.iso", m, mf).returncode != 0


def check(**over):
    args = {"run-id": RUN_ID, "artifact": "a", "evidence-artifact": "b", "producer-sha": PRODUCER_SHA,
            "expected-sha256": EXPECTED, "installer-digest": "", "attempt": "1"}
    args.update({k.replace("_", "-"): v for k, v in over.items()})
    cmd = [sys.executable, str(SCRIPT), "check-inputs"]
    for k, v in args.items():
        cmd += [f"--{k}", v]
    return subprocess.run(cmd, text=True, capture_output=True)


def test_dispatch_inputs_are_validated_before_any_download():
    assert check().returncode == 0
    for bad in (dict(run_id="abc"), dict(run_id=""), dict(artifact="../x"), dict(artifact="a b"),
                dict(evidence_artifact="a"), dict(producer_sha="main"), dict(producer_sha="D14A830C" + "0" * 32),
                dict(expected_sha256="abc"), dict(expected_sha256="sha256:" + "A" * 64),
                dict(installer_digest="sha256:short")):
        assert check(**bad).returncode != 0, bad
    assert check(installer_digest=INSTALLER).returncode == 0
def verify_metadata(tmp_path, run=None, artifacts=None):
    names = [f"iso-skipjack-gnome-run{RUN_ID}-a1",
             f"browser-evidence-skipjack-gnome-run{RUN_ID}-a1"]
    run = run or {"id": int(RUN_ID), "repository": {"id": 1, "full_name": "tuna-os/iso-builder"},
                  "head_repository": {"id": 1, "full_name": "tuna-os/iso-builder"},
                  "path": ".github/workflows/ci.yml", "head_sha": PRODUCER_SHA, "run_attempt": 1,
                  "status": "completed", "conclusion": "failure"}
    artifacts = artifacts or {"artifacts": [
        {"id": 10, "name": names[0], "digest": "sha256:" + "a" * 64, "expired": False,
         "workflow_run": {"id": int(RUN_ID), "repository_id": 1, "head_repository_id": 1, "head_sha": PRODUCER_SHA}},
        {"id": 11, "name": names[1], "digest": "sha256:" + "b" * 64, "expired": False,
         "workflow_run": {"id": int(RUN_ID), "repository_id": 1, "head_repository_id": 1, "head_sha": PRODUCER_SHA}},
    ]}
    (tmp_path / "run.json").write_text(json.dumps(run))
    (tmp_path / "artifacts.json").write_text(json.dumps(artifacts))
    cmd = [sys.executable, str(SCRIPT), "verify-metadata", "--run-id", RUN_ID, "--attempt", "1",
           "--artifact", names[0], "--evidence-artifact", names[1], "--producer-sha", PRODUCER_SHA,
           "--run-metadata", str(tmp_path / "run.json"), "--artifacts-metadata", str(tmp_path / "artifacts.json"),
           "--out", str(tmp_path / "verified.json"), "--output", str(tmp_path / "output")]
    return subprocess.run(cmd, text=True, capture_output=True)


def test_actual_metadata_accepts_same_run_attempt_even_when_guest_run_failed(tmp_path):
    assert verify_metadata(tmp_path).returncode == 0
    data = json.loads((tmp_path / "verified.json").read_text())
    assert [a["id"] for a in data["artifacts"]] == [10, 11]


@pytest.mark.parametrize("field,value", [
    ("repository", {"full_name": "attacker/repo"}),
    ("head_repository", {"full_name": "attacker/repo"}),
    ("path", ".github/workflows/other.yml"),
    ("head_sha", "0" * 40),
    ("run_attempt", 2),
    ("status", "in_progress"),
])
def test_wrong_producer_run_metadata_fails_before_artifact_use(tmp_path, field, value):
    run = {"id": int(RUN_ID), "repository": {"id": 1, "full_name": "tuna-os/iso-builder"},
           "head_repository": {"id": 1, "full_name": "tuna-os/iso-builder"},
           "path": ".github/workflows/ci.yml", "head_sha": PRODUCER_SHA, "run_attempt": 1, "status": "completed"}
    run[field] = value
    assert verify_metadata(tmp_path, run=run).returncode != 0
    assert not (tmp_path / "verified.json").exists()


@pytest.mark.parametrize("field,value", [
    ("head_sha", "0" * 40), ("name", f"iso-skipjack-gnome-run{RUN_ID}-a2"),
    ("workflow_run_id", 99), ("repository_id", 99), ("head_repository_id", 99),
])
def test_wrong_artifact_metadata_fails_before_artifact_use(tmp_path, field, value):
    artifacts = {"artifacts": [
        {"id": 10, "name": f"iso-skipjack-gnome-run{RUN_ID}-a1", "digest": "sha256:" + "a" * 64,
         "expired": False, "workflow_run": {"id": int(RUN_ID), "repository_id": 1, "head_repository_id": 1, "head_sha": PRODUCER_SHA}},
        {"id": 11, "name": f"browser-evidence-skipjack-gnome-run{RUN_ID}-a1", "digest": "sha256:" + "b" * 64,
         "expired": False, "workflow_run": {"id": int(RUN_ID), "repository_id": 1, "head_repository_id": 1, "head_sha": PRODUCER_SHA}},
    ]}
    if field == "name":
        artifacts["artifacts"][0]["name"] = value
    elif field == "head_sha":
        artifacts["artifacts"][0]["workflow_run"][field] = value
    else:
        artifacts["artifacts"][0]["workflow_run"][{"workflow_run_id": "id"}.get(field, field)] = value
    assert verify_metadata(tmp_path, artifacts=artifacts).returncode != 0
    assert not (tmp_path / "verified.json").exists()


def test_operator_installer_expectation_never_satisfies_frontend_identity(case):
    tmp_path, iso, m, mf = case
    assert derive(tmp_path, iso, m, mf, installer_digest=INSTALLER).returncode == 0
    env = (tmp_path / "env").read_text()
    label = json.loads((tmp_path / "label.json").read_text())["identities"]
    assert "TUNAOS_QUAL_INSTALLER_DIGEST" not in env
    assert label["installer"]["value"] is None
    assert label["installerExpectation"]["value"] == INSTALLER
