---
tags: [adr, flavors, nvidia]
---

# ADR 0001: rename `-gdx` flavors to `-nvidia`

Accepted. "GDX" was opaque; `-nvidia` says what the flavor adds. Rejected keeping GDX (permanent confusion) and shipping both (doubles tags, CI and storage). One-time migration cost accepted. `docs/adr/0001-gdx-to-nvidia-rename.md`.
