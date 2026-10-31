#!/usr/bin/env python3
"""Print one verdict per strict qualification leg as GitHub-flavoured Markdown.

Usage: summarize-strict-legs.py <iso-e2e output dir>

The strict harness (``scripts/iso-e2e.sh --strict-offline-gui``) runs a plain
and an encrypted leg and keeps going after one fails, so the job's single exit
code hides which leg stopped. This reads only files the harness already wrote
and reports each leg on its own. It never sends input, never writes evidence
and never marks a leg or a target qualified: a leg is "passed" only when the
harness's own per-leg fragment (``strict-qual-<mode>.json``) exists with every
required observation true.

Failure labels are derived from the evidence, not assumed. The encrypted leg
is labelled "unresolved prompt visibility (#3380)" only when its installed-boot
helper log carries the helper's own "passphrase prompt never appeared" line
after a completed GUI install. Any other failure keeps a generic label.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

MODES = ("plain", "luks")
MAX_JSON_BYTES = 1024 * 1024
MAX_LOG_BYTES = 16 * 1024 * 1024

# Every observation a passing leg must carry. This is the harness's fragment
# schema (verify_strict_installed_boot in scripts/iso-e2e.sh); a fragment that
# lacks one of these is not a pass.
REQUIRED_TRUE = (
    "installed_boot",
    "desktop_contract",
    "cold_boot",
    "warm_boot",
    "media_detached",
    "boot_arguments_unmodified",
)

PROMPT_NEVER_APPEARED = "!!! passphrase prompt never appeared"
NO_USERSPACE_AFTER_UNLOCK = "!!! first boot never reached userspace after unlock"

# GitHub issue that owns the unresolved encrypted cold-boot prompt question.
LUKS_PROMPT_ISSUE = "#3380"


def find(root: Path, *names: str) -> Path | None:
    """First existing file among root/name and root/strict-diagnostics/name."""
    for name in names:
        for base in (root, root / "strict-diagnostics"):
            path = base / name
            if path.is_file():
                return path
    return None


def load_json(path: Path | None) -> dict | None:
    if path is None:
        return None
    try:
        if path.stat().st_size > MAX_JSON_BYTES:
            return None
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def log_contains(path: Path | None, needle: str) -> bool:
    if path is None:
        return False
    try:
        with path.open("rb") as stream:
            data = stream.read(MAX_LOG_BYTES)
    except OSError:
        return False
    return needle.encode() in data


def fragment_problem(mode: str, fragment: dict) -> str | None:
    if fragment.get("mode") != mode:
        return f"fragment names mode {fragment.get('mode')!r}"
    missing = [key for key in REQUIRED_TRUE if fragment.get(key) is not True]
    if missing:
        return "observations not true: " + ", ".join(missing)
    # The prompt must match the mode: shown for LUKS, absent for plain.
    if fragment.get("passphrase_prompt") is not (mode == "luks"):
        return "passphrase_prompt does not match the mode"
    return None


def observer_note(root: Path) -> str:
    report = load_json(find(root, "strict-luks-cold-observation/observations.json"))
    if report is None:
        return ""
    status = report.get("status")
    frames = report.get("frames")
    classes: list[str] = []
    if isinstance(frames, list):
        for frame in frames:
            label = frame.get("classification") if isinstance(frame, dict) else None
            if isinstance(label, str) and label not in classes:
                classes.append(label)
    note = f"screen gate status `{status}`" if isinstance(status, str) else ""
    if classes:
        note += f", frames classified `{'`, `'.join(classes)}`"
    return note


def judge(root: Path, mode: str, desktop: str = "gnome") -> tuple[str, str]:
    """Return (verdict, detail) for one leg."""
    fragment_path = find(root, f"strict-qual-{mode}.json")
    if fragment_path is not None:
        fragment = load_json(fragment_path)
        if fragment is None:
            return "failed: malformed leg fragment", f"`{fragment_path.name}` is not a JSON object"
        problem = fragment_problem(mode, fragment)
        if problem:
            return "failed: leg fragment rejected", problem
        return (
            "passed",
            f"GUI install {fragment.get('install_duration_s')}s; installed boots with the ISO "
            f"detached and unmodified arguments: cold {fragment.get('cold_boot_s')}s, "
            f"warm {fragment.get('warm_boot_s')}s",
        )

    # Retained diagnostics (strict-diagnostics/) do not stage the fragment. The
    # harness logs the boot times only after both installed boots verified, so
    # that line is the next best record; say so rather than call it a pass.
    if log_contains(find(root, "strict-offline-evidence.log"), f"installed_{mode}_boot_times "):
        return (
            "passed (evidence log only)",
            "boot times logged after both installed boots verified; the leg fragment is not in this directory",
        )

    report_path = find(root, f"walkthrough-{mode}/walkthrough-{desktop}.json")
    started = find(root, f"strict-{mode}-started.txt", f"strict-{mode}-live-serial.log") or (
        find(root, "strict-offline-evidence.log")
        if log_contains(find(root, "strict-offline-evidence.log"), f"phase=live-{mode} ")
        else None
    )
    if report_path is None and started is None:
        return "not run", "no start marker, no installer report"

    report = load_json(report_path)
    if report is None:
        return "failed: installer GUI report absent", "the walkthrough wrote no readable report"
    transitions = report.get("transitions")
    last = transitions[-1] if isinstance(transitions, list) and transitions else "none"
    if not (report.get("submitted") is True and report.get("accepted") is True
            and report.get("completed") is True):
        return (
            "failed: installer GUI did not complete",
            f"submitted={report.get('submitted')}, accepted={report.get('accepted')}, "
            f"completed={report.get('completed')}, last state `{last}`",
        )

    gui = "GUI install completed"
    if mode == "luks":
        log = find(root, "strict-luks-installed-serial.log")
        if log_contains(log, PROMPT_NEVER_APPEARED):
            detail = f"{gui}; unmodified installed cold boot showed no passphrase prompt"
            note = observer_note(root)
            if note:
                detail += f" ({note})"
            return f"failed: unresolved prompt visibility ({LUKS_PROMPT_ISSUE})", detail
        if log_contains(log, NO_USERSPACE_AFTER_UNLOCK):
            return (
                "failed: installed boot did not reach userspace after unlock",
                f"{gui}; the passphrase was accepted but userspace never started",
            )
    return "failed: installed boot did not verify", f"{gui}; no passing leg fragment was written"


def summarize(root: Path, desktop: str = "gnome") -> str:
    rows = [(mode, *judge(root, mode, desktop)) for mode in MODES]
    lines = [
        "## Strict offline GUI qualification: per-leg verdicts",
        "",
        "| Leg | Verdict | Evidence |",
        "|---|---|---|",
    ]
    lines += [f"| {mode} | {verdict} | {detail} |" for mode, verdict, detail in rows]
    lines.append("")
    passed = all(verdict == "passed" for _, verdict, _ in rows)
    receipt = find(root, "qualification-evidence.json")
    if passed and receipt is not None:
        lines.append(
            "Both legs passed and the harness wrote `qualification-evidence.json`. "
            "The next step validates it; this summary does not qualify the target."
        )
    elif passed:
        lines.append(
            "Both legs passed but `qualification-evidence.json` is absent, so the "
            "target is not qualified."
        )
    else:
        lines.append(
            "Not qualified: at least one leg did not pass. No thresholds, boot "
            "arguments or gates were relaxed to produce this result."
        )
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    if len(argv) not in (2, 3) or (len(argv) == 3 and argv[2] != "xfce"):
        print("usage: summarize-strict-legs.py <iso-e2e output dir> [xfce]", file=sys.stderr)
        return 2
    root = Path(argv[1])
    if not root.is_dir():
        print(f"summarize-strict-legs: {root} is not a directory", file=sys.stderr)
        return 2
    sys.stdout.write(summarize(root, argv[2] if len(argv) == 3 else "gnome"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
