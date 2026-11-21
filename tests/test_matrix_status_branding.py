"""The Branding axis of docs/MATRIX-STATUS.md: runtime branding per cell.

The Gate job records the image's runtime branding verdict as a step NAMED
`branding: status=<ok|fail|absent> failed=<ids|->` (the `tested-digest:`
carrier convention). gen-matrix-status.py parses it from the scoring run's
Gate, renders a `## Branding` table, and records it in matrix-provenance.json.
It is a reported axis: absent is not tested, never pass, and no branding
verdict moves the composite. No published image prints the markers yet, so
every fixture here is synthetic.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

_spec = importlib.util.spec_from_file_location(
    "gms_branding", SCRIPTS / "gen-matrix-status.py"
)
gms = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gms)

RUN = "https://github.com/tuna-os/tunaOS/actions/runs"


def _job(name, *steps, conclusion="success"):
    return {"name": name, "conclusion": conclusion,
            "steps": [{"name": n, "conclusion": c} for n, c in steps]}


def test_an_ok_step_parses_with_no_failed_ids():
    """`status=ok failed=-` is a passing verdict with an empty id list.

    Falsification: a parser that keeps "-" as an id, or that does not accept
    the ok status, returns something other than {"ok", []} and fails here.
    """
    assert gms.parse_branding_step("branding: status=ok failed=-") == {
        "status": "ok", "failed": []}


def test_a_fail_step_carries_its_failed_check_ids():
    """The contract's check ids, dotted ones included, come back in order.

    Falsification: an id pattern without "." (boot.efi, desktop.gnome.user)
    or a split on anything but "," makes this parse None or mangle the list.
    """
    assert gms.parse_branding_step(
        "branding: status=fail failed=hostname,boot.efi,desktop.gnome.user"
    ) == {"status": "fail", "failed": ["hostname", "boot.efi", "desktop.gnome.user"]}


def test_a_fail_step_without_ids_still_scores_fail():
    """A lost id list must not turn a failure into "no record".

    Falsification: requiring ids on fail returns None here, and the cell
    would then render absent instead of failed.
    """
    assert gms.parse_branding_step("branding: status=fail failed=-") == {
        "status": "fail", "failed": []}


def test_an_absent_step_parses_as_absent():
    """The Gate saw no marker (image predates the checker): status absent.

    Falsification: dropping "absent" from the status alternatives returns
    None here.
    """
    assert gms.parse_branding_step("branding: status=absent failed=-") == {
        "status": "absent", "failed": []}


@pytest.mark.parametrize("name", [
    "branding: status=pass failed=-",          # not a contract status
    "branding: status=ok",                     # no failed field
    "branding:status=ok failed=-",             # missing separator space
    "branding: status=ok failed=hostname",     # ok contradicts a failure
    "branding: status=absent failed=issue",    # absent contradicts a failure
    "branding: status=fail failed=hostname,",  # trailing comma
    "branding: status=fail failed=Host Name",  # not an id
    "branding: status=ok failed=- extra",      # trailing garbage
    f"tested-digest: amd64=sha256:{'a' * 64}",
    "",
    None,
])
def test_a_malformed_step_name_records_nothing(name):
    """Anything outside the grammar is ignored, never guessed at.

    Falsification: a prefix match instead of a full match, or accepting ok
    with failed ids, returns a record for one of these names.
    """
    assert gms.parse_branding_step(name) is None


@pytest.mark.parametrize("conclusion", ["skipped", "failure", "cancelled", None])
def test_a_branding_step_that_did_not_succeed_is_ignored(conclusion):
    """Only a successful step is a record, exactly as for tested-digest.

    Falsification: reading the name regardless of the step conclusion returns
    the ok record here.
    """
    job = _job("build / gnome / Gate", ("branding: status=ok failed=-", conclusion))
    assert gms.step_branding(job) is None


def test_the_successful_branding_step_wins_over_a_skipped_one():
    """A skipped twin step earlier in the list does not hide the real one.

    Falsification: returning on the first `branding:` name, whatever its
    conclusion, yields None (the skipped step) instead of the fail record.
    """
    job = _job("build / gnome / Gate",
               ("branding: status=ok failed=-", "skipped"),
               ("branding: status=fail failed=issue", "success"))
    assert gms.step_branding(job) == {"status": "fail", "failed": ["issue"]}


def test_build_stage_reads_the_branding_step_of_the_scoring_gate(monkeypatch):
    """The collector keeps each cell's Gate branding record from its run.

    Falsification: not reading Gate steps (or reading Promote's) leaves
    stage["branding"] empty, and the kde Gate without a step would wrongly
    gain a record.
    """
    monkeypatch.setattr(gms, "_matrix", lambda key, desktops_only: {"albacore": {"gnome", "kde"}})
    monkeypatch.setattr(gms, "main_runs", lambda workflow, limit=10: [
        {"databaseId": 7, "conclusion": "success", "createdAt": "2026-11-20T00:00:00Z"}])
    monkeypatch.setattr(gms, "run_jobs", lambda run_id: [
        _job("build / gnome / Gate",
             ("Boot and verify", "success"),
             ("branding: status=fail failed=hostname,boot.efi", "success")),
        _job("build / gnome / Promote", ("branding: status=ok failed=-", "success")),
        _job("build / kde / Gate", ("Boot and verify", "success")),
        _job("build / kde / Promote"),
    ])
    stage = gms.build_stage_results()["albacore"]
    assert stage["branding"] == {"gnome": {"status": "fail", "failed": ["hostname", "boot.efi"]}}


def _stage():
    """albacore: gnome ok, kde fail, cosmic Gate ran with no step, niri no
    Gate at all, base ok (outside the desktop columns)."""
    jobs = {(f, "Gate"): "success" for f in ("gnome", "kde", "cosmic", "base")}
    jobs.update({(f, "Promote"): "success" for f in ("gnome", "kde", "cosmic", "base")})
    return {"albacore": {
        "jobs": jobs, "date": "2026-11-20", "run_id": "100",
        "cell_run": {"gnome": ("2026-11-20", "101"), "kde": ("2026-11-20", "102"),
                     "cosmic": ("2026-11-19", "103"), "base": ("2026-11-20", "104")},
        "branding": {"gnome": {"status": "ok", "failed": []},
                     "kde": {"status": "fail", "failed": ["hostname", "desktop.kde.user"]},
                     "base": {"status": "ok", "failed": []}},
    }}


CELLS = [f"albacore:{f}" for f in ("gnome", "kde", "cosmic", "niri", "base")]
DESKTOPS = {"albacore": {"gnome", "kde", "cosmic", "niri"}}


def test_the_section_scores_ok_fail_absent_and_untested_cells():
    """✅ ok and ❌ fail link to their run; absent and untested are both ⬜.

    Falsification: rendering a Gate that ran without a branding step as ✅,
    or dropping the run links, changes the albacore row asserted here.
    """
    lines, records = gms.branding_section(CELLS, DESKTOPS, _stage())
    row = next(line for line in lines if line.startswith("| **albacore** |"))
    assert row == (
        f"| **albacore** | [✅]({RUN}/101#artifacts) | [❌]({RUN}/102#artifacts) "
        f"| [⬜]({RUN}/103#artifacts) | ⬜ | — |"
    )
    assert lines[0] == "## Branding"
    # base is counted, though only desktops have a column.
    assert "**2 of 5** cells pass the runtime branding contract (3 reported, 2 absent or never tested)." in lines
    assert records["albacore:cosmic"]["status"] == "absent"
    assert records["albacore:cosmic"]["verdict"] == "untested"
    assert records["albacore:niri"] == {
        "verdict": "untested", "status": "untested", "failed": [],
        "date": "", "run": "", "evidence": ""}
    assert records["albacore:kde"] == {
        "verdict": "fail", "status": "fail", "failed": ["hostname", "desktop.kde.user"],
        "date": "2026-11-20", "run": f"{RUN}/102", "evidence": f"{RUN}/102#artifacts"}


def test_failed_check_ids_are_named_on_one_masked_line():
    """The failing cell's ids are listed, on a line the PR gate masks.

    Falsification: omitting the ids, or a prefix VOLATILE_LINE does not
    match, fails these asserts (and would break --check-structure whenever a
    cell fails).
    """
    lines, _ = gms.branding_section(CELLS, DESKTOPS, _stage())
    footnote = [line for line in lines if line.startswith("Branding failures: ")]
    assert footnote == [f"Branding failures: [`albacore:kde`]({RUN}/102) (hostname, desktop.kde.user)."]
    assert gms.VOLATILE_LINE.match(footnote[0])


def test_no_branding_verdict_moves_the_composite(monkeypatch):
    """Branding fail and ok render the same composite; provenance records it.

    Falsification: wiring branding into the composite inputs changes the
    composite headline between the two renders, and not merging the records
    leaves provenance without a "branding" axis.
    """
    def render(status, failed):
        inputs = gms.structure_only_inputs()
        stage = _stage()
        stage["albacore"]["branding"]["gnome"] = {"status": status, "failed": failed}
        inputs["stage"] = stage
        return gms.build_pair(inputs)

    ok_block, ok_prov = render("ok", [])
    fail_block, fail_prov = render("fail", ["issue"])
    composite = lambda block: block.split("## Composite green", 1)[1].split("## Silent omissions", 1)[0]  # noqa: E731
    assert composite(ok_block) == composite(fail_block)
    assert ok_prov["albacore:gnome"]["branding"]["verdict"] == "pass"
    assert fail_prov["albacore:gnome"]["branding"]["verdict"] == "fail"
    assert {k: v for k, v in ok_prov["albacore:gnome"].items() if k != "branding"} == \
        {k: v for k, v in fail_prov["albacore:gnome"].items() if k != "branding"}
    assert "## Branding" in fail_block


def test_branding_is_live_state_for_the_pull_request_gate():
    """A scored branding section masks to the same shape as an empty one.

    Falsification: an unmasked failure footnote or unmasked run links make
    the structural comparison differ, so --check-structure would fail on any
    pull request opened after a Gate reported branding.
    """
    live, _ = gms.build_pair({**gms.structure_only_inputs(), "stage": _stage()})
    empty, _ = gms.build_pair(gms.structure_only_inputs())
    rows = gms.table_rows(live) & gms.table_rows(empty)
    assert gms.structural(live, rows) == gms.structural(empty, rows)


def test_absent_branding_is_not_a_never_tested_assertion():
    """The reported axis is tallied, but not counted against the bar.

    Falsification: counting non-criterion axes in never_tested raises it by
    every absent branding cell; dropping the tally loses summary["branding"].
    """
    block, provenance = gms.build_pair(gms.structure_only_inputs())
    without = {cell: {a: r for a, r in axes.items() if a != "branding"}
               for cell, axes in provenance.items()}
    summary = gms.factory_health_summary(provenance, block, full_sweep_dates=[])
    assert summary["never_tested"] == gms.factory_health_summary(
        without, block, full_sweep_dates=[])["never_tested"]
    assert summary["branding"] == {"passed": 0, "tested": 0, "total": len(provenance)}
