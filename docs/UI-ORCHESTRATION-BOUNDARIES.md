# UI and orchestration boundary plan

Tracks [tunaos#3025](https://github.com/tuna-os/tunaos/issues/3025).
Plan identifier: `3025-ui-boundaries`. Clauses `B1`–`B4` below define the
review evidence for each migration. This guide coordinates the linked work. It does not certify the seven codebases.
Each repository keeps its own interfaces, tests and review process.

## B1: Keep construction at the root

The entrypoint can construct all services and own their lifetime. A handler,
view or controller receives only the operations it calls. Domain code takes typed inputs and returns results or events. It does not
import GTK, Wails, HTTP routers or global application state to reach a backend.

Use the interfaces already present in each repository before adding one.
A facade must expose a bounded task, such as disk plans or tab navigation.
Do not pass a service registry, a generic lookup function or the whole state
through a new name. That would preserve the original dependencies.

## Work map

These are scope and test targets derived from the linked findings. They are
not a status table. Read the issue discussion and open PRs before each patch;
the original line counts and dependency counts are historical observations.

| Repository and existing tracker | First bounded task | Evidence for the boundary |
|---|---|---|
| [Spindle #493](https://github.com/tuna-os/spindle/issues/493), [#551](https://github.com/tuna-os/spindle/issues/551), [#498](https://github.com/tuna-os/spindle/issues/498), [#662](https://github.com/tuna-os/spindle/issues/662) | Extract one route domain and its required state; compose routers at the root. | Exercise a handler with an in-memory domain adapter, without constructing full `AppState`. Compare route paths, middleware and error responses. |
| [Mariner #70](https://github.com/tuna-os/mariner/issues/70) | Move tab lifecycle into a controller with explicit navigation and view callbacks. | Test tab open, switch and close without constructing `AppWindow` or unrelated file/tag services. Check signal cleanup when the window closes. |
| [Wootc #297](https://github.com/tuna-os/wootc/issues/297) | Continue the install engine seam behind the Wails methods; keep platform operations injected. | Test validation, step order, cancellation and error cleanup without Wails or Windows globals. Preserve exported methods, JSON DTOs and events. |
| [Bootc-installer #80](https://github.com/tuna-os/bootc-installer/issues/80), [#85](https://github.com/tuna-os/bootc-installer/issues/85) | Keep disk-plan policy pure; move fisherman launch, log transport and recipe cleanup behind a GTK-free adapter. | Import and test the adapter without GI stubs. Cover launch failure, cancel, log drain and credential cleanup; compare disk payloads. |
| [Corral #305](https://github.com/tuna-os/corral/issues/305) | Use its screen/command separation as a review example; verify any remaining flow before proposing work. | Test transitions through `Update` with command doubles; ensure backend calls remain in commands. |
| [Xfce-linux #119](https://github.com/tuna-os/xfce-linux/issues/119) | Extract BuildStream parsing and the state model before process, telemetry, HTTP and template adapters. | Import parser tests normally, without patching thread startup. Test recorded log input without Podman, `/proc` sampling or an HTTP server. |
| [Finupdate #62](https://github.com/tuna-os/finupdate/issues/62), [#125](https://github.com/tuna-os/finupdate/issues/125), [#113](https://github.com/tuna-os/finupdate/issues/113) | Separate update orchestration and registry access from UI state; preserve the runner and consumer contracts. | Test module failure and a single terminal outcome using the real runner with fake modules. Check C ABI and D-Bus consumers when their contracts change. |

Reuse these specific work records:

- Spindle [#494's consolidation comment](https://github.com/tuna-os/spindle/issues/494#issuecomment-6355877050)
  points to #493/#551 for route extraction. Keep handler dependency work linked
  to #498/#662; a file split alone does not prove isolation.
- Wootc #297 links [#659](https://github.com/tuna-os/wootc/pull/659)
  as partial work. Review that diff before you change the engine seam.
- Bootc-installer [#86](https://github.com/tuna-os/bootc-installer/pull/86)
  merged a disk-plan extraction. Build on that extraction.
- Corral [#580](https://github.com/tuna-os/corral/pull/580) merged the later
  command extractions. The [completion account](https://github.com/tuna-os/corral/issues/305#issuecomment-6201931420)
  links the earlier transition and screen work. Use those diffs as examples,
  not as evidence that the other repositories meet the same boundary.
- Finupdate #113 concerns exported consumers, not service size. Keep its
  [existing child tasks](https://github.com/tuna-os/finupdate/issues/113#issuecomment-5840177970)
  separate from #62, and retain #125's aggregate-outcome test during extraction.

## B2: Migrate one flow through all four phases

Start with the Xfce parser as a suggested pure-code pilot, using Corral's
transition tests as a review reference. Then apply the same sequence to one
Spindle domain and one desktop controller. Installer and update work also
needs failure and cleanup evidence before moving the privileged adapter.
Repositories can proceed independently; there is no shared library or release
that must land first.

1. **Extract the facade.** Record the current inputs, outputs, event order and
   lifetime rules. Move one task behind a narrow interface while the old
   caller still works. Keep behavior and public contracts unchanged.
2. **Add test adapters.** Run the domain or controller with deterministic
   doubles. Cover success, rejected input, backend failure, cancellation and
   cleanup where applicable. Test the production adapter's translation too.
3. **Convert callers.** Give each migrated handler or view its explicit
   dependencies. Keep only transport conversion and widget updates in that layer.
   Wire the production implementation at startup.
4. **Remove full-state access.** Remove the old fallback for that flow. Add
   an import or dependency check that rejects its return. Run the existing
   integration tests to prove the real composition still works.

Repeat for the next flow after the first has all four pieces. Reviewers can
then measure which dependencies each caller can access.

## B3: Attach proof to each local PR

The contributor who extracts a flow owns its evidence and links the local PR
from the existing tracker. The repository's reviewers assess its behavior and
lifetime rules. The work map does not assign owners.

Include the source revision, old and new dependency lists, test command and
result, and the public contracts compared. An isolated test must fail if it
tries to start an unrelated backend. A production adapter test must detect
wrong argument, event or error translation. Keep a small integration test for
startup wiring. Doubles do not prove that the real adapters connect.

For install/update flows, retain privilege checks, argument validation,
credential cleanup and a single terminal result. Exercise destructive
operations through doubles or the repository's disposable test harness.
This plan does not authorize their use against host disks.

Keep each change reversible: wire the previous adapter back at the composition
root if a regression appears. Do not combine extraction with a protocol,
product-policy or data-format change. Such changes need their own review.

## B4: Track evidence without copying live status

Use the existing issues as the work queue. Read their current state and
comments with authenticated `gh` commands, for example:

```bash
GH_TOKEN="$GH_TOKEN" gh issue view 3025 --repo tuna-os/tunaos --comments
GH_TOKEN="$GH_TOKEN" gh issue view 551 --repo tuna-os/spindle --comments
GH_TOKEN="$GH_TOKEN" gh pr list --repo tuna-os/spindle --state open
GH_TOKEN="$GH_TOKEN" gh pr view 580 --repo tuna-os/corral \
  --json url,state,mergedAt,baseRefName,mergeCommit
```

An issue marked closed is a navigation hint. Verify merged PRs and inspect
the target branch before you mark a boundary complete. If a flow still
uses full-state injection, link the remainder from its local tracker and
#3025. Do not create a second issue for the same extraction.

Keep #3025 open until each row has evidence for narrow dependencies, isolated
tests, real wiring tests and removal of the old access path. A reviewer can
also confirm why a row needs no further change.
This plan documents how to coordinate the work. It does not
complete the sibling refactors or establish a new organization-wide CI gate.
