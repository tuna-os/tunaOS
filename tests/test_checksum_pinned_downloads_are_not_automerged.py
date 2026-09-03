"""A download pinned twice (version + sha256) must not be automerged by Renovate.

Renovate maintains the version half of such a pin and cannot maintain the
checksum half, so its bump alone fails every base build closed at
`sha256sum --check`. `check-download-checksums.yml` names the stale pair on
the PR, but the main ruleset requires no status checks
(docs/BRANCH-PROTECTION.md), so platformAutomerge merges through a red
check. Measured twice in two days:

- #2293 (remora v0.4.0 -> v0.4.1) merged 2026-09-02 21:58Z with v0.4.0's
  hashes; #2305 repinned them.
- #2308 (v0.4.1 -> v0.4.2) merged 2026-09-03 01:11Z with the `checksums`
  check FAILED on the PR, and flounder's base build died at
  install-remora.sh an hour later (run 33694724467, job 100479165741:
  "sha256sum: WARNING: 1 computed checksum did NOT match").

The only lever inside this repository is renovate.json: every dependency
whose version is paired with a hand-pinned checksum must end up with
`automerge: false` after Renovate's last-rule-wins evaluation. The list of
such dependencies is DERIVED from the files that carry the pairs, so adding
a new checksummed download without excluding it fails here first.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
RENOVATE = ROOT / "renovate.json"
IMAGE_VERSIONS = ROOT / "image-versions.yaml"
REMORA = ROOT / "build_scripts/install-remora.sh"

RENOVATE_MARKER = re.compile(r"#\s*renovate:\s*datasource=\S+\s+depName=(\S+)")


def checksum_paired_dep_names() -> set[str]:
    """Every depName whose version sits next to a sha256 map or literal."""
    names: set[str] = set()

    # image-versions.yaml: a `<key>_sha256:` map next to `<key>: "vX"` whose
    # preceding comment carries the renovate marker.
    text = IMAGE_VERSIONS.read_text()
    downloads = yaml.safe_load(text).get("downloads") or {}
    for key in downloads:
        if key.endswith("_sha256") and key[: -len("_sha256")] in downloads:
            base = key[: -len("_sha256")]
            m = re.search(rf"{RENOVATE_MARKER.pattern}\n\s*{re.escape(base)}:", text)
            assert m, f"{base} has a sha256 map but no renovate marker to name it"
            names.add(m.group(1))

    # install-remora.sh: a renovate marker over REMORA_VERSION and a
    # REMORA_SHA256 case table below it.
    remora = REMORA.read_text()
    if "REMORA_SHA256=" in remora:
        m = RENOVATE_MARKER.search(remora)
        assert m, "install-remora.sh pins a sha256 but carries no renovate marker"
        names.add(m.group(1))

    return names


def effective_automerge(dep_name: str) -> bool | None:
    """Renovate semantics: later packageRules override earlier ones."""
    cfg = json.loads(RENOVATE.read_text())
    result = cfg.get("automerge")
    for rule in cfg.get("packageRules", []):
        matched = False
        if dep_name in (rule.get("matchDepNames") or []):
            matched = True
        if dep_name in (rule.get("matchPackageNames") or []):
            matched = True
        # Rules keyed only on update type apply to every dependency.
        if "matchUpdateTypes" in rule and not any(
            k.startswith("match") and k != "matchUpdateTypes" for k in rule
        ):
            matched = True
        if matched and "automerge" in rule:
            result = rule["automerge"]
    return result


def test_the_derived_list_names_the_known_pairs():
    names = checksum_paired_dep_names()
    assert "tuna-os/remora" in names
    assert "twpayne/chezmoi" in names


def test_every_checksum_paired_download_ends_up_not_automerged():
    for dep in sorted(checksum_paired_dep_names()):
        assert effective_automerge(dep) is False, (
            f"{dep} is version+sha256 pinned but Renovate would automerge its "
            "bump; add it to the `automerge: false` rule in renovate.json "
            "(#2308 shipped a red `checksums` check into main this way)"
        )


def test_the_exclusion_comes_after_the_patch_automerge_rule():
    """Renovate applies packageRules in order and the last match wins. An
    exclusion placed BEFORE the blanket patch/pin/digest automerge rule is
    overridden by it and protects nothing."""
    rules = json.loads(RENOVATE.read_text())["packageRules"]
    blanket = [i for i, r in enumerate(rules) if r.get("automerge") is True
               and "matchUpdateTypes" in r]
    holds = [i for i, r in enumerate(rules) if r.get("automerge") is False
             and "tuna-os/remora" in (r.get("matchDepNames") or [])]
    assert blanket and holds, "expected both the blanket automerge rule and the remora hold"
    assert max(blanket) < min(holds), (
        "the checksum-pinned hold must come AFTER the blanket patch automerge "
        "rule, or the blanket rule overrides it"
    )


def test_the_pr_check_does_not_claim_to_block_the_merge():
    """The workflow's header used to say a stale bump 'cannot merge itself'.
    It demonstrably can (#2308). The comment must not make that claim again
    until a required-status-check rule exists on main."""
    body = (ROOT / ".github/workflows/check-download-checksums.yml").read_text()
    assert "cannot merge itself" not in body, (
        "check-download-checksums.yml claims to block merges; the main "
        "ruleset has no required checks, so it does not (#2308)"
    )
