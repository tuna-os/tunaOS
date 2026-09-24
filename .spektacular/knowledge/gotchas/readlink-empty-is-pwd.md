---
tags: [shell, safety]
---

# `readlink -f ""` returns `$PWD`

Trap: an empty path resolved with `readlink -f` becomes the working directory; `rawhide_rpmdb_probe` then `rm -rf`'d a repo checkout during a bats run.
Do instead: reject empty/relative paths before resolving, reject `/` and `$PWD` after, make deletes conditional on the copy. See `docs/ci-troubleshooting.md` §4 row 39.
