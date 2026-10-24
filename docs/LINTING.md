# Lint tool and gate contract

`toolchain/lint-tools.json` is the source of truth for the tools that can change
or interpret repository configuration.

| Tool | Version | Source |
|---|---:|---|
| actionlint | 1.7.12 | `rhysd/actionlint` GitHub release |
| ShellCheck | 0.11.0 | `koalaman/shellcheck` GitHub release |
| just | 1.59.0 | `casey/just` GitHub release |
| shfmt | 3.14.1 | `mvdan/sh` GitHub release |

The contract records the release tag, asset name, extraction path and SHA-256
for Linux and macOS on x86-64 and ARM64. `scripts/lint_tools.py install`
verifies the downloaded asset before installing it. `verify` checks all four
versions before `just fix`, `just lint` or `just check` runs. An older binary
earlier on `PATH` is an error, not a fallback.

## Bootstrap

```bash
python3 scripts/lint_tools.py install --bin-dir "$HOME/.local/bin"
export PATH="$HOME/.local/bin:$PATH"
just setup
just fix && just check
```

Set `TUNAOS_LINT_BIN_DIR` when `just setup` should use another prefix. CI uses
the same installer with an ephemeral runner directory. `scripts/run-config-lint.sh`
provides the shared ShellCheck, shfmt, YAML, JSON, actionlint and just-format
commands, including positive and intentionally invalid ShellCheck/actionlint
fixtures.

## Gate policy

All checks in `.github/workflows/lint.yml` are merge gates:

- ShellCheck findings (non-errors are visible and advisory; errors gate),
  shfmt drift, yamllint, JSON syntax, actionlint and just formatting;
- immutable GitHub Action pins; and
- package-source policy.

The local `just check` command runs the same configuration lint commands.
`actionlint` was previously advisory in CI while fatal locally; it is gating in
both places now. The action-pin and package-source checks remain independently
gating because they enforce supply-chain and release policy. Changing a check
to advisory, adding an ignore, or reducing the scanned paths is a policy change
that requires maintainer review. Vendored `_upstream-snapshots/`, generated
`.build/` content, external extension sources and package-repository checkouts
remain outside formatter and lint ownership.

## Updating a tool

1. Open the upstream GitHub release and select all four supported platform
   assets. Query the official release with
   `gh api repos/OWNER/REPOSITORY/releases/tags/TAG --jq '.assets[] | [.name, .digest] | @tsv'`
   and copy each `sha256:...` digest into `toolchain/lint-tools.json` (without
   the prefix); do not calculate hashes from a mirror.
2. Update the version, tag, asset names, archive members and exact version
   regular expression together.
3. Run `python3 -m pytest tests/test_lint_tools.py`, bootstrap the updated
   binaries into an empty directory, and put that directory first on `PATH`.
4. Run `just fix && just check`, `just test-contract`, and verify that `git diff`
   contains no unexplained formatter changes.

The version-and-digest change is reviewed as one unit. A release without all
supported assets does not replace the current tool.
