---
tags: [adr, iso, tacklebox]
---

# ADR 0002: build ISOs in the browser from GHCR images

Accepted, live at iso.tunaos.org. The long tail of variant x flavor ISOs is self-service: tacklebox compiled to WASM pulls from ghcr.io through a stateless CORS relay. Rejected publishing extra artifact streams, a hosted build service, and a local CLI as primary path, because each adds maintenance. `docs/adr/0002-browser-iso-builder.md`.
