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
  published-manifest, bootc-label, install-configuration, alias, and
  containerized desktop sanity checks. These checks do **not** update or
  roll back an installed system.

## Installed update and rollback pilot

[`scripts/installed-lifecycle-pilot.py`](../../scripts/installed-lifecycle-pilot.py)
is the separate, opt-in Skipjack/GNOME amd64 pilot from tunaOS#3798. It takes
an already-qualified installed-A qcow2, verifies immutable A and B platform
digests before creating a disposable overlay, then proves this exact sequence:

1. cold boot A with no installation media and verify the booted registry
   deployment plus the installed GNOME runtime contract;
2. `bootc switch --retain` to B, reboot, and verify B plus the contract;
3. `bootc rollback` to A, reboot, and verify A plus the contract.

The input disk is never opened as a host block device. The harness refuses
tags, equal A/B digests, another target or architecture, an unverified disk
digest, and execution without `--confirm-disposable-vm`. It records bounded
command output and every passed, failed, or skipped stage in
[`schemas/installed-lifecycle-evidence-v1.schema.json`](../../schemas/installed-lifecycle-evidence-v1.schema.json).
Cleanup always runs; a cleanup failure is recorded without replacing the
first lifecycle failure.

During execution, `installed-lifecycle-evidence.partial.json` is only an
in-progress recovery checkpoint. It can contain pending stages and an
`incomplete` result, so it does not conform to the final evidence schema.
Successful or normally failed runs replace it with the schema-valid
`installed-lifecycle-evidence.json`; the partial file remains only after an
interrupt or abrupt failure.

A passing verdict is enforced twice. The harness accepts a boot stage only
when it returns the booted registry deployment for the expected digest and a
passed runtime desktop contract, and it passes only when all eight stages,
including cleanup, passed. The schema independently rejects a `passed`
verdict with any failed or skipped stage, with a missing stage, with a boot
stage that lacks booted-deployment proof, or with mutable or malformed
identities. Failed reports keep rejected inputs verbatim, so they stay
schema-valid and visible.

```bash
scripts/installed-lifecycle-pilot.py \
  --disk installed-a.qcow2 \
  --disk-sha256 "$DISK_SHA256" \
  --image-a "ghcr.io/tuna-os/skipjack@sha256:$A_DIGEST" \
  --image-b "ghcr.io/tuna-os/skipjack@sha256:$B_DIGEST" \
  --variant skipjack --flavor gnome --platform linux/amd64 \
  --ssh-key "$SSH_KEY" \
  --source-run-id "$RUN_ID/$RUN_ATTEMPT" \
  --source-head-sha "$SOURCE_HEAD_SHA" \
  --harness-sha "$HARNESS_SHA" \
  --output-dir lifecycle-evidence \
  --confirm-disposable-vm
```

Offline tests exercise the state machine only:

```bash
pytest -q tests/test_installed_lifecycle_pilot.py
```

They are not runtime acceptance. Acceptance requires a retained, schema-valid
report from an approved exact-head one-cell run whose cold, warm, and recovery
outcomes all passed. A container inspection, no-op update, failed/skipped
stage, or run that booted a different deployment remains non-passing. Rebase
is explicitly outside this pilot.

See [`.github/green-criteria.yml`](../../.github/green-criteria.yml) for how
the existing scheduled checks feed into what "green" means for a given
(variant, flavor) cell. This opt-in pilot does not replace or widen those
production gates.
