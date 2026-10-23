# DistroWatch — Project Submission Draft

> Draft for an authorized project representative; submission is not recorded.
> Tracking: [#2885](https://github.com/tuna-os/tunaos/issues/2885) and
> [#1333](https://github.com/tuna-os/tunaos/issues/1333).

## Submission process and evidence

Policy reference: DistroWatch's [Submit Distribution page](https://distrowatch.com/dwres.php?resource=submit)
(cached page text retrieved on 2026-10-23). It describes submission by **email**
with four fields: project name, website URL, a brief description including the
base distribution, and a link to installation media (ISO). It also says it does
not enter correspondence about listing, so **no reply is expected**. The
submitter must recheck the live page for current eligibility, recipient, and
waiting-list policy before sending, record the requirements with an access
date in #2885, and adapt the draft below. Do not promise a listing date or
purchase expedited evaluation.

Use a project-authorized contact identity. Before sending, check #1333 and
#2885 for an existing receipt to avoid duplicate submissions. Record the sent
date, email channel, and a redacted sent-email record in
[the outreach ledger](ADOPTION-OUTREACH-STATUS.md). The sent email is submission
evidence; do not require a reply or treat sending as acceptance. Keep contact
details and private correspondence out of public evidence. Record waiting-list
and live profile URLs separately: acceptance onto a waiting list is not a live
profile.

## Project description for review

TunaOS builds Linux desktop operating system images distributed as bootable
OCI containers. It uses bootc for image-based updates and rollback. Its build
configuration combines base distributions, desktop environments, and hardware
overlays in a manifest-driven image factory.

The project includes Enterprise Linux and community distribution bases,
including AlmaLinux, CentOS Stream, and Fedora.
Desktop options include GNOME, KDE Plasma, COSMIC, Niri, and XFCE; availability
varies by variant. See the build matrix for the combinations configured today
and the published verification evidence for the status of individual images.
TunaOS's repository is licensed under Apache-2.0; included upstream software
retains its respective licenses.

## Profile fields and variant summary

| Field | Source / proposed value |
|---|---|
| Name | TunaOS |
| Homepage | https://tunaos.org/ |
| Source | https://github.com/tuna-os/tunaos |
| Description | Adapt the project description above and name the base distribution of the selected installation media |
| Installation media (ISO) | Select a published ISO from [tunaos.org/download](https://tunaos.org/download); paste its direct ISO URL into the email and verify the artifact and checksum before submission |
| Repository license | [Apache-2.0](../LICENSE); not a blanket license for all image packages |
| Base distributions and variants | Generate from [tunaos.toml](../tunaos.toml); see command below |
| Desktops | Use each variant's configured flavors |
| **Architectures** | Images: x86_64, aarch64 (per configured variant/platform). ISOs: x86_64; aarch64 ISO publication is tracked in [#1592](https://github.com/tuna-os/tunaos/issues/1592). Do not infer ISO availability from container platforms |
| Image readiness | [MATRIX-STATUS.md](MATRIX-STATUS.md) and [green criteria](GREEN-CRITERIA.md); verify freshness before making a readiness claim |

Generate a reviewable variant summary at submission time:

```sh
python3 scripts/config.py show
```

Attach that output or link its commit in #2885 and summarize the configured
base distributions for the editor. Confirm actual downloadable artifacts as
well: configuration alone does not establish successful publication or boot.
Do not copy a second live-status matrix into this draft. Follow the
[content claim checklist](CONTENT-CLAIM-CHECKLIST.md) for release dates,
hardware, support, and readiness claims.

## Referral link and handoff

Proposed homepage URL for the listing:

```text
https://tunaos.org/?utm_source=distrowatch&utm_medium=referral&utm_campaign=project_profile
```

This is a proposed campaign URL, not deployed instrumentation. The site owner
must confirm query parameters survive navigation/redirects and appear in the
existing analytics export before supplying it to DistroWatch. Do not add a
tracking script or enable additional collection as part of a listing request.
If the editor requires a plain homepage URL, use the referrer-host fallback
specified in [ADOPTION-METRICS.md](../ADOPTION-METRICS.md#distrowatch-referral-measurement).

## Completion checklist

- [ ] Read the live submission policy and record verified requirements
- [ ] Verify profile fields, generated variant summary, downloads, and checksums
- [ ] Confirm project contact identity and analytics capability with their owners
- [ ] Submit once by email; record dated, redacted sent-email evidence in the outreach ledger
- [ ] Record waiting-list URL and live profile URL when provided
- [ ] Verify a test visit is captured; exclude it from reported referrals
- [ ] Publish monthly referral snapshots and the Q4 comparison by 2026-12-31

#2885 remains open until external submission, measurement activation, and the
Q4 report have evidence. This draft does not establish any of those outcomes.
