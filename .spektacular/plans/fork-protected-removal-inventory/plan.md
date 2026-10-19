# Protected removal qualification plan

## Scope and approval

Continue the authorized single-config package operations work in a stacked draft.
Keep production removals rejected. Spektacular CLI is unavailable in this
execution environment; this manual plan records the compatibility boundary.
No-person-present planning approval is recorded here under the agent guide.

## Implementation

1. Capture complete native base and desktop inventories with closed schema and
   source/image provenance. Protect the union of names, including leaf packages.
2. Gate qualification explicitly; reject protected-name requests and inventory
   drift before mutation. Use existing exact native removal adapter.
3. Require full postflight inventory equality excluding only explicit targets;
   emit a new receipt only after success. Failed roots must be discarded.
4. Test malformed data, failures and genuine private-root dpkg operations. Add
   independent disposable RPM/pacman native fixtures and CI coverage.
5. Run formatting, static checks and fork regressions before publishing a draft.

## Boundaries

Caller-provided provenance is not an authenticity proof. Production promotion
requires trusted capture stages, protected baseline artifacts and actual image
qualification. Native tool evidence does not prove maintainer-script safety.
Portage and inherited-layer production removal remain unsupported.
