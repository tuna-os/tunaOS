# RFC 017: Protected native-package removal

- **Status:** Draft. Specification only. Every removal stays rejected.
- **Issue:** [#3803](https://github.com/tuna-os/tunaOS/issues/3803) (F4b of epic [#3668](https://github.com/tuna-os/tunaOS/issues/3668))
- **Branch:** `rfc017-protected-package-removal`
- **Owner:** tuna-os maintainers
- **Related:** [RFC 013](rfc013-single-fork-config.md), [#3739](https://github.com/tuna-os/tunaOS/pull/3739) (F4 additions), [#3802](https://github.com/tuna-os/tunaOS/issues/3802), [#3805](https://github.com/tuna-os/tunaOS/issues/3805), [#3474](https://github.com/tuna-os/tunaOS/issues/3474)
- **Prior art:** [#3444](https://github.com/tuna-os/tunaOS/pull/3444), [#3449](https://github.com/tuna-os/tunaOS/pull/3449), [#3453](https://github.com/tuna-os/tunaOS/pull/3453) (drafts on the superseded preview path)
- **Decision:** None. A maintainer must approve this specification before any removal code lands.

## Problem

The maintainer decision on #3668 is: package additions now, removals later.
A removal can take out a package that the base, the desktop or the update
path needs. The image can then build and still fail to boot, log in, update
or roll back.

This RFC specifies the conditions for a safe removal: the protected set, the
validation steps, the failure codes and the evidence for each package family.
It does not enable a removal.

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

## Scope and non-goals

This RFC covers:

- the protected set for each family, from existing contracts;
- the validation steps before, during and after the transaction;
- the failure codes, and where each one appears;
- inherited defaults and conflict rules;
- adversarial fixtures;
- the evidence that admits a family.

This RFC does not:

- enable a removal, a destructive package operation or a policy change;
- add a committed catalog of package names;
- change stock images or stock framework removals.

## Protected set

### Sources

The protected set comes from contracts that already exist. The build computes
it from the image at the removal boundary. No committed list of package names
holds it.

| Source | What it names | Categories |
|---|---|---|
| `build_scripts/checks/verify-base-contract.sh` | `bootc`, system state, system bus unit | boot, init, update |
| `build_scripts/checks/verify-desktop-experience.sh` | Commands, units, session files and portals for each desktop | desktop, session |
| `tunaos.toml` `[desktops.<d>.packages.<family>]` | `required` names and `display_manager` | desktop, session |
| `build_scripts/40-services.sh` (`tunaos_enable_network_manager`) | `NetworkManager.service` or `systemd-networkd` | networking |
| `scripts/lib/tunaos_packages.py` | Package families of desktop profiles | family names |
| Native markers in the image | dnf `protected.d`, dpkg `Essential: yes` and `Priority: required`, pacman `HoldPkg`, Portage `@system` | package manager, init, base |

The markers are family data in the image, not TunaOS data. At evidence level
E2, a test measures which markers each family ships.

### Gaps in the contracts

No contract names the kernel, the initramfs, the boot loader or the package
manager. Also, no build check names the network unit. The approved change
adds these checks to the build check of `verify-base-contract.sh`:

| Check | Category |
|---|---|
| A kernel image and an initramfs under `/usr/lib/modules/<version>/` | boot |
| The boot loader update tool that `bootc install` uses for the family | boot |
| The native package manager command | package manager |
| `NetworkManager.service` or `systemd-networkd.service` | networking |
| `bootc` and its image store tools (`ostree` or composefs) | update, recovery |

The new checks then feed the protected set, as the existing checks do.

### Derivation

At the removal boundary, the build does these steps:

1. Map each contract item (command, unit, path or name) to its native owner.
   The owner query is `rpm -qf` for dnf and zypper, `dpkg -S` for apt,
   `pacman -Qo` for pacman and `qfile` for Portage.
2. Add the native markers.
3. Add the installed dependency closure of steps 1 and 2. A removal of a
   dependency also removes the package that needs it.
4. Record the source of each entry, for example
   `gdm <- verify-desktop-experience.sh require_any_unit gdm gdm3`.

An item without an owner fails the build with `contract-unowned`. Thus a
contract item never drops out of the protected set without notice.

## Validation

The steps run in this order. Each failure stops the build before the package
database changes.

| Step | Rule | Failure code |
|---|---|---|
| 1 | Removals exist only in `variants.<v>.packages.remove`, so each list has one family. `[defaults.packages].remove` stays rejected | `schema` |
| 2 | Each name matches the native name pattern of the family, as #3739 checks additions. No globs, versions, architectures or options | `schema` |
| 3 | A name in both the effective additions and the removals | `conflict` |
| 4 | The family is in the admission table in code. The table is empty now | `unsupported-family` |
| 5 | Each name is an installed package with that exact name. A virtual name or a "provides" match is not enough | `not-installed`, `ambiguous-name` |
| 6 | No name is in the protected set | `protected` |
| 7 | The native simulation removes exactly the requested names | `dependency-induced` |
| 8 | The simulator exists, exits with 0 and gives output that the parser accepts | `solver-unavailable` |
| 9 | The transaction runs with the same names and no force options | `transaction-failed` |
| 10 | The inventory after the transaction equals the inventory before it, minus the names | `inventory-drift` |
| 11 | The base and desktop contracts pass after the removal | the existing contract failure |

Steps 1 to 4 run in `just check`. They need no image. With an empty admission
table, every removal fails in `just check`, as it does now. Steps 5 to 11 run
in the build.

### Native simulation

Each simulation uses only the local package database, with repositories off
and no cascade option.

| Family | Simulation | Transaction |
|---|---|---|
| dnf | `dnf remove --assumeno --disablerepo='*' --setopt=clean_requirements_on_remove=False <names>` | Same, with `-y` instead of `--assumeno` |
| apt | `apt-get -s purge <names>` (no `autoremove`) | `apt-get purge -y <names>` |
| pacman | `pacman -R --print --print-format %n <names>` (no `-s`, `-c` or `-dd`) | `pacman -R --noconfirm <names>` |
| zypper | `zypper --non-interactive --no-refresh remove --dry-run --details <names>` | Same, without `--dry-run` |
| emerge | `emerge --pretend --depclean <atoms>` | `emerge --depclean <atoms>`, after admission only |

The implementation must not use these options: `--nodeps`, `-dd`, `--force-*`,
`--allow-remove-essential`, `--clean-deps`, `-s`, `-c` and `emerge -C`.

If a simulator needs repository metadata, it fails with `solver-unavailable`.
It does not refresh. Thus old or offline repositories cannot change the
result.

### Removal boundary

A removal runs once for each image. It runs after the last package
transaction of the last package stage of the image. That stage is the base
stage for a base flavor and the desktop stage for a desktop flavor. The
removal runs before `build_scripts/90-image-info.sh` and `build_scripts/99-cleanup.sh`.

A desktop flavor starts from its base image. Thus a removal that the base
stage did can return as a desktop dependency. The desktop stage then
simulates the removal again. If a desktop package needs the name, the result
is `dependency-induced`.

Debian and Gentoo images have no package database after cleanup. The
`.packages` step in `.github/workflows/reusable-build-image.yml` records this
(tunaos-packages#135). Steps 5 to 11 thus run at the boundary, not on the
final image.

### Inherited defaults and conflicts

| Case | Rule |
|---|---|
| A removal of a package that a TOML addition installs | `conflict`. Remove the addition instead |
| A removal of a desktop profile `required` name | `protected` |
| A removal in `[defaults.packages]` | `schema`. One name cannot mean the same package in all families |
| The same name twice | `schema` |
| A removal of a package that a later stage installs again | `dependency-induced` at that stage |
| Stock framework removals in `build_scripts/` | Not fork removals. No change |

### Receipt

A successful removal writes a receipt for each image. The receipt holds the
family, the names and the tool versions. It also holds the hash of the
protected set with its sources, and the inventory hashes before and after.
Decision 7 selects the location.

## Adversarial fixtures

The implementation must include these fixtures. Source tests use command
stubs. Native fixtures use a disposable root or container of the family.

| Fixture | Input | Expected |
|---|---|---|
| Direct protected removal | `systemd`, the kernel package, `gdm`, `NetworkManager`, the package manager | `protected`, with the source |
| Removal of a protected dependency | A library that a protected package needs | `protected` (closure) |
| Reverse dependency removal | A name whose removal also removes another package (zypper and apt do this) | `dependency-induced`, with the extra names |
| Unneeded dependency cleanup | A leaf whose removal frees other packages (dnf, pacman `-s`) | Only the leaf goes; inventory equals the request |
| Unavailable solver | Simulator absent, exits with non-zero, or output that does not parse | `solver-unavailable` |
| Old repositories | Metadata old or offline; the tool asks for a refresh | `solver-unavailable`; nothing refreshes |
| Name only in a repository | A name that is not installed | `not-installed` |
| Ambiguous aliases | A virtual name (`x-terminal-emulator`), a provides name, a glob, `pkg-1.2`, `pkg.x86_64`, `pkg:amd64`, a Gentoo name with no category | `ambiguous-name` or `schema` |
| Option injection | `-y`, `--nodeps`, a name with a space or a newline | `schema` |
| Conflict | The same name in `add` and `remove` | `conflict` |
| Unsupported family | Any family that is not in the admission table | `unsupported-family` in `just check` |
| Package script side effect | A script removes an extra package during the transaction | `inventory-drift` |

## Approval boundary and evidence

The admission table in code lists the families that may remove packages. It
is empty. A family enters the table only in a reviewed pull request that
links all of its evidence. Missing evidence keeps the family out.

| Level | Evidence | Kind |
|---|---|---|
| E1 | Every fixture passes with command stubs | source test |
| E2 | Every fixture passes in a disposable native root or container, with zero skips | native fixture |
| E3 | A variant of the family builds with one approved removal, and the contracts pass | image build |
| E4 | That image passes the boot gate | boot |
| E5 | The image installs, and it boots again with the media removed | install |
| E6 | `bootc upgrade` and `bootc rollback` work on the installed system | update, recovery |

E3 to E6 are separate from source tests. #3474 owns E4 to E6 for the
reference journeys. Each family records the exact identity of the source, the
config, the image and the tools.

Each family needs its own evidence at every level:

| Family | Owner query | Native markers to measure in E2 | Special risk |
|---|---|---|---|
| dnf | `rpm -qf` | `protected.d` | `clean_requirements_on_remove` removes unneeded dependencies |
| apt | `dpkg -S` | `Essential: yes`, `Priority: required` | Removes packages that need the target; no package database after cleanup on Debian |
| pacman | `pacman -Qo` | `HoldPkg` | `pkg_remove` uses `-Rns` and hides failures |
| zypper | `rpm -qf` | None known; E2 measures | Removes packages that need the target |
| emerge | `qfile` | `@system` | `emerge -C` ignores dependencies; no package database after cleanup |

No family has evidence against this specification yet. The prior art has
partial E2 work for apt, RPM and pacman on the preview path. That work counts
only after a new run against this specification.

## Prior art

#3444, #3449 and #3453 are drafts on the superseded preview path. Reuse
these parts and do not write them again:

- the private-root dpkg fixture and the RPM and pacman container jobs (#3449);
- the inventory schema with provenance, and the exact delta check (#3449);
- the dependency preflight before the transaction (#3453).

#3453 also adds `fork-optional-removals.json`, a committed list of removable
names. Decision 1 selects between that model and this one.

## Evidence for this RFC

| Check | State |
|---|---|
| Existing rejection tests | Pass locally; numbers in the PR |
| `tests/test_protected_removal_rfc.py` (sources exist, every family has a row) | Pass locally |
| Removal code, native fixtures, builds, boots | Not run: blocked on approval |

## Decisions for the maintainer

1. **Protected set model.** Choose one of three models. This RFC uses
   contracts, native markers and their closure. #3449 protects every package
   in the baseline. #3453 uses a committed list of removable names.
2. **Contract gaps.** Approve the new build checks. They cover the kernel,
   the initramfs, the boot loader, the package manager and the network unit.
3. **Variant level only.** Approve that removals exist only in
   `variants.<v>.packages.remove`, and that `[defaults.packages].remove`
   stays rejected.
4. **Boundary.** Approve that the removal runs once for each image, after
   its last package transaction.
5. **Exact set.** Approve that any extra removal in the simulation fails.
6. **Evidence.** Approve levels E1 to E6, and the order of families. The
   recommendation is dnf and apt first, and emerge last.
7. **Receipt.** Choose the location: an image file under
   `/usr/share/tunaos/`, an OCI label, or a CI artifact.
8. **Stock removals.** Confirm that stock framework removals stay outside
   this validator.
