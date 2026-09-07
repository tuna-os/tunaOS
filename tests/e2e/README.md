# End-to-end tests

This directory is a pointer, not a new test suite — tunaOS already has
substantial E2E coverage, just not under this path:

- [`.github/workflows/iso-e2e.yml`](../../.github/workflows/iso-e2e.yml) +
  [`scripts/iso-e2e.sh`](../../scripts/iso-e2e.sh) — boots the live ISO under
  QEMU and asserts the installer frontend actually appears.
- [`.github/workflows/luks-e2e.yml`](../../.github/workflows/luks-e2e.yml) —
  drives fisherman over SSH through a full disk install (including the
  encrypted path) and asserts the resulting system boots.
- [`.github/workflows/bootc-lifecycle.yml`](../../.github/workflows/bootc-lifecycle.yml) —
  update/rebase/rollback against a deployed system.

See [`.github/green-criteria.yml`](../../.github/green-criteria.yml) for how
these feed into what "green" means for a given (variant, flavor) cell.
