---
tags: [gates, testing, systemd]
---

# An assertion that can never pass looks like background noise

Trap: `graphical.target is active` was asserted from inside that target's own start transaction (always `activating`); the SSH host-key check fired on images that disable sshd by design. Red on every run for months, so nobody read them. Polling for `active` deadlocks.
Do instead: treat "always fails" as the bug; assert what the design guarantees (`active|activating`, sshd enabled-or-active). See `docs/ci-troubleshooting.md` §4 rows 33, 35.
