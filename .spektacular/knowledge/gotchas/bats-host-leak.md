---
tags: [testing, bats, hermetic]
---

# bats tests can read the developer host's state

Trap: `test_lib.bats` failed only on ublue-derived workstations because `lib.sh` read `/usr/share/ublue-os/image-info.json` and a global `jq` stub; dismissed as noise, it hid a real `BASE_IMAGE` clobbering bug.
Do instead: make `setup()` point host paths at non-existent files; investigate local-only failures. See `docs/ci-troubleshooting.md` §4 row 37.
