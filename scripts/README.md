# scripts/ — Build Orchestration & Tooling

Scripts in this directory run on the **build host** (outside the container).
They orchestrate image builds, CI pipelines, ISO generation, and verification.

These scripts are invoked by:
- The `Justfile` (via `just build`, `just iso`, etc.)
- GitHub Actions workflows
- Developers directly on the command line
