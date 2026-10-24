# bootc / OSTree community engagement proposal

Prepared for [#3300](https://github.com/tuna-os/tunaos/issues/3300).
This is a maintainer handoff draft: no message has been sent, partnership agreed,
or meeting booked. A TunaOS maintainer must own external correspondence and any
commitment of testing capacity, speaking time, or release support.

## Contact route and claim boundaries

Start with the public community routes linked from the
[bootc README](https://github.com/bootc-dev/bootc#readme): its discussion forum
and the [bootc community page](https://docs.fedoraproject.org/en-US/bootc/community/).
Ask there which maintainer should receive the proposal before addressing an
email to an assumed lead. For OSTree-specific findings, use the discussion
routes in the [OSTree README](https://github.com/ostreedev/ostree#contact-and-discussion-forums).
These upstream sources were checked on 2026-10-24; recheck before sending.
Do not infer a CNCF working group, contact address, or sponsorship relationship
from the issue's target list. Ask bootc maintainers for an appropriate wider
cloud-native Linux introduction if they consider one useful.

Describe TunaOS as a desktop image factory using bootc. “Canonical desktop
reference implementation” is an aspiration requiring upstream agreement, not
a title TunaOS can award itself. Avoid blanket “production-ready” claims:
[green criteria](../GREEN-CRITERIA.md) and the generated
[matrix status](../MATRIX-STATUS.md) define evidence for individual cells.
Follow the [content claim checklist](../CONTENT-CLAIM-CHECKLIST.md) before sending.

## Initial email / discussion draft

Subject: Desktop lifecycle feedback and a small bootc collaboration proposal

Hello bootc maintainers,

TunaOS builds desktop OS images using bootc. We would like to contribute desktop
lifecycle feedback and explore whether a small collaboration would be useful to
your community. Our [source](https://github.com/tuna-os/tunaos) and
[build pipeline](../PIPELINE.md) describe the implementation; our
[verification criteria](../GREEN-CRITERIA.md) distinguish build success from
validated desktop behavior.

Would you be interested in reviewing a short desktop case study and, if it fits
your documentation policy, linking TunaOS as a downstream desktop example?
We would supply a reproducible update/rollback report for one agreed image and
bootc version, including failures and limitations. We would also welcome your
advice on the most useful lifecycle or UX issue to investigate first.

If useful, could we join an existing community meeting for a 20-minute kickoff?
We propose selecting one documentation improvement and one bounded test case,
then deciding together whether a recurring monthly discussion adds value.
A joint article could follow once we have measured results and both projects
have reviewed the text. Who would be the best contact for this?

Thank you,
[Sending maintainer: name and preferred public contact]

Before sending, replace relative document links with public GitHub URLs at the
reviewed commit, fill the sender identity, and attach a current evidence report.

## Proposed framework and quick wins

| Workstream | TunaOS offer | Upstream request | Completion evidence |
| --- | --- | --- | --- |
| Documentation link | Submit a concise downstream-example entry after invitation | Choose location and acceptable wording | Accepted upstream PR URL, or recorded decline |
| Lifecycle feedback | Reproduce one agreed install/update/rollback scenario | Identify a useful compatibility question | Public report with exact versions, digest, commands, logs, expected/actual behavior |
| Joint article | Draft “Desktop Meets Cloud-Native: bootc for Daily Drivers” around measured results | Technical review and optional coauthor | Both parties approve publication text and attribution |
| Monthly sync | Supply agenda and notes if an owner volunteers | Agree cadence and participants | Explicit opt-in and next meeting agreed; otherwise remain asynchronous |
| Canary testing | Propose an isolated VM trial of a candidate bootc release | Select candidate and reporting channel | Reproducible report; no automatic production promotion |

The documentation entry offered for upstream review is:

> TunaOS is a downstream desktop image factory using bootc. See its source,
> build pipeline, and per-image verification criteria for implementation details
> and current limitations.

Use public source links when submitting it. Upstream chooses whether and where
this belongs; acceptance does not imply support or endorsement.

## Kickoff agenda and testing scope

1. Five minutes: desktop lifecycle concerns and upstream priorities.
2. Five minutes: choose one image/architecture, stable baseline and candidate
   bootc version, with a named volunteer from TunaOS.
3. Five minutes: agree a disposable-VM install, update, reboot, desktop login,
   rollback and reboot scenario. Record image digests, bootc/OSTree versions,
   VM configuration, commands, logs and desktop observations for both versions.
4. Five minutes: select the documentation quick win and reporting channel;
   agree who writes notes and whether a follow-up is needed.

Keep candidate testing separate from release promotion. Existing
[testing guidance](../TESTING.md) and [green criteria](../GREEN-CRITERIA.md)
remain authoritative; this proposal adds no CI gate or promised coverage.
Route minimal bootc failures to bootc, OSTree-specific reproductions to OSTree,
and downstream integration failures to TunaOS. Remove credentials and personal
information before publishing logs.

After a successful pilot, offer a joint talk abstract about the measured desktop
lifecycle results. LPC, a KDE sprint, and a GNOME event are possible audiences,
not confirmed venues. A human speaker must verify the event's current CFP or
organizer route, obtain coauthor consent, and approve travel or other costs
before submission. Do not promise dates or a conference series.

## Maintainer follow-through

- Assign the sending maintainer and a testing volunteer in #3300 before outreach.
- Record the sent message URL (or date and a nonprivate summary), reply, agreed
  scope and next action in #3300. Keep private contact details out of the tracker.
- After the first reply, agree a kickoff time through the existing community
  process; do not create a recurring invitation without participant consent.
- If there is no reply, send one courteous follow-up after two weeks, then leave
  the proposal available for asynchronous feedback.
- Link accepted documentation, test reports and any approved publication from
  #3300. External engagement remains open until those outcomes are recorded.
