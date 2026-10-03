# Infrastructure Release Versioning and Gating Policy

**Status**: Proposed — becomes active when merged  
**Owner**: TunaOS maintainers  
**Tracks**: [#2731](https://github.com/tuna-os/tunaos/issues/2731)

## Purpose

TunaOS infrastructure is consumed across repositories. A release must therefore
identify an immutable input, state its compatibility contract, and provide a
verified way to update or roll back. This policy supplies that shared contract
for tools, libraries, workflows, package factories, and infrastructure
containers maintained by the `tuna-os` organization.

The key words **MUST**, **MUST NOT**, **SHOULD**, and **MAY** are normative.

## Scope and relationship to image versions

This policy applies when an organization repository publishes an artifact for
another repository or a user to consume, including:

- command-line tools, libraries, and installers;
- reusable GitHub Actions and workflows;
- build, package, and installer containers; and
- package-factory configuration and repository snapshots.

It does not replace the date-based scheme for operating-system images. TunaOS
images continue to follow [VERSIONING.md](VERSIONING.md), and variant promotion
continues to follow [VARIANT-LIFECYCLE.md](VARIANT-LIFECYCLE.md). An internal
repository with no published consumer interface does not need releases until it
creates one.

## Version identifiers

### Software and repository releases

Infrastructure software MUST use Semantic Versioning 2.0.0 with a `v`-prefixed
Git tag:

```text
vMAJOR.MINOR.PATCH
vMAJOR.MINOR.PATCH-rc.N
```

- `PATCH` is a backward-compatible fix.
- `MINOR` adds backward-compatible behavior.
- `MAJOR` changes or removes a supported interface.
- A release candidate uses `-rc.N` and is never advertised as stable.
- A first public release normally starts at `v0.1.0`. During `v0.x`, a breaking
  change increments `MINOR`; `PATCH` remains backward-compatible.
- `v1.0.0` is a stability claim and MUST pass the stable-release gate below.

Supported interfaces include documented CLI flags and output, configuration
schemas, library APIs, workflow inputs/outputs/secrets, container entrypoints,
and artifact names. A Git tag and the assets attached to it are immutable.
Corrections require a new version; maintainers MUST NOT move or recreate a
published tag.

### Multi-component factories and upstream packages

A factory MUST NOT invent one SemVer value for unrelated upstream packages.
Each package retains its upstream version plus the ecosystem's package-release
field. Rebuilds increment that release field rather than changing the upstream
version.

The factory's own public configuration, schema, or tooling MAY have a SemVer
release. A published repository snapshot MUST have an immutable snapshot ID,
signed metadata, and provenance linking it to a source commit and build run.
Consumers pin that snapshot or its immutable digest, not a moving repository
alias.

### Containers and release assets

A container produced by a software release MUST have the matching SemVer tag
and an immutable digest. A binary archive or installer MUST include a checksum.
Executable artifacts and containers MUST be signed and accompanied by an SBOM
and build provenance when they are promoted for downstream use.

Mutable aliases such as `latest`, `main`, and bare major/minor tags MAY exist
for discovery or local testing, but are not release identifiers and MUST NOT be
the only way to reproduce a release.

## Release lifecycle and gates

A release is gated by evidence, not by the presence of a tag. The release PR or
workflow summary MUST link the source commit, successful gate run, generated
changelog, and published-artifact verification.

| Stage | Required evidence |
|---|---|
| **Release candidate** | Version and compatibility impact selected; automated tests, lint, and security checks pass; candidate artifacts are built from the tagged commit; release notes identify breaking changes and migrations. |
| **First public release** | Candidate gate passes; repository has an owner, license, contribution and security-reporting paths, documented install/upgrade/rollback steps, supported platforms, and a consumer-facing interface; published artifacts have integrity metadata; at least one clean-room install or downstream integration succeeds using the immutable artifact. |
| **Subsequent release** | Candidate gate passes; SemVer classification matches the diff; compatibility tests cover supported interfaces; upgrade and rollback are exercised when persistent state or a schema changes; publication verification confirms every expected asset, signature, SBOM, and provenance record. |
| **Stable (`v1.0.0+`)** | First-release gate passes; the supported interface and compatibility window are explicit; at least one real downstream uses an immutable pin; release and rollback automation are documented and have completed successfully; no open release-blocking security or data-loss defect remains. |

A release job MUST fail closed when required evidence or an expected artifact is
missing. Retrying a failed gate is allowed; skipping it or publishing manually
without equivalent recorded evidence is not. Repositories SHOULD encode these
criteria in required CI and a protected release environment so the policy
cannot silently drift away from the workflow.

A project MAY publish `v0.x` releases indefinitely while its interface is
incubating. “First release” means the first externally consumable version; it
does not mean stable. A project that starts directly at `v1.0.0` must satisfy
both the first-release and stable gates.

## Downstream pinning contract

Protected build, test, and release paths MUST resolve every cross-repository
input to immutable content. Use the following pin for each artifact class:

| Dependency | Required downstream pin |
|---|---|
| GitHub Action or reusable workflow | Full commit SHA, with the release tag in a comment for readability |
| OCI image | Digest (`name@sha256:...`); a SemVer tag MAY be recorded alongside it |
| Downloaded binary/archive | Exact version plus verified checksum and signature when published |
| Language dependency | Declared compatible SemVer range plus a committed lockfile, or an exact version where lockfiles do not apply |
| Package repository | Immutable, signed snapshot ID/digest; package version constraints where compatibility requires them |
| Git source | Signed release tag resolved to a recorded commit; raw branch pins are prohibited |

`main`, `latest`, nightly URLs, and other moving aliases MAY be used in an
explicitly non-production development or canary lane. They MUST NOT feed a
promoted TunaOS image, installer, release asset, or release gate. Renovate or an
equivalent updater SHOULD propose pin changes through normal review and CI;
automation must not exchange immutability for unattended updates.

When a downstream adopts a release it MUST retain its last-known-good pin until
the replacement passes that downstream's own gates. Rollback means restoring
that previous pin, not moving or overwriting the upstream release tag.

## Decision authority and release workflow

1. The repository release owner proposes the version and records the gate
   evidence in a release PR or automated release PR.
2. A repository maintainer or applicable `CODEOWNERS` reviewer approves the
   compatibility classification and release notes. The author MUST NOT be the
   sole approver where branch protection supports independent review.
3. The protected release workflow builds and publishes from the approved commit
   using least-privilege credentials. Humans do not upload substitute assets to
   make a failed run appear complete.
4. The workflow verifies the published tag, assets, signatures, SBOM, and
   provenance before reporting success.
5. A breaking release, support-window reduction, or exception to this policy
   additionally requires approval from a TunaOS organization maintainer and a
   linked decision issue.

Security fixes follow the same integrity and publication gates. Coordinated
disclosure MAY keep notes private until publication, but urgency is not a
reason to reuse a version, move a tag, or bypass a protected environment.

## Deprecation, support, and end of life

Every repository with public releases MUST state its support window in its
README or release documentation. Unless it declares a longer window, the
organization default is:

- before `v1.0.0`, only the latest minor line is supported;
- at and after `v1.0.0`, the latest minor of the current major is supported;
- a superseded major receives critical security fixes for 90 days after the
  replacement major is released; and
- release candidates, moving aliases, and development snapshots are unsupported.

Deprecation MUST be announced in release notes and documentation with the
replacement, migration instructions, final supported version, and EOL date.
The notice period is at least 90 days for a stable interface and 30 days for an
incubating `v0.x` interface. At EOL, maintainers mark the release line
unsupported and update security documentation; they do not delete immutable
tags or assets needed for verification and rollback.

A compromised or dangerously defective artifact MAY be revoked immediately.
The maintainer MUST publish an advisory naming affected versions, prevent new
consumption, and release a fixed version. Existing tags remain in the audit
trail unless removal is required to stop active harm; any removal is recorded
in the advisory.

## Exceptions and adoption

An exception requires a public issue that names the repository, affected
consumer, reason, risk control, owner, and expiry date. Exceptions are
time-bounded and do not establish precedent. Secrets or embargoed vulnerability
details belong in a private security advisory rather than the public issue.

A repository adopting this policy SHOULD:

1. link this document from its release or contributing documentation;
2. declare its artifact classes, supported interfaces, and support window;
3. configure release automation and protected approvals for the applicable
   gates;
4. replace mutable downstream references with immutable pins; and
5. add an automated test that rejects new mutable pins in protected paths.

Policy changes use the normal TunaOS RFC/ADR process when they alter the
version contract, release authority, or minimum gates. Maintainers review this
policy annually and after any release incident caused by an ambiguous version,
missing gate, or failed rollback.
