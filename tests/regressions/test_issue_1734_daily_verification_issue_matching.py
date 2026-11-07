"""tunaOS#1734: a failing cell must only update its own daily-verification issue.

Run 37453199979 passed hummingbird:cosmic (job 112234466278), but its
hummingbird:gnome failure was reported on the COSMIC issue by full-text search.
Falsification: behavioural — execute the workflow reporter with COSMIC first
in the search results; selecting the first result comments on the wrong issue.
"""

import json
import os
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("exact_match", [True, False])
def test_failure_report_targets_only_the_exact_cell(tmp_path, exact_match):
    workflow = yaml.safe_load((ROOT / ".github/workflows/daily-verify.yml").read_text())
    reporter = next(
        step["run"]
        for step in workflow["jobs"]["verify"]["steps"]
        if step["name"] == "Create Issue on Failure"
    )
    results = [{"number": 1734, "title": "Daily Verification Failed: hummingbird:cosmic"}]
    if exact_match:
        results.append(
            {"number": 1733, "title": "Daily Verification Failed: hummingbird:gnome"}
        )
    calls = tmp_path / "calls.jsonl"
    gh = tmp_path / "gh"
    gh.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys\n"
        "args = sys.argv[1:]\n"
        "if args[:2] == ['issue', 'list']:\n"
        "    results = json.loads(os.environ['SEARCH_RESULTS'])\n"
        "    if '-q' in args:\n"
        "        print(results[0]['number'])\n"
        "    else:\n"
        "        print(json.dumps(results))\n"
        "else:\n"
        "    with open(os.environ['CALLS'], 'a') as out:\n"
        "        out.write(json.dumps(args) + '\\n')\n"
    )
    gh.chmod(0o755)
    subprocess.run(
        ["bash", "-e", "-o", "pipefail", "-c", reporter],
        check=True,
        env={
            **os.environ,
            "PATH": f"{tmp_path}:{os.environ['PATH']}",
            "SEARCH_RESULTS": json.dumps(results),
            "CALLS": str(calls),
            "VARIANT": "hummingbird",
            "FLAVOR": "gnome",
            "GITHUB_REPOSITORY_OWNER": "tuna-os",
            "GITHUB_REPOSITORY": "tuna-os/tunaOS",
            "GITHUB_SERVER_URL": "https://github.com",
            "GITHUB_RUN_ID": "37453199979",
        },
    )
    actions = [json.loads(line) for line in calls.read_text().splitlines()]
    assert len(actions) == 1
    if exact_match:
        assert actions[0][:3] == ["issue", "comment", "1733"]
    else:
        assert actions[0][:2] == ["issue", "create"]
        assert actions[0][actions[0].index("--title") + 1] == (
            "Daily Verification Failed: hummingbird:gnome"
        )
