"""The primary-config matrix must keep the compatibility floor and current Python.
Falsification: removing Python 3.10 loses floor coverage; removing 3.15 loses
coverage against the standard library's newer TOML parser.
"""
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def test_primary_matrix_runs_python310_floor_and_python315():
    workflow = (ROOT / '.github/workflows/test.yml').read_text()
    job = workflow.split('  primary-config:', 1)[1].split('\n  unit-tests:', 1)[0]
    matrix = re.search(r'(?m)^\s*python-version:\s*\[([^\]]+)\]', job)
    assert matrix is not None
    versions = re.findall(r'["\'](\d+\.\d+(?:\.\d+)?)["\']', matrix.group(1))
    assert versions == ['3.10', '3.15']
    assert 'python -m pytest -q tests/test_primary_config.py' in job


def test_renovate_floor_rule_is_narrow_and_allows_patch_updates():
    settings = json.loads((ROOT / 'renovate.json').read_text())
    rules = [rule for rule in settings['packageRules']
             if rule.get('matchManagers') == ['github-actions']
             and rule.get('matchPackageNames') == ['python']
             and rule.get('matchFileNames') == ['.github/workflows/test.yml']]
    assert len(rules) == 1
    rule = rules[0]
    assert rule['matchCurrentValue'] == r'/^3\.10(?:\.|$)/'
    assert rule['allowedVersions'] == '<3.11'
    assert rule.get('enabled', True) is True
    pattern = rule['matchCurrentValue'][1:-1]
    assert re.search(pattern, '3.10') and re.search(pattern, '3.10.22')
    assert not re.search(pattern, '3.15')
    assert not re.search(pattern, '3.11')
