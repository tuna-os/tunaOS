# TunaOS Roadmap

> Last updated: 2026-06-05 | See also: [Milestones](https://github.com/tuna-os/tunaOS/milestones)

## Current Status

| Variant | Base OS | Status | Desktop Environments |
|---------|---------|--------|---------------------|
| **Yellowfin** | CentOS Stream 10 | Stable | GNOME, GNOME 50, KDE, COSMIC, Niri |
| **Albacore** | AlmaLinux 10 | Stable | GNOME, GNOME 50, KDE, COSMIC, Niri |
| **Bonito** | Fedora 44 | In Progress | GNOME, GNOME 50, KDE |
| **Skipjack** | CentOS Stream 10 + COPR GNOME | COPR coordination | GNOME 49, GNOME 50 |
| **Redfin** | RHEL 10 | Experimental | GNOME |

## Q2 2026 — Stabilize Core Variants (April–June)

**Milestone:** [Q2 2026 - Stabilize Core Variants](https://github.com/tuna-os/tunaOS/milestone/1)

### Goals

- [ ] **CI Stabilization**: Resolve persistent build failures across variants (#226–#229)
- [ ] **Bonito Completion**: Fix `bootc container lint` issues, enable in CI matrix
- [ ] **Skipjack COPR Resolution**: Coordinate with upstream COPR for `gnome-shell-common` Obsoletes
- [ ] **Documentation Expansion**: ROADMAP.md, CONTRIBUTING.md, SECURITY.md, CODE_OF_CONDUCT.md
- [ ] **ISO Reliability**: Stabilize Live ISO builds and E2E smoke tests
- [ ] **RHEL 10 Redfin**: Expand from experimental to beta

### Key Deliverables

- Clean baseline builds for all variants (no `|| true` masking)
- Published ROADMAP.md and CONTRIBUTING.md
- Live ISO passing E2E smoke for all variants
- Bonito variant marked stable

## H2 2026 — Ecosystem Growth (July–December)

### Goals

- [ ] **Migration Guides**: Documented paths from Fedora Silverblue/Kinoite and Universal Blue
- [ ] **arm64 Support**: Multi-architecture ISO builds and GHCR images
- [ ] **GDX Stabilization**: NVIDIA driver and CUDA pipeline maturity
- [ ] **Community Growth**: First external contributors, published contributor guide
- [ ] **Semantic Versioning**: Adopt SemVer + date hybrid versioning scheme
- [ ] **Upstream Alignment**: Track CentOS Stream 11 development, Fedora 45

## Upstream Dependencies

| Component | Current | Target | Notes |
|-----------|---------|--------|-------|
| CentOS Stream | 10 | 10 | Tracking CS10 lifecycle |
| Fedora (Bonito) | 44 | 44 / 45 | Fedora 45 expected Q4 2026 |
| COPR (gnome-shell) | 49/50 | 49/50 | Obsoletes fix in progress |
| AlmaLinux | 10 | 10 | Tracking AL10 releases |
| RHEL | 10 | 10 | Redfin variant |
| bootc | latest | latest | Container-native boot |

## Community Targets

- **Q2 2026**: 50 GitHub stars, 5 active contributors
- **H2 2026**: 200 GitHub stars, 15 active contributors, first community PR merged

## How to Contribute

See [CONTRIBUTING.md](CONTRIBUTING.md) for setup and workflow. Strategic issues are labeled `roadmap` and `strategic`.

---

*Maintained by the TunaOS team. Updated by the strategist agent (hive-keen-mink).*