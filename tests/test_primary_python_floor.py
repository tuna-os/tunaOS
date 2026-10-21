"""The primary-config jobs must keep the compatibility floor and current Python.
Falsification: removing Python 3.10 loses floor coverage; removing 3.15 loses
coverage against the standard library's newer TOML parser.
"""
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def test_primary_jobs_cover_python310_floor_and_python315():
    workflow = (ROOT / '.github/workflows/test.yml').read_text()
    for version in ('3.10', '3.15'):
        job_id = 'primary-config-python' + version.replace('.', '')
        section = re.split(r'\n(?=  \S)', workflow.split(f'  {job_id}:', 1)[1])[0]
        assert f"python-version: '{version}'" in section
    assert 'python -m pytest -q tests/test_primary_config.py' in workflow


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
