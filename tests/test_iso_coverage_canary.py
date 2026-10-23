from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def test_canary_is_one_opt_in_diagnostic_not_a_privileged_reusable_call():
    workflow = (ROOT / '.github/workflows/iso-coverage-canary.yml').read_text()
    script = (ROOT / 'scripts/iso-coverage-canary.sh').read_text()
    assert 'workflow_dispatch:' in workflow and 'default: false' in workflow
    assert 'pull_request_target' not in workflow and 'schedule:' not in workflow
    assert 'contents: read' in workflow and 'contents: write' not in workflow
    assert 'secrets: inherit' not in workflow and 'GITHUB_TOKEN:' not in workflow
    assert 'uses: ./.github/workflows/luks-e2e.yml' not in workflow
    assert 'ref: ${{ inputs.source_sha || github.event.pull_request.head.sha }}' in workflow
    assert 'iso-coverage-diagnostic-' in workflow
    assert 'iso-coverage-receipt-' not in workflow
    assert 'timeout-minutes: 120' in workflow
    assert "github.run_attempt == '1'" in workflow
    assert 'export VARIANT=skipjack FLAVOR=gnome' in script
    assert 'scripts/iso-e2e.sh "${isos[0]}" --luks' in script
    assert 'git rev-parse HEAD' in script
    assert not re.search(r'\b(git push|podman push|skopeo copy)\b', script)


def test_cheap_pr_gate_has_no_install_or_write_privileges():
    workflow = (ROOT / '.github/workflows/iso-coverage-checks.yml').read_text()
    assert 'pull_request:' in workflow and 'pull_request_target' not in workflow
    assert 'contents: read' in workflow and ': write' not in workflow
    assert 'tests/test_iso_coverage_*.py' in workflow
    assert 'run: bash scripts/iso-coverage-canary.sh' not in workflow


def test_premerge_canary_requires_explicit_exact_head_approval_label():
    workflow = (ROOT / '.github/workflows/iso-coverage-canary.yml').read_text()
    assert 'pull_request:' in workflow and 'types: [labeled]' in workflow
    assert "format('iso:{0}', github.event.pull_request.head.sha)" in workflow
    assert 'github.event.pull_request.head.repo.full_name == github.repository' in workflow
    assert 'synchronize' not in workflow and 'opened' not in workflow
    assert 'pull_request_target' not in workflow
