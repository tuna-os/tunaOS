"""Credential selection for non-owner publish destinations (#3801, RFC 016).

The owner path (ghcr.io/<owner>) keeps the repository GITHUB_TOKEN. Any other
destination needs TUNAOS_PUBLISH_USERNAME, TUNAOS_PUBLISH_PASSWORD and a
TUNAOS_PUBLISH_SCOPE variable equal to that destination. Missing, partial or
mismatched credentials fail; nothing falls back to ghcr.io/<owner>. All tools
here are credential-free command stubs; the workflow wiring tests below read
the real workflow files.
"""
from __future__ import annotations

import importlib
import importlib.util
import os
from pathlib import Path
import subprocess
import sys

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
LIB_SPEC = importlib.util.spec_from_file_location(
    "publish_credentials_test_lib",
    ROOT / "scripts/lib/__init__.py",
    submodule_search_locations=[str(ROOT / "scripts/lib")],
)
assert LIB_SPEC and LIB_SPEC.loader
lib_package = importlib.util.module_from_spec(LIB_SPEC)
sys.modules[LIB_SPEC.name] = lib_package
LIB_SPEC.loader.exec_module(lib_package)
creds = importlib.import_module(f"{LIB_SPEC.name}.publish_credentials")

SPEC = importlib.util.spec_from_file_location("publish_credentials_config", ROOT / "scripts/lib/tunaos_config.py")
assert SPEC and SPEC.loader
config = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(config)

SECRET_USER = "acme+ci-robot"
SECRET_PASS = "not-a-real-secret-0123456789"


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
    "example.com:abc/acme", "example.com:/acme",
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
    assert result.returncode == 1 and "untrusted-event" in result.stderr


def test_cli_refuses_with_one_error_line():
    result = cli(TUNAOS_HAS_PUBLISH_PASSWORD="false")
    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr.splitlines() == [
        result.stderr.strip()
    ] and result.stderr.startswith("::error::publish credential: partial-credentials:")


@pytest.mark.parametrize("name", ["TUNAOS_PUBLISH_USERNAME", "TUNAOS_PUBLISH_PASSWORD"])
def test_cli_refuses_secret_values(name):
    result = cli(**{name: SECRET_PASS})
    assert result.returncode == 1
    assert "secret-in-resolver" in result.stderr
    assert SECRET_PASS not in result.stdout + result.stderr


@pytest.mark.parametrize("name", ["TUNAOS_PUBLISH_USERNAME", "TUNAOS_PUBLISH_PASSWORD"])
def test_cli_ignores_empty_secret_placeholders(name):
    result = cli(**{name: ""})
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("value", ["", "1", "True", "yes"])
def test_cli_flags_are_strict(value):
    result = cli(TUNAOS_HAS_PUBLISH_USERNAME=value)
    assert result.returncode == 1 and "invalid-input" in result.stderr


# ── Login helper with credential-free command stubs ───────────────────────────

STUB = """#!/usr/bin/env bash
{ printf '%s' "$(basename "$0")"; printf ' %s' "$@"; printf '\\n'; } >> "$STUB_LOG"
if [[ "$(basename "$0")" == sudo ]]; then
	if [[ "${1:-}" == -n ]]; then shift; fi
	exec "$@"
fi
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
    ("sudo-podman", ["sudo -n podman login --username=acme+ci-robot --password-stdin quay.io/acme",
                     "podman login --username=acme+ci-robot --password-stdin quay.io/acme"]),
    ("sudo-skopeo", ["sudo -n skopeo login --username=acme+ci-robot --password-stdin quay.io/acme",
                     "skopeo login --username=acme+ci-robot --password-stdin quay.io/acme"]),
    ("cosign", ["cosign login --username=acme+ci-robot --password-stdin quay.io"]),
    ("docker", ["docker login --username=acme+ci-robot --password-stdin quay.io"]),
])
def test_login_passes_the_password_on_stdin_only(login, tool, argv):
    result, calls, stdin = login(tool)
    assert result.returncode == 0, result.stderr
    assert calls == argv
    assert stdin == SECRET_PASS
    assert result.stdout == ""
    assert f"publish login: {tool} -> quay.io/acme" in result.stderr
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


@pytest.mark.parametrize("scope", [
    "quay.io", "https://quay.io/acme", "quay.io/acme\n::x", "QUAY.io/acme", "",
    "registry/acme", "quay.io/acme/../evil", "quay.io/acme//evil", "quay.io/acme/",
])
def test_login_refuses_a_scope_the_resolver_cannot_print(login, scope):
    result, calls, _ = login("podman", scope=scope)
    assert result.returncode == 1 and calls == []
    # One ::error:: line carrying the resolver's reason, not two annotations.
    assert result.stderr.splitlines() == [result.stderr.strip()]
    assert result.stderr.startswith("::error::publish login: scope must be a valid")
    assert "publish scope: invalid-scope:" in result.stderr


@pytest.mark.parametrize("scope", [
    "localhost:5000/acme",
    "registry.example.com:65535/acme/sub_name",
    "ghcr.io/acme-org/a--b",
])
def test_login_accepts_scopes_the_resolver_can_print(login, scope):
    assert "/".join(creds.parse_destination(scope)) == scope
    result, calls, _ = login("podman", scope=scope)
    assert result.returncode == 0, result.stderr
    assert calls == [f"podman login --username=acme+ci-robot --password-stdin {scope}"]


@pytest.mark.parametrize(
    "scope",
    ["localhost:0/acme", "localhost:00000/acme", "localhost:65536/acme", "localhost:99999/acme"],
)
def test_login_refuses_out_of_range_ports(login, scope):
    result, calls, _ = login("podman", scope=scope)
    assert result.returncode == 1 and calls == []


def test_login_refuses_unknown_tools(login):
    result, calls, _ = login("oras")
    assert result.returncode == 1 and calls == []


def test_login_refuses_tool_log_injection(login):
    result, calls, _ = login("unknown\n::warning::injected")
    assert result.returncode == 1 and calls == []
    assert result.stderr.splitlines() == ["::error::publish login: tool contains a line break"]


# ── Workflow wiring (RFC 016) ─────────────────────────────────────────────────

WORKFLOWS = ROOT / ".github/workflows"
SECRET_NAMES = ("TUNAOS_PUBLISH_USERNAME", "TUNAOS_PUBLISH_PASSWORD")
ENVIRONMENT = "${{ %s && vars.TUNAOS_PUBLISH_SCOPE != '' && 'publish' || '' }}"


def load(name):
    return yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))


def steps(workflow, job):
    return workflow["jobs"][job]["steps"]


def named(workflow, job, name):
    found = [step for step in steps(workflow, job) if step.get("name") == name]
    assert len(found) == 1, (job, name, [s.get("name") for s in steps(workflow, job)])
    return found[0]


def index(workflow, job, name):
    return [step.get("name") for step in steps(workflow, job)].index(name)


# (workflow file, job, expected `environment`)
CREDENTIAL_JOBS = [
    ("reusable-build-image.yml", "build_push", ENVIRONMENT % "inputs.publish"),
    ("reusable-build-image.yml", "manifest", ENVIRONMENT % "inputs.publish"),
    ("reusable-build-image.yml", "sign", ENVIRONMENT % "inputs.publish"),
    ("reusable-build-image.yml", "tag-image", ENVIRONMENT % "inputs.publish"),
    ("attest-sbom.yml", "attest", "${{ vars.TUNAOS_PUBLISH_SCOPE != '' && 'publish' || '' }}"),
    ("build-variant.yml", "generate_matrix", ENVIRONMENT % "github.event_name != 'pull_request'"),
]


@pytest.mark.parametrize("workflow,job,environment", CREDENTIAL_JOBS)
def test_credential_jobs_use_the_protected_publish_environment(workflow, job, environment):
    # RFC 016 decision 3. The expression is empty for the stock repository (no
    # TUNAOS_PUBLISH_SCOPE) and for runs that do not publish, so neither is
    # attached to a deployment-protected environment.
    assert load(workflow)["jobs"][job]["environment"] == environment


def secret_references(node, path=()):
    """Yield (path, text) for every string under node that names a publish secret."""
    if isinstance(node, dict):
        for key, value in node.items():
            yield from secret_references(value, path + (str(key),))
    elif isinstance(node, list):
        for position, value in enumerate(node):
            yield from secret_references(value, path + (position,))
    elif isinstance(node, str) and any(f"secrets.{name}" in node for name in SECRET_NAMES):
        yield path, node


def test_secret_values_reach_only_the_login_helper_steps():
    # A credential may be (a) passed by name down a workflow_call chain,
    # (b) tested for presence for the resolver, or (c) placed in the env of the
    # step that runs publish-registry-login.sh. Never a job env, a `with:`
    # input, an action, a build step or a resolver env.
    for path in sorted(WORKFLOWS.glob("*.yml")):
        workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
        for ref_path, text in secret_references(workflow.get("jobs", {})):
            where = f"{path.name}:{'/'.join(map(str, ref_path))}"
            job_id = ref_path[0]
            if ref_path[1] == "secrets":  # workflow_call hand-off by name
                assert ref_path[2] in SECRET_NAMES and text == "${{ secrets.%s }}" % ref_path[2], where
                continue
            assert ref_path[1] == "steps", where
            step = workflow["jobs"][job_id]["steps"][ref_path[2]]
            assert ref_path[3] == "env", where
            if "publish-credential.py" in step.get("run", ""):
                assert text.endswith(" != '' }}"), f"{where}: the resolver may get presence flags only"
                assert ref_path[4].startswith("TUNAOS_HAS_"), where
            else:
                assert "publish-registry-login.sh" in step["run"], where
                assert "uses" not in step and ref_path[4] in SECRET_NAMES and text == "${{ secrets.%s }}" % ref_path[4], where
                assert "registry-secret" in step["if"], where
        assert not any(f"secrets.{name}" in str(workflow.get("env", "")) for name in SECRET_NAMES), path.name


def triggers(document):
    """The `on:` section; YAML 1.1 reads an unquoted `on` as True, a quoted one stays 'on'."""
    return document.get(True, document.get("on"))


def test_triggers_reads_both_spellings_of_on():
    assert triggers({True: {"push": None}}) == {"push": None}
    assert triggers({"on": {"push": None}}) == {"push": None}


def test_declared_workflow_call_secrets_are_optional():
    for name in ("reusable-build-image.yml", "build-variant.yml"):
        secrets = triggers(load(name))["workflow_call"]["secrets"]
        for secret in SECRET_NAMES:
            assert secrets[secret].get("required") is False, (name, secret)


def test_every_caller_of_build_variant_passes_the_credential_by_name():
    callers = 0
    for path in sorted(WORKFLOWS.glob("*.yml")):
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        for job_id, job in document.get("jobs", {}).items():
            if job.get("uses") != "./.github/workflows/build-variant.yml":
                continue
            if "pull_request" in triggers(document):
                continue  # pull requests never publish; they get no credential
            callers += 1
            for secret in SECRET_NAMES:
                assert job["secrets"][secret] == "${{ secrets.%s }}" % secret, (path.name, job_id)
    assert callers >= 15


def test_build_variant_hands_the_credential_to_every_image_stage():
    stages = [job for job in load("build-variant.yml")["jobs"].values()
              if job.get("uses") == "./.github/workflows/reusable-build-image.yml"]
    assert len(stages) == 4
    for job in stages:
        assert job["secrets"] == {name: "${{ secrets.%s }}" % name for name in SECRET_NAMES}


@pytest.mark.parametrize("workflow,job", [
    ("reusable-build-image.yml", "build_push"), ("reusable-build-image.yml", "manifest"),
    ("reusable-build-image.yml", "sign"), ("reusable-build-image.yml", "tag-image"),
    ("attest-sbom.yml", "attest"), ("build-variant.yml", "generate_matrix"),
])
def test_every_credential_job_resolves_before_it_logs_in(workflow, job):
    data = load(workflow)
    resolver = [s for s in steps(data, job) if "publish-credential.py" in s.get("run", "")]
    assert len(resolver) == 1
    helpers = [s for s in steps(data, job) if "publish-registry-login.sh" in s.get("run", "")]
    assert (len(helpers) == 0) == (job == "generate_matrix")
    order = [s.get("name") for s in steps(data, job)]
    for helper in helpers:
        assert order.index(resolver[0]["name"]) < order.index(helper["name"])
        assert helper["if"] in ("${{ steps.publish_credential.outputs.mode == 'registry-secret' }}",
                                "steps.publish_credential.outputs.mode == 'registry-secret'")
    env = resolver[0]["env"]
    assert set(env) >= {"TUNAOS_PUBLISH_SCOPE", "TUNAOS_HAS_PUBLISH_USERNAME", "TUNAOS_HAS_PUBLISH_PASSWORD",
                        "TUNAOS_PUBLISH_EVENT"}
    assert env["TUNAOS_PUBLISH_SCOPE"] == "${{ vars.TUNAOS_PUBLISH_SCOPE }}"


def test_build_push_logs_in_after_build_image_and_keeps_the_cache_read_only():
    # RFC 016 decision 4: no build step may have the non-owner credential, and
    # the layer cache that the build writes needs a login, so it is read-only.
    data = load("reusable-build-image.yml")
    login = index(data, "build_push", "Login to non-owner publish registry")
    assert index(data, "build_push", "Build Image") < login < index(data, "build_push", "Push to GHCR")
    helper = named(data, "build_push", "Login to non-owner publish registry")["run"]
    assert "for tool in docker podman sudo-podman; do" in helper
    assert index(data, "build_push", "Resolve publish credential") < index(data, "build_push", "Build Image")


@pytest.fixture
def cache_step(tmp_path):
    step = named(load("reusable-build-image.yml"), "build_push", "Configure buildah registry layer cache")

    def run(mode, is_pr="false"):
        env_file = tmp_path / f"env-{mode}-{is_pr}"
        env = {"PATH": os.environ["PATH"], "IMAGE_REGISTRY": "quay.io/acme", "IS_PR": is_pr,
               "PUBLISH_MODE": mode, "GITHUB_ENV": str(env_file)}
        subprocess.run(["bash", "-euo", "pipefail", "-c", step["run"]], env=env, check=True)
        return env_file.read_text(encoding="utf-8").strip()
    return run


def test_layer_cache_is_writable_only_on_the_owner_path(cache_step):
    read_only = "BUILDAH_CACHE_FLAGS=--layers --cache-from quay.io/acme/tunaos-buildcache"
    assert cache_step("registry-secret") == read_only
    assert cache_step("github-token") == read_only + " --cache-to quay.io/acme/tunaos-buildcache"
    assert cache_step("none") == read_only + " --cache-to quay.io/acme/tunaos-buildcache"
    assert cache_step("github-token", is_pr="true") == read_only


OWNER_PATH_STEPS = [
    # (workflow, job, step name, what stays exactly as on main)
    ("reusable-build-image.yml", "build_push", "Login to GitHub Container Registry (cache + push)",
     {"if": "${{ inputs.publish }}", "uses": "./.github/actions/ghcr-login"}),
    ("reusable-build-image.yml", "manifest", "Login to GitHub Container Registry", {"if": "${{ inputs.publish }}"}),
    ("reusable-build-image.yml", "sign", "Login to GitHub Container Registry", {}),
    ("reusable-build-image.yml", "tag-image", "Login to GitHub Container Registry", {}),
    ("attest-sbom.yml", "attest", "Login to GitHub Container Registry", {"if": "steps.fetch.outputs.refs != '0'"}),
]


@pytest.mark.parametrize("workflow,job,name,expected", OWNER_PATH_STEPS)
def test_owner_path_login_steps_are_unchanged(workflow, job, name, expected):
    # The stock path is the existing GITHUB_TOKEN login to ghcr.io. RFC 016 adds
    # steps beside these; it does not edit, gate or remove them.
    step = named(load(workflow), job, name)
    for key, value in expected.items():
        assert step[key] == value
    assert "TUNAOS_" not in str(step) and "publish_credential" not in str(step)
    if "run" in step:
        assert "ghcr.io" in step["run"] or "REGISTRY" in step["run"]
        assert "GITHUB_TOKEN" in str(step["env"])
    else:
        action = yaml.safe_load((ROOT / ".github/actions/ghcr-login/action.yml").read_text(encoding="utf-8"))
        assert action["runs"]["steps"][0]["with"] == {
            "registry": "ghcr.io", "username": "${{ github.actor }}", "password": "${{ github.token }}"}


def test_pull_only_jobs_get_no_credential():
    # RFC 016 decision 5: published destinations allow anonymous pull, so verify,
    # ISO and lifecycle jobs never receive the secret.
    for path in sorted(WORKFLOWS.glob("*.yml")):
        workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
        for job_id, job in workflow.get("jobs", {}).items():
            allowed = (path.name, job_id) in {(w, j) for w, j, _ in CREDENTIAL_JOBS} or "secrets" in job
            if not allowed:
                assert not list(secret_references(job)), (path.name, job_id)
    names = {(w, j) for w, j, _ in CREDENTIAL_JOBS}
    assert ("reusable-build-image.yml", "verify_desktop") not in names
    assert ("reusable-build-artifacts.yml", "build-artifacts") not in names


# ── attest-sbom resolver step, run for real ───────────────────────────────────

@pytest.fixture
def attest(tmp_path):
    step = named(load("attest-sbom.yml"), "attest", "Resolve publish credential")
    script = step["run"].replace("python3 scripts/publish-credential.py",
                                 f"{sys.executable} {ROOT}/scripts/publish-credential.py")

    def run(refs, *, event="schedule", scope="", username=True, password=True):
        work = tmp_path / f"w{len(list(tmp_path.iterdir()))}"
        digests = work / "supply-chain/digests"
        digests.mkdir(parents=True)
        for position, ref in enumerate(refs):
            (digests / f"image-{position}.ref").write_text(ref + "\n", encoding="utf-8")
        output = work / "output"
        output.touch()
        env = {"PATH": os.environ["PATH"], "GITHUB_OUTPUT": str(output), "GITHUB_REPOSITORY_OWNER": "hanthor",
               "TUNAOS_PUBLISH_EVENT": event, "TUNAOS_PUBLISH_SCOPE": scope,
               "TUNAOS_HAS_PUBLISH_USERNAME": str(username).lower(), "TUNAOS_HAS_PUBLISH_PASSWORD": str(password).lower()}
        result = subprocess.run(["bash", "-e", "-c", script], env=env, cwd=work,
                                text=True, capture_output=True)
        return result, output.read_text(encoding="utf-8").splitlines()
    return run


DIGEST = "@sha256:" + "a" * 64


def test_attest_owner_destination_uses_the_github_token(attest):
    result, out = attest(["ghcr.io/hanthor/yellowfin" + DIGEST, "ghcr.io/hanthor/albacore" + DIGEST])
    assert result.returncode == 0, result.stderr
    assert out[0] == "mode=github-token"


def test_attest_scoped_destination_uses_the_registry_secret(attest):
    result, out = attest(["quay.io/acme/yellowfin" + DIGEST], scope="quay.io/acme")
    assert result.returncode == 0, result.stderr
    assert out == ["mode=registry-secret", "registry=quay.io", "namespace=acme", "scope=quay.io/acme"]


@pytest.mark.parametrize("kwargs,code", [
    ({"username": False, "password": False}, "missing-credentials"),
    ({"scope": "quay.io/acme", "password": False}, "partial-credentials"),
    ({"scope": "quay.io/other"}, "scope-mismatch"),
    ({"scope": "quay.io/acme", "event": "pull_request"}, "untrusted-event"),
])
def test_attest_refuses_what_the_resolver_refuses(attest, kwargs, code):
    result, out = attest(["quay.io/acme/yellowfin" + DIGEST], **kwargs)
    assert result.returncode == 1 and out == [] and code in result.stderr


def test_attest_refuses_outputs_that_span_destinations(attest):
    result, out = attest(["quay.io/acme/yellowfin" + DIGEST, "ghcr.io/hanthor/albacore" + DIGEST], scope="quay.io/acme")
    assert result.returncode == 1 and out == [] and "more than one publish destination" in result.stdout


@pytest.mark.parametrize('path', [
    'scripts/publish-credential.py', 'scripts/publish-registry-login.sh', 'tests/test_publish_credentials.py'])
def test_no_file_claims_the_workflows_are_unwired(path):
    text = (ROOT / path).read_text(encoding='utf-8')
    for stale in ('No workflow ' + 'calls', 'no workflow is ' + 'wired'):
        assert stale not in text, (path, stale)


def _events(document):
    section = triggers(document)
    return set(section) if isinstance(section, dict) else set(section if isinstance(section, list) else [section])


def _reaches_resolver(path, document):
    text = path.read_text(encoding='utf-8')
    return path.name in ('build-variant.yml', 'reusable-build-image.yml', 'attest-sbom.yml') or any(
        called in text for called in ('./.github/workflows/build-variant.yml', './.github/workflows/reusable-build-image.yml'))


def test_every_workflow_that_reaches_a_resolver_runs_only_on_trusted_events_or_pull_request():
    """The resolver refuses publishing on other events (merge_group, comments, ...).

    No workflow may reach it on one of those, or a run that published before would fail.
    """
    allowed = {'push', 'schedule', 'workflow_dispatch', 'pull_request', 'workflow_call', 'workflow_run'}
    seen = []
    for path in sorted(WORKFLOWS.glob('*.yml')):
        document = yaml.safe_load(path.read_text(encoding='utf-8'))
        if _reaches_resolver(path, document):
            seen.append(path.name)
            assert _events(document) <= allowed, (path.name, sorted(_events(document) - allowed))
    assert 'build-yellowfin.yml' in seen and 'tuna-pr-images.yml' in seen and 'attest-sbom.yml' in seen
    # test.yml runs on merge_group (Unit Tests is a required check), so the
    # Tuna PR image builds that reach the resolver moved out of it.
    assert 'test.yml' not in seen
