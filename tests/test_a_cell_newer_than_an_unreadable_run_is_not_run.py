#!/usr/bin/env python3
"""A cell added after an unreadable build run is not run; an older one refuses.

build_stage_results() skips a build run whose jobs no query can read, and
raises if any configured cell is still unscored, because the skipped run may
have held that cell's verdict. A pull request adding bonito:gnome-x13s met
that refusal behind run 39630438457, whose jobs endpoint answered HTTP 502:
no run on main can hold a verdict for a cell main never configured, yet every
pull request that added a cell was blocked by an unrelated historical run.

The skipped run's commit settles it: a cell that tunaos.toml did not build at
the run's head SHA cannot be in that run, so it is scored not run, with the
reason. A cell that existed then, or whose existence the checkout cannot
answer (no SHA, a commit the clone lacks), still refuses.

Falsification: behavioural. Put back the unconditional `if unreadable and
unscored: raise` and test_a_cell_added_after_the_unreadable_run_is_not_run
raises; drop the existence check and the refusal tests stop raising.
"""

import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "gen-matrix-status.py"

_spec = importlib.util.spec_from_file_location("gen_matrix_status_new_cell", SCRIPT)
gms = importlib.util.module_from_spec(_spec)
sys.modules["gen_matrix_status_new_cell"] = gms
_spec.loader.exec_module(gms)

UNREADABLE, OLDER = "39630438457", "39500000000"


def _flavor(flavor_id, build_image=True):
    return (
        "[[variants.bonito.flavors]]\n"
        f'id = "{flavor_id}"\n'
        "stage = 2\n"
        f"build_image = {'true' if build_image else 'false'}\n"
    )


def _config(*flavors):
    return "[variants]\n\n[variants.bonito]\n" + "".join(flavors)


def _jobs(flavor, promote="success"):
    return [
        {"name": f"🎣-bonito / {flavor} / Promote", "conclusion": promote},
        {"name": f"🎣-bonito / {flavor} / Gate", "conclusion": "success"},
    ]


class _Checkout:
    """A git checkout whose history is the fixture's tunaos.toml revisions."""

    def __init__(self, root: Path):
        self.root = root
        self._git("init", "-q")

    def _git(self, *args):
        env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
               "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
        return subprocess.run(["git", "-C", str(self.root), *args], env=env,
                              check=True, capture_output=True, text=True).stdout.strip()

    def commit(self, config: str) -> str:
        (self.root / "tunaos.toml").write_text(config)
        self._git("add", "tunaos.toml")
        self._git("commit", "-q", "-m", "config")
        return self._git("rev-parse", "HEAD")


class ACellNewerThanAnUnreadableRun(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.checkout = _Checkout(Path(tmp.name))
        # create=True only so this file runs against a generator without the
        # attribute, to show the failure; a missing checkout fails (a) anyway.
        patcher = mock.patch.object(gms, "CHECKOUT", self.checkout.root, create=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        # This pull request's configuration: gnome-x13s is the new cell.
        patcher = mock.patch.object(
            gms, "_matrix", return_value={"bonito": {"gnome", "kde", "gnome-x13s"}})
        patcher.start()
        self.addCleanup(patcher.stop)

    def _results(self, unreadable_sha, views):
        runs = [
            {"databaseId": UNREADABLE, "conclusion": "success",
             "createdAt": "2026-10-29T03:00:00Z", "headSha": unreadable_sha},
            {"databaseId": OLDER, "conclusion": "success",
             "createdAt": "2026-10-28T03:00:00Z", "headSha": "0" * 40},
        ]

        def gh_json(*args):
            if args[:2] == ("api", "--paginate"):
                return None  # the small-page fallback 502s too
            if args[0] == "api":  # main_runs' newest-run cross-check
                return {"workflow_runs": [{"id": UNREADABLE}]}
            if args[:2] == ("run", "list"):
                return runs
            if args[:2] == ("run", "view"):
                return views.get(args[2])
            raise AssertionError(args)

        with mock.patch.object(gms, "gh_json", gh_json), \
                mock.patch.object(gms.sys, "stderr") as stderr:
            got = gms.build_stage_results()["bonito"]
        return got, "".join(c.args[0] for c in stderr.write.call_args_list)

    def test_a_cell_added_after_the_unreadable_run_is_not_run(self):
        sha = self.checkout.commit(_config(_flavor("gnome"), _flavor("kde")))
        got, written = self._results(
            sha, {OLDER: {"jobs": _jobs("gnome") + _jobs("kde", "failure")}})
        self.assertEqual(set(got["not_run"]), {"gnome-x13s"})
        reason = got["not_run"]["gnome-x13s"]
        self.assertIn(UNREADABLE, reason)
        self.assertIn(sha[:12], reason)
        self.assertIn("not configured", reason)
        self.assertIn("gnome-x13s", written)
        # Not run means no verdict: no jobs and no run of its own.
        self.assertNotIn("gnome-x13s", got["cell_run"])
        self.assertNotIn(("gnome-x13s", "Promote"), got["jobs"])
        # The cells that did exist keep their older verdicts.
        self.assertEqual(got["jobs"][("kde", "Promote")], "failure")
        self.assertEqual(got["cell_run"]["gnome"], ("2026-10-28", OLDER))

    def test_a_cell_configured_but_not_built_then_is_not_run(self):
        sha = self.checkout.commit(_config(
            _flavor("gnome"), _flavor("kde"), _flavor("gnome-x13s", build_image=False)))
        got, _ = self._results(sha, {OLDER: {"jobs": _jobs("gnome") + _jobs("kde")}})
        self.assertEqual(set(got["not_run"]), {"gnome-x13s"})

    def test_a_cell_that_existed_at_the_unreadable_run_still_raises(self):
        # kde was built by the unreadable run's commit, and the older run is a
        # GNOME-only dispatch: the skipped run may hold kde's only verdict.
        sha = self.checkout.commit(_config(_flavor("gnome"), _flavor("kde")))
        with self.assertRaises(RuntimeError) as raised:
            self._results(sha, {OLDER: {"jobs": _jobs("gnome")}})
        self.assertIn("kde", str(raised.exception))
        self.assertIn(UNREADABLE, str(raised.exception))
        self.assertNotIn("gnome-x13s", str(raised.exception))

    def test_the_new_cell_raises_when_the_unreadable_run_built_it(self):
        sha = self.checkout.commit(
            _config(_flavor("gnome"), _flavor("kde"), _flavor("gnome-x13s")))
        with self.assertRaises(RuntimeError) as raised:
            self._results(sha, {OLDER: {"jobs": _jobs("gnome") + _jobs("kde")}})
        self.assertIn("gnome-x13s", str(raised.exception))

    def test_a_commit_the_checkout_lacks_still_raises(self):
        self.checkout.commit(_config(_flavor("gnome"), _flavor("kde")))
        with self.assertRaises(RuntimeError) as raised:
            self._results("f" * 40, {OLDER: {"jobs": _jobs("gnome") + _jobs("kde")}})
        self.assertIn("gnome-x13s", str(raised.exception))

    def test_a_run_without_a_head_sha_still_raises(self):
        self.checkout.commit(_config(_flavor("gnome"), _flavor("kde")))
        with self.assertRaises(RuntimeError):
            self._results(None, {OLDER: {"jobs": _jobs("gnome") + _jobs("kde")}})

    def test_readable_runs_score_as_before(self):
        sha = self.checkout.commit(_config(_flavor("gnome"), _flavor("kde")))
        got, _ = self._results(sha, {
            UNREADABLE: {"jobs": _jobs("gnome", "failure")},
            OLDER: {"jobs": _jobs("gnome") + _jobs("kde")},
        })
        self.assertEqual(got["not_run"], {})
        self.assertEqual(got["jobs"], {
            ("gnome", "Promote"): "failure", ("gnome", "Gate"): "success",
            ("kde", "Promote"): "success", ("kde", "Gate"): "success",
        })
        self.assertEqual(got["cell_run"], {
            "gnome": ("2026-10-29", UNREADABLE), "kde": ("2026-10-28", OLDER),
        })
        self.assertEqual((got["date"], got["run_id"]), ("2026-10-29", UNREADABLE))


if __name__ == "__main__":
    unittest.main()
