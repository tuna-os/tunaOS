---
created_date: "2026-10-24"
document_status: draft
---

# Protected native-package removal

## Scope and safety boundary (`PR-1`)

This is the F4b design for issue #3803. It does not enable package removal.
The primary `tunaos.toml` validator and every generated consumer MUST continue
to reject non-empty removal intent before writing repository files, invoking a
package manager, or writing a success receipt. A maintainer-approved revision of
this design is a prerequisite for implementation, not permission to publish or
to mutate an installed system.

Removal is limited to disposable image-build roots. Runtime removal from an
installed TunaOS system, force removal, dependency bypass, orphan cleanup and
package-manager replacement are out of scope. Any failed preflight, transaction,
postflight or receipt write invalidates the disposable root; it MUST NOT be
continued, committed as an image layer or reused as qualification evidence.

The implementation MUST extend the primary parser and resolver used by builds
and authoring tools. It MUST NOT add another package catalog, a second removal
schema or a fork-only execution path. The qualification-only work in draft PRs
#3444 and #3449 is research to reuse after approval; it is not primary-config
admission or evidence that a family is safe to enable.

## Terms (`PR-2`)

- **Native identity**: the package manager's exact installed identity: package
  name, epoch/version/release where available, architecture and repository or
  source provenance. A capability, virtual provide, fuzzy match, path, archive,
  URL or version/architecture selector is not an input identity.
- **Protected set**: installed native identities that satisfy an effective
  package or runtime contract for the selected build cell, plus native
  protection metadata such as Debian `Essential`/`Protected` packages.
- **Removal closure**: every installed identity the native solver proposes to
  remove, obsolete or replace, whether explicitly requested or dependency
  induced. Autoremovals count even when the frontend labels them as cleanup.
- **Transaction fingerprint**: a digest over source/config/base-image identity,
  native inventory, protected-set receipt, enabled repository snapshots, solver
  and package-manager versions, requested removals and the complete proposed
  transaction.
- **Qualified cell**: one exact variant, flavor, platform, base-image digest,
  repository snapshot and package-manager/tool version combination with all
  evidence required by `PR-8`. Qualification never applies to a package-manager
  family in the abstract.

## Protected inventory and provenance (`PR-3`)

There MUST NOT be a checked-in list of package names described as universally
protected. Names differ between native families and such a list becomes stale.
For each selected cell, the compiler MUST derive the protected set from the same
resolved inputs and checks that define a usable TunaOS image:

| Capability that cannot be removed blindly | Existing authority | Protected projection |
|---|---|---|
| Boot, kernel and initramfs | Selected base image and ordered base/overlay package operations; `verify-base-contract.sh`; applicable kernel/driver checks | Exact installed owners of required boot artifacts, kernel/module tree, initramfs generator and boot units, plus required base/overlay package identities |
| Init and system bus | `verify-base-contract.sh` system-state and bus assertions | Installed owners of PID 1, the default target, system bus unit/binary and contract-required policy files |
| Native package manager | Containerfile route from `resolve-flavor.sh` and `lib.sh` package-manager selection | Installed owners of the selected manager, database/query tools, configuration and trust-store providers |
| Desktop, display manager and session | `tunaos_packages.py` resolved desktop policy and installed contract; `verify-desktop-experience.sh` | Required native package identities and installed owners of the selected display-manager unit, session registration, shell/compositor, portals, keyring, audio and contract-required commands/files |
| Networking and name resolution | Base/runtime contracts, including the active manager and service/unit checks | Installed owners of the selected network manager, address tool, resolver and required service units |
| Update, rollback and recovery | `verify-base-contract.sh` bootc status contract and applicable boot/update helpers | Installed owners of bootc, ostree/deployment tooling, bootloader/update payloads and recovery units/scripts |

The projection MUST use the effective primary configuration and current build
root. Package names declared by the resolved package contract are queried as
installed native identities. Paths, commands and units asserted by runtime
contracts are resolved to installed package owners with the selected native
manager. Alternative artifacts such as `gdm.service`/`gdm3.service` are resolved
from what is actually present; the compiler MUST NOT protect every guessed
alternative.

The protected set is the union of all applicable capability projections and the
native manager's own protected metadata. A package may carry several reasons.
No configuration scope may subtract a reason, replace this set or declare an
exception. If a required contract input is missing, stale, waived without a
qualified replacement, not uniquely attributable where ownership is required,
or unsupported by the projection, removal for that cell MUST fail closed.

Each protected-set receipt MUST bind:

- source commit and primary-config SHA-256;
- variant, resolved flavor/parent closure and platform;
- base and inherited image digests;
- package-manager family and exact tool/solver versions;
- complete installed native inventory digest;
- hashes of resolved package contracts and applicable runtime check sources;
- authenticated enabled repository identities, snapshot/freshness data and
  trust-key fingerprints;
- every protected native identity with one or more contract reasons.

A changed input invalidates the receipt. A caller-supplied digest is not proof of
origin; trusted build stages MUST produce and pass the receipt.

## Resolution, inheritance and conflicts (`PR-4`)

Removal intent MUST be parsed and explained by the primary configuration
resolver. It follows the scopes that schema supports at implementation time;
for F4 that is defaults followed by variant. If desktop or exact-cell package
deltas are later admitted, they append in the existing general-to-specific
order. Lists use stable exact-value deduplication. Empty lists are no-ops, not
clears.

More specific scopes MUST NOT cancel inherited additions, optional additions or
removals. The same native input in more than one operation class is an error
after inheritance. A repository ID inherited with different content is an
error. Package intent never removes a matrix hold or expands a supported cell.

Before solving, each requested value MUST resolve to exactly one currently
installed native package name. Virtual provides, aliases, package groups and
cross-family names are rejected when zero or multiple installed owners match.
The authoring tool may report candidates, but MUST NOT guess, partially edit the
file or treat metadata availability as transaction solvability.

## Transaction protocol (`PR-5`)

One serialized package operation owns a disposable build root. The protocol is:

1. Validate the primary configuration and resolve the exact matrix route,
   inherited package intent and package-manager family.
2. Authenticate and refresh every enabled configured repository. Bind the
   exact snapshot and freshness result. Unavailable, expired, signature-invalid
   or identity-mismatched metadata fails before removal simulation, even when
   the local package database could answer the request.
3. Capture the complete installed native inventory and compile the protected
   set under `PR-3`. Resolve requested names under `PR-4`.
4. Ask the native solver for the complete removal closure without mutation.
   The adapter MUST expose exact native identities, not infer the closure from a
   summary count or grep human prose. A backend that cannot provide a complete,
   machine-checkable plan is unsupported.
5. Reject a plan that removes, obsoletes or replaces any protected identity;
   contains an implicit add, upgrade or downgrade; omits a requested identity;
   uses force/no-dependency/cascade/orphan-cleanup semantics; or differs from
   the operation order resolved from primary configuration.
6. Execute the proposed removal with normal package scripts in a fresh copy of
   the same disposable root. Capture the complete after-inventory and require it
   to equal the before-inventory minus the approved removal closure. Run all
   applicable source/image contract checks there. This qualification execution
   is discarded, including on success.
7. Immediately before the real image-build mutation, repeat repository,
   inventory, protected-set and solver resolution. Its transaction fingerprint
   MUST equal the qualified fingerprint. Apply the removal, then required adds
   and optional adds in the existing order. Any failure discards the build root.
8. Recompute the final inventory, rerun applicable image contracts and write an
   atomic success receipt only after every check passes. A later image layer or
   publication step MUST require that receipt for a configuration containing
   removal intent.

A dry-run is necessary but not sufficient: maintainer scripts and the final
inventory are exercised only in the disposable qualification transaction.
Source tests, command-dispatch tests and a solver exit status do not substitute
for that execution.

## Native family adapters (`PR-6`)

All adapters MUST prohibit force, dependency bypass and automatic cleanup flags.
They MUST preserve the repository and solver options used by the corresponding
installation route.

| Route | Native simulation and closure source | Additional fail-closed rules |
|---|---|---|
| dnf/libdnf (EL, Fedora, ELN, Hummingbird) | libdnf transaction objects, or a dnf5 assumption/no transaction whose complete NEVRA action set is obtained through a stable machine interface; confirm with a normal transaction in a disposable installroot | Reject unavailable solver APIs, protected-package overrides, implicit obsoletes/replacements and a plan derived from repository state different from the build |
| apt/dpkg (Debian, Ubuntu) | `apt-get --simulate` using the production apt configuration, followed by a normal transaction in an isolated root; bind every `Remv` identity to dpkg status/version/architecture | Always protect `Essential: yes` and `Protected: yes`; reject proposed configuration, install, upgrade or downgrade actions and non-machine-stable simulation output |
| pacman (Arch) | Native remove dependency check and printable exact target plan against the selected sync/local databases, followed by a normal transaction under an isolated root/database | Never use `--nodeps`, cascade, recursive orphan cleanup or overwrite; dependency-required requests fail rather than widening the closure |
| zypper/libzypp (openSUSE) | libzypp transaction data or zypper dry-run XML containing the complete solvable action set, followed by a normal transaction in a disposable root | Reject clean-deps, vendor/repository changes, solver recommendations that alter unrelated packages and unstructured output |
| Portage (Gentoo) | Unsupported until Portage can expose an exact installed-atom removal closure and a disposable-root transaction that removes packages rather than only deselecting world entries | `emerge --deselect` is not removal evidence; any Gentoo removal intent fails before mutation |

If a tool version loses the required machine interface or changes plan semantics,
qualification for affected cells expires automatically.

## Adversarial fixtures (`PR-7`)

Fixtures use disposable private roots and packages with deterministic payloads.
Every rejection asserts unchanged inventory, payload hashes, repository files
and absence of a success receipt.

1. **Direct protected removal**: request a package identity backing each
   protected capability class. Validation rejects before a real transaction.
2. **Dependency-induced removal**: request an unprotected library whose native
   solver plan removes or replaces a protected consumer. The closure
   intersection rejects the plan.
3. **Unavailable solver**: remove the solver executable/library or its required
   machine-output capability. The adapter reports the exact missing prerequisite
   and performs no fallback command.
4. **Stale repositories**: use expired metadata, a changed snapshot and an
   unreachable configured source. Each fails before simulation or mutation;
   cached installed-state success is not accepted.
5. **Ambiguous aliases**: present a virtual provide or alias with multiple
   installed providers. Resolution names candidates and rejects the request.
6. **Unsupported family**: submit removal intent to Portage and to an unknown
   manager. Both fail before repository writes or manager invocation.
7. **Inherited conflict**: place the same package in inherited add/optional and
   remove operations. Primary resolution fails atomically and explains both
   source paths.
8. **Plan drift**: change inventory, repository snapshot, solver version or
   protected-contract hash between qualification and application. Fingerprint
   mismatch invalidates the root.
9. **Script/postflight failure**: make a native package script fail or create an
   unexpected inventory delta. The disposable root is discarded and no success
   receipt exists.

The direct and induced fixtures MUST include boot/update, init/bus, package
manager, desktop/session and network reasons. Testing one hard-coded name is not
coverage of the projection.

## Approval and evidence gate (`PR-8`)

Implementation MUST NOT begin until a maintainer approves this design revision
on #3803 or its pull request. Approval authorizes only the bounded implementation
plan; it does not enable removal for any cell. Any change to protection sources,
transaction semantics, supported families or evidence boundaries requires a new
review.

A cell may accept removal intent only after all of the following are attached to
one immutable source/config/base/repository/tool identity:

1. parser/resolver and adversarial source tests, including proof that rejected
   input invokes no package manager and leaves no generated output;
2. native solver and disposable-root transaction evidence for that exact route,
   with complete before/plan/after inventories and protected-set receipt;
3. a real image build that consumes removal intent and passes all applicable
   package, base, desktop, driver and image checks;
4. boot and login proof for the resulting image;
5. installation to a separate target followed by media-detached target boot;
6. update to a newer deployment and rollback/recovery to the prior deployment.

Evidence is recorded as source checks, native transaction, image build, boot,
install, update and recovery results separately. `not run`, missing, stale,
wrong-digest, skipped or waived evidence is not a pass. Qualification is per
cell; unqualified cells and every unsupported family continue to reject removal
intent. The first implementation MUST ship disabled and require explicit,
reviewed admission data rather than infer readiness from a family name.

## Non-goals (`PR-9`)

- Removing stock package policy or converting build-framework mechanisms into
  configuration.
- Mapping a generic package name across distributions by string similarity.
- Removing packages from a running installation or published image.
- Disabling native trust, dependency, protected-package or signature policy.
- Treating a successful source suite, dry-run or package-manager transaction as
  proof of boot, install, update or recovery behavior.
- Expanding supported variants, flavors, platforms or release policy.
