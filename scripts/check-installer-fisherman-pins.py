#!/usr/bin/env python3
"""Fail when a desktop's installer builds fisherman from the wrong repository.

WHY THIS EXISTS
---------------
fisherman moved from projectbluefin/fisherman to tuna-os/fisherman. Only ONE
of the five installer Flatpaks followed. For roughly two months afterwards:

  org.tunaos.InstallerKde     tuna-os/fisherman        027fa25c  2026-08-29
  bootc-installer (gnome)     projectbluefin submodule 6092be78  2026-06-23
  org.tunaos.InstallerCosmic  projectbluefin @ dev     35c8f6f1  2026-07-31
  org.tunaos.InstallerNiri    projectbluefin           35c8f6f1  2026-07-31
  org.tunaos.InstallerXfce    projectbluefin           35c8f6f1  2026-07-31

Every one of those Flatpaks was still being REBUILT daily, so nothing looked
stale. The packages were fresh; the sources were not. `marlin:cosmic` could
not install at all -- it died at step 9 of 10, 98% in, on a fisherman bug
fixed months earlier -- and no gate anywhere said so.

Renovate cannot catch this class: a git source aimed at a repository that no
longer moves has nothing to bump. Neither can anything that inspects the
published Flatpak's build date. The only reliable signal is the SOURCE, which
lives in five other repositories -- so this check reads them.

It is deliberately about the repository, not the revision. Pinning an older
revision of the LIVE repo is a normal, visible choice; sourcing a repo that
stopped moving is a silent one.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

# The repository fisherman actually lives in now.
CANONICAL = "tuna-os/fisherman"

# Where each desktop's installer declares its fisherman source. `manifest` is
# a Flatpak manifest with a `fisherman` module; `submodule` is a .gitmodules
# entry (gnome builds fisherman from a `type: dir` source backed by one).
INSTALLERS = {
    "kde": {"repo": "tuna-os/tuna-installer-kde",
            "manifest": "flatpak/org.tunaos.InstallerKde.json"},
    "cosmic": {"repo": "tuna-os/tuna-installer-cosmic",
               "manifest": "flatpak/org.tunaos.InstallerCosmic.json"},
    "niri": {"repo": "tuna-os/tuna-installer-niri",
             "manifest": "flatpak/org.tunaos.InstallerNiri.json"},
    "xfce": {"repo": "tuna-os/tuna-installer-xfce",
             "manifest": "flatpak/org.tunaos.InstallerXfce.json"},
    "gnome": {"repo": "tuna-os/bootc-installer", "submodule": "fisherman"},
}


def normalize_repo(url: str) -> str:
    """github.com/OWNER/NAME(.git) -> OWNER/NAME. Anything else comes back as-is."""
    u = url.strip().removesuffix(".git")
    for prefix in ("https://github.com/", "git@github.com:", "http://github.com/"):
        if u.startswith(prefix):
            return u[len(prefix):]
    return u


def source_from_manifest(text: str) -> dict:
    """The fisherman module's git source, from a Flatpak manifest."""
    manifest = json.loads(text)
    for module in manifest.get("modules", []):
        if not isinstance(module, dict) or module.get("name") != "fisherman":
            continue
        for source in module.get("sources", []):
            if source.get("type") == "git":
                return source
        return {}
    return {}


def source_from_gitmodules(text: str, path: str) -> dict:
    """The named submodule's url/branch, from a .gitmodules file."""
    current, found = None, {}
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("[submodule"):
            current = None
        elif "=" in line:
            key, _, value = line.partition("=")
            key, value = key.strip(), value.strip()
            if key == "path":
                current = value
            elif current == path and key in ("url", "branch"):
                found[key] = value
    return found


def audit(sources: dict) -> list[str]:
    """Pure: {desktop: source_dict} -> list of problems. No network."""
    problems = []
    for desktop, source in sorted(sources.items()):
        url = source.get("url")
        if not url:
            problems.append(
                f"{desktop}: no fisherman git source found -- the manifest "
                f"shape changed, so this check is no longer looking at "
                f"anything. Fix the check, do not delete it."
            )
            continue
        repo = normalize_repo(url)
        if repo != CANONICAL:
            problems.append(
                f"{desktop}: builds fisherman from {repo}, not {CANONICAL}. "
                f"A source pointed at a repository that no longer moves goes "
                f"stale silently -- Renovate has nothing to bump and the "
                f"Flatpak keeps rebuilding, so nothing looks wrong."
            )
    return problems


def fetch(repo: str, path: str) -> str:
    url = f"https://api.github.com/repos/{repo}/contents/{path}"
    request = urllib.request.Request(
        url, headers={"Accept": "application/vnd.github.raw"}
    )
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read().decode()


def collect() -> dict:
    sources = {}
    for desktop, where in INSTALLERS.items():
        if "manifest" in where:
            sources[desktop] = source_from_manifest(
                fetch(where["repo"], where["manifest"])
            )
        else:
            sources[desktop] = source_from_gitmodules(
                fetch(where["repo"], ".gitmodules"), where["submodule"]
            )
    return sources


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--json", action="store_true", help="print the collected sources"
    )
    args = parser.parse_args()

    try:
        sources = collect()
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
        # Never turn a network blip into a red build; this guards against
        # drift over months, not against a flaky minute.
        print(f"::warning::could not read installer manifests: {exc}")
        return 0

    if args.json:
        print(json.dumps(sources, indent=2, sort_keys=True))

    for desktop, source in sorted(sources.items()):
        pin = source.get("commit") or source.get("branch") or "?"
        print(f"  {desktop:<8} {normalize_repo(source.get('url', '?'))} @ {pin}")

    # Divergence is a warning, not an error: pinning different revisions of
    # the LIVE repo is a visible choice, and kde running ahead of the others
    # is normal for a day or two. It is worth saying out loud because that is
    # exactly the shape the silent drift took -- kde moved, nobody else did.
    revisions = {
        d: s.get("commit") or s.get("branch")
        for d, s in sources.items()
        if s.get("url")
    }
    if len(set(revisions.values())) > 1:
        spread = ", ".join(f"{d}={(r or '?')[:8]}" for d, r in sorted(revisions.items()))
        print(f"::warning::installers disagree on the fisherman revision: {spread}")

    problems = audit(sources)
    for problem in problems:
        print(f"::error::{problem}")
    if problems:
        print(f"\n{len(problems)} installer(s) build fisherman from the wrong repo.")
        return 1
    print(f"\nall {len(sources)} installers build fisherman from {CANONICAL}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
