#!/usr/bin/env bash
# Register what a CI job creates so `just ci-cleanup` can remove it later --
# and nothing else. Thin shell veneer over scripts/ci-cleanup.py, which owns
# the scope rule, the ledger and the removal (see its docstring).
#
# Source it, then:
#   ci_labels=(); mapfile -t ci_labels < <(ci_label_args)
#   podman run "${ci_labels[@]}" ...      # container swept by label on exit
#   ci_own_pidfile "$QEMU_PIDFILE"        # QEMU/swtpm stopped via their pidfile
#   ci_own_dir "$work"                    # tree removed if our marker survives
#   ci_own_image localhost/x:y [--root]   # untagged while it is still that image
#   ci_own_loop "$raw"                    # loop devices backed by $raw detached
#
# Every helper is a no-op outside a CI job (no GITHUB_RUN_ID) and never fails
# the caller: registration is best effort, the creating script's own trap is
# still the first line of defence.

_CI_SCOPE_PY="${TUNAOS_CI_CLEANUP:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/ci-cleanup.py}"

_ci_scope_run() {
	python3 "$_CI_SCOPE_PY" "$@" || return 0
}

ci_label_args() { _ci_scope_run labels; }
ci_scratch_dir() { python3 "$_CI_SCOPE_PY" scratch; }
ci_own_dir() { _ci_scope_run own dir "$1"; }
ci_own_pidfile() { _ci_scope_run own pidfile "$1"; }
ci_own_image() { _ci_scope_run own image "$@"; }
ci_own_loop() { _ci_scope_run own loop "$1"; }
