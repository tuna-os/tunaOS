"""A dnf flag on the wrong side of the subcommand is a silent no-op install.

dnf5 splits its command line into global options and command-scoped options.
`--skip-unavailable` is command-scoped: `dnf -y --skip-unavailable install …`
is not a slightly-odd spelling of `dnf -y install --skip-unavailable …`, it is
a hard usage error that never reaches a repository:

    Unknown argument "--skip-unavailable" for command "dnf5".
    … (It has to be placed after the command.)

That would be a loud, obvious failure except that the hummingbird callers in
install-desktop.sh are written `dnf_retry … || install_available …`. The `||`
caught our own usage error and quietly re-ran the whole desktop package set
through the fallback — which does not honour the manifest's `exclude:` list
and forces `install_weak_deps=False`. So the build stayed green while
shipping a different image than the manifest describes, and burned four
dnf_retry attempts plus 35s of backoff per call getting there.

Observed on Build Hummingbird #66 (run 32907940350), job
`🐦-hummingbird / gnome / linux-amd64`, on all 52 gnome desktop packages.

Two guards here, because either one alone leaves the door open:

  * the placement lint catches the mis-spelling at review time, anywhere in
    the tree, not just at the two sites that were wrong;
  * the dnf_retry behaviour test makes a usage error fail on the FIRST
    attempt and emit a workflow annotation, so the next one is visible in the
    job's annotations even when a caller's `||` swallows the exit code.
"""

import re
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
LIB = REPO / "build_scripts" / "lib.sh"

# Options dnf5 accepts only AFTER the command word. Not an exhaustive list of
# dnf5's command-scoped options — just the ones this repo actually uses, so a
# failure here always names a real line someone wrote.
COMMAND_SCOPED = ("--skip-unavailable", "--skip-broken", "--nobest", "--best")

# Splits a line into the separate simple commands a shell would run.
_SEPARATORS = re.compile(r"\|\||&&|\||;")


def _logical_lines(text):
    """Yield (line_number, joined_text), following backslash continuations.

    The subcommand can sit on the first physical line while the package list
    runs on for another twenty, so judging a physical line in isolation would
    read `dnf -y install --skip-unavailable \\` as having no subcommand.
    """
    pending, start = "", None
    for number, raw in enumerate(text.splitlines(), start=1):
        stripped = raw.strip()
        if start is None:
            start = number
        if stripped.endswith("\\"):
            pending += stripped[:-1] + " "
            continue
        yield start, pending + stripped
        pending, start = "", None
    if pending:
        yield start, pending


def _misplaced_flags(line):
    """Return the command-scoped flags this line puts before its subcommand."""
    if line.lstrip().startswith("#"):
        return []
    found = []
    for segment in _SEPARATORS.split(line):
        tokens = segment.split()
        if not tokens or tokens[0] not in ("dnf", "dnf_retry"):
            continue
        rest = tokens[1:]
        # The subcommand is the first bare word: everything dnf5 takes before
        # it is an option, and every option this repo passes globally is
        # either a flag (-y) or the --opt=value form.
        subcommand = next(
            (i for i, token in enumerate(rest) if not token.startswith("-")), None
        )
        if subcommand is None:
            continue  # no command word on this line — nothing to judge
        for index, token in enumerate(rest[:subcommand]):
            name = token.split("=", 1)[0]
            if name in COMMAND_SCOPED:
                found.append((token, rest[subcommand]))
    return found


def _scan(root):
    bad = []
    for path in sorted(root.rglob("*.sh")):
        text = path.read_text(encoding="utf-8", errors="replace")
        for number, line in _logical_lines(text):
            for flag, subcommand in _misplaced_flags(line):
                bad.append(
                    f"{path.relative_to(REPO)}:{number}: {flag} precedes "
                    f"`{subcommand}` — dnf5 rejects the whole invocation"
                )
    return bad


class CommandScopedFlagPlacement(unittest.TestCase):
    def test_no_shell_script_puts_a_command_scoped_flag_before_the_subcommand(self):
        offenders = _scan(REPO / "build_scripts")
        self.assertEqual(
            offenders,
            [],
            "dnf5 refuses these outright; a caller's `|| fallback` will hide it:\n"
            + "\n".join(offenders),
        )

    def test_the_iso_and_live_scripts_are_covered_too(self):
        for directory in ("live-iso", "iso_files"):
            root = REPO / directory
            if root.is_dir():
                self.assertEqual(_scan(root), [])

    def test_the_lint_actually_recognises_the_shape_it_is_guarding(self):
        """Guard the guard: the exact line from run 32907940350 must trip it.

        Without this, a scanner that silently matched nothing — a typo in the
        flag list, a regex that never fires — would pass the suite above by
        finding zero offenders in a clean tree.
        """
        broken = 'dnf_retry -y --skip-unavailable install "${PKGS[@]}" || install_available "${PKGS[@]}"'
        self.assertEqual(
            _misplaced_flags(broken), [("--skip-unavailable", "install")]
        )

    def test_the_lint_does_not_object_to_correct_placement(self):
        for good in (
            'dnf_retry -y install --skip-unavailable "${PKGS[@]}"',
            'dnf -y --enablerepo="${REPO_ID}" install --skip-unavailable "${PKGS[@]}"',
            # `group install` is a two-word command; the flag follows both.
            "dnf group install -y --skip-unavailable ${OPTS} ${GROUPS}",
            "dnf -y install --skip-broken --setopt=install_weak_deps=False foo",
        ):
            self.assertEqual(_misplaced_flags(good), [], good)

    def test_a_fallback_on_the_right_hand_side_is_not_mistaken_for_the_command(self):
        """`… || install_available "${PKGS[@]}"` must not be parsed as dnf args."""
        line = 'dnf -y install --skip-unavailable a b || install_available a b'
        self.assertEqual(_misplaced_flags(line), [])


class DnfRetryTreatsAUsageErrorAsFinal(unittest.TestCase):
    """Run the real dnf_retry from lib.sh against a fake dnf."""

    @classmethod
    def setUpClass(cls):
        source = LIB.read_text(encoding="utf-8")
        match = re.search(r"^dnf_retry\(\) \{$.*?^\}$", source, re.M | re.S)
        assert match, "dnf_retry() no longer matches the shape this test extracts"
        cls.function = match.group(0)

    def _run(self, stderr_text, exit_code, attempts=4):
        """Invoke dnf_retry with `dnf` stubbed to fail a fixed way."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            counter = tmp / "calls"
            stub = tmp / "dnf"
            stub.write_text(
                "#!/usr/bin/env bash\n"
                # `clean metadata` is dnf_retry's own between-attempt call, not
                # one of the caller's attempts — succeed without counting it.
                'if [[ "$1" == clean ]]; then exit 0; fi\n'
                f'echo x >>"{counter}"\n'
                f"cat <<'EOF'\n{stderr_text}\nEOF\n"
                f"exit {exit_code}\n"
            )
            stub.chmod(0o755)
            script = tmp / "harness.sh"
            script.write_text(
                "#!/usr/bin/env bash\nset -uo pipefail\n"
                # Real backoff is attempt*5 seconds; keep the test fast without
                # editing the function under test.
                "sleep() { :; }\n"
                f"{self.function}\n"
                'dnf_retry -y install --skip-unavailable foo; echo "rc=$?"\n'
            )
            script.chmod(0o755)
            env = {
                "PATH": f"{tmp}:/usr/bin:/bin",
                "DNF_RETRY_ATTEMPTS": str(attempts),
            }
            proc = subprocess.run(
                ["bash", str(script)],
                capture_output=True,
                text=True,
                env=env,
                timeout=60,
            )
            calls = len(counter.read_text().splitlines()) if counter.exists() else 0
            return proc, calls

    USAGE = (
        'Unknown argument "--skip-unavailable" for command "dnf5". '
        'Add "--help" for more information about the arguments.\n'
        "The argument is available for commands: download, install, upgrade. "
        "(It has to be placed after the command.)"
    )

    def test_a_usage_error_is_not_retried(self):
        proc, calls = self._run(self.USAGE, 2)
        self.assertEqual(
            calls,
            1,
            "dnf5 rejected the command line; four attempts see the identical "
            f"rejection.\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}",
        )

    def test_a_usage_error_still_reports_failure_to_the_caller(self):
        proc, _ = self._run(self.USAGE, 2)
        self.assertIn("rc=2", proc.stdout)

    def test_a_usage_error_is_annotated_so_a_swallowing_caller_cannot_hide_it(self):
        proc, _ = self._run(self.USAGE, 2)
        self.assertIn("::error title=dnf invoked incorrectly::", proc.stderr)

    def test_a_transient_failure_is_still_retried_to_the_attempt_limit(self):
        """Guard the guard: the new early return must not swallow real retries."""
        proc, calls = self._run(
            "Curl error (28): Timeout was reached for https://mirror/repodata", 1
        )
        self.assertEqual(calls, 4, proc.stderr)

    def test_an_unresolvable_transaction_is_still_not_retried(self):
        proc, calls = self._run("No match for argument: flatpak", 1)
        self.assertEqual(calls, 1, proc.stderr)


if __name__ == "__main__":
    unittest.main()
