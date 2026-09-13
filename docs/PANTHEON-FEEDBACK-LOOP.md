# Pantheon packaging feedback loop

**Status**: maintainer-ready
**Tracking**: [tunaOS#1353](https://github.com/tuna-os/tunaos/issues/1353)
and the canonical [Pantheon packaging/bug triage tracker](https://github.com/tuna-os/tunaos/issues/1469)

Gurnard is TunaOS's Ubuntu 24.04/Noble variant with the Pantheon desktop. It
is a new packaging surface: upstream elementary targets elementary OS, while
Gurnard combines the Pantheon packages with an immutable bootc image. This
document defines how to invite useful public feedback and turn it into
actionable triage without presenting TunaOS as an elementary OS channel.

## Public invitation

Publish this invitation only after the Gurnard launch post and download link
are live. Use a public blog comment or reply and the TunaOS Matrix room
(`#tunaos:reilly.asia`); do not cold-DM users or elementary maintainers.

```markdown
Gurnard is TunaOS's experimental Ubuntu 24.04 + Pantheon image. We are
looking for people familiar with Pantheon or elementary OS to try the desktop
and report packaging or integration issues.

Please report one reproducible symptom per issue using the Pantheon bug form,
which asks for everything triage needs:
https://github.com/tuna-os/tunaos/issues/new?template=pantheon-bug.yml

The canonical tracker for this effort is
https://github.com/tuna-os/tunaos/issues/1469 — read it first for scope, then
file individual symptoms with the form. Please do not send private logs or
secrets.

This is feedback for TunaOS's packaging surface, not a request for upstream
elementary support. If a behavior also occurs on elementary OS, mention that
so we can separate upstream behavior from TunaOS integration work.
```

Adapt the words to the channel and follow its moderation rules. The launch
post is the canonical announcement. The invitation must link to it and to the
form, and must not repeat a full release pitch.

## Triage contract

Every report should receive an acknowledgement or a classification. Keep the
discussion public. The one exception is a report where the reporter has
disclosed sensitive data by accident.

Reports filed through
[`.github/ISSUE_TEMPLATE/pantheon-bug.yml`](../.github/ISSUE_TEMPLATE/pantheon-bug.yml)
arrive labelled `pantheon`, `bug`, and `needs-info`. Here `needs-info` is the
form's default, not a judgement. Replace it with one classification from the
table below. If a fact is still missing, keep the label and ask one question
in public.

| Classification | Meaning | Next action |
|---|---|---|
| `upstream` | Reproduces in the upstream Pantheon/elementary stack | Link the upstream report or documentation; do not promise a TunaOS fix |
| `packaging` | Missing, conflicting, or incorrectly configured Debian/PPA package or file | Identify the manifest/package change and add a focused follow-up |
| `image` | Bootc image, filesystem, service, update, or rollback integration | Capture the image tag and relevant service/log output; file a code issue |
| `installer` | Live ISO, first boot, or installation-specific behavior | Record ISO version and hardware; link installer evidence |
| `documentation` | Missing or unclear Gurnard/Pantheon instruction | File a small documentation task and link the corrected guide |
| `needs-info` | Reproduction or version details are missing | Ask one concise public follow-up; do not guess the cause |

Do not label a report `upstream` merely because it involves Pantheon. First
check whether the package set, display manager, image configuration, or
immutable update path changes the behavior. Conversely, do not promise to
patch upstream behavior in the Gurnard image without maintainer agreement.

## Maintainer checklist

Before inviting feedback:

- [ ] Gurnard/Pantheon is downloadable and the URL resolves to the current
      release or catalog entry.
- [ ] The post says `experimental` and names the tested architecture and
      hardware scope.
- [ ] The public tracker [#1469](https://github.com/tuna-os/tunaos/issues/1469)
      has the `bug`, `community`, and `outreach` labels.
- [ ] The six classification labels (`upstream`, `packaging`, `image`,
      `installer`, `documentation`, `needs-info`) plus `pantheon` all exist in
      the repo, so the form's default labels resolve and triage can apply a
      classification without inventing one.
- [ ] The invitation links to the form and the tracker, and does not ask for
      cold DMs.
- [ ] The maintainer or triager is available to acknowledge reports.

For each new report:

1. Confirm the Gurnard/Pantheon version, architecture, and reproduction path.
2. Add one classification label and link the relevant manifest, check, or
   upstream issue.
3. Separate packaging defects from upstream behavior in the issue summary.
4. Mark the first one or two small, reproducible follow-ups `good first issue`
   only after a maintainer has written acceptance criteria and confirmed that
   the task does not require elementary upstream access.
5. Record the outcome in the next adoption snapshot, including unresolved
   reports and any change to the download or docs funnel.

## Monthly feedback record

The adoption-metrics owner should add a row or short note for each snapshot.
Do not treat issue volume as a measure of quality by itself: a successful
invitation may initially increase reports because more users can find the
project.

| Snapshot | Invitation URL/channel | New Pantheon reports | Classified | Fixed/closed | Needs upstream | Gurnard downloads/docs signal | Notes |
|---|---|---:|---:|---:|---|---|---|
| [YYYY-MM] | [URL and blog/Matrix] | [N] | [N] | [N] | [N] | [value or not measured] | [context] |

The public tracker is the source of truth for individual reports. This table
is only a monthly summary and must not duplicate private reporter data.
