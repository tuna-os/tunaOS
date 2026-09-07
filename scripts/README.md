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
| `evidence-bundle.sh` | Normalizes a gate's logs and verdicts under `evidence/<variant>/<flavor>/<arch>/` |
| `gen-ci-lanes.py` | Generates the PR/post-merge/scheduled workflow inventory in `docs/CI_SPEC.md` |
| `sync-upstream-snapshots.sh` | Syncs and drift-checks the `_upstream-snapshots/` tree |
| `iso-e2e.sh` | Boots an ISO or disk under QEMU: live smoke, SSH, `--luks` install + unlock, app launches |
| `install-checkpoints.py` | OCRs the frames `iso-e2e.sh` captured and asserts them against `tests/install-pipeline-screens.yaml` (see `docs/INSTALL-PIPELINE-CHECKPOINTS.md`) |
| `installer-walkthrough.py` | Drives the installer frontend with `sendkey` and asserts its pages against `tests/installer-screens.yaml` |
| `check-upstream-snapshot-size.sh` | Fails refreshes that exceed the snapshot size or change budget |

See `docs/AGENT_GUIDE.md`'s Key Files table for the fuller list and how
these fit into the overall build pipeline (`docs/PIPELINE.md`,
`docs/build-pipeline.md`).
