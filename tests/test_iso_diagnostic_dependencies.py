"""Source contracts only; never execute a workflow, installer or test recipe."""
import copy
from pathlib import Path
import re

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
REQUIREMENT = 'requirements-iso-diagnostic.txt'


def assert_direct_selections_have_decoder(workflow):
    for job in workflow.get('jobs', {}).values():
        installed = False
        for step in job.get('steps', []):
            script = step.get('run', '')
            installs = [command for command in re.split(r'\|\||\n', script)
                        if 'pip install' in command and REQUIREMENT in command]
            if installs:
                assert all('-r '+REQUIREMENT in command for command in installs)
                installed = True
            if re.search(r'\bpytest\b', script) and re.search(
                    r'(?:^|\s)(?:tests/?|tests/test_installed_boot_diagnostic.py)(?:\s|$)', script):
                assert installed, 'diagnostic test selection lacks decoder installation'


def test_clean_runner_selections_install_pinned_decoder():
    for path in (ROOT/'.github/workflows').glob('*.yml'):
        assert_direct_selections_have_decoder(yaml.load(path.read_text(), Loader=yaml.BaseLoader))
    workflow = yaml.load((ROOT/'.github/workflows/test.yml').read_text(), Loader=yaml.BaseLoader)
    assert REQUIREMENT in workflow['on']['pull_request']['paths']
    requirements = [line for line in (ROOT/REQUIREMENT).read_text().splitlines()
                    if line.strip() and not line.startswith('#')]
    assert requirements == ['zstandard==0.25.0']


def test_local_and_randomized_selections_share_dependency_setup():
    recipes = (ROOT/'just/utilities.just').read_text()
    setup = recipes.split('_ensure_test_deps:', 1)[1].split('\ntest:', 1)[0]
    installation = next(line for line in setup.splitlines() if REQUIREMENT in line)
    assert all('-r '+REQUIREMENT in part for part in installation.split('||'))
    for name in ('test', 'test-pytest', 'test-fast', 'test-random'):
        assert re.search(r'^'+name+r'(?:[^:\n]*):[^\n]*_ensure_test_deps$', recipes, re.M)
    randomized = (ROOT/'.github/workflows/randomized-tests.yml').read_text()
    assert 'just test-random' in randomized


def test_removing_ci_installation_breaks_contract():
    workflow = yaml.load((ROOT/'.github/workflows/test.yml').read_text(), Loader=yaml.BaseLoader)
    broken = copy.deepcopy(workflow)
    for step in broken['jobs']['unit-tests']['steps']:
        if 'run' in step:
            step['run'] = '\n'.join(line for line in step['run'].splitlines() if REQUIREMENT not in line)
    with pytest.raises(AssertionError, match='lacks decoder'):
        assert_direct_selections_have_decoder(broken)


@pytest.mark.parametrize('selection', ['tests/', 'tests', 'tests/test_installed_boot_diagnostic.py'])
def test_new_unprepared_selection_is_rejected(selection):
    with pytest.raises(AssertionError, match='lacks decoder'):
        assert_direct_selections_have_decoder({'jobs': {'new': {'steps': [
            {'run': 'python -m pytest '+selection}]}}})
