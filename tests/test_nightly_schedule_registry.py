"""The nightly crons must match the registry table, and each other never.

`build-variant.yml` opens with a schedule registry and the instruction "If you
add a variant or move a cron, keep this table true." Nothing enforced it, and
it stopped being true: every one of the 13 per-variant nightlies sat on the
same `0 1 * * *` cron while the table described a ~2h stagger, and
hummingbird was missing from the table altogether.

That is not a documentation nit. The org has a 20-concurrent-job ceiling, so
13 simultaneous crons queue against each other: scheduled yellowfin runs took
1h32m-8h45m and failed 14 nights running, while the same build dispatched
by hand off-peak finished green in 1h02m. The stagger is the fix that was
written down and then lost.

These tests pin the three things that can rot independently: the crons
against the table, the table against the real flavor counts, and the slots
against each other.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github/workflows"
VARIANT_WORKFLOW = WORKFLOWS / "build-variant.yml"
BUILD_CONFIG = ROOT / ".github/build-config.yml"

# The proving workflows this window is reserved for: daily-verify 04:00,
# verify-asahi 05:40, matrix-status & catalog-facts 06:00,
# desktop-contract-sweep 08:00.
PROVING_WINDOW = (4, 9)
MAX_IN_PROVING_WINDOW = 2
# A variant may sit inside the window only if it is SMALL. Today gurnard has
# 2 flavors and guppy 4; the next tier up is the 7-flavor group (flounder,
# flounder-sid, grouper, sailfin) and everything above it runs to 20. So 4 is
# the boundary between "fits beside the verification workflows" and "is a
# fleet build", and it is a threshold rather than a ranking on purpose --
# see test_the_proving_window_carries_only_small_builds.
MAX_FLAVORS_IN_PROVING_WINDOW = 4

# `20 13 * * *` -> ("13", "20", "*"); `20 6 * * 2` -> ("6", "20", "2").
_DAILY_CRON = re.compile(r"^(\d{1,2}) (\d{1,2}) \* \* (\*|[0-6])$")
# `#   00:20 yellowfin(20fl)  02:20 albacore(20)` -> repeated (HH, MM, name, n)
_TABLE_ENTRY = re.compile(r"(\d{2}):(\d{2}) ([a-z0-9-]+)\((\d+)(?:fl)?\)")


def registry_table() -> dict[str, tuple[int, int, int]]:
    """variant -> (hour, minute, documented flavor count), from the comment."""
    entries: dict[str, tuple[int, int, int]] = {}
    for line in VARIANT_WORKFLOW.read_text().splitlines():
        # The table lives in the header comment block, above the `on:` key.
        if line.rstrip() == "on:":
            break
        if not line.startswith("#"):
            continue
        for hh, mm, name, count in _TABLE_ENTRY.findall(line):
            entries[name] = (int(hh), int(mm), int(count))
    return entries


def scheduled_crons() -> dict[str, tuple[int, int]]:
    """variant -> (hour, minute), from each build-<variant>.yml."""
    return {v: (h, m) for v, (h, m, _) in _schedules().items()}


def scheduled_weekdays() -> dict[str, str]:
    """variant -> cron weekday field ("*" for a nightly, "0".."6" for a weekly)."""
    return {v: dow for v, (_, _, dow) in _schedules().items()}


def _schedules() -> dict[str, tuple[int, int, str]]:
    slots: dict[str, tuple[int, int, str]] = {}
    for path in sorted(WORKFLOWS.glob("build-*.yml")):
        variant = path.stem[len("build-") :]
        if variant not in flavor_counts():
            continue  # reusable plumbing or a base rebuild, not a variant nightly
        doc = yaml.safe_load(path.read_text())
        # PyYAML parses the bare `on:` key as the boolean True.
        triggers = doc.get("on", doc.get(True)) or {}
        schedule = triggers.get("schedule") if isinstance(triggers, dict) else None
        if not schedule:
            continue
        match = _DAILY_CRON.match(schedule[0]["cron"].strip())
        if not match:
            continue  # e.g. the weekly archlinuxarm base rebuild
        minute, hour, dow = match.groups()
        slots[variant] = (int(hour), int(minute), dow)
    return slots


def flavor_counts() -> dict[str, int]:
    config = yaml.safe_load(BUILD_CONFIG.read_text())
    return {v["id"]: len(v.get("flavors", [])) for v in config["variants"]}


def test_every_nightly_appears_in_the_registry() -> None:
    """hummingbird was scheduled but undocumented, so nothing balanced it."""
    assert set(scheduled_crons()) == set(registry_table())


def test_the_registry_matches_the_actual_crons() -> None:
    table = registry_table()
    for variant, (hour, minute) in scheduled_crons().items():
        assert (hour, minute) == table[variant][:2], (
            f"{variant} runs at {hour:02d}:{minute:02d} but the registry in "
            f"build-variant.yml says {table[variant][0]:02d}:{table[variant][1]:02d}"
        )


def test_the_registry_flavor_counts_are_real() -> None:
    """The counts are what the stagger is balanced on, so they must not rot."""
    counts = flavor_counts()
    for variant, (_, _, documented) in registry_table().items():
        assert documented == counts[variant], (
            f"registry says {variant} has {documented} flavors; "
            f"build-config.yml declares {counts[variant]}"
        )


def test_no_two_variants_share_a_slot() -> None:
    """The regression itself: 13 nightlies on one cron, starving each other."""
    slots = scheduled_crons()
    seen: dict[tuple[int, int], str] = {}
    for variant, slot in sorted(slots.items()):
        assert slot not in seen, (
            f"{variant} and {seen[slot]} both fire at "
            f"{slot[0]:02d}:{slot[1]:02d}; the 20-job ceiling makes them queue"
        )
        seen[slot] = variant


def test_the_proving_window_carries_only_small_builds() -> None:
    """04:00-09:00 belongs to the verification workflows, not the fleet.

    This asserted a RANKING -- that the variants inside the window are exactly
    the N smallest scheduled variants -- and that shape has now rotted twice
    for reasons that had nothing to do with the stagger:

      * wahoo (Fedora ELN, `experimental: true`) entered build-config at 2
        flavors and displaced guppy from `smallest`, though it is emitted
        dispatch-only and has no cron to occupy any slot at all. Fixed by
        ranking against SCHEDULED variants only.
      * hummingbird dropped from 5 flavors to 3 when kde and niri were removed
        for having no package set, which made it smaller than guppy and so
        "should" have been in the window. It should not be, and the reason is
        not its size: it fires at 22:20 so the image build follows the day's
        package publish. Moving it into the morning would break that ordering
        to satisfy an arithmetic tie-break.

    A total order over the whole fleet is simply the wrong instrument. Any
    flavor added or removed ANYWHERE re-sorts it, and the test then demands a
    scheduling change that nothing about the contention justifies.

    The hazard is unchanged and is what gets asserted instead: a BIG build
    inside the reserved window queues against daily-verify, verify-asahi,
    matrix-status, catalog-facts and desktop-contract-sweep under the org's
    20-concurrent-job ceiling. That is a question of size against a threshold,
    not of rank. Both guards stay -- how MANY variants sit in the window, and
    how BIG each is -- so the two ways it can be spoiled are still covered.
    """
    counts = flavor_counts()
    low, high = PROVING_WINDOW
    inside = [v for v, (h, _) in scheduled_crons().items() if low <= h < high]

    assert len(inside) <= MAX_IN_PROVING_WINDOW, (
        f"{sorted(inside)} all fire inside the {low:02d}:00-{high:02d}:00 "
        "proving window"
    )
    oversized = {v: counts[v] for v in inside
                 if counts[v] > MAX_FLAVORS_IN_PROVING_WINDOW}
    assert not oversized, (
        f"{oversized} fire inside the {low:02d}:00-{high:02d}:00 proving "
        f"window with more than {MAX_FLAVORS_IN_PROVING_WINDOW} flavors; the "
        "window is reserved for the verification workflows and a fleet-sized "
        "build queues against them under the 20-job ceiling"
    )


def test_the_proving_window_guard_would_notice_a_fleet_build() -> None:
    """The guard above must be able to FAIL, not merely to pass today.

    A threshold test is exactly the shape that quietly stops examining
    anything if the threshold drifts above the fleet. This asserts the
    threshold still sits below the largest scheduled variant, so the guard
    has something it would actually reject.
    """
    counts = flavor_counts()
    scheduled = scheduled_crons()
    heaviest = max(scheduled, key=lambda v: counts[v])
    assert counts[heaviest] > MAX_FLAVORS_IN_PROVING_WINDOW, (
        f"the threshold ({MAX_FLAVORS_IN_PROVING_WINDOW}) is at or above the "
        f"largest scheduled variant ({heaviest} at {counts[heaviest]}), so the "
        "guard cannot fail for any variant and is measuring nothing"
    )


# ── weekly cadence: scheduled runs are thinned, nothing else is ───────────


def _matrix_program() -> str:
    """The jq program in build-variant.yml's Generate Matrix step."""
    text = VARIANT_WORKFLOW.read_text()
    start = text.index("FULL_MATRIX=$(jq -c --arg event ")
    first = text.index("'", start) + 1
    return text[first : text.index("' \"$CONFIG_JSON\"", first)]


def _matrix(event: str, dow: int, variant: str) -> list[dict]:
    jq = shutil.which("jq")
    if jq is None:
        pytest.skip("jq is not installed")
    out = subprocess.run(
        [jq, "-c", "--arg", "event", event, "--argjson", "dow", str(dow),
         _matrix_program(), str(BUILD_CONFIG)],
        env={"FILTER_VARIANT": variant, "FILTER_FLAVOR": "all", "PATH": os.environ["PATH"]},
        capture_output=True, text=True, check=True,
    ).stdout
    return [row for line in out.splitlines() for row in [json.loads(line)]]


def _config() -> dict:
    return {v["id"]: v for v in yaml.safe_load(BUILD_CONFIG.read_text())["variants"]}


def test_a_scheduled_run_builds_hwe_and_isos_only_on_the_weekly_day() -> None:
    variant = _config()["albacore"]
    day = variant["weekly_day"]
    weekly = set(variant["weekly_flavors"])
    other = day % 7 + 1

    on_day = _matrix("schedule", day, "albacore")
    off_day = _matrix("schedule", other, "albacore")

    on_ids = {r["flavor"] for r in on_day}
    off_ids = {r["flavor"] for r in off_day}
    assert weekly & on_ids, "no weekly flavor is built on its weekly day"
    assert not weekly & off_ids, f"weekly flavors built off-day: {sorted(weekly & off_ids)}"
    assert {"base", "gnome"} <= off_ids, "the nightly flavors must build every night"
    assert off_ids <= on_ids, "the weekly day must be a superset of a normal night"
    assert any(r["build_iso"] for r in on_day)
    assert not any(r["build_iso"] for r in off_day)


def test_dispatch_and_pr_runs_are_never_thinned() -> None:
    full = {(r["flavor"], r["build_iso"]) for r in _matrix("workflow_dispatch", 1, "albacore")}
    day = _config()["albacore"]["weekly_day"]
    on_day = {(r["flavor"], r["build_iso"]) for r in _matrix("schedule", day, "albacore")}
    assert full == on_day
    # A PR run keeps only the PR flavors regardless of the weekday.
    assert {r["flavor"] for r in _matrix("pull_request", 1, "albacore")} <= {"gnome", "tuna"}


def test_a_weekly_cron_variant_builds_everything_each_run() -> None:
    for variant in ("guppy", "gurnard", "flounder-sid"):
        ids = {r["flavor"] for r in _matrix("schedule", 1, variant)}
        assert ids == {f["id"] for f in _config()[variant]["flavors"] if f.get("build_image")}


def test_weekly_days_leave_monday_clear_and_split_the_heavy_variants() -> None:
    """Monday carries the weekly boot report; two big variants on one day is
    the 22k-minute-a-day spike this cadence exists to avoid."""
    config = _config()
    days = {v: c["weekly_day"] for v, c in config.items() if "weekly_day" in c}
    assert days, "no variant has a weekly_day, so nothing is thinned"
    assert 1 not in days.values(), f"Monday is reserved: {days}"
    crons = scheduled_weekdays()
    assert "1" not in crons.values(), "a weekly cron fires on Monday"
    heavy = [v for v, c in config.items() if v in days and len(c["flavors"]) >= 15]
    heavy_days = [days[v] for v in heavy]
    assert len(heavy_days) == len(set(heavy_days)), (
        f"heavy variants share a weekly day: { {v: days[v] for v in heavy} }"
    )


def test_a_weekly_variant_is_never_also_nightly_gated() -> None:
    """weekly_day needs a daily cron; a weekly cron already builds everything."""
    weekdays = scheduled_weekdays()
    for variant, config in _config().items():
        if "weekly_day" in config:
            assert weekdays[variant] == "*", f"{variant} has weekly_day but a weekly cron"
