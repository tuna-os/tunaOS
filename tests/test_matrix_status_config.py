#!/usr/bin/env python3
"""Unit tests for the config-loading, network and CLI layers of
gen-matrix-status.py that tests/test_matrix_status.py (drift gate) and
tests/test_matrix_status_fetch.py (gh subprocess fetch/classification) do
not reach.

Covers, per tunaOS#1721:

  * load_build_config's hand-rolled fallback parser — the code path that
    only runs when PyYAML is unavailable, and so is exercised on exactly
    zero normal CI runs even though it silently mirrors PyYAML's behaviour
    for every variant/flavor in the repo.
  * overlay_tags — the one function that talks to the network directly
    (ghcr.io token exchange + tag list), not through the `gh` subprocess.
  * contract_results — subprocess-based artifact download, including the
    "no successful run yet" and "artifact expired" fallbacks.
  * desktop_table — the per-desktop row renderer shared by every section.
  * nvidia_tally's stale-result branch.
  * main()'s --check / --check-structure / default-write dispatch, with
    build() mocked so this exercises argument handling and file I/O only.

Nothing here talks to the real network or a real `gh` — the two doors
outside (urllib.request.urlopen and subprocess.run) are mocked at the
call site, same as tests/test_matrix_status_fetch.py does for gh_json.
"""

import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "gen-matrix-status.py"

_spec = importlib.util.spec_from_file_location("gen_matrix_status", SCRIPT)
gms = importlib.util.module_from_spec(_spec)
sys.modules["gen_matrix_status"] = gms
_spec.loader.exec_module(gms)


# ── load_build_config: the no-PyYAML fallback parser ───────────────────────

CONFIG_TEXT = """\
config:
  global_platforms: ["linux/amd64", "linux/arm64"]

iso_groups:
  - suffix: ""
    flavors: [gnome-nvidia, gnome-nvidia-hwe]
    offline_flavors: [gnome, gnome-hwe, gnome-nvidia, gnome-nvidia-hwe]
  - suffix: community
    publish: false
    flavors: [kde-nvidia, cosmic-nvidia]
    offline_flavors: [kde, cosmic, kde-nvidia, cosmic-nvidia]

variants:
  - id: yellowfin
    emoji: "🐠"
    platforms: ["linux/amd64", "linux/arm64"]
    flavors:
      - id: base
        stage: 1
        build_image: true
        build_iso: false
        build_qcow2: false
      - id: base-nvidia
        platforms: ["linux/amd64"]
        stage: 2
        build_image: true
        build_iso: false
        build_qcow2: false
      - id: gnome
        stage: 2
        build_image: true
        build_iso: true
        build_qcow2: true
"""


class LoadBuildConfigFallbackParser(unittest.TestCase):
    """The hand-rolled parser used when `import yaml` fails.

    Forces the ImportError branch by blanking sys.modules["yaml"] — the
    standard trick for simulating a missing module without actually
    uninstalling PyYAML from the test environment.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.config_path = Path(self.tmp.name) / "build-config.yml"
        self.config_path.write_text(CONFIG_TEXT)

    def _load(self):
        with mock.patch.dict(sys.modules, {"yaml": None}):
            return gms.load_build_config(self.config_path)

    def test_iso_groups_parsed(self):
        cfg = self._load()
        self.assertEqual(len(cfg["iso_groups"]), 2)
        first = cfg["iso_groups"][0]
        self.assertEqual(first["suffix"], "")
        self.assertTrue(first["publish"])  # default when publish: is absent
        self.assertEqual(first["flavors"], ["gnome-nvidia", "gnome-nvidia-hwe"])
        self.assertEqual(
            first["offline_flavors"],
            ["gnome", "gnome-hwe", "gnome-nvidia", "gnome-nvidia-hwe"],
        )

    def test_iso_group_publish_false_is_parsed(self):
        cfg = self._load()
        second = cfg["iso_groups"][1]
        self.assertEqual(second["suffix"], "community")
        self.assertFalse(second["publish"])

    def test_variant_id_and_platforms(self):
        cfg = self._load()
        self.assertEqual(len(cfg["variants"]), 1)
        variant = cfg["variants"][0]
        self.assertEqual(variant["id"], "yellowfin")
        self.assertEqual(variant["platforms"], ["linux/amd64", "linux/arm64"])

    def test_flavor_build_flags(self):
        cfg = self._load()
        flavors = {f["id"]: f for f in cfg["variants"][0]["flavors"]}
        self.assertEqual(len(flavors), 3)
        self.assertTrue(flavors["gnome"]["build_iso"])
        self.assertTrue(flavors["gnome"]["build_qcow2"])
        self.assertFalse(flavors["base"]["build_iso"])
        self.assertFalse(flavors["base"]["build_qcow2"])

    def test_flavor_platform_override(self):
        """base-nvidia overrides the variant-level platforms to amd64-only."""
        cfg = self._load()
        flavors = {f["id"]: f for f in cfg["variants"][0]["flavors"]}
        self.assertEqual(flavors["base-nvidia"]["platforms"], ["linux/amd64"])

    def test_flavor_without_override_inherits_variant_platforms(self):
        cfg = self._load()
        flavors = {f["id"]: f for f in cfg["variants"][0]["flavors"]}
        self.assertEqual(flavors["base"]["platforms"], ["linux/amd64", "linux/arm64"])

    def test_iso_matrix_uses_build_iso(self):
        with mock.patch.object(gms, "load_build_config", return_value=self._load()):
            matrix = gms.iso_matrix()
        # Only `gnome` sets build_iso: true in CONFIG_TEXT.
        self.assertEqual(matrix, {"yellowfin": {"gnome"}})

    def test_matches_pyyaml_on_the_same_input(self):
        """The whole point of the fallback: it must agree with PyYAML.

        Runs the real `import yaml` path (no mocking) against the same file
        and compares the two parses structurally, so a fallback that drifts
        from PyYAML's actual behaviour fails loudly instead of only being
        caught the day PyYAML happens to be missing in production.
        """
        pyyaml_cfg = gms.load_build_config(self.config_path)
        fallback_cfg = self._load()

        self.assertEqual(
            [v["id"] for v in pyyaml_cfg["variants"]],
            [v["id"] for v in fallback_cfg["variants"]],
        )
        py_flavors = {f["id"]: f["build_iso"]
                      for f in pyyaml_cfg["variants"][0]["flavors"]}
        fb_flavors = {f["id"]: f["build_iso"]
                      for f in fallback_cfg["variants"][0]["flavors"]}
        self.assertEqual(py_flavors, fb_flavors)


# ── overlay_tags: the one function that hits the network directly ─────────

class OverlayTagsNetworkLayer(unittest.TestCase):
    """ghcr.io token exchange + tag listing, with digest tags excluded."""

    @staticmethod
    def _resp(payload: dict):
        cm = mock.MagicMock()
        cm.__enter__.return_value = io.BytesIO(json.dumps(payload).encode())
        cm.__exit__.return_value = False
        return cm

    def test_excludes_digest_tags(self):
        token_resp = self._resp({"token": "tok"})
        tags_resp = self._resp({"tags": ["yellowfin-gnome", "sha256-deadbeef"]})
        with mock.patch.object(gms.urllib.request, "urlopen",
                               side_effect=[token_resp, tags_resp]):
            tags = gms.overlay_tags()
        self.assertEqual(tags, {"yellowfin-gnome"})

    def test_no_tags_key_is_empty_set_not_a_crash(self):
        token_resp = self._resp({"token": "tok"})
        tags_resp = self._resp({})
        with mock.patch.object(gms.urllib.request, "urlopen",
                               side_effect=[token_resp, tags_resp]):
            tags = gms.overlay_tags()
        self.assertEqual(tags, set())

    def test_uses_the_bearer_token_from_the_first_call(self):
        token_resp = self._resp({"token": "swordfish"})
        tags_resp = self._resp({"tags": []})
        with mock.patch.object(gms.urllib.request, "urlopen",
                               side_effect=[token_resp, tags_resp]) as urlopen:
            gms.overlay_tags()
        second_call_req = urlopen.call_args_list[1].args[0]
        self.assertEqual(second_call_req.get_header("Authorization"),
                          "Bearer swordfish")


# ── contract_results: subprocess-downloaded artifact ───────────────────────

class ContractResultsArtifactDownload(unittest.TestCase):
    """desktop-contract-sweep.yml's baseline artifact, not job conclusions."""

    def _run(self, status="completed"):
        return {"databaseId": 1, "createdAt": "2026-08-06T00:00:00Z",
                "status": status, "conclusion": "success"}

    def test_reads_verdicts_from_the_downloaded_artifact(self):
        cells = [{"cell": "yellowfin:gnome", "status": "pass"},
                 {"cell": "yellowfin:kde", "status": "fail"}]

        def fake_download(cmd, **kwargs):
            out_dir = Path(cmd[cmd.index("--dir") + 1])
            (out_dir / "all.json").write_text(json.dumps(cells))
            return subprocess.CompletedProcess(cmd, 0)

        with mock.patch.object(gms, "gh_json", return_value=[self._run()]), \
                mock.patch.object(gms.subprocess, "run", side_effect=fake_download):
            got = gms.contract_results()

        self.assertEqual(got["yellowfin:gnome"][0], "pass")
        self.assertEqual(got["yellowfin:kde"][0], "fail")

    def test_non_success_runs_are_skipped(self):
        bad_run = {"databaseId": 1, "createdAt": "2026-08-06T00:00:00Z",
                   "status": "completed", "conclusion": "failure"}
        with mock.patch.object(gms, "gh_json", return_value=[bad_run]), \
                mock.patch.object(gms.subprocess, "run") as run:
            got = gms.contract_results()
        self.assertEqual(got, {})
        run.assert_not_called()

    def test_expired_artifact_falls_through_to_the_next_run(self):
        older_ok = {"databaseId": 1, "createdAt": "2026-08-01T00:00:00Z",
                    "status": "completed", "conclusion": "success"}
        newer_expired = {"databaseId": 2, "createdAt": "2026-08-06T00:00:00Z",
                         "status": "completed", "conclusion": "success"}
        calls = []

        def fake_download(cmd, **kwargs):
            run_id = cmd[cmd.index("run") + 2] if "download" in cmd else None
            calls.append(run_id)
            if run_id == "2":
                raise subprocess.CalledProcessError(1, cmd)
            out_dir = Path(cmd[cmd.index("--dir") + 1])
            (out_dir / "all.json").write_text(
                json.dumps([{"cell": "a:b", "status": "pass"}]))
            return subprocess.CompletedProcess(cmd, 0)

        with mock.patch.object(gms, "gh_json",
                               return_value=[newer_expired, older_ok]), \
                mock.patch.object(gms.subprocess, "run", side_effect=fake_download):
            got = gms.contract_results()

        self.assertEqual(got, {"a:b": ("pass", "2026-08-01", "1")})

    def test_no_runs_at_all_is_an_empty_dict(self):
        with mock.patch.object(gms, "gh_json", return_value=[]):
            self.assertEqual(gms.contract_results(), {})

    def test_download_succeeds_but_artifact_has_no_all_json(self):
        """gh run download can exit 0 without producing all.json (empty
        artifact) — that must fall through to the next run, not KeyError."""
        older_ok = {"databaseId": 1, "createdAt": "2026-08-01T00:00:00Z",
                    "status": "completed", "conclusion": "success"}
        newer_empty = {"databaseId": 2, "createdAt": "2026-08-06T00:00:00Z",
                       "status": "completed", "conclusion": "success"}

        def fake_download(cmd, **kwargs):
            run_id = cmd[cmd.index("run") + 2]
            if run_id == "1":
                out_dir = Path(cmd[cmd.index("--dir") + 1])
                (out_dir / "all.json").write_text(
                    json.dumps([{"cell": "a:b", "status": "pass"}]))
            # run_id == "2": download "succeeds" but writes nothing.
            return subprocess.CompletedProcess(cmd, 0)

        with mock.patch.object(gms, "gh_json",
                               return_value=[newer_empty, older_ok]), \
                mock.patch.object(gms.subprocess, "run", side_effect=fake_download):
            got = gms.contract_results()

        self.assertEqual(got, {"a:b": ("pass", "2026-08-01", "1")})


# ── desktop_table ───────────────────────────────────────────────────────────

class DesktopTableRendering(unittest.TestCase):

    def test_header_lists_every_desktop(self):
        rows = gms.desktop_table({}, {}, lambda v, d: f"{v}:{d}")
        self.assertEqual(rows[0], "| Variant | " + " | ".join(gms.DESKTOPS) + " |")

    def test_one_row_per_variant_in_scope(self):
        matrix = {"yellowfin": {"gnome", "kde"}}
        results = {"yellowfin:gnome": ("success", "2026-08-06", "1")}
        rows = gms.desktop_table(matrix, results, lambda v, d: f"{v}:{d}")
        variant_rows = [r for r in rows if r.startswith("| **")]
        self.assertEqual(len(variant_rows), 1)
        self.assertIn("**yellowfin**", variant_rows[0])

    def test_cell_glyphs_reflect_results(self):
        matrix = {"yellowfin": {"gnome"}}
        results = {"yellowfin:gnome": ("success", "2026-08-06", "1")}
        rows = gms.desktop_table(matrix, results, lambda v, d: f"{v}:{d}")
        row = next(r for r in rows if "yellowfin" in r)
        self.assertIn(gms.PASS, row)


# ── nvidia_tally: the stale-result branch ──────────────────────────────────

class NvidiaTallyStaleResults(unittest.TestCase):

    def test_counts_stale_nvidia_results(self):
        matrix = {"yellowfin": {"gnome-nvidia", "gnome"}}
        results = {"yellowfin:gnome-nvidia": ("success", "2026-08-06", "1")}
        stale = gms.nvidia_tally(matrix, results, lambda v, d: f"{v}:{d}")
        self.assertEqual(stale, 1)

    def test_non_nvidia_flavors_are_not_counted(self):
        matrix = {"yellowfin": {"gnome"}}
        results = {"yellowfin:gnome": ("success", "2026-08-06", "1")}
        stale = gms.nvidia_tally(matrix, results, lambda v, d: f"{v}:{d}")
        self.assertEqual(stale, 0)

    def test_nvidia_flavor_with_no_result_is_not_counted(self):
        matrix = {"yellowfin": {"gnome-nvidia"}}
        stale = gms.nvidia_tally(matrix, {}, lambda v, d: f"{v}:{d}")
        self.assertEqual(stale, 0)


# ── main(): --check / --check-structure / default write ────────────────────

class MainCliDispatch(unittest.TestCase):
    """Argument handling and file I/O, with build() mocked.

    build()'s own orchestration (475-738) composes iso_matrix, luks_matrix,
    latest_results, contract_results, overlay_tags, cell, desktop_table,
    tally, undeclared_tally and nvidia_tally — every one of which has its
    own unit tests above and in test_matrix_status_fetch.py — so mocking it
    here isolates what main() itself is responsible for: reading the
    existing doc, diffing, and choosing an exit code.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.doc = Path(self.tmp.name) / "MATRIX-STATUS.md"

    @staticmethod
    def _wrap(body: str) -> str:
        # build() always returns its own BEGIN/END markers (see build()'s
        # `out = [BEGIN, ..., END]`); main() strips the committed doc's
        # markers via str.split() and rebuilds entirely from what build()
        # returns, so a mock standing in for build() must wrap its body the
        # same way or head/tail reconstruction never matches the file.
        return f"{gms.BEGIN}\n{body}\n{gms.END}"

    def _write_doc(self, body: str):
        self.doc.write_text(f"# Matrix status\n\n{self._wrap(body)}\n")

    def _run_main(self, argv, generated_body="new content"):
        with mock.patch.object(gms, "DOC", self.doc), \
                mock.patch.object(gms, "build", return_value=self._wrap(generated_body)), \
                mock.patch.object(sys, "argv", ["gen-matrix-status.py", *argv]):
            return gms.main()

    def test_missing_doc_exits_nonzero(self):
        missing = Path(self.tmp.name) / "does-not-exist.md"
        with mock.patch.object(gms, "DOC", missing), \
                mock.patch.object(sys, "argv", ["gen-matrix-status.py"]):
            with self.assertRaises(SystemExit):
                gms.main()

    def test_doc_without_markers_exits_nonzero(self):
        self.doc.write_text("no markers here")
        with mock.patch.object(gms, "DOC", self.doc), \
                mock.patch.object(sys, "argv", ["gen-matrix-status.py"]):
            with self.assertRaises(SystemExit):
                gms.main()

    def test_check_returns_zero_when_already_current(self):
        self._write_doc("same content")
        rc = self._run_main(["--check"], generated_body="same content")
        self.assertEqual(rc, 0)

    def test_check_returns_one_when_stale(self):
        self._write_doc("old content")
        rc = self._run_main(["--check"], generated_body="new content")
        self.assertEqual(rc, 1)

    def test_default_mode_writes_the_regenerated_doc(self):
        self._write_doc("old content")
        rc = self._run_main([], generated_body="new content")
        self.assertEqual(rc, 0)
        self.assertIn("new content", self.doc.read_text())

    def test_default_mode_is_a_noop_when_already_current(self):
        self._write_doc("same content")
        before = self.doc.read_text()
        rc = self._run_main([], generated_body="same content")
        self.assertEqual(rc, 0)
        self.assertEqual(self.doc.read_text(), before)

    def test_check_structure_ignores_live_value_changes(self):
        block = "\n| **yellowfin** | ✅ | ⬜ | ⬜ | ⬜ | ⬜ |\n"
        self._write_doc(block)
        # A pure glyph flip is live CI state, not something a PR controls.
        changed_glyphs = "\n| **yellowfin** | ❌ | ⬜ | ⬜ | ⬜ | ⬜ |\n"
        rc = self._run_main(["--check-structure"], generated_body=changed_glyphs)
        self.assertEqual(rc, 0)

    def test_check_structure_still_catches_hand_edits(self):
        block = "\n## LUKS E2E\n\nsome prose\n"
        self._write_doc(block)
        rc = self._run_main(["--check-structure"],
                             generated_body="\n## LUKS E2E\n\ndifferent prose\n")
        self.assertEqual(rc, 1)

    def test_check_and_check_structure_are_mutually_exclusive(self):
        with mock.patch.object(sys, "argv",
                               ["gen-matrix-status.py", "--check", "--check-structure"]):
            with self.assertRaises(SystemExit):
                gms.main()


if __name__ == "__main__":
    unittest.main()
