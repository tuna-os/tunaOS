"""Credential selection for non-owner publish destinations (#3801, RFC 016).

The owner path (ghcr.io/<owner>) keeps the repository GITHUB_TOKEN. Any other
destination needs TUNAOS_PUBLISH_USERNAME, TUNAOS_PUBLISH_PASSWORD and a
TUNAOS_PUBLISH_SCOPE variable equal to that destination. Missing, partial or
mismatched credentials fail; nothing falls back to ghcr.io/<owner>. All tools
here are credential-free command stubs, and no workflow is wired yet.
"""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import subprocess
import sys

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from lib import publish_credentials as creds  # noqa: E402

SPEC = importlib.util.spec_from_file_location("publish_credentials_config", ROOT / "scripts/lib/tunaos_config.py")
config = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(config)

SECRET_USER = "acme+ci-robot"
SECRET_PASS = "s3cr3t-Value-0123456789"


def pick(destination, *, owner="tuna-os", event="schedule", publish=True, scope="",
         username=False, password=False):
    return creds.select(destination, owner=owner, event=event, publish=publish, scope=scope,
                        has_username=username, has_password=password)


def refused(code, destination, **kwargs):
    with pytest.raises(creds.CredentialError) as info:
        pick(destination, **kwargs)
    assert info.value.code == code
    assert "\n" not in str(info.value) and "\r" not in str(info.value)
    return str(info.value)


# ── Stock owner path ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("event", sorted(creds.TRUSTED_EVENTS))
def test_stock_owner_path_uses_github_token(event):
    selection = pick("ghcr.io/tuna-os", event=event)
    assert (selection.mode, selection.scope) == ("github-token", "ghcr.io/tuna-os")


def test_owner_path_ignores_secrets_without_a_scope():
    # TunaOS has no TUNAOS_PUBLISH_* secrets; if one appeared, the owner path
    # would still use GITHUB_TOKEN exactly as it does today.
    assert pick("ghcr.io/tuna-os", username=True, password=True).mode == "github-token"
    assert pick("ghcr.io/tuna-os", username=True).mode == "github-token"


def test_owner_case_and_sub_namespace_stay_on_the_owner_path():
    # The workflow default is format('ghcr.io/{0}', github.repository_owner).
    assert pick("ghcr.io/Acme-Fork", owner="Acme-Fork").scope == "ghcr.io/acme-fork"
    assert pick("ghcr.io/acme-fork/os", owner="Acme-Fork").mode == "github-token"


def test_stock_resolved_destination_selects_github_token(tmp_path):
    path = tmp_path / "build-config.yml"
    path.write_text(config.render(config.load()), encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if k not in ("IMAGE_REGISTRY", "REPO_ORGANIZATION")}
    env["GITHUB_REPOSITORY_OWNER"] = "tuna-os"
    out = subprocess.run(
        ["bash", "-c", 'source scripts/lib/publish-destination.sh; tunaos_publish_destination "$1"', "_", str(path)],
        cwd=ROOT, env=env, text=True, capture_output=True, check=True).stdout.split()
    assert pick("/".join(out)).mode == "github-token"


def test_scope_equal_to_owner_destination_is_allowed():
    assert pick("ghcr.io/tuna-os", scope="ghcr.io/tuna-os").mode == "github-token"


# ── Approved alternate registry and namespace ─────────────────────────────────

@pytest.mark.parametrize("destination", [
    "quay.io/acme", "ghcr.io/acme-org", "registry.gitlab.com/group/sub-group/os", "localhost:5000/dev",
    "ghcr.io/tuna-os-evil",
])
def test_non_owner_destination_with_scoped_credentials(destination):
    selection = pick(destination, scope=destination, username=True, password=True)
    assert (selection.mode, selection.scope) == ("registry-secret", destination)


@pytest.mark.parametrize("registry,namespace", [
    ("localhost:5000", "dev"), ("registry.gitlab.com", "group/sub-group/os"), ("ghcr.io", "my_org")])
def test_every_build_publish_shape_is_selectable(registry, namespace):
    source = config.load()
    source["build"]["publish"] = {"registry": registry, "namespace": namespace}
    config.validate(source)
    destination = f"{registry}/{namespace}"
    assert pick(destination, scope=destination, username=True, password=True).mode == "registry-secret"


# ── Missing, partial and conflicting credentials ──────────────────────────────

@pytest.mark.parametrize("destination", ["quay.io/acme", "ghcr.io/acme-org"])
def test_missing_credentials_never_fall_back_to_owner_ghcr(destination):
    message = refused("missing-credentials", destination, scope=destination)
    assert "does not fall back to ghcr.io/tuna-os" in message
    assert f"TUNAOS_PUBLISH_SCOPE={destination}" in message


@pytest.mark.parametrize("username,password,absent", [
    (True, False, "TUNAOS_PUBLISH_PASSWORD"), (False, True, "TUNAOS_PUBLISH_USERNAME")])
def test_partial_credentials_are_refused(username, password, absent):
    message = refused("partial-credentials", "quay.io/acme", scope="quay.io/acme",
                      username=username, password=password)
    assert message.startswith(f"partial-credentials: {absent} is not set")


def test_credentials_without_a_scope_are_refused():
    refused("missing-scope", "quay.io/acme", username=True, password=True)


@pytest.mark.parametrize("destination,scope", [
    # IMAGE_REGISTRY override sends the run elsewhere than the approved scope.
    ("quay.io/evil", "quay.io/acme"),
    ("evil.example/acme", "quay.io/acme"),
    # Scope is exact: no prefix or parent-namespace match.
    ("quay.io/acme-evil", "quay.io/acme"),
    ("quay.io/acme/sub", "quay.io/acme"),
    ("quay.io/acme", "quay.io/acme/sub"),
    ("quay.io:443/acme", "quay.io/acme"),
])
def test_scope_mismatch_keeps_the_credential_at_its_scope(destination, scope):
    refused("scope-mismatch", destination, scope=scope, username=True, password=True)


def test_override_back_to_owner_ghcr_conflicts_with_a_configured_scope():
    # [build.publish] says quay.io/acme and the operator variable says
    # ghcr.io/<owner>: refuse instead of publishing where the fork did not ask.
    refused("scope-mismatch", "ghcr.io/tuna-os", scope="quay.io/acme", username=True, password=True)


# ── Malicious values ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("destination", [
    "quay.io/acme\n::add-mask::x", "quay.io/acme\r\n::stop-commands::t", "https://quay.io/acme",
    "quay.io/../acme", "quay.io/acme:latest", "quay.io/acme@sha256:00", "QUAY.IO/acme", "quay.io/ acme",
    "quay.io", "/acme", "", "quay.io/acme/", "user:pw@quay.io/acme", "quay.io/acme;rm -rf /",
])
def test_malformed_destinations_are_refused_without_log_injection(destination):
    refused("invalid-destination", destination, scope="quay.io/acme", username=True, password=True)


@pytest.mark.parametrize("scope", ["quay.io/acme\n::add-mask::x", "quay.io", "QUAY.io/acme", "*"])
def test_malformed_scope_is_refused(scope):
    refused("invalid-scope", "quay.io/acme", scope=scope, username=True, password=True)


@pytest.mark.parametrize("owner", ["", "tuna os", "tuna-os\n::add-mask::x", "-tuna", "a" * 40, "tuna/os"])
def test_malformed_owner_is_refused(owner):
    refused("invalid-owner", "ghcr.io/tuna-os", owner=owner)


# ── Untrusted execution ───────────────────────────────────────────────────────

@pytest.mark.parametrize("event", [
    "pull_request", "pull_request_target", "merge_group", "workflow_run", "issue_comment", "", "Push"])
def test_untrusted_events_may_not_publish(event):
    refused("untrusted-event", "quay.io/acme", event=event, scope="quay.io/acme", username=True, password=True)
    refused("untrusted-event", "ghcr.io/tuna-os", event=event)


@pytest.mark.parametrize("destination", ["quay.io/acme", "ghcr.io/tuna-os"])
def test_non_publishing_runs_select_no_credential(destination):
    assert pick(destination, event="pull_request", publish=False).mode == "none"


# ── CLI: presence flags in, GITHUB_OUTPUT lines out ───────────────────────────

def cli(**overrides):
    env = {k: v for k, v in os.environ.items() if not k.startswith(("TUNAOS_", "GITHUB_"))}
    env.update(TUNAOS_PUBLISH_DESTINATION="quay.io/acme", GITHUB_REPOSITORY_OWNER="hanthor",
               TUNAOS_PUBLISH_EVENT="schedule", TUNAOS_PUBLISH="true", TUNAOS_PUBLISH_SCOPE="quay.io/acme",
               TUNAOS_HAS_PUBLISH_USERNAME="true", TUNAOS_HAS_PUBLISH_PASSWORD="true")
    env.update(overrides)
    return subprocess.run([sys.executable, str(ROOT / "scripts/publish-credential.py")],
                          env=env, text=True, capture_output=True)


def test_cli_prints_github_output_lines():
    result = cli()
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.splitlines() == [
        "mode=registry-secret", "registry=quay.io", "namespace=acme", "scope=quay.io/acme"]


def test_cli_owner_path():
    result = cli(TUNAOS_PUBLISH_DESTINATION="ghcr.io/hanthor", TUNAOS_PUBLISH_SCOPE="",
                 TUNAOS_HAS_PUBLISH_USERNAME="false", TUNAOS_HAS_PUBLISH_PASSWORD="false")
    assert result.stdout.splitlines()[0] == "mode=github-token"


def test_cli_reads_trust_from_the_explicit_event_not_github_event_name():
    # attest-sbom.yml runs on workflow_run; it passes the triggering run's event.
    assert cli(GITHUB_EVENT_NAME="workflow_run").returncode == 0
    result = cli(GITHUB_EVENT_NAME="schedule", TUNAOS_PUBLISH_EVENT="pull_request")
    assert result.returncode == 1 and "untrusted-event" in result.stdout


def test_cli_refuses_with_one_error_line():
    result = cli(TUNAOS_HAS_PUBLISH_PASSWORD="false")
    assert result.returncode == 1
    assert result.stdout.splitlines() == [
        result.stdout.strip()] and result.stdout.startswith("::error::publish credential: partial-credentials:")


@pytest.mark.parametrize("name", ["TUNAOS_PUBLISH_USERNAME", "TUNAOS_PUBLISH_PASSWORD"])
def test_cli_refuses_secret_values(name):
    result = cli(**{name: SECRET_PASS})
    assert result.returncode == 1
    assert "secret-in-resolver" in result.stdout
    assert SECRET_PASS not in result.stdout + result.stderr


@pytest.mark.parametrize("value", ["", "1", "True", "yes"])
def test_cli_flags_are_strict(value):
    result = cli(TUNAOS_HAS_PUBLISH_USERNAME=value)
    assert result.returncode == 1 and "invalid-input" in result.stdout


# ── Login helper with credential-free command stubs ───────────────────────────

STUB = """#!/usr/bin/env bash
{ printf '%s' "$(basename "$0")"; printf ' %s' "$@"; printf '\\n'; } >> "$STUB_LOG"
if [[ "$(basename "$0")" == sudo ]]; then exec "$@"; fi
cat >> "$STUB_STDIN"
"""


@pytest.fixture
def login(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name in ("docker", "podman", "skopeo", "cosign", "sudo"):
        (bin_dir / name).write_text(STUB, encoding="utf-8")
        (bin_dir / name).chmod(0o755)
    log, stdin = tmp_path / "argv.log", tmp_path / "stdin.log"

    def run(tool, scope="quay.io/acme", **overrides):
        log.write_text("", encoding="utf-8")
        stdin.write_text("", encoding="utf-8")
        env = {k: v for k, v in os.environ.items() if not k.startswith("TUNAOS_")}
        env.update(PATH=f"{bin_dir}:{env['PATH']}", STUB_LOG=str(log), STUB_STDIN=str(stdin),
                   TUNAOS_PUBLISH_MODE="registry-secret", TUNAOS_PUBLISH_USERNAME=SECRET_USER,
                   TUNAOS_PUBLISH_PASSWORD=SECRET_PASS)
        env.update(overrides)
        result = subprocess.run(["bash", str(ROOT / "scripts/publish-registry-login.sh"), tool, scope],
                                env=env, text=True, capture_output=True)
        return result, log.read_text(encoding="utf-8").splitlines(), stdin.read_text(encoding="utf-8")
    return run


@pytest.mark.parametrize("tool,argv", [
    ("podman", ["podman login --username=acme+ci-robot --password-stdin quay.io/acme"]),
    ("skopeo", ["skopeo login --username=acme+ci-robot --password-stdin quay.io/acme"]),
    ("sudo-podman", ["sudo podman login --username=acme+ci-robot --password-stdin quay.io/acme",
                     "podman login --username=acme+ci-robot --password-stdin quay.io/acme"]),
    ("sudo-skopeo", ["sudo skopeo login --username=acme+ci-robot --password-stdin quay.io/acme",
                     "skopeo login --username=acme+ci-robot --password-stdin quay.io/acme"]),
    ("cosign", ["cosign login quay.io --username=acme+ci-robot --password-stdin"]),
    ("docker", ["docker login quay.io --username=acme+ci-robot --password-stdin"]),
])
def test_login_passes_the_password_on_stdin_only(login, tool, argv):
    result, calls, stdin = login(tool)
    assert result.returncode == 0, result.stderr
    assert calls == argv
    assert stdin == SECRET_PASS
    assert SECRET_PASS not in result.stdout + result.stderr + "\n".join(calls)
    assert SECRET_USER not in result.stdout + result.stderr


def test_alternate_ghcr_namespace_login_is_namespace_scoped(login):
    # A namespace key leaves the ghcr.io GITHUB_TOKEN entry for upstream pulls.
    _, calls, _ = login("podman", scope="ghcr.io/acme-org")
    assert calls == ["podman login --username=acme+ci-robot --password-stdin ghcr.io/acme-org"]


@pytest.mark.parametrize("overrides,reason", [
    ({"TUNAOS_PUBLISH_MODE": "github-token"}, "owner path uses GITHUB_TOKEN"),
    ({"TUNAOS_PUBLISH_MODE": ""}, "owner path uses GITHUB_TOKEN"),
    ({"TUNAOS_PUBLISH_PASSWORD": ""}, "must both be set"),
    ({"TUNAOS_PUBLISH_USERNAME": ""}, "must both be set"),
    ({"TUNAOS_PUBLISH_USERNAME": "--password=x"}, "may contain only"),
    ({"TUNAOS_PUBLISH_USERNAME": "robot\n::add-mask::"}, "may contain only"),
    ({"TUNAOS_PUBLISH_USERNAME": "robot name"}, "may contain only"),
    ({"TUNAOS_PUBLISH_PASSWORD": "abc\ndef"}, "line break"),
    ({"TUNAOS_PUBLISH_PASSWORD": "abc\rdef"}, "line break"),
])
def test_login_refuses_before_running_any_tool(login, overrides, reason):
    result, calls, stdin = login("podman", **overrides)
    assert result.returncode == 1 and reason in result.stderr
    assert calls == [] and stdin == ""
    assert SECRET_PASS not in result.stdout + result.stderr


@pytest.mark.parametrize("scope", ["quay.io", "https://quay.io/acme", "quay.io/acme\n::x", "QUAY.io/acme", ""])
def test_login_refuses_a_scope_the_resolver_cannot_print(login, scope):
    result, calls, _ = login("podman", scope=scope)
    assert result.returncode == 1 and calls == []


def test_login_refuses_unknown_tools(login):
    result, calls, _ = login("oras")
    assert result.returncode == 1 and calls == []


# ── Activation boundary ───────────────────────────────────────────────────────

def test_no_workflow_is_wired_before_approval():
    # RFC 016 activation needs maintainer approval. Wiring a workflow must
    # change this test in the same reviewed PR.
    names = ("TUNAOS_PUBLISH_USERNAME", "TUNAOS_PUBLISH_PASSWORD", "TUNAOS_PUBLISH_SCOPE",
             "publish-credential.py", "publish-registry-login.sh")
    for path in sorted((ROOT / ".github").rglob("*.y*ml")):
        text = path.read_text(encoding="utf-8")
        assert not [name for name in names if name in text], path


def test_owner_path_login_steps_are_unchanged():
    # The stock path is the existing GITHUB_TOKEN login to ghcr.io in each
    # publishing job; RFC 016 adds steps beside these and never edits them.
    action = yaml.safe_load((ROOT / ".github/actions/ghcr-login/action.yml").read_text(encoding="utf-8"))
    docker = action["runs"]["steps"][0]["with"]
    assert docker == {"registry": "ghcr.io", "username": "${{ github.actor }}", "password": "${{ github.token }}"}
    workflow = (ROOT / ".github/workflows/reusable-build-image.yml").read_text(encoding="utf-8")
    assert 'cosign login ghcr.io -u "$GHCR_ACTOR" --password-stdin' in workflow
    assert "uses: ./.github/actions/ghcr-login" in workflow
