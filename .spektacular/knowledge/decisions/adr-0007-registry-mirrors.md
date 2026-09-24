---
tags: [adr, registry, pins]
---

# ADR 0007: centralise image refs in `registry-map.yaml`

Accepted, shipped directly to main. Every external image ref resolves through `registry_ref()` (`scripts/_registry.sh`, fronted by `scripts/resolve-image.sh`) from `registry-map.yaml`, with env overrides at registry/path/tag level and digest pins for tool images. Enables mirrors and one inventory of dependencies. `docs/adr/0007-registry-mirror-support.md`.
