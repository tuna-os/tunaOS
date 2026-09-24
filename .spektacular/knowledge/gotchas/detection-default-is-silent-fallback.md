---
tags: [live-iso, desktop, defaults]
---

# A detection default hides unrecognised input

Trap: `customize-live.sh` defaulted `DESKTOP=gnome`, so Pantheon got GDM autologin on a LightDM image and the published ISO booted to a black screen.
Do instead: fail loudly on unrecognised input, and test the unrecognised case explicitly. See `docs/ci-troubleshooting.md` §4 row 40.
