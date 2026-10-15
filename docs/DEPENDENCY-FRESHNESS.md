# Dependency freshness and automerge policy

**Scope:** every repository in the `tuna-os` organization  
**Policy source:** [`tuna-os/.github`](https://github.com/tuna-os/.github)  
**Tracks:** [#1636](https://github.com/tuna-os/tunaOS/issues/1636), [#2833](https://github.com/tuna-os/tunaOS/issues/2833)

This policy keeps dependencies current. It also stops a repository from a
silent reduction of the organization's review boundary. Renovate is the
version update service. Dependabot security updates provide a second path for
advisories. Do not configure both services for routine updates.

## Required Renovate configuration

Every repository with managed dependencies must extend the shared preset:

```json
{
  "$schema": "https://docs.renovatebot.com/renovate-schema.json",
  "extends": ["local>tuna-os/.github"]
}
```

Repository configuration may add custom managers, package groups, release-age
limits, or explicit package holds. It must not automerge a `major` update. The
shared preset is the source of truth for the default rules:

| Update class | Merge rule |
|---|---|
| `minor`, `patch`, `pin`, `pinDigest`, `digest` | May automerge only after the repository's required CI and branch protections pass |
| `major` | Human review required |
| Package with a documented unsafe migration or coupled checksum | Human review required, even for a routine update |

Maintainers can make a local exception stricter than the shared policy. Its
`packageRules[].description` must name the constraint, evidence, owner, and
exit condition. Maintainers must approve a shared policy change before a repo
can weaken the rule for major updates. A local override grants no approval.

Run both checks after each change to the Renovate config:

```bash
RENOVATE_VERSION=$(yq -r '.jobs.validate.steps[] | select(.name == "Install dependencies").env.RENOVATE_VERSION' \
  .github/workflows/validate-renovate.yaml)
npx --yes --package "renovate@${RENOVATE_VERSION}" \
  renovate-config-validator --strict --no-global renovate.json
python3 scripts/check-renovate-automerge-policy.py renovate.json
```

The validator checks syntax and deprecated options. The policy
checker catches a different failure mode: valid JSON that layers a broad or
package-scoped `automerge: true` rule over major updates. Repositories created
from `tuna-os/.github/project-starter` receive the same gate. Existing
repositories must copy the gate during rollout. A template repair does not
retroactively protect them.

## Immutable-reference contract

Dependencies executed during a build or CI run use an immutable identity:

- GitHub Actions use a full commit SHA, with the release tag retained as a
  comment for reviewability.
- Container images use a digest. A tag may accompany the digest to show the
  intended release line.
- Git submodules use the reviewed commit recorded by the parent repository.
- Downloaded release artifacts use a fixed version and verified upstream
  checksum. When Renovate cannot update both values, set `automerge: false`
  for that package. Update the version and checksum in the same change.

A branch ref, mutable action tag, bare container tag, or `latest` download URL
needs a documented exception with an owner and exit condition.
A freshness bot is not a substitute for identity verification.

## Renovate and Dependabot coordination

Renovate manages versions and digests on a schedule. Do not add Dependabot
`version-updates` for an ecosystem that Renovate manages. Keep Dependabot
security updates and alerts active. GitHub advisories trigger that path.

When both services open a PR for the same advisory:

1. Keep the PR that carries the advisory link.
2. Confirm that this PR reaches a supported fixed version. Do not close the
   security PR because a routine update exists.
3. Run the repository's test suite. Keep human review for a major update or
   migration.
4. Merge one fix, then let the other bot rebase or close its obsolete PR.
5. Record any temporary hold in the selected PR. Name an owner and unblock
   condition.

## Update cadence and queue control

Renovate may discover updates continuously. Repositories should group related
updates. Use `minimumReleaseAge` for unusually noisy or high-risk sources; do
not disable the bot. Security updates use no routine window. Treat a dependency
dashboard or config error as operational work. Restore a successful run before
you close it.

## Fleet rollout checklist

For each organization repository:

- Renovate is installed and its config extends `local>tuna-os/.github`.
- The config passes both schema and automerge-policy validation in CI.
- Dependabot does not manage routine versions for the same ecosystem.
- Actions, images, submodules, and downloaded artifacts follow the immutable
  reference contract.
- Branch protection is present for every check relied upon by automerge.
- Every hold or policy exception names an owner and exit condition.

The rollout is complete only when each existing repository passes this list.
The project-starter gate protects new repositories but does not prove the
migration of older repositories.

## Monthly health check

The supply-chain owner runs a fleet check monthly and after a change to the
shared preset. Derive the report from GitHub each time; do not commit a
hand-maintained repository-status table.

```bash
# Configuration failures raised by Renovate
gh search issues --owner tuna-os --state open --match title \
  '"Action Required: Fix Renovate Configuration"'

# Open bot queues; inspect age, failing checks, and duplicate ecosystems
gh search prs --owner tuna-os --state open --author app/renovate
gh search prs --owner tuna-os --state open --author app/dependabot

# Configs that declare the shared preset (compare with the live repo inventory)
gh search code --owner tuna-os --filename renovate.json \
  '"local>tuna-os/.github"'
gh repo list tuna-os --limit 200 --json name,isArchived
```

The report records the command timestamp, halted configurations, oldest open
bot PR, unreviewed major updates, policy-check failures, missing active-repo
coverage, and remediation issue or PR. List archived repos in the report, but
do not run automation for them. A healthy month has no halted config and no
local bypass of major-update review. Each stale bot PR has an owner and an
unblock condition.
