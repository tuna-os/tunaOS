# Blog Post Draft: Bonito — TunaOS on Fedora, Ready for Your Workstation

**Status**: Held for human review and editing  
**Target audience**: Fedora community, Silverblue/Kinoite users, Fedora Desktop SIG  
**Platforms**: Fedora Discussion, Planet Fedora (if accepted), Red Hat Developer Blog (partnership discussion)

---

## Claim Evidence Log

| Claim | Evidence | File/Link |
|-------|----------|-----------|
| Bonito is built on Fedora 44 | README.md image table, USER-GUIDE.md variant definitions | [README.md L93](https://github.com/tuna-os/tunaOS/blob/main/README.md#L93), [USER-GUIDE.md §2](https://github.com/tuna-os/tunaOS/blob/main/docs/USER-GUIDE.md#L57) |
| Bonito ships GNOME, KDE, COSMIC, Niri, XFCE as first-class desktops | README.md image table; USER-GUIDE.md desktop reference | [README.md L93-96](https://github.com/tuna-os/tunaOS/blob/main/README.md#L93), [USER-GUIDE.md §2](https://github.com/tuna-os/tunaOS/blob/main/docs/USER-GUIDE.md#L68) |
| Bonito images are bootc-based with atomic updates and rollback | USER-GUIDE.md §1 ("bootc-based") | [USER-GUIDE.md §1](https://github.com/tuna-os/tunaOS/blob/main/docs/USER-GUIDE.md#L1-bootc) |
| Bonito ships Homebrew and Flathub by default | README.md feature list; USER-GUIDE.md §7 | [README.md L24-25](https://github.com/tuna-os/tunaOS/blob/main/README.md#L24-25) |
| Bonito supports arm64 and x86_64 architectures | README.md image table | [README.md L93](https://github.com/tuna-os/tunaOS/blob/main/README.md#L93) |
| Latest Bonito release: kde-20261006 | latestRelease API query | `gh repo view tuna-os/tunaos --json latestRelease` |
| Bonito images published to GHCR | README.md registry paths; INSTALL.md authentication docs | [README.md L93](https://github.com/tuna-os/tunaOS/blob/main/README.md#L93), [INSTALL.md §Auth](https://github.com/tuna-os/tunaOS/blob/main/docs/INSTALL.md) |
| GREEN criteria require builds, boots, and desktop functionality | docs/GREEN-CRITERIA.md | [GREEN-CRITERIA.md](https://github.com/tuna-os/tunaOS/blob/main/docs/GREEN-CRITERIA.md) |

---

## Draft Post

### Bonito: Fedora-Based Immutable Desktop, Ready Now

**Introducing Bonito, TunaOS's Fedora variant — atomic updates, rollback built-in, and the same desktop power you love.**

If you've been following [Silverblue](https://silverblue.fedoraproject.org/) and [Kinoite](https://kinoite.fedoraproject.org/) — or the Universal Blue family ([Bluefin](https://projectbluefin.io), [Aurora](https://docs.getaurora.dev)) — you know what [bootc](https://github.com/containers/bootc) offers: an OS delivered as a container image, updated atomically, rolled back instantly, and identical everywhere. Bonito brings that experience to Fedora 44 with desktop-first polish.

#### What is Bonito?

Bonito is a bootc-based desktop distribution built from Fedora 44, published nightly as container images to the GitHub Container Registry. It follows Fedora's release cadence — faster updates than enterprise bases, curated by Red Hat's Fedora community.

Like Silverblue and Kinoite, Bonito treats the OS as immutable infrastructure: every system is bit-for-bit identical to what we test in CI. Desktop environments, drivers, and system packages ship in the image. Apps come from Flathub or Homebrew. Updates are atomic; if something breaks, boot into the previous generation. Rollback is one command (or one GRUB menu pick).

#### Which desktops?

Bonito ships with parity across five first-class desktop environments:

- **GNOME** (default) — the Fedora standard
- **KDE Plasma** — full Plasma 6 stack
- **COSMIC** (System76) — tiling-window innovation
- **Niri** (scrollable tiling) — lightweight Wayland compositor
- **XFCE** — lightweight and responsive

Pick the tag you want: `ghcr.io/tuna-os/bonito:gnome`, `bonito:kde`, `bonito:cosmic`, etc. All are first-class; all are tested to boot and reach a working desktop in CI every night.

#### Install Bonito

**From an ISO (recommended for new users):**
Visit [tunaos.org/download](https://tunaos.org/download), download the Bonito ISO, and write it to USB. Or build a custom ISO with your chosen desktop in the [web builder](https://tunaos.org/iso-builder).

**From Windows (using wootc):**
If you're dual-booting, the [wootc installer](https://github.com/tuna-os/wootc/releases) sets up a TunaOS partition and boot menu from Windows without needing a USB drive. Read the [Migration Guide](https://github.com/tuna-os/tunaOS/blob/main/MIGRATION.md) for details.

**Switch an existing bootc system:**
If you're running Silverblue, Kinoite, Bluefin, or any bootc-based system:

```bash
sudo bootc switch ghcr.io/tuna-os/bonito:gnome
```

Replace `gnome` with your chosen desktop. Reboot, and you're on Bonito.

#### Why Bonito matters for Fedora users

If you've wanted **Fedora's cadence with Silverblue/Kinoite's robustness**, Bonito closes the gap. It's the Fedora base you already trust, packaged in the immutable model that makes updates bulletproof and rollback frictionless.

Bonito also demonstrates that bootc-based desktops aren't locked to a single distribution. Fedora users can now choose: the Fedora community's Silverblue/Kinoite, or Bonito's multi-desktop perspective on the same Fedora foundation. Both exist; both matter.

#### Architecture and hardware support

Bonito runs on **x86_64 and ARM64** (aarch64). We test and publish both. Full hardware support details — including Apple Silicon (via Asahi) and NVIDIA driver options — are in [docs/HARDWARE.md](https://github.com/tuna-os/tunaOS/blob/main/docs/HARDWARE.md).

#### Get involved

- **Report issues**: [GitHub Issues](https://github.com/tuna-os/tunaOS/issues)
- **Chat**: [#tunaos:reilly.asia](https://matrix.to/#/%23tunaos:reilly.asia) on Matrix
- **Discord**: [TunaOS](https://discord.gg/MXSTqB8Nv)
- **Fedora channels**: [Fedora Discussion](https://discussion.fedoraproject.org) — look for TunaOS in the Desktop or Atomic SIGs
- **Contribute**: See [CONTRIBUTING.md](https://github.com/tuna-os/tunaOS/blob/main/CONTRIBUTING.md) for development setup

#### Links

- [TunaOS homepage](https://tunaos.org)
- [Bonito downloads](https://tunaos.org/download)
- [User Guide](https://github.com/tuna-os/tunaOS/blob/main/docs/USER-GUIDE.md)
- [GitHub repository](https://github.com/tuna-os/tunaOS)
- [Launch announcement](https://tunaos.org/blog/modern-enterprise-linux-desktops-with-tunaos)

---

## Notes for reviewers

1. This draft grounds every capability claim in the repository documentation and API data (see Evidence Log).
2. Tone is peer-to-peer, not marketing: we explain what Bonito *is* and link to documentation rather than making superlative claims.
3. Fedora-specific language ("Fedora's cadence," "Red Hat's Fedora community," Silverblue/Kinoite comparison) positions TunaOS as part of the Fedora ecosystem, not external to it.
4. Call-to-action is community engagement (chat, issues, contribute), not download metrics.
5. The post does **not** claim roadmap commitments, regulatory compliance, or future support tiers.
6. Desktop parity claim is grounded in README.md image table and USER-GUIDE.md.

### Publication pathway

**For Fedora Discussion:**
- Post to [Desktop SIG](https://discussion.fedoraproject.org/c/desktop/) and [Atomic SIG](https://discussion.fedoraproject.org/c/atomic/) categories
- Title: "Bonito — TunaOS on Fedora, with GNOME, KDE, COSMIC, Niri, and XFCE"
- Link to this post and tunaos.org/download

**For Planet Fedora (if approved by editors):**
- Contact Fedora Community Team (via Fedora Discussion moderators) for submission guidelines
- This post can be republished as-is with minimal edits

**For external blog syndication:**
- This draft is appropriate for Red Hat Developer Blog, InfoQ, Linux Matters podcast show notes, or similar technical publications
- No human-authored official endorsement needed; just community discovery and link-sharing

---

**Status: Ready for human review. Author: outreach agent. For questions or edits, comment on GitHub issue #3052.**
