# tunaOS Community Governance

**Status**: Proposed for maintainer adoption
**Tracking issue**: [#1168](https://github.com/tuna-os/tunaOS/issues/1168)
**Scope**: the tunaOS repository and the community spaces maintained by the tuna-os organization

This document describes how the project makes decisions, grants maintainer
authority, handles community concerns, and records changes. It complements the
[contribution ladder](COMMUNITY.md), [Code of Conduct](CODE_OF_CONDUCT.md), and
[RFC lifecycle](RFC-PROCESS.md); it does not replace any of them.

Until this proposal is adopted by the project lead, it is a reviewable policy
draft. Existing repository access and branch-protection settings remain the
source of truth for permissions.

## Principles

- **Open by default**: project discussions, proposals, and decisions happen in
  public GitHub issues, discussions, or pull requests unless privacy or security
  requires a restricted channel.
- **Earned authority**: access follows demonstrated, sustained contribution and
  is limited to the area that needs it.
- **Documented decisions**: important technical and process decisions link to
  the proposal and record the outcome, rationale, and follow-up work.
- **Reversible by default**: when evidence is incomplete, prefer a small,
  observable change with a review date over an irreversible commitment.
- **Respectful participation**: the Code of Conduct applies to every project
  surface, including issue comments, Matrix, events, and private reports.

## Roles and authority

Roles are responsibilities, not employment titles. One person may hold more
than one role, and a role can be shared as the community grows.

| Role | Responsibilities | Authority |
|---|---|---|
| **Project lead** | Sets project direction, owns the organization relationship, and resolves escalated project decisions. | Final authority for repository administration, maintainer appointments, releases, and decisions that cannot reach consensus. |
| **Core maintainer** | Reviews cross-cutting changes, architecture, CI, releases, and security-sensitive work; mentors area maintainers. | Merge authority for assigned repositories/areas, subject to required CI, CODEOWNERS review, and branch protection. |
| **Area maintainer** | Owns a documented area such as a variant, desktop, docs, or workflow; keeps it healthy and reviews changes. | Review and merge authority for the assigned area when CODEOWNERS and branch rules permit it; may request broader review. |
| **Trusted reviewer** | Provides recurring, high-quality reviews and triage without owning an area. | Review and recommendation authority; no merge or administrative access unless separately granted. |
| **Contributor** | Submits code, docs, tests, issues, and proposals. | May participate in every public decision and can propose changes to any area. |
| **Community moderator** | Keeps Matrix and other community spaces welcoming, applies the Code of Conduct, and routes support/questions. | May moderate conversations and apply documented space rules; cannot override technical or project decisions. |

The current maintainer list and area assignments belong in
[MAINTAINERS.md](MAINTAINERS.md). GitHub permissions must be no broader than the
role requires. No bot or Hive agent is a substitute for human maintainer
accountability.

## Becoming, changing, and leaving a maintainer role

1. A contributor demonstrates sustained, constructive work in the area: useful
   changes, reviews, triage, releases, documentation, or community support.
2. An existing maintainer proposes the appointment in a public issue or PR,
   naming the area, expected responsibilities, and access requested.
3. The project lead and at least one other maintainer review the proposal when
   that second maintainer exists. During the current single-maintainer phase,
   the proposal must remain open for public comment for at least seven days.
4. The decision and role are recorded in `MAINTAINERS.md`; access is granted
   only after the record is merged.

A maintainer may step down at any time by opening a short transition issue.
Inactive access should be reduced after six months without meaningful activity,
with notice and an opportunity to return. Removal for misconduct follows the
Code of Conduct process; removal of technical access is a safety action and
does not itself determine whether the person may continue contributing.

## How decisions are made

### Normal changes

Issues and PRs are the default decision record. The author states the problem,
scope, alternatives, risks, and how the result will be checked. Reviewers
should raise concerns with concrete evidence and suggest an alternative where
possible.

The project uses **lazy consensus**: after reasonable notice, silence is not a
veto, but a maintainer must not merge a change with an unresolved, substantive
objection. A maintainer records the decision in the issue or PR, including the
review window and any dissent. The existing target of reviewing contributions
within 48 hours is a service goal, not a promise that a decision is automatic.

### Cross-cutting or hard-to-reverse changes

Use the lifecycle in [RFC-PROCESS.md](RFC-PROCESS.md) for architectural and
process proposals. The RFC must identify an owner, options, risks, review
window, and success criteria. A merged RFC gets an ADR so the decision remains
discoverable after the implementation changes.

### Escalation

If reviewers cannot resolve a substantive disagreement:

1. Summarize the options and the unresolved evidence in the tracking issue.
2. Invite the relevant area maintainers and allow at least seven days for
   input, unless a security or release incident requires faster action.
3. The project lead decides, or explicitly defers/abandons the proposal, and
   records the rationale and a review date.

An appeal should add new evidence or identify a process violation; repeating a
settled preference does not reopen a decision. A later RFC can supersede a
decision when circumstances change.

### Emergency changes

Maintainers may act immediately to protect users, credentials, the build
pipeline, or the project’s legal/safety position. The actor must open a
post-incident issue within 48 hours, document what changed and why, and request
retrospective review. Security-sensitive details belong in the security channel
until disclosure is safe.

## Review, merge, and CODEOWNERS policy

- Every change goes through a PR unless it is an explicitly documented emergency
  action.
- Required CI and branch protection are mandatory; a maintainer cannot waive a
  failing safety or correctness gate without recording the reason and follow-up.
- `.github/CODEOWNERS` identifies accountable human reviewers. CODEOWNERS
  approval is required where branch rules require it, but CODEOWNERS alone does
  not grant merge authority.
- Each maintained sub-repository should keep its own CODEOWNERS file and link
  back to this policy. The narrowest applicable area owner reviews first; a
  core maintainer reviews cross-cutting changes.
- Hive agents may prepare changes, triage, and provide review input. A human
  maintainer owns the merge decision and any external communication.

## Community spaces and conduct

GitHub is the canonical place for technical decisions. Matrix and event spaces
are for support, coordination, and community discussion; a decision made there
must be summarized in a public GitHub issue or PR before it is treated as
project policy.

Moderation follows `CODE_OF_CONDUCT.md`. Reports should use the private security
advisory route when public reporting would expose sensitive information. A
moderator may pause a conversation, remove harmful content where the platform
allows it, and ask a maintainer to investigate; technical disagreement alone is
not a conduct violation.

## Accountability and review

The project lead should review this document and `MAINTAINERS.md` at least
quarterly, and after a major governance incident. The review should check:

- named maintainers and area ownership are current;
- access matches responsibilities;
- decisions and RFCs have recorded outcomes;
- community reports were handled consistently; and
- the contributor path has a next step from contributor to reviewer or
  maintainer.

Changes to this policy require a PR, public review, and a decision record in
the PR. The project lead records adoption or rejection in the tracking issue.
