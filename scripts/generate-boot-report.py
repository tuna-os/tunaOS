#!/usr/bin/env python3
"""Generate the weekly boot screenshot report.

Replaces the inline bash that used to live in
.github/workflows/weekly-boot-report.yml. The Python version exists because
this version of the report fans out across:

  - .github/build-config.yml         — for the live (variant, flavor) matrix
  - workflow artifacts                — to fetch each boot screenshot
  - workflow runs (Build, iso-e2e)    — to embed pass/fail status
  - the published OCI images          — to extract /usr/share/tunaos/missing-on-*
  - the `screenshots` branch          — to commit images + diff vs last week
  - GitHub Issues                     — to publish the final report

That's six APIs and a lot of branching; bash was getting hard to read.

This script is meant to be invoked by the workflow itself. It uses the
GitHub CLI for all API access (matches every other workflow in the repo)
and writes the final markdown to stdout for the workflow to capture.

Inputs (env):
  GH_TOKEN            — already populated by actions/checkout
  GITHUB_REPOSITORY   — e.g. tuna-os/tunaos
  GITHUB_RUN_ID       — passed-through for the report footer
  REPORT_DATE         — YYYY-MM-DD (defaults to today UTC)
  TODAY_BRANCH        — branch in `screenshots` where today's PNGs land
                        (defaults to "boot/${REPORT_DATE}")
  PREVIOUS_BRANCH     — optional; if set, screenshots are SHA-compared
                        against the same combo there for change detection
"""

from __future__ import annotations

import base64
import dataclasses
import datetime as dt
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
from typing import Iterable


REPO = os.environ["GITHUB_REPOSITORY"]
REPO_OWNER = REPO.split("/", 1)[0]
TODAY = os.environ.get("REPORT_DATE") or dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")
TODAY_BRANCH_PATH = os.environ.get("TODAY_BRANCH", f"boot/{TODAY}")
PREVIOUS_BRANCH_PATH = os.environ.get("PREVIOUS_BRANCH", "")

# Age thresholds for the staleness flag. Tuned for the weekly cadence — a
# screenshot from yesterday is fine, one from last month is suspect.
FRESH_DAYS = 7
STALE_DAYS = 30


# ── Helpers ─────────────────────────────────────────────────────────────────


def gh(*args, **kwargs) -> subprocess.CompletedProcess[str]:
    """Run `gh <args>` and return the result. Caller checks rc."""
    return subprocess.run(
        ["gh", *args],
        capture_output=True,
        text=True,
        **kwargs,
    )


def gh_json(*args) -> object:
    """Like gh() but parses stdout as JSON, raises on non-zero."""
    result = gh(*args)
    result.check_returncode()
    return json.loads(result.stdout)


def age_marker(timestamp: str | None) -> tuple[str, str]:
    """Return (emoji, age-string) for a screenshot timestamp.

    Inputs are RFC3339 strings from the GitHub API. Outputs:
       ✅  ≤ 7 days       — fresh, no concern
       ⚠️  8–30 days      — getting stale, flag visibly
       ❌  > 30 days      — way too old, gate the publish UI
       ❓  None / parse-failure — never built
    """
    if not timestamp or timestamp == "N/A":
        return "❓", "never"
    try:
        ts = dt.datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError:
        return "❓", timestamp
    now = dt.datetime.now(dt.timezone.utc)
    days = (now - ts).days
    if days <= FRESH_DAYS:
        emoji = "✅"
    elif days <= STALE_DAYS:
        emoji = "⚠️"
    else:
        emoji = "❌"
    if days <= 0:
        return emoji, "today"
    if days == 1:
        return emoji, "1 day"
    return emoji, f"{days} days"


def status_emoji(conclusion: str | None) -> str:
    """Map a workflow conclusion to an emoji marker."""
    return {
        "success": "✅",
        "failure": "❌",
        "cancelled": "⏹️",
        "skipped": "⏭️",
        "timed_out": "⌛",
        None: "❓",
        "": "❓",
    }.get(conclusion, "❓")


# ── Build matrix ────────────────────────────────────────────────────────────


@dataclasses.dataclass
class Combo:
    variant: str
    flavor: str
    build_iso: bool
    build_qcow2: bool

    @property
    def key(self) -> str:
        return f"{self.variant}-{self.flavor}"


def load_combos() -> list[Combo]:
    """Read build-config.yml and produce the screenshot matrix.

    We honor the same `build_iso` / `build_qcow2` flags publish-isos.yml uses
    so the report's matrix matches what's actually built.
    """
    config_path = pathlib.Path(".github/build-config.yml")
    # The runner doesn't have yq pre-installed in every workflow. Use Python
    # for YAML parsing so this script has no external deps beyond `gh`.
    try:
        import yaml  # type: ignore[import-untyped]
    except ImportError:
        subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", "PyYAML"], check=True)
        import yaml  # type: ignore[import-untyped]

    data = yaml.safe_load(config_path.read_text())
    combos: list[Combo] = []
    for variant in data.get("variants", []):
        vid = variant["id"]
        for flavor in variant.get("flavors", []):
            if not flavor.get("build_iso") and not flavor.get("build_qcow2"):
                # Skip image-only flavors that don't produce screenshots
                continue
            combos.append(
                Combo(
                    variant=vid,
                    flavor=flavor["id"],
                    build_iso=bool(flavor.get("build_iso")),
                    build_qcow2=bool(flavor.get("build_qcow2")),
                )
            )
    return combos


# ── Artifact lookup ─────────────────────────────────────────────────────────


def fetch_latest_artifact(name: str, dest_dir: pathlib.Path) -> dict | None:
    """Download the most recent artifact with the given name.

    Returns dict with keys:
        path     — local path to the extracted screenshot.png
        created  — RFC3339 timestamp from the artifact
        run_id   — the workflow_run.id that produced it (for back-links)
    Or None if no matching artifact exists.
    """
    data = gh_json(
        "api",
        f"/repos/{REPO}/actions/artifacts?name={name}&per_page=1",
    )
    artifacts = data.get("artifacts") or []
    if not artifacts:
        return None
    art = artifacts[0]
    dest = dest_dir / name
    dest.mkdir(parents=True, exist_ok=True)
    rc = gh(
        "run", "download", str(art["workflow_run"]["id"]),
        "--repo", REPO,
        "--name", name,
        "--dir", str(dest),
    )
    if rc.returncode != 0:
        return None
    screenshot = dest / "screenshot.png"
    if not screenshot.is_file():
        return None
    return {
        "path": screenshot,
        "created": art.get("created_at"),
        "run_id": art["workflow_run"]["id"],
    }


# ── Workflow-status lookup ──────────────────────────────────────────────────


def latest_workflow_run(workflow_file: str) -> dict | None:
    """Most-recent run of the given workflow file. Status only — we don't
    care about jobs at this level."""
    try:
        data = gh_json(
            "api",
            f"/repos/{REPO}/actions/workflows/{workflow_file}/runs?per_page=1&branch=main",
        )
        runs = data.get("workflow_runs") or []
        return runs[0] if runs else None
    except Exception:
        return None


def build_status_for(variant: str) -> dict | None:
    """Latest Build <Variant> conclusion. Wraps the per-variant build
    workflows (build-yellowfin.yml etc.) so we don't have to special-case
    them at the call site."""
    return latest_workflow_run(f"build-{variant}.yml")


def e2e_status_for(variant: str, flavor: str) -> dict | None:
    """Latest iso-e2e run; the matrix is variant×flavor-keyed so we'd need
    job-level inspection to be precise. For the report we just surface the
    workflow's overall conclusion (which fails-fast if any matrix cell did)."""
    return latest_workflow_run("iso-e2e.yml")


# ── Missing-package wishlist ────────────────────────────────────────────────


def extract_wishlist(variant: str, flavor: str, tmp_root: pathlib.Path) -> list[str]:
    """Pull /usr/share/tunaos/missing-on-<variant>.txt from the published
    image. We use `podman create + cp + rm` rather than `podman run` so we
    don't pay for `dnf` startup just to cat a file.

    Returns the deduped package-name list (without the header comments).
    """
    image = f"ghcr.io/{REPO_OWNER}/{variant}:{flavor}"
    container = subprocess.run(
        ["podman", "create", "--pull=newer", image],
        capture_output=True,
        text=True,
    )
    if container.returncode != 0:
        # Image probably doesn't exist or isn't reachable from the runner.
        return []
    cid = container.stdout.strip()
    try:
        host_path = tmp_root / f"missing-{variant}.txt"
        cp = subprocess.run(
            ["podman", "cp", f"{cid}:/usr/share/tunaos/missing-on-{variant}.txt", str(host_path)],
            capture_output=True,
        )
        if cp.returncode != 0 or not host_path.exists():
            return []
        names = sorted({
            line.strip()
            for line in host_path.read_text().splitlines()
            if line.strip() and not line.startswith("#")
        })
        return names
    finally:
        subprocess.run(["podman", "rm", cid], capture_output=True)


# ── Screenshots branch I/O ──────────────────────────────────────────────────


def commit_screenshot(local_path: pathlib.Path, repo_path: str) -> bool:
    """Upload `local_path` to the `screenshots` branch at `repo_path`,
    overwriting any prior file at that location. Returns True on success."""
    if not local_path.is_file():
        return False
    existing = gh(
        "api",
        f"/repos/{REPO}/contents/{repo_path}?ref=screenshots",
        "--jq", ".sha",
    )
    existing_sha = existing.stdout.strip() if existing.returncode == 0 else ""
    payload = {
        "message": f"boot-report: {repo_path}",
        "content": base64.b64encode(local_path.read_bytes()).decode("ascii"),
        "branch": "screenshots",
    }
    if existing_sha and existing_sha != "null":
        payload["sha"] = existing_sha
    proc = subprocess.run(
        ["gh", "api", "--method", "PUT",
         f"/repos/{REPO}/contents/{repo_path}", "--input", "-"],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
    )
    return proc.returncode == 0


def fetch_previous_hash(repo_path: str) -> str | None:
    """Get the sha256 of last week's screenshot for the same combo."""
    if not PREVIOUS_BRANCH_PATH:
        return None
    prev_path = repo_path.replace(TODAY_BRANCH_PATH, PREVIOUS_BRANCH_PATH, 1)
    api = gh(
        "api",
        f"/repos/{REPO}/contents/{prev_path}?ref=screenshots",
    )
    if api.returncode != 0:
        return None
    try:
        data = json.loads(api.stdout)
    except json.JSONDecodeError:
        return None
    raw = base64.b64decode(data.get("content", ""))
    if not raw:
        return None
    return hashlib.sha256(raw).hexdigest()


# ── Pruning ─────────────────────────────────────────────────────────────────


def prune_screenshots_branch(keep_weeks: int = 4) -> None:
    """Delete weekly directories in `screenshots/boot/` older than the last
    `keep_weeks` snapshots. Today's dir is always preserved."""
    api = gh(
        "api",
        f"/repos/{REPO}/contents/boot?ref=screenshots",
    )
    if api.returncode != 0:
        return
    try:
        entries = json.loads(api.stdout)
    except json.JSONDecodeError:
        return
    if not isinstance(entries, list):
        return
    dated_dirs = sorted(
        (e["name"] for e in entries if e.get("type") == "dir"),
        reverse=True,
    )
    to_delete = dated_dirs[keep_weeks:]
    for name in to_delete:
        # Walk the dir and delete each file (Contents API only deletes files).
        dir_api = gh("api", f"/repos/{REPO}/contents/boot/{name}?ref=screenshots")
        if dir_api.returncode != 0:
            continue
        for f in json.loads(dir_api.stdout):
            if f.get("type") != "file":
                continue
            subprocess.run(
                ["gh", "api", "--method", "DELETE",
                 f"/repos/{REPO}/contents/boot/{name}/{f['name']}",
                 "-f", f"message=boot-report: prune boot/{name}/{f['name']}",
                 "-f", "branch=screenshots",
                 "-f", f"sha={f['sha']}"],
                capture_output=True,
            )


# ── Report rendering ────────────────────────────────────────────────────────


def render_combo_row(
    combo: Combo,
    iso_info: dict | None,
    qcow2_info: dict | None,
    iso_changed: bool | None,
    qcow2_changed: bool | None,
    build_run: dict | None,
    e2e_run: dict | None,
) -> str:
    """Return the markdown stanza for one combo."""
    lines: list[str] = []
    lines.append(f"## `{combo.variant}` / `{combo.flavor}`")
    lines.append("")
    lines.append(f"**Image:** `ghcr.io/{REPO_OWNER}/{combo.variant}:{combo.flavor}`")

    # Status line: build conclusion + e2e conclusion at a glance
    build_emoji = status_emoji(build_run.get("conclusion") if build_run else None)
    build_url = build_run.get("html_url") if build_run else ""
    e2e_emoji = status_emoji(e2e_run.get("conclusion") if e2e_run else None)
    e2e_url = e2e_run.get("html_url") if e2e_run else ""
    status_pieces = [
        f"build {build_emoji}" + (f" ([run]({build_url}))" if build_url else ""),
        f"e2e {e2e_emoji}" + (f" ([run]({e2e_url}))" if e2e_url else ""),
    ]
    lines.append("**Status:** " + " · ".join(status_pieces))
    lines.append("")

    # Per-screenshot row
    def cell(info: dict | None, changed: bool | None, kind: str) -> str:
        if info is None:
            return "_not available_"
        emoji, age = age_marker(info.get("created"))
        change_tag = ""
        if changed is True:
            change_tag = " · ✨ changed"
        elif changed is False:
            change_tag = " · = same"
        return (
            f"{emoji} {age}{change_tag}"
            f"<br>[![{combo.key} {kind}]({info['url']})]({info['url']})"
            f"<br><sub>[run](https://github.com/{REPO}/actions/runs/{info['run_id']})</sub>"
        )

    if iso_info or qcow2_info:
        lines.append("| ISO Boot | QCOW2 Boot |")
        lines.append("|:---:|:---:|")
        lines.append(
            "| "
            + cell(iso_info, iso_changed, "iso")
            + " | "
            + cell(qcow2_info, qcow2_changed, "qcow2")
            + " |"
        )
    else:
        lines.append("_no screenshots available for this combo_")
    lines.append("")
    lines.append("---")
    lines.append("")
    return "\n".join(lines)


def render_report(
    combos_data: list[dict],
    wishlist: dict[str, list[str]],
) -> str:
    """Final markdown for the issue body."""
    out: list[str] = []
    out.append(f"# 🖥️ Weekly Boot Screenshot Report")
    out.append("")
    out.append(f"**Generated:** {dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    out.append("")
    out.append("Each combo shows the ISO and QCOW2 boot screenshots from the latest")
    out.append("artifacts, the conclusion of the most recent Build and ISO E2E runs,")
    out.append("and whether the screenshot changed vs. last week's snapshot.")
    out.append("")
    out.append("Legend: ✅ fresh (≤7d) · ⚠️ stale (8–30d) · ❌ very stale (>30d)")
    out.append("· ✨ changed vs last week · = unchanged")
    out.append("")
    out.append("---")
    out.append("")

    # Split combos into fresh and stale so the alarming ones aren't buried
    fresh: list[str] = []
    stale: list[str] = []
    for row in combos_data:
        rendered = row["rendered"]
        if row["stale"]:
            stale.append(rendered)
        else:
            fresh.append(rendered)

    if fresh:
        out.append("## Fresh builds")
        out.append("")
        out.extend(fresh)
    if stale:
        out.append("## ⚠️ Stale or missing builds")
        out.append("")
        out.append(
            "These combos have screenshots older than 7 days (or none at all). "
            "Check if the underlying build is still healthy before publishing."
        )
        out.append("")
        out.extend(stale)

    # Aggregate the EL10 wishlist
    if wishlist:
        out.append("## 📦 EL10 packaging wishlist")
        out.append("")
        out.append(
            "Packages requested by build_scripts but not in the active EL10 "
            "repos (BaseOS/AppStream/EPEL/CRB/COPRs). Candidates for "
            "[tuna-os/github-copr](https://github.com/tuna-os/github-copr)."
        )
        out.append("")
        # Flatten + dedupe across all images
        all_missing: dict[str, set[str]] = {}
        for variant, names in wishlist.items():
            for n in names:
                all_missing.setdefault(n, set()).add(variant)
        if all_missing:
            out.append("| Package | Missing on |")
            out.append("|---|---|")
            for pkg in sorted(all_missing):
                variants = ", ".join(sorted(all_missing[pkg]))
                out.append(f"| `{pkg}` | {variants} |")
            out.append("")

    # Trigger publish footer
    dispatch_url = f"https://github.com/{REPO}/actions/workflows/publish-isos.yml"
    out.append("## 🚀 Release ISOs")
    out.append("")
    out.append(f"Review the screenshots above. If everything looks good, [trigger ISO publish]({dispatch_url}).")
    out.append("")
    out.append("_ISOs are also auto-published on the 1st and 15th of each month._")

    return "\n".join(out)


# ── Main ────────────────────────────────────────────────────────────────────


def main() -> int:
    combos = load_combos()
    print(f"==> Loaded {len(combos)} combos from build-config.yml", file=sys.stderr)

    work_root = pathlib.Path(tempfile.mkdtemp(prefix="boot-report-"))

    # Pre-fetch workflow status per variant (build) and global (e2e). Cache
    # these so we don't re-query for each flavor in the same variant.
    build_runs: dict[str, dict | None] = {}
    e2e_run = e2e_status_for("", "")

    combos_data: list[dict] = []
    wishlist: dict[str, list[str]] = {}

    for combo in combos:
        print(f"==> {combo.key}", file=sys.stderr)
        if combo.variant not in build_runs:
            build_runs[combo.variant] = build_status_for(combo.variant)

        iso_info = None
        if combo.build_iso:
            iso_info = fetch_latest_artifact(
                f"{combo.key}-boot-screenshot", work_root
            )
        qcow2_info = None
        if combo.build_qcow2:
            qcow2_info = fetch_latest_artifact(
                f"{combo.key}-qcow2-boot-screenshot", work_root
            )

        # Upload to the screenshots branch + record the public URL on the
        # info dict so render_combo_row can embed it.
        iso_changed = qcow2_changed = None
        if iso_info:
            repo_path = f"{TODAY_BRANCH_PATH}/{combo.key}-iso.png"
            commit_screenshot(iso_info["path"], repo_path)
            iso_info["url"] = (
                f"https://raw.githubusercontent.com/{REPO}/screenshots/{repo_path}"
            )
            new_hash = hashlib.sha256(iso_info["path"].read_bytes()).hexdigest()
            prev_hash = fetch_previous_hash(repo_path)
            if prev_hash is not None:
                iso_changed = new_hash != prev_hash
        if qcow2_info:
            repo_path = f"{TODAY_BRANCH_PATH}/{combo.key}-qcow2.png"
            commit_screenshot(qcow2_info["path"], repo_path)
            qcow2_info["url"] = (
                f"https://raw.githubusercontent.com/{REPO}/screenshots/{repo_path}"
            )
            new_hash = hashlib.sha256(qcow2_info["path"].read_bytes()).hexdigest()
            prev_hash = fetch_previous_hash(repo_path)
            if prev_hash is not None:
                qcow2_changed = new_hash != prev_hash

        # Wishlist is per-variant (lib.sh writes one file per variant), so
        # only fetch on the first flavor we encounter for that variant.
        if combo.variant not in wishlist:
            wishlist[combo.variant] = extract_wishlist(combo.variant, combo.flavor, work_root)

        # Determine staleness for sorting
        worst_age_days = -1
        for info in (iso_info, qcow2_info):
            if info and info.get("created"):
                try:
                    ts = dt.datetime.fromisoformat(info["created"].replace("Z", "+00:00"))
                    days = (dt.datetime.now(dt.timezone.utc) - ts).days
                    worst_age_days = max(worst_age_days, days)
                except ValueError:
                    pass
        is_stale = worst_age_days > FRESH_DAYS or (iso_info is None and qcow2_info is None)

        combos_data.append({
            "rendered": render_combo_row(
                combo,
                iso_info,
                qcow2_info,
                iso_changed,
                qcow2_changed,
                build_runs[combo.variant],
                e2e_run,
            ),
            "stale": is_stale,
        })

    # Drop empty wishlists so the final table doesn't show them
    wishlist = {k: v for k, v in wishlist.items() if v}

    report = render_report(combos_data, wishlist)
    print(report)

    # Best-effort prune; never fatal
    try:
        prune_screenshots_branch()
    except Exception as e:
        print(f"prune skipped: {e}", file=sys.stderr)

    shutil.rmtree(work_root, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
