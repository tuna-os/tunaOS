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

import re
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

# `20 13 * * *` -> ("13", "20"); anything else is not a daily slot.
_DAILY_CRON = re.compile(r"^(\d{1,2}) (\d{1,2}) \* \* \*$")
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
    slots: dict[str, tuple[int, int]] = {}
    for path in sorted(WORKFLOWS.glob("build-*.yml")):
        variant = path.stem[len("build-") :]
        if variant in {"variant", "flavor", "toolchain"}:
            continue  # reusable plumbing, not a variant nightly
        doc = yaml.safe_load(path.read_text())
        # PyYAML parses the bare `on:` key as the boolean True.
        triggers = doc.get("on", doc.get(True)) or {}
        schedule = triggers.get("schedule") if isinstance(triggers, dict) else None
        if not schedule:
            continue
        match = _DAILY_CRON.match(schedule[0]["cron"].strip())
        if not match:
            continue  # e.g. the weekly archlinuxarm base rebuild
        minute, hour = match.groups()
        slots[variant] = (int(hour), int(minute))
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


def test_the_proving_window_carries_only_the_smallest_builds() -> None:
    """04:00-09:00 belongs to the verification workflows, not the fleet."""
    counts = flavor_counts()
    low, high = PROVING_WINDOW
    inside = [v for v, (h, _) in scheduled_crons().items() if low <= h < high]
    assert len(inside) <= MAX_IN_PROVING_WINDOW, (
        f"{sorted(inside)} all fire inside the {low:02d}:00-{high:02d}:00 "
        "proving window"
    )
    smallest = sorted(counts, key=lambda v: (counts[v], v))[: len(inside)]
    assert sorted(inside) == sorted(smallest), (
        f"the proving window carries {sorted(inside)}; the smallest builds "
        f"are {sorted(smallest)}"
    )
