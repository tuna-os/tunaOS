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
import json
import re
import sys
import urllib.error
import urllib.request

import yaml

MANIFEST_GLOB = "manifests/desktops/*.yaml"
IMAGE_VERSIONS = "image-versions.yaml"
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


def oci_pins(path: str = IMAGE_VERSIONS) -> dict[str, str]:
    """name -> image@digest for every digest-pinned entry in image-versions.yaml."""
    try:
        with open(path, encoding="utf-8") as f:
            doc = yaml.safe_load(f) or {}
    except FileNotFoundError:
        return {}
    out: dict[str, str] = {}
    for entry in doc.get("images") or []:
        if not isinstance(entry, dict):
            continue
        name, image, digest = entry.get("name"), entry.get("image"), entry.get("digest")
        if isinstance(name, str) and isinstance(image, str) and isinstance(digest, str):
            out[name] = f"{image}@{digest}"
    return out


FILE_REPO_RE = re.compile(r"^file:///run/([^/]+)/?$")


def collect(doc, pins_by_name: dict[str, str] | None = None) -> list[tuple[str, str]]:
    """Walk a parsed manifest and return (kind, probe_url) pairs.

    Shapes handled — one per declaration style that exists in the manifests:
      dnf:   {..., "baseurl": URL}            -> URL/repodata/repomd.xml
      oci:   {..., "baseurl": "file:///run/NAME"}
                                              -> the image@digest that
                                                 image-versions.yaml pins
                                                 under NAME (Containerfile.el10
                                                 bind-mounts its /repository
                                                 at /run/NAME). Probed as a
                                                 registry manifest, since a
                                                 file:// URL is only ever
                                                 reachable inside the build.
                                                 A file:// baseurl with no pin
                                                 behind it is reported as
                                                 `oci-unpinned` and FAILS: it
                                                 names a repo nothing provides.
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
                baseurl = node["baseurl"]
                file_hit = FILE_REPO_RE.match(baseurl)
                if file_hit:
                    ref = (pins_by_name or {}).get(file_hit.group(1))
                    if ref:
                        pins.append(("oci", ref))
                    else:
                        pins.append(("oci-unpinned", baseurl))
                elif baseurl.startswith("file://"):
                    pins.append(("oci-unpinned", baseurl))
                else:
                    pins.append(("dnf", _sub_vars(baseurl).rstrip("/")
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


# Registry quirks mirror scripts/check-base-image-pins.sh: docker.io is a
# name whose API host is registry-1.docker.io; quay/ghcr/docker hand out
# anonymous pull tokens from different endpoints; anything else is tried
# unauthenticated.
OCI_ACCEPT = ",".join((
    "application/vnd.oci.image.index.v1+json",
    "application/vnd.docker.distribution.manifest.list.v2+json",
    "application/vnd.docker.distribution.manifest.v2+json",
    "application/vnd.oci.image.manifest.v1+json",
))


def oci_manifest_request(ref: str) -> tuple[str, str | None]:
    """(manifest_url, token_url_or_None) for an image@digest reference."""
    name, _, digest = ref.partition("@")
    name = name.split(":", 1)[0] if "/" not in name.split(":", 1)[-1] else name
    registry, _, repo = name.partition("/")
    host = "registry-1.docker.io" if registry == "docker.io" else registry
    token = {
        "docker.io": f"https://auth.docker.io/token?service=registry.docker.io&scope=repository:{repo}:pull",
        "quay.io": f"https://quay.io/v2/auth?service=quay.io&scope=repository:{repo}:pull",
        "ghcr.io": f"https://ghcr.io/token?scope=repository:{repo}:pull",
    }.get(registry)
    return f"https://{host}/v2/{repo}/manifests/{digest}", token


def probe_oci(ref: str) -> tuple[int, bytes]:
    """HTTP status of the registry manifest behind image@digest."""
    manifest_url, token_url = oci_manifest_request(ref)
    headers = {**UA, "Accept": OCI_ACCEPT}
    if token_url:
        try:
            with urllib.request.urlopen(
                    urllib.request.Request(token_url, headers=UA),
                    timeout=TIMEOUT) as resp:
                token = json.loads(resp.read().decode()).get("token", "")
            if token:
                headers["Authorization"] = f"Bearer {token}"
        except (urllib.error.URLError, OSError, ValueError):
            pass  # an unauthenticated probe still answers 401/404 honestly
    req = urllib.request.Request(manifest_url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, b""
    except (urllib.error.URLError, OSError):
        return 0, b""


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
        taken = datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).date()
    except (OverflowError, OSError, ValueError):
        return None
    return ((today or datetime.date.today()) - taken).days


def main() -> int:
    pins: dict[str, str] = {}
    by_name = oci_pins()
    for path in sorted(glob.glob(MANIFEST_GLOB)):
        with open(path, encoding="utf-8") as f:
            doc = yaml.safe_load(f)
        for kind, url in collect(doc, by_name):
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
        if kind == "oci-unpinned":
            # A file:// repo is a bind mount of something; if image-versions.yaml
            # pins nothing under that name, the build has no bytes to mount and
            # dnf will read an empty directory. Loud, not skipped.
            print(f"FAIL  {kind:5s} ---  {url}")
            print(f"::error::file:// package repo has no digest pin behind it "
                  f"in {IMAGE_VERSIONS}: {url} — nothing provides the "
                  f"repository the manifest mounts (rebuildable criterion, W7)")
            failed += 1
            continue
        if "$" in url:
            print(f"SKIP  {kind:5s} (unresolved repo variable)  {url}")
            skipped += 1
            continue
        if kind == "oci":
            code, body = probe_oci(url)
            if code != 200:
                code, body = probe_oci(url)
        else:
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
            what = ("OCI package-repo pin (the digest behind a file:// "
                    "baseurl) no longer resolves" if kind == "oci"
                    else "package-repo pin no longer resolves")
            print(f"::error::{what} (HTTP {code}): {url} — an image that "
                  f"references it cannot be rebuilt (rebuildable criterion, W7)")
            failed += 1

    print(f"\nchecked {len(pins) - skipped} package-repo pin(s), "
          f"{skipped} skipped; {failed} unresolvable or stale, "
          f"{stale} datestamped snapshot(s) past {SNAPSHOT_WARN_DAYS}d")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
