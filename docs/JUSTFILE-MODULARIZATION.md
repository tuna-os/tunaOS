# Justfile modularization standard

**Tracker**: [#508](https://github.com/tuna-os/tunaos/issues/508)
**Status**: adopted for tunaOS; cross-repo rollout pending maintainer
coordination

## Decision

Recipes that form a coherent subsystem belong in local `.just` modules under
`just/`, and the root `Justfile` imports them with a relative local import:

```just
import 'just/utilities.just'
import 'just/custom-overlay.just'
```

This is the supported mechanism in the current Just toolchain. Just imports
resolve local source files; an import such as
`import 'git@github.com:tuna-os/just-recipes.git'` does not fetch a repository
and fails when the source file is absent. A future shared recipe repository
therefore needs an explicit vendoring mechanism (submodule or pinned CI
checkout) before a consuming root file can import it.

## What belongs in a module

Extract a recipe group when it has a clear lifecycle or subsystem boundary,
for example:

- validation, test, and formatting helpers (`just/utilities.just`);
- custom image and ISO overlay operations (`just/custom-overlay.just`);
- VM/demo operations, ISO publishing, or other independent workflow groups.

Keep the root file responsible for global variables, the primary build graph,
and private primitives shared by multiple modules. Just imports share one
recipe/variable namespace, so an imported recipe may call a root private
helper, but names must remain unique across all imported files.

## Migration checklist for authorized repositories

For each repository with a large Justfile:

1. Inventory recipes by subsystem and record the current line count.
2. Extract one coherent group at a time into `just/<area>.just`.
3. Keep the recipe bodies byte-equivalent during extraction; verify with
   `just --show <recipe>` before and after.
4. Run the repository's syntax, unit, and integration checks after each group.
5. Update the root README/agent guide with the module map.
6. Repeat until the root file contains orchestration and shared primitives,
   not unrelated subsystem implementations.

The tunaOS baseline is the reference implementation: `custom-overlay.just`
was extracted first, followed by `utilities.just`, while `_ensure-deps` stays
in the root because both the build engine and imported recipes use it.

## Cross-repo follow-up

Do not create a `just-recipes` repository or add a remote import as an
individual repository change. That requires a maintainer decision about
version pinning, release compatibility, and how consuming repositories vendor
the files. If approved, the shared repository must be pinned (submodule or CI
checkout), imported from a local path, and tested against each consumer before
recipes are removed from that consumer's tree.
