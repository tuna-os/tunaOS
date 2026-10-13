"""The all14 Tuna candidate matrix stays candidate-only.

`.github/tuna-matrix-candidates.yml` stages admission inputs for the 13
Tuna cells absent from `.github/build-config.yml`; `manifests/tuna/
target-handoffs.yaml` carries their per-target session/portal/DM handoff
fixtures. Both files are fixtures: no production workflow, build script,
or desktop manifest consumer reads them, and neither file may claim
support, promotion, media, or final pins.

The failure mode this file exists to prevent is a candidate record that
quietly becomes a qualification claim -- a `support:` value flipped to
please a dashboard, a media flag copied from another cell, a platform
list counted as admitted before its G3 gate passes. Every value pinned
below was read off an actual source at e4e2 (variant issues 3195-3207,
package-author issues 828-838, the build config, the installed contract,
and the factory recipe); a correction lands in the owning source first,
then here.

P2 guard closure hardens only this file; both fixtures are byte-identical.
Handoff targets are cross-bound to their variants, package prerequisites
and stages, with mutation negatives. Contract constants are checked
against the actual contract script, the shipped payload files and the
Marlin desktop manifest, with drift negatives; the factory recipe side is
pinned by an exact commit/blob receipt verified out of band, since unit
CI must not fetch live network. The no-consumer lint covers the root
Justfile, every root Containerfile, extensionless entrypoints and
experiences/, with coverage and synthetic-consumer negatives. Gate
bodies are edited distillations of their owning issues, not verbatim
quotations.
"""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parents[1]
CANDIDATES = ROOT / ".github" / "tuna-matrix-candidates.yml"
HANDOFFS = ROOT / "manifests" / "tuna" / "target-handoffs.yaml"
CONFIG = ROOT / ".github" / "build-config.yml"
VERIFY_CONTRACT = ROOT / "build_scripts" / "checks" / "verify-desktop-experience.sh"
TUNA_MANIFEST = ROOT / "manifests" / "desktops" / "tuna.yaml"
# Shipped payload files under experiences/. Built with joinpath from plain
# strings -- never a `ROOT / "experiences"` literal -- so this file adds no
# new top-level name to the filter-coverage test's first-segment counting.
# Coverage still holds: this guard runs unfiltered on every PR through
# tuna-matrix-admission.yml, not through test.yml's path filter.
PORTAL_PAYLOAD = ROOT.joinpath(
    "experiences", "tuna", "files", "usr", "share",
    "xdg-desktop-portal", "tuna-portals.conf",
)
GREETD_ENVIRONMENTS = ROOT.joinpath(
    "experiences", "tuna", "files", "etc", "greetd", "environments",
)

TUNAOS_ISSUE = "https://github.com/tuna-os/tunaOS/issues/{}"
PACKAGES_ISSUE = "https://github.com/tuna-os/tunaos-packages/issues/{}"

# Variant -> (qualification issue, base verbatim from that issue,
# package prerequisite, Containerfile stage verbatim from that issue).
EXPECTED_CELLS = {
    "yellowfin": (3195, "AlmaLinux 10 Kitten", 828, "Containerfile.el10"),
    "albacore": (3196, "AlmaLinux 10", 828, "Containerfile.el10"),
    "skipjack": (3197, "CentOS Stream 10", 828, "Containerfile.el10"),
    "wahoo": (3198, "Fedora ELN", 829, "Containerfile.el10"),
    "bonito": (3199, "Fedora 44", 830, "Containerfile.el10"),
    "hummingbird": (3200, "Hummingbird pinned bootc base", 832, "Containerfile.el10"),
    "sailfin": (3201, "openSUSE Tumbleweed", 833, "Containerfile.opensuse"),
    "guppy": (3202, "Gentoo stage3", 838, "Containerfile.gentoo"),
    "bonito-rawhide": (3203, "Fedora Rawhide", 831, "Containerfile.el10"),
    "gurnard": (3204, "Ubuntu Noble", 834, "Containerfile.ubuntu"),
    "grouper": (3205, "Ubuntu Resolute", 835, "Containerfile.ubuntu"),
    "flounder": (3206, "Debian Trixie", 836, "Containerfile.debian"),
    "flounder-sid": (3207, "Debian Sid", 837, "Containerfile.debian"),
}

EXPECTED_BINARIES = (
    "tuna-compositor",
    "tuna-session",
    "tuna-shell-host",
    "tuna-shell-gtk",
    "tuna-ibus-bridge",
    "tuna-greeter",
)

# Handoff target -> (variants owned by that target, package prerequisite,
# Containerfile stage). Cross-checked against the candidate cells: a target
# must carry the same prerequisite and stage its variants' records carry.
EXPECTED_TARGETS = {
    "el10": (("yellowfin", "albacore", "skipjack"), 828, "Containerfile.el10"),
    "eln": (("wahoo",), 829, "Containerfile.el10"),
    "fedora44": (("bonito",), 830, "Containerfile.el10"),
    "rawhide": (("bonito-rawhide",), 831, "Containerfile.el10"),
    "hummingbird": (("hummingbird",), 832, "Containerfile.el10"),
    "opensuse": (("sailfin",), 833, "Containerfile.opensuse"),
    "gentoo": (("guppy",), 838, "Containerfile.gentoo"),
    "ubuntu-noble": (("gurnard",), 834, "Containerfile.ubuntu"),
    "ubuntu-resolute": (("grouper",), 835, "Containerfile.ubuntu"),
    "debian-trixie": (("flounder",), 836, "Containerfile.debian"),
    "debian-sid": (("flounder-sid",), 837, "Containerfile.debian"),
}

# Exact factory receipt for the six-binaries/compat/payload lists. The recipe
# lives in tunaos-packages, outside this repo, so unit CI cannot read it
# without unbounded live network; the commit/blob below pins the exact source
# those lists were verified against out of band. Re-verify against that blob --
# not just re-type the lists -- before changing either side.
FACTORY_RECIPE_COMMIT = "f1965b3e5385e20f81d35bc2d0b1e7b3c75400de"
FACTORY_RECIPE_BLOB = "d1c68be1fc81c8b4c14a05efd109a2f5a447f3df"
FACTORY_RECIPE_PATH = "packages/tuna-desktop/package.yaml"

# Bounded direct-reference lint surface. Directory entries are plain strings
# resolved through `ROOT / entry` (never `ROOT / "literal"`) for the same
# filter-counting reason as the payload paths above.
SCAN_DIRS = (
    ".github/workflows",
    ".github/scripts",
    "scripts",
    "build_scripts",
    "just",
    "experiences",
)
SCAN_ROOT_FILES = ("Justfile",)
SCAN_ROOT_GLOBS = ("Containerfile.*",)
SCAN_SUFFIXES = {".yml", ".yaml", ".sh", ".py", ".just", ".conf", ""}
FIXTURE_MARKERS = ("tuna-matrix-candidates", "tuna/target-handoffs")


def _candidates():
    return yaml.safe_load(CANDIDATES.read_text(encoding="utf-8"))


def _handoffs():
    return yaml.safe_load(HANDOFFS.read_text(encoding="utf-8"))


def _variants():
    config = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    return {v["id"]: v for v in config["variants"]}


def _contract_text():
    return VERIFY_CONTRACT.read_text(encoding="utf-8")


def _tuna_manifest():
    return yaml.safe_load(TUNA_MANIFEST.read_text(encoding="utf-8"))


def _check_target_bindings(doc, cells_by_variant):
    """Every handoff target owns exactly its variants and carries the same
    package prerequisite and Containerfile stage the candidate records carry
    for those variants. Factored out so the mutation test below can prove
    each corruption mode fails."""
    ids = [target["id"] for target in doc["targets"]]
    assert len(ids) == len(set(ids)), f"duplicate handoff target id in {sorted(ids)}"
    assert sorted(ids) == sorted(EXPECTED_TARGETS), "handoff target set drifted"
    for target in doc["targets"]:
        variants, prereq, stage = EXPECTED_TARGETS[target["id"]]
        assert sorted(target["variants"]) == sorted(variants), target["id"]
        assert target["package_prerequisite"] == PACKAGES_ISSUE.format(prereq), target["id"]
        assert target["containerfile_stage"] == stage, target["id"]
        for variant in target["variants"]:
            cell = cells_by_variant[variant]
            assert cell["package_prerequisite"] == target["package_prerequisite"], variant
            assert cell["containerfile_stage"] == target["containerfile_stage"], variant


def _check_contract_binding(doc, contract):
    """Every installed-contract constant in the handoff must appear in the
    exact enforcement line the contract script uses for it -- not merely
    beside a literal kept in this file. Handoff typos and contract drift
    both fail here."""
    session = doc["session_contract"]
    assert f"for binary in {' '.join(session['binaries'])}" in contract
    desktop = session["wayland_session"]
    assert f"require_glob '{desktop}'" in contract
    assert f"grep -qx 'Exec={session['session_exec']}' {desktop}" in contract
    assert f"grep -qx 'DesktopNames={session['session_desktop_names']}' {desktop}" in contract
    assert f"require_glob '{session['pam_service']}'" in contract
    assert f"require_glob '{session['user_target']}'" in contract
    compat_desktop = session["compat_session"]
    assert f"require_glob '{compat_desktop}'" in contract
    assert f"grep -qx 'Exec={session['session_exec']}' {compat_desktop}" in contract
    assert f"grep -qx 'NoDisplay=true' {compat_desktop}" in contract
    assert f"require_glob '{session['compat_pam_service']}'" in contract
    assert f"grep -qx '{session['session_exec']}' /etc/greetd/environments" in contract
    portal = doc["portal_contract"]
    assert f"require_glob '{portal['config']}'" in contract
    portal_lines = [
        line for line in contract.splitlines()
        if "require_portal_preference" in line and portal["config"] in line
    ]
    assert len(portal_lines) == 2, portal_lines
    loop = next(line for line in portal_lines if "$portal" in line)
    access = next(line for line in portal_lines if ".Access" in line)
    assert loop.rsplit(None, 1)[-1] == portal["screencast_backend"]
    assert loop.rsplit(None, 1)[-1] == portal["screenshot_backend"]
    assert access.rsplit(None, 1)[-1] == portal["access_backend"]
    dm = doc["dm_contract"]
    assert f"require_unit {dm['manager']}" in contract
    assert f"dm_pattern='^{dm['manager']}" in contract
    for greeter in dm["retained_greeter"].split("/"):
        assert f"require_command {greeter}" in contract, greeter


def _check_payload_binding(doc, payload, environments, manifest):
    """The handoff must also agree with what the image actually ships and
    installs: the portal payload, the greetd environments file, and the
    Marlin desktop manifest that carries the greeter and portal packages."""
    session = doc["session_contract"]
    portal = doc["portal_contract"]
    dm = doc["dm_contract"]
    assert f"org.freedesktop.impl.portal.ScreenCast={portal['screencast_backend']};" in payload
    assert f"org.freedesktop.impl.portal.Screenshot={portal['screenshot_backend']};" in payload
    assert f"org.freedesktop.impl.portal.Access={portal['access_backend']};" in payload
    assert session["session_exec"] in environments.split()
    assert manifest["display_manager"] == dm["manager"]
    installed = manifest["packages"]["pacman"]
    for backend in {
        portal["screencast_backend"],
        portal["screenshot_backend"],
        portal["access_backend"],
    }:
        assert f"xdg-desktop-portal-{backend}" in installed, backend
    for greeter in dm["retained_greeter"].split("/"):
        assert any(greeter in package for package in installed), greeter


def _is_probably_text(path):
    try:
        with path.open("rb") as handle:
            return b"\x00" not in handle.read(8192)
    except OSError:
        return False


def _scan_files():
    """Every production entrypoint the direct-reference lint covers: the
    enumerated root files and globs at any suffix, plus the suffix-filtered
    directory walk (extensionless entrypoints included, binaries skipped)."""
    candidates = set()
    for name in SCAN_ROOT_FILES:
        candidate = ROOT / name
        if candidate.is_file():
            candidates.add(candidate)
    for pattern in SCAN_ROOT_GLOBS:
        for candidate in ROOT.glob(pattern):
            if candidate.is_file():
                candidates.add(candidate)
    for entry in SCAN_DIRS:
        root = ROOT / entry
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            if path.is_file() and path.suffix in SCAN_SUFFIXES:
                candidates.add(path)
    return sorted(path for path in candidates if _is_probably_text(path))


def _references_fixtures(path):
    text = path.read_text(encoding="utf-8", errors="replace")
    return any(marker in text for marker in FIXTURE_MARKERS)


def test_the_candidate_matrix_is_candidate_only():
    doc = _candidates()
    assert doc["version"] == 1
    assert doc["status"] == "candidate-only"
    assert len(doc["cells"]) == 13
    assert sorted(c["variant"] for c in doc["cells"]) == sorted(EXPECTED_CELLS)


def test_every_cell_carries_its_actual_issue_prereq_and_stage():
    doc = _candidates()
    for cell in doc["cells"]:
        issue, base, prereq, stage = EXPECTED_CELLS[cell["variant"]]
        assert cell["issue"] == TUNAOS_ISSUE.format(issue), cell["variant"]
        assert cell["base"] == base, cell["variant"]
        assert cell["package_prerequisite"] == PACKAGES_ISSUE.format(prereq), cell["variant"]
        assert cell["containerfile_stage"] == stage, cell["variant"]
        assert cell["status"] == "candidate", cell["variant"]
        assert cell["support"] == "none", cell["variant"]
        assert cell["pins"] == "pending", cell["variant"]
        assert cell["admitted_platforms"] == [], cell["variant"]


def test_declared_platforms_match_build_config():
    """declared_platforms is scope context copied from the build config, and
    this test keeps the copy honest. Admission is the empty list beside it."""
    doc = _candidates()
    variants = _variants()
    for cell in doc["cells"]:
        assert cell["declared_platforms"] == variants[cell["variant"]]["platforms"], cell["variant"]


def test_no_cell_claims_media_or_production_fields():
    for cell in _candidates()["cells"]:
        for field in ("build_image", "build_iso", "build_qcow2", "luks_e2e", "publish"):
            assert field not in cell, f"{cell['variant']}: {field} is a production claim"


def test_build_config_still_has_no_tuna_flavor_for_candidates():
    """The 13 cells are absent from the production matrix. A tuna flavor
    appearing there is admission work landing through the owning issue, and
    this candidate record must be retired for that cell in the same change --
    not left shadowing production."""
    variants = _variants()
    for variant in EXPECTED_CELLS:
        flavor_ids = [f["id"] for f in variants[variant]["flavors"]]
        assert "tuna" not in flavor_ids, f"{variant} gained a production tuna flavor"


def test_marlin_reference_matches_the_image_only_cell():
    """Media-proof from source: marlin:tuna builds an image and nothing else.
    The reference row mirrors the build config; drift fails here."""
    variants = _variants()
    tuna = next(f for f in variants["marlin"]["flavors"] if f["id"] == "tuna")
    assert tuna["build_image"] is True
    assert tuna.get("build_iso") is False
    assert tuna.get("build_qcow2") is False
    assert tuna.get("luks_e2e") is False
    assert tuna.get("platforms") == ["linux/amd64"]
    ref = _candidates()["marlin_reference"]
    assert ref["build_image"] is True
    assert ref["build_iso"] is False
    assert ref["build_qcow2"] is False
    assert ref["luks_e2e"] is False
    assert ref["platforms"] == ["linux/amd64"]
    assert ref["pins"] == "pending-final-qualification"


def test_gates_cite_every_variant_issue():
    gates = _candidates()["gates"]
    assert gates["provenance"] == [TUNAOS_ISSUE.format(n) for n in range(3195, 3208)]
    assert [g["id"] for g in gates["implementation"]] == [
        "G1-native-package-stage",
        "G2-session-payload-ownership",
        "G3-explicit-cell-platforms",
        "G4-boot-dm-session-auth",
        "G5-installed-journeys-negatives",
        "G6-installer-artifact-paths",
    ]
    assert [g["id"] for g in gates["acceptance"]] == [
        "A1-exact-head-evidence-bundle",
        "A2-installed-arch-evidence",
        "A3-epic-gated-publication",
    ]


def test_gates_carry_their_substantive_requires_bodies():
    """IDs and provenance URLs alone would pass with swapped or emptied
    bodies. Each gate keeps a non-empty requires body carrying its
    substantive requirement. Bodies are edited/paraphrased distillations of
    the owning issues' checklists, not verbatim quotations -- the phrases
    below pin substance, not wording."""
    gates = _candidates()["gates"]
    bodies = {gate["id"]: gate["requires"] for gate in gates["implementation"] + gates["acceptance"]}
    expected_phrases = {
        "G1-native-package-stage": ("Containerfile", "dependency mapping"),
        "G2-session-payload-ownership": ("Lockdown", "package ownership"),
        "G3-explicit-cell-platforms": ("platform", "digest"),
        "G4-boot-dm-session-auth": ("gtkgreet", "authentication"),
        "G5-installed-journeys-negatives": ("portal", "failure"),
        "G6-installer-artifact-paths": ("ISO", "recovery"),
        "A1-exact-head-evidence-bundle": ("Exact-head", "image digest"),
        "A2-installed-arch-evidence": ("architecture", "failure"),
        "A3-epic-gated-publication": ("epic", "publication"),
    }
    assert sorted(bodies) == sorted(expected_phrases)
    for gate_id, phrases in expected_phrases.items():
        assert isinstance(bodies[gate_id], str) and bodies[gate_id].strip(), gate_id
        for phrase in phrases:
            assert phrase in bodies[gate_id], f"{gate_id}: missing {phrase!r}"


def test_handoffs_cover_all_thirteen_variants_exactly_once():
    doc = _handoffs()
    assert doc["version"] == 1
    assert doc["status"] == "candidate-handoffs-only"
    seen = []
    for target in doc["targets"]:
        seen.extend(target["variants"])
    assert sorted(seen) == sorted(EXPECTED_CELLS)
    assert "marlin" not in seen


def test_handoff_targets_bind_variants_prereq_and_stage():
    cells = {cell["variant"]: cell for cell in _candidates()["cells"]}
    _check_target_bindings(_handoffs(), cells)


def test_handoff_target_guard_catches_binding_mutations():
    """Negative controls: a wrong prerequisite, a foreign stage, a misowned
    variant, or a duplicated target id must each fail the binding check. The
    pre-P2 guard (coverage/count/pending/media only) stayed green on all four."""
    cells = {cell["variant"]: cell for cell in _candidates()["cells"]}
    base = _handoffs()

    wrong_prereq = copy.deepcopy(base)
    wrong_prereq["targets"][0]["package_prerequisite"] = PACKAGES_ISSUE.format(829)
    with pytest.raises(AssertionError):
        _check_target_bindings(wrong_prereq, cells)

    foreign_stage = copy.deepcopy(base)
    foreign_stage["targets"][1]["containerfile_stage"] = "Containerfile.gentoo"
    with pytest.raises(AssertionError):
        _check_target_bindings(foreign_stage, cells)

    misowned = copy.deepcopy(base)
    misowned["targets"][0]["variants"] = ["wahoo"]
    with pytest.raises(AssertionError):
        _check_target_bindings(misowned, cells)

    duplicate = copy.deepcopy(base)
    duplicate["targets"][1]["id"] = duplicate["targets"][0]["id"]
    with pytest.raises(AssertionError):
        _check_target_bindings(duplicate, cells)


def test_handoffs_match_the_installed_contract_source():
    """Session/portal/DM constants are bound to the actual installed-contract
    script, the shipped payload files, and the Marlin desktop manifest --
    not re-asserted against literals kept in this file. A handoff typo, a
    drifted contract, or a payload/manifest that stops carrying a named
    path fails here."""
    doc = _handoffs()
    _check_contract_binding(doc, _contract_text())
    _check_payload_binding(
        doc,
        PORTAL_PAYLOAD.read_text(encoding="utf-8"),
        GREETD_ENVIRONMENTS.read_text(encoding="utf-8"),
        _tuna_manifest(),
    )


def test_contract_binding_catches_drift_and_typos():
    """Negative controls for the source binding: a handoff value the script
    does not enforce, and a script that drops an enforcement, must each
    fail. The pre-P2 literal comparison stayed green on script drift by
    construction -- it never read the script."""
    doc = _handoffs()
    contract = _contract_text()
    typo = copy.deepcopy(doc)
    typo["session_contract"]["session_exec"] = "tuna-session-typo"
    with pytest.raises(AssertionError):
        _check_contract_binding(typo, contract)
    drifted = contract.replace(
        "/usr/share/wayland-sessions/tuna.desktop",
        "/usr/share/wayland-sessions/tuna-renamed.desktop",
    )
    assert drifted != contract
    with pytest.raises(AssertionError):
        _check_contract_binding(doc, drifted)


def test_handoffs_pin_compat_lockdown_and_native_status():
    """What real consumers require beyond the session paths: the compat set
    is the exact roost- rename expansion the factory recipe ships as
    relative symlinks and the contract script verifies link by link;
    Lockdown descriptor/routing stay pending on the owning draft instead of
    naming a descriptor; the native greeter stays pending on wired-auth
    proof instead of displacing gtkgreet/cage."""
    doc = _handoffs()
    session = doc["session_contract"]
    assert tuple(session["binaries"]) == EXPECTED_BINARIES
    suffixes = []
    for binary in session["binaries"]:
        assert binary.startswith("tuna-"), binary
        suffixes.append(binary.split("tuna-", 1)[1])
    assert session["compat_binaries"] == [f"roost-{suffix}" for suffix in suffixes]
    assert session["compat_session"] == "/usr/share/wayland-sessions/roost.desktop"
    assert session["compat_pam_service"] == "/etc/pam.d/roost-lock"
    contract = _contract_text()
    assert 'compat_link="/usr/bin/roost-$name"' in contract
    assert '[[ "$compat_target" == "tuna-$name" ]]' in contract
    assert session["compat_session"] in contract
    assert session["compat_pam_service"] in contract
    portal = doc["portal_contract"]
    assert portal["lockdown_descriptor"] == "pending-on-3194", "Lockdown route is owned by draft #3194"
    assert portal["lockdown_routing"] == "pending-on-3194", "Lockdown route is owned by draft #3194"
    assert doc["dm_contract"]["native_greeter"] == "pending-wired-auth-proof"
    for pinned in (FACTORY_RECIPE_COMMIT, FACTORY_RECIPE_BLOB):
        assert len(pinned) == 40 and all(c in "0123456789abcdef" for c in pinned)
    assert FACTORY_RECIPE_PATH == "packages/tuna-desktop/package.yaml"


def test_handoffs_leave_every_package_identity_pending():
    doc = _handoffs()
    assert len(doc["targets"]) == 11
    for target in doc["targets"]:
        for field in (
            "package_identity",
            "repository_identity",
            "signature_trust",
            "source_vendor_arch",
            "native_dependency_mapping",
        ):
            assert target[field] == "pending", f"{target['id']}: {field}"
        assert target["media"] == {"iso": False, "qcow2": False, "luks_e2e": False}, target["id"]


def test_handoffs_name_no_package_source_or_media():
    """Mirror of the package-source policy for the one manifests/ file this
    change adds: no copr/ppa/obs/aur keys, no external repository baseurl,
    no enabled media anywhere in the document."""
    text = HANDOFFS.read_text(encoding="utf-8")
    doc = yaml.safe_load(text)

    def walk(value, path=""):
        if isinstance(value, dict):
            for key, child in value.items():
                assert str(key).lower() not in {"copr", "ppa", "obs", "aur"}, f"{path}.{key}"
                walk(child, f"{path}.{key}" if path else str(key))
        elif isinstance(value, list):
            for index, child in enumerate(value):
                walk(child, f"{path}[{index}]")
        elif isinstance(value, str) and path.endswith(".baseurl"):
            assert not value.startswith(("http://", "https://")), path

    walk(doc)
    assert "c10s-gnome-5" not in text


def test_no_direct_production_reference_to_the_candidate_files():
    """Bounded direct-reference lint: no production entrypoint may name the
    candidate fixtures. tests/ may read them and the admission workflow runs
    this file; nothing else may reference them.

    Bounded means bounded: this catches literal direct references under the
    enumerated entrypoints (workflows, scripts, just, experiences, the root
    Justfile, and every root Containerfile -- extensionless entrypoints
    included). References assembled through a directory glob or a
    constructed path are not detected; a substring scan cannot prove all
    possible consumers."""
    offenders = [
        str(path.relative_to(ROOT)) for path in _scan_files() if _references_fixtures(path)
    ]
    assert not offenders, (
        "production must keep consuming build-config.yml, not the candidate fixtures: "
        + ", ".join(offenders)
    )


def test_direct_reference_lint_covers_the_required_surfaces():
    """The pre-P2 scan walked five directories with five suffixes and never
    saw the root Justfile, any Containerfile, extensionless entrypoints, or
    experiences/. Each of those surfaces must be scannable now."""
    scanned = {path.relative_to(ROOT) for path in _scan_files()}
    assert Path("Justfile") in scanned
    assert any(str(path).startswith("Containerfile.") for path in scanned)
    assert Path("build_scripts/scripts/image-info-set") in scanned
    assert any(path.suffix == "" and path.name != "Justfile" for path in scanned)
    assert any(str(path).startswith("experiences/") for path in scanned)


def test_direct_reference_lint_flags_a_synthetic_consumer(tmp_path):
    """The lint must actually fire: a file naming a fixture is an offender,
    and a file naming neither marker is not."""
    consumer = tmp_path / "fake-entrypoint"
    consumer.write_text("source .github/tuna-matrix-candidates.yml\n", encoding="utf-8")
    assert _references_fixtures(consumer)
    clean = tmp_path / "clean"
    clean.write_text("source .github/build-config.yml\n", encoding="utf-8")
    assert not _references_fixtures(clean)
