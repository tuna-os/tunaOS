# RFC 016: Credentials for non-owner publish destinations

- **Status:** Draft. Design, resolver and stub tests only. No workflow uses them.
- **Issue:** [#3801](https://github.com/tuna-os/tunaOS/issues/3801) (F1b of epic [#3668](https://github.com/tuna-os/tunaOS/issues/3668))
- **Branch:** `rfc016-publish-credentials`
- **Owner:** tuna-os maintainers
- **Related:** [RFC 013](rfc013-single-fork-config.md), [#3736](https://github.com/tuna-os/tunaOS/pull/3736) (`[build.publish]`), [#3474](https://github.com/tuna-os/tunaOS/issues/3474), [#3806](https://github.com/tuna-os/tunaOS/issues/3806) (F5)
- **Decision:** None. A maintainer must approve this design before a workflow, secret or permission changes.

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
- change a workflow, a job permission or the owner path;
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
| `TUNAOS_PUBLISH_USERNAME` | secret | repository settings | Registry user or robot account |
| `TUNAOS_PUBLISH_PASSWORD` | secret | repository settings | Registry token for that account |
| `TUNAOS_PUBLISH_SCOPE` | variable | repository settings | Exact approved destination, for example `quay.io/acme` |

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

The resolver writes `mode`, `registry`, `namespace` and `scope` as
`GITHUB_OUTPUT` lines. A refusal is one `::error::` line and exit status 1.
Untrusted text in that line is in `repr()` form. Thus a newline in a value
cannot start a workflow command.

### Login helper

`scripts/publish-registry-login.sh <tool> <scope>` logs in one tool with the
two secrets. It runs only when `TUNAOS_PUBLISH_MODE=registry-secret`.

| Tool | Command | Credential key |
|---|---|---|
| `podman`, `sudo-podman` | `podman login --username=U --password-stdin <scope>` | `<registry>/<namespace>` |
| `skopeo`, `sudo-skopeo` | `skopeo login --username=U --password-stdin <scope>` | `<registry>/<namespace>` |
| `docker` | `docker login <registry> --username=U --password-stdin` | registry host (oras reads this file) |
| `cosign` | `cosign login <registry> --username=U --password-stdin` | registry host |

The password goes to the tool on standard input. The shell builtin `printf`
writes it, so no process gets it as an argument. The helper rejects a username
outside `[A-Za-z0-9][A-Za-z0-9._@+-]*` and a password with a line break.

Podman and skopeo store a namespace key, as `containers-auth.json(5)`
specifies. Thus a `ghcr.io` entry from `GITHUB_TOKEN` stays usable for
upstream pulls. Docker and cosign keep one entry for each host. See decision 6.

### Job wiring after approval

The owner path keeps every existing step, unchanged. Activation adds one
resolver step per job and helper steps with `if: mode == 'registry-secret'`.

| Job | Registry writes to the destination | Steps added for `registry-secret` |
|---|---|---|
| `generate_matrix` (`build-variant.yml`) | none | Resolver only, so a refusal stops the run before build minutes start |
| `build_push` | layer cache, image push, `.packages` artifact | Resolver; helper for `docker`, `podman` and `sudo-podman` after **Build Image** (decision 4) |
| `manifest` | `-testing` manifest list | Resolver; helper for `podman` |
| `sign` | cosign signatures | Resolver; helper for `cosign` |
| `tag-image` | promotion of bare tags | Resolver; helper for `podman`, `sudo-podman` and `sudo-skopeo` |
| `attest` (`attest-sbom.yml`) | SBOM attestations | Resolver with the triggering run's event; helper for `cosign` |
| `verify_boot`, `verify_desktop`, ISO and lifecycle jobs | none (pull) | None. These jobs pull without credentials |

Secrets reach the reusable workflow through the generated wrappers.
`scripts/generate-workflows.py` passes the two secrets to `build-variant.yml`.
That workflow declares them as optional `workflow_call` secrets and passes them
to `reusable-build-image.yml`. Each secret goes only into the `env` of a helper
step. A build step never gets a secret.

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
| A writer dispatches a workflow from an unreviewed branch | The exact scope limits the token to the approved destination. Decision 3 can also restrict the secrets to `main` |
| An operator override disagrees with `tunaos.toml` | `scope-mismatch` |
| A value carries a newline, a URL scheme or an option | Pattern checks, `repr()` in errors, `--username=` form |
| A secret appears in a log | Standard input only. GitHub masks secrets. The helper and resolver never print them |
| Build code reads a secret | With decision 4, helper steps run after the build. The build `sudo --preserve-env` list names no credential |
| The token has too much access | Use a robot or deploy token that can write the one namespace. Do not use an account or organization admin token |
| CI silently publishes to upstream | No fallback (steps 8 to 11) |

## Evidence

| Check | State |
|---|---|
| Resolver and helper tests with command stubs (`tests/test_publish_credentials.py`) | Pass locally; numbers in the PR |
| Existing destination tests (`tests/test_publish_destination.py`) | Pass locally |
| Workflow wiring | Not done: blocked on approval |
| Login, push, pull and sign in an isolated test registry | Not run: no approved test credentials |

The stub tests cover the owner path, an approved alternate registry, an
alternate `ghcr.io` namespace, and missing and partial credentials. They also
cover overrides that disagree, malicious values and untrusted events.
`test_no_workflow_is_wired_before_approval` fails if a workflow names a
`TUNAOS_PUBLISH_*` input, the resolver or the helper. Activation must change
that test in the same reviewed pull request.

## Decisions for the maintainer

1. **Names.** Approve `TUNAOS_PUBLISH_USERNAME`, `TUNAOS_PUBLISH_PASSWORD`
   and the variable `TUNAOS_PUBLISH_SCOPE`.
2. **Scope rule.** Approve one scope for each repository. The match is
   exact, with no prefix match. A fork with two destinations needs a later
   extension.
3. **Secret location.** Choose repository secrets, or a `publish` environment
   that only `main` can deploy. The environment is the recommendation.
4. **Layer cache.** For `registry-secret`, the recommendation is to log in
   after **Build Image**. That job then reads the cache but does not write it. The other
   choice logs in before the build, as the owner path does now.
5. **Anonymous pull.** Approve that published destinations must allow
   anonymous pull. Verify, ISO and lifecycle jobs then need no credential.
6. **Other `ghcr.io` namespaces.** For `ghcr.io/<other-org>`, docker and
   cosign hold the secret token for all of `ghcr.io` in those jobs. Accept
   this, or refuse non-owner `ghcr.io` destinations.
7. **Trusted events.** Approve `push`, `schedule` and `workflow_dispatch`.
   `attest-sbom.yml` passes the event of the build run that triggered it.
8. **Runtime proof.** Approve an isolated test namespace and test
   credentials. Without them, the login, push, pull and sign proof stays
   blocked.
