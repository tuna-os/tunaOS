#!/usr/bin/env python3
"""A build workflow that is not on main yet has no runs; it is not a failed query.

tunaOS#3884 adds the stingray variant and its build-stingray.yml in the same
pull request. Until it merges, GitHub answers HTTP 404 for the workflow and for
its runs, so the newest-run query returned nothing and gh_json_required raised
"refusing to score the cells it covers as untested". The regenerate check
failed, although "never run on main" is exactly what an untested cell is.

Now a 404 for the workflow itself means no runs; any other failure still raises
(see test_a_failed_run_query_is_not_an_untested_cell.py).

Falsification: behavioural. Make workflow_not_on_main() always return False
and test_a_workflow_not_on_main_has_no_runs raises; make it ignore the status
and test_any_other_failure_still_raises stops raising.
"""

import importlib.util
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "gen-matrix-status.py"

_spec = importlib.util.spec_from_file_location("gen_matrix_status_not_on_main", SCRIPT)
assert _spec and _spec.loader
gms = importlib.util.module_from_spec(_spec)
sys.modules["gen_matrix_status_not_on_main"] = gms
_spec.loader.exec_module(gms)


def _proc(returncode, stderr):
    return subprocess.CompletedProcess([], returncode, stdout="", stderr=stderr)


def _no_listing(*args):
    if args[0] == "api":  # the newest-run query fails
        return None
    raise AssertionError(f"unexpected call {args}")


class AWorkflowNotOnMain(unittest.TestCase):
    def test_a_workflow_not_on_main_has_no_runs(self):
        with mock.patch.object(gms, "gh_json", _no_listing), \
                mock.patch.object(gms, "_gh_run", return_value=_proc(1, "gh: Not Found (HTTP 404)")), \
                mock.patch.object(gms.sys, "stderr"):
            self.assertEqual(gms.main_runs("build-stingray.yml"), [])

    def test_any_other_failure_still_raises(self):
        with mock.patch.object(gms, "gh_json", _no_listing), \
                mock.patch.object(gms, "_gh_run", return_value=_proc(1, "gh: HTTP 502: Server Error")):
            with self.assertRaises(RuntimeError):
                gms.main_runs("build-bonito.yml")

    def test_a_readable_workflow_is_not_probed(self):
        def listing(*args):
            if args[0] == "api":
                return {"workflow_runs": [{"id": 7}]}
            if args[:2] == ("run", "list"):
                return [{"databaseId": 7, "conclusion": "success", "createdAt": "2026-10-29T00:00:00Z"}]
            raise AssertionError(f"unexpected call {args}")

        with mock.patch.object(gms, "gh_json", listing), \
                mock.patch.object(gms, "_gh_run", side_effect=AssertionError("probed a readable workflow")):
            self.assertEqual([r["databaseId"] for r in gms.main_runs("build-bonito.yml")], [7])


if __name__ == "__main__":
    unittest.main()
