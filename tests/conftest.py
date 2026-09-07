"""Seeded test-order shuffling: `TUNAOS_TEST_SEED=<n> pytest` or `--shuffle`.

Tests in this tree read the same files, spawn the same scripts, and write to
shared paths; a test that passes only because a sibling ran first is a
latent failure waiting for the next reorder. Hive runs its suites in random
order for exactly that reason, and epic #2250 (item 3) asks for the same
here: a nightly lane that randomises execution order and records the seed
so any failure is reproducible with one environment variable.

This is a self-contained plugin rather than pytest-randomly so that the
seed's spelling is stable (`TUNAOS_TEST_SEED`), the reproduction command is
the one printed, and the PR gate needs no extra dependency.

Behaviour:
  * `--shuffle` or a set `TUNAOS_TEST_SEED` enables shuffling. The seed is
    taken from the variable when set, otherwise drawn at random.
  * Order is shuffled at MODULE granularity first, then within each module,
    so fixtures scoped to a module still amortise as intended.
  * The seed is printed in the header and, on failure, in the summary as
    `TUNAOS_TEST_SEED=<n>` — copy that into the environment to reproduce.
  * Without either flag nothing changes; the PR gate keeps its file order.
"""

from __future__ import annotations

import os
import random

import pytest


def pytest_addoption(parser):
    parser.addoption(
        "--shuffle", action="store_true", default=False,
        help="run tests in a seeded random order (seed from TUNAOS_TEST_SEED "
             "or drawn at random and printed)",
    )


def _seed(config) -> int | None:
    raw = os.environ.get("TUNAOS_TEST_SEED")
    if raw:
        try:
            return int(raw)
        except ValueError as e:
            raise pytest.UsageError(f"TUNAOS_TEST_SEED must be an integer, got {raw!r}") from e
    if config.getoption("--shuffle"):
        return random.SystemRandom().randrange(1, 2**31)
    return None


def pytest_configure(config):
    config._tunaos_seed = _seed(config)


def pytest_report_header(config):
    seed = getattr(config, "_tunaos_seed", None)
    if seed is not None:
        return f"shuffled test order, TUNAOS_TEST_SEED={seed}"
    return None


def pytest_collection_modifyitems(config, items):
    seed = getattr(config, "_tunaos_seed", None)
    if seed is None:
        return
    rng = random.Random(seed)
    by_module: dict[str, list] = {}
    for item in items:
        by_module.setdefault(str(item.fspath), []).append(item)
    modules = list(by_module)
    rng.shuffle(modules)
    reordered = []
    for mod in modules:
        group = by_module[mod]
        rng.shuffle(group)
        reordered.extend(group)
    items[:] = reordered


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    seed = getattr(config, "_tunaos_seed", None)
    if seed is None:
        return
    if exitstatus != 0:
        terminalreporter.section("reproduce this order")
        terminalreporter.write_line(
            f"TUNAOS_TEST_SEED={seed} python3 -m pytest tests/ tests/pytest/"
        )
    else:
        terminalreporter.write_line(f"order seed: TUNAOS_TEST_SEED={seed}")
