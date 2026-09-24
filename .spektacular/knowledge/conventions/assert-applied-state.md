---
tags: [testing, branding, gates]
---

# Assert the applied effect in the built image, not the presence of a file or call

Test that the thing happened, not that its ingredients exist. A wallpaper file under `/usr/share/backgrounds` changes nothing unless the session is told to use it; a script that is invoked is not a script that is reached (early `exit 0`). Verify a fix in the built artifact (`just build` then `podman run --rm <image> ...`), not only in the source tree.

Source: `docs/BRANDING.md` (three layers); `AGENTS.md` "Being invoked is not being reached", "Verify a fix in the built artifact".
