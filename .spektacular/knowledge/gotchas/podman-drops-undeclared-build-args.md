---
tags: [podman, containerfile, build]
---

# podman silently drops a `--build-arg` the Containerfile never declares

Trap: `Containerfile.ubuntu` lacked `ARG ENABLE_SSHD`, so the value never reached the build script; no warning.
Do instead: when adding a build-arg, declare `ARG`/`ENV` in every Containerfile that needs it (el10, overlay, ubuntu, debian, arch, gentoo, opensuse). See `docs/ci-troubleshooting.md` §4 row 8.
