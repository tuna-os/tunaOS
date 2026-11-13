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
lives in another repository -- so this check reads it.

CONSOLIDATION NOTE
------------------
The five per-desktop installer repos (tuna-os/tuna-installer-{kde,cosmic,
niri,xfce} plus the gnome `.gitmodules` submodule in tuna-os/bootc-installer)
have since been consolidated: every frontend now ships from
tuna-os/bootc-installer, with one Flatpak manifest per desktop. Since
bootc-installer#351 (2026-11-11) the four `frontends/<desktop>/flatpak/`
manifests include `shared/flatpak/fisherman.json`, which builds fisherman
from a `type: dir` source backed by the `fisherman` submodule, as the gnome
manifest does. This check follows each manifest to its fisherman module,
including module files, and audits a `type: dir` source through the
matching `.gitmodules` entry and the committed gitlink.

It is deliberately about the repository AND a revision floor, not just the
repository. Pinning an older revision of the LIVE repo used to be described
here as a normal, visible choice; the MediaInput v1 incident showed the
limit of that view. FLOOR_COMMIT sets the minimum declared fisherman source
for all five production frontends. This source ancestry policy does not
prove the contents of a deployed Flatpak or qualify a live desktop.
"""

from __future__ import annotations

import argparse
import json
import os
import posixpath
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

# The repository fisherman actually lives in now.
CANONICAL = "tuna-os/fisherman"

# Audit the production installer sources, not the default development branch.
# Task 9 promotes dev to this branch before overlays may be rebuilt.
INSTALLER_REF = "prod"

# Minimum declared fisherman source for all five production frontends.
# Release v2026.10.31-23e47c51 declares this source revision. Raising this
# floor is an all-five source policy change, not just a GNOME bundle update.
# Compare full resolved SHAs; accept only this commit or its descendants.
# A declared source revision is not an embedded binary VCS identity.
FLOOR_COMMIT = "230f6ec856bf70f40faf76dc1c9e7327cf1a7a2f"

# The Flatpak manifest each desktop's installer builds from. All five frontends
# consolidated into tuna-os/bootc-installer. The fisherman module is inline (gnome)
# or in an included module file (shared/flatpak/fisherman.json); its source is
# a `git` URL or a `type: dir` path backed by a `.gitmodules` submodule.
INSTALLERS = {
    "kde": {"repo": "tuna-os/bootc-installer",
            "manifest": "frontends/kde/flatpak/org.tunaos.InstallerKde.json"},
    "cosmic": {"repo": "tuna-os/bootc-installer",
               "manifest": "frontends/cosmic/flatpak/org.tunaos.InstallerCosmic.json"},
    "niri": {"repo": "tuna-os/bootc-installer",
             "manifest": "frontends/niri/flatpak/org.tunaos.InstallerNiri.json"},
    "xfce": {"repo": "tuna-os/bootc-installer",
             "manifest": "frontends/xfce/flatpak/org.tunaos.InstallerXfce.json"},
    "gnome": {"repo": "tuna-os/bootc-installer",
              "manifest": "flatpak/org.bootcinstaller.Installer.json"},
}


def normalize_repo(url: str) -> str:
    """github.com/OWNER/NAME(.git) -> OWNER/NAME. Anything else comes back as-is."""
    u = url.strip().removesuffix(".git")
    for prefix in ("https://github.com/", "git@github.com:", "http://github.com/"):
        if u.startswith(prefix):
            return u[len(prefix):]
    return u


def repo_path(base: str, relative: str) -> str:
    """Resolve a manifest-relative path to a path in the same repository."""
    path = posixpath.normpath(posixpath.join(posixpath.dirname(base), relative))
    if relative.startswith("/") or path == ".." or path.startswith("../"):
        raise KeyError(f"{relative!r} in {base} points outside the repository")
    return path


def fisherman_source(manifest: str, read) -> dict:
    """The fisherman module's source, from a Flatpak manifest.

    `read(path)` returns the text of a repository file. A string module entry
    names a module file relative to the manifest. A `git` source comes back
    as declared; a `dir` source comes back as {"dir": <repository path>}.
    """
    for entry in json.loads(read(manifest)).get("modules", []):
        declared_in = manifest
        if isinstance(entry, str):
            declared_in = repo_path(manifest, entry)
            entry = json.loads(read(declared_in))
        if not isinstance(entry, dict) or entry.get("name") != "fisherman":
            continue
        for source in entry.get("sources", []):
            if not isinstance(source, dict):
                continue
            if source.get("type") == "git":
                return source
            if source.get("type") == "dir" and isinstance(source.get("path"), str):
                return {"dir": repo_path(declared_in, source["path"])}
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


def audit(sources: dict, floor: str = FLOOR_COMMIT) -> list[str]:
    """Pure: {desktop: source_dict} -> list of problems. No network."""
    problems = []
    for desktop, source in sorted(sources.items()):
        source_error = source.get("source_error")
        if source_error:
            problems.append(f"{desktop}: {source_error}")
            continue
        url = source.get("url")
        if not url:
            problems.append(
                f"{desktop}: no fisherman git or submodule source found -- the "
                f"manifest shape changed, so this check is no longer looking at "
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
            continue
        pin = source.get("resolved") or source.get("commit") or source.get("branch")
        if not pin:
            problems.append(
                f"{desktop}: canonical fisherman source has no revision pin. "
                f"Pin a commit or branch at or after {floor[:12]}."
            )
            continue
        # Full SHAs were resolved at fetch time (branches to their head SHA),
        # so this compares exact revisions against the production source floor.
        if source.get("at_or_after_floor") is False:
            problems.append(
                f"{desktop}: pins fisherman at {(pin or '?')[:12]}, older than "
                f"or unrelated to the production source floor {floor[:12]}. "
                f"Advance the pin to a revision at or after the floor."
            )
    return problems


def fetch(repo: str, path: str, ref: str = INSTALLER_REF) -> str:
    query = urllib.parse.urlencode({"ref": ref})
    url = f"https://api.github.com/repos/{repo}/contents/{path}?{query}"
    request = urllib.request.Request(
        url, headers={"Accept": "application/vnd.github.raw"}
    )
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read().decode()


def api_json(url: str) -> dict:
    request = urllib.request.Request(
        url, headers={"Accept": "application/vnd.github+json"}
    )
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(request, timeout=30) as response:
        try:
            value = json.loads(response.read().decode())
        except json.JSONDecodeError as exc:
            raise KeyError(f"{url} returned invalid JSON") from exc
    if not isinstance(value, dict):
        raise KeyError(f"{url} returned non-object JSON")
    return value


def resolve_sha(repo: str, ref: str) -> str:
    """A branch (or short SHA) in repo -> its full 40-character HEAD SHA."""
    sha = api_json(f"https://api.github.com/repos/{repo}/commits/{ref}").get("sha")
    if not isinstance(sha, str) or re.fullmatch(r"[0-9a-f]{40}", sha) is None:
        raise KeyError(f"{repo}@{ref} did not resolve to a full commit SHA")
    return sha


def submodule_sha(repo: str, path: str, ref: str = INSTALLER_REF) -> str:
    """Return the exact gitlink committed by the installer production ref."""
    query = urllib.parse.urlencode({"ref": ref})
    value = api_json(
        f"https://api.github.com/repos/{repo}/contents/{path}?{query}"
    )
    if not isinstance(value, dict):
        raise KeyError(f"{repo}:{path}@{ref} returned non-object JSON")
    sha = value.get("sha")
    if not isinstance(sha, str) or re.fullmatch(r"[0-9a-f]{40}", sha) is None:
        raise KeyError(f"{repo}:{path}@{ref} has no valid committed submodule SHA")
    return sha


def floor_is_ancestor(repo: str, sha: str, floor: str = FLOOR_COMMIT) -> bool | None:
    """Is `floor` an ancestor of (or identical to) `sha`? None if unknowable."""
    try:
        status = api_json(
            f"https://api.github.com/repos/{repo}/compare/{floor}...{sha}"
        )["status"]
    except urllib.error.HTTPError as exc:
        # A missing commit is deterministic source drift, not a network blip.
        return False if exc.code == 404 else None
    except (urllib.error.URLError, TimeoutError, KeyError):
        return None
    # "ahead": sha descends from the floor; "identical": pinned exactly on it.
    # "behind"/"diverged": the pin predates the floor (or left its line).
    return status in ("ahead", "identical")


def submodule_source(repo: str, path: str, read, gitlink) -> dict:
    """The url and committed gitlink of the submodule a `type: dir` source uses."""
    found = source_from_gitmodules(read(".gitmodules"), path)
    if not found.get("url"):
        raise KeyError(
            f"fisherman builds from {path}, which is not a submodule in "
            f"{repo}@{INSTALLER_REF}:.gitmodules"
        )
    # A tracking branch is not the source used by the build. Git checks
    # out the production ref's committed gitlink, so audit that SHA.
    source = {"url": found["url"]}
    try:
        source["commit"] = gitlink(path)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            source["source_error"] = (
                f"production gitlink {path} is missing at {repo}@{INSTALLER_REF}"
            )
        else:
            source["at_or_after_floor"] = None
    except (urllib.error.URLError, TimeoutError):
        source["at_or_after_floor"] = None
    return source


def collect() -> dict:
    sources = {}
    files: dict[tuple[str, str], str] = {}
    gitlinks: dict[tuple[str, str], str] = {}
    for desktop, where in INSTALLERS.items():
        repo = where["repo"]

        # All five manifests include the same module file and submodule, so
        # read each production file and gitlink once.
        def read(path: str, repo: str = repo) -> str:
            if (repo, path) not in files:
                try:
                    files[repo, path] = fetch(repo, path, INSTALLER_REF)
                except urllib.error.HTTPError as exc:
                    if exc.code != 404:
                        raise
                    raise KeyError(
                        f"production file {path} is missing at {repo}@{INSTALLER_REF}"
                    ) from exc
            return files[repo, path]

        def gitlink(path: str, repo: str = repo) -> str:
            if (repo, path) not in gitlinks:
                gitlinks[repo, path] = submodule_sha(repo, path, INSTALLER_REF)
            return gitlinks[repo, path]

        try:
            source = fisherman_source(where["manifest"], read)
            if "dir" in source:
                source = submodule_source(repo, source["dir"], read, gitlink)
        except KeyError as exc:
            source = {"source_error": exc.args[0]}
        sources[desktop] = source
    # Resolve every canonical-repo pin to a full SHA (branches to their head)
    # so the floor check compares exact revisions, then record whether the
    # MediaInput v1 floor is an ancestor of each pin. A resolution the API
    # cannot answer stays None and only warns -- same policy as a fetch blip.
    for desktop, source in sources.items():
        url = source.get("url")
        if not url or normalize_repo(url) != CANONICAL:
            continue
        ref = source.get("commit") or source.get("branch")
        if not ref:
            continue
        try:
            sha = ref if re.fullmatch(r"[0-9a-f]{40}", ref) else resolve_sha(CANONICAL, ref)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                source["source_error"] = (
                    f"fisherman revision {ref!r} does not exist in {CANONICAL}"
                )
            else:
                source["at_or_after_floor"] = None
            continue
        except KeyError as exc:
            source["source_error"] = str(exc)
            continue
        except (urllib.error.URLError, TimeoutError):
            source["at_or_after_floor"] = None
            continue
        source["resolved"] = sha
        source["at_or_after_floor"] = floor_is_ancestor(CANONICAL, sha)
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
        pin = source.get("resolved") or source.get("commit") or source.get("branch") or "?"
        print(f"  {desktop:<8} {normalize_repo(source.get('url', '?'))} @ {pin}")

    # Divergence is a warning, not an error: pinning different revisions of
    # the LIVE repo is a visible choice, and kde running ahead of the others
    # is normal for a day or two. It is worth saying out loud because that is
    # exactly the shape the silent drift took -- kde moved, nobody else did.
    # (Below the floor is different: that is an error, raised by audit().)
    revisions = {
        d: s.get("resolved") or s.get("commit") or s.get("branch")
        for d, s in sources.items()
        if s.get("url")
    }
    if len(set(revisions.values())) > 1:
        spread = ", ".join(f"{d}={(r or '?')[:8]}" for d, r in sorted(revisions.items()))
        print(f"::warning::installers disagree on the fisherman revision: {spread}")

    # A floor the API could not resolve stays None: warn, do not fail --
    # same policy as a fetch blip above.
    unknown = sorted(
        d for d, s in sources.items()
        if s.get("url") and normalize_repo(s["url"]) == CANONICAL
        and s.get("at_or_after_floor") is None
    )
    if unknown:
        print(f"::warning::could not resolve the floor ancestry for: {', '.join(unknown)}")

    problems = audit(sources)
    for problem in problems:
        print(f"::error::{problem}")
    if problems:
        print(f"\n{len(problems)} installer(s) failed the fisherman source check.")
        return 1
    print(f"\nall {len(sources)} installers build fisherman from {CANONICAL} "
          f"at or after the floor {FLOOR_COMMIT[:12]}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
