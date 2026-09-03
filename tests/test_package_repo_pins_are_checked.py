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
    # The named motivators: the hummingbird snapshot datestamp, and the EL10
    # GNOME 50 tier that replaced the #391 COPR single point of failure
    # (2026-09-03: no more COPR for a desktop stack).
    assert any("hummingbird/20251124" in u for u in urls)
    assert any("repo.tunaos.org/gnome50/10-stream-x86_64" in u for u in urls)
    assert not any("projectname=c10s-gnome-5" in u for u in urls), (
        "a jreilly1821/c10s-gnome-5x COPR is back in a manifest; GNOME on EL10 comes from the factory tier"
    )


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
