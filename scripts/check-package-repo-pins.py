#!/usr/bin/env python3
"""Verify every package-repo pin declared in the desktop manifests resolves.

W7 of docs/GREEN-MASTER-PLAN.md, second box of the `rebuildable` criterion.
check-base-image-pins.sh covers the base image digests; this covers the other
half of "can this image still be built tomorrow": the package repositories the
manifests point at.

These pins break in ways a build log reads as something else entirely:

- repo.tunaos.org snapshot URLs are immutable datestamps (the hummingbird
  manifest pins 20251124 — a snapshot nobody will think about until the day
  the bucket is cleaned).
- COPR projects are personal infrastructure. jreilly1821/c10s-gnome-50 is a
  declared single point of failure (#391); yalter/niri-git and the
  avengemedia repos are other people's. A deleted COPR 404s at dnf time,
  mid-build, per flavor.
- PPAs and the tideforge APT repo fail the same way for the apt family.

Like the base-image check, this runs nightly BEFORE the variant builds, so an
expired pin is one named line here rather than N broken cells there.

Exit non-zero if any pin fails to resolve. SKIP (not FAIL) for URLs whose
repo variables cannot be resolved statically — a skip is printed so it cannot
silently become a hole.
"""

from __future__ import annotations

import glob
import sys
import urllib.error
import urllib.request

import yaml

MANIFEST_GLOB = "manifests/desktops/*.yaml"
TIMEOUT = 25
UA = {"User-Agent": "tunaos-repo-pin-check (+https://github.com/tuna-os/tunaOS)"}

# dnf repo variables we can resolve statically. Anything left unresolved after
# this substitution is reported as SKIP rather than guessed at.
VARS = {"$basearch": "x86_64"}


def _sub_vars(url: str) -> str:
    for var, val in VARS.items():
        url = url.replace(var, val)
    return url


def collect(doc) -> list[tuple[str, str]]:
    """Walk a parsed manifest and return (kind, probe_url) pairs.

    Shapes handled — one per declaration style that exists in the manifests:
      dnf:   {..., "baseurl": URL}            -> URL/repodata/repomd.xml
      apt:   {..., "uri": URL, "suite": S}    -> flat (S == "./") URL/Packages
                                                 else URL/dists/S/InRelease
             {..., "keyring_url": URL}        -> URL itself
      copr:  {"copr": [{"repo": "o/n", "extra_repos": ["o/n", ...]}]}
                                              -> COPR api_3 project endpoint
      ppa:   {"ppa": [{"repo": "ppa:o/n"}]}   -> Launchpad API archive endpoint
    """
    pins: list[tuple[str, str]] = []

    def copr_probe(spec: str) -> tuple[str, str]:
        owner, _, name = spec.partition("/")
        return ("copr", "https://copr.fedorainfracloud.org/api_3/project"
                        f"?ownername={owner}&projectname={name}")

    def walk(node):
        if isinstance(node, dict):
            if isinstance(node.get("baseurl"), str):
                pins.append(("dnf", _sub_vars(node["baseurl"]).rstrip("/")
                             + "/repodata/repomd.xml"))
            if isinstance(node.get("uri"), str) and "suite" in node:
                uri = node["uri"].rstrip("/")
                suite = str(node.get("suite", "./"))
                if suite in ("./", "."):
                    pins.append(("apt", f"{uri}/Packages"))
                else:
                    pins.append(("apt", f"{uri}/dists/{suite}/InRelease"))
            if isinstance(node.get("keyring_url"), str):
                pins.append(("key", node["keyring_url"]))
            for entry in node.get("copr") or []:
                if isinstance(entry, dict) and isinstance(entry.get("repo"), str):
                    pins.append(copr_probe(entry["repo"]))
                    for extra in entry.get("extra_repos") or []:
                        pins.append(copr_probe(extra))
            for entry in node.get("ppa") or []:
                if isinstance(entry, dict) and isinstance(entry.get("repo"), str):
                    spec = entry["repo"].removeprefix("ppa:")
                    owner, _, name = spec.partition("/")
                    pins.append(("ppa", "https://api.launchpad.net/1.0/"
                                        f"~{owner}/+archive/ubuntu/{name}"))
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(doc)
    return pins


def probe(url: str) -> int:
    req = urllib.request.Request(url, headers=UA, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return resp.status
    except urllib.error.HTTPError as e:
        return e.code
    except (urllib.error.URLError, OSError):
        return 0


def main() -> int:
    pins: dict[str, str] = {}
    for path in sorted(glob.glob(MANIFEST_GLOB)):
        with open(path, encoding="utf-8") as f:
            doc = yaml.safe_load(f)
        for kind, url in collect(doc):
            pins.setdefault(url, kind)

    if not pins:
        # Zero pins means the extraction broke, not that the manifests are
        # clean — the same absence-of-evidence rule as everywhere else.
        print("::error::package-repo pin check found zero declared repos — "
              "extraction is broken, not the manifests clean")
        return 1

    failed = 0
    skipped = 0
    for url in sorted(pins):
        kind = pins[url]
        if "$" in url:
            print(f"SKIP  {kind:5s} (unresolved repo variable)  {url}")
            skipped += 1
            continue
        code = probe(url) or probe(url)  # one retry on transport failure
        if code == 200:
            print(f"ok    {kind:5s} {code}  {url}")
        else:
            print(f"FAIL  {kind:5s} {code}  {url}")
            print(f"::error::package-repo pin no longer resolves "
                  f"(HTTP {code}): {url} — an image that references it "
                  f"cannot be rebuilt (rebuildable criterion, W7)")
            failed += 1

    print(f"\nchecked {len(pins) - skipped} package-repo pin(s), "
          f"{skipped} skipped; {failed} unresolvable")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
