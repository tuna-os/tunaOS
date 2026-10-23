# Adopter case study program

Issue: [#3020](https://github.com/tuna-os/tunaos/issues/3020).
This process extends the [adoption call](ADOPTION-CALL.md). It captures real
usage; a star, contribution, download, or upstream dependency is not proof of
adoption. This document makes no new claims of adoption.

## Submit a report

Reply to the adoption call's Show-and-tell Discussion with the template below.
If that Discussion is not available, open a
[TunaOS issue](https://github.com/tuna-os/tunaos/issues/new) titled
`Adopter case study: <public name>`, or submit a documentation PR. Link any
existing adoption-request issue so reviewers can keep one source record.
You can submit written answers; an interview is optional. Aim for 1–2 pages.

All these routes are public. Omit private details about contacts, hostnames, users, credentials, and infrastructure. Use ranges for scale if you cannot disclose the numbers. Leave unknown or undisclosed fields marked
as such. Do not submit another organization's story without its permission.

```markdown
# <Approved public name>: <use case>

Report date (YYYY-MM-DD):
Organization type / industry:
Public organization or project URL (optional):
Representative's public handle and authority to speak for the organization:
Usage category: production / development / evaluation
Using TunaOS since (YYYY-MM):

## Problem and choice
What problem needed solving? What did you use before, and why try TunaOS?

## Deployment
Variant(s) and desktop(s) actually used:
Deployment scale (devices/users, or a range) and reporting period:
Workload and deployment/update approach:
Pilot scope versus ongoing production scope:

## Results and limits
What changed? Give a before/after measure, method, and observation period
where available. Label personal observations as qualitative feedback.
What did not work, and what workarounds or limitations remain?
What would you tell another team evaluating TunaOS?
Optional approved quote and public evidence links:

## Publication permission
I am authorized to share this report for <public name>.
Approved public name and attribution:
May TunaOS publish the final text in repository docs? yes / no
May TunaOS reuse the final text in a public blog post? yes / no
May TunaOS add the approved entry to ADOPTERS.md? yes / no
I will review and approve the exact text, quotes, links, and adopter entry
in the publication PR before publication.
```

## Capture and publish

1. A maintainer takes ownership of each response in #3020 and links its source
   record. Confirm that the representative can authorize the report. Do not
   treat a GitHub profile's employer field as confirmation.
2. Ask only for missing template fields. Check dates, deployment category, and
   the scope of results with the respondent. Distinguish self-reported benefits
   from measured results. Apply the [content claim checklist](CONTENT-CLAIM-CHECKLIST.md)
   to project claims. One user's production deployment does not establish general readiness for that variant.
3. Open a PR with the report at `docs/case-studies/<short-name>.md`. Add it to
   the [docs index](README.md) and link the public source response. Include
   only approved information. Omit logos without permission from their owner.
4. Request explicit approval of the exact final revision from the authorized
   representative in the PR. Approval must cover attribution, quotes, results,
   and each publication destination. Reconfirm approval after substantive
   edits. A submission or silence alone does not approve the final copy.
5. With separate listing consent, add a linked row to the matching section of
   [ADOPTERS.md](../ADOPTERS.md) in the same PR. Use Production only for
   confirmed ongoing production use; keep pilots in Development & Evaluation.
   An anonymous story is welcome but does not count as a named adopter.
6. After review and merge, record the publication PR in #3020. A maintainer can
   arrange a blog version only if the representative approved that destination. Handle later corrections or consent withdrawal through a follow-up PR, per the adoption call.
   Remove or amend the report and adopter entry together.

## Outreach queue

The outreach contributor should invite 5–10 willing teams through existing
relationships and public calls. These are candidate pools, not named adopters:

| Pool | Discovery route | Invitation route |
|---|---|---|
| Hacktoberfest contributors | [Contributor plan](HACKTOBERFEST-2026.md) | Existing opt-in contributor follow-up |
| Early stargazers and issue reporters | Voluntary usage reports in project discussions and issues | Reply in an existing usage conversation where an invitation is welcome |
| Fedora and AlmaLinux communities | Existing community contacts | Ask the channel owner to share the adoption call |
| Cloud-native infrastructure teams | Public bootc usage discussions | Invite teams that explicitly express interest |
| Universities and research institutions | Existing teaching or research contacts | Ask a known contact to share the call |

Do not scrape star lists for contacts, cold-DM people, or infer an employer's
usage from an individual's contribution. Keep the response record in the
adoption Discussion or linked issue. Link to that record from other channels.
An authorized outreach contributor can adapt this invitation:

> Does your team use or evaluate TunaOS? We welcome a short, voluntary
> [case study](https://github.com/tuna-os/tunaos/blob/main/docs/ADOPTER-CASE-STUDIES.md).
> Share your problem, deployment, benefits, and limitations. You approve the
> final text and choose whether ADOPTERS.md names your team. Evaluation reports
> are welcome too. Please share only information you can make public.

## Follow-up and evidence

Use #3020 for dated updates with links to invitations, source responses,
consent approvals, and publication PRs. Record each team's stage as invited,
responded, draft, approval requested, published, or declined. Record only
public names the team allows; do not commit a private prospect list. Close
out a declined invitation without repeated requests.

The issue proposes 2–3 reports before the November 1 metrics launch and 3–5
for Q4 2026. These are goals, not delivered results. At each checkpoint,
report the actual gap with linked evidence; never fill it with sample stories.
Keep invitations, responses, approved reports, and published reports separate.
Count each external organization once in the adopters metric, even when it
has several reports. Record adoption evidence under
[ADOPTION-METRICS.md](../ADOPTION-METRICS.md); internal project use and ecosystem
dependencies do not count as external adopters.
