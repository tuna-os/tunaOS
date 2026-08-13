# Q4 2026 Promotion Calendar

> Status: **draft** — maintainer review and contributor availability are required
> before committing to dates or external outreach.
> Tracking issues: [#1166](https://github.com/tuna-os/tunaOS/issues/1166),
> [#1135](https://github.com/tuna-os/tunaOS/issues/1135) (Q1 2027 CFP prep).
> Planning window: September–November 2026.

This calendar turns the Fedora 45, All Things Open, and KubeCon + CloudNativeCon
North America moments into a small, coordinated promotion sequence. It assumes
that the project continues its weekly release cadence and that the relevant
release artifacts are green before publication. It also covers the CFP
*windows* for two Q1 2027 events (FOSDEM 2027, SCaLE 21x) — the events
themselves land after this calendar's own Sept–Nov 2026 range, but their CFPs
open inside it, which is the actionable part now.

## Calendar

| Window | Moment | Primary action | Owner / dependency | Deliverable |
|---|---|---|---|---|
| **Early September** | Q4 preparation | Confirm a maintainer or contributor who will attend either event; ask in the issue and Matrix. Confirm the Bonito/Fedora 45 status and collect links, screenshots, and current download instructions. | Outreach coordinator; maintainer confirms technical claims. | Named event contacts, asset checklist, and a single source of truth for links. |
| **September** | NVIDIA follow-up | Draft “CUDA on an Enterprise Linux desktop: TunaOS `-nvidia` flavors” as an optional companion post. Use the recovered `-nvidia` build results from [#1118](https://github.com/tuna-os/tunaOS/issues/1118) only after the current matrix is green. | Content owner; current amd64 and arm64 NVIDIA verification. | Reviewable draft and reproducible build/verification links. |
| **Fedora 45 release week (~October 20–24)** | Fedora 45 | Publish the Bonito/Fedora 45 release-week post. Cover support status, what changed, download links, and the weekly release/verified-boot cadence. Coordinate the first public release-notes digest with the post. | Bonito maintainer; release artifacts and [#1136](https://github.com/tuna-os/tunaOS/issues/1136) digest template. | tunaos.org/blog post, Matrix announcement, and release-notes digest. |
| **October 13–15** | All Things Open 2026, Raleigh | Treat this as an attendance and informal-demo window, not a CFP. If a contributor attends, offer a short Bonito or bootc demo and record questions and contacts for follow-up. | Named attendee; portable demo and stable download URL. | Attendance note, demo links, and follow-up queue. |
| **October 16–30** | Post-ATO follow-up | Publish a short event recap or Fedora post amplification. Route technical questions to the relevant project issues and avoid implying an official booth or talk. | Attendee plus outreach coordinator. | Recap, answered questions, and attributed referral links where practical. |
| **November 9–13** | KubeCon + CloudNativeCon North America 2026 | Use the event as a hallway-track and blog-tie-in opportunity, not a submission. Lead with Corral (Kubernetes-native VMs), bootc’s CNCF Sandbox context, and the desktop/container-fleet connection. | Named attendee; current Corral and bootc references. | One-page conversation brief, demo links, and qualified follow-ups. |
| **~October 2026** | FOSDEM 2027 CFP opens (event: Brussels, Feb 6–7 2027) | Finalize and submit the CFP abstract already drafted in [docs/CFP-FOSDEM-2027.md](./CFP-FOSDEM-2027.md) — confirm the exact portal-open date, record the demo video outlined there, and submit to the Containers devroom first. | Speaker/maintainer-designate; demo video and reviewed abstract. | Submitted CFP, tracked in [#1135](https://github.com/tuna-os/tunaOS/issues/1135). |
| **~November 2026** | SCaLE 21x CFP opens (event: Pasadena, March 2027) | Adapt the FOSDEM abstract for SCaLE's format and audience (broader open-source/platform-engineering mix, not container-specialist); confirm the exact portal-open date before submitting. No SCaLE-specific draft exists yet — write one from the FOSDEM abstract rather than from scratch. | Speaker/maintainer-designate. | Submitted CFP, tracked in [#1135](https://github.com/tuna-os/tunaOS/issues/1135). |
| **November 16–20** | KubeCon follow-up | Publish a concise recap or technical tie-in, with links to Corral and the relevant TunaOS documentation. Capture questions that should become docs or issues. | Attendee plus Corral maintainer. | Recap, documentation/issues backlog, and referral summary. |

## Fedora 45 release-week post

The post should be drafted in September and held for the confirmed release
window. Suggested outline:

1. What Fedora 45 means for Bonito and its current support status.
2. The immutable desktop workflow: bootable OCI image, atomic updates, and
   rollback.
3. The current image/download links and architecture coverage, checked against
   the release artifacts on publication day.
4. What is new in the release and where readers can find the release notes.
5. A clear invitation to try Bonito, join Matrix, or contribute feedback.

Do not promise Fedora 45 support until the corresponding image has passed the
normal release gates. If the Fedora release date moves, move this post and the
digest together; the event and KubeCon dates remain independent calendar items.

## Event conversation briefs

### All Things Open

- Position TunaOS as an open-source, bootable-container desktop project.
- Demonstrate a stable image and the normal install/update/rollback path.
- Ask whether the person wants a follow-up link; do not collect personal data
  in a public issue.
- Record recurring questions and route them to documentation or issues.

### KubeCon + CloudNativeCon North America

- Connect TunaOS’s image model to the operational model familiar to a
  Kubernetes audience.
- Use Corral as the primary companion-project example: declarative VMs,
  snapshots, and GPU passthrough where those claims are current and verified.
- Mention bootc’s CNCF Sandbox status only with the canonical upstream link.
- Keep the discussion explicitly informal: no booth, talk, or CFP should be
  implied by this plan.

## Launch checklist

- [ ] Maintainer confirms the Fedora 45 support claim and release-week date.
- [ ] Bonito image, download page, release notes, and verification links are
      checked on publication day.
- [ ] A contributor volunteers for All Things Open and/or KubeCon NA.
- [ ] Demo hardware and a reliable network-independent demo path are tested.
- [ ] Drafts receive technical review before publication.
- [ ] Matrix announcements link to the canonical post rather than duplicating
      changing technical details.
- [ ] Referral links and notable questions are recorded in the follow-up notes.
- [ ] Any resulting docs or engineering work is filed as a separate issue.

## Related work

- [#1118](https://github.com/tuna-os/tunaOS/issues/1118) — NVIDIA image build
  recovery and verification.
- [#1136](https://github.com/tuna-os/tunaOS/issues/1136) — release-notes digest.
- [#1137](https://github.com/tuna-os/tunaOS/issues/1137) — Fedora Magazine pitch.
- [#1147](https://github.com/tuna-os/tunaOS/issues/1147) — release cadence and
  green Generate Release runs.
- [#1159](https://github.com/tuna-os/tunaOS/issues/1159) — Q4 planning kickoff.
