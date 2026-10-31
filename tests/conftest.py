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
import shutil
import textwrap
import time

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
    # Existing compatibility-reader tests must also work in a fresh checkout.
    import importlib.util
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("primary_test_setup", root / "scripts/lib/tunaos_config.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.prepare(root)
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


class FakeClock:
    """`sleep` and `date +%s` on PATH, sharing one virtual clock.

    The retry helpers under test back off with `sleep` and measure their
    deadline with `date +%s`. Waiting those out for real made three cosign
    tests a minute each. Here `sleep N` returns at once, appends N to a log
    and moves the private clock forward by exactly N whole seconds. Calls
    are synchronous: the next `date +%s` sees that advance, while reading
    the clock never advances it or waits for wall time. Every backoff,
    including one after the final attempt, is on record in `sleeps`.
    Only one nonnegative whole-second duration is supported; fractional
    durations fail explicitly rather than being rounded. Other `date`
    invocations are passed unchanged to the real binary.
    The supported operations use Bash builtins, not per-poll Python or cat.
    """

    def __init__(self, root):
        real_date = shutil.which("date")
        assert real_date, "no date(1) on PATH to fall back to"
        self._bash = shutil.which("bash")
        assert self._bash, "no bash on PATH to run fake clock commands"
        self.bin = root / "bin"
        self.bin.mkdir(parents=True)
        self._now = root / "now"
        self._log = root / "sleeps"
        self._now.write_text(f"{int(time.time())}\n")
        self._log.write_text("")
        self._stub("sleep", f"""\
            [[ $# -eq 1 && $1 =~ ^[0-9]+$ ]] || {{
              echo "fake sleep: only whole seconds are faked, got: $*" >&2
              exit 2
            }}
            printf '%s\\n' "$1" >> "{self._log}"
            printf '%s\\n' "$(( $(< "{self._now}") + 10#$1 ))" > "{self._now}"
            """)
        self._stub("date", f"""\
            if [[ $# -eq 1 && $1 == +%s ]]; then
              printf '%s\\n' "$(< "{self._now}")"
            else
              exec "{real_date}" "$@"
            fi
            """)

    def _stub(self, name, body):
        path = self.bin / name
        path.write_text(f"#!{self._bash}\n" + textwrap.dedent(body))
        path.chmod(0o755)

    @property
    def sleeps(self) -> list[int]:
        """Every duration passed to `sleep`, in call order."""
        return [int(line) for line in self._log.read_text().split()]


@pytest.fixture
def fake_clock(tmp_path):
    """A virtual clock: prepend `fake_clock.bin` to a script's PATH."""
    return FakeClock(tmp_path / "fake-clock")
