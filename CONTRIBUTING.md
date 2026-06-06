# Contributing to TunaOS

Thank you for contributing to TunaOS — bootc-based desktop OS images on Enterprise Linux.

## Quick Start

```bash
# Install prerequisites (Homebrew recommended for consistency with CI)
brew install just podman shellcheck shfmt

# Clone and set up
git clone https://github.com/tuna-os/tunaOS.git
cd tunaOS
just fix && just check
```

## Pre-Commit Workflow (mandatory)

Always run before every commit:

```bash
just fix     # Format shell scripts and Justfile
just check   # shellcheck, yamllint, jq, actionlint
git diff     # Review your changes
```

Commits must be signed with DCO: `git commit -s`

## Building Images

```bash
# Build a single variant (fastest test — ~25-35 min with warm cache)
just yellowfin base

# Build the full flavor chain
just yellowfin base && just yellowfin dx && just yellowfin gdx

# Build other variants
just albacore base
just skipjack base
just bonito base
```

**First build:** ~45-60 minutes (cold cache). **Never cancel builds early.**

## When to Build

| Change type | Build required? |
|---|---|
| `Containerfile*`, `build_scripts/*`, `system_files*` | **Yes — always** |
| `scripts/*` | Sometimes (if testing ISO/VM) |
| Docs, CI workflows, README | No |

## Pull Request Process

1. Fork the repository and create a feature branch
2. Run `just fix && just check` before pushing
3. Ensure your commits are signed (`git commit -s`)
4. Open a PR against the `main` branch
5. CI runs builds and image diffs automatically
6. Address feedback from maintainers

## Architecture

See [`docs/AGENT_GUIDE.md`](docs/AGENT_GUIDE.md) for a detailed architecture overview:
- Variants and flavors
- Build pipeline stages
- CI/CD matrix configuration
- Key files and environment variables

## Documentation

- [Agent Guide](docs/AGENT_GUIDE.md) — complete reference for contributors
- [Build Pipeline](docs/build-pipeline.md) — CI/CD overview
- [Improvement Plan](docs/IMPROVEMENT_PLAN.md) — roadmap and progress
- [Testing Guide](docs/TESTING.md) — ISO e2e test harness
- [mdBook](docs/book/src/introduction.md) — user-facing documentation

## Community

- [GitHub Issues](https://github.com/tuna-os/tunaOS/issues)
- [Matrix Chat: #tunaos:reilly.asia](https://matrix.to/#/%23tunaos:reilly.asia)
- [Universal Blue Discord](https://discord.gg/WEu6BdFEtp)

## License

TunaOS is licensed under [Apache 2.0](LICENSE).
