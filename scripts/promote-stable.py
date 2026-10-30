#!/usr/bin/env python3
"""RFC 018 phase 2: report what the :testing -> :stable promotion would do.

For every cell (variant image path x flavor published_tag, build_image true)
this reads the registry and GitHub, picks the digest the bare (stable) tag
would move to, evaluates the promotion gates and prints one line per cell:

    PROMOTE  every gate passed for the newest soaked :testing digest
    HOLD     a gate held the cell; the reason names the gate
    NOOP     stable already points at that digest, or is ahead of it

It is read-only. Phase 2 is a dry run: ``--mode`` accepts only ``dry-run`` and
nothing here copies, tags or deletes an image. A held cell is data, not an
error, so the run exits 0 whenever it could evaluate the cells.

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
  Soak-After       every commit between the stable and candidate revisions is
                   scanned for ``Soak-After: <N>d``; the candidate waits for
                   the largest N

Usage:
    scripts/promote-stable.py evaluate [--cell 'albacore:gnome,yellowfin:*']
    scripts/promote-stable.py rollback --cell albacore:gnome \\
        --to gnome-20261027 --reason 'boot regression, #1234'
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
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
REVISION_LABEL = "org.opencontainers.image.revision"
# Containerfile.final records the build commit only as image.version
# (SHA_HEAD_SHORT); accept it when it is a commit and the revision is absent.
VERSION_LABEL = "org.opencontainers.image.version"
COMMIT = re.compile(r"[0-9a-f]{7,40}\Z")
SOAK_AFTER = re.compile(r"^Soak-After:[ \t]*([0-9]+)[ \t]*d[ \t]*$", re.I | re.M)
PHASE3 = "RFC 018 phase 3 not enabled"


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

    def stable_refs(self) -> list[str]:
        """Every ref the stable ring owns: bare, per-arch and alias tags."""
        registry = self.image.rsplit("/", 1)[0]
        arches = [p.removeprefix("linux/").replace("/", "-") for p in self.platforms]
        return ([self.ref(self.tag)] + [self.ref(f"{self.tag}-{a}") for a in arches]
                + [f"{registry}/{alias}:{self.tag}" for alias in self.aliases])


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
class Verdict:
    cell: Cell
    decision: str
    reason: str
    stable: str = ""
    candidate: str = ""
    verdict: str = ""             # the phase-3 rule's answer when it differs


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
        # Only possible while Promote still writes the bare tag (RFC 018
        # phases 1-2) or after a manual forward repoint: moving stable to an
        # older soaked digest would be a rollback, which this never does.
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


def decide(cell: Cell, candidate: Generation, blockers: list[str],
           sweep: tuple[bool, str], soak_after: tuple[bool, str]) -> tuple[str, str]:
    """Combine the gate results for a selected candidate."""
    held = [f"release-blocker: {', '.join(blockers)}"] if blockers else []
    held += [why for ok, why in (sweep, soak_after) if not ok]
    if held:
        return "HOLD", "; ".join(held)
    return "PROMOTE", (f"{candidate.tag} ({short(candidate.digest)}) entered :testing "
                       f"{candidate.oldest}, {cell.soak_days}d soak served; "
                       f"{sweep[1]}; {soak_after[1]}")


# ── Registry and GitHub reads ────────────────────────────────────────────────

def run(cmd: list[str], *, binary: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=False, capture_output=True, text=not binary, timeout=180)


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


def evaluate(cell: Cell, now: datetime, issues: list[dict] | None,
             sweep: Sweep | None, sweep_error: str) -> Verdict:
    try:
        stable_got = manifest(cell.ref(cell.tag))
        stable = stable_got[0] if stable_got else None
        gens, raws = probe(cell, now)
        if stable_got:
            raws.setdefault(stable, stable_got[1])
        selection = select(gens, stable, cell.soak_days, now)
        candidate = selection.candidate
        base = dict(cell=cell, stable=short(stable),
                    candidate=f"{candidate.tag} ({short(candidate.digest)})" if candidate else "")
        if selection.decision == "HOLD" or (selection.decision == "NOOP" and not selection.ahead):
            return Verdict(decision=selection.decision, reason=selection.reason, **base)
        ahead = ""
        if selection.ahead:
            ahead = (f"stable is ahead at {selection.ahead.tag} ({short(stable)}); Promote "
                     "writes the bare tag until RFC 018 phase 3")
            if candidate is None:
                return Verdict(decision="NOOP", reason=ahead,
                               verdict=f"HOLD {selection.reason}", **base)
        if issues is None:
            blockers = ["lookup failed"]
        else:
            blockers = matching_blockers(cell, issues)
        sweep_result = (False, f"desktop contract: {sweep_error}") if sweep_error else \
            sweep_gate(cell, sweep, candidate)
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
        decision, reason = decide(cell, candidate, blockers, sweep_result, soak_after)
        if selection.ahead:
            return Verdict(decision="NOOP", reason=ahead, verdict=f"{decision} {reason}", **base)
        return Verdict(decision=decision, reason=reason, **base)
    except FactError as exc:
        return Verdict(cell=cell, decision="HOLD", reason=f"could not evaluate: {exc}")


def line(v: Verdict) -> str:
    text = f"{v.decision:<7} {v.cell.name:<26} {v.reason}"
    return text + (f" | phase-3 verdict: {v.verdict}" if v.verdict else "")


def summary(verdicts: list[Verdict], now: datetime, sweep_note: str, blocker_note: str) -> str:
    counts = {d: sum(v.decision == d for v in verdicts) for d in ("PROMOTE", "HOLD", "NOOP")}
    rows = ["## Stable promotion (RFC 018 phase 2, dry run)", "",
            (f"Evaluated {stamp(now)} for {len(verdicts)} cell(s): {counts['PROMOTE']} PROMOTE, "
             f"{counts['HOLD']} HOLD, {counts['NOOP']} NOOP. Nothing was copied or tagged."), "",
            f"- release-blocker issues: {blocker_note}",
            f"- desktop-contract-sweep: {sweep_note}", "",
            "| Cell | Soak | Stable (bare) | Candidate | Decision | Reason | Phase-3 verdict |",
            "|---|--:|---|---|:--:|---|---|"]
    for v in verdicts:
        cells = [v.cell.name, f"{v.cell.soak_days}d", f"`{v.stable}`" if v.stable else "",
                 v.candidate, f"**{v.decision}**", v.reason, v.verdict or v.decision]
        rows.append("| " + " | ".join(c.replace("|", "\\|") for c in cells) + " |")
    return "\n".join(rows) + "\n"


def load_cells(args) -> list[Cell]:
    config = json.loads(Path(args.config).read_text())
    return filter_cells(cells_from_config(config, args.registry), args.cell)


def cmd_evaluate(args) -> int:
    now = args.now
    cells = load_cells(args)
    try:
        issues = blocker_issues(args.repo)
        blocker_note = f"{len(issues)} open labelled {BLOCKER_LABEL}"
    except FactError as exc:
        issues, blocker_note = None, f"lookup failed ({exc}); every cell holds"
    wanted = {key for key in map(sweep_cell, cells) if key}
    sweep, sweep_error = None, ""
    try:
        sweep = latest_sweep(args.repo, wanted) if wanted else Sweep({})
        runs = sorted({row[2] for row in sweep.cells.values()}) if sweep else []
        sweep_note = f"results from run(s) {', '.join(runs)}" if runs else "no usable artifact"
    except FactError as exc:
        sweep_error = f"sweep lookup failed ({exc})"
        sweep_note = sweep_error
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        verdicts = list(pool.map(lambda c: evaluate(c, now, issues, sweep, sweep_error), cells))
    for verdict in verdicts:
        print(line(verdict), flush=True)
    if args.summary:
        with open(args.summary, "a", encoding="utf-8") as handle:
            handle.write(summary(verdicts, now, sweep_note, blocker_note))
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
    if current_digest == target[0]:
        text = f"NOOP    {cell.name:<26} stable already at {args.to} ({short(target[0])})"
    else:
        text = (f"ROLLBACK {cell.name} (dry run): would repoint {', '.join(cell.stable_refs())} "
                f"from {short(current_digest)} to {args.to} ({short(target[0])}); reason: {reason}")
    print(text)
    if args.summary:
        with open(args.summary, "a", encoding="utf-8") as handle:
            handle.write(f"## Stable rollback (RFC 018 phase 2, dry run)\n\n{text}\n\n"
                         "Nothing was copied.\n")
    return 0


def parse_now(value: str) -> datetime:
    moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def main(argv=None) -> int:
    owner = os.environ.get("GITHUB_REPOSITORY_OWNER", "tuna-os")
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("evaluate", "rollback"):
        p = sub.add_parser(name)
        p.add_argument("--mode", default="dry-run")
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
    args = parser.parse_args(argv)
    if args.mode != "dry-run":
        print(f"::error::{PHASE3}: promote-stable only runs --mode dry-run (got {args.mode!r})",
              file=sys.stderr)
        return 2
    return cmd_evaluate(args) if args.command == "evaluate" else cmd_rollback(args)


if __name__ == "__main__":
    sys.exit(main())
