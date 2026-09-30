"""Dynamic fork simulation tests (epic #2250 item 13).

Proves that `scripts/fork-simulation.py` accurately simulates pull request workflows
under fork conditions (read-only GITHUB_TOKEN, empty repository secrets) across
the required contributor personas:
  * First-time external contributor (head.repo.fork == true)
  * Same-repo contributor (head.repo.fork == false)
  * Renovate bot (user.type == 'Bot', actor == 'renovate[bot]')
"""

from __future__ import annotations

import importlib.util
import io
import json
from contextlib import redirect_stdout
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "fork_simulation", ROOT / "scripts" / "fork-simulation.py"
)
sim = importlib.util.module_from_spec(spec)
import sys
sys.modules["fork_simulation"] = sim
spec.loader.exec_module(sim)


def test_required_personas_are_defined():
    persona_ids = [p.id for p in sim.PERSONAS]
    assert "external_contributor" in persona_ids
    assert "same_repo_contributor" in persona_ids
    assert "renovate" in persona_ids

    ext = next(p for p in sim.PERSONAS if p.id == "external_contributor")
    assert ext.is_fork is True
    assert ext.user_type == "User"

    same = next(p for p in sim.PERSONAS if p.id == "same_repo_contributor")
    assert same.is_fork is False
    assert same.user_type == "User"

    ren = next(p for p in sim.PERSONAS if p.id == "renovate")
    assert ren.is_fork is False
    assert ren.user_type == "Bot"
    assert "renovate" in ren.actor


def test_expression_evaluator_evaluates_standard_patterns():
    ext_ctx = sim.build_context(
        next(p for p in sim.PERSONAS if p.id == "external_contributor")
    )
    same_ctx = sim.build_context(
        next(p for p in sim.PERSONAS if p.id == "same_repo_contributor")
    )
    ren_ctx = sim.build_context(
        next(p for p in sim.PERSONAS if p.id == "renovate")
    )

    # Fork check
    fork_expr = "github.event.pull_request.head.repo.fork == false"
    assert sim._eval_gh_expression(fork_expr, ext_ctx) is False
    assert sim._eval_gh_expression(fork_expr, same_ctx) is True

    # Bot check
    bot_expr = "github.event.pull_request.user.type == 'Bot'"
    assert sim._eval_gh_expression(bot_expr, ext_ctx) is False
    assert sim._eval_gh_expression(bot_expr, ren_ctx) is True

    # Human PR nudges filter check
    nudge_expr = (
        "github.event.pull_request.draft == false && "
        "github.actor != 'renovate[bot]' && "
        "github.actor != 'dependabot[bot]'"
    )
    assert sim._eval_gh_expression(nudge_expr, ext_ctx) is True
    assert sim._eval_gh_expression(nudge_expr, same_ctx) is True
    assert sim._eval_gh_expression(nudge_expr, ren_ctx) is False


def test_all_current_pr_workflows_pass_fork_simulation():
    results = sim.evaluate()
    assert len(results) >= 5, "expected multiple PR workflows to be evaluated"
    failures = [r for r in results if not r["passed"]]
    assert not failures, (
        "The following PR workflows failed dynamic fork simulation:\n"
        + "\n".join(f"{f['file']}: {f['failures']}" for f in failures)
    )


def test_unguarded_write_step_fails_fork_simulation(tmp_path):
    bad_wf = tmp_path / "bad-push.yml"
    bad_wf.write_text(
        yaml.dump({
            "name": "Bad Push Workflow",
            "on": {"pull_request": None},
            "jobs": {
                "push": {
                    "runs-on": "ubuntu-latest",
                    "steps": [
                        {"name": "Unguarded push", "run": "git push origin main"}
                    ],
                }
            },
        })
    )

    res = sim.simulate_workflow(bad_wf)
    assert not res["passed"]
    assert res["personas"]["external_contributor"]["status"] == "fail"
    assert any("write action" in err for err in res["failures"])


def test_unguarded_secret_reference_fails_fork_simulation(tmp_path):
    secret_wf = tmp_path / "bad-secret.yml"
    secret_wf.write_text(
        yaml.dump({
            "name": "Bad Secret Workflow",
            "on": {"pull_request": None},
            "jobs": {
                "upload": {
                    "runs-on": "ubuntu-latest",
                    "steps": [
                        {
                            "name": "Upload to cloud",
                            "run": "rclone copy ./build remote:",
                            "env": {"KEY": "${{ secrets.R2_SECRET_KEY }}"},
                        }
                    ],
                }
            },
        })
    )

    res = sim.simulate_workflow(secret_wf)
    assert not res["passed"]
    assert res["personas"]["external_contributor"]["status"] == "fail"
    assert any("secrets R2_SECRET_KEY" in err for err in res["failures"])


def test_fork_guarded_write_step_passes_simulation(tmp_path):
    guarded_wf = tmp_path / "guarded-push.yml"
    guarded_wf.write_text(
        yaml.dump({
            "name": "Guarded Push Workflow",
            "on": {"pull_request": None},
            "jobs": {
                "push": {
                    "runs-on": "ubuntu-latest",
                    "steps": [
                        {
                            "name": "Guarded push",
                            "if": "github.event.pull_request.head.repo.fork == false",
                            "run": "git push origin main",
                        },
                        {
                            "name": "Diff for fork",
                            "if": "always() && github.event.pull_request.head.repo.fork == true",
                            "run": "echo 'diff summary' >> $GITHUB_STEP_SUMMARY",
                        },
                    ],
                }
            },
        })
    )

    res = sim.simulate_workflow(guarded_wf)
    assert res["passed"]
    assert res["personas"]["external_contributor"]["status"] == "pass"
    assert res["personas"]["same_repo_contributor"]["status"] == "pass"


def test_json_output_cli():
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = sim.main(["--json"])
    assert rc == 0
    data = json.loads(buf.getvalue())
    assert data["passed"] is True
    assert data["failed"] == []
    assert data["total"] >= 5
    assert "external_contributor" in data["personas"]


def test_markdown_report_cli():
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = sim.main([])
    assert rc == 0
    out = buf.getvalue()
    assert "## Fork simulation report" in out
    assert "| Workflow | Verdict |" in out
    assert "All `pull_request` workflows passed fork simulation." in out


def test_bot_only_workflow_skips_humans_and_runs_for_bot(tmp_path):
    bot_wf = tmp_path / "bot-only.yml"
    bot_wf.write_text(
        yaml.dump({
            "name": "Bot Only Workflow",
            "on": {"pull_request": None},
            "jobs": {
                "drop": {
                    "if": "github.event.pull_request.user.type == 'Bot' && github.event.pull_request.head.repo.full_name == github.repository",
                    "runs-on": "ubuntu-latest",
                    "steps": [
                        {
                            "name": "Drop reviewers",
                            "run": "gh api -X DELETE repos/tuna-os/tunaos/pulls/1/requested_reviewers",
                        }
                    ],
                }
            },
        })
    )

    res = sim.simulate_workflow(bot_wf)
    assert res["passed"]
    assert res["personas"]["external_contributor"]["status"] == "skipped"
    assert res["personas"]["same_repo_contributor"]["status"] == "skipped"
    assert res["personas"]["renovate"]["status"] == "pass"


def test_fork_simulation_cli_strict_flag(tmp_path, monkeypatch):
    bad_wf = tmp_path / "bad.yml"
    bad_wf.write_text(
        yaml.dump({
            "name": "Bad",
            "on": {"pull_request": None},
            "jobs": {
                "bad": {
                    "runs-on": "ubuntu-latest",
                    "steps": [{"name": "Push", "run": "git push origin main"}],
                }
            },
        })
    )
    monkeypatch.setattr(sim, "WORKFLOWS_DIR", tmp_path)
    assert sim.main(["--strict"]) == 1


def test_fork_simulation_workflow_declaration():
    wf_path = ROOT / ".github" / "workflows" / "fork-simulation.yml"
    assert wf_path.exists(), "fork-simulation.yml does not exist"
    doc = yaml.safe_load(wf_path.read_text(encoding="utf-8"))

    on = doc.get("on", doc.get(True, {}))
    assert "schedule" in on
    assert "workflow_dispatch" in on

    assert doc["permissions"].get("contents") == "read"
    assert doc["permissions"].get("issues") == "write"

    body = wf_path.read_text(encoding="utf-8")
    assert "scripts/fork-simulation.py" in body
    assert "$GITHUB_STEP_SUMMARY" in body
    assert "gh issue" in body
    assert "<!-- fork-simulation -->" in body

