#!/usr/bin/env python3
"""The inspector must never hand back a partial file, or a file 14 times over.

scripts/inspect-published-image.py exists because tunaOS#2485 stalled on "the
next step is a `podman run`", and CI's diagnosis environment has no container
runtime. It reads published images over plain HTTPS instead.

The failure mode that makes it dangerous is silent. In a `zstd:chunked` layer a
large file is stored as a `reg` entry followed by trailing `chunk` entries,
each with its own byte range. Read only the `reg` range and the request
succeeds, zstd decompresses cleanly, and you get a plausible file missing its
tail. A 374,034-byte file_contexts measured 49,094 bytes that way, ending
mid-record, and looked exactly like a truncated write in the image — a
complete, wrong answer to #2485 that was one comment away from being filed.

The mirror-image bug followed the fix: acting on every entry find() returns,
chunks included, re-reads the whole file once per chunk. `cat` returned
5,236,476 bytes for that same file, the 374,034 repeated fourteen times.

So: assemble every chunk, and check the result against the size the TOC
declares. Nothing here touches the network.
"""

import importlib.util
import sys
import unittest
from pathlib import Path
from unittest import mock

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "inspect-published-image.py"

_spec = importlib.util.spec_from_file_location("inspect_published_image", SCRIPT)
ipi = importlib.util.module_from_spec(_spec)
sys.modules["inspect_published_image"] = ipi
_spec.loader.exec_module(ipi)

PATH = "etc/selinux/targeted/contexts/files/file_contexts"


def _entries(size):
    """One reg entry plus two chunks, the shape a large file really has."""
    return [
        {"type": "reg", "name": PATH, "size": size, "offset": 0, "endOffset": 10},
        {"type": "chunk", "name": PATH, "offset": 10, "endOffset": 20},
        {"type": "chunk", "name": PATH, "offset": 20, "endOffset": 30},
    ]


class AFileIsItsRegEntryPlusItsChunks(unittest.TestCase):
    def _read(self, entries, size_of_part=b"part"):
        with mock.patch.object(ipi, "blob_range", return_value=b"raw"), \
                mock.patch.object(ipi, "_unzstd", return_value=size_of_part):
            return ipi.toc_read("r", {"digest": "d"}, entries, PATH, "t")

    def test_every_chunk_is_read_not_just_the_first(self):
        self.assertEqual(self._read(_entries(12)), b"part" * 3)

    def test_a_short_read_is_refused_rather_than_returned(self):
        # The #2485 near-miss: declared 12, assembled 4. Returning it would
        # have been a truncated file that looked entirely plausible.
        entries = [_entries(12)[0]]
        with self.assertRaises(SystemExit) as caught:
            self._read(entries)
        self.assertIn("12", str(caught.exception))

    def test_a_long_read_is_refused_too(self):
        # Guards the other direction: over-collecting is as wrong as under-.
        with self.assertRaises(SystemExit):
            self._read(_entries(4))

    def test_chunks_of_a_different_file_are_not_swept_in(self):
        entries = _entries(8)[:2] + [
            {"type": "reg", "name": "etc/other", "offset": 30, "endOffset": 40},
            {"type": "chunk", "name": "etc/other", "offset": 40, "endOffset": 50},
        ]
        self.assertEqual(self._read(entries), b"part" * 2)

    def test_a_second_file_of_the_same_name_ends_the_run(self):
        # Two layers' worth of entries in one list: stop at the second `reg`
        # rather than concatenating both copies of the file.
        entries = _entries(8)[:2] + _entries(8)[:2]
        self.assertEqual(self._read(entries), b"part" * 2)


class TheTableOfContentsIsReadWithoutTheLayer(unittest.TestCase):
    def test_the_annotation_names_the_range_to_fetch(self):
        layer = {"digest": "d", "annotations": {ipi.TOC_POSITION: "100:20:999:1"}}
        with mock.patch.object(ipi, "blob_range", return_value=b"raw") as fetch, \
                mock.patch.object(ipi, "_unzstd", return_value=b'{"entries":[]}'):
            ipi.layer_toc("r", layer, "t")
        # offset and COMPRESSED length — not the uncompressed 999, which would
        # over-read past the end of the blob.
        self.assertEqual(fetch.call_args.args[2:4], (100, 20))

    def test_a_layer_without_the_annotation_has_no_toc(self):
        self.assertIsNone(ipi.layer_toc("r", {"digest": "d"}, "t"))

    def test_entries_absent_or_null_both_mean_nothing_to_walk(self):
        for toc in (None, {}, {"entries": None}):
            with self.subTest(toc=toc):
                self.assertEqual(ipi.toc_entries(toc), [])


class TheRetryExistsBecauseALostLayerLooksLikeAMissingFile(unittest.TestCase):
    def test_a_partial_transfer_is_retried_before_it_becomes_an_answer(self):
        import subprocess
        err = subprocess.CalledProcessError(18, "curl")
        ok = subprocess.CompletedProcess(args=["curl"], returncode=0, stdout=b"body")
        with mock.patch.object(ipi.subprocess, "run", side_effect=[err, ok]) as run, \
                mock.patch.object(ipi.time, "sleep"):
            self.assertEqual(ipi._curl("url", binary=True), b"body")
        self.assertEqual(run.call_count, 2)

    def test_it_gives_up_rather_than_returning_empty(self):
        import subprocess
        err = subprocess.CalledProcessError(18, "curl")
        with mock.patch.object(ipi.subprocess, "run", side_effect=err), \
                mock.patch.object(ipi.time, "sleep"), \
                self.assertRaises(subprocess.CalledProcessError):
            ipi._curl("url")

    def test_a_nonsense_attempt_count_says_so_instead_of_raising_None(self):
        # attempts=0 skips the loop body entirely. The first version ended on
        # `raise last` with last still None, which Python turns into "TypeError:
        # exceptions must derive from BaseException" — an error about the error
        # handler, naming neither the URL nor the real problem.
        with self.assertRaises(ValueError) as caught:
            ipi._curl("url", attempts=0)
        self.assertIn("at least 1", str(caught.exception))

    def test_the_last_failure_keeps_its_own_traceback(self):
        # Re-raised from inside the handler, so the traceback points at the
        # curl call that failed rather than at the bottom of the retry loop.
        import subprocess
        err = subprocess.CalledProcessError(18, "curl")
        with mock.patch.object(ipi.subprocess, "run", side_effect=err), \
                mock.patch.object(ipi.time, "sleep"):
            try:
                ipi._curl("url", attempts=2)
            except subprocess.CalledProcessError as exc:
                self.assertIs(exc.__traceback__.tb_next.tb_frame.f_code,
                              ipi._curl.__code__)


if __name__ == "__main__":
    unittest.main()
