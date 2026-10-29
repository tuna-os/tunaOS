# SDLC roadmap: tunaOS and the tuna-os org

**Status**: Phase 0 shipped 2026-10-29. Later phases are proposals.
**Source**: a review of the SDLC spec for Hive (HIVE-1..9, TUNA-1..7). The
review compared the spec with the live School and Reef hives, the Hive code
in `hivecommons/hive` and `tuna-os/hive`, and the org's repositories.

Each change lands alone, with a measurement that shows whether it worked.
The order is: keep the fleet healthy, configure what Hive already ships,
raise repository protection, then write new Hive code. New Hive code starts
as an upstream RFC. A reference implementation in `tuna-os/hive` runs on one
of our spokes before the RFC asks for review.

## What the review found

| Spec assumption | What is true (2026-10-29) |
|---|---|
| School/Reef run the `tuna-os/hive` fork | They run `ghcr.io/hivecommons/hive:v6-latest` on the Spindle VPS (`/srv/hives`) with a locally built `hive` binary bind-mounted over the image's. The fork's default branch tracks upstream `v4`, which upstream froze on 2026-10-05. |
| The fleet is healthy enough to add policy | Both spokes were crash-looping: 114 restarts in two days, all one bug (`SendKick` double-unlock in the shared-session pool). Each restart re-armed GitHub slow-start caution, so the hives spent most of their time idle. |
| HIVE-1 needs new exclusion/approval code | Upstream already has `governor.labels.exempt`, `issue_filter.require_labels`, `hard_suppress_labels`, `reporter_trust`, the #5117 PR-side hold and its `approved-direction` label. The missing piece is narrower: hive-filed proposals are admitted, and #5117 only fires after an implementer has opened the PR. |
| HIVE-8 needs a sensitive-path gate | `sentinel.sensitive_paths` exists and is on by default (workflows, CODEOWNERS, `Justfile`, …). It needs tunaOS-specific paths, not code. |
| HIVE-2 needs disclosure trailers | Hive PRs already carry `Hive-Run`/`Hive-Plan`/`Hive-Spec` trailers and `Co-authored-by` credit. Disclosure matters only for patches sent to external upstreams. |
| The label is `direction-approved` | Hive reads `approved-direction`. |
| Duplicate PRs are agent drift | 19 of the 21 open same-title PR pairs are Hive adoptions (`Supersedes #N`). All 25 merged adoptions closed their originals, so these are in-flight work, not leaks. Review the App PR; the original closes itself. |
| A long-lived `staging-matrix` branch | tunaOS `main` runs a merge queue. A second integration branch doubles promotion work for one maintainer; path-filtered required checks give the same blast-radius split on `main`. |

Queue at review time: tunaOS had 130 open PRs (101 under 7 days old) and 218
open issues. Hive filed 171 of the issues. No maintainer had acknowledged
127 of those, which are `[architect]`/`[strategist]`/`[outreach]` proposals.

## Phase 0: shipped 2026-10-29

| Change | Where | Verification |
|---|---|---|
| Fix the `SendKick` double-unlock crash | `tuna-os/hive` `fix/shared-pool-kick-relock` (6ad4ed4), on reef; school runs it inside 911e5c0 | Regression test fails before and passes after. The `crux/agent` suite has the same 4 failures as the deployed commit. At 12:31Z, reef had 0 restarts in 7 h 11 min and school 0 in 7 h 02 min (before: 78 and 36 in two days). |
| Admission-side #5117: hold unacknowledged hive-filed proposals | `tuna-os/hive` `feat/agent-proposal-gate` (911e5c0, with the fix), on school with `project.issue_filter.agent_proposal` | Unit tests cover the batch and webhook paths. Live: school holds 189 proposals in 11 repos, 62 of them in tunaOS. That is the dry-run count: 127 proposals, less 65 that earlier filters (decision, hold) already catch. |
| Agents leave newcomer issues alone | School `governor.labels.exempt` += `good first issue`, `hacktoberfest`, `starter` | Parsed by the deployed config loader. |
| `approved-direction` exists where maintainers need it | Label created on all 11 School repos | — |
| Policy says what is enforced | `TRIAGE-POLICY.md` §6 | — |

Rollback: `/srv/hives/compose.override.yaml` names the binary of each
service. To revert a service, delete its entry and run
`docker compose up -d <svc>`. The older binary ignores `agent_proposal`.
Config backups are in `/srv/hives/backups/`.

## Phase 1: config and fleet hygiene (weeks 1–2)

1. **Converge the fleet onto one tracked build.** Hub, reef and school run
   three binaries today. All three come from upstream `v5` with fork
   patches; only the image tag says `v6`. Point the fork's default branch at
   that upstream line. Keep the two patches above until upstream has them;
   upstream #15049 already has the crash fix. Record the commit of each
   deployed binary in `FORK.md`. Exit: `hive --version` on each spoke names
   a commit on a pushed branch.
2. **Agent-proposal gate on Reef.** Same `issue_filter.agent_proposal` block.
   Exit: one week of Reef with no merged PR whose only rationale is an
   unacknowledged proposal.
3. **Merge guard for tunaOS (TUNA-4). Done 2026-10-29.** School's
   `auto_merge.human_merge_paths` lists `cosign.pub`, `registry-map.yaml`,
   `.github/green-criteria.yml`, `tunaos.toml`,
   `files/usr/bin/tunaos-luks-tpm2-enroll` and
   `files/usr/share/ublue-os/just/60-tunaos-luks.just`. Hive holds a PR that
   changes one of them, for every author, and a person must merge it. Use
   exact paths: Hive's matcher does not match patterns like `**/*luks*`
   (hivecommons/hive#15386). The build makes `.github/build-config.yml`
   from `tunaos.toml`, and Git ignores it, so a PR cannot change it. Guard
   the source.
4. **Close #1167.** Add the `required_status_checks` rule from
   `docs/BRANCH-PROTECTION.md` to the `main` ruleset. The merge queue runs
   today with no required check.
5. **Drain the adoption pairs.** Review the 19 App PRs that supersede a
   contributor PR. Each original closes when its App PR merges.
6. **Decide the held proposals.** Approve, close, or fold each into an RFC.
   The gate stops new work on them; it does not decide them.
7. **Split the GitHub budget.** School and reef use one App installation and
   share its 6,150 requests per hour. The budget ran out at 05:01Z and at
   06:06Z on 2026-10-29, which stops enumeration on both hives. Give each
   spoke its own installation, or lower the sweep rates. Exit: no
   `rate limit … exceeded` log line for a week.

## Phase 2: org protection baseline (weeks 3–6)

Measured 2026-10-29 across the 43 active repos:

| Gap | Repos |
|---|---|
| No branch protection | tuna-desktop, ccleft, compass, quickcast, rust-atomicwrites, iced, rdocx, libcosmic, PaperWM, hive-operator |
| Protected, zero required checks, no ruleset | 12, including fisherman and bootc-installer |
| Required review on the default branch | only `tuna-os/hive` |
| No CODEOWNERS | 12 |
| Hive PRs opened in the last 30 days | 533, across 42 repos |

Order by blast radius:

1. **Tier A, installers and boot** (`bootc-migrate`, `wootc`,
   `bootc-installer`, `fisherman`, `bootsahi`): ruleset with required
   checks, required human review, and sentinel paths for the whole repo. Hive
   never auto-merges here.
2. **Tier B, image and build core** (`tunaOS`, `tunaos-packages`, `corral`,
   `tacklebox`, `iso-builder`): required checks. For tunaOS, add a PR check
   for the blast-radius split (TUNA-2). It builds four canary cells from the
   checkout (albacore:gnome, bonito:kde, marlin:cosmic, flounder:xfce) and
   runs the desktop contract on them. It runs when a PR changes
   `Containerfile.final`, `Containerfile.el10`, `Containerfile.overlay`,
   `build_scripts/**` or `tunaos.toml`. Put it in
   `tuna-pr-images.yml`, which already builds Tuna images on PRs.
   `just test-canary-cells` runs the same contract on the published images:
   it is a post-publish canary, not a PR gate.
3. **Tier C, apps, docs and tools**: one org ruleset (no force-push, no
   deletion, required CI where it exists).
4. **Tier D, upstream forks** (PaperWM, libcosmic, iced, rdocx,
   rust-atomicwrites): protect the default branch. Upstream-bound patches go
   out under a maintainer's name (TUNA-7) by convention until Phase 3 decides
   whether that needs Hive support.

## Phase 3: Hive features via upstream RFC (week 6 onward)

We file each item upstream when its phase starts. At that time, a reference
implementation runs on a Tuna OS spoke, and the RFC cites its numbers.

| RFC | Spec item | Why we need it | Reference spoke |
|---|---|---|---|
| Admission-side #5117 for hive-filed proposals ([hivecommons/hive#15329](https://github.com/hivecommons/hive/issues/15329)) | HIVE-1 | Shipped in Phase 0; filed upstream 2026-10-29 | school |
| Lane freeze windows (scheduled per-lane pause) | HIVE-7 / TUNA-6 | Biweekly ISO stabilisation: pause architect/strategist/outreach on days 11–14, keep ci-maintainer and quality. Repo pause exists but is all-or-nothing. | school |
| Soak-gated promotion | HIVE-6 / TUNA-3 | Only if the two-ring LTS proposal passes `RFC-PROCESS.md` first; which variants form the LTS ring is a product decision. | — |
| Post-merge revert sheriff | HIVE-8 / TUNA-4 | After Phase 2 gives tunaOS required checks to bisect against; the image-digest rollback stays a runbook (`runbooks/rollback-a-bad-image-promotion.md`) until then. | school |

## Not planned

| Spec item | Reason |
|---|---|
| HIVE-4 merge-queue handoff (Prow/bors) | The org uses GitHub's merge queue, which Hive already drives. |
| HIVE-5 assertion-density / MC/DC gates | Required CI checks are the custom gate. Hive's merge gate already waits on them. |
| HIVE-9 public-inbox adapter, profile presets | No mailing-list project in the org; one hive config per spoke does not need presets. |
| TUNA-5 power-loss fault injection | Worth doing in `corral`, but it is test infrastructure, not SDLC policy. Track it there. |
