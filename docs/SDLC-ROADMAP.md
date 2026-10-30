# SDLC roadmap: tunaOS and the tuna-os org

**Status**: an experiment from 2026-10-29 to 2026-11-26. Tracker:
[#4072](https://github.com/tuna-os/tunaOS/issues/4072).

**Source**: the agent specification for opt-in SDLC primitives in Hive and the
rollout to the tunaOS fleet. It has nine Hive items (HIVE-1..9) and seven org
items (TUNA-1..7). This file records what we did with each item, what we will
do, and what we will not do, and why.

## How we work

- Keep the fleet healthy first. Configure what Hive already ships before we
  write new Hive code.
- New Hive code lands on the `tuna/v6` branch of
  [tuna-os/hive](https://github.com/tuna-os/hive) (upstream `v6` plus our
  patches) and runs on School or Reef. We file it upstream after it has
  numbers from a live hive. `FORK.md` in that repository records each patch
  and the commit that each service runs.
- Each new Hive setting is opt-in: an absent key keeps upstream behavior.
- Each change lands alone, with a measurement that shows whether it worked.

## What the review found

| Spec assumption | What was true on 2026-10-29 |
|---|---|
| School and Reef run the `tuna-os/hive` fork | They ran the upstream image with a local binary mounted over it. The fork's default branch tracked upstream `v4`, which upstream froze on 2026-10-05. |
| The fleet is healthy enough to add policy | Both hives were crash-looping: 114 restarts in two days, from one bug in the shared session pool. |
| HIVE-1 needs new filter code | Upstream already had label exemptions, issue filters, reporter trust and CEL triggers. The gap was narrower: Hive admitted its own unacknowledged proposals. |
| HIVE-2 needs disclosure trailers | Hive PRs already carry `Hive-Run`, `Hive-Plan` and `Hive-Spec` trailers and `Co-authored-by` credit. |
| HIVE-8 needs a sensitive-path gate | `sentinel.sensitive_paths` and `auto_merge.human_merge_paths` exist. They needed tunaOS paths, not code. |
| The approval label is `direction-approved` | Hive reads `approved-direction`. |
| ISOs release every 14 days | `publish-isos.yml` publishes every Sunday at 22:00 UTC. |
| A `staging-matrix` branch | tunaOS `main` uses a merge queue. A second integration branch doubles the promotion work for one maintainer. |

## Spec items

### Done

| Item | What we did | Evidence |
|---|---|---|
| HIVE-1 proposal latch | `project.issue_filter.agent_proposal` holds a hive-filed proposal at admission until a maintainer acknowledges it. After the ACMM L6 decision it covers `agent/strategist`, `agent/outreach` and their title prefixes. Live on School and Reef. | Unacknowledged proposals that reach agents: 127 to 0. Upstream RFC [hivecommons/hive#15329](https://github.com/hivecommons/hive/issues/15329). |
| HIVE-1 CEL filters | We use the CEL triggers that upstream already ships. Rule `human-bug-first` kicks the scanner for an unclaimed human-filed issue with `priority/p0`, `bug` or `kind/bug`. `priority/p0` also ranks first in every kick. | Live on School and Reef since 2026-10-30. |
| HIVE-7 release clock, as TUNA-6 | `governor.freeze_windows` (new, opt-in). School's `iso-weekend` window pauses architect, strategist and outreach on Saturday and Sunday (UTC), before the Sunday ISO publish. The fixer agents keep running. | First live window: Saturday 2026-10-31. |
| HIVE-8 sensitive-path hold, as TUNA-4 | `auto_merge.human_merge_paths` on School lists `cosign.pub` and the two LUKS controls. Everything else in tunaOS merges on green checks (ACMM L6). | Live since 2026-10-29. |
| TUNA-1 architect drift | The HIVE-1 latch, plus a triage of 305 held proposals: 18 approved, 211 closed, 8 reopened. Policy is in `TRIAGE-POLICY.md` §6. | Open tunaOS issues: 218 to 104. |
| TUNA-2 required checks | The tunaOS `main` ruleset requires `Lint` and `Unit Tests`. The merge queue waits up to 180 minutes. Copilot reviews do not block a merge. | #1167 closed. |
| Org protection | An org baseline ruleset (no deletion, no force-push) on every repo. Tier A repos (`bootc-migrate`, `wootc`, `bootc-installer`, `fisherman`, `bootsahi`) and Tier B repos (`corral`, `tacklebox`, `iso-builder`) require checks. CODEOWNERS added where it was missing. | Unprotected repos: 10 to 0. See `docs/BRANCH-PROTECTION.md`. |

### Will do

| Item | Plan | Waits on |
|---|---|---|
| TUNA-2 PR canary cells | A PR check in `tuna-pr-images.yml` builds four cells (albacore:gnome, bonito:kde, marlin:cosmic, flounder:xfce) and runs the desktop contract. It runs only when a PR changes the Containerfiles, `build_scripts/**` or `tunaos.toml`. | Nothing; next pilot candidate. |
| HIVE-8 / TUNA-4 revert sheriff | After a merge breaks a required check on `main`, Hive bisects and opens a revert PR. The image-digest rollback stays a runbook (`runbooks/rollback-a-bad-image-promotion.md`) until the sheriff has a record. | A pilot on `tuna/v6`. |
| HIVE-6 / TUNA-3 soak promotion | A fast ring and an LTS ring, with `Soak-After:` promotion. | The two-ring LTS proposal must pass `RFC-PROCESS.md` first. The LTS variants are a product decision. |

### Will not do

| Item | Reason |
|---|---|
| HIVE-2 disclosure parser | Hive PRs already disclose their runs. Disclosure matters only for patches that go to external upstreams, which TUNA-7 covers by convention. |
| HIVE-3 dual-mode relay | No org repo needs a cosigned relay. Upstream-bound patches go out under a maintainer's name (TUNA-7). |
| HIVE-4 merge handoff (Prow, bors) | The org uses the GitHub merge queue, which Hive already drives. |
| HIVE-5 custom gate runners | Required CI checks are the custom gate, and Hive's merge gate already waits on them. |
| HIVE-7 blast-radius router | Path-filtered required checks on `main` give the same split (TUNA-2). |
| HIVE-7 CommitFest digest | The proposal latch and the #4072 reports cover the same need. |
| HIVE-9 profiles and public inbox | One config per hive does not need presets, and no org project uses a mailing list. |
| TUNA-2 `staging-matrix` branch | See the review table: the merge queue and path-filtered checks replace it. |
| TUNA-5 fault injection | This is test infrastructure, not SDLC policy. Track it in `tuna-os/corral`. |
| TUNA-7 relay mode in Hive | Kept as a convention: a maintainer sends upstream patches under their own name. |

## Work the rollout needed outside the spec

| Change | Result |
|---|---|
| Crash fix in the shared session pool | Restarts: 114 in two days to 0. Upstream has the same fix. |
| Credential broker fix (agents could not reach the omp auth broker) | Agent CLIs start again. Upstream PR [hivecommons/hive#15433](https://github.com/hivecommons/hive/pull/15433). |
| Path-glob fix (`**/` patterns did not match) | Merged upstream as hivecommons/hive#15387. |
| The fleet runs one tracked build | Hub, School and Reef run `tuna/v6`. The `v5` line is retired. |
| Agents off GitHub Copilot | The Copilot logins were removed. All 29 agents run `openai-codex/gpt-6-luna` through the omp auth broker. |
| Input classifier through omp | New opt-in `ioscan.classifier.backend: omp`, with no tools and an isolated profile. School and Reef use `anthropic/claude-haiku-4-5`. Kicks that carry issue text are no longer withheld. |
| Owner sign-in on the hives | A fix to the hive proxy lets GitHub device-flow sign-in start. |
| Human bug reports first | A tunaOS bug form that applies `bug`, the `human-bug-first` trigger, and `priority/p0` in the ranking. |

## Next steps

| Step | Owner | When |
|---|---|---|
| Check that the first freeze window paused only its three agents | Agent | After 2026-11-01 |
| Contributor sign-in through the hub (single sign-on). The hub side is built and staged. | Owner: create a GitHub OAuth app. Agent: wire up the hub, Caddy and the hives, Reef first. | When the app exists |
| A second GitHub App installation, so School and Reef stop sharing one API budget | Owner | Open |
| File the proxy sign-in fix and the omp classifier backend upstream, with live numbers | Agent | After one week live |
| Drop fork patches as upstream merges them | Agent | Each upstream release |
| Report the metrics against the baseline | Agent | 2026-11-26, on #4072 |

Rollback for any Hive change: `/srv/hives/compose.override.yaml` names the
binary of each service. Configuration and data backups are in
`/srv/hives/backups/`.
