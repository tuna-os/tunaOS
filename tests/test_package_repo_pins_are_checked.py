"""W7, second box: the package-repo pins are checked, not remembered.

check-base-image-pins.sh proved the pattern on base digests (#1788: three
variants died overnight with nothing in the repo changing). The manifests
carry the same class of pin on the package side — repo.tunaos.org snapshot
datestamps, personal COPRs (#391), PPAs, the tideforge APT repo — and until
this landed, nothing asserted any of them between one nightly and the next.
"""
from __future__ import annotations

import importlib.util
import pathlib

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check-package-repo-pins.py"
WORKFLOW = ROOT / ".github" / "workflows" / "check-base-image-pins.yml"

spec = importlib.util.spec_from_file_location("crpp", SCRIPT)
crpp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(crpp)


def test_every_declaration_shape_is_extracted() -> None:
    """One synthetic manifest carrying every shape the real manifests use."""
    doc = {
        "fedora": {"repos": [{"name": "snap",
                              "baseurl": "https://repo.example/x/20251124-x86_64/"}]},
        "el10": {"copr": [{"repo": "owner/proj",
                           "extra_repos": ["owner/extra"]}]},
        "apt": {"repos": [{"uri": "https://repo.example/deb/", "suite": "./",
                           "keyring_url": "https://repo.example/deb/key.gpg"}],
                "ppa": [{"repo": "ppa:someone/stuff"}]},
        "deb": {"repos": [{"uri": "https://repo.example/deb2", "suite": "noble"}]},
    }
    urls = {url for _, url in crpp.collect(doc)}
    assert urls == {
        "https://repo.example/x/20251124-x86_64/repodata/repomd.xml",
        "https://copr.fedorainfracloud.org/api_3/project"
        "?ownername=owner&projectname=proj",
        "https://copr.fedorainfracloud.org/api_3/project"
        "?ownername=owner&projectname=extra",
        "https://repo.example/deb/Packages",
        "https://repo.example/deb/key.gpg",
        "https://api.launchpad.net/1.0/~someone/+archive/ubuntu/stuff",
        "https://repo.example/deb2/dists/noble/InRelease",
    }


def test_the_real_manifests_yield_the_known_pin_classes() -> None:
    """Extraction against the actual manifests finds every pin class we know
    is declared today. If a manifest refactor changes a shape, this fails
    before the nightly check silently starts checking nothing."""
    pins: list[tuple[str, str]] = []
    for path in sorted((ROOT / "manifests" / "desktops").glob("*.yaml")):
        pins.extend(crpp.collect(yaml.safe_load(path.read_text())))
    kinds = {k for k, _ in pins}
    assert {"dnf", "copr", "ppa", "apt", "key"} <= kinds, (
        f"missing pin classes: extraction found only {sorted(kinds)}"
    )
    urls = [u for _, u in pins]
    # The two named motivators: the hummingbird snapshot datestamp and the
    # #391 COPR single point of failure.
    assert any("hummingbird/20251124" in u for u in urls)
    assert any("projectname=c10s-gnome-50" in u for u in urls)


def test_basearch_is_substituted_and_leftovers_skip_not_guess() -> None:
    doc = {"repos": [{"baseurl": "https://r.example/$basearch/"},
                     {"baseurl": "https://r.example/$releasever/"}]}
    urls = {url for _, url in crpp.collect(doc)}
    assert "https://r.example/x86_64/repodata/repomd.xml" in urls
    # $releasever is not statically resolvable; it must survive to the SKIP
    # path rather than being silently dropped or mangled.
    assert any("$releasever" in u for u in urls)


def test_zero_extracted_pins_is_a_failure_not_a_pass() -> None:
    body = SCRIPT.read_text()
    assert "found zero declared repos" in body, (
        "an extraction that finds nothing must fail loudly — the "
        "absence-of-evidence rule (#1730) applies to the checker itself"
    )


def test_the_nightly_workflow_runs_it() -> None:
    body = WORKFLOW.read_text()
    assert "check-package-repo-pins.py" in body
    doc = yaml.safe_load(WORKFLOW.read_text())
    jobs = doc["jobs"]
    assert "package-repos" in jobs, (
        "package-repo pins get their own job so a base-pin failure cannot "
        "stop them from reporting (and vice versa)"
    )


# ── file:// repos are OCI pins in disguise ─────────────────────────────────
#
# hummingbird:gnome takes GNOME 51 from projectbluefin/utah-packages: an OCI
# image carrying a createrepo_c repository, pinned by digest in
# image-versions.yaml and bind-mounted at /run/utah-packages by
# Containerfile.el10. The manifest declares it as `baseurl:
# file:///run/utah-packages`. Probing that as an HTTP URL answers 0 and the
# nightly went red on it from the day the pin landed (run 33699188451,
# 2026-09-03: "FAIL dnf 0 file:///run/utah-packages/repodata/repomd.xml").
# The pin behind it is what can rot, so that is what gets probed.


def test_a_file_repo_resolves_to_the_oci_pin_that_provides_it():
    doc = {"hummingbird": {"repos": [{"name": "utah-packages",
                                      "baseurl": "file:///run/utah-packages",
                                      "priority": 4}]}}
    pins = {"utah-packages": "ghcr.io/projectbluefin/utah-packages@sha256:" + "a" * 64}
    assert crpp.collect(doc, pins) == [
        ("oci", "ghcr.io/projectbluefin/utah-packages@sha256:" + "a" * 64)
    ]


def test_a_file_repo_with_no_pin_behind_it_is_a_failure_not_a_skip():
    """Nothing provides the bytes the manifest mounts: that is a repo that
    cannot be rebuilt, and it must be named, not skipped."""
    doc = {"repos": [{"baseurl": "file:///run/nothing-pins-this"}]}
    assert crpp.collect(doc, {}) == [("oci-unpinned", "file:///run/nothing-pins-this")]
    assert crpp.collect(doc, None) == [("oci-unpinned", "file:///run/nothing-pins-this")]


def test_the_real_manifests_route_the_utah_repo_through_image_versions():
    pins = crpp.oci_pins(str(ROOT / "image-versions.yaml"))
    assert "utah-packages" in pins, "image-versions.yaml no longer pins utah-packages"
    assert pins["utah-packages"].startswith("ghcr.io/projectbluefin/utah-packages@sha256:")
    collected: list[tuple[str, str]] = []
    for path in sorted((ROOT / "manifests" / "desktops").glob("*.yaml")):
        collected.extend(crpp.collect(yaml.safe_load(path.read_text()), pins))
    kinds = {k for k, _ in collected}
    assert "oci-unpinned" not in kinds, [u for k, u in collected if k == "oci-unpinned"]
    assert ("oci", pins["utah-packages"]) in collected
    assert not any(u.startswith("file://") for _, u in collected), (
        "a file:// URL survived to the probe list; it can never resolve over HTTP"
    )


def test_the_oci_probe_asks_the_registry_for_the_digest_with_a_token():
    """Same quirks as check-base-image-pins.sh: ghcr/quay/docker.io hand out
    anonymous pull tokens from different places, docker.io is not an API
    host, and the manifest must be requested by digest, not by tag."""
    ref = "ghcr.io/projectbluefin/utah-packages@sha256:" + "b" * 64
    url, token = crpp.oci_manifest_request(ref)
    assert url == "https://ghcr.io/v2/projectbluefin/utah-packages/manifests/sha256:" + "b" * 64
    assert token == "https://ghcr.io/token?scope=repository:projectbluefin/utah-packages:pull"

    url, token = crpp.oci_manifest_request("docker.io/library/debian:trixie@sha256:" + "c" * 64)
    assert url.startswith("https://registry-1.docker.io/v2/library/debian/manifests/sha256:")
    assert "auth.docker.io" in token

    url, token = crpp.oci_manifest_request("quay.io/fedora/fedora-bootc:44@sha256:" + "d" * 64)
    assert url == "https://quay.io/v2/fedora/fedora-bootc/manifests/sha256:" + "d" * 64
    assert token == "https://quay.io/v2/auth?service=quay.io&scope=repository:fedora/fedora-bootc:pull"

    url, token = crpp.oci_manifest_request("registry.opensuse.org/opensuse/tumbleweed@sha256:" + "e" * 64)
    assert url == "https://registry.opensuse.org/v2/opensuse/tumbleweed/manifests/sha256:" + "e" * 64
    assert token is None
