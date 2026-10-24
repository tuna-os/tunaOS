"""#3152: preserve every finding and reject incomplete coordination snapshots."""

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    'workflow_security_rollout', ROOT / 'scripts/gen-workflow-security-rollout.py'
)
rollout = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(rollout)


def issue(number=1, repo='tuna-os/example'):
    return {
        'repository_url': f'https://api.github.com/repos/{repo}',
        'number': number, 'html_url': f'https://github.com/{repo}/issues/{number}',
        'title': '[sec-check] missing permissions', 'state': 'open',
        'updated_at': '2026-10-23T00:00:00Z',
    }


def search(pages):
    def run(command, **kwargs):
        assert command[:5] == ['gh', 'api', '--method', 'GET', 'search/issues']
        assert '--paginate' in command and '--slurp' in command
        assert kwargs['check'] is True
        return SimpleNamespace(stdout=json.dumps(pages))
    return run


def page(items, total=None, incomplete=False):
    return {'items': items, 'total_count': len(items) if total is None else total,
            'incomplete_results': incomplete}


def test_collects_all_pages_and_deduplicates_queries():
    snapshot = rollout.collect_issues(
        ['first', 'second'], run=search([page([issue(1)], 2), page([issue(2)], 2)])
    )
    assert [i['number'] for i in snapshot['issues']] == [1, 2]


@pytest.mark.parametrize('pages', [[], [page([], 1)], [page([], incomplete=True)]])
def test_partial_search_cannot_be_published(pages):
    with pytest.raises(ValueError):
        rollout.collect_issues(['query'], run=search(pages))


def test_api_search_cap_cannot_be_published():
    with pytest.raises(ValueError, match='Truncated'):
        rollout.collect_issues(['query'], run=search([page([issue(n) for n in range(1000)], 1001)]))


def test_generated_index_keeps_duplicates_visible_and_escapes_titles():
    snapshot = rollout.collect_issues(['query'], run=search([page([issue(2), issue(1)])]))
    snapshot['issues'][0]['title'] = '<script> [title](https://bad.example)'
    output = rollout.render(snapshot)
    assert '2 open issues in 1 repositories' in output
    assert output.index('[#1]') < output.index('[#2]')
    assert '<script>' not in output
    assert '&#91;title&#93;' in output


def test_committed_index_matches_snapshot():
    snapshot = json.loads((ROOT / 'docs/data/workflow-security-issues.json').read_text())
    assert (ROOT / 'docs/WORKFLOW-SECURITY-ROLLOUT-INDEX.md').read_text() == rollout.render(snapshot)
