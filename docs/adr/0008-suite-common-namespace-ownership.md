# ADR 0008: Clarify suite-common namespace ownership

- Status: accepted
- Date: 2026-08-14
- Related issue: [tunaOS #517](https://github.com/tuna-os/tunaos/issues/517)

## Context

The TunaOS organization has three repositories whose names contain
`suite-common`:

- [`suite-common`](https://github.com/tuna-os/suite-common) is the standalone
  GTK4/libadwaita Python library used by legacy Python applications.
- [`suite-common-rust`](https://github.com/tuna-os/suite-common-rust) is a
  standalone Rust project whose Cargo package is `suite-common-rs`.
- [`gtk-office-suite`](https://github.com/tuna-os/gtk-office-suite) contains
  the active workspace crate `suite-common`, alongside `suite-common-core`.

This is easy to misread as one project with multiple implementations. It also
used to be a literal Cargo package-name collision. The standalone Rust package
has since been renamed to `suite-common-rs` and its GTK dependencies have been
updated to the current 0.11/0.9 generation, so that part of the original
finding is no longer current.

## Decision

Treat `gtk-office-suite/suite-common` as the canonical Rust shared library for
new TunaOS and GTK Office Suite development. Use `suite-common-rs` only when a
consumer explicitly needs the standalone Rust project, and describe the
standalone Python project as a separate legacy library rather than as another
Rust implementation.

This repository records the ownership and naming decision only. Renaming or
archiving the Python repository, or changing the standalone Rust repository's
disposition, requires action by the maintainers of those repositories and is
not performed by a TunaOS code change.

## Consequences

- New Rust code has an unambiguous canonical dependency target.
- Searches for `suite-common` can be resolved by checking the language and
  repository path instead of assuming the projects are interchangeable.
- The Python-to-Rust migration remains an explicit cross-repository effort;
  this ADR does not imply API or compatibility between the libraries.
- Follow-up repository rename/archive work remains with the relevant project
  maintainers.

---
*Recorded from the current repository state and the re-check documented on
[tunaOS #517](https://github.com/tuna-os/tunaos/issues/517).*
