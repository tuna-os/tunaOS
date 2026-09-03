"""A garbage-collected base image pin must be caught before it costs a night.

Base images are digest-pinned for reproducibility, and upstream registries
garbage-collect untagged manifests. A pin that was valid when written stops
resolving with nothing in this repo changing. The failure then surfaces deep
in a nightly base build as `manifest unknown`, which reads like a broken
Containerfile rather than an expired pin -- and it takes every downstream
flavor of that variant with it.

On 2026-08-16 that cost bonito, bonito-rawhide and sailfin their whole
variants: 24 matrix cells, three base images, one root cause (#1788).

These tests drive `scripts/check-base-image-pins.sh` with a fake `curl` and a
fake `yq`, so they assert the script's actual behaviour without touching the
network -- including the registry quirks that make a wrong request look
exactly like a dead pin.
"""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/check-base-image-pins.sh"
WORKFLOW = ROOT / ".github/workflows/check-base-image-pins.yml"

yaml = pytest.importorskip("yaml")


def _exe(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


def run_check(tmp_path, refs, *, codes=None):
    """Run the script with a stubbed registry.

    `codes` maps a digest substring to the HTTP code the fake curl returns;
    anything unlisted answers 200.
    """
    codes = codes or {}
    bindir = tmp_path / "bin"
    bindir.mkdir()

    _exe(
        bindir / "yq",
        "#!/usr/bin/env bash\n" + "".join(f'echo "{r}"\n' for r in refs),
    )

    # The fake curl records every URL it is asked for, so the test can assert
    # which host the script actually talked to.
    rules = "\n".join(f'  *{frag}*) code={code} ;;' for frag, code in codes.items())
    _exe(
        bindir / "curl",
        f"""#!/usr/bin/env bash
url=""
for a in "$@"; do case "$a" in https://*) url="$a" ;; esac; done
echo "$url" >> "{tmp_path}/urls.txt"
case "$url" in
  *"/token"*|*"/v2/auth"*) echo '{{"token":"faketoken"}}'; exit 0 ;;
esac
code=200
case "$url" in
{rules}
esac
for a in "$@"; do
  if [ "$a" = "%{{http_code}}" ]; then printf '%s' "$code"; exit 0; fi
done
exit 0
""",
    )

    env = dict(os.environ)
    env["PATH"] = f"{bindir}:{env['PATH']}"
    env["YQ"] = str(bindir / "yq")
    env["CONFIG"] = str(tmp_path / "config.yml")
    (tmp_path / "config.yml").write_text("variants: []\n", encoding="utf-8")

    proc = subprocess.run(
        ["bash", str(SCRIPT)], capture_output=True, text=True, env=env, cwd=ROOT
    )
    urls = (tmp_path / "urls.txt").read_text() if (tmp_path / "urls.txt").exists() else ""
    return proc, urls


GOOD = "quay.io/fedora/fedora-bootc:44@sha256:" + "a" * 64
DEAD = "quay.io/fedora/fedora-bootc:44@sha256:" + "b" * 64


def test_a_resolvable_pin_passes(tmp_path):
    proc, _ = run_check(tmp_path, [GOOD])
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "0 unresolvable" in proc.stdout


def test_a_garbage_collected_pin_fails_the_check(tmp_path):
    """This is the whole point: exit non-zero, and name the ref."""
    proc, _ = run_check(tmp_path, [DEAD], codes={"b" * 64: 404})
    assert proc.returncode == 1
    assert "FAIL  404" in proc.stdout
    assert "::error::" in proc.stdout
    assert DEAD in proc.stdout, "the failing ref is not named, so nobody knows what to re-pin"


def test_one_dead_pin_does_not_hide_the_healthy_ones(tmp_path):
    """'Which ones are fine' is as useful as 'which one broke'.

    A check that stops at the first failure would have reported one of the
    three 08-16 breakages and hidden the other two.
    """
    proc, _ = run_check(tmp_path, [GOOD, DEAD], codes={"b" * 64: 404})
    assert proc.returncode == 1
    assert "ok    200" in proc.stdout
    assert "checked 2 digest-pinned base image(s); 1 unresolvable" in proc.stdout


def test_an_unpinned_base_is_reported_rather_than_silently_passed(tmp_path):
    """Not this script's failure, but not something to swallow either."""
    proc, _ = run_check(tmp_path, ["docker.io/library/alpine:latest"])
    assert proc.returncode == 0
    assert "SKIP" in proc.stdout


# ── the registry quirks, each of which otherwise looks like a dead pin ─────


def test_docker_io_is_translated_to_its_real_api_host(tmp_path):
    """`docker.io` is a name, not an API host; manifests live elsewhere.

    Getting this wrong returns 404 and is indistinguishable from a GC'd
    digest -- the check would then condemn a perfectly good pin.
    """
    run_check(tmp_path, ["docker.io/library/debian:trixie@sha256:" + "c" * 64])
    urls = (tmp_path / "urls.txt").read_text()
    assert "registry-1.docker.io/v2/library/debian/manifests" in urls
    assert "https://docker.io/v2/" not in urls


def test_a_registry_needing_no_token_does_not_abort_the_script(tmp_path):
    """`set -e` plus a helper that returns non-zero when it finds no token
    silently killed an earlier version of this script before it printed a
    single line. Exit 1 with no output is the worst possible result: it looks
    like a failing check with nothing to act on.
    """
    proc, _ = run_check(tmp_path, ["registry.opensuse.org/opensuse/tumbleweed:latest@sha256:" + "d" * 64])
    assert proc.returncode == 0
    assert proc.stdout.strip(), "the script produced no output at all"
    assert "ok    200" in proc.stdout


def test_the_manifest_request_accepts_index_and_list_types(tmp_path):
    """Multi-arch tags 404 on content-type grounds if Accept is too narrow."""
    body = SCRIPT.read_text()
    for media in (
        "application/vnd.oci.image.index.v1+json",
        "application/vnd.docker.distribution.manifest.list.v2+json",
    ):
        assert media in body, f"Accept header omits {media}"


# ── it has to actually run on a schedule to be worth anything ─────────────


def _cron_minutes_after_midnight(expr):
    """`m h * * *` -> minutes since 00:00 UTC. Only the daily form is used here."""
    minute, hour = expr.split()[0], expr.split()[1]
    return int(hour) * 60 + int(minute)


def _nightly_build_schedules():
    """Read the real variant-build crons off disk.

    Deliberately derived, not written down. The first version of this test
    hardcoded "the nightly base builds start ~04:00Z" and asserted `hour < 4`.
    The builds actually run at 01:00, so the check shipped at 03:00 -- two
    hours AFTER the thing it exists to protect -- and the test passed anyway,
    because it was checking my assumption rather than the repository.
    """
    out = {}
    for wf in sorted((ROOT / ".github/workflows").glob("build-*.yml")):
        data = yaml.safe_load(wf.read_text())
        if not isinstance(data, dict):
            continue
        sched = (data.get(True) or {}).get("schedule") if isinstance(data.get(True), dict) else None
        if not sched:
            continue
        for entry in sched:
            cron = entry.get("cron", "")
            if len(cron.split()) == 5 and cron.split()[1].isdigit() and cron.split()[0].isdigit():
                out.setdefault(wf.name, []).append(cron)
    return out


def test_the_check_runs_before_the_nightlies():
    """A pin check that runs after the build it was meant to protect is decor.

    The margin matters as much as the order: GitHub's scheduler is not
    punctual. On 2026-08-17 the 01:00 nightlies did not start until 02:17 --
    a 77-minute delay -- so a check scheduled shortly beforehand can still
    lose the race.
    """
    wf = yaml.safe_load(WORKFLOW.read_text())
    crons = [c["cron"] for c in wf[True]["schedule"]]
    assert crons, "no schedule — the check would only ever run by hand"

    nightlies = _nightly_build_schedules()
    assert nightlies, "found no scheduled build-*.yml workflows to compare against"

    earliest_build = min(
        _cron_minutes_after_midnight(c) for crons_ in nightlies.values() for c in crons_
    )
    check_at = min(_cron_minutes_after_midnight(c) for c in crons)

    # Same-day comparison only makes sense if the check is earlier in the day;
    # a check late the previous evening wraps to a negative margin, so measure
    # the gap the way the clock actually runs.
    margin = earliest_build - check_at
    if margin < 0:
        margin += 24 * 60

    # Bounded at BOTH ends. A lower bound alone is not enough: because the
    # gap wraps around midnight, a check that runs two hours *after* the
    # nightly scores 22 hours of "margin" against the following night's run.
    # That is how the 03:00 schedule passed this test while being exactly the
    # thing the test exists to forbid. An upper bound makes it a pre-flight
    # rather than a day-stale reading.
    assert 120 <= margin <= 360, (
        f"pin check fires {margin} min before the earliest nightly build "
        f"(at {earliest_build // 60:02d}:{earliest_build % 60:02d}Z, from "
        f"{sorted(nightlies)[:3]}…). Want 2-6h: enough slack for GitHub's "
        "scheduling delay, close enough that the pins are still current."
    )


def test_the_check_avoids_the_top_of_the_hour():
    """:00 is the most contended minute and attracts the longest queueing."""
    wf = yaml.safe_load(WORKFLOW.read_text())
    minutes = {int(c["cron"].split()[0]) for c in wf[True]["schedule"]}
    assert 0 not in minutes, "scheduled on the hour, where GitHub queues longest"


def test_declared_platforms_are_checked_against_base_architectures():
    """W8 (arch_honesty): declaring an architecture the base image cannot
    provide is a config error caught nightly, not a guaranteed-red cell
    someone diagnoses from build logs (#1755 §3)."""
    body = SCRIPT.read_text(encoding="utf-8")
    assert "arch_honesty" in body
    assert "provides only" in body, "the failure must name what the base has"
    # linux/amd64/v2 is a microarchitecture level of amd64 — it must map to
    # amd64, or every /v2 declaration false-positives.
    assert 'arch="${arch%%/*}"' in body


def test_arch_honesty_failures_fail_the_check():
    body = SCRIPT.read_text(encoding="utf-8")
    assert 'if [ "$arch_failed" -gt 0 ]' in body


def test_arch_honesty_criterion_is_advisory_and_asserted():
    import yaml
    criteria = yaml.safe_load(
        (SCRIPT.parents[1] / ".github" / "green-criteria.yml").read_text()
    )["criteria"]
    c = next(c for c in criteria if c["id"] == "arch_honesty")
    assert c["enforcement"] == "advisory"
    assert "check-base-image-pins" in c["asserted_by"]


# ── the checker itself can be the thing that is broken ─────────────────────


def test_zero_pins_checked_is_a_failure_not_a_pass(tmp_path):
    """A yq expression the pinned yq rejects (`// empty` is jq, and mikefarah
    yq v4.53.3 answers "lexer: invalid input text \"empty\"") fails inside a
    process substitution where `set -e` cannot see it. From the night that
    shipped, the nightly printed "checked 0 digest-pinned base image(s);
    0 unresolvable" and exited 0 while sailfin's garbage-collected pin took
    every sailfin build down on `manifest unknown` (run 33687500544). The
    absence-of-evidence rule applies to the checker: zero checked is red."""
    proc, _ = run_check(tmp_path, [])
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "checked 0 digest-pinned base image(s)" in proc.stdout
    assert "::error::" in proc.stdout
    assert "ZERO" in proc.stdout


def test_an_all_unpinned_config_is_still_read_not_broken(tmp_path):
    """The guard is about the extraction reading nothing, not about the pins
    it read being digest-less: an unpinned base is SKIP (its own test above),
    and one SKIP proves the expression works."""
    proc, _ = run_check(tmp_path, ["docker.io/library/alpine:latest"])
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_the_pin_extraction_uses_no_jq_only_syntax():
    """`empty` is jq. mikefarah yq -- the binary the workflow installs -- has
    no such operator, and the arch-honesty loop in the same script already
    uses the `// ""` form that both accept. Keep the two consistent."""
    body = SCRIPT.read_text()
    assert "// " + "empty" not in body, (
        "the jq `empty` fallback is rejected by the pinned mikefarah yq "
        "(v4.53.3: 'lexer: invalid input text'); use `.base_image // \"\"`"
    )
