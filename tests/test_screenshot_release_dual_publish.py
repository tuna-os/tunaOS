"""Screenshots are dual-published: R2 stays, and the `screenshots` release is added.

Epic #3470 moves off Cloudflare R2 without breaking `download.tunaos.org`
URLs. The four screenshot workflows therefore keep their R2 upload and also
run `scripts/screenshot-release.py publish`, which puts the same `-latest`
PNGs on the rolling `screenshots` release. docs/SCREENSHOT-RELEASE.md maps each
R2 key to its asset URL for the docs site.

Three things are checked, each against the real files:

  mapping    R2 key -> asset name -> URL, the key the workflows really write to
             R2, and the table in docs/SCREENSHOT-RELEASE.md;
  guards     the publishing job holds `contents: write` while the workflow
             default stays read-only; the step runs only for push, schedule or
             dispatch on the default branch; no `pull_request` trigger; the
             only credential is GITHUB_TOKEN and no R2 secret is read;
  behaviour  the script run against a stand-in `gh` that records its calls.

`problems()` is the one checker. The real workflows must give no problems, and
the mutation tests prove it reports each defect (a variant that lacks the new
step fails).
"""

from __future__ import annotations

import copy
import importlib.util
import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
SCRIPT = ROOT / "scripts" / "screenshot-release.py"
DOC = ROOT / "docs" / "SCREENSHOT-RELEASE.md"

spec = importlib.util.spec_from_file_location("screenshot_release", SCRIPT)
sr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sr)

PUBLISH = "scripts/screenshot-release.py publish"
BRANCH_CONJUNCT = "github.event.repository.default_branch == github.ref_name"
ALLOWED_EVENTS = {"push", "schedule", "workflow_dispatch"}
FORBIDDEN_TRIGGERS = {"pull_request", "pull_request_target", "issue_comment", "merge_group"}

# workflow -> (kind, job that holds the publish step, job is dedicated to it)
EXPECTED = {
    "installer-screenshots.yml": ("installer", "commit-to-repo", False),
    "installer-smoke.yml": ("installer", "publish-screenshots", False),
    "weekly-desktop-screenshots.yml": ("desktop", "publish-release", True),
    "weekly-qcow2-screenshots.yml": ("boot", "publish-release", True),
}


def _load(name: str) -> dict:
    return yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))


def _triggers(doc: dict) -> set[str]:
    on = doc.get("on", doc.get(True))  # PyYAML reads a bare `on:` key as True
    if isinstance(on, str):
        return {on}
    return set(on or {})


def _norm(expr: object) -> str:
    return re.sub(r"\s+", " ", str(expr or "")).strip()


def _publish_steps(doc: dict) -> list[tuple[str, int, dict]]:
    return [
        (job_id, i, step)
        for job_id, job in (doc.get("jobs") or {}).items()
        for i, step in enumerate((job or {}).get("steps") or [])
        if PUBLISH in str(step.get("run", ""))
    ]


def problems(name: str, doc: dict) -> list[str]:
    """Every way `doc` fails the dual-publish contract for workflow `name`."""
    kind, job_id, dedicated = EXPECTED[name]
    out: list[str] = []

    bad = _triggers(doc) & FORBIDDEN_TRIGGERS
    if bad:
        out.append(f"triggers {sorted(bad)} would let untrusted code reach the publish step")

    top = doc.get("permissions")
    if not isinstance(top, dict) or top.get("contents") != "read" or "write" in top.values():
        out.append(f"workflow permissions must stay read-only contents, got {top!r}")

    steps = _publish_steps(doc)
    if len(steps) != 1:
        return out + [f"expected exactly one `{PUBLISH}` step, found {len(steps)}"]
    found_job, _, step = steps[0]
    if found_job != job_id:
        out.append(f"publish step is in job {found_job!r}, expected {job_id!r}")
    job = doc["jobs"][found_job]

    if f"--kind {kind}" not in step["run"]:
        out.append(f"publish step must pass --kind {kind}")
    if '--repo "$GITHUB_REPOSITORY"' not in step["run"]:
        out.append('publish step must pass --repo "$GITHUB_REPOSITORY"')

    if (job.get("permissions") or {}).get("contents") != "write":
        out.append(f"job {found_job!r} needs `permissions: contents: write` to upload release assets")
    if dedicated:
        extra = set(job.get("permissions") or {}) - {"contents"}
        if extra:
            out.append(f"dedicated job {found_job!r} holds unneeded permissions {sorted(extra)}")
        if "screenshot" not in str(job.get("needs")):
            out.append(f"dedicated job {found_job!r} must run after the capture job")
        other = [j for j, jb in doc["jobs"].items() if j != found_job and (jb.get("permissions") or {}).get("contents") == "write"]
        if other and name.startswith("weekly-qcow2"):
            out.append(f"jobs {other} also hold contents: write; only the publish job should")

    cond = _norm(job.get("if")) + " && " + _norm(step.get("if"))
    if BRANCH_CONJUNCT not in cond:
        out.append(f"no `{BRANCH_CONJUNCT}` conjunct: a feature-branch dispatch would publish")
    events = re.search(r"fromJSON\('(\[[^']*\])'\),\s*github\.event_name\)", cond)
    if not events:
        out.append("no `contains(fromJSON('[...]'), github.event_name)` event allowlist")
    elif set(json.loads(events.group(1))) != ALLOWED_EVENTS:
        out.append(f"event allowlist is {json.loads(events.group(1))}, expected {sorted(ALLOWED_EVENTS)}")
    if "pull_request" in cond:
        out.append("guard names pull_request")

    if step.get("env") != {"GH_TOKEN": "${{ secrets.GITHUB_TOKEN }}"}:
        out.append(f"publish step env must be exactly GH_TOKEN from GITHUB_TOKEN, got {step.get('env')!r}")
    blob = yaml.dump(step) + (yaml.dump(job) if dedicated else "")
    if re.search(r"secrets\.R2_|rclone|RCLONE_CONFIG", blob):
        out.append("publish path reads an R2 secret or runs rclone")
    if "${{" in step["run"]:
        out.append("publish `run` interpolates an expression; pass it through env")
    for s in job.get("steps") or []:
        if str(s.get("uses", "")).startswith("actions/checkout") and (s.get("with") or {}).get("persist-credentials") is True and dedicated:
            out.append("dedicated job persists the token in .git/config")
    return out


WORKFLOW_NAMES = sorted(EXPECTED)


@pytest.mark.parametrize("name", WORKFLOW_NAMES)
def test_the_workflow_dual_publishes_with_the_required_guards(name):
    assert problems(name, _load(name)) == []


# ── a variant that lacks the new step, or weakens a guard, must fail ────────────

def _mutate(name: str, fn) -> dict:
    doc = copy.deepcopy(_load(name))
    fn(doc, EXPECTED[name][1])
    return doc


def _drop_step(doc, job):
    doc["jobs"][job]["steps"] = [s for s in doc["jobs"][job]["steps"] if PUBLISH not in str(s.get("run", ""))]


def _drop_branch_guard(doc, job):
    for holder in (doc["jobs"][job], *doc["jobs"][job]["steps"]):
        if "if" in holder:
            holder["if"] = _norm(holder["if"]).replace(BRANCH_CONJUNCT, "true")


def _allow_pr(doc, job):
    for holder in (doc["jobs"][job], *doc["jobs"][job]["steps"]):
        if "if" in holder:
            holder["if"] = _norm(holder["if"]).replace('"push",', '"push","pull_request",').replace("'[\"push\",", "'[\"push\",\"pull_request\",")


def _no_job_write(doc, job):
    doc["jobs"][job]["permissions"] = {"contents": "read"}


def _top_write(doc, job):
    doc["permissions"] = {"contents": "write"}


def _pr_trigger(doc, job):
    on = doc.get("on", doc.get(True))
    on["pull_request"] = {}


def _leak_r2(doc, job):
    for s in doc["jobs"][job]["steps"]:
        if PUBLISH in str(s.get("run", "")):
            s["env"]["R2_SECRET"] = "${{ secrets.R2_SECRET_ACCESS_KEY }}"


def _wrong_kind(doc, job):
    for s in doc["jobs"][job]["steps"]:
        if PUBLISH in str(s.get("run", "")):
            s["run"] = s["run"].replace("--kind ", "--kind x")


def _duplicate_step(doc, job):
    steps = doc["jobs"][job]["steps"]
    steps.append(copy.deepcopy(next(s for s in steps if PUBLISH in str(s.get("run", "")))))


MUTATIONS = {
    "no publish step": (_drop_step, "found 0"),
    "two publish steps": (_duplicate_step, "found 2"),
    "no default-branch guard": (_drop_branch_guard, "default_branch"),
    "pull_request allowed by the guard": (_allow_pr, "event allowlist"),
    "job lacks contents: write": (_no_job_write, "contents: write"),
    "workflow default is write": (_top_write, "read-only"),
    "pull_request trigger": (_pr_trigger, "triggers"),
    "R2 secret reaches the step": (_leak_r2, "GH_TOKEN"),
    "wrong --kind": (_wrong_kind, "--kind"),
}


@pytest.mark.parametrize("name", WORKFLOW_NAMES)
@pytest.mark.parametrize("label", sorted(MUTATIONS))
def test_a_variant_without_the_step_or_a_guard_is_rejected(name, label):
    fn, expect = MUTATIONS[label]
    found = problems(name, _mutate(name, fn))
    assert any(expect in p for p in found), (label, found)


# ── the R2 upload is still there, and it writes the keys the mapping assumes ────

def _r2_latest_templates(doc: dict) -> set[str]:
    """`<prefix>NAME-latest.png` keys that rclone steps write, NAME left as a token."""
    keys = set()
    for job in doc["jobs"].values():
        for step in job.get("steps") or []:
            run = str(step.get("run", ""))
            if not re.search(r"rclone\s+copyto", run):
                continue
            direct = re.search(r'R2:\$\{\{ secrets\.R2_BUCKET \}\}/(screenshots/installer/)\$\{base\}-latest\.png', run)
            dest = re.search(r'DEST="R2:\$\{\{ secrets\.R2_BUCKET \}\}/(screenshots(?:/boot)?)"', run)
            if direct:
                keys.add(f"{direct.group(1)}NAME-latest.png")
            elif dest and '"${DEST}/${BASE}-latest.png"' in run:
                keys.add(f"{dest.group(1)}/NAME-latest.png")
    return keys


@pytest.mark.parametrize("name", WORKFLOW_NAMES)
def test_the_r2_upload_stays_and_writes_the_key_the_mapping_assumes(name):
    kind = EXPECTED[name][0]
    assert _r2_latest_templates(_load(name)) == {sr.r2_key(kind, "NAME")}


def test_every_workflow_that_uploads_screenshots_to_r2_dual_publishes():
    writers = set()
    for path in sorted(WORKFLOWS.glob("*.y*ml")):
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if any(k.startswith("screenshots/") for k in _r2_latest_templates(doc)) or any(
            re.search(r"rclone\s+copyto.*screenshots/", str(s.get("run", "")), re.S)
            for j in (doc.get("jobs") or {}).values() for s in (j or {}).get("steps") or []
        ):
            writers.add(path.name)
    assert writers == set(EXPECTED), (
        f"a workflow that uploads screenshots to R2 must also publish to the release "
        f"and be listed in EXPECTED: {sorted(writers ^ set(EXPECTED))}"
    )


# ── mapping ─────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("kind,name,key,asset", [
    ("desktop", "yellowfin-gnome", "screenshots/yellowfin-gnome-latest.png", "yellowfin-gnome-latest.png"),
    ("boot", "skipjack-kde", "screenshots/boot/skipjack-kde-latest.png", "boot__skipjack-kde-latest.png"),
    ("installer", "cosmic_01_welcome", "screenshots/installer/cosmic_01_welcome-latest.png", "installer__cosmic_01_welcome-latest.png"),
    ("installer", "smoke-kde_03", "screenshots/installer/smoke-kde_03-latest.png", "installer__smoke-kde_03-latest.png"),
])
def test_r2_key_maps_to_a_release_asset_url(kind, name, key, asset):
    assert sr.r2_key(kind, name) == key
    assert sr.asset_name(key) == asset
    assert sr.asset_url("tuna-os/tunaos", key) == f"https://github.com/tuna-os/tunaos/releases/download/screenshots/{asset}"


def test_the_workflow_matrices_map_to_distinct_assets():
    desktop = _load("weekly-desktop-screenshots.yml")["jobs"]["screenshot"]["strategy"]["matrix"]
    excluded = {(e["variant"], e["flavor"]) for e in desktop.get("exclude", [])}
    cells = [(v, f) for v in desktop["variant"] for f in desktop["flavor"] if (v, f) not in excluded]
    boot = [(c["variant"], c["flavor"]) for c in _load("weekly-qcow2-screenshots.yml")["jobs"]["screenshot"]["strategy"]["matrix"]["include"]]
    assets = [sr.asset_name(sr.r2_key("desktop", f"{v}-{f}")) for v, f in cells]
    assets += [sr.asset_name(sr.r2_key("boot", f"{v}-{f}")) for v, f in boot]
    assert len(cells) > 20 and len(boot) == 16
    assert len(assets) == len(set(assets))


@pytest.mark.parametrize("kind,name", [
    ("desktop", "a__b"), ("desktop", "installer__x"), ("desktop", ""), ("desktop", "-lead"),
    ("desktop", "has space"), ("desktop", "a/b"), ("desktop", "naïve"), ("bogus", "x"),
])
def test_a_name_that_would_collide_or_be_renamed_is_rejected(kind, name):
    with pytest.raises(ValueError):
        sr.r2_key(kind, name)


def test_a_key_outside_the_screenshots_tree_is_rejected():
    for key in ("live-isos/x-latest.png", "screenshots/x.jpg", "screenshots/a b.png"):
        with pytest.raises(ValueError):
            sr.asset_name(key)
    with pytest.raises(ValueError):
        sr.asset_url("not-a-repo", "screenshots/x-latest.png")


def test_the_docs_table_is_the_generated_table():
    text = DOC.read_text(encoding="utf-8")
    block = re.search(r"<!-- screenshot-url-table:start -->\n(.*?)<!-- screenshot-url-table:end -->", text, re.S)
    assert block, "docs/SCREENSHOT-RELEASE.md lost its generated table markers"
    assert block.group(1) == sr.render_table()
    for kind, name in sr.TABLE_EXAMPLES:
        assert sr.r2_key(kind, name) in block.group(1)
    for workflow in EXPECTED:
        assert workflow in text, f"docs/SCREENSHOT-RELEASE.md does not list {workflow}"
    assert "SCREENSHOT-RELEASE.md" in (ROOT / "docs" / "README.md").read_text(encoding="utf-8")


def test_the_adoption_snapshot_ignores_the_rolling_release():
    spec2 = importlib.util.spec_from_file_location("adoption_snapshot", ROOT / "scripts" / "adoption-snapshot.py")
    sys.path.insert(0, str(ROOT / "scripts"))
    snap = importlib.util.module_from_spec(spec2)
    spec2.loader.exec_module(snap)
    assert sr.RELEASE_TAG in snap.ROLLING_ASSET_RELEASES
    asset = {"id": 1, "name": "x-latest.png", "download_count": 900, "browser_download_url": "u"}
    out = snap.release_counts([
        {"draft": False, "tag_name": sr.RELEASE_TAG, "assets": [asset]},
        {"draft": False, "tag_name": "yellowfin-20261001", "assets": [dict(asset, id=2, download_count=3)]},
    ])
    assert out["published_releases"] == 1
    assert out["non_iso_downloads_lifetime"] == 3


# ── behaviour against a stand-in gh ─────────────────────────────────────────────

FAKE_GH = """#!/usr/bin/env bash
# Records every call. State: $FAKE_GH_STATE/{exists,log}. FAIL_CREATE=1 makes
# `release create` fail; RACE=1 makes it fail after the other writer created it.
printf '%s\\n' "$*" >> "$FAKE_GH_STATE/log"
[[ "$1 $2" == "release view" ]] && { [[ -e "$FAKE_GH_STATE/exists" ]]; exit; }
if [[ "$1 $2" == "release create" ]]; then
  [[ "${RACE:-}" == 1 ]] && touch "$FAKE_GH_STATE/exists"
  [[ "${FAIL_CREATE:-}" == 1 || "${RACE:-}" == 1 ]] && { echo "create failed" >&2; exit 1; }
  touch "$FAKE_GH_STATE/exists"; exit 0
fi
if [[ "$1 $2" == "release upload" ]]; then
  for a in "$@"; do [[ -f "$a" ]] && cp "$a" "$FAKE_GH_STATE/uploaded-$(basename "$a")"; done
  exit 0
fi
exit 99
"""


@pytest.fixture
def gh(tmp_path, monkeypatch):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    exe = bindir / "gh"
    exe.write_text(FAKE_GH)
    exe.chmod(exe.stat().st_mode | stat.S_IXUSR)
    state = tmp_path / "state"
    state.mkdir()
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_GH_STATE", str(state))
    monkeypatch.delenv("FAIL_CREATE", raising=False)
    monkeypatch.delenv("RACE", raising=False)
    return state


def _png(tmp_path: Path, name: str, data: bytes) -> str:
    p = tmp_path / f"{name}.png"
    p.write_bytes(data)
    return f"{name}={p}"


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True)


def _calls(state: Path) -> list[str]:
    log = state / "log"
    return log.read_text().splitlines() if log.exists() else []


def test_it_creates_the_release_then_uploads_renamed_assets_with_clobber(gh, tmp_path):
    r = _run("publish", "--kind", "installer", "--repo", "tuna-os/tunaos",
             _png(tmp_path, "cosmic_01_welcome", b"one"), _png(tmp_path, "smoke-kde_03", b"two"))
    assert r.returncode == 0, r.stderr
    calls = _calls(gh)
    create = next(c for c in calls if c.startswith("release create"))
    assert create.startswith("release create screenshots --repo tuna-os/tunaos")
    assert "--prerelease" in create and "--latest=false" in create
    upload = next(c for c in calls if c.startswith("release upload"))
    assert upload.startswith("release upload screenshots --repo tuna-os/tunaos --clobber ")
    assert (gh / "uploaded-installer__cosmic_01_welcome-latest.png").read_bytes() == b"one"
    assert (gh / "uploaded-installer__smoke-kde_03-latest.png").read_bytes() == b"two"
    assert "installer__smoke-kde_03-latest.png" in r.stdout
    assert "https://github.com/tuna-os/tunaos/releases/download/screenshots/installer__cosmic_01_welcome-latest.png" in r.stdout


def _publish_step_script(name: str) -> tuple[dict, str]:
    (_, _, step), = _publish_steps(_load(name))
    return step, step["run"]


def test_the_installer_step_finds_pngs_in_the_nested_artifact_layout(gh, tmp_path):
    """The walkthrough artifact downloads as installer-shots/staged/*.png.

    upload-artifact roots a multi-path upload at the workspace, so a flat
    `installer-shots/*.png` glob matches nothing (runs 38250603341 and
    34832292351 both logged `Staged 0 screenshot(s)` after a good capture).
    """
    step, script = _publish_step_script("installer-screenshots.yml")
    assert "staged" not in _norm(step.get("if")), "the release step must not depend on the flat-glob staging counter"
    shots = tmp_path / "installer-shots"
    (shots / "staged").mkdir(parents=True)
    (shots / "staged" / "cosmic_01_welcome.png").write_bytes(b"cosmic")
    (shots / "staged" / "01_welcome.png").write_bytes(b"gnome")
    (shots / "walkthrough-out").mkdir()
    (shots / "walkthrough-out" / "walkthrough-gnome.json").write_text("{}")
    script = script.replace("/tmp/installer-shots", str(shots)).replace("scripts/screenshot-release.py", str(SCRIPT))
    r = subprocess.run(["bash", "-c", script], capture_output=True, text=True,
                       env={**os.environ, "GITHUB_REPOSITORY": "tuna-os/tunaos"})
    assert r.returncode == 0, r.stderr
    assert (gh / "uploaded-installer__cosmic_01_welcome-latest.png").read_bytes() == b"cosmic"
    assert (gh / "uploaded-installer__01_welcome-latest.png").read_bytes() == b"gnome"
    assert not list(gh.glob("uploaded-*json*"))


def test_an_existing_release_is_not_recreated(gh, tmp_path):
    (gh / "exists").touch()
    r = _run("publish", "--kind", "desktop", "--repo", "tuna-os/tunaos", _png(tmp_path, "yellowfin-gnome", b"x"))
    assert r.returncode == 0, r.stderr
    assert not any(c.startswith("release create") for c in _calls(gh))
    assert (gh / "uploaded-yellowfin-gnome-latest.png").exists()


def test_losing_the_create_race_is_not_an_error(gh, tmp_path, monkeypatch):
    monkeypatch.setenv("RACE", "1")
    r = _run("publish", "--kind", "boot", "--repo", "tuna-os/tunaos", _png(tmp_path, "yellowfin-gnome", b"x"))
    assert r.returncode == 0, r.stderr
    assert (gh / "uploaded-boot__yellowfin-gnome-latest.png").exists()


def test_a_release_that_cannot_be_created_fails_loudly_and_uploads_nothing(gh, tmp_path, monkeypatch):
    monkeypatch.setenv("FAIL_CREATE", "1")
    r = _run("publish", "--kind", "boot", "--repo", "tuna-os/tunaos", _png(tmp_path, "yellowfin-gnome", b"x"))
    assert r.returncode == 1
    assert "cannot create release screenshots" in r.stderr
    assert not any(c.startswith("release upload") for c in _calls(gh))


def test_dry_run_and_empty_input_never_call_gh(gh, tmp_path):
    r = _run("publish", "--kind", "desktop", "--repo", "tuna-os/tunaos", "--dry-run", _png(tmp_path, "a-b", b"x"))
    assert r.returncode == 0 and "Would publish screenshots/a-b-latest.png" in r.stdout
    empty = _run("publish", "--kind", "desktop", "--repo", "tuna-os/tunaos")
    assert empty.returncode == 0 and "no screenshots to publish" in empty.stdout
    assert _calls(gh) == []


@pytest.mark.parametrize("bad", ["noequals", "=path", "name=", "missing=/nonexistent.png"])
def test_malformed_or_missing_sources_fail_before_any_gh_call(gh, bad):
    r = _run("publish", "--kind", "desktop", "--repo", "tuna-os/tunaos", bad)
    assert r.returncode == 1 and "::error::screenshot release" in r.stderr
    assert _calls(gh) == []


def test_two_sources_that_flatten_to_one_asset_fail_before_any_gh_call(gh, tmp_path):
    # r2_key rejects `__`, so a collision needs two spellings of one name.
    a = _png(tmp_path, "same", b"1")
    r = _run("publish", "--kind", "desktop", "--repo", "tuna-os/tunaos", a, a)
    assert r.returncode == 1 and "both map to asset" in r.stderr
    assert _calls(gh) == []


def test_the_table_command_prints_what_the_docs_carry(capsys):
    assert sr.main(["table"]) == 0
    assert capsys.readouterr().out == sr.render_table()
