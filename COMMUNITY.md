# Community

## Getting Involved

> 🎃 **Hacktoberfest 2026**: We are participating! Looking for your first open-source PR? Check out our [good first issues](https://github.com/tuna-os/tunaOS/issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22) and join us on Matrix for maintainer office hours in October.

tunaOS is an open-source project building OCI-based Enterprise Linux desktops. We welcome contributors at all levels.

### Quick Start

1. **Try it**: `bootc switch --enforce-container-sigpolicy ghcr.io/tuna-os/yellowfin:gnome`
2. **Report issues**: [GitHub Issues](https://github.com/tuna-os/tunaOS/issues)
3. **Read the docs**: [CONTRIBUTING.md](CONTRIBUTING.md), [AGENT_GUIDE.md](docs/AGENT_GUIDE.md)
4. **Add yourself**: If your org uses TunaOS, add it to [ADOPTERS.md](ADOPTERS.md)

### Contribution Ladder

| Level | What you do | How to start |
|-------|-------------|--------------|
| **Tester** | Run images, report bugs | Install any variant, open issues |
| **Contributor** | Fix bugs, improve docs | Good first issues, PRs welcome |
| **Desktop maintainer** | Own a desktop flavor | Build and test regularly, review PRs |
| **Variant maintainer** | Own a distro variant | Monitor builds, fix breakage |
| **Core maintainer** | Architecture, CI, releases | Sustained contribution + trust |

### Contributor recognition and attribution

We recognize contributors for the work they actually contribute, while taking
care to distinguish human contributions from automated activity. Before
publishing a contributor spotlight or counting a contribution toward the
community's human-contributor metrics, maintainers should verify the commit
author and the contributor's identity. This keeps public thanks meaningful and
avoids attributing agent work to a person.

The `shimonenator` commits previously described as the project's first external
human contribution were confirmed on 2026-08-13 to be authored by the Google
Antigravity agent (`antigravity`). They remain useful project work, but are not
a human-contributor milestone; the search for and welcome to our first external
human contributor remains open.

### Communication

- **GitHub Issues**: Bug reports, feature requests, discussion
- **GitHub Discussions**: General topics, ideas, Q&A
- **PR Reviews**: All contributions reviewed within 48 hours
- **Matrix**: [#tunaos:reilly.asia](https://matrix.to/#/%23tunaos:reilly.asia) — real-time chat, weekly release notes, monthly office hours (see below)

### Matrix room cadence

The Matrix room is the project's real-time channel; this section documents
its recurring structure so it doesn't rely on any one person's memory to
keep going (#1136).

- **Weekly release notes** (Fridays, mirroring the [weekly boot
  report](https://github.com/tuna-os/tunaOS/issues?q=is%3Aissue+label%3Aboot-report)
  cadence): post a short summary of the week's [Generate
  Release](.github/workflows/generate-changelog-release.yml) runs and any
  notable boot-report findings. Template:

  ```
  📦 This week in tunaOS — <date>

  - Released: <variant/flavor list + dates, from `gh release list`>
  - Boot health: <link to this week's boot-report issue>
  - Notable changes: <1-3 bullets — new variant, fixed regression, etc.>
  - Full changelog: <link to the release/CHANGELOG.md entry>
  ```

- **Monthly office hours** (~30 min, announced 1 week ahead in the room):
  open Q&A / walkthrough slot. No fixed agenda beyond "bring questions."

- **`#new-to-tunaos` pinned message** — the three best entry points for
  someone new to the room:

  ```
  👋 New here? Start with one of these:

  1. Try it: bootc switch --enforce-container-sigpolicy ghcr.io/tuna-os/yellowfin:gnome
  2. Pick a starter task: issues labeled "good first issue"
     → https://github.com/tuna-os/tunaOS/issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22
  3. Read CONTRIBUTING.md and COMMUNITY.md (this file) before your first PR

  Questions are welcome any time — you don't need to wait for office hours.
  ```

- **Cross-posting GitHub Discussions**: when a Discussions thread gets real
  engagement (multiple replies, a maintainer answer, a decision), drop a
  one-line summary + link into the room. Keeps the room aware of
  async-first conversations without duplicating them live.

### Adoption Metrics

| Metric | Current |
|--------|---------|
| GitHub Stars | Tracked via GitHub API |
| Downloads | `ghcr.io/tuna-os` pull counts |
| Active variants | Yellowfin, Albacore, Skipjack, Bonito, Redfin |
| Active desktops | GNOME, GNOME 50, KDE, COSMIC, Niri |
| Adopters | [See ADOPTERS.md](ADOPTERS.md) — organizations using TunaOS |

### Code of Conduct

See [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md). We follow the Contributor Covenant.

## Project Governance

tunaOS is maintained by [@hanthor](https://github.com/hanthor) with automated assistance from Hive agents. Decisions are made via GitHub Issues and PRs. See [MAINTAINERS.md](MAINTAINERS.md) for the full maintainer playbook.
