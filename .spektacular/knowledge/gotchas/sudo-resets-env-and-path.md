---
tags: [sudo, env, shell]
---

# `sudo` drops env vars and uses `secure_path`

Trap: `sudo` resets the environment (lost `VARIANT`/`FLAVOR`) and uses `secure_path`, so `command -v x` as the user succeeds while `sudo x` is "command not found"; it also resets `HOME`, leaking root/rootless podman stores.
Do instead: `sudo -E` where env is needed, full paths under sudo, pin `HOME`/`XDG_*` explicitly. See `docs/ci-troubleshooting.md` §4 rows 2, 13, 31.
