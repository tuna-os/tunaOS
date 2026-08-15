#!/usr/bin/env python3
"""Unit tests for the gh/podman plumbing of scripts/generate-boot-report.py.

tests/python/test_generate_boot_report.py covers the pure report logic
(age_marker, status_emoji, render_report, ...). It never calls the module's
subprocess doors, so the entire API-touching half — gh/gh_json wrappers,
artifact download, workflow/job lookups, the podman wishlist extractor,
screenshot commit/previous-hash, and branch pruning — sat at 0% and the
script at 47% overall.

Everything here mocks subprocess.run at the module level; nothing touches a
network, a `gh` binary, or a container. Mirrors the mocking pattern of
tests/test_matrix_status_fetch.py (mock the only door outside).

The module reads GITHUB_REPOSITORY / REPORT_DATE / PREVIOUS_BRANCH at import
time, so it is loaded via importlib with those env vars set — same as
tests/python/test_generate_boot_report.py.
"""

import base64
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ["GITHUB_REPOSITORY"] = "tuna-os/tunaOS"
os.environ.setdefault("REPORT_DATE", "2026-08-10")
os.environ.setdefault("PREVIOUS_BRANCH", "boot/2026-08-03")

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "generate-boot-report.py"
_spec = importlib.util.spec_from_file_location("generate_boot_report_gh", _SCRIPT)
gbr = importlib.util.module_from_spec(_spec)
sys.modules["generate_boot_report_gh"] = gbr
_spec.loader.exec_module(gbr)


def _completed(stdout: str = "", returncode: int = 0) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=["gh"], returncode=returncode, stdout=stdout)


def _combo() -> gbr.Combo:
    return gbr.Combo(variant="yellowfin", flavor="gnome", build_iso=True, build_qcow2=True)


class TestGhWrapper(unittest.TestCase):
    """The `gh` subprocess wrapper: arg shape, kwargs passthrough."""

    def test_prefixes_command_with_gh(self):
        cp = _completed()
        with mock.patch.object(gbr.subprocess, "run", return_value=cp) as run:
            out = gbr.gh("api", "/repos/x/actions/runs")
        self.assertIs(out, cp)
        self.assertEqual(run.call_args.args[0], ["gh", "api", "/repos/x/actions/runs"])
        self.assertEqual(run.call_args.kwargs["capture_output"], True)
        self.assertEqual(run.call_args.kwargs["text"], True)

    def test_forwards_extra_kwargs(self):
        with mock.patch.object(gbr.subprocess, "run", return_value=_completed()) as run:
            gbr.gh("run", "list", input="{}", check=True)
        self.assertEqual(run.call_args.kwargs.get("input"), "{}")
        self.assertEqual(run.call_args.kwargs.get("check"), True)


class TestGhJson(unittest.TestCase):
    """gh_json: parse stdout, propagate failures."""

    def test_parses_json(self):
        with mock.patch.object(gbr.subprocess, "run",
                               return_value=_completed('{"a": 1}')) as run:
            self.assertEqual(gbr.gh_json("run", "list"), {"a": 1})
        self.assertEqual(run.call_args.args[0][0], "gh")

    def test_nonzero_exit_raises(self):
        bad = _completed("", returncode=1)
        bad.check_returncode = lambda: (_ for _ in ()).throw(
            subprocess.CalledProcessError(1, "gh"))
        with mock.patch.object(gbr.subprocess, "run", return_value=bad):
            with self.assertRaises(subprocess.CalledProcessError):
                gbr.gh_json("run", "list")

    def test_invalid_json_raises(self):
        with mock.patch.object(gbr.subprocess, "run", return_value=_completed("nope")):
            with self.assertRaises(json.JSONDecodeError):
                gbr.gh_json("run", "list")


class TestFetchLatestArtifact(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dest = Path(self._tmp.name)

    def _artifact(self, run_id=7, created="2026-08-09T00:00:00Z"):
        return {"artifacts": [{
            "name": "yellowfin-gnome-boot-screenshot",
            "workflow_run": {"id": run_id},
            "created_at": created,
        }]}

    def test_no_artifacts_returns_none(self):
        with mock.patch.object(gbr.subprocess, "run",
                               return_value=_completed("{}")):
            self.assertIsNone(gbr.fetch_latest_artifact("boot", self.dest))

    def test_download_failure_returns_none(self):
        responses = [_completed(json.dumps(self._artifact())), _completed("", returncode=1)]
        with mock.patch.object(gbr.subprocess, "run", side_effect=responses) as run:
            self.assertIsNone(gbr.fetch_latest_artifact("boot", self.dest))
        # gh run download was attempted
        self.assertIn("download", run.call_args.args[0])

    def test_missing_screenshot_file_returns_none(self):
        responses = [_completed(json.dumps(self._artifact())), _completed()]
        with mock.patch.object(gbr.subprocess, "run", side_effect=responses):
            self.assertIsNone(gbr.fetch_latest_artifact("boot", self.dest))

    def test_success_returns_info(self):
        (self.dest / "yellowfin-gnome-boot-screenshot").mkdir(parents=True)
        (self.dest / "yellowfin-gnome-boot-screenshot" / "screenshot.png").write_bytes(b"png")
        responses = [_completed(json.dumps(self._artifact())), _completed()]
        with mock.patch.object(gbr.subprocess, "run", side_effect=responses) as run:
            info = gbr.fetch_latest_artifact("yellowfin-gnome-boot-screenshot", self.dest)
        self.assertIsNotNone(info)
        self.assertEqual(info["run_id"], 7)
        self.assertEqual(info["created"], "2026-08-09T00:00:00Z")
        self.assertTrue(info["path"].is_file())
        download_args = run.call_args.args[0]
        self.assertIn("--name", download_args)


class TestWorkflowLookups(unittest.TestCase):
    def test_latest_workflow_run_returns_first(self):
        data = {"workflow_runs": [{"id": 1, "conclusion": "success"}]}
        with mock.patch.object(gbr.subprocess, "run",
                               return_value=_completed(json.dumps(data))):
            run = gbr.latest_workflow_run("build-yellowfin.yml")
        self.assertEqual(run["id"], 1)

    def test_empty_runs_returns_none(self):
        with mock.patch.object(gbr.subprocess, "run", return_value=_completed("{}")):
            self.assertIsNone(gbr.latest_workflow_run("build-yellowfin.yml"))

    def test_exception_returns_none(self):
        with mock.patch.object(gbr.subprocess, "run", side_effect=OSError("boom")):
            self.assertIsNone(gbr.latest_workflow_run("build-yellowfin.yml"))

    def test_build_status_for_delegates(self):
        data = {"workflow_runs": [{"id": 3, "conclusion": "failure"}]}
        with mock.patch.object(gbr, "latest_workflow_run",
                               return_value={"id": 3}) as lwr, \
             mock.patch.object(gbr.subprocess, "run",
                               return_value=_completed(json.dumps(data))):
            out = gbr.build_status_for("yellowfin")
        self.assertEqual(out["id"], 3)
        lwr.assert_called_once_with("build-yellowfin.yml")


class TestE2EStatus(unittest.TestCase):
    def setUp(self):
        gbr._E2E_JOBS_CACHE = None

    def _run(self, run_id=9, conclusion="success"):
        return {"id": run_id, "conclusion": conclusion, "html_url": "https://run/9"}

    def _jobs(self, names):
        return {"jobs": [{"name": n, "conclusion": "success", "html_url": f"https://job/{n}"}
                         for n in names]}

    def test_no_run_returns_none(self):
        with mock.patch.object(gbr, "latest_workflow_run", return_value=None):
            self.assertIsNone(gbr.e2e_status_for("yellowfin", "gnome"))

    def test_matching_job_found(self):
        run = self._run()
        with mock.patch.object(gbr, "latest_workflow_run", return_value=run), \
             mock.patch.object(gbr.subprocess, "run",
                               return_value=_completed(json.dumps(
                                   self._jobs(["E2E yellowfin:gnome", "E2E yellowfin:kde"])))):
            out = gbr.e2e_status_for("yellowfin", "gnome")
        self.assertEqual(out["conclusion"], "success")
        self.assertIn("job/E2E yellowfin:gnome", out["html_url"])

    def test_no_matching_job_falls_back_to_run(self):
        run = self._run()
        with mock.patch.object(gbr, "latest_workflow_run", return_value=run), \
             mock.patch.object(gbr.subprocess, "run",
                               return_value=_completed(json.dumps(self._jobs(["E2E bonito:gnome"])))):
            out = gbr.e2e_status_for("yellowfin", "gnome")
        self.assertIs(out, run)

    def test_jobs_fetch_error_falls_back(self):
        run = self._run()
        with mock.patch.object(gbr, "latest_workflow_run", return_value=run), \
             mock.patch.object(gbr.subprocess, "run", side_effect=OSError("boom")):
            out = gbr.e2e_status_for("yellowfin", "gnome")
        self.assertIs(out, run)

    def test_cache_avoids_second_fetch(self):
        run = self._run()
        with mock.patch.object(gbr, "latest_workflow_run", return_value=run), \
             mock.patch.object(gbr.subprocess, "run",
                               return_value=_completed(json.dumps(self._jobs(["E2E yellowfin:gnome"])))) as srun:
            gbr.e2e_status_for("yellowfin", "gnome")
            gbr.e2e_status_for("yellowfin", "gnome")
        # One gh_json fetch total: second call hits the cache.
        self.assertEqual(srun.call_count, 1)


class TestExtractWishlist(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def test_podman_create_failure_returns_empty(self):
        with mock.patch.object(gbr.subprocess, "run",
                               return_value=_completed("", returncode=1)):
            self.assertEqual(gbr.extract_wishlist("yellowfin", "gnome", self.root), [])

    def test_podman_cp_failure_returns_empty(self):
        responses = [_completed("cid123"), _completed("", returncode=1), _completed()]
        with mock.patch.object(gbr.subprocess, "run", side_effect=responses) as run:
            self.assertEqual(gbr.extract_wishlist("yellowfin", "gnome", self.root), [])
        # container is still cleaned up
        self.assertIn("rm", run.call_args.args[0])

    def test_missing_host_file_returns_empty(self):
        responses = [_completed("cid123"), _completed(), _completed()]
        with mock.patch.object(gbr.subprocess, "run", side_effect=responses):
            self.assertEqual(gbr.extract_wishlist("yellowfin", "gnome", self.root), [])

    def test_parses_dedupes_and_strips_comments(self):
        host = self.root / "missing-yellowfin.txt"
        host.write_text("# header\nzlib\nabc\nzlib\n\n  def \n")
        responses = [_completed("cid123"), _completed(), _completed()]
        with mock.patch.object(gbr.subprocess, "run", side_effect=responses):
            names = gbr.extract_wishlist("yellowfin", "gnome", self.root)
        self.assertEqual(names, ["abc", "def", "zlib"])


class TestCommitScreenshot(unittest.TestCase):
    def test_missing_local_file_returns_false(self):
        with mock.patch.object(gbr.subprocess, "run") as run:
            self.assertFalse(gbr.commit_screenshot(Path("/nonexistent.png"), "boot/x.png"))
        run.assert_not_called()

    def test_put_failure_returns_false(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "shot.png"
            p.write_bytes(b"\x89PNG")
            responses = [_completed('"abc123"'), _completed("", returncode=1)]
            with mock.patch.object(gbr.subprocess, "run", side_effect=responses):
                self.assertFalse(gbr.commit_screenshot(p, "boot/2026-08-10/yellowfin-gnome-iso.png"))

    def test_put_success_includes_sha_when_present(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "shot.png"
            p.write_bytes(b"\x89PNG")
            responses = [_completed("abc123"), _completed()]
            with mock.patch.object(gbr.subprocess, "run", side_effect=responses) as run:
                self.assertTrue(gbr.commit_screenshot(p, "boot/2026-08-10/yellowfin-gnome-iso.png"))
            payload = json.loads(run.call_args.kwargs["input"])
            self.assertEqual(payload["sha"], "abc123")
            self.assertEqual(payload["branch"], "screenshots")

    def test_put_success_without_existing_sha(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "shot.png"
            p.write_bytes(b"\x89PNG")
            responses = [_completed("", returncode=1), _completed()]
            with mock.patch.object(gbr.subprocess, "run", side_effect=responses) as run:
                self.assertTrue(gbr.commit_screenshot(p, "boot/2026-08-10/yellowfin-gnome-iso.png"))
            payload = json.loads(run.call_args.kwargs["input"])
            self.assertNotIn("sha", payload)


class TestFetchPreviousHash(unittest.TestCase):
    def _content_entry(self, raw: bytes) -> dict:
        return {"content": base64.b64encode(raw).decode("ascii")}

    def test_no_previous_branch_returns_none(self):
        with mock.patch.object(gbr, "PREVIOUS_BRANCH_PATH", ""):
            with mock.patch.object(gbr.subprocess, "run") as run:
                self.assertIsNone(gbr.fetch_previous_hash("boot/2026-08-10/x.png"))
            run.assert_not_called()

    def test_api_failure_returns_none(self):
        with mock.patch.object(gbr.subprocess, "run", return_value=_completed("", returncode=1)):
            self.assertIsNone(gbr.fetch_previous_hash("boot/2026-08-10/x.png"))

    def test_invalid_json_returns_none(self):
        with mock.patch.object(gbr.subprocess, "run", return_value=_completed("nope")):
            self.assertIsNone(gbr.fetch_previous_hash("boot/2026-08-10/x.png"))

    def test_empty_content_returns_none(self):
        with mock.patch.object(gbr.subprocess, "run",
                               return_value=_completed(json.dumps(self._content_entry(b"")))):
            self.assertIsNone(gbr.fetch_previous_hash("boot/2026-08-10/x.png"))

    def test_returns_sha256_of_decoded_content(self):
        raw = b"\x89PNG-bytes"
        with mock.patch.object(gbr.subprocess, "run",
                               return_value=_completed(json.dumps(self._content_entry(raw)))) as run:
            out = gbr.fetch_previous_hash("boot/2026-08-10/x.png")
        self.assertEqual(out, hashlib.sha256(raw).hexdigest())
        # prev path substituted
        self.assertIn("2026-08-03", run.call_args.args[0][2])


class TestPruneScreenshotsBranch(unittest.TestCase):
    def test_api_failure_returns_silently(self):
        with mock.patch.object(gbr.subprocess, "run", return_value=_completed("", returncode=1)):
            gbr.prune_screenshots_branch()  # must not raise

    def test_invalid_json_returns_silently(self):
        with mock.patch.object(gbr.subprocess, "run", return_value=_completed("nope")):
            gbr.prune_screenshots_branch()

    def test_non_list_returns_silently(self):
        with mock.patch.object(gbr.subprocess, "run", return_value=_completed("{}")):
            gbr.prune_screenshots_branch()

    def _entries(self, names):
        return [{"name": n, "type": "dir"} for n in names] + \
               [{"name": "README.md", "type": "file"}]

    def test_deletes_only_dirs_beyond_keep_weeks(self):
        # 2026-08-10 is newest; keep 4 → delete 2026-08-03 and older, keep
        # 2026-08-10 / 08-09 / 08-08 / 08-07.
        dirs = ["2026-08-10", "2026-08-09", "2026-08-08", "2026-08-07",
                "2026-08-03", "2026-08-02"]
        files = [{"name": "x.png", "type": "file", "sha": "s1"}]
        list_resp = _completed(json.dumps(self._entries(dirs)))
        dir_resp = _completed(json.dumps(files))
        del_resp = _completed()
        responses = [list_resp, dir_resp, del_resp, dir_resp, del_resp]
        with mock.patch.object(gbr.subprocess, "run", side_effect=responses) as run:
            gbr.prune_screenshots_branch(keep_weeks=4)
        deletes = [c.args[0] for c in run.call_args_list
                   if c.args[0][:2] == ["gh", "api"] and "--method" in c.args[0]
                   and c.args[0][c.args[0].index("--method") + 1] == "DELETE"]
        # exactly the two stale dirs' files
        self.assertEqual(len(deletes), 2)
        for d in deletes:
            self.assertIn("2026-08-0", "".join(d))
        self.assertNotIn("2026-08-10", "".join(deletes[0]))


class TestRenderComboRowScreenshots(unittest.TestCase):
    def test_row_with_screenshots_and_change_tags(self):
        combo = _combo()
        now = "2026-08-09T00:00:00Z"
        iso = {"created": now, "url": "https://img/iso", "run_id": 7}
        qcow2 = {"created": now, "url": "https://img/qcow2", "run_id": 8}
        build = {"conclusion": "success", "html_url": "https://run/build"}
        e2e = {"conclusion": "failure", "html_url": "https://run/e2e"}
        row = gbr.render_combo_row(combo, iso, qcow2, True, False, build, e2e)
        self.assertIn("| ISO Boot | QCOW2 Boot |", row)
        self.assertIn("✨ changed", row)
        self.assertIn("= same", row)
        self.assertIn(f"ghcr.io/{gbr.REPO_OWNER}/yellowfin:gnome", row)
        self.assertIn("[run](https://github.com/tuna-os/tunaOS/actions/runs/7)", row)

    def test_row_without_screenshots(self):
        combo = _combo()
        row = gbr.render_combo_row(combo, None, None, None, None, None, None)
        self.assertIn("_no screenshots available for this combo_", row)

    def test_cell_none_is_not_available(self):
        combo = _combo()
        row = gbr.render_combo_row(combo, None, {"created": "N/A", "url": "u", "run_id": 1},
                                   None, None, None, None)
        self.assertIn("_not available_", row)


class TestLoadCombosFallback(unittest.TestCase):
    YAML = """\
variants:
  - id: yellowfin
    flavors:
      - id: gnome
        build_iso: true
        build_qcow2: false
      - id: kde
        build_qcow2: true
      - id: headless
        build_iso: false
        build_qcow2: false
"""

    def _patch_path(self):
        cfg = mock.MagicMock()
        cfg.read_text.return_value = self.YAML
        return mock.patch.object(gbr.pathlib, "Path", return_value=cfg)

    def test_loads_combos_honoring_flags(self):
        with self._patch_path():
            combos = gbr.load_combos()
        self.assertEqual(
            [(c.variant, c.flavor, c.build_iso, c.build_qcow2) for c in combos],
            [("yellowfin", "gnome", True, False),
             ("yellowfin", "kde", False, True)],
        )
        # headless flavor sets neither flag → skipped
        self.assertEqual(len(combos), 2)

    def test_yaml_missing_falls_back_to_pip_install(self):
        def pip_install(cmd, *a, **kw):
            # Simulate a successful pip install making yaml importable again.
            sys.modules.pop("yaml", None)
            return subprocess.CompletedProcess(cmd, 0)

        with self._patch_path(), \
             mock.patch.dict(sys.modules, {"yaml": None}), \
             mock.patch.object(gbr.subprocess, "run", side_effect=pip_install) as run:
            combos = gbr.load_combos()
        self.assertEqual(len(combos), 2)
        self.assertEqual(run.call_args.args[0][:4],
                         [sys.executable, "-m", "pip", "install"])


class TestPruneScreenshotsBranchExtra(unittest.TestCase):
    def test_dir_listing_failure_skips_dir(self):
        dirs = ["2026-08-10", "2026-08-09", "2026-08-08", "2026-08-07",
                "2026-08-02"]
        entries = [{"name": n, "type": "dir"} for n in dirs]
        list_resp = _completed(json.dumps(entries))
        fail_resp = _completed("", returncode=1)
        with mock.patch.object(gbr.subprocess, "run",
                               side_effect=[list_resp, fail_resp]) as run:
            gbr.prune_screenshots_branch(keep_weeks=4)
        # no DELETE issued when the stale dir listing fails
        self.assertNotIn("DELETE", run.call_args.args[0])

    def test_non_file_entries_skipped(self):
        dirs = ["2026-08-10", "2026-08-09", "2026-08-08", "2026-08-07",
                "2026-08-02"]
        entries = [{"name": n, "type": "dir"} for n in dirs]
        dir_contents = [{"name": "subdir", "type": "dir"},
                        {"name": "x.png", "type": "file", "sha": "s1"}]
        list_resp = _completed(json.dumps(entries))
        dir_resp = _completed(json.dumps(dir_contents))
        del_resp = _completed()
        with mock.patch.object(gbr.subprocess, "run",
                               side_effect=[list_resp, dir_resp, del_resp]) as run:
            gbr.prune_screenshots_branch(keep_weeks=4)
        # exactly one DELETE: the file, not the nested dir
        deletes = [c.args[0] for c in run.call_args_list
                   if "--method" in c.args[0] and c.args[0][c.args[0].index("--method") + 1] == "DELETE"]
        self.assertEqual(len(deletes), 1)
        self.assertIn("x.png", " ".join(deletes[0]))


class TestMain(unittest.TestCase):
    def test_full_run_returns_zero(self):
        import io
        combo = _combo()
        with tempfile.TemporaryDirectory() as td:
            work = Path(td) / "work"
            work.mkdir()
            with mock.patch.object(gbr, "load_combos", return_value=[combo]), \
                 mock.patch.object(gbr.tempfile, "mkdtemp", return_value=str(work)), \
                 mock.patch.object(gbr, "build_status_for",
                                   return_value={"conclusion": "success", "html_url": "https://b"}), \
                 mock.patch.object(gbr, "e2e_status_for", return_value=None), \
                 mock.patch.object(gbr, "fetch_latest_artifact", return_value=None), \
                 mock.patch.object(gbr, "extract_wishlist", return_value=[]), \
                 mock.patch.object(gbr, "prune_screenshots_branch") as prune, \
                 mock.patch.object(sys, "stdout", new_callable=io.StringIO) as out, \
                 mock.patch.object(sys, "stderr", new_callable=io.StringIO):
                rc = gbr.main()
        self.assertEqual(rc, 0)
        self.assertIn("yellowfin", out.getvalue())
        self.assertIn("no screenshots available", out.getvalue())
        prune.assert_called_once()


    def test_full_run_with_screenshots_and_prune_error(self):
        import io
        combo = _combo()
        with tempfile.TemporaryDirectory() as td:
            work = Path(td) / "work"
            work.mkdir()
            shot = work / "shot.png"
            shot.write_bytes(b"\x89PNG")
            info = {"path": shot, "created": "2026-08-09T00:00:00Z", "run_id": 7}
            with mock.patch.object(gbr, "load_combos", return_value=[combo]), \
                 mock.patch.object(gbr.tempfile, "mkdtemp", return_value=str(work)), \
                 mock.patch.object(gbr, "build_status_for",
                                   return_value={"conclusion": "success", "html_url": "https://b"}), \
                 mock.patch.object(gbr, "e2e_status_for", return_value=None), \
                 mock.patch.object(gbr, "fetch_latest_artifact", return_value=info), \
                 mock.patch.object(gbr, "commit_screenshot", return_value=True), \
                 mock.patch.object(gbr, "fetch_previous_hash", return_value=None), \
                 mock.patch.object(gbr, "extract_wishlist", return_value=[]), \
                 mock.patch.object(gbr, "prune_screenshots_branch",
                                   side_effect=OSError("boom")) as prune, \
                 mock.patch.object(sys, "stdout", new_callable=io.StringIO) as out, \
                 mock.patch.object(sys, "stderr", new_callable=io.StringIO):
                rc = gbr.main()
        self.assertEqual(rc, 0)
        self.assertIn("| ISO Boot | QCOW2 Boot |", out.getvalue())
        prune.assert_called_once()  # prune raised; main swallowed it


if __name__ == "__main__":
    unittest.main()
