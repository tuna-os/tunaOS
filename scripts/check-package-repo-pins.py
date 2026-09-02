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

import datetime
import glob
import re
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


# ---------------------------------------------------------------------------
# Datestamped snapshot freshness.
#
# Resolving is the right property for an immutable snapshot of a STABLE
# release: it either still exists or it does not. It is the wrong property for
# a snapshot of a ROLLING distribution, which keeps answering 200 long after it
# has stopped being a usable base to layer against.
#
# hummingbird is exactly that case and is why this exists. Fedora Hummingbird
# is a rolling release tracking Fedora Rawhide (docs/HUMMINGBIRD.md) — not
# Fedora 43, whatever the .fc43 dist tags suggest. tunaOS pins two halves of it
# independently: the base image by digest in build-config.yml, and the package
# snapshot by datestamp in build_scripts/10-base-packages.sh. Both were
# coherent when taken. They drift with every upstream roll.
#
# The drift does not surface as a pin problem. It surfaces as UNRESOLVABLE
# DEPENDENCIES inside the layered desktop: on 2026-08-25 the 20251124 snapshot
# served gtk4 but not the harfbuzz gtk4 requires, so dnf reported gtk4 and 17
# others as BROKEN rather than missing, --skip-unavailable dropped them, and
# hummingbird:gnome shipped with 410 packages and no GNOME in it. Every pin in
# that build resolved. Nothing here was red.
#
# So age is checked as well as reachability. Exactly one pin in the manifests
# carries a datestamp today (measured), so this is precise rather than a broad
# heuristic looking for something to flag.
SNAPSHOT_RE = re.compile(r"/[^/]*?(20\d{6})[^/]*/")
SNAPSHOT_WARN_DAYS = 60
SNAPSHOT_FAIL_DAYS = 180


def snapshot_age_days(url: str, today: datetime.date | None = None) -> int | None:
    """Age in days of a YYYYMMDD datestamp in the URL path, else None.

    `today` is injectable so the tests do not drift into failing as the
    calendar moves — a check whose verdict depends on when it runs is a check
    nobody can reason about.
    """
    hit = SNAPSHOT_RE.search(url)
    if not hit:
        return None
    stamp = hit.group(1)
    try:
        taken = datetime.date(int(stamp[:4]), int(stamp[4:6]), int(stamp[6:8]))
    except ValueError:
        return None  # 20259999 and friends are not datestamps
    return ((today or datetime.date.today()) - taken).days


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


def probe(url: str) -> tuple[int, bytes]:
    """(status, body). The body rides along so content-age needs no re-fetch."""
    req = urllib.request.Request(url, headers=UA, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, b""
    except (urllib.error.URLError, OSError):
        return 0, b""


def repomd_content_age_days(body: bytes,
                            today: datetime.date | None = None) -> int | None:
    """Age of a repomd.xml's <revision>, when it is an epoch timestamp.

    This is what STALE should mean for a datestamped repo. The hummingbird
    prefix carries 20251124 in its NAME, but the package factory publishes
    into that same prefix nightly (r2_path: hummingbird/20251124-$arch), so it
    is a LIVING repository with a date in its label, not an immutable
    snapshot. Judging it by the label would cry STALE forever about a repo
    receiving packages daily -- and a check that cries wolf gets deleted,
    which is worse than no check. The repomd revision is written at index
    time; createrepo_c stamps it with the epoch, so its age is the age of the
    CONTENT. A revision that is not epoch-shaped (some tools write serials)
    yields None and the caller falls back to the name date, saying so.
    """
    import re as _re
    m = _re.search(rb"<revision>(\d{9,11})</revision>", body)
    if not m:
        return None
    ts = int(m.group(1))
    try:
        taken = datetime.datetime.utcfromtimestamp(ts).date()
    except (OverflowError, OSError, ValueError):
        return None
    return ((today or datetime.date.today()) - taken).days


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
    stale = 0
    for url in sorted(pins):
        kind = pins[url]
        if "$" in url:
            print(f"SKIP  {kind:5s} (unresolved repo variable)  {url}")
            skipped += 1
            continue
        code, body = probe(url)
        if code != 200:
            code, body = probe(url)  # one retry on transport failure
        if code == 200:
            age = snapshot_age_days(url)
            basis = "name"
            if age is not None:
                content_age = repomd_content_age_days(body)
                if content_age is not None:
                    age, basis = content_age, "content"
            if age is None:
                print(f"ok    {kind:5s} {code}  {url}")
            elif age >= SNAPSHOT_FAIL_DAYS:
                print(f"STALE {kind:5s} {code}  {url}  ({age}d old, by {basis})")
                print(f"::error::datestamped snapshot pin is {age} days old "
                      f"(limit {SNAPSHOT_FAIL_DAYS}): {url} — it still "
                      f"resolves, which is why nothing else catches this. "
                      f"Against a rolling upstream a snapshot this old no "
                      f"longer satisfies the dependencies of what is layered "
                      f"on top of it; the symptom is packages skipped for "
                      f"BROKEN dependencies mid-build, not a 404 here. "
                      f"See docs/HUMMINGBIRD.md")
                stale += 1
                failed += 1
            elif age >= SNAPSHOT_WARN_DAYS:
                print(f"ok    {kind:5s} {code}  {url}  ({age}d old, by {basis})")
                print(f"::warning::datestamped snapshot pin is {age} days old "
                      f"({url}) — refresh it before it drifts far enough from "
                      f"the base image to break dependency resolution")
                stale += 1
            else:
                print(f"ok    {kind:5s} {code}  {url}  ({age}d old, by {basis})")
        else:
            print(f"FAIL  {kind:5s} {code}  {url}")
            print(f"::error::package-repo pin no longer resolves "
                  f"(HTTP {code}): {url} — an image that references it "
                  f"cannot be rebuilt (rebuildable criterion, W7)")
            failed += 1

    print(f"\nchecked {len(pins) - skipped} package-repo pin(s), "
          f"{skipped} skipped; {failed} unresolvable or stale, "
          f"{stale} datestamped snapshot(s) past {SNAPSHOT_WARN_DAYS}d")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
