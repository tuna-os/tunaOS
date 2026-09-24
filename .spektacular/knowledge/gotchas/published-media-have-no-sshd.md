---
tags: [iso, ssh, testing]
---

# SSH-based ISO e2e modes only work on dev ISOs

Trap: production images ship sshd disabled, so `iso-e2e.sh --luks/--ssh-only/--kickstart/--app-launch` fail on published media ("SSH not available"); dev ISOs need `ENABLE_SSHD=1`.
Do instead: use `--published` (QEMU monitor + OCR) for shipped artifacts. See `docs/AGENT_GUIDE.md` "Testing an ISO"; `docs/ci-troubleshooting.md` §4 rows 7, 35.
