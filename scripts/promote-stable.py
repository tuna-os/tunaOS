#!/usr/bin/env python3
"""RFC 018: move each cell's :stable (bare) tags to its newest soaked :testing image.

For every cell (variant image path x flavor published_tag, build_image true)
this reads the registry and GitHub, picks the digest the bare (stable) tag
moves to, evaluates the promotion gates and prints one line per cell:

    PROMOTE  every gate passed for the newest soaked :testing digest
    HOLD     a gate held the cell; the reason names the gate
    NOOP     stable already points at that digest, or is ahead of it

Evaluation is read-only. A held cell is data, not an error, so ``evaluate``
exits 0 whenever it could evaluate the cells. With ``--mode promote`` it also
writes a plan file: for each PROMOTE cell, the tags to write, their sources
and the stable digest that was evaluated. ``apply`` reads that plan in a
separate job that may write packages, and copies by digest. ``rollback``
writes the same kind of plan for one cell and one dated tag.

The :testing history is the dated tags Promote writes, ``<tag>-YYYYMMDD``: the
date is the day the digest became the cell's :testing image. Consecutive dated
tags with one digest are one generation, which entered :testing on its oldest
date. Because the tag carries a day and not a time, the soak is measured from
the END of that day: a digest dated D with soak_days N is eligible from
D + N + 1 at 00:00 UTC, so it has always been :testing for at least N days.

Gates for the selected generation (docs/rfc/rfc018-testing-stable-rings.md):
  soak             age >= soak_days (build-config.yml, from tunaos.toml)
  release-blocker  no open issue labelled release-blocker names the cell, by
                   ``variant:flavor`` (or ``image:published_tag``) in the title
                   or by a ``variant/<variant>`` label
  desktop contract the newest desktop-contract-sweep result for the cell is
                   pass (artifact desktop-contract-baseline, all.json)
  lifecycle        no job for the cell failed in the newest scheduled
                   bootc-lifecycle.yml run (job name ``variant:flavor (arch)``)
  Soak-After       every commit between the stable and candidate revisions is
                   scanned for ``Soak-After: <N>d``; the candidate waits for
                   the largest N

A promotion writes, from the candidate's dated tags:
  <tag>-YYYYMMDD         -> <tag>
  <tag>-<arch>-YYYYMMDD  -> <tag>-<arch>, for each platform
  <tag>-YYYYMMDD         -> <alias>:<tag>, for each build-config alias
``apply`` first re-reads the bare tag and every source. If one of them moved
since the evaluation, it skips the cell (compare-and-set). It then checks that
every written tag has its source's digest; a mismatch or a failed copy fails
the run.

Usage:
    scripts/promote-stable.py evaluate [--cell 'albacore:gnome,yellowfin:*']
    scripts/promote-stable.py evaluate --mode promote --plan plan.json
    scripts/promote-stable.py rollback --cell albacore:gnome \\
        --to gnome-20261027 --reason 'boot regression, #1234' [--mode rollback --plan plan.json]
    scripts/promote-stable.py apply --plan plan.json
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, time, timedelta
import fnmatch
import functools
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time as time_module

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.tunaos_config import DEFAULT_SOAK_DAYS  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
BLOCKER_LABEL = "release-blocker"
SWEEP_WORKFLOW = "desktop-contract-sweep.yml"
SWEEP_ARTIFACT = "desktop-contract-baseline"
SWEEP_RUNS = 5
# desktop-contract-sweep.yml sweeps base desktops only (its generate_matrix
# regex); a -hwe/-nvidia/-asahi/... flavor is the same desktop contract, so it
# inherits that desktop's verdict. tests/test_promote_stable.py keeps the two
# lists equal.
SWEPT_DESKTOPS = ("gnome", "kde", "niri", "xfce", "cosmic")
LOOKBACK_DAYS = 30
# scripts/build-image-inner.sh stamps the full build commit here. Images built
# before it did carry the commit only as image.version (Containerfile.final,
# SHA_HEAD_SHORT); accept that when the revision label is absent.
REVISION_LABEL = "org.opencontainers.image.revision"
VERSION_LABEL = "org.opencontainers.image.version"
COMMIT = re.compile(r"[0-9a-f]{7,40}\Z")
SOAK_AFTER = re.compile(r"^Soak-After:[ \t]*([0-9]+)[ \t]*d[ \t]*$", re.I | re.M)
LIFECYCLE_WORKFLOW = "bootc-lifecycle.yml"
LIFECYCLE_JOB = re.compile(r"(?P<cell>[^\s:]+:[^\s:]+) \((?P<arch>[a-z0-9_-]+)\)\Z")
LIFECYCLE_FAILED = ("failure", "timed_out")
COPY_ATTEMPTS = 4
# A copy re-uploads every layer that the destination repository lacks. An
# alias repository can need the whole image, which is several GB.
COPY_TIMEOUT = 3600
MODES = {"evaluate": ("dry-run", "promote"), "rollback": ("dry-run", "rollback")}


class FactError(RuntimeError):
    """A registry or API read failed; the cell is held, never promoted."""


@dataclass(frozen=True)
class Cell:
    variant: str
    flavor: str
    image: str
    tag: str
    platforms: tuple[str, ...]
    aliases: tuple[str, ...]
    soak_days: int

    @property
    def name(self) -> str:
        return f"{self.variant}:{self.flavor}"

    def ref(self, tag: str) -> str:
        return f"{self.image}:{tag}"

    def dated(self, day: date) -> str:
        return f"{self.tag}-{day:%Y%m%d}"

    def stable_writes(self, dated_tag: str) -> list[tuple[str, str]]:
        """(source, destination) refs that move every stable tag of the cell
        to the dated :testing tag ``<tag>-YYYYMMDD``: bare, per-arch, alias."""
        day = dated_tag.removeprefix(f"{self.tag}-")
        registry = self.image.rsplit("/", 1)[0]
        arches = [p.removeprefix("linux/").replace("/", "-") for p in self.platforms]
        source = self.ref(dated_tag)
        return ([(source, self.ref(self.tag))]
                + [(self.ref(f"{self.tag}-{a}-{day}"), self.ref(f"{self.tag}-{a}")) for a in arches]
                + [(source, f"{registry}/{alias}:{self.tag}") for alias in self.aliases])


@dataclass(frozen=True)
class Generation:
    """Consecutive dated tags carrying one digest, newest first."""
    digest: str
    newest: date
    oldest: date
    tag: str


@dataclass(frozen=True)
class Selection:
    decision: str | None          # NOOP/HOLD when final; None = evaluate gates
    reason: str
    candidate: Generation | None
    baseline: str | None          # digest whose revision bounds Soak-After
    ahead: Generation | None      # stable's own generation when it is newer


@dataclass(frozen=True)
class Sweep:
    cells: dict                   # "variant:desktop" -> (status, reason, run_id, day)


@dataclass(frozen=True)
class Lifecycle:
    """The newest scheduled bootc-lifecycle.yml run, per cell."""
    run_id: str
    day: date
    arches: dict                  # "variant:flavor" -> {arch: conclusion}


@dataclass(frozen=True)
class Verdict:
    cell: Cell
    decision: str
    reason: str
    stable: str = ""
    candidate: str = ""
    verdict: str = ""             # the gates' answer when stable is ahead (NOOP)
    stable_digest: str | None = None
    source: Generation | None = None


def eligible_at(entered: date, days: int) -> datetime:
    return datetime.combine(entered + timedelta(days=days + 1), time(0), tzinfo=UTC)


def short(digest: str | None) -> str:
    return digest.split(":", 1)[-1][:12] if digest else "none"


def stamp(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%MZ")


def cells_from_config(config: dict, registry: str) -> list[Cell]:
    cells = []
    for variant in config["variants"]:
        suffix = variant.get("tag_suffix", "")
        image = f"{registry}/{variant.get('publish_name', variant['id'])}"
        for flavor in variant["flavors"]:
            if flavor.get("build_image") is not True:
                continue
            cells.append(Cell(
                variant=variant["id"], flavor=flavor["id"], image=image,
                tag=flavor["id"] + (f"-{suffix}" if suffix else ""),
                platforms=tuple(flavor.get("platforms", variant["platforms"])),
                aliases=tuple(variant.get("aliases", [])),
                soak_days=variant.get("soak_days", DEFAULT_SOAK_DAYS)))
    return cells


def filter_cells(cells: list[Cell], patterns: str) -> list[Cell]:
    wanted = [p.strip() for p in patterns.split(",") if p.strip()]
    if not wanted:
        return cells
    unmatched = [p for p in wanted if not any(fnmatch.fnmatchcase(c.name, p) for c in cells)]
    if unmatched:
        raise SystemExit(f"promote-stable: no build_image cell matches {', '.join(unmatched)}")
    return [c for c in cells if any(fnmatch.fnmatchcase(c.name, p) for p in wanted)]


def generations(cell: Cell, found: list[tuple[date, str]]) -> list[Generation]:
    """Group newest-first (day, digest) probes into generations."""
    out: list[Generation] = []
    for day, digest in found:
        if out and out[-1].digest == digest:
            out[-1] = Generation(digest, out[-1].newest, day, cell.dated(out[-1].newest))
        else:
            out.append(Generation(digest, day, day, cell.dated(day)))
    return out


def soaked(generation: Generation, days: int, now: datetime) -> bool:
    return now >= eligible_at(generation.oldest, days)


def settled(gens: list[Generation], days: int, now: datetime) -> bool:
    """True once more probing cannot change select(): a soaked generation has
    an older one after it, so its entry day and the shadow baseline are known."""
    return any(soaked(g, days, now) for g in gens[:-1])


def select(gens: list[Generation], stable: str | None, days: int, now: datetime) -> Selection:
    if not gens:
        return Selection("HOLD", "no dated :testing tag in the lookback window", None, None, None)
    index = next((i for i, g in enumerate(gens) if soaked(g, days, now)), None)
    stable_index = next((i for i, g in enumerate(gens) if g.digest == stable), None)
    if index is not None and index == stable_index:
        return Selection("NOOP", f"stable already at {gens[index].tag} ({short(stable)}), "
                         "the newest soaked :testing image", gens[index], None, None)
    newest = gens[0]
    wait = (f"soak: newest :testing {newest.tag} entered {newest.oldest}, needs {days}d, "
            f"eligible {stamp(eligible_at(newest.oldest, days))}")
    if stable_index is not None and (index is None or stable_index < index):
        # Stable is newer than the soaked candidate after a manual forward
        # repoint, after Promote bootstrapped a new cell, and on the first
        # runs after RFC 018 phase 3 (Promote wrote the bare tag until then).
        # Moving stable to an older soaked digest would be a rollback, which
        # this never does.
        ahead = gens[stable_index]
        if index is None:
            return Selection("NOOP", wait, None, None, ahead)
        baseline = gens[index + 1].digest if index + 1 < len(gens) else None
        return Selection("NOOP", "", gens[index], baseline, ahead)
    if index is None:
        return Selection("HOLD", wait, None, None, None)
    return Selection(None, "", gens[index], stable, None)


def matching_blockers(cell: Cell, issues: list[dict]) -> list[str]:
    names = {cell.name, f"{cell.image.rsplit('/', 1)[-1]}:{cell.tag}"}
    title = re.compile("|".join(rf"(?<![\w.-]){re.escape(n)}(?![\w.-])" for n in sorted(names)),
                       re.IGNORECASE)
    label = f"variant/{cell.variant}"
    hits = []
    for issue in issues:
        if title.search(issue["title"]):
            hits.append(f"#{issue['number']} (title)")
        elif label in issue["labels"]:
            hits.append(f"#{issue['number']} (label {label})")
    return hits


def sweep_cell(cell: Cell) -> str | None:
    if cell.flavor in SWEPT_DESKTOPS:
        return cell.name
    desktop = cell.flavor.split("-", 1)[0]
    return f"{cell.variant}:{desktop}" if desktop in SWEPT_DESKTOPS else None


def sweep_gate(cell: Cell, sweep: Sweep | None, candidate: Generation) -> tuple[bool, str]:
    key = sweep_cell(cell)
    if key is None:
        return True, "desktop contract n/a (sweep reads base desktops only)"
    via = "" if key == cell.name else f" via {key}"
    if sweep is None:
        return False, "desktop contract: no desktop-contract-baseline artifact with all.json"
    if key not in sweep.cells:
        return False, f"desktop contract: no sweep result for {key}"
    status, why, run_id, day = sweep.cells[key]
    if status != "pass":
        return False, f"desktop contract{via}: {status} ({why}; run {run_id}, {day})"
    if day < candidate.oldest:
        return False, (f"desktop contract{via}: newest result (run {run_id}, {day}) predates "
                       f"{candidate.tag} entering :testing on {candidate.oldest}")
    return True, f"desktop contract{via} pass (run {run_id}, {day})"


def lifecycle_gate(cell: Cell, lifecycle: Lifecycle | None) -> tuple[bool, str]:
    """bootc-lifecycle.yml checks the published bare tag of each non-beta cell,
    one job per arch. A failed job holds the cell; a cell the run did not
    check (beta lane, no scheduled run yet) is n/a, not a hold."""
    if lifecycle is None:
        return True, f"lifecycle: n/a (no completed scheduled {LIFECYCLE_WORKFLOW} run)"
    arches = lifecycle.arches.get(cell.name)
    if not arches:
        return True, f"lifecycle: n/a (cell not in run {lifecycle.run_id})"
    failed = sorted(a for a, conclusion in arches.items() if conclusion in LIFECYCLE_FAILED)
    if failed:
        return False, (f"lifecycle: {', '.join(failed)} failed (run {lifecycle.run_id}, "
                       f"{lifecycle.day})")
    return True, f"lifecycle pass (run {lifecycle.run_id}, {lifecycle.day})"


def soak_after_days(message: str) -> int:
    return max((int(n) for n in SOAK_AFTER.findall(message)), default=0)


def soak_after_gate(trailers: list[tuple[str, int]], candidate: Generation, days: int,
                    now: datetime, scanned: int = 0) -> tuple[bool, str]:
    if not trailers:
        return True, f"no Soak-After trailer in {scanned} commit(s)"
    sha, longest = max(trailers, key=lambda t: t[1])
    if longest <= days:
        return True, f"Soak-After {longest}d ({sha[:7]}) within {days}d soak"
    at = eligible_at(candidate.oldest, longest)
    if now < at:
        return False, f"Soak-After: {sha[:7]} asks {longest}d, eligible {stamp(at)}"
    return True, f"Soak-After {longest}d ({sha[:7]}) served"


def decide(cell: Cell, candidate: Generation, blockers: list[str], sweep: tuple[bool, str],
           lifecycle: tuple[bool, str], soak_after: tuple[bool, str]) -> tuple[str, str]:
    """Combine the gate results for a selected candidate."""
    held = [f"release-blocker: {', '.join(blockers)}"] if blockers else []
    held += [why for ok, why in (sweep, lifecycle, soak_after) if not ok]
    if held:
        return "HOLD", "; ".join(held)
    return "PROMOTE", (f"{candidate.tag} ({short(candidate.digest)}) entered :testing "
                       f"{candidate.oldest}, {cell.soak_days}d soak served; "
                       f"{sweep[1]}; {lifecycle[1]}; {soak_after[1]}")


# ── Registry and GitHub reads ────────────────────────────────────────────────

def run(cmd: list[str], *, binary: bool = False,
        timeout: int = 180) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=False, capture_output=True, text=not binary,
                          timeout=timeout)


def manifest(ref: str) -> tuple[str, dict] | None:
    """(digest, manifest) for ref, or None when the tag does not exist."""
    error = ""
    for attempt in range(3):
        result = run(["skopeo", "inspect", "--raw", f"docker://{ref}"], binary=True)
        if result.returncode == 0:
            digest = "sha256:" + hashlib.sha256(result.stdout).hexdigest()
            return digest, json.loads(result.stdout)
        error = result.stderr.decode(errors="replace").strip()
        if re.search(r"manifest unknown|not found", error, re.IGNORECASE):
            return None
        time_module.sleep(5 * (attempt + 1))
    last = error.splitlines()[-1] if error else "no output"
    raise FactError(f"registry read failed for {ref}: {last}")


def revision(image: str, digest: str, raw: dict) -> str:
    child = digest
    if raw.get("manifests"):
        child = raw["manifests"][0]["digest"]
    result = run(["skopeo", "inspect", "--config", "--raw", f"docker://{image}@{child}"])
    if result.returncode != 0:
        raise FactError(f"cannot read config of {image}@{short(digest)}")
    labels = (json.loads(result.stdout).get("config") or {}).get("Labels") or {}
    value = labels.get(REVISION_LABEL) or labels.get(VERSION_LABEL) or ""
    if not COMMIT.fullmatch(value):
        raise FactError(f"{image}@{short(digest)} has no commit in "
                        f"{REVISION_LABEL} or {VERSION_LABEL}")
    return value


def gh_json(args: list[str]):
    result = run(["gh", *args])
    if result.returncode != 0:
        raise FactError(f"gh {' '.join(args[:2])} failed: {result.stderr.strip()[:200]}")
    return result.stdout


def blocker_issues(repo: str) -> list[dict]:
    out = gh_json(["api", "--paginate",
                   f"repos/{repo}/issues?state=open&labels={BLOCKER_LABEL}&per_page=100",
                   "--jq", (".[] | select(has(\"pull_request\") | not) | "
                            "{number, title, labels: [.labels[].name]}")])
    return [json.loads(line) for line in out.splitlines() if line.strip()]


def latest_sweep(repo: str, wanted: set[str]) -> Sweep | None:
    """Per cell, the newest result across the last few completed sweeps.

    Like scripts/gen-matrix-status.py, a FAILED run is read: the sweep fails
    whenever any cell does, so requiring success would discard every real
    measurement. all.json is uploaded only after the sweep reconciled its
    table, so a run without it is skipped. A filtered manual sweep covers some
    cells only; older runs fill the rest, each result keeping its own date.
    """
    runs = json.loads(gh_json(["run", "list", "--repo", repo, "--workflow", SWEEP_WORKFLOW,
                               "--limit", "10",
                               "--json", "databaseId,createdAt,status,conclusion"]))
    cells: dict = {}
    read = 0
    for item in runs:
        if item["status"] != "completed" or item["conclusion"] not in ("success", "failure"):
            continue
        run_id = str(item["databaseId"])
        with tempfile.TemporaryDirectory() as tmp:
            got = run(["gh", "run", "download", run_id, "--repo", repo, "--name", SWEEP_ARTIFACT,
                       "--dir", tmp])
            path = Path(tmp) / "all.json"
            if got.returncode != 0 or not path.exists():
                continue
            day = date.fromisoformat(item["createdAt"][:10])
            for row in json.loads(path.read_text()):
                cells.setdefault(row["cell"], (row["status"], row.get("reason", ""), run_id, day))
        read += 1
        if wanted <= set(cells) or read >= SWEEP_RUNS:
            break
    return Sweep(cells) if cells else None

def lifecycle_from_jobs(run_id: str, day: date, jobs: list[dict]) -> Lifecycle:
    """Group a lifecycle run's jobs by cell. Beta-lane jobs ("BETA ...") only
    check that a tag exists, so they are not read (as gen-matrix-status.py)."""
    arches: dict = {}
    for job in jobs:
        match = LIFECYCLE_JOB.fullmatch(job.get("name") or "")
        if match:
            arches.setdefault(match["cell"], {})[match["arch"]] = job.get("conclusion") or ""
    return Lifecycle(run_id, day, arches)


def latest_lifecycle(repo: str) -> Lifecycle | None:
    """The newest completed scheduled bootc-lifecycle.yml run. A manual run can
    be filtered to a few cells, so it is not read."""
    runs = json.loads(gh_json(["run", "list", "--repo", repo, "--workflow", LIFECYCLE_WORKFLOW,
                               "--event", "schedule", "--status", "completed", "--limit", "1",
                               "--json", "databaseId,createdAt"]))
    if not runs:
        return None
    run_id = str(runs[0]["databaseId"])
    # per_page=100 on a run of ~150 jobs answered HTTP 502 (2026-10-30); 50 works.
    out = gh_json(["api", "--paginate", f"repos/{repo}/actions/runs/{run_id}/jobs?per_page=50",
                   "--jq", ".jobs[] | {name, conclusion}"])
    jobs = [json.loads(line) for line in out.splitlines() if line.strip()]
    return lifecycle_from_jobs(run_id, date.fromisoformat(runs[0]["createdAt"][:10]), jobs)



@functools.cache
def commit_trailers(base: str, head: str) -> tuple[int, tuple[tuple[str, int], ...]]:
    """(commit count, Soak-After trailers) for commits in head but not base.

    Read from the local clone, not the compare API: main moves hundreds of
    commits a day, and paging that per cell would spend the job token's hourly
    API budget. promote-stable.yml checks out full history (blob:none).
    """
    git = ["git", "-C", str(ROOT)]
    for sha in (base, head):
        if run([*git, "rev-parse", "--verify", "--quiet", f"{sha}^{{commit}}"]).returncode:
            raise FactError(f"commit {sha} is not in the local clone (fetch full history)")
    log = run([*git, "log", "--format=%H%x1f%B%x1e", f"{base}..{head}"])
    if log.returncode:
        raise FactError(f"git log {base}..{head} failed: {log.stderr.strip()[:200]}")
    records = [r.strip() for r in log.stdout.split("\x1e") if r.strip()]
    trailers = []
    for record in records:
        sha, _, message = record.partition("\x1f")
        days = soak_after_days(message)
        if days:
            trailers.append((sha, days))
    return len(records), tuple(trailers)


# ── Evaluation ───────────────────────────────────────────────────────────────

def probe(cell: Cell, now: datetime) -> tuple[list[Generation], dict]:
    found, raws = [], {}
    lookback = max(LOOKBACK_DAYS, cell.soak_days + 7)
    for back in range(lookback + 1):
        day = now.date() - timedelta(days=back)
        got = manifest(cell.ref(cell.dated(day)))
        if got:
            found.append((day, got[0]))
            raws[got[0]] = got[1]
            if settled(generations(cell, found), cell.soak_days, now):
                break
    return generations(cell, found), raws



@dataclass(frozen=True)
class Facts:
    """Lookups shared by every cell. An error string holds every cell."""
    issues: list[dict] | None
    sweep: Sweep | None
    sweep_error: str
    lifecycle: Lifecycle | None
    lifecycle_error: str


def evaluate(cell: Cell, now: datetime, facts: Facts) -> Verdict:
    try:
        stable_got = manifest(cell.ref(cell.tag))
        stable = stable_got[0] if stable_got else None
        gens, raws = probe(cell, now)
        if stable_got:
            raws.setdefault(stable, stable_got[1])
        selection = select(gens, stable, cell.soak_days, now)
        candidate = selection.candidate
        base = dict(cell=cell, stable=short(stable), stable_digest=stable,
                    candidate=f"{candidate.tag} ({short(candidate.digest)})" if candidate else "")
        if selection.decision == "HOLD" or (selection.decision == "NOOP" and not selection.ahead):
            return Verdict(decision=selection.decision, reason=selection.reason, **base)
        ahead = ""
        if selection.ahead:
            # A manual forward repoint, or a cell that Promote bootstrapped
            # with its first image: stable never moves back on a schedule.
            ahead = (f"stable is ahead at {selection.ahead.tag} ({short(stable)}); it moves "
                     "when a newer :testing image has soaked")
            if candidate is None:
                return Verdict(decision="NOOP", reason=ahead,
                               verdict=f"HOLD {selection.reason}", **base)
        if facts.issues is None:
            blockers = ["lookup failed"]
        else:
            blockers = matching_blockers(cell, facts.issues)
        sweep_result = (False, f"desktop contract: {facts.sweep_error}") if facts.sweep_error \
            else sweep_gate(cell, facts.sweep, candidate)
        lifecycle_result = (False, f"lifecycle: {facts.lifecycle_error}") \
            if facts.lifecycle_error else lifecycle_gate(cell, facts.lifecycle)
        try:
            if selection.baseline is None:
                soak_after = (True, "no older stable revision; Soak-After not scanned")
            else:
                head = revision(cell.image, candidate.digest, raws[candidate.digest])
                tail = revision(cell.image, selection.baseline, raws[selection.baseline])
                scanned, trailers = commit_trailers(tail, head)
                soak_after = soak_after_gate(list(trailers), candidate, cell.soak_days, now,
                                             scanned)
        except FactError as exc:
            soak_after = (False, f"Soak-After not checked: {exc}")
        decision, reason = decide(cell, candidate, blockers, sweep_result, lifecycle_result,
                                  soak_after)
        if selection.ahead:
            return Verdict(decision="NOOP", reason=ahead, verdict=f"{decision} {reason}", **base)
        return Verdict(decision=decision, reason=reason, source=candidate, **base)
    except FactError as exc:
        return Verdict(cell=cell, decision="HOLD", reason=f"could not evaluate: {exc}")


# ── Plan and apply ───────────────────────────────────────────────────────────

def plan_entry(cell: Cell, dated_tag: str, digest: str, stable: str | None,
               read=None) -> dict:
    """The writes that move cell's stable tags to dated_tag, with the digest
    each source has now. ``from`` is the stable digest the decision was made
    against; apply skips the cell if the bare tag no longer has it."""
    read = read or manifest
    seen: dict[str, str] = {}
    writes = []
    for source, dest in cell.stable_writes(dated_tag):
        if source not in seen:
            got = read(source)
            if got is None:
                raise FactError(f"{source} does not exist")
            seen[source] = got[0]
        if source == cell.ref(dated_tag) and seen[source] != digest:
            raise FactError(f"{source} is now {short(seen[source])}, not the evaluated "
                            f"{short(digest)}")
        writes.append({"source": source, "digest": seen[source], "dest": dest})
    return {"cell": cell.name, "bare": cell.ref(cell.tag), "from": stable, "to": dated_tag,
            "digest": digest, "writes": writes}


def repository(ref: str) -> str:
    """ghcr.io/o/image:tag -> ghcr.io/o/image."""
    head, _, last = ref.rpartition("/")
    return f"{head}/{last.split(':', 1)[0].split('@', 1)[0]}"


def copy_retry(source: str, dest: str, sleep=time_module.sleep) -> str:
    """skopeo copy --all with retries, like copy_retry in
    reusable-build-image.yml's Promote. Returns "" or the last error."""
    error = ""
    cmd = ["skopeo", "copy", "--all", "--preserve-digests", f"docker://{source}",
           f"docker://{dest}"]
    for attempt in range(1, COPY_ATTEMPTS + 1):
        try:
            result = run(cmd, timeout=COPY_TIMEOUT)
        except subprocess.TimeoutExpired:
            error = f"timed out after {COPY_TIMEOUT}s"
        else:
            if result.returncode == 0:
                return ""
            lines = result.stderr.strip().splitlines()
            error = lines[-1] if lines else f"exit {result.returncode}"
        if attempt < COPY_ATTEMPTS:
            print(f"::warning::copy to {dest} failed (attempt {attempt}/{COPY_ATTEMPTS}): "
                  f"{error}; retrying in {attempt * 15}s", flush=True)
            sleep(attempt * 15)
    return error


def apply_entry(entry: dict, done: str, read=None, copy=None) -> tuple[str, str, list[str]]:
    """(status, detail, written tags) for one plan entry.

    SKIPPED: the bare tag or a source moved since the plan was made, or could
    not be read; nothing was written. FAILED: a copy failed or a written tag
    does not have its source's digest. The bare tag is written last, so a
    failed copy leaves stable where it was and the next run plans it again.
    """
    read = read or manifest
    copy = copy or copy_retry
    try:
        current = read(entry["bare"])
        current = current[0] if current else None
        if current != entry["from"]:
            return "SKIPPED", (f"stable moved from {short(entry['from'])} to {short(current)} "
                               "since the evaluation"), []
        for write in entry["writes"]:
            got = read(write["source"])
            if got is None or got[0] != write["digest"]:
                now = short(got[0]) if got else "missing"
                return "SKIPPED", (f"{write['source']} moved from {short(write['digest'])} to "
                                   f"{now} since the evaluation"), []
    except FactError as exc:
        return "SKIPPED", f"could not re-read the tags: {exc}", []
    ordered = sorted(entry["writes"], key=lambda w: w["dest"] == entry["bare"])
    written = []
    for write in ordered:
        error = copy(f"{repository(write['source'])}@{write['digest']}", write["dest"])
        if error:
            return "FAILED", f"copy to {write['dest']} failed: {error}", written
        written.append(write["dest"])
    wrong = []
    for write in ordered:
        try:
            got = read(write["dest"])
        except FactError as exc:
            wrong.append(f"{write['dest']} unreadable ({exc})")
            continue
        if got is None or got[0] != write["digest"]:
            wrong.append(f"{write['dest']} is {short(got[0]) if got else 'missing'}, "
                         f"expected {short(write['digest'])}")
    if wrong:
        return "FAILED", "digest check: " + "; ".join(wrong), written
    return done, (f"{entry['to']} ({short(entry['digest'])}) verified on "
                  f"{len(written)} tag(s)"), written


def apply_summary(plan: dict, results: list[tuple[dict, str, str, list[str]]]) -> str:
    action = plan["action"]
    rows = [f"## Stable tags written (RFC 018 {action})", ""]
    if plan.get("reason"):
        rows += [f"Reason: {plan['reason']}", ""]
    rows += ["| Cell | From | To | Result | Detail | Tags written |", "|---|---|---|:--:|---|---|"]
    for entry, status, detail, written in results:
        cells = [entry["cell"], f"`{short(entry['from'])}`",
                 f"{entry['to']} (`{short(entry['digest'])}`)", f"**{status}**", detail,
                 ", ".join(f"`{ref.rsplit('/', 1)[-1]}`" for ref in written)]
        rows.append("| " + " | ".join(c.replace("|", "\\|") for c in cells) + " |")
    if not results:
        rows.append("| | | | | Nothing to write. | |")
    return "\n".join(rows) + "\n"


def cmd_apply(args) -> int:
    plan = json.loads(Path(args.plan).read_text())
    done = "ROLLED BACK" if plan["action"] == "rollback" else "PROMOTED"

    def one(entry: dict) -> tuple[dict, str, str, list[str]]:
        status, detail, written = apply_entry(entry, done)
        level = {"FAILED": "::error::", "SKIPPED": "::warning::"}.get(status, "")
        print(f"{level}{status:<11} {entry['cell']:<26} {detail}", flush=True)
        return entry, status, detail, written

    # Cells are independent; every copy within one cell stays in order.
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        results = list(pool.map(one, plan["cells"]))
    if args.summary:
        with open(args.summary, "a", encoding="utf-8") as handle:
            handle.write(apply_summary(plan, results))
    return 1 if any(status == "FAILED" for _, status, _, _ in results) else 0


# ── Report ───────────────────────────────────────────────────────────────────

def line(v: Verdict) -> str:
    text = f"{v.decision:<7} {v.cell.name:<26} {v.reason}"
    return text + (f" | gate verdict: {v.verdict}" if v.verdict else "")


def summary(verdicts: list[Verdict], now: datetime, mode: str, notes: dict[str, str]) -> str:
    counts = {d: sum(v.decision == d for v in verdicts) for d in ("PROMOTE", "HOLD", "NOOP")}
    outcome = ("Dry run: nothing was copied or tagged." if mode == "dry-run" else
               "The PROMOTE cells are handed to the Write stable tags job.")
    rows = [f"## Stable promotion (RFC 018, {mode})", "",
            (f"Evaluated {stamp(now)} for {len(verdicts)} cell(s): {counts['PROMOTE']} PROMOTE, "
             f"{counts['HOLD']} HOLD, {counts['NOOP']} NOOP. {outcome}"), ""]
    rows += [f"- {name}: {note}" for name, note in notes.items()]
    rows += ["", "| Cell | Soak | Stable (bare) | Candidate | Decision | Reason | Gate verdict |",
             "|---|--:|---|---|:--:|---|---|"]
    for v in verdicts:
        cells = [v.cell.name, f"{v.cell.soak_days}d", f"`{v.stable}`" if v.stable else "",
                 v.candidate, f"**{v.decision}**", v.reason, v.verdict or v.decision]
        rows.append("| " + " | ".join(c.replace("|", "\\|") for c in cells) + " |")
    return "\n".join(rows) + "\n"


def write_plan(path: str, plan: dict) -> None:
    Path(path).write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")


def load_cells(args) -> list[Cell]:
    config = json.loads(Path(args.config).read_text())
    return filter_cells(cells_from_config(config, args.registry), args.cell)


def gather_facts(repo: str, cells: list[Cell]) -> tuple[Facts, dict[str, str]]:
    try:
        issues = blocker_issues(repo)
        blocker_note = f"{len(issues)} open labelled {BLOCKER_LABEL}"
    except FactError as exc:
        issues, blocker_note = None, f"lookup failed ({exc}); every cell holds"
    wanted = {key for key in map(sweep_cell, cells) if key}
    sweep, sweep_error = None, ""
    try:
        sweep = latest_sweep(repo, wanted) if wanted else Sweep({})
        runs = sorted({row[2] for row in sweep.cells.values()}) if sweep else []
        sweep_note = f"results from run(s) {', '.join(runs)}" if runs else "no usable artifact"
    except FactError as exc:
        sweep_error = f"sweep lookup failed ({exc})"
        sweep_note = sweep_error
    lifecycle, lifecycle_error = None, ""
    try:
        lifecycle = latest_lifecycle(repo)
        lifecycle_note = (f"scheduled run {lifecycle.run_id} ({lifecycle.day})" if lifecycle
                          else "no completed scheduled run; every cell is n/a")
    except FactError as exc:
        lifecycle_error = f"lookup failed ({exc})"
        lifecycle_note = f"{lifecycle_error}; every cell holds"
    facts = Facts(issues, sweep, sweep_error, lifecycle, lifecycle_error)
    return facts, {"release-blocker issues": blocker_note, "desktop-contract-sweep": sweep_note,
                   LIFECYCLE_WORKFLOW: lifecycle_note}


def planned(verdict: Verdict) -> tuple[Verdict, dict | None]:
    """A PROMOTE verdict and its plan entry; HOLD if a source cannot be read."""
    if verdict.decision != "PROMOTE":
        return verdict, None
    try:
        entry = plan_entry(verdict.cell, verdict.source.tag, verdict.source.digest,
                           verdict.stable_digest)
    except FactError as exc:
        return replace(verdict, decision="HOLD", reason=f"could not plan: {exc}"), None
    return verdict, entry


def cmd_evaluate(args) -> int:
    now = args.now
    cells = load_cells(args)
    facts, notes = gather_facts(args.repo, cells)
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        verdicts = list(pool.map(lambda c: evaluate(c, now, facts), cells))
        entries: list[dict] = []
        if args.mode == "promote":
            pairs = list(pool.map(planned, verdicts))
            verdicts = [verdict for verdict, _ in pairs]
            entries = [entry for _, entry in pairs if entry]
    for verdict in verdicts:
        print(line(verdict), flush=True)
    if args.mode == "promote":
        write_plan(args.plan, {"action": "promote", "cells": entries})
    if args.summary:
        with open(args.summary, "a", encoding="utf-8") as handle:
            handle.write(summary(verdicts, now, args.mode, notes))
    return 0


def cmd_rollback(args) -> int:
    reason = args.reason.strip()
    if not reason:
        raise SystemExit("promote-stable: rollback needs a non-empty --reason")
    cells = [c for c in load_cells(args) if c.name == args.cell]
    if len(cells) != 1:
        raise SystemExit(f"promote-stable: rollback needs exactly one cell, not {args.cell!r}")
    cell = cells[0]
    match = re.fullmatch(re.escape(cell.tag) + r"-([0-9]{8})", args.to)
    try:
        datetime.strptime(match.group(1) if match else "", "%Y%m%d")
    except ValueError:
        raise SystemExit(f"promote-stable: --to must be a dated tag {cell.tag}-YYYYMMDD "
                         f"of {cell.name}") from None
    target = manifest(cell.ref(args.to))
    if target is None:
        raise SystemExit(f"promote-stable: {cell.ref(args.to)} does not exist")
    current = manifest(cell.ref(cell.tag))
    current_digest = current[0] if current else None
    entries = []
    if current_digest == target[0]:
        text = f"NOOP    {cell.name:<26} stable already at {args.to} ({short(target[0])})"
    else:
        try:
            entry = plan_entry(cell, args.to, target[0], current_digest)
        except FactError as exc:
            raise SystemExit(f"promote-stable: cannot roll back to {args.to}: {exc}") from None
        entries.append(entry)
        how = "would repoint" if args.mode == "dry-run" else "repoints"
        text = (f"ROLLBACK {cell.name}: {how} {', '.join(w['dest'] for w in entry['writes'])} "
                f"from {short(current_digest)} to {args.to} ({short(target[0])}); "
                f"reason: {reason}")
    print(text)
    if args.mode == "rollback":
        write_plan(args.plan, {"action": "rollback", "reason": reason, "cells": entries})
    if args.summary:
        outcome = ("Dry run: nothing was copied." if args.mode == "dry-run" else
                   "The Write stable tags job applies it.")
        with open(args.summary, "a", encoding="utf-8") as handle:
            handle.write(f"## Stable rollback (RFC 018, {args.mode})\n\n{text}\n\n{outcome}\n")
    return 0


def parse_now(value: str) -> datetime:
    moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def main(argv=None) -> int:
    owner = os.environ.get("GITHUB_REPOSITORY_OWNER", "tuna-os")
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    for name, modes in MODES.items():
        p = sub.add_parser(name)
        p.add_argument("--mode", default="dry-run", choices=modes)
        p.add_argument("--plan", default="",
                       help="plan file for the apply command (required unless --mode dry-run)")
        p.add_argument("--config", default=str(ROOT / ".github/build-config.yml"))
        p.add_argument("--registry", default=os.environ.get("IMAGE_REGISTRY") or f"ghcr.io/{owner}")
        p.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", "tuna-os/tunaOS"))
        p.add_argument("--summary", default=os.environ.get("GITHUB_STEP_SUMMARY", ""))
        p.add_argument("--cell", default="", required=name == "rollback",
                       help="comma-separated variant:flavor names or globs (albacore:*, *:gnome)")
    sub.choices["evaluate"].add_argument("--jobs", type=int, default=8)
    sub.choices["evaluate"].add_argument("--now", type=parse_now,
                                         default=datetime.now(UTC).replace(microsecond=0))
    sub.choices["rollback"].add_argument("--to", required=True,
                                         help="dated tag, e.g. gnome-20261027")
    sub.choices["rollback"].add_argument("--reason", required=True)
    apply = sub.add_parser("apply")
    apply.add_argument("--plan", required=True)
    apply.add_argument("--summary", default=os.environ.get("GITHUB_STEP_SUMMARY", ""))
    apply.add_argument("--jobs", type=int, default=4)
    args = parser.parse_args(argv)
    if args.command == "apply":
        return cmd_apply(args)
    if args.mode != "dry-run" and not args.plan:
        parser.error(f"--mode {args.mode} needs --plan")
    return cmd_evaluate(args) if args.command == "evaluate" else cmd_rollback(args)


if __name__ == "__main__":
    sys.exit(main())
