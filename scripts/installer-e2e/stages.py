"""The seven e2e stages of the image-installer track (tunaOS#4910).

Stage order follows the issue: live boot, installer pages, install, TPM
unlock or recovery key, first-boot setup, desktop + `bootc status`,
`bootc switch` + rollback. Per-cell extras come from the medium row:

- btrfs cells (non-EL): stage 3 also asserts a file written in the live
  session survives the install (seed/migrate keeps the session, #4908).
- EL10 cells (xfs): the reboot/soft-reboot stage stays a TODO marker until
  the #4908/#4909 mechanism lands; the harness records it, never fakes it.
"""

from __future__ import annotations

STAGES = (
    {
        "id": "live-boot",
        "title": "Live boot",
        "checks": ("medium boots to a live session", "readiness stamp present"),
    },
    {
        "id": "installer-pages",
        "title": "Installer pages",
        "checks": ("frontend window mapped", "disk page lists the target disk"),
    },
    {
        "id": "install",
        "title": "Install",
        "checks": ("confirm names the target disk", "install phase completes"),
    },
    {
        "id": "unlock",
        "title": "Recovery key saved, TPM unlock",
        "checks": (
            "the recovery key shows and the page after it shows",
            "the key opens the disk without the TPM (tried in stage 6)",
        ),
    },
    {
        "id": "first-boot-setup",
        "title": "First-boot setup",
        "checks": ("initial setup completes", "user session starts"),
    },
    {
        "id": "desktop-status",
        "title": "Desktop plus bootc status",
        "checks": ("desktop up", "`bootc status` names the installed digest"),
    },
    {
        "id": "switch-rollback",
        "title": "bootc switch plus rollback",
        "checks": (
            "`bootc switch` stages the candidate digest",
            "`bootc rollback` returns to the baseline",
        ),
    },
)

# A seeded btrfs root keeps the live session, so a file written live must
# still exist after the install. EL10 copies blocks and soft-reboots.
BTRFS_SURVIVES_FILE = "/var/tmp/installer-e2e-live-marker"
EL10_REBOOT_TODO = "TODO(#4908/#4909): EL10 soft-reboot handoff not built yet"


def plan_for_cell(cell):
    """Stage list for one installer_medium cell row, with per-cell extras."""
    filesystem = cell.get("filesystem", "")
    stages = [dict(s, checks=list(s["checks"])) for s in STAGES]
    if filesystem == "btrfs":
        for stage in stages:
            if stage["id"] == "install":
                stage["checks"] = [
                    *stage["checks"],
                    f"file {BTRFS_SURVIVES_FILE} written live survives",
                ]
    elif filesystem == "xfs":
        for stage in stages:
            if stage["id"] == "first-boot-setup":
                stage["checks"] = [*stage["checks"], EL10_REBOOT_TODO]
    return stages


def stage_ids():
    """The seven stage ids in run order."""
    return [s["id"] for s in STAGES]
