# Fedora Base Currency Policy

**Status**: DRAFT — proposed 2026-08-13 by the strategist agent for review
**Owner**: tuna-os (hanthor) / strategist
**Tracks**: #1171 (Fedora 45 planning), #272 (Bonito / Fedora 44 GA), #637 (rawhide variant)

## Purpose

tunaOS currently builds **two** Fedora-base variants simultaneously — Bonito
(Fedora 44) and Bonito Rawhide — with no written policy for which Fedora
release(s) the project commits to tracking, or when a new Fedora release
starts a base-currency transition. Fedora ships a new release roughly every
six months (Fedora 45 is expected ~October 2026); without a policy, each
transition is decided ad hoc, and outreach can promote a release ("Fedora 45
is coming" — #1137, #1166) before the product has a tracked plan for it, as
#1171 flagged.

## Policy

tunaOS tracks Fedora bases on an **N (current stable) + rawhide** model,
**one base transition at a time**:

1. **N (current stable)** is the GA-track base — e.g. Bonito tracks Fedora 44
   today. This is the release users are told to expect stability from.
2. **Rawhide** is tracked in parallel as a preview/early-warning lane (Bonito
   Rawhide, #637) — it exists to catch breakage before it lands in the next
   stable, not to ship a second GA product.
3. When a new Fedora stable ships, it does **not** immediately become a new
   tunaOS base variant. Planning for the new base (N+1) starts only after
   the current base (N) reaches GA per [VARIANT-LIFECYCLE.md](VARIANT-LIFECYCLE.md)
   — i.e. Fedora 45 base planning is sequenced **after** Bonito (Fedora 44)
   GA (#272), not in parallel with it. Running two incomplete Fedora GA
   efforts at once is the exact failure mode #1171 and the Q3 mid-quarter
   review (#1299) both flagged.
4. Once N+1 GA work starts, the previous stable (N) is retired from active
   development per the exit criteria in VARIANT-LIFECYCLE.md — tunaOS does
   not carry more than one GA-track Fedora stable base at a time.

## Fedora 45 sequencing

- **Now (Q3 2026)**: Bonito (Fedora 44) GA is the active goal (#272, Q3
  milestone). Bonito Rawhide (#637) continues as the preview lane and is the
  earliest signal for Fedora 45-era breakage, since rawhide already tracks
  ahead of 44 GA.
- **Trigger for Fedora 45 base planning**: Bonito (Fedora 44) reaches GA
  per VARIANT-LIFECYCLE.md exit criteria, or the Q4 checkpoint determines #272
  is descoped/carried — either way, #1171 is the tracking issue for
  standing up Fedora 45 base work, and should not open a second parallel
  GA effort while #272 is still open.
- **Outreach coordination**: Fedora 45 promotion (#1137 Fedora Magazine
  pitch, #1166 Q4 promotion calendar) should message Fedora 45 support as
  planned/upcoming, not shipped, until this policy's trigger condition is
  met and #1171 reports base readiness.

## Relationship to other bases

This policy covers Fedora only. Other rolling/tracking bases (Sailfin/
openSUSE Tumbleweed, Marlin/Arch, Flounder/Debian Sid) already follow a
rolling model by construction and are out of scope here; RHEL-family bases
(Yellowfin/Albacore/Skipjack/Redfin) follow their own major-version cadence
and are covered by VARIANT-LIFECYCLE.md's general admission/exit criteria,
not this document.
