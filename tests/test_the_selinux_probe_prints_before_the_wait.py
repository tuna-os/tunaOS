"""The SELinux probe has to print on a machine that cannot be asked anything.

tunaOS#2485: on the two rolling EL10 bases, dbus-broker, systemd-logind and
pam_selinux all fail inside libselinux. The images are identical to albacore's
where the issue looked — dbus_contexts byte-for-byte the same, 0644 root:root,
no security.selinux xattr anywhere in the family — so the labels arrive at
install time and the open question is what they are at runtime.

Nobody has seen them. `scripts/iso-e2e.sh` collects boot diagnostics over SSH,
and sshd cannot open a PAM session without the system bus, so the one image
that could answer is the one that cannot be asked:

    WARNING: guest SSH unavailable; could not collect boot diagnostics

Serial survives all of that. Two properties make the probe useful, and both are
easy to lose in a later edit:

  * it prints ABOVE the settle wait. Everything below that wait is unreachable
    on exactly these images (tunaOS#2514), so a probe below it would describe
    only the machines that were never the problem.
  * it cannot fail the contract. A diagnostic that turns a red boot into a
    differently-red boot has made the gate worse, not better.
"""

import re
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "build_scripts/checks/verify-base-contract.sh"


class TheProbeRunsBeforeAnythingCanBlock(unittest.TestCase):
    def setUp(self):
        self.text = SCRIPT.read_text()
        # Joined: the probe's first echo spans three lines with backslash
        # continuations, and a matcher that reads one line at a time passes
        # against code it was written to reject. That has bitten this suite
        # before (tests/test_the_nvidia_initramfs..., tunaOS#2517).
        self.joined = self.text.replace("\\\n", " ")

    def _index(self, needle):
        i = self.text.find(needle)
        self.assertNotEqual(i, -1, f"{needle!r} is gone from {SCRIPT.name}")
        return i

    def test_it_is_invoked_above_the_settle_wait(self):
        probe = self._index("\n_selinux_probe 2>&1")
        wait = self._index("is-system-running --wait")
        self.assertLess(
            probe, wait,
            "the probe moved below the settle wait; on the images it exists for "
            "the wait times out and nothing below it is reached (tunaOS#2514)")

    def test_it_prints_the_library_version_under_test(self):
        # The one measurement that splits the family: libselinux is 3.10 on
        # albacore, which works, and 3.11 on both variants that fail.
        self.assertIn("libselinux", self.text)
        self.assertRegex(self.joined, r"TUNAOS_SELINUX_PROBE .*lib=")

    def test_it_reports_the_runtime_label_of_the_file_that_fails(self):
        self.assertIn("/etc/selinux/targeted/contexts/dbus_contexts", self.text)
        self.assertRegex(self.joined, r"TUNAOS_SELINUX_PROBE label=")


class TheProbeCannotFailTheContract(unittest.TestCase):
    def setUp(self):
        self.text = SCRIPT.read_text()
        body = re.search(r"_selinux_probe\(\) \{(.*?)\n\}", self.text, re.S)
        self.assertIsNotNone(body, "the probe function is gone")
        self.body = body.group(1)

    def test_the_call_swallows_a_failure(self):
        self.assertIn("_selinux_probe 2>&1 || true", self.text)

    # There was a static test here asserting every `$(...)` ended in `|| echo`.
    # It encoded one spelling of the fallback rather than the property, and it
    # went red the moment a field switched to a `command -v` guard with a
    # `${x:-default}` — a shape that is strictly safer. TheProbeIsRunNotJustRead
    # below checks the same property by running the thing, which is both harder
    # to satisfy accidentally and indifferent to how the fallback is written.

    def test_the_script_does_not_run_under_errexit(self):
        # `set -e` would turn any probe command's non-zero exit into a failed
        # contract before the fallbacks could run.
        self.assertIn("set -uo pipefail", self.text)
        self.assertNotRegex(self.text, r"^set -e|^set -[a-z]*e[a-z]*o")


class TheProbeIsRunNotJustRead(unittest.TestCase):
    """Executed, because the bug this catches is invisible in the source.

    The first spelling ended the matchpathcon field with
    `2>&1 | head -1 || echo unavailable`. Under pipefail that put a shell
    "command not found" message INSIDE the marker line and printed the fallback
    on a second line, so one field became two lines and neither was a
    measurement. Reading the script did not show it. Running it did.
    """

    def _run(self, path_env):
        body = re.search(r"(_selinux_probe\(\) \{.*?\n\})", SCRIPT.read_text(), re.S)
        self.assertIsNotNone(body, "the probe function is gone")
        script = body.group(1) + "\n_selinux_probe 2>&1 || true\n"
        # bash by absolute path: PATH here is the CHILD's lookup path, and
        # /nonexistent is the point of the test, so the interpreter itself
        # cannot be found through it.
        bash = shutil.which("bash") or "/bin/bash"
        return subprocess.run([bash, "-uo", "pipefail", "-c", script],
                              capture_output=True, text=True,
                              env={"PATH": path_env})

    def test_it_exits_zero_with_none_of_its_tools_present(self):
        self.assertEqual(self._run("/nonexistent").returncode, 0)

    def test_every_line_is_one_marker_and_nothing_else(self):
        for path_env in ("/nonexistent", "/usr/bin:/bin"):
            out = self._run(path_env)
            lines = [ln for ln in out.stdout.splitlines() if ln.strip()]
            with self.subTest(path=path_env):
                self.assertTrue(lines, "the probe printed nothing")
                for line in lines:
                    self.assertTrue(
                        line.startswith("TUNAOS_SELINUX_PROBE "),
                        f"stray line in probe output: {line!r}. Every field must "
                        "be one line, or the serial log carries half a fact.")

    def test_it_prints_one_line_per_field(self):
        out = self._run("/nonexistent")
        lines = [ln for ln in out.stdout.splitlines() if ln.strip()]
        self.assertEqual(len(lines), 5, f"expected 5 fields, got: {lines}")


if __name__ == "__main__":
    unittest.main()
