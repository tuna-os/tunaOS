# RFC 017: Protected native-package removal

- **Status:** Draft. One specification now holds the design. A maintainer must approve the decisions below. Every removal stays rejected.
- **Issue:** [#3803](https://github.com/tuna-os/tunaOS/issues/3803) (F4b of epic [#3668](https://github.com/tuna-os/tunaOS/issues/3668))
- **Branch:** `rfc017-protected-package-removal` (this document only)
- **Owner:** tuna-os maintainers
- **Specification:** [F4b specification](../../.spektacular/specs/20261024100000-protected-native-package-removal.md) and [plan](../../.spektacular/plans/20261024100000-protected-native-package-removal/plan.md), from [#3855](https://github.com/tuna-os/tunaOS/pull/3855). They are the normative design.
- **Related:** [RFC 013](rfc013-single-fork-config.md), [#3739](https://github.com/tuna-os/tunaOS/pull/3739) (F4 additions), [#3802](https://github.com/tuna-os/tunaOS/issues/3802), [#3805](https://github.com/tuna-os/tunaOS/issues/3805), [#3474](https://github.com/tuna-os/tunaOS/issues/3474)
- **Prior art:** [#3444](https://github.com/tuna-os/tunaOS/pull/3444), [#3449](https://github.com/tuna-os/tunaOS/pull/3449), [#3453](https://github.com/tuna-os/tunaOS/pull/3453) (drafts on the superseded preview path)
- **Decision:** None yet. This RFC becomes an [ADR](../adr/README.md) when a maintainer approves.

## Problem

The maintainer decision on #3668 is: package additions now, removals later.
A removal can take out a package that the base, the desktop or the update
path needs. The image can then build and still fail to boot, log in, update
or roll back.

This RFC records the decisions behind the specification of a safe removal. It
does not enable a removal, and it does not repeat the specification.

## Current state

| Path | Where removals stop | Pinned by |
|---|---|---|
| Primary TOML (`[defaults.packages]`, `variants.<v>.packages`) | `scripts/lib/tunaos_config.py` in #3739 (not on `main` yet): "package removals are not supported" | `tests/test_image_packages.py::test_removals_are_rejected_with_the_reason` in #3739 |
| Preview fork config, source check | `scripts/prepare-fork-config.py` | `tests/test_fork_config_consumers.py::test_package_supported_names_and_rejected_removals` |
| Preview fork config, build | `build_scripts/lib/fork-packages.sh` | `tests/test_fork_package_consumer.py::test_all_removals_fail_before_transaction_or_file_write` |

This RFC keeps all three rejections and their tests.

`pkg_remove` in `build_scripts/lib.sh` is not safe for this purpose:

| Family | `pkg_remove` today | Problem for a fork removal |
|---|---|---|
| pacman | `pacman -Rns --noconfirm "$@" 2>/dev/null \|\| true` | Removes dependencies too, and hides a failure |
| emerge | `emerge --deselect "$@"` | Removes nothing from the image |
| zypper | `zypper --non-interactive rm "$@"` | Also removes packages that need the target |
| dnf | `dnf_retry remove -y "$@"` | Can remove dependencies that nothing else needs |
| apt | `apt-get purge -y "$@"` | Also removes packages that need the target |

A fork removal never goes through `pkg_remove`. Stock framework removals in
`build_scripts/` are not fork removals. This RFC does not change them.

## One design

Two proposals existed: the specification in #3855 and an earlier draft of this
RFC (#3858). Where they agreed, the specification states the rule once. Where
they differed, the specification took the stricter or the verified option. The
table lists each difference and its outcome.

| Topic | #3855 specification | Earlier RFC draft | Outcome in the specification |
|---|---|---|---|
| Protected set | Projected from contracts and native metadata; no list of names; receipt binds every input | Same sources, plus the installed dependency closure of the protected packages | Specification model. The plan check (the closure must equal the request) covers the dependency closure |
| Contract coverage | Cited `verify-base-contract.sh` for kernel and boot | Measured that no check names the kernel, initramfs, boot loader, package manager or network unit | Measured on `main`: only `bootc`, system state and the system bus are asserted. The specification now lists the gaps and requires the checks first (`PR-3`) |
| Closure rule | Reject a plan that removes a protected identity | The simulation must remove exactly the requested names | Exact set. Any extra removal fails with `dependency-induced` (`PR-5` step 5) |
| Repositories | Authenticate and refresh once, bind the snapshot, then fail on stale data | Local database only; never refresh | Refresh once in an explicit step; no later step refreshes; missing metadata fails (`PR-5` step 2) |
| Scope | Defaults, then variant | Variant only: one list names one family | Variant only for removals; defaults removal stays rejected (`PR-4`) |
| Boundary | Removal before additions | After the last package transaction of the last stage, again in each derived stage | After the additions, repeated per derived stage (`PR-5` step 7) |
| Portage | Unsupported until it can expose an exact removal closure | Admitted later with `emerge --depclean` | Unsupported (`PR-6`) |
| Failure surface | Fixtures only | Named codes and the stage of each | Named codes, `PR-9` |
| Name grammar | Exact installed name | Same, with option and pattern fixtures | Same; fixtures 10 to 13 (`PR-7`) |
| Transaction proof | Simulate, qualify in a discarded copy, require an equal fingerprint | Simulate, run, compare inventories | Specification protocol (`PR-5`) |
| Evidence | Six levels, per cell | E1 to E6, per family | Same six levels, per cell (`PR-8`) |

## Scope and non-goals

This RFC does not:

- enable a removal, a destructive package operation or a policy change;
- add a committed catalog of package names;
- change stock images or stock framework removals.

## Evidence for this RFC

| Check | State |
|---|---|
| Existing rejection tests | Unchanged. This RFC changes no production code |
| `tests/test_protected_removal_rfc.py` (cited files exist, the specification is linked, every family has a `pkg_remove` row, the decisions are numbered) | Source test |
| `tests/test_protected_removal_spec.py` in #3855 (the specification names real files, covers every family, and its failure codes are tabulated) | Source test |
| Removal code, native fixtures, builds, boots | Not run: blocked on approval |

## Decisions for the maintainer

Each decision names the option that the specification uses. Approval of the
specification (`PR-8`) is approval of these options.

1. **Protected set model.** Use contracts, native markers and a plan that must
   equal the request (the specification). The alternatives: #3449 protects
   every package in the baseline. #3453 uses a committed list of removable
   names.
2. **Contract gaps.** Approve new base-contract checks. They cover the kernel,
   the initramfs, the boot-loader tool, the package manager, the network unit
   and the image stores. They come first in the plan.
3. **Variant scope only.** Removals exist only in `variants.<v>.packages.remove`.
   `[defaults]` removal stays rejected, because one name is not one package in
   every family.
4. **Boundary.** Removal is the last package transaction of the last package
   stage, and each derived stage repeats it.
5. **Exact set.** Any extra removal in the simulation fails. This holds
   whether or not the extra package has protection.
6. **Evidence and order.** The six levels of `PR-8`, for each cell. The
   recommendation is dnf and apt first. Portage stays unsupported.
7. **Receipt.** Choose where the success receipt lives: an image file under
   `/usr/share/tunaos/`, an OCI label, or a CI artifact. The specification
   only needs later stages and publication to check it.
8. **Stock removals.** Confirm that stock framework removals stay outside this
   validator.
