#!/usr/bin/env python3
"""Contract tests for the matrix-status GitHub transport boundary."""

import subprocess
import unittest
from unittest import mock

from scripts.matrix_status_github import query_json


class GitHubJsonAdapter(unittest.TestCase):
    def test_returns_decoded_json(self):
        completed = subprocess.CompletedProcess(
            args=["gh"], returncode=0, stdout='{"ok": true}'
        )
        run = mock.Mock(return_value=completed)

        self.assertEqual(query_json(["run", "list"], run=run, sleep=mock.Mock()),
                         {"ok": True})
        run.assert_called_once_with(
            ["gh", "run", "list"], capture_output=True, text=True, check=True
        )

    def test_retries_process_and_payload_failures(self):
        failed = subprocess.CalledProcessError(1, ["gh"])
        malformed = subprocess.CompletedProcess(
            args=["gh"], returncode=0, stdout="not-json"
        )
        succeeded = subprocess.CompletedProcess(
            args=["gh"], returncode=0, stdout="[]"
        )
        run = mock.Mock(side_effect=[failed, malformed, succeeded])
        sleep = mock.Mock()

        self.assertEqual(query_json(["api"], run=run, sleep=sleep), [])
        self.assertEqual(run.call_count, 3)
        self.assertEqual(sleep.call_args_list, [mock.call(2), mock.call(2)])

    def test_returns_none_after_retry_budget_is_exhausted(self):
        run = mock.Mock(side_effect=subprocess.CalledProcessError(1, ["gh"]))
        self.assertIsNone(query_json(["api"], run=run, sleep=mock.Mock()))
        self.assertEqual(run.call_count, 3)

    def test_rejects_an_empty_retry_budget(self):
        with self.assertRaisesRegex(ValueError, "at least 1"):
            query_json(["api"], run=mock.Mock(), sleep=mock.Mock(), attempts=0)


if __name__ == "__main__":
    unittest.main()
