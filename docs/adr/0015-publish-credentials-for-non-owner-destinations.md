# ADR 0015: Credentials for non-owner publish destinations

- Status: accepted
- Date: 2026-10-25
- Approval: maintainer decisions on every numbered decision of RFC 016, given on 2026-10-25 through the orchestrator the maintainer delegated to. They are in the RFC's [Decisions](../rfc/rfc016-publish-credentials.md#decisions) table.
- RFC: [RFC 016](../rfc/rfc016-publish-credentials.md)
- Issue: [#3801](https://github.com/tuna-os/tunaOS/issues/3801)
- Implementation: [#3853](https://github.com/tuna-os/tunaOS/pull/3853)

## Context

`[build.publish]` can name a destination outside `ghcr.io/<owner>`. Every
publish job logs in to `ghcr.io` with `GITHUB_TOKEN`, which can write only the
owner's packages, so such a destination fails at its first push.

## Decision

- A destination of `ghcr.io/<owner>` keeps the existing steps unchanged.
- Any other destination needs two secrets: `TUNAOS_PUBLISH_USERNAME` and
  `TUNAOS_PUBLISH_PASSWORD`. They are in a `publish` environment that only
  `main` can deploy.
- It also needs the variable `TUNAOS_PUBLISH_SCOPE`, equal to the destination.
  One scope for each repository. The match is exact.
- Only `push`, `schedule` and `workflow_dispatch` runs publish.
- Login follows **Build Image**, so the layer cache is read-only and no build
  step has the credential.
- Published destinations allow anonymous pull; pull-only jobs get no credential.
- CI never falls back to `ghcr.io/<owner>`. A missing, partial or mismatched
  input fails with a named code.
- For `ghcr.io/<other-org>`, docker and cosign keep one entry for all of
  `ghcr.io`. The maintainer accepts that limit.

## Consequences

- The stock repository sets no scope, so its jobs have no environment and no
  new step runs.
- A fork needs three settings and a robot token for one namespace.
- A fork with two destinations needs a later extension.
- Source tests use command stubs. No registry login, push, pull or signature
  has run. An isolated test namespace needs a later, separate approval.
