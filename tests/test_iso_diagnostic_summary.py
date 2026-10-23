"""Bounded diagnostic output must not expose arbitrary guest text."""
import importlib.util
import json
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    'iso_diagnostics', Path(__file__).parents[1] / 'scripts/collect-iso-diagnostics.py')
diagnostics = importlib.util.module_from_spec(spec)
spec.loader.exec_module(diagnostics)


def write_report(root, value):
    path = root / 'walkthrough-plain' / 'walkthrough-gnome.json'
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(value))
    return path


def test_summary_only_emits_allowlisted_observations(tmp_path, capsys):
    write_report(tmp_path, {
        'frames': [{'state': 'welcome', 'text': ['SECRET OCR']},
                   {'state': 'unknown'}, {'state': 'SECRET STATE'}],
        'transitions': ['welcome', 'SECRET TRANSITION'],
        'frontmost': True, 'submitted': False, 'accepted': False,
        'completed': False, 'error': 'SECRET ERROR', 'password': 'SECRET PASSWORD',
    })
    diagnostics.collect(tmp_path)
    output = capsys.readouterr().out
    assert 'SECRET' not in output
    reports = [json.loads(line.split(': ', 1)[1]) for line in output.splitlines()]
    assert reports[0] == {
        'mode': 'plain', 'diagnostic': 'available',
        'states': ['welcome', 'unknown', 'invalid'],
        'transitions': ['welcome', 'invalid'],
        'frontmost': True, 'submit_attempted': None, 'submitted': False,
        'accepted': False, 'completed': False, 'clicks': [],
    }
    assert reports[1] == {'mode': 'luks', 'diagnostic': 'unavailable'}


@pytest.mark.parametrize('value', [
    [], {'frames': 'SECRET', 'transitions': []},
    {'frames': [], 'transitions': 'SECRET'},
    {'frames': [{}] * 129, 'transitions': []},
    {'frames': [], 'transitions': ['welcome'] * 129},
])
def test_malformed_or_unbounded_report_is_unavailable(tmp_path, value):
    write_report(tmp_path, value)
    assert diagnostics.walkthrough_summary(tmp_path, 'plain') == {
        'mode': 'plain', 'diagnostic': 'unavailable'}


def test_non_boolean_outcomes_are_not_echoed(tmp_path):
    write_report(tmp_path, {'frames': [None], 'transitions': [],
                            'completed': 'SECRET', 'submitted': 1})
    result = diagnostics.walkthrough_summary(tmp_path, 'plain')
    assert result['states'] == ['invalid']
    assert result['completed'] is None
    assert result['submitted'] is None
    assert 'SECRET' not in json.dumps(result)


@pytest.mark.parametrize('raw', [b'{', b'\xff', b' ' * (1024 * 1024 + 1)])
def test_invalid_or_oversized_bytes_are_unavailable(tmp_path, raw):
    path = write_report(tmp_path, {})
    path.write_bytes(raw)
    assert diagnostics.walkthrough_summary(tmp_path, 'plain')['diagnostic'] == 'unavailable'


@pytest.mark.parametrize('mode', ['../outside', 'plain\nSECRET', None, ['plain']])
def test_invalid_mode_is_not_used_or_echoed(tmp_path, mode):
    assert diagnostics.walkthrough_summary(tmp_path, mode) == {
        'mode': 'invalid', 'diagnostic': 'unavailable'}


def test_collector_does_not_summarize_symlink_input(tmp_path, capsys):
    secret = tmp_path / 'outside.json'
    secret.write_text(json.dumps({'frames': [{'state': 'welcome'}],
                                 'transitions': [], 'completed': True}))
    directory = tmp_path / 'walkthrough-plain'
    directory.mkdir()
    (directory / 'walkthrough-gnome.json').symlink_to(secret)
    diagnostics.collect(tmp_path)
    reports = [json.loads(line.split(': ', 1)[1])
               for line in capsys.readouterr().out.splitlines()]
    assert reports == [{'mode': mode, 'diagnostic': 'unavailable'}
                       for mode in ('plain', 'luks')]
    assert not (tmp_path / 'strict-diagnostics/walkthrough-plain/walkthrough-gnome.json').exists()


def test_safe_click_geometry_and_uncertainty_exclude_secrets(tmp_path, capsys):
    click = {'action': 'submit-install', 'state': 'summary',
             'frame': [1280,800], 'box': [100,200,300,230], 'point': [200,215],
             'transport': 'uncertain', 'password': 'SECRET', 'text': 'SECRET'}
    write_report(tmp_path, {'frames': [], 'transitions': [],
                            'clicks': [click], 'submit_attempted': True,
                            'submitted': False, 'accepted': False, 'completed': False})
    diagnostics.collect(tmp_path)
    output = capsys.readouterr().out
    assert 'SECRET' not in output
    result = json.loads(output.splitlines()[0].split(': ',1)[1])
    assert result['submit_attempted'] is True
    assert not result['submitted'] and not result['completed']
    assert result['clicks'] == [{key: value for key, value in click.items()
                                if key not in ('password','text')}]


@pytest.mark.parametrize('field,value', [
    ('action','SECRET'), ('state','SECRET'), ('transport','SECRET'),
    ('box',[0,0,'SECRET',30]), ('box',[0,0,1921,30]),
    ('point',[True,10]), ('point',[1,2]), ('frame',[640,479]),
])
def test_invalid_click_fields_never_echo(tmp_path, field, value):
    click = {'action': 'welcome-install', 'state': 'welcome',
             'frame': [1280,800], 'box': [100,200,300,230],
             'point': [200,215], 'transport': 'server-response'}
    click[field] = value
    assert diagnostics.safe_click(click) == {'diagnostic': 'invalid'}


def test_click_list_is_bounded(tmp_path):
    write_report(tmp_path, {'frames': [], 'transitions': [], 'clicks': [{}]*33})
    assert diagnostics.walkthrough_summary(tmp_path, 'plain')['diagnostic'] == 'unavailable'
