#!/usr/bin/env python3
"""Fill the installer parity matrix from the frontends' GPU-less captures.

WHY. `docs/INSTALLER-FRONTENDS.md` has a parity matrix fed by
`walkthrough-<flavor>.json`, and the only producer of that file has been
`scripts/installer-walkthrough.py` — a VM harness that OCRs QEMU screendumps
and therefore needs a virgl-capable host. niri and xfce are Smithay
compositors that render nothing without EGL_EXT_device_drm, so their rows have
read `_GPU_` since the matrix was written: never evaluated, not once. Two
crash-on-launch bugs and a 93%-white screen survived in exactly that gap,
because "no data" and "fine" look identical in a table.

Each frontend repo now runs an offscreen screenshot capture on a stock runner
and emits the same `walkthrough-<flavor>.json`. This imports those.

    scripts/import-frontend-parity.py [--check]

WHAT THIS MUST NOT DO, and the reason the script is shaped the way it is.

An offscreen capture and a VM run do NOT measure the same thing, and merging
them into one ✅ would be a worse failure than the blank cells it replaces —
it would claim coverage nobody has. Specifically, a capture that drives pages
programmatically inside the app's own process cannot speak to:

  * **Launches** — whether the flatpak starts under the real desktop.
  * **Renders** — whether a compositor with no GL can draw it. This is the
    precise thing niri and xfce are suspected to fail, and the capture runs
    offscreen, so it can never observe it.
  * **Advances** — whether a keypress moves the wizard. The capture calls
    navigateTo() directly. KDE's "enter activates no button" defect
    (tuna-installer-kde#4) is invisible to it by construction.

So this importer fills the SCREEN columns only, and tags every cell it writes
with its source. The first three columns stay the VM run's territory and are
left exactly as they are.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOC = os.path.join(REPO, "docs", "INSTALLER-FRONTENDS.md")
BEGIN = "<!-- BEGIN GENERATED — scripts/import-frontend-parity.py -->"
END = "<!-- END GENERATED — scripts/import-frontend-parity.py -->"

# gnome is upstream and unmodified, and ships no capture of ours.
FRONTENDS = [
    ("KDE", "kde", "tuna-os/tuna-installer-kde"),
    ("COSMIC", "cosmic", "tuna-os/tuna-installer-cosmic"),
    ("Niri", "niri", "tuna-os/tuna-installer-niri"),
    ("XFCE", "xfce", "tuna-os/tuna-installer-xfce"),
]

SCREENS = ["welcome", "disk", "encryption", "summary", "install", "done"]
REQUIRED = {"welcome", "disk", "summary"}


class _Failed:
    """A gh invocation that could not happen. Shaped like CompletedProcess so
    callers need no special case — a missing gh degrades to 'unfetched', which
    the matrix renders as ⬜, rather than taking the import down with a
    traceback."""
    returncode, stdout, stderr = 1, "", "gh CLI not found on PATH"


def gh(*args, **kw):
    try:
        return subprocess.run(["gh", *args], capture_output=True, text=True, **kw)
    except FileNotFoundError:
        return _Failed()


def fetch(repo, flavor, dest):
    """Newest walkthrough-<flavor>.json from that repo's screenshots workflow.

    Returns (data, run_url) or (None, reason). A frontend we cannot fetch is
    reported as unfetched — never silently dropped, and never carried forward
    from a previous import. A stale row that looks current is the failure mode
    this whole document exists to prevent.
    """
    r = gh("run", "list", "--repo", repo, "--workflow", "screenshots.yml",
           "--limit", "10", "--json", "databaseId,conclusion,headBranch,url")
    if r.returncode:
        return None, f"gh run list failed: {r.stderr.strip()[:120]}"
    try:
        runs = json.loads(r.stdout)
    except json.JSONDecodeError:
        return None, "could not parse gh output"

    # Only main. A PR run reports the branch's frontend, not the shipped one.
    runs = [x for x in runs if x.get("headBranch") == "main"]
    if not runs:
        return None, "no runs on main"

    for run in runs:
        out = os.path.join(dest, str(run["databaseId"]))
        d = gh("run", "download", str(run["databaseId"]), "--repo", repo,
               "--name", "gui-screenshots", "--dir", out)
        if d.returncode:
            continue
        path = os.path.join(out, f"walkthrough-{flavor}.json")
        if not os.path.exists(path):
            # The capture ran but predates the parity emitter.
            continue
        with open(path) as fh:
            return json.load(fh), run["url"]
    return None, "no run carried a parity report"


def cell(data, screen):
    reached = (data.get("screens") or {}).get(screen)
    if reached is None:
        return "⬜"
    if reached:
        return "✅ᶜ"
    # A required screen the capture could not find is a real gap — but it is
    # as often the frontend's wording missing the spec's keywords as a missing
    # screen. Both matter; neither is "it failed to install".
    return "❌ᶜ" if screen in REQUIRED else "⬜ᶜ"


def render(results):
    lines = [
        BEGIN,
        "",
        "| Frontend | Source | welcome | disk | encryption | summary | install | done |",
        "|----------|--------|---------|------|------------|---------|---------|------|",
    ]
    notes = []
    for label, flavor, repo in FRONTENDS:
        data, ref = results[flavor]
        if data is None:
            lines.append(f"| {label} | — | " + " | ".join(["⬜"] * 6)
                         + " |")
            notes.append(f"- **{label}** — no parity report imported ({ref}).")
            continue
        cells = " | ".join(cell(data, s) for s in SCREENS)
        src = f"[capture]({ref})"
        lines.append(f"| {label} | {src} | {cells} |")
        notes.append(
            f"- **{label}** — {data.get('frames')} pages, "
            f"{data.get('rendered_frames')} passed the pixel audit, "
            f"{data.get('advanced_transitions')} transitions. "
            f"Text from `{data.get('text_source', 'unknown')}`.")
    lines += ["", "ᶜ = GPU-less offscreen capture in the frontend's own repo.",
              "**It attests to screen parity only.** It drives pages in-process,",
              "so it cannot observe whether the app launches under the real",
              "desktop, whether a GL-less compositor can draw it, or whether a",
              "keypress advances the wizard — the first three columns of the",
              "matrix above remain the VM walkthrough's job, and a green row",
              "here is not a substitute for one.", ""]
    lines += notes + ["", END]
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="fail if the doc is out of date; write nothing")
    args = ap.parse_args()

    with tempfile.TemporaryDirectory() as tmp:
        results = {f: fetch(repo, f, tmp) for _, f, repo in FRONTENDS}

    for label, flavor, _ in FRONTENDS:
        data, ref = results[flavor]
        print(f"{label:8s} {'ok' if data else 'MISSING'}  {ref}")

    block = render(results)
    with open(DOC) as fh:
        doc = fh.read()

    if BEGIN in doc and END in doc:
        new = re.sub(re.escape(BEGIN) + r".*?" + re.escape(END), block, doc,
                     flags=re.S)
    else:
        print(f"FAIL: markers not found in {DOC}", file=sys.stderr)
        return 2

    if args.check:
        if new != doc:
            print("FAIL: parity section is out of date — run without --check",
                  file=sys.stderr)
            return 1
        print("parity section is current")
        return 0

    if new == doc:
        print("no change")
        return 0
    with open(DOC, "w") as fh:
        fh.write(new)
    print(f"updated {DOC}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
