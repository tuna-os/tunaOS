---
tags: [adr, repos, rust]
---

# ADR 0009: suite-common namespace ownership

Accepted. `gtk-office-suite/suite-common` is the canonical Rust shared library; `suite-common-rs` only when the standalone project is needed; the Python `suite-common` is a separate legacy library. Naming decision only; no cross-repo changes from tunaOS. `docs/adr/0009-suite-common-namespace-ownership.md`.
