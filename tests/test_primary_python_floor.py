"""The primary-config jobs must keep the compatibility floor and current Python.
Falsification: removing Python 3.10 loses floor coverage; removing 3.15 loses
coverage against the standard library's newer TOML parser.
"""
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def test_primary_jobs_cover_python310_floor_and_python315():
    """One job runs the suite under 3.10 and then under 3.15.

    Each interpreter is set up, then the suite runs against it, in that order:
    a `setup-python` that is not followed by its own verify step would test the
    previous interpreter twice.
    """
    import yaml
    workflow = yaml.safe_load((ROOT / '.github/workflows/test.yml').read_text())
    assert 'primary-config-python310' not in workflow['jobs']
    assert 'primary-config-python315' not in workflow['jobs']
    steps = workflow['jobs']['primary-config']['steps']
    versions = [str(step['with']['python-version']) for step in steps
                if str(step.get('uses', '')).startswith('actions/setup-python@')]
    assert versions == ['3.10', '3.15']
    current = None
    verified = []
    for step in steps:
        if str(step.get('uses', '')).startswith('actions/setup-python@'):
            current = str(step['with']['python-version'])
        elif 'python -m pytest -q tests/test_primary_config.py' in step.get('run', ''):
            verified.append(current)
            if current == '3.15':
                assert step['if'] == '${{ !cancelled() }}', 'a 3.10 failure must not hide the 3.15 result'
    assert verified == ['3.10', '3.15']


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


def test_renovate_floor_rule_also_matches_by_dep_name():
    """The floor is pinned by depName as well as by packageName.

    Renovate listed this dependency as `python` (type uses-with) with the package
    actions/python-versions, and the matchPackageNames rule above did not stop
    PR #3552 moving the floor to 3.15. A second rule keyed on matchDepNames
    covers the name Renovate displays. Dropping either rule reopens the gap.
    """
    settings = json.loads((ROOT / 'renovate.json').read_text())
    rules = [rule for rule in settings['packageRules']
             if rule.get('matchManagers') == ['github-actions']
             and rule.get('matchDepNames') == ['python']
             and rule.get('matchFileNames') == ['.github/workflows/test.yml']]
    assert len(rules) == 1
    rule = rules[0]
    assert rule['matchCurrentValue'] == r'/^3\.10(?:\.|$)/'
    assert rule['allowedVersions'] == '<3.11'
    assert rule.get('enabled', True) is True
