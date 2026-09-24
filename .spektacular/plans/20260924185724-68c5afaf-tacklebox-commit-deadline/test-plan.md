---
created_date: "2026-09-24"
document_status: final
closed_date: "2026-09-24"
---

# Test plan: 20260924185724-68c5afaf-tacklebox-commit-deadline

Manual checks for the success metrics that no unit test can cover. Automated coverage (bats `tests/bats/test_build_iso_tacklebox.bats`, pytest `tests/regressions/test_issue_1893_customize_commit_deadline.py`) is not repeated here.

## 1. First large-desktop ISO build after merge passes the commit step

- **What to measure**: tacklebox's post-customize `podman commit` completes for a multi-GB desktop; threshold: no `exit status 124` from the commit and no line `commit customized … (killed if it exceeded the 1800s cap`.
- **How**: after merge, dispatch a build of one previously failing cell, e.g. `gh workflow run live-iso-bootc.yml -f variant=skipjack -f flavor=xfce` (or wait for the scheduled `publish-iso-groups.yml` run covering marlin gnome/kde). In the log: `gh run view <run-id> --log | grep -E 'Tacklebox environment:|podman commit|commit customized|exceeded its'`.
- **Expected result**: the log shows `==> Tacklebox environment: TBOX_CUSTOMIZE_COMMIT_TIMEOUT=1800` (plus any job knobs), the `Building tacklebox @ ae93e9b…` line, and the build proceeds past the commit to ISO assembly. A commit that now takes > 600 s but < 1800 s is the expected shape.
- **Who / when**: the PR author, on the first CI run after merge; attach the run link to tunaOS#1893.

## 2. No commit-deadline failures on main for two weeks

- **What to measure**: count of ISO build jobs on `main` failing with tacklebox's commit timeout in the 14 days after merge; threshold: 0.
- **How**: `gh run list --branch main --created ">=<merge-date>" --workflow <each ISO workflow> --status failure --json databaseId` then for each run `gh run view <id> --log-failed | grep -E 'commit customized .*cap|exit status 124'`. ISO workflows: live-iso-bootc, publish-iso-groups, iso-e2e, luks-e2e, installer-smoke, installer-screenshots, weekly-desktop-screenshots, live-initramfs, reusable-build-artifacts.
- **Expected result**: 0 matches. If a cell fails at exactly 1800 s, do not raise the default blindly: record the measured time in docs/ci-troubleshooting.md row 42 and ask the maintainer (see plan Open Questions).
- **Who / when**: the maintainer or triage agent, 14 days after merge; close tunaOS#1893 on success.

## 3. A workflow-set TBOX_* knob takes effect on the container path

- **What to measure**: a job that runs tacklebox via the container path (`TACKLEBOX_FROM_SOURCE` unset) with an exported `TBOX_*` knob shows it on the container command line.
- **How**: locally as root: `export TBOX_CUSTOMIZE_NETWORK=host; sudo -E TACKLEBOX_FROM_SOURCE=0 ./scripts/build-iso-tacklebox.sh yellowfin gnome ghcr` and watch stderr; or `sudo -E bash -c 'set -x; source scripts/lib/common.sh; …'` to see the `podman run … --env TBOX_CUSTOMIZE_NETWORK=host --env TBOX_CUSTOMIZE_COMMIT_TIMEOUT=1800 ghcr.io/tuna-os/tacklebox:latest build …` argv.
- **Expected result**: `==> Tacklebox environment:` lists both knobs, and live-customize runs with host networking (no DNS failures of the nested-container kind).
- **Who / when**: optional, the next person who moves a job to the container path. Note `sudo` without `-E`/`--preserve-env` drops caller-set knobs (only the in-library 1800 default survives).
