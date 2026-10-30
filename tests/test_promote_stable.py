"""RFC 018: scripts/promote-stable.py selection, gates, plan and apply, offline.

Every fact the script reads from the registry or GitHub enters through a small
I/O function; these tests feed the pure functions fixtures instead, so the
soak boundary, the Soak-After maximum, the release-blocker match, the sweep
and lifecycle gates, the NOOP cases, the tags a promotion or rollback writes,
the compare-and-set skip and the digest check are pinned without network.
"""
from __future__ import annotations

from datetime import UTC, date, datetime
import importlib.util
from pathlib import Path
import json
import os
import re
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
def _load(name: str, path: Path):
    # dataclasses resolve string annotations through sys.modules, so a module
    # loaded from a file path must be registered before it executes.
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


ps = _load("promote_stable_under_test", ROOT / "scripts/promote-stable.py")
tunaos_config = _load("promote_stable_config", ROOT / "scripts/lib/tunaos_config.py")

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


def test_stable_ahead_of_the_soaked_candidate_is_noop_with_a_gate_verdict():
    # A bootstrapped cell or a manual forward repoint: stable is today's image.
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
                                 (False, "lifecycle: amd64 failed"),
                                 (False, "Soak-After: abc asks 7d"))
    assert decision == "HOLD"
    assert reason == ("release-blocker: #2 (title); desktop contract: x; "
                      "lifecycle: amd64 failed; Soak-After: abc asks 7d")


def test_all_gates_green_promotes():
    decision, reason = ps.decide(cell(), CANDIDATE, [], (True, "desktop contract pass"),
                                 (True, "lifecycle pass (run 9, 2026-10-29)"),
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





# ── bootc-lifecycle gate ─────────────────────────────────────────────────────

LIFECYCLE_JOBS = [
    {"name": "Generate matrix", "conclusion": "success"},
    {"name": "albacore:gnome (amd64)", "conclusion": "success"},
    {"name": "albacore:gnome (arm64)", "conclusion": "success"},
    {"name": "albacore:kde (amd64)", "conclusion": "success"},
    {"name": "albacore:kde (arm64)", "conclusion": "failure"},
    {"name": "yellowfin:niri (amd64)", "conclusion": "timed_out"},
    {"name": "BETA bonito-rawhide:kde (amd64)", "conclusion": "failure"},
]


def test_lifecycle_jobs_are_grouped_by_cell_and_beta_jobs_are_ignored():
    lifecycle = ps.lifecycle_from_jobs("77", date(2026, 10, 29), LIFECYCLE_JOBS)
    assert lifecycle.arches == {
        "albacore:gnome": {"amd64": "success", "arm64": "success"},
        "albacore:kde": {"amd64": "success", "arm64": "failure"},
        "yellowfin:niri": {"amd64": "timed_out"},
    }


def test_lifecycle_failure_holds_and_an_unchecked_cell_is_na():
    lifecycle = ps.lifecycle_from_jobs("77", date(2026, 10, 29), LIFECYCLE_JOBS)
    assert ps.lifecycle_gate(cell("albacore", "gnome"), lifecycle) == (
        True, "lifecycle pass (run 77, 2026-10-29)")
    assert ps.lifecycle_gate(cell("albacore", "kde"), lifecycle) == (
        False, "lifecycle: arm64 failed (run 77, 2026-10-29)")
    assert not ps.lifecycle_gate(cell("yellowfin", "niri"), lifecycle)[0]
    ok, why = ps.lifecycle_gate(cell("bonito-rawhide", "kde"), lifecycle)
    assert ok and why == "lifecycle: n/a (cell not in run 77)"
    ok, why = ps.lifecycle_gate(cell(), None)
    assert ok and why.startswith("lifecycle: n/a (no completed scheduled bootc-lifecycle.yml run")


def test_lifecycle_job_names_match_the_workflow():
    yaml = pytest.importorskip("yaml")
    workflow = yaml.safe_load((ROOT / ".github/workflows/bootc-lifecycle.yml").read_text())
    assert workflow["jobs"]["lifecycle"]["name"] == \
        "${{ matrix.variant }}:${{ matrix.flavor }} (${{ matrix.arch }})"
    assert workflow["jobs"]["lifecycle-beta"]["name"].startswith("BETA ")


# ── promotion and rollback plans ─────────────────────────────────────────────

REG = "ghcr.io/tuna-os"
DATED = "sha256:" + "d" * 64
OLD = "sha256:" + "0" * 64
ARCH = {"amd64": "sha256:" + "a" * 64, "arm64": "sha256:" + "b" * 64}


def registry(**extra):
    """A fake registry: ref -> digest, with a read() like ps.manifest."""
    tags = {f"{REG}/albacore:gnome": OLD,
            f"{REG}/albacore:gnome-20261026": DATED,
            f"{REG}/albacore:gnome-amd64-20261026": ARCH["amd64"],
            f"{REG}/albacore:gnome-arm64-20261026": ARCH["arm64"]}
    tags.update(extra)

    def read(ref):
        return (tags[ref], {}) if tags.get(ref) else None
    return tags, read


def test_stable_writes_map_dated_sources_to_bare_arch_and_alias_tags():
    assert cell().stable_writes("gnome-20261026") == [
        (f"{REG}/albacore:gnome-20261026", f"{REG}/albacore:gnome"),
        (f"{REG}/albacore:gnome-amd64-20261026", f"{REG}/albacore:gnome-amd64"),
        (f"{REG}/albacore:gnome-arm64-20261026", f"{REG}/albacore:gnome-arm64"),
        (f"{REG}/albacore:gnome-20261026", f"{REG}/almalinux:gnome")]


def test_stable_writes_keep_the_tag_suffix_for_arch_and_alias():
    rawhide = ps.Cell("bonito-rawhide", "kde", f"{REG}/bonito", "kde-rawhide",
                      ("linux/amd64",), ("fedora",), 3)
    assert rawhide.stable_writes("kde-rawhide-20261026") == [
        (f"{REG}/bonito:kde-rawhide-20261026", f"{REG}/bonito:kde-rawhide"),
        (f"{REG}/bonito:kde-rawhide-amd64-20261026", f"{REG}/bonito:kde-rawhide-amd64"),
        (f"{REG}/bonito:kde-rawhide-20261026", f"{REG}/fedora:kde-rawhide")]


def test_plan_entry_records_each_source_digest_and_the_evaluated_stable():
    _, read = registry()
    entry = ps.plan_entry(cell(), "gnome-20261026", DATED, OLD, read=read)
    assert entry["cell"] == "albacore:gnome"
    assert (entry["bare"], entry["from"], entry["to"], entry["digest"]) == (
        f"{REG}/albacore:gnome", OLD, "gnome-20261026", DATED)
    assert [(w["source"].rsplit("/", 1)[1], w["digest"], w["dest"].rsplit("/", 1)[1])
            for w in entry["writes"]] == [
        ("albacore:gnome-20261026", DATED, "albacore:gnome"),
        ("albacore:gnome-amd64-20261026", ARCH["amd64"], "albacore:gnome-amd64"),
        ("albacore:gnome-arm64-20261026", ARCH["arm64"], "albacore:gnome-arm64"),
        ("albacore:gnome-20261026", DATED, "almalinux:gnome")]


def test_plan_entry_refuses_a_missing_source_or_a_moved_dated_tag():
    _, read = registry(**{f"{REG}/albacore:gnome-arm64-20261026": None})
    with pytest.raises(ps.FactError, match="gnome-arm64-20261026 does not exist"):
        ps.plan_entry(cell(), "gnome-20261026", DATED, OLD, read=read)
    _, read = registry(**{f"{REG}/albacore:gnome-20261026": "sha256:" + "e" * 64})
    with pytest.raises(ps.FactError, match="not the evaluated"):
        ps.plan_entry(cell(), "gnome-20261026", DATED, OLD, read=read)


def test_a_promote_verdict_whose_source_vanished_is_held(monkeypatch):
    monkeypatch.setattr(ps, "manifest", lambda ref: None)
    source = ps.Generation(DATED, date(2026, 10, 26), date(2026, 10, 26), "gnome-20261026")
    verdict = ps.Verdict(cell(), "PROMOTE", "ok", stable_digest=OLD, source=source)
    held, entry = ps.planned(verdict)
    assert entry is None and held.decision == "HOLD"
    assert held.reason.startswith("could not plan:")
    noop = ps.Verdict(cell(), "NOOP", "x")
    assert ps.planned(noop) == (noop, None)


# ── apply: compare-and-set, copy by digest, verify ───────────────────────────

def fake_copy(tags, fail=None, corrupt=None):
    """A copy that writes the source digest to the destination, like skopeo."""
    calls = []

    def copy(source, dest):
        calls.append((source, dest))
        if dest == fail:
            return "blob upload unknown"
        tags[dest] = "sha256:" + "f" * 64 if dest == corrupt else source.split("@", 1)[1]
        return ""
    return calls, copy


def planned_entry():
    _, read = registry()
    return ps.plan_entry(cell(), "gnome-20261026", DATED, OLD, read=read)


def test_apply_copies_by_digest_bare_last_and_verifies():
    entry = planned_entry()
    tags, read = registry()
    calls, copy = fake_copy(tags)
    status, detail, written = ps.apply_entry(entry, "PROMOTED", read=read, copy=copy)
    assert status == "PROMOTED", detail
    assert calls == [
        (f"{REG}/albacore@{ARCH['amd64']}", f"{REG}/albacore:gnome-amd64"),
        (f"{REG}/albacore@{ARCH['arm64']}", f"{REG}/albacore:gnome-arm64"),
        (f"{REG}/albacore@{DATED}", f"{REG}/almalinux:gnome"),
        (f"{REG}/albacore@{DATED}", f"{REG}/albacore:gnome")]
    assert written[-1] == f"{REG}/albacore:gnome"
    assert tags[f"{REG}/albacore:gnome"] == DATED
    assert tags[f"{REG}/almalinux:gnome"] == DATED
    assert "verified on 4 tag(s)" in detail


def test_apply_skips_a_cell_whose_stable_moved_since_the_evaluation():
    entry = planned_entry()
    tags, read = registry(**{f"{REG}/albacore:gnome": "sha256:" + "9" * 64})
    calls, copy = fake_copy(tags)
    status, detail, written = ps.apply_entry(entry, "PROMOTED", read=read, copy=copy)
    assert status == "SKIPPED" and calls == [] and written == []
    assert "stable moved from 000000000000 to 999999999999" in detail


def test_apply_skips_a_cell_whose_source_moved():
    entry = planned_entry()
    tags, read = registry(**{f"{REG}/albacore:gnome-amd64-20261026": "sha256:" + "c" * 64})
    calls, copy = fake_copy(tags)
    status, detail, _ = ps.apply_entry(entry, "PROMOTED", read=read, copy=copy)
    assert status == "SKIPPED" and calls == []
    assert "gnome-amd64-20261026 moved" in detail


def test_apply_fails_when_a_written_tag_has_the_wrong_digest():
    entry = planned_entry()
    tags, read = registry()
    _, copy = fake_copy(tags, corrupt=f"{REG}/almalinux:gnome")
    status, detail, _ = ps.apply_entry(entry, "PROMOTED", read=read, copy=copy)
    assert status == "FAILED"
    assert detail == (f"digest check: {REG}/almalinux:gnome is ffffffffffff, "
                      "expected dddddddddddd")


def test_a_failed_copy_fails_the_cell_before_the_bare_tag_moves():
    entry = planned_entry()
    tags, read = registry()
    _, copy = fake_copy(tags, fail=f"{REG}/almalinux:gnome")
    status, detail, written = ps.apply_entry(entry, "PROMOTED", read=read, copy=copy)
    assert status == "FAILED" and "blob upload unknown" in detail
    assert tags[f"{REG}/albacore:gnome"] == OLD
    assert f"{REG}/albacore:gnome" not in written


def test_apply_exits_non_zero_on_a_failed_cell_and_writes_the_summary(tmp_path, monkeypatch):
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps({"action": "promote", "cells": [planned_entry()]}))
    summary = tmp_path / "summary.md"
    monkeypatch.setattr(ps, "apply_entry",
                        lambda entry, done: ("FAILED", "digest check: x", []))
    assert ps.main(["apply", "--plan", str(plan), "--summary", str(summary)]) == 1
    text = summary.read_text()
    assert "| albacore:gnome | `000000000000` | gnome-20261026 (`dddddddddddd`) | **FAILED** |" \
        in text
    monkeypatch.setattr(ps, "apply_entry", lambda entry, done: (done, "verified", ["t"]))
    assert ps.main(["apply", "--plan", str(plan), "--summary", ""]) == 0


def test_copy_retry_retries_with_skopeo_copy_all_and_preserved_digests(monkeypatch):
    calls, sleeps = [], []

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs.get("timeout")))
        return subprocess.CompletedProcess(cmd, 1 if len(calls) < 3 else 0, "", "upload unknown\n")
    monkeypatch.setattr(ps, "run", fake_run)
    assert ps.copy_retry("r/a@sha256:1", "r/a:gnome", sleep=sleeps.append) == ""
    assert calls[0] == (["skopeo", "copy", "--all", "--preserve-digests", "docker://r/a@sha256:1",
                         "docker://r/a:gnome"], ps.COPY_TIMEOUT)
    assert sleeps == [15, 30]
    calls.clear()
    monkeypatch.setattr(ps, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, "", "x\n"))
    assert ps.copy_retry("r/a@sha256:1", "r/a:gnome", sleep=sleeps.append) == "x"


# ── evaluate and rollback write the plan ─────────────────────────────────────

def test_evaluate_in_promote_mode_plans_only_promote_cells(tmp_path, monkeypatch):
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"variants": [{
        "id": "albacore", "platforms": ["linux/amd64", "linux/arm64"], "aliases": ["almalinux"],
        "flavors": [{"id": "gnome", "build_image": True}, {"id": "kde", "build_image": True}]}]}))
    facts = ps.Facts([], ps.Sweep({}), "", None, "")
    monkeypatch.setattr(ps, "gather_facts", lambda repo, cells: (facts, {"x": "y"}))
    source = ps.Generation(DATED, date(2026, 10, 26), date(2026, 10, 26), "gnome-20261026")

    def fake_evaluate(c, now, got):
        assert got is facts
        if c.flavor == "gnome":
            return ps.Verdict(c, "PROMOTE", "ok", stable_digest=OLD, source=source)
        return ps.Verdict(c, "HOLD", "soak")
    monkeypatch.setattr(ps, "evaluate", fake_evaluate)
    _, read = registry()
    monkeypatch.setattr(ps, "manifest", read)
    plan, summary = tmp_path / "plan.json", tmp_path / "summary.md"
    args = ["evaluate", "--config", str(config), "--registry", REG, "--summary", str(summary)]
    with pytest.raises(SystemExit):
        ps.main([*args, "--mode", "promote"])
    assert ps.main([*args, "--mode", "promote", "--plan", str(plan)]) == 0
    written = json.loads(plan.read_text())
    assert written["action"] == "promote"
    assert [e["cell"] for e in written["cells"]] == ["albacore:gnome"]
    assert written["cells"][0]["from"] == OLD
    assert "Stable promotion (RFC 018, promote)" in summary.read_text()
    plan.unlink()
    assert ps.main([*args, "--mode", "dry-run"]) == 0
    assert not plan.exists()


def test_rollback_plans_the_dated_tag_of_the_cell(tmp_path, monkeypatch, capsys):
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"variants": [{
        "id": "albacore", "platforms": ["linux/amd64", "linux/arm64"], "aliases": ["almalinux"],
        "flavors": [{"id": "gnome", "build_image": True}]}]}))
    _, read = registry()
    monkeypatch.setattr(ps, "manifest", read)
    plan = tmp_path / "plan.json"
    base = ["rollback", "--config", str(config), "--registry", REG, "--summary", "",
            "--cell", "albacore:gnome"]
    assert ps.main([*base, "--to", "gnome-20261026", "--reason", "boot loop, #9",
                    "--mode", "rollback", "--plan", str(plan)]) == 0
    written = json.loads(plan.read_text())
    assert written["action"] == "rollback" and written["reason"] == "boot loop, #9"
    (entry,) = written["cells"]
    assert (entry["from"], entry["to"], entry["digest"]) == (OLD, "gnome-20261026", DATED)
    assert [w["dest"] for w in entry["writes"]] == [
        f"{REG}/albacore:gnome", f"{REG}/albacore:gnome-amd64", f"{REG}/albacore:gnome-arm64",
        f"{REG}/almalinux:gnome"]
    assert "ROLLBACK albacore:gnome: repoints" in capsys.readouterr().out
    with pytest.raises(SystemExit, match="dated tag gnome-YYYYMMDD of albacore:gnome"):
        ps.main([*base, "--to", "kde-20261026", "--reason", "x"])
    with pytest.raises(SystemExit, match="non-empty --reason"):
        ps.main([*base, "--to", "gnome-20261026", "--reason", "  "])


def test_unknown_modes_are_rejected():
    with pytest.raises(SystemExit):
        ps.main(["evaluate", "--mode", "rollback"])
    with pytest.raises(SystemExit):
        ps.main(["rollback", "--mode", "promote", "--cell", "a:b", "--to", "b-20261026",
                 "--reason", "x"])


# ── the workflow ─────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def workflow():
    yaml = pytest.importorskip("yaml")
    return yaml.safe_load(WORKFLOW.read_text())


def resolve_mode(workflow, tmp_path, **env):
    step = next(s for s in workflow["jobs"]["evaluate"]["steps"] if s.get("id") == "mode")
    output = tmp_path / "out"
    output.write_text("")
    base = {"EVENT": "workflow_dispatch", "INPUT_MODE": "", "CELL": "", "ROLLBACK_TO": "",
            "REASON": ""}
    result = subprocess.run(["bash", "-c", step["run"]], check=False, capture_output=True,
                            text=True,
                            env={**base, **env, "PATH": os.environ["PATH"],
                                 "GITHUB_OUTPUT": str(output)})
    return result, dict(line.split("=", 1) for line in output.read_text().split())


def test_the_schedule_promotes_and_a_manual_run_defaults_to_a_dry_run(workflow, tmp_path):
    assert workflow[True]["schedule"] == [{"cron": "0 6 * * *"}]
    dispatch = workflow[True]["workflow_dispatch"]["inputs"]["mode"]
    assert dispatch["options"] == ["dry-run", "promote", "rollback"]
    assert dispatch["default"] == "dry-run"
    _, out = resolve_mode(workflow, tmp_path, EVENT="schedule")
    assert out == {"mode": "promote", "command": "evaluate"}
    _, out = resolve_mode(workflow, tmp_path, INPUT_MODE="dry-run")
    assert out == {"mode": "dry-run", "command": "evaluate"}


def test_a_rollback_needs_a_cell_a_dated_tag_and_a_reason(workflow, tmp_path):
    result, out = resolve_mode(workflow, tmp_path, INPUT_MODE="rollback", CELL="albacore:gnome",
                               ROLLBACK_TO="gnome-20261026", REASON="  ")
    assert result.returncode == 1 and "non-empty reason" in result.stdout
    result, out = resolve_mode(workflow, tmp_path, INPUT_MODE="promote", CELL="albacore:gnome",
                               ROLLBACK_TO="gnome-20261026", REASON="x")
    assert result.returncode == 1
    _, out = resolve_mode(workflow, tmp_path, INPUT_MODE="rollback", CELL="albacore:gnome",
                          ROLLBACK_TO="gnome-20261026", REASON="boot loop")
    assert out == {"mode": "rollback", "command": "rollback"}
    _, out = resolve_mode(workflow, tmp_path, INPUT_MODE="dry-run", CELL="albacore:gnome",
                          ROLLBACK_TO="gnome-20261026", REASON="boot loop")
    assert out == {"mode": "dry-run", "command": "rollback"}


def test_only_the_apply_job_can_write_packages(workflow):
    assert workflow["permissions"] == {"contents": "read", "issues": "read", "actions": "read",
                                       "packages": "read"}
    assert workflow["concurrency"] == {"group": "promote-stable", "cancel-in-progress": False}
    evaluate, apply = workflow["jobs"]["evaluate"], workflow["jobs"]["apply"]
    assert "permissions" not in evaluate
    assert apply["permissions"] == {"contents": "read", "packages": "write"}
    assert apply["needs"] == "evaluate"
    assert apply["if"] == "needs.evaluate.outputs.apply == 'true'"
    reads = "\n".join(s.get("run", "") for s in evaluate["steps"])
    writes = "\n".join(s.get("run", "") for s in apply["steps"])
    assert not re.search(r"skopeo copy|promote-stable.py apply", reads)
    assert "promote-stable.py apply --plan" in writes
    assert "skopeo login" in writes and "GITHUB_TOKEN" in str(apply["steps"])
