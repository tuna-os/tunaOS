"""RFC 018 phase 2: scripts/promote-stable.py selection and gates, offline.

Every fact the script reads from the registry or GitHub enters through a small
I/O function; these tests feed the pure functions fixtures instead, so the
soak boundary, the Soak-After maximum, the release-blocker match, the sweep
gate and the NOOP cases are pinned without network.
"""
from __future__ import annotations

from datetime import UTC, date, datetime
import importlib.util
from pathlib import Path
import re
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("promote_stable_under_test",
                                              ROOT / "scripts/promote-stable.py")
ps = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ps)
CONFIG_SPEC = importlib.util.spec_from_file_location("promote_stable_config",
                                                     ROOT / "scripts/lib/tunaos_config.py")
tunaos_config = importlib.util.module_from_spec(CONFIG_SPEC)
CONFIG_SPEC.loader.exec_module(tunaos_config)

WORKFLOW = ROOT / ".github/workflows/promote-stable.yml"
SWEEP_WORKFLOW = ROOT / ".github/workflows/desktop-contract-sweep.yml"


def cell(variant="albacore", flavor="gnome", soak=3, image=None, tag=None):
    return ps.Cell(variant=variant, flavor=flavor, image=image or f"ghcr.io/tuna-os/{variant}",
                   tag=tag or flavor, platforms=("linux/amd64", "linux/arm64"),
                   aliases=("almalinux",), soak_days=soak)


def at(text):
    return datetime.fromisoformat(text).replace(tzinfo=UTC)


def gens(c, *pairs):
    """pairs newest first: ("2026-10-30", "sha256:aaa")."""
    return ps.generations(c, [(date.fromisoformat(d), digest) for d, digest in pairs])


HISTORY = (("2026-10-30", "sha256:e"), ("2026-10-29", "sha256:d"), ("2026-10-28", "sha256:c"),
           ("2026-10-27", "sha256:b"), ("2026-10-26", "sha256:a"))


# ── soak ─────────────────────────────────────────────────────────────────────

def test_soak_is_measured_from_the_end_of_the_dated_day():
    c = cell()
    history = gens(c, ("2026-10-26", "sha256:a"))
    held = ps.select(history, "sha256:old", 3, at("2026-10-29T23:59:59"))
    assert held.decision == "HOLD"
    assert "eligible 2026-10-30T00:00Z" in held.reason
    ready = ps.select(history, "sha256:old", 3, at("2026-10-30T00:00:00"))
    assert ready.decision is None
    assert ready.candidate.tag == "gnome-20261026"
    assert ready.baseline == "sha256:old"


def test_newest_soaked_generation_wins_and_soak_days_is_per_variant():
    c = cell()
    history = gens(c, *HISTORY)
    assert ps.select(history, "sha256:z", 3, at("2026-10-30T06:00")).candidate.digest == "sha256:a"
    assert ps.select(history, "sha256:z", 1, at("2026-10-30T06:00")).candidate.digest == "sha256:c"
    long = ps.select(history, "sha256:z", 5, at("2026-10-30T06:00"))
    assert long.decision == "HOLD" and "needs 5d" in long.reason


def test_a_digest_dated_on_several_days_entered_testing_on_the_oldest():
    c = cell()
    history = gens(c, ("2026-10-29", "sha256:a"), ("2026-10-28", "sha256:a"),
                   ("2026-10-26", "sha256:a"), ("2026-10-25", "sha256:old"))
    assert [(g.digest, g.newest, g.oldest) for g in history] == [
        ("sha256:a", date(2026, 10, 29), date(2026, 10, 26)),
        ("sha256:old", date(2026, 10, 25), date(2026, 10, 25))]
    assert history[0].tag == "gnome-20261029"
    selection = ps.select(history, "sha256:old", 3, at("2026-10-30T06:00"))
    assert selection.candidate.digest == "sha256:a"


def test_probing_stops_once_a_soaked_generation_has_an_older_neighbour():
    c = cell()
    now = at("2026-10-30T06:00")
    assert not ps.settled(gens(c, *HISTORY[:4]), 3, now)
    assert not ps.settled(gens(c, *HISTORY[:5]), 3, now)
    assert ps.settled(gens(c, *HISTORY, ("2026-10-25", "sha256:0")), 3, now)


def test_no_dated_tag_holds():
    selection = ps.select([], "sha256:x", 3, at("2026-10-30T06:00"))
    assert selection.decision == "HOLD" and "no dated :testing tag" in selection.reason


# ── NOOP ─────────────────────────────────────────────────────────────────────

def test_digest_already_stable_is_noop():
    c = cell()
    history = gens(c, *HISTORY)
    selection = ps.select(history, "sha256:a", 3, at("2026-10-30T06:00"))
    assert selection.decision == "NOOP"
    assert "stable already at gnome-20261026" in selection.reason


def test_stable_ahead_of_the_soaked_candidate_is_noop_with_a_phase3_shadow():
    # Phases 1-2: Promote still writes the bare tag, so stable is today's image.
    c = cell()
    history = gens(c, *HISTORY, ("2026-10-25", "sha256:0"))
    selection = ps.select(history, "sha256:e", 3, at("2026-10-30T06:00"))
    assert selection.decision == "NOOP"
    assert selection.ahead.tag == "gnome-20261030"
    assert selection.candidate.digest == "sha256:a"
    # Soak-After for the shadow verdict is scanned against the generation
    # stable would have left, not against the newer bare tag.
    assert selection.baseline == "sha256:0"


def test_stable_ahead_and_nothing_soaked_is_noop():
    c = cell()
    history = gens(c, ("2026-10-30", "sha256:e"), ("2026-10-29", "sha256:d"))
    selection = ps.select(history, "sha256:e", 3, at("2026-10-30T06:00"))
    assert selection.decision == "NOOP" and selection.candidate is None
    assert "soak:" in selection.reason


# ── Soak-After ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("message,days", [
    ("fix: boot\n\nSoak-After: 7d\nSigned-off-by: a <a@b>", 7),
    ("x\n\nsoak-after:2d\nSoak-After: 10d\n", 10),
    ("x\n\nSoak-After: 7 days\n", 0),
    ("mentions Soak-After: 9d inline", 0),
    ("x", 0),
])
def test_soak_after_trailer_parsing(message, days):
    assert ps.soak_after_days(message) == days


def test_candidate_waits_for_the_largest_soak_after():
    candidate = ps.Generation("sha256:a", date(2026, 10, 20), date(2026, 10, 20), "gnome-20261020")
    trailers = [("a" * 40, 2), ("b" * 40, 7), ("c" * 40, 5)]
    ok, why = ps.soak_after_gate(trailers, candidate, 3, at("2026-10-27T23:00"))
    assert not ok and "bbbbbbb asks 7d" in why and "eligible 2026-10-28T00:00Z" in why
    ok, why = ps.soak_after_gate(trailers, candidate, 3, at("2026-10-28T00:00"))
    assert ok and "served" in why
    ok, why = ps.soak_after_gate([("a" * 40, 2)], candidate, 3, at("2026-10-24T00:00"))
    assert ok and "within 3d soak" in why
    assert ps.soak_after_gate([], candidate, 3, at("2026-10-24T00:00"), 12) == (
        True, "no Soak-After trailer in 12 commit(s)")


def test_commit_trailers_reads_only_the_range_from_local_history(tmp_path, monkeypatch):
    def git(*args):
        return subprocess.run(["git", "-C", str(tmp_path), "-c", "user.name=t",
                               "-c", "user.email=t@t", *args],
                              check=True, capture_output=True, text=True).stdout.strip()

    git("init", "-q")
    git("commit", "-q", "--allow-empty", "-m", "base\n\nSoak-After: 30d")
    base = git("rev-parse", "HEAD")
    git("commit", "-q", "--allow-empty", "-m", "luks: change\n\nSoak-After: 6d")
    git("commit", "-q", "--allow-empty", "-m", "docs: typo")
    head = git("rev-parse", "HEAD")
    monkeypatch.setattr(ps, "ROOT", tmp_path)
    ps.commit_trailers.cache_clear()
    count, trailers = ps.commit_trailers(base[:7], head)
    assert count == 2
    assert [days for _sha, days in trailers] == [6]
    with pytest.raises(ps.FactError, match="not in the local clone"):
        ps.commit_trailers("0" * 40, head)
    ps.commit_trailers.cache_clear()


# ── release-blocker ──────────────────────────────────────────────────────────

ISSUES = [
    {"number": 1, "title": "albacore:gnome-hwe black screen", "labels": ["release-blocker"]},
    {"number": 2, "title": "Regression on albacore:gnome after kernel bump",
     "labels": ["release-blocker"]},
    {"number": 3, "title": "installer crash", "labels": ["release-blocker", "variant/yellowfin"]},
    {"number": 4, "title": "bonito:kde-rawhide does not boot", "labels": ["release-blocker"]},
]


def test_release_blocker_matches_by_title_without_matching_sibling_flavors():
    assert ps.matching_blockers(cell("albacore", "gnome"), ISSUES) == ["#2 (title)"]
    assert ps.matching_blockers(cell("albacore", "gnome-hwe"), ISSUES) == ["#1 (title)"]
    assert ps.matching_blockers(cell("albacore", "kde"), ISSUES) == []


def test_release_blocker_matches_by_variant_label():
    hits = ps.matching_blockers(cell("yellowfin", "kde"), ISSUES)
    assert hits == ["#3 (label variant/yellowfin)"]


def test_release_blocker_matches_the_published_image_name():
    rawhide = cell("bonito-rawhide", "kde", image="ghcr.io/tuna-os/bonito", tag="kde-rawhide")
    assert ps.matching_blockers(rawhide, ISSUES) == ["#4 (title)"]


# ── desktop-contract-sweep ───────────────────────────────────────────────────

CANDIDATE = ps.Generation("sha256:a", date(2026, 10, 26), date(2026, 10, 26), "gnome-20261026")
SWEEP = ps.Sweep({
    "albacore:gnome": ("pass", "contract satisfied", "41", date(2026, 10, 30)),
    "albacore:kde": ("fail", "missing required: dolphin", "41", date(2026, 10, 30)),
    "yellowfin:gnome": ("pass", "contract satisfied", "39", date(2026, 10, 25)),
})


def test_missing_sweep_result_holds():
    ok, why = ps.sweep_gate(cell("albacore", "niri"), SWEEP, CANDIDATE)
    assert not ok and "no sweep result for albacore:niri" in why
    ok, why = ps.sweep_gate(cell("albacore", "gnome"), None, CANDIDATE)
    assert not ok and "no desktop-contract-baseline artifact" in why


def test_failing_or_stale_sweep_result_holds():
    ok, why = ps.sweep_gate(cell("albacore", "kde"), SWEEP, CANDIDATE)
    assert not ok and "fail (missing required: dolphin" in why
    ok, why = ps.sweep_gate(cell("yellowfin", "gnome"), SWEEP, CANDIDATE)
    assert not ok and "predates gnome-20261026" in why


def test_passing_sweep_and_derived_or_desktopless_flavors():
    assert ps.sweep_gate(cell("albacore", "gnome"), SWEEP, CANDIDATE)[0]
    ok, why = ps.sweep_gate(cell("albacore", "gnome-nvidia"), SWEEP, CANDIDATE)
    assert ok and "via albacore:gnome" in why
    ok, why = ps.sweep_gate(cell("albacore", "base-hwe"), SWEEP, CANDIDATE)
    assert ok and "n/a" in why


def test_swept_desktops_match_the_sweep_workflow():
    match = re.search(r'test\("\^\(([a-z|]+)\)\$"\)', SWEEP_WORKFLOW.read_text())
    assert match, "desktop-contract-sweep.yml no longer filters flavors by a desktop regex"
    assert tuple(match.group(1).split("|")) == ps.SWEPT_DESKTOPS


# ── decision ─────────────────────────────────────────────────────────────────

def test_every_failing_gate_is_named():
    decision, reason = ps.decide(cell(), CANDIDATE, ["#2 (title)"], (False, "desktop contract: x"),
                                 (False, "Soak-After: abc asks 7d"))
    assert decision == "HOLD"
    assert reason == "release-blocker: #2 (title); desktop contract: x; Soak-After: abc asks 7d"


def test_all_gates_green_promotes():
    decision, reason = ps.decide(cell(), CANDIDATE, [], (True, "desktop contract pass"),
                                 (True, "no Soak-After trailer in 3 commit(s)"))
    assert decision == "PROMOTE"
    assert reason.startswith("gnome-20261026 (a) entered :testing 2026-10-26, 3d soak served")


# ── cells, config and the workflow ───────────────────────────────────────────

def test_cells_come_from_build_config_with_per_variant_soak():
    matrix = tunaos_config.matrix(tunaos_config.load())
    cells = {c.name: c for c in ps.cells_from_config(matrix, "ghcr.io/tuna-os")}
    assert cells["albacore:gnome"].soak_days == 3
    assert cells["yellowfin:gnome"].soak_days == 5
    rawhide = cells["bonito-rawhide:kde"]
    assert (rawhide.image, rawhide.tag) == ("ghcr.io/tuna-os/bonito", "kde-rawhide")
    built = {(v["id"], f["id"]) for v in matrix["variants"] for f in v["flavors"]
             if f.get("build_image") is True}
    assert {(c.variant, c.flavor) for c in cells.values()} == built


def test_cells_without_projected_soak_fall_back_to_the_default():
    config = {"variants": [{"id": "x", "platforms": ["linux/amd64"],
                            "flavors": [{"id": "gnome", "build_image": True},
                                        {"id": "kde", "build_image": False}]}]}
    cells = ps.cells_from_config(config, "ghcr.io/o")
    assert [(c.name, c.soak_days) for c in cells] == [("x:gnome", tunaos_config.DEFAULT_SOAK_DAYS)]


def test_cell_filter_accepts_names_and_globs_and_rejects_unknown():
    cells = [cell("albacore", "gnome"), cell("albacore", "kde"), cell("yellowfin", "gnome")]
    assert [c.name for c in ps.filter_cells(cells, "albacore:gnome, yellowfin:*")] == [
        "albacore:gnome", "yellowfin:gnome"]
    assert len(ps.filter_cells(cells, "")) == 3
    with pytest.raises(SystemExit, match="no build_image cell matches nope:gnome"):
        ps.filter_cells(cells, "nope:gnome")


def test_stable_refs_cover_bare_arch_and_alias_tags():
    assert cell().stable_refs() == [
        "ghcr.io/tuna-os/albacore:gnome", "ghcr.io/tuna-os/albacore:gnome-amd64",
        "ghcr.io/tuna-os/albacore:gnome-arm64", "ghcr.io/tuna-os/almalinux:gnome"]


def test_only_dry_run_mode_is_accepted(capsys):
    assert ps.main(["evaluate", "--mode", "promote"]) == 2
    assert "RFC 018 phase 3 not enabled" in capsys.readouterr().err


def test_workflow_is_dry_run_only():
    yaml = pytest.importorskip("yaml")
    text = WORKFLOW.read_text()
    workflow = yaml.safe_load(text)
    assert workflow[True]["schedule"] == [{"cron": "0 6 * * *"}]
    assert workflow["permissions"] == {"contents": "read", "issues": "read", "actions": "read",
                                       "packages": "read"}
    for job in workflow["jobs"].values():
        assert "permissions" not in job
    runs = "\n".join(step.get("run", "") for job in workflow["jobs"].values()
                     for step in job["steps"])
    assert "RFC 018 phase 3 not enabled" in runs
    assert not re.search(r"skopeo copy|imagetools create|podman push|docker push", runs)
    assert runs.count("--mode dry-run") == 2
