# ADR 0013: Opt-in fork config consumer preview

- Status: accepted for the bounded experimental preview
- Approval: [maintainer approach approval](https://github.com/tuna-os/tunaOS/pull/3439#issuecomment-6275714577)
- Date: 2026-10-19
- Issue: [#3433](https://github.com/tuna-os/tunaOS/issues/3433)
- RFC: [RFC 013](../rfc/rfc013-single-fork-config.md)
- Implementation: [PR #3439](https://github.com/tuna-os/tunaOS/pull/3439)

## Context

The foundation can validate fork intent but does not apply it to
images. Fork authors need an explicit local path to test package additions and
wallpaper choices without a change to default builds or production admission.

## Decision

Accept the experimental preview in #3439 as an opt-in path. Reuse the existing
catalog, routes and build engine. Prepare isolated contexts from reviewed source
bytes. Apply supported additions of native packages, URLs and supplied wallpapers
through the existing desktop paths. Keep receipts for those command outcomes
and assets. Refuse unsupported operations before the build.

Create new pinned configs only through explicit template initialization.
Existing config pins stay strict and never refresh automatically. Config intent
explanation remains optional; it is not evidence that an image consumed intent.

Default builds, production publication and admission remain unchanged. The
preview never publishes images. Fork preview builds disable layer reuse until
cache behavior has separate evidence.

## Consequences and limits

- This decision extends ADR 0012 only for the bounded local preview.
- Tests can validate the inputs and consumer behavior under test stubs.
  They do not qualify images or transactions in native package managers.
- Name/logo overrides, package removals, custom schemas for non-RPM repositories,
  base/overlay closure and unsupported wallpaper consumers remain rejected.
- Full brand support and production consumer rollout need their own review.
- Build, boot, login, install, target-only reboot, update and recovery evidence
  remain required for the delivery milestone. This ADR does not imply status.
- Rollback uses the unchanged stock build path. The broader RFC remains open.
