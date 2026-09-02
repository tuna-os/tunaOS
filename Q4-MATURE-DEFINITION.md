# Q4 2026 "Mature" — Definition of Done

**Milestone**: Q4 2026 "Mature" (milestone #3, closes 2026-12-30)
**Tracker**: #1637 | **Prepared**: 2026-08-14 | **Decision authority**: maintainer

This document defines what "Mature" means operationally for tunaOS at the end of Q4
2026. It exists because Q3 demonstrated the cost of a milestone without exit
criteria: four strategic goals sat open with zero movement until a forced 08-22
checkpoint (#1299). Q4 must close with evidence, not wishes.

---

## Principles

1. **A goal is done when its exit criterion is met with evidence** — a merged PR, a
   published artifact, a live ruleset, a public snapshot. "In progress" is not a status.
2. **Every Q3 descope lands on a named Q4 tracker with a first-PR date** — decided at
   the 08-22 Q3 checkpoint, not discovered at Q4 close.
3. **"Mature" is falsifiable** — the claim requires a public adoption artifact
   (ADOPTERS.md), not vibes.
4. **Milestone fidelity is checked monthly** — every tracker attached at creation,
   milestone count matches reality (#1307 ritual).

---

## Q4 Goal Exit Criteria

| Goal | Tracker | Exit criterion (evidence required) |
|------|---------|-------------------------------------|
| Adoption metrics / usage telemetry | #1174 | First monthly download/usage snapshot **published by 2026-11-01**; dashboard or doc with numbers, not prose |
| Adoption evidence | #1348 | ≥1 production adopter listed in ADOPTERS.md with a verifiable reference (deployment, testimonial, case study) |
| Community governance model | #1168 | Governance doc merged (maintainer roles, decision rights, contribution ladder) and referenced from CONTRIBUTING.md |
| Branch protection + required CI | #1167 | Active `main` ruleset on tunaos contains a `required_status_checks` rule for `lint`, `lint-summary`, and `unit-tests`; verify the rule and a clean merge-queue evaluation from a non-bypass PR |
| Release automation | #1186 | Scheduled releases for **all supported flavors** (kde/xfce/cosmic/niri + gnome) with assets; ≥2 consecutive weekly cycles green |
| Package signing / SBOM | #1187 | Signed SBOM attestation present on every published release artifact org-wide (not just gnome); verification docs public |
| Supply chain hardening | #1193 | Dependency-freshness automation healthy org-wide: no halted Renovate configs, org automerge gate enforced (#1636, #1612) |
| Variant lifecycle policy | #1175 | VARIANT-LIFECYCLE.md enforced: every new variant passes admission gate; Beta→Stable exit criteria documented and applied |
| Tacklebox decoupling | #1192 | Tacklebox core decoupled from tunaOS build pipeline per original scope (#306); CI consumes it as an external dependency |
| Upstream snapshot automation | #1194 | Snapshot automation for upstream bases running on schedule (weekly) with drift reporting |
| Fedora 45 base readiness | #1171 | Fedora 45 base-variant planning sequenced after Bonito GA (#272) per FEDORA-BASE-POLICY.md; currency policy documented |
| Bonito (Fedora 44) GA *carryover* | #272 | **If descoped at 08-22**: Beta→Stable exit criteria met, GA release published with assets, ROADMAP status flipped to Stable |
| Redfin (RHEL 10) alpha *carryover* | #1123 | **If descoped at 08-22**: local-build alpha documented and reproducible per docs/rhel-setup.md; automated path scoped or explicitly out of scope with reason |

---

## What "Mature" Means at Q4 Close (summary claim)

At 2026-12-30, the org can claim "Mature" only if **all of** the following hold:

- [ ] Downloads are verified working and release cadence is multi-flavor, not gnome-only
- [ ] Adoption metrics snapshot exists (published 11-01) and ADOPTERS.md has ≥1 production entry
- [ ] Branch protection is enforced on the primary repo
- [ ] Every release artifact carries a signed SBOM
- [ ] Dependency freshness automation is healthy org-wide
- [ ] Governance and variant-lifecycle docs are merged and enforced
- [ ] All Q3 descopes are either completed or explicitly re-scoped with owners

---

## Monthly fidelity check (starting 2026-09-30)

| Date | Check |
|------|-------|
| 2026-09-30 | Q3 closes; Q4 tracker list finalized with descope decisions recorded |
| 2026-10-31 | Monthly: milestone count vs tracker states; adoption snapshot draft review |
| 2026-11-30 | Monthly: milestone count; mid-quarter checkpoint (format per Q3 #1299) |
| 2026-12-30 | Q4 closes; exit criteria verified item-by-item; ROADMAP updated |

---

*Prepared by strategist agent (ACMM L6 — full mode). Related: #1637, #1299, #1307, #1348.*
