# RFC 016: Credentials for non-owner publish destinations

- **Status:** Accepted on 2026-10-25. The maintainer adopted the recommended option of every decision (see [Decisions](#decisions)). The implementation is [#3853](https://github.com/tuna-os/tunaOS/pull/3853); the runtime proof stays blocked.
- **Issue:** [#3801](https://github.com/tuna-os/tunaOS/issues/3801) (F1b of epic [#3668](https://github.com/tuna-os/tunaOS/issues/3668))
- **Branch:** `rfc016-publish-credentials` (this document only; the resolver, helper, workflow wiring and tests are in #3853)
- **Owner:** tuna-os maintainers
- **Related:** [RFC 013](rfc013-single-fork-config.md), [#3736](https://github.com/tuna-os/tunaOS/pull/3736) (`[build.publish]`), [#3474](https://github.com/tuna-os/tunaOS/issues/3474), [#3806](https://github.com/tuna-os/tunaOS/issues/3806) (F5)
- **Decision:** [ADR 0015](../adr/0015-publish-credentials-for-non-owner-destinations.md)

## Problem

A fork can name its destination in `tunaos.toml`:

```toml
[build.publish]
registry = "quay.io"
namespace = "acme"
```

`scripts/lib/publish-destination.sh` resolves this value, and every publish
job gets it as `IMAGE_REGISTRY`. The value is correct in image references,
`os-release` and bootc metadata. CI cannot push to it.

Each job that writes to the registry logs in to `ghcr.io` with the
repository `GITHUB_TOKEN`:

| Job | File | Login today |
|---|---|---|
| `build_push` | `.github/workflows/reusable-build-image.yml` | `./.github/actions/ghcr-login`: docker, podman and `sudo podman` to `ghcr.io` |
| `manifest` | same | `podman login ... ghcr.io` |
| `sign` | same | `cosign login ghcr.io` |
| `tag-image` | same | podman, `sudo podman`, `sudo skopeo` to `ghcr.io` |
| `attest` | `.github/workflows/attest-sbom.yml` | `cosign login ghcr.io` |

`GITHUB_TOKEN` can write packages of the repository owner only. A
destination outside `ghcr.io/<owner>` thus fails at the first push. The
existing `vars.IMAGE_REGISTRY` override has the same gap.

## Scope and non-goals

This RFC covers:

- the secret and variable names;
- one rule that selects the credential from the resolved destination;
- how login, push, cosign and promotion use that rule;
- the failure for each missing or wrong input;
- the trust boundary and the threat model.

This RFC does not:

- add, grant or rotate a secret;
- change the owner path: it keeps every existing step, byte for byte;
- push to a registry or claim runtime proof;
- support destinations that need credentials to pull. Users run
  `bootc upgrade` without a registry login, so a published image must allow
  anonymous pull.

## Terms

| Term | Meaning |
|---|---|
| destination | The effective `<registry>/<namespace>` of a job: `vars.IMAGE_REGISTRY`, else `[build.publish]`, else `ghcr.io/<owner>` |
| owner path | A destination of `ghcr.io/<owner>` or `ghcr.io/<owner>/...`, with the owner in lower case |
| non-owner destination | Any other destination |
| scope | The single destination that a repository administrator approves for the publish credential |

## Contract

### Inputs

| Name | Kind | Where it lives | Content |
|---|---|---|---|
| `TUNAOS_PUBLISH_USERNAME` | secret | the `publish` environment | Registry user or robot account |
| `TUNAOS_PUBLISH_PASSWORD` | secret | the `publish` environment | Registry token for that account |
| `TUNAOS_PUBLISH_SCOPE` | variable | repository settings | Exact approved destination, for example `quay.io/acme` |

The `publish` environment allows deployments from `main` only (decision 3).
Do not also create a repository secret of the same name. An environment secret
overrides it, but every branch can read a repository secret.

`tunaos.toml` never holds a credential or a scope. A pull request can edit
the tree. It cannot edit the settings of the repository. The scope is
therefore the trust anchor, and the destination in the tree is only a request.

### Selection rule

`scripts/lib/publish_credentials.py` contains the rule.
`scripts/publish-credential.py` is its command-line entry point. The resolver
reads presence flags (`secrets.X != ''`), not secret values. It refuses to run
if a secret value is in its environment.

The resolver applies these steps in order:

| Step | Condition | Result |
|---|---|---|
| 1 | Owner is not a GitHub login name | `invalid-owner` |
| 2 | Destination does not match the `[build.publish]` registry and namespace patterns | `invalid-destination` |
| 3 | The job does not publish | `none`: no destination login |
| 4 | Event is not `push`, `schedule` or `workflow_dispatch` | `untrusted-event` |
| 5 | Scope is set but malformed | `invalid-scope` |
| 6 | Owner path, scope empty or equal to the destination | `github-token`: existing steps only |
| 7 | Owner path, scope set to another destination | `scope-mismatch` |
| 8 | Non-owner, neither secret set | `missing-credentials` |
| 9 | Non-owner, one secret set | `partial-credentials` |
| 10 | Non-owner, scope empty | `missing-scope` |
| 11 | Non-owner, scope not equal to the destination | `scope-mismatch` |
| 12 | Non-owner, both secrets set, scope equal | `registry-secret` |

Scope comparison is exact string equality. `quay.io/acme` does not authorize
`quay.io/acme-evil`, `quay.io/acme/sub` or `quay.io:443/acme`. The
namespace is in lower case before comparison, as `publish-destination.sh`
writes it.

The resolver prints `mode`, `registry`, `namespace` and `scope` on standard
output; the workflow step appends those lines to `$GITHUB_OUTPUT`. A refusal is
one `::error::` line on standard error and exit status 1. Untrusted text in that
line is in `repr()` form. Thus a newline in a value cannot start a workflow
command.

### Login helper

`scripts/publish-registry-login.sh <tool> <scope>` logs in one tool with the
two secrets. It runs only when `TUNAOS_PUBLISH_MODE=registry-secret`.

| Tool | Command | Credential key |
|---|---|---|
| `podman`, `sudo-podman` | `podman login --username=U --password-stdin <scope>` | `<registry>/<namespace>` |
| `skopeo`, `sudo-skopeo` | `skopeo login --username=U --password-stdin <scope>` | `<registry>/<namespace>` |
| `docker` | `docker login --username=U --password-stdin <registry>` | registry host (oras reads this file) |
| `cosign` | `cosign login --username=U --password-stdin <registry>` | registry host |

The password goes to the tool on standard input. The shell builtin `printf`
writes it, so no process gets it as an argument. The helper rejects a username
outside `[A-Za-z0-9][A-Za-z0-9._@+-]*` and a password with a line break.
The `sudo-*` tools run `sudo -n`, so a host that would prompt fails at once.
It does not read the password from standard input.

Podman and skopeo store a namespace key, as `containers-auth.json(5)`
specifies. Thus a `ghcr.io` entry from `GITHUB_TOKEN` stays usable for
upstream pulls. Docker and cosign keep one entry for each host. See decision 6.

### Job wiring

The owner path keeps every existing step, unchanged. The wiring adds one
resolver step per job, helper steps with `if: mode == 'registry-secret'`, and
an `environment` expression.

| Job | Registry writes to the destination | Steps added for `registry-secret` |
|---|---|---|
| `generate_matrix` (`build-variant.yml`) | none | Resolver only, so a refusal stops the run before build minutes start |
| `build_push` | layer cache, image push, `.packages` artifact | Resolver; helper for `docker`, `podman` and `sudo-podman` after **Build Image** (decision 4) |
| `manifest` | `-testing` manifest list | Resolver; helper for `podman` |
| `sign` | cosign signatures | Resolver; helper for `cosign` |
| `tag-image` | `:<flavor>-testing` and dated tags; bare tags only for a new cell (RFC 018) | Checkout and resolver; helper for `podman`, `sudo-podman` and `sudo-skopeo` |
| `apply` (`promote-stable.yml`) | bare, arch and alias tags of the stable ring (RFC 018) | Resolver with the run's event; helper for `skopeo` |
| `attest` (`attest-sbom.yml`) | SBOM attestations | Resolver with the triggering run's event and the destination of the build's digest refs; helper for `cosign` |
| `verify_boot`, `verify_desktop`, ISO and lifecycle jobs | none (pull) | None. These jobs pull without credentials |

Each of these jobs carries `environment: publish` when the run publishes and
`vars.TUNAOS_PUBLISH_SCOPE` is set, and no environment otherwise. An empty
environment name means no environment. The stock repository sets no scope, so
its jobs and every pull request run stay as they are. A fork that sets a scope
gets a deployment-protected job, and a dispatch from another branch than
`main` fails at the environment before any step runs.

Secrets reach the reusable workflow through the generated wrappers.
`scripts/generate-workflows.py` passes the two secrets, by name, to
`build-variant.yml`. GitHub needs this even for a secret that exists only in
an environment. That workflow declares them as optional `workflow_call`
secrets and passes them to `reusable-build-image.yml`. Each secret goes only
into the `env` of a helper step, or, as a presence test, of a resolver step. A
build step never gets a secret, and a test enforces this.

With `registry-secret` the layer cache is read-only: `--cache-to` is not set,
because no credential exists while **Build Image** runs.

The digest checks, the keyless cosign identity, the signature check before
promotion and the boot gates stay the same. The identity is
`https://github.com/<repo>/.github/workflows/reusable-build-image.yml@<ref>`.
Only the registry that stores the signature changes.

### Failures

| Code | Typical cause | Fix |
|---|---|---|
| `missing-credentials` | Fork set `[build.publish]` but no secrets | Add both secrets and the scope variable |
| `partial-credentials` | One secret is absent | Add the absent secret |
| `missing-scope` | Secrets exist, variable does not | Set `TUNAOS_PUBLISH_SCOPE` to the destination |
| `scope-mismatch` | `IMAGE_REGISTRY` or `[build.publish]` changed, or the variable is stale | Make the three values agree |
| `untrusted-event` | A pull request, merge queue or comment run tried to publish | None: such runs do not publish |
| `invalid-destination`, `invalid-scope`, `invalid-owner` | Malformed or injected value | Correct the value |
| `secret-in-resolver` | Workflow passed a secret value to the resolver | Pass `TUNAOS_HAS_*` flags |

CI never falls back to `ghcr.io/<owner>`. A run that cannot publish where the
fork asked fails, and the error names the fix.

## Threat model

| Threat | Control |
|---|---|
| A pull request points `[build.publish]` at an attacker registry to capture the token | Pull request runs do not publish (step 4). The scope lives in settings, and the match is exact |
| A pull request from a fork | GitHub gives no secrets to such runs. Step 4 still refuses |
| A writer dispatches a workflow from an unreviewed branch | The `publish` environment refuses any branch but `main`, so the secrets never reach that run. The exact scope also limits the token to the approved destination |
| An operator override disagrees with `tunaos.toml` | `scope-mismatch` |
| A value carries a newline, a URL scheme or an option | Pattern checks, `repr()` in errors, `--username=` form |
| A secret appears in a log | Standard input only. GitHub masks secrets. The helper and resolver never print them |
| Build code reads a secret | With decision 4, helper steps run after the build. The build `sudo --preserve-env` list names no credential |
| The token has too much access | Use a robot or deploy token that can write the one namespace. Do not use an account or organization admin token |
| CI silently publishes to upstream | No fallback (steps 8 to 11) |

## Evidence

Source checks, stub-only. Nothing here is a registry login, push, pull or
signature.

| Check | State |
|---|---|
| Resolver, login helper and workflow-wiring tests with command stubs (`tests/test_publish_credentials.py`) | In #3853. The PR gives the counts |
| Existing destination tests (`tests/test_publish_destination.py`) | In #3853 |
| Workflow wiring | In #3853, with the tests that pin it |
| Login, push, pull and sign in an isolated test registry | **Blocked.** Decision 8 defers it |
| That GitHub resolves an environment secret in a reusable workflow job when the caller passes it by name. That GitHub treats an empty `environment` as none | Taken from the GitHub documentation and a community report. Not run in this repository |

The stub tests cover these cases:

- the owner path, an approved alternate registry, an alternate `ghcr.io`
  namespace, and missing and partial credentials;
- overrides that disagree, malicious values and untrusted events;
- the order of login after **Build Image**, and the read-only cache;
- no secret value reaches a build step, a job `env` or an action input.

## Decisions

The maintainer adopted the recommended option of every decision on
2026-10-25, through the orchestrator the maintainer delegated to.

| # | Decision | Outcome |
|---|---|---|
| 1 | Names | `TUNAOS_PUBLISH_USERNAME`, `TUNAOS_PUBLISH_PASSWORD` and the variable `TUNAOS_PUBLISH_SCOPE`. #3853 first used `PUBLISH_REGISTRY_USERNAME` and `PUBLISH_REGISTRY_TOKEN`; it now uses these |
| 2 | Scope rule | One exact scope for each repository, no prefix match. A fork with two destinations needs a later extension |
| 3 | Secret location | A `publish` environment that only `main` can deploy |
| 4 | Layer cache | Log in after **Build Image**. The cache is read-only for `registry-secret` |
| 5 | Anonymous pull | A published destination must allow anonymous pull. Verify, ISO and lifecycle jobs get no credential |
| 6 | Other `ghcr.io` namespaces | Accept that docker and cosign hold the token for all of `ghcr.io` in those jobs. Non-owner `ghcr.io` destinations stay allowed |
| 7 | Trusted events | `push`, `schedule` and `workflow_dispatch`. `attest-sbom.yml` passes the event of the build run that triggered it |
| 8 | Runtime proof | An isolated test namespace and test credentials need a later, separate approval. The proof stays blocked until then |
