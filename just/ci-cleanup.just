# --- CI hygiene: job cleanup and stale-run reaping ---
# Workflows call these instead of carrying their own shell. Both are thin
# wrappers: the rules live in scripts/ci-cleanup.py and scripts/ci-reap-stale.py,
# where tests/test_ci_cleanup.py and tests/test_ci_reap_stale.py drive them.

# Remove what THIS CI job created (run-scoped containers, registered images, QEMU/loop devices, owned scratch) and nothing else; safe to run twice or when nothing exists
ci-cleanup:
    #!/usr/bin/env bash
    set -euo pipefail
    cd {{ justfile_directory() }}
    python3 "{{ justfile_directory() }}/scripts/ci-cleanup.py" run

# Cancel runs stuck queued/in_progress (STALE_QUEUED_HOURS, default 6) and delete old runs/expired artifacts (KEEP_RUN_DAYS, default 14); DRY_RUN=1 prints only
ci-reap-stale:
    #!/usr/bin/env bash
    set -euo pipefail
    cd {{ justfile_directory() }}
    python3 "{{ justfile_directory() }}/scripts/ci-reap-stale.py"
