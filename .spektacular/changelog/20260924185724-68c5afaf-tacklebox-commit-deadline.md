---
created_date: "2026-09-24"
document_status: final
closed_date: "2026-09-24"
---

# Tacklebox commit deadline on main (tunaOS#1893)

## What was built

- `tunaos_run_tacklebox` (`scripts/lib/tacklebox.sh`) gives tacklebox's post-customize `podman commit` a 1800-second deadline by default (`TBOX_CUSTOMIZE_COMMIT_TIMEOUT`), accepts `0` or any positive whole number as an override, and fails with exit 2 on anything else before tacklebox starts. The value is function-local, so callers that source the library are unchanged afterwards.
- Every exported `TBOX_*` variable now reaches tacklebox on the container path as an explicit `--env`, as it already did on the host-binary path; the forwarded knobs are logged on both paths. `--env-host` is still never used.
- The tacklebox pin moves from `f3dd168` to `ae93e9b` (tuna-os/tacklebox#300), the first revision that reads the setting; it descends from the `fd95174` floor.
- Tests: 11 new bats cases (5 structural ports from v4, 6 behavioural against the real function with a stub podman / fake binary) and `tests/regressions/test_issue_1893_customize_commit_deadline.py`.
- Docs: "Environment contract" and "Commit deadline" sections in `docs/TACKLEBOX-CONTRACT.md`; §4 row 42 in `docs/ci-troubleshooting.md`; corrected comment in `weekly-desktop-screenshots.yml`.

## Why it matters

Large desktop ISO builds on main (skipjack:xfce, marlin:gnome/kde) failed at exactly 600 s in the commit step although the image was fine. The fix existed on v4 (#2507) and an unmerged PR branch (#2598) but did not cherry-pick onto main. Anyone building a tunaOS ISO in CI or locally benefits; workflows can also now set any tacklebox knob on the container path.

## Deviations from the plan

- Error message also echoes the bad value and states that `0` disables the inner deadline.
- The regression test pins `TACKLEBOX_FROM_SOURCE=0` and asserts one `podman run` line (v4's version could silently take the host path).
- The docs were rewritten in STE style instead of copied from v4; the new prose adds 0 STE findings (repo total 1644/1650).
- Otherwise none.
