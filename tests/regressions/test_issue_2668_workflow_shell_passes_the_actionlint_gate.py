"""tunaOS#2668: `just check` failed on a clean main from two shell bugs in workflows.

actionlint 1.7.12 with shellcheck 0.11.0 reported findings that are not in the
`-ignore` list in `just/utilities.just`. Both were real defects, not noise:

- desktop-contract-sweep.yml (SC2193): `[[ "${{ matrix.variant }}" ==
  hummingbird* ]]` puts a template expansion inside a shell test. The step
  already exports the value as `$VARIANT`, so the test reads that instead.
- installer-smoke.yml (SC2094): the "no tunaos-live-session journal" check
  was inside the `{ ... } > "$out"` group. Its grep read the file while the
  group was still writing it, and its `::notice::` went into the log file, not
  into the workflow annotations. Also, the bare tag also matched the section
  header that the capture echoes into "$out" on every run, so the notice could
  never fire. It now runs after the group closes and matches the journal's
  `tag[pid]:` form.

Falsification: behavioural for the notice (the real `if` block runs with a log
that holds the header but no journal line, and must print the notice; the old
bare-tag grep prints nothing); structural for the rest — confirmed red by
moving the block back inside the group, which fails the ordering assert, and by
restoring `"${{ matrix.variant }}"`, which fails the template-in-test assert.
"""

import re
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"


def _step(workflow: str, job: str, name: str) -> str:
    doc = yaml.safe_load((WORKFLOWS / workflow).read_text(encoding="utf-8"))
    for s in doc["jobs"][job]["steps"]:
        if name in s.get("name", ""):
            return s["run"]
    raise AssertionError(f"{workflow}: step {name!r} not found in job {job!r}")


def _capture_step() -> str:
    return _step("installer-smoke.yml", "smoke", "Capture installer stderr")


def _notice_block(body: str) -> str:
    m = re.search(r"^if ! grep .*?\"\$out\".*?^fi$", body, re.S | re.M)
    assert m, "the tunaos-live-session notice block is not in the capture step"
    return m.group(0)


def test_the_sweep_does_not_template_expand_inside_a_shell_test():
    body = _step("desktop-contract-sweep.yml", "sweep", "Run the contract")
    offenders = re.findall(r"\[\[[^\]]*\$\{\{[^\]]*\]\]", body)
    assert not offenders, (
        "a ${{ }} expression inside [[ ]] is a constant to shellcheck (SC2193) "
        f"and fails `just check`; use the step's env var: {offenders}"
    )
    assert '[[ "$VARIANT" == hummingbird* ]]' in body
    assert '[[ "$VARIANT" == wahoo* ]]' in body


def test_the_notice_reads_the_log_only_after_it_is_written():
    body = _capture_step()
    group_close = body.index('} > "$out" 2>&1')
    notice = body.index(_notice_block(body))
    assert notice > group_close, (
        'the grep of "$out" runs inside the group that writes "$out" (SC2094), '
        "and its ::notice:: is redirected into the log file"
    )


def _run_notice(tmp_path: Path, log: str) -> str:
    out = tmp_path / "installer-stderr.log"
    out.write_text(log, encoding="utf-8")
    script = f'FLAVOR=xfce\nout="{out}"\n{_notice_block(_capture_step())}\n'
    return subprocess.run(
        ["bash", "-c", script], capture_output=True, text=True, check=True
    ).stdout


def test_the_notice_fires_when_only_the_section_header_mentions_the_tag(tmp_path):
    header = "-- what the session command itself said (tunaos-live-session) --"
    assert header in _capture_step(), "the capture no longer echoes this header"
    log = f"{header}\n-- No entries --\n"
    assert "::notice::xfce: no tunaos-live-session journal" in _run_notice(
        tmp_path, log
    )


def test_the_notice_stays_quiet_when_the_session_journal_is_present(tmp_path):
    log = (
        "-- what the session command itself said (tunaos-live-session) --\n"
        "Sep 24 12:00:01 live tunaos-live-session[1273]: "
        "ERROR xfwl4: Failed to initialize primary GPU node\n"
    )
    assert _run_notice(tmp_path, log) == ""
