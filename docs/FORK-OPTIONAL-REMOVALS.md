# Reviewed optional stock removals

The adapter accepts `packages.remove: [fastfetch]` for GNOME on `grouper` (apt) or
`yellowfin` (dnf). It rejects other names, selectors, variants, managers and
flavors before mutation. Stock builds do not change. There is no new config
layer. An empty list for removals preserves the existing package path.

The only policy is `build_scripts/lib/fork-optional-removals.json` in the source
repository. The compiler imports `validate_intent(packages, manager, variant,
flavor)` from its sibling Python helper. This function validates policy without
package commands. The image consumer also runs `validate --manifest PATH` before
package work. There is no policy override through the CLI, manifest or environment.

## Build sequence and evidence

1. Capture all packages in the untouched desktop before fork repositories or
   additions. Bind the baseline to the source receipt, canonical manifest hash,
   variant, flavor, platform and policy hash. Check the native OS family,
   `VARIANT_ID`, architecture and database health.
2. Keep the printed SHA-256 from capture in the caller's shell until the late
   boundary. Do not read that reference back from the image after additions.
   A package script could replace both files.
3. Apply additions through the existing strict adapter. Package versions can
   change. Every stock name and architecture must still exist before removal.
   A solver must not silently delete another stock package.
4. After desktop setup, revalidate policy, provenance and the retained hash.
   Check native health and the installed target. Reject scripts for target
   removal that lack qualification.
5. Execute the existing desktop checker from the source repository. Remove its
   old marker first. Check for a new `validated_at_build=true` marker and the
   corresponding pass log. Reject waived, missing, stale or malformed results.
   A substitute checker cannot report success.
6. Call the private native primitive for exact removal. For apt, use
   `dpkg --dry-run --remove` then `dpkg --remove`. For dnf, use `rpm -e --test`
   then `rpm -e`. Do not use solver erase, recursive cleanup or force flags.
   Do not disable dependency checks or run automatic repair.
7. Compare the complete inventories. Only fastfetch may disappear; all other
   records must stay equal. Recheck health and run the strict desktop contract
   again. Check inventory and provenance again before the receipt write.

The removal receipt has `status: complete` only after all checks pass.
It records source, manifest, policy and baseline hashes, both inventories,
removed names, and checker/marker hashes. It does not invent an OCI digest.
Record the identity of each real image in separate evidence from canary runs.
The shell caller owns the overall package receipt. It completes that receipt
only after this helper succeeds.

Every failure is fatal, including a receipt write error. Discard the root.
A package tool or trigger can change files before it fails. These checks cannot
undo those changes. Do not run package operations concurrently. Removal is not
purge: native tools may retain configuration files.

## Helper API

Create the directories for the baseline and receipt first. Evidence files must
be new regular files. Their paths must have no symlink ancestors.

```sh
helper=/run/context/build_scripts/lib/fork-optional-removals.py
python3 "$helper" validate --manifest "$manifest"
baseline_sha256=$(python3 "$helper" capture \
  --manifest "$manifest" --baseline "$baseline" --root /)
# Apply fork additions and finish normal desktop setup, then:
python3 "$helper" apply --manifest "$manifest" \
  --baseline "$baseline" --baseline-sha256 "$baseline_sha256" \
  --receipt "$receipt" --context /run/context --root / --desktop gnome
```

`--root` redirects evidence and OS identity files only. It does not redirect
package commands or the desktop checker. Those operate on the current build
container. Never assume that this argument provides isolation for package operations.
Tests in private roots redirect every native tool through wrappers and replace
contract execution with a stub. Production uses `/` inside a disposable image
build.

A later desktop pass in another shell uses `verify-complete`. Pass the same
arguments as `apply`, except `--baseline-sha256`. This path checks the completed
receipt, baseline hash, exact current inventory, native health and a fresh
result from the strict desktop check. It also checks that evidence and inventory stay equal
during verification. It never removes packages or writes another receipt.

It cannot resume an incomplete or failed removal. It trusts evidence from the
first successful boundary as build artifacts. It cannot recover that shell's
private hash. It cannot use the receipt to approve another mutation.

The public `tunaos_qualify_fork_removals` entrypoint still needs
`TUNAOS_FORK_REMOVAL_QUALIFICATION=1`. It retains its protection policy.
The production adapter calls a private shared primitive after its stronger
checks. It never sets the qualification variable. The CLI for inventory
qualification and its fixture-only receipt do not change.

## Package scripts and proof limits

The first policy rejects `prerm`, `postrm` and `triggers` files in the dpkg
target. For RPM, it rejects all scriptlets and triggers that fastfetch owns.
Errors from these queries also stop removal. The helper does not disable
scripts or triggers.

Triggers from other installed packages may still run. An exact delta in inventory
does not prove that all other files in the payload stayed equal.
Each check covers a different risk.
They do not prove guest boot, login or installation.

RPM uses separate queries for scriptlets, package triggers and file triggers.
See its [scriptlet documentation](https://rpm.org/docs/latest/manual/file_triggers.html).
If fastfetch acquires scripts, review the policy and qualification first.
Do not skip its scripts or loosen the check during a build.

`tests/test_fork_optional_removals.py` checks policy, routes and protected names.
It covers baseline hashes, missing names, changed architectures, upgrades and
native failures. It also checks exact deltas, false contract results, checker
identity and receipt provenance.

The native APT/dpkg tests use a private database. They install small fixtures
with the names stock, fastfetch and added. They check exact removal or native
dependency refusal. The fastfetch fixture is not the distribution's real
package. A stub replaces the desktop checker.

These tests are not full-image qualification. Separate canaries must test real Grouper and Yellowfin images
through the shell consumer, with real packages and pre/post desktop evidence.

## Disposable image proof

Use `scripts/qualify-fork-optional-removal.py` after the native image canary.
Pass `--image` with the local image tag, `--variant`, `--ancestor-manifest` with
that image's original prepared manifest, and `--output` with a new directory.
The launcher compiles a separate package-only context from the current source
pin. It does not reuse the paired identity authority from the ancestor.

The launcher inspects the local image ID and never pulls, tags or pushes an image.
It runs a uniquely named child without network access. Before the real package
consumer runs, it verifies the child's old receipt against the ancestor manifest.
It preserves that exact receipt as ancestry evidence in the proof directory.
Timeout cleanup checks the child label and verifies that the child no longer
exists. Failure to verify cleanup makes the proof fail.

The proof includes the native inventory and contract results for the disposable child.
It does not qualify the original image's identity, boot or installer.
A complete build with removal intent needs its own image qualification.
