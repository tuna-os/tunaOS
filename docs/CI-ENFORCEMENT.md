# CI enforcement and signal review

Issue [#3011](https://github.com/tuna-os/tunaos/issues/3011) tracks differences in CI
checks across the organization. This is the rollout baseline for repository
review, not a claim that all repositories enforce it. Each repository adopts
changes through its own PR. Maintainers apply branch protection and rulesets.

## Required and advisory checks

| Check | Baseline for adoption | What a failure means |
|---|---|---|
| DCO | Required on every PR | Each author signs each commit; the trailer email matches the author email. |
| Lint and unit tests | Required where the language or file type applies | Reproduce with the repository's contributor commands. Rust projects include format, Clippy and unit tests. |
| STE | Required budget ratchet for source prose | Use the shared rules and the repository's committed budget. Fix new findings; do not raise the budget to pass. |
| CI contract and fork safety | Required where adopted | Declared gates must run; PR jobs must work with fork permissions. |
| Build, boot and E2E | Follow the repository's explicit release contract | Product safety checks remain blocking where the contract says so. Experimental checks start advisory and need evidence before promotion. |
| Diagnostics and new experimental checks | Advisory until qualified | Report findings with an owner and a repair issue; do not treat these as merge approval. |

For tunaOS, [green criteria](GREEN-CRITERIA.md) and
[`.github/green-criteria.yml`](../.github/green-criteria.yml) govern image
promotion. `just test-contract` verifies their wiring. Required checks on GitHub are a separate control. A red workflow alone does not prove that
branch protection needs it. A skipped or stale safety check is not a pass.
Do not make all E2E checks advisory in response to intermittent failures.

The shared library is in
[`tuna-os/.github`](https://github.com/tuna-os/.github/blob/main/docs/WORKFLOWS.md).
Use `ste-lint.yml`, `reusable-lint.yml`, `reusable-ci-contract.yml` and
`reusable-fork-safety.yml` there. Keep their implementations in that repository.
Review the actual callee at its pinned ref, including step-level
`continue-on-error`: the shared lint workflow has advisory actionlint behavior.
A caller name does not prove that every tool blocks.

Adoption PRs should pin a reviewed commit and use dependency updates to keep
it current. Keep triggers and least-privilege permissions in each caller.
Verify that each eligible PR and merge-queue event emits the required check contexts.
Path filters must not prevent a required context from completion.
Run secret-dependent release work on trusted events, not contributor code.

## Runtime and false-positive budget

Use these initial budgets for review when you adopt a check. This proposal sets
limits for rollout. It does not measure service levels or authorize changes to an
existing safety gate without evidence.

| Job class | Proposed explicit timeout |
|---|---|
| DCO, STE, lint and contract validation | 15 minutes |
| Unit tests and ordinary application builds | 60 minutes |
| VM boot and E2E | 120 minutes |
| OS image and artifact builds | 360 minutes |

Set `timeout-minutes` on executable jobs. A reusable-workflow caller delegates
this to its callee; it cannot set a job timeout on the `uses` job. Record an
exception with the job, owner, run links, measured duration, rationale and
review date if the class budget is unsuitable. For example, Gentoo source
builds need measured limits. Queue time is separate from execution time.
A timeout is an actionable observation, not proof that the code is wrong.

Review the last 100 completed runs per check over at most 30 days each week.
The proposed false-positive budget is at most 1% **confirmed** unrelated
failures. With fewer than 100 samples, publish the counts and mark the estimate
insufficient. A retry that passes is only a candidate. Compare the same commit, inputs and
logs before you attribute a failure to infrastructure or a flaky test.

Keep cancellations, skipped checks and unknown causes separate. Report runtime
p95 and timeouts alongside the numerator and denominator. The audit below
collects configuration, not these outcome metrics.

If a check exceeds the budget, open a repair issue with an owner. Review it at the
next weekly triage. It never automatically disables a gate. Use the existing
[graduation criteria](../.github/green-criteria.yml) for tunaOS image checks;
the proposed false-positive budget does not replace that contract.

## Escalate a failed signal

1. Record the PR, commit SHA, check and failed run URL. Reproduce the relevant
   command. Fix deterministic code, lint, DCO or STE failures in the PR.
2. For an apparent transient failure, compare logs and, if justified, request
   one rerun of the same commit. Link both runs; preserve the first failure.
   Do not rebase or retry until a run happens to pass.
3. Request `needs-ci-signal` for a failure whose cause is still unknown.
   Link a CI repair issue with the evidence, owner and next review date.
   Contributors without label permissions can write the request in a comment.
   Maintainers create the label if absent. This is a triage request, not a
   successful check or a write-gate bypass.
4. Reserve `hold` for a concrete dependency, unresolved product/review issue or
   required check that still lacks valid evidence of success. State that reason.
   A PR can need CI diagnosis and still be held by an existing required gate.
   Remove each label only when evidence resolves its stated reason.

Only maintainers change enforcement. Any temporary advisory exception needs a
repair issue, scope, expiry date and evidence that explains how it preserves safety for releases. Never bypass a required check to clear the hold queue.

## Reproduce the organization audit

Run from this checkout with Python, PyYAML, `gh` and `GH_TOKEN`:

```sh
python3 scripts/audit-org-ci.py --output /tmp/tuna-ci-audit.json
# Limit a diagnostic run; names are case-sensitive as returned by GitHub.
python3 scripts/audit-org-ci.py --repo tunaOS --repo spindle --output /tmp/ci-pilot.json
```

The script discovers the current accessible repository set with pagination;
it does not freeze the issue's historical count of 27. It includes forks and
archived repositories, marked separately. It captures each default branch's
SHA, workflow triggers, job names, shared workflow refs, timeout declarations,
conditions and job/step `continue-on-error`. It reads classic branch protection
and effective branch rules (including inherited rulesets) separately. All API
calls are GETs; it never executes remote code or changes settings or labels.

An inaccessible protection endpoint (including HTTP 404) is **unknown**, not
proof that no protection exists. Empty observed rules do not resolve unknown
protection from classic settings. The report distinguishes absent workflows from truncated trees.
If the inventory is incomplete, the script writes its findings and exits nonzero.
Missing access to settings remains visible in JSON even when workflow inventory
succeeds. A fully observed audit only covers repositories visible to the token.

Review `required_status_checks` in both protection and effective rules against
the emitted check contexts. Inspect names with matrix expressions, external DCO Apps, conditional steps,
path filters and reusable callees. This script does not infer effective
enforcement from YAML or classify failures as flaky. It reports callee timeouts
as delegated, not absent. 

Inspect the
callee at the exact `uses` ref before filing drift. Rules that apply to another
integration or release branch need a separate review. This audit covers only the default
branch of each repository.

During weekly contributor triage:

1. Regenerate the JSON and attach it to the review record. Keep live inventories
   out of committed prose; the next run is the source of current state.
2. Review tunaOS, remora, bootc-migrate, spindle, tunaos-packages, scoop-bucket
   and xfce-linux first, then every remaining discovered repository. Assign an
   owner to each unknown setting, duplicate implementation and timeout gap.
3. Open per-repository adoption PRs with the shared implementation ref, expected
   check context, trigger coverage, timeout exception and local test evidence.
   Ask maintainers to reconcile required contexts after those PRs land.
4. Review the run sample and `needs-ci-signal` queue. Track repaired checks,
   unknowns and remaining holds by linked issues instead of a hand-copied count.

Cross-repository adoption PRs, maintainer protection changes and the first
30-day outcome sample remain rollout work under #3011. This document and the
audit supply a repeatable baseline; they do not certify org-wide adoption.
