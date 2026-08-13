# scripts/ — build orchestration & tooling

Scripts in this directory run on the **build host** (outside the container).
They orchestrate image builds, CI pipelines, ISO generation, and
verification — as opposed to `build_scripts/`, which runs **inside** the
container during `podman build` (see `build_scripts/README.md`).

Invoked by:
- `just` (via `just build`, `just iso`, etc. — see `just/`)
- GitHub Actions workflows (`.github/workflows/`)
- Developers directly on the command line

## Key scripts

| Script | Purpose |
|---|---|
| `resolve-flavor.sh` | Routes a variant/flavor to its Containerfile, target, parent, and build flags |
| `resolve-image.sh` | Resolves image references (base, common, brew, akmods) |
| `build-image-inner.sh` | The build engine (env-var driven) |
| `sync-upstream-snapshots.sh` | Syncs and drift-checks the `_upstream-snapshots/` tree |

See `docs/AGENT_GUIDE.md`'s Key Files table for the fuller list and how
these fit into the overall build pipeline (`docs/PIPELINE.md`,
`docs/build-pipeline.md`).
