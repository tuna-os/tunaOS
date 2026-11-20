"""tunaOS#4831: every index digest Promote publishes carries a signature.

Build Marlin run 44720498099 (2026-11-20) published ``marlin:tuna`` as
``sha256:b2b4e5b9...`` with no signature. In job 136371550103, Promote copied
every tag and then failed in ``Sign the promoted index`` with ``signing
digest: user declined the prompt``. The ``sign`` job sets ``COSIGN_YES``. The
``tag-image`` job did not, and cosign v3 reads the confirmation from a stdin
that answers no. Build Bonito run 44730012078 failed in the same way. In the
same run, the Manifest job read back ``:tuna-testing``. Only Promote writes
that tag, so the read-back returned the previous promotion
(``sha256:f99f966b...``). Sign signed that index again, and the candidate
(``sha256:cc3ed762...``) remained unsigned.

These tests run the real workflow steps against stub ``skopeo``, ``podman``
and ``cosign``. The stub cosign prompts like cosign v3 and declines when the
step does not set COSIGN_YES. The tests check four things:

* the Manifest job outputs the digest of the ``-candidate`` tag it pushed;
* Promote records every ``<repo>@<digest>`` that its copies write;
* the signing step signs and verifies each of those references without a
  prompt;
* in every workflow, a ``cosign`` upload runs without a prompt and cannot
  fail with the step still green.

Falsification: behavioural — on the tree that shipped the incident, the
Promote signing step gets no COSIGN_YES, the stub cosign declines, and
``test_promote_signs_and_verifies_every_published_ref`` fails. The Manifest
step outputs the stub's ``-testing`` (previous) digest, and
``test_manifest_outputs_the_candidate_it_pushed`` fails. Structural — remove
``COSIGN_YES`` from any job that runs ``cosign sign`` and
``test_every_cosign_upload_is_non_interactive`` names that job.
"""

from __future__ import annotations

import os
import re
import subprocess
import textwrap
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = sorted((ROOT / ".github" / "workflows").glob("*.y*ml"))
REUSABLE = ROOT / ".github/workflows/reusable-build-image.yml"

PREVIOUS = "sha256:" + "0" * 64
LOCAL = "sha256:" + "1" * 64
CANDIDATE = "sha256:" + "2" * 64
PROMOTED = "sha256:" + "3" * 64
ALIAS_PROMOTED = "sha256:" + "4" * 64
IDENTITY = "https://github.com/tuna-os/tunaOS/.github/workflows/reusable-build-image.yml@refs/heads/main"

COSIGN_UPLOAD = re.compile(r"\bcosign\s+(sign|sign-blob|attest)\b")


def _workflow(path: Path = REUSABLE) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _step(job: dict, name: str) -> dict:
    return next(s for s in job["steps"] if s.get("name") == name)


def _host_env() -> dict[str, str]:
    """The test host's env, minus anything that would answer cosign's prompt."""
    return {k: v for k, v in os.environ.items() if k != "COSIGN_YES"}


def _literal_env(*blocks: dict | None) -> dict[str, str]:
    """The env a step really gets, minus the ${{ }} values a test must supply."""
    env: dict[str, str] = {}
    for block in blocks:
        for key, value in (block or {}).items():
            if "${{" not in str(value):
                env[key] = str(value)
    return env


def _stub(bindir: Path, name: str, body: str) -> None:
    bindir.mkdir(parents=True, exist_ok=True)
    path = bindir / name
    path.write_text("#!/usr/bin/env bash\n" + textwrap.dedent(body))
    path.chmod(0o755)


def _outputs(text: str) -> dict[str, str]:
    """Parse $GITHUB_OUTPUT, including name<<DELIM multi-line values."""
    out: dict[str, str] = {}
    lines = iter(text.splitlines())
    for line in lines:
        if "<<" in line and "=" not in line.split("<<", 1)[0]:
            name, delim = line.split("<<", 1)
            value = []
            for body in lines:
                if body == delim:
                    break
                value.append(body)
            out[name] = "\n".join(value)
        elif "=" in line:
            name, value = line.split("=", 1)
            out[name] = value
    return out


# ── Manifest: Sign gets the candidate this run pushed ────────────────────────

def test_manifest_outputs_the_candidate_it_pushed(tmp_path):
    step = _step(_workflow()["jobs"]["manifest"], "Push Manifest")
    bindir = tmp_path / "bin"
    _stub(bindir, "podman", f"""\
        if [[ "$1 $2" == "manifest push" ]]; then
          printf '%s' '{LOCAL}' > /tmp/digestfile
          exit 0
        fi
        exit 99
    """)
    # :tuna-testing still names the previous promotion until Promote runs.
    _stub(bindir, "skopeo", f"""\
        case "${{@: -1}}" in
          *:tuna-candidate) echo '{CANDIDATE}' ;;
          *:tuna-testing) echo '{PREVIOUS}' ;;
          *) exit 1 ;;
        esac
    """)
    output = tmp_path / "github_output"
    env = os.environ | {
        "PATH": f"{bindir}:{os.environ['PATH']}",
        "MANIFEST": "m", "TAGS": "tuna", "DEFAULT_TAG": "tuna",
        "IMAGE_REGISTRY": "ghcr.io/tuna-os", "IMAGE_NAME": "marlin",
        "GITHUB_OUTPUT": str(output),
    }
    digestfile = Path("/tmp/digestfile")
    digestfile.unlink(missing_ok=True)
    try:
        proc = subprocess.run(["bash", "-e", "-c", step["run"]], env=env,
                              capture_output=True, text=True, timeout=60)
    finally:
        digestfile.unlink(missing_ok=True)
    assert proc.returncode == 0, proc.stderr
    assert _outputs(output.read_text())["DIGEST"] == CANDIDATE, (
        "Sign would sign a digest other than the -candidate index this run pushed"
    )


# ── Promote: record every copy, then sign and verify each one ────────────────

def _run_promote(tmp_path: Path) -> dict[str, str]:
    job = _workflow()["jobs"]["tag-image"]
    step = _step(job, "Pull Image and Apply Tags")
    bindir = tmp_path / "bin"
    _stub(bindir, "sudo", 'exec "$@"\n')
    # Each repository gets its own rewritten index; the testing tag of the
    # image repository is made to differ too, so every copy must be recorded.
    _stub(bindir, "skopeo", f"""\
        digestfile="" dest="${{@: -1}}"
        while (($#)); do
          [[ "$1" == --digestfile ]] && digestfile="$2"
          shift
        done
        case "$dest" in
          docker://ghcr.io/tuna-os/tuna:*) d='{ALIAS_PROMOTED}' ;;
          docker://ghcr.io/tuna-os/marlin:tuna-testing) d='{PREVIOUS}' ;;
          *) d='{PROMOTED}' ;;
        esac
        [[ -n "$digestfile" ]] && printf '%s' "$d" > "$digestfile"
        exit 0
    """)
    output = tmp_path / "github_output"
    output.write_text("")
    env = os.environ | _literal_env(job.get("env"), step.get("env")) | {
        "PATH": f"{bindir}:{os.environ['PATH']}",
        "GITHUB_OUTPUT": str(output),
        "IMAGE_NAME": "marlin", "IMAGE_ALIASES": "tuna", "IMAGE_REGISTRY": "ghcr.io/tuna-os",
        "DEFAULT_TAG": "tuna", "MAJOR_VERSION": "", "ALL_PLATFORMS_BUILT": "true",
        "INPUT_PLATFORMS": "linux/amd64", "MAX_RETRIES": "1",
    }
    proc = subprocess.run(["bash", "-e", "-c", step["run"]], env=env,
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    return _outputs(output.read_text())


def test_promote_records_every_index_it_wrote(tmp_path):
    outputs = _run_promote(tmp_path)
    assert outputs["index_digest"] == PROMOTED
    assert sorted(outputs["published_refs"].splitlines()) == sorted([
        f"ghcr.io/tuna-os/marlin@{PROMOTED}",
        f"ghcr.io/tuna-os/marlin@{PREVIOUS}",
        f"ghcr.io/tuna-os/tuna@{ALIAS_PROMOTED}",
    ])


COSIGN_V3 = """\
    echo "cosign $*" >> "$STUB_DIR/calls"
    case "$1" in
      login) cat >/dev/null; exit 0 ;;
      sign)
        ref="${@: -1}" yes=0
        for a in "$@"; do [[ "$a" == --yes || "$a" == -y || "$a" == --yes=true ]] && yes=1; done
        [[ "${COSIGN_YES:-}" == true || "${COSIGN_YES:-}" == 1 ]] && yes=1
        if ((!yes)); then
          printf 'Are you sure you would like to continue? [y/N] '
          read -r answer || answer=""
          if [[ "$answer" != [yY]* ]]; then
            echo "Error: signing [$ref]: signing digest: user declined the prompt" >&2
            exit 1
          fi
        fi
        echo "$ref" >> "$STUB_DIR/signed"
        ;;
      verify)
        ref="$2"
        args=" $* "
        [[ "$args" == *" --certificate-identity $EXPECT_IDENTITY "* ]] || { echo "Error: none of the expected identities matched" >&2; exit 1; }
        grep -qxF "$ref" "$STUB_DIR/signed" 2>/dev/null || { echo "Error: no signatures found" >&2; exit 1; }
        ;;
      *) exit 99 ;;
    esac
"""


def test_promote_signs_and_verifies_every_published_ref(tmp_path):
    published = _run_promote(tmp_path / "promote")["published_refs"]
    job = _workflow()["jobs"]["tag-image"]
    step = _step(job, "Sign the promoted index")
    assert not step.get("continue-on-error"), "a failed signature must fail Promote"
    bindir = tmp_path / "bin"
    _stub(bindir, "cosign", COSIGN_V3)
    summary = tmp_path / "summary"
    env = _host_env() | _literal_env(job.get("env"), step.get("env")) | {
        "PATH": f"{bindir}:{os.environ['PATH']}",
        "STUB_DIR": str(tmp_path),
        "EXPECT_IDENTITY": IDENTITY,
        "GITHUB_TOKEN": "t", "GHCR_ACTOR": "a",
        "GITHUB_REPOSITORY": "tuna-os/tunaOS", "GITHUB_REF": "refs/heads/main",
        "GITHUB_WORKSPACE": str(ROOT), "GITHUB_STEP_SUMMARY": str(summary),
        "PUBLISHED_REFS": published,
        "SIGN_DEADLINE_MINUTES": "1",
    }
    proc = subprocess.run(["bash", "-e", "-c", step["run"]], env=env, stdin=subprocess.DEVNULL,
                          capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    signed = (tmp_path / "signed").read_text().split()
    assert sorted(signed) == sorted(published.splitlines())
    calls = (tmp_path / "calls").read_text()
    for ref in published.splitlines():
        assert f"cosign verify {ref} --certificate-identity {IDENTITY}" in calls, calls


def test_promote_fails_when_promotion_recorded_nothing(tmp_path):
    job = _workflow()["jobs"]["tag-image"]
    step = _step(job, "Sign the promoted index")
    bindir = tmp_path / "bin"
    _stub(bindir, "cosign", COSIGN_V3)
    env = _host_env() | _literal_env(job.get("env"), step.get("env")) | {
        "PATH": f"{bindir}:{os.environ['PATH']}", "STUB_DIR": str(tmp_path),
        "PUBLISHED_REFS": "", "GITHUB_WORKSPACE": str(ROOT),
    }
    proc = subprocess.run(["bash", "-e", "-c", step["run"]], env=env, stdin=subprocess.DEVNULL,
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode != 0
    assert not (tmp_path / "signed").exists()


def test_promote_signs_after_its_last_copy():
    steps = _workflow()["jobs"]["tag-image"]["steps"]
    copies = [i for i, s in enumerate(steps) if "skopeo copy" in s.get("run", "")]
    signs = [i for i, s in enumerate(steps) if COSIGN_UPLOAD.search(s.get("run", ""))]
    assert copies and signs and max(copies) < min(signs), (
        "Promote writes a tag after its signing step, so that tag's index is unsigned"
    )
    sign = steps[min(signs)]
    assert "steps.tag.outputs.published_refs" in str(sign.get("env", {})), (
        "Promote's signing step must sign the references the copies recorded"
    )


# ── Every workflow: a cosign upload never waits on a prompt ──────────────────

def _uploads():
    for path in WORKFLOWS:
        for job_id, job in (_workflow(path).get("jobs") or {}).items():
            for step in job.get("steps") or []:
                code = "\n".join(line for line in step.get("run", "").splitlines()
                                 if not line.strip().startswith("#"))
                if COSIGN_UPLOAD.search(code):
                    yield pytest.param(job, step, code, id=f"{path.name}:{job_id}:{step.get('name')}")


@pytest.mark.parametrize(("job", "step", "code"), list(_uploads()))
def test_every_cosign_upload_is_non_interactive(job, step, code):
    env = _literal_env(job.get("env"), step.get("env"))
    yes = env.get("COSIGN_YES", "").lower() in {"true", "1"} or re.search(r"\s--yes\b|\s-y\b", code)
    assert yes, (
        "cosign v3 asks for confirmation before it uploads to the transparency "
        "log and a runner's stdin answers no; set COSIGN_YES: \"true\" on the "
        "job or step (tunaOS#4831)"
    )
    assert not step.get("continue-on-error"), (
        "a signing step that cannot fail its job publishes unsigned images green"
    )
