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

## Executing a transition — where the version actually lives

A currency policy that does not say what to edit cannot be carried out, and
this repo has already paid for that. `scripts/get-base-image.sh`'s header
records a second hardcoded copy of the variant→base map drifting from
build-config:

    bonito    build-config: fedora-bootc:44      here: fedora-bootc:43

— "silently, because nothing compared them". The lesson it drew was to keep one
copy. The inventory below is the copies that remain, measured on 2026-08-14,
so the next transition is a checklist rather than a search.

**Authoritative.** Change this first; everything else follows it:

| Location | What |
|---|---|
| `.github/build-config.yml` (`bonito` entry) | `base_image:` — the pin every build resolves, and `description:` alongside it, which feeds docs and the image label |

**Must be changed in the same PR.** None of these derive from the pin above:

| Location | What | Note |
|---|---|---|
| `registry-map.yaml` → `fedora-bootc.tag` | duplicate of the base version | **no consumers** — nothing calls `registry_ref fedora-bootc`, so it can drift without any build failing |
| `Justfile:5` → `coreos_stable_version` | akmods/CoreOS stream for bonito | the value every real build uses |
| `scripts/build-image-inner.sh` → `COREOS_STABLE_VERSION` default | same, for direct invocation | had drifted to `41` while the Justfile said `43` |
| `build_scripts/overlay/overrides/nvidia/20-nvidia.sh` → `FEDORA_AKMODS_VERSION` fallback | negativo17 nvidia userspace tree | only a fallback; the live value is derived from the akmods bundle's dist tag |

**Prose that states the version** and goes stale without failing anything:
`ROADMAP.md`, `MIGRATION.md`, `.github/copilot-instructions.md`,
`docs/PIPELINE.md`, `docs/build-pipeline.md`, `docs/AGENT_GUIDE.md`,
`docs/LUKS-TPM.md`, `docs/FEDORA-MAGAZINE-PITCH.md`, `docs/adr/0003-mkosi-co-build-poc.md`.

`tests/bats/test_fedora_base_currency.bats` compares the pins that can be
compared, so the silent half of this list is no longer silent. The prose list
is not machine-checked — deliberately, since pinning strings in nine documents
would fail on every unrelated wording change — which is why it is written down
here instead.

## Relationship to other bases

This policy covers Fedora only. Other rolling/tracking bases (Sailfin/
openSUSE Tumbleweed, Marlin/Arch, Flounder/Debian Sid) already follow a
rolling model by construction and are out of scope here; RHEL-family bases
(Yellowfin/Albacore/Skipjack/Redfin) follow their own major-version cadence
and are covered by VARIANT-LIFECYCLE.md's general admission/exit criteria,
not this document.
