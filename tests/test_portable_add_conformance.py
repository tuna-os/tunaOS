"""Shared portable-add plan v1 conformance corpus (#3475).

Every case under tests/fixtures/portable-add-plan-v1/ runs through the public
CLI (scripts/config-packages.py) exactly as a frontend would invoke it. The
only replaced seams are the container runner (subprocess.run) and the signed
APT fetch; nothing is pulled, run or downloaded.
"""
import functools
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import urllib.error

import pytest

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / 'tests/fixtures/portable-add-plan-v1'
sys.path.insert(0, str(ROOT / 'scripts'))
from lib import portable_add, signed_apt  # noqa: E402

SPEC = importlib.util.spec_from_file_location('config_packages_conformance', ROOT / 'scripts/config-packages.py')
cli = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cli)

CASES = sorted(path.name for path in CORPUS.iterdir() if path.is_dir())


def load(name):
    directory = CORPUS / name
    case = json.loads((directory / 'case.json').read_text(encoding='utf-8'))
    expected = json.loads((directory / 'expected.json').read_text(encoding='utf-8'))
    return directory, case, expected


def simulated(simulation, commands):
    def run(command, **kwargs):
        commands.append(command)
        return subprocess.CompletedProcess(command, simulation['returncode'],
                                           simulation['stdout'], simulation['stderr'])
    return run


def offline_fetch(reason):
    def fetch(url, limit):
        raise urllib.error.URLError(reason)
    return fetch


def invoke(directory, case, monkeypatch):
    """Run one case through the CLI; return (exit code, simulated container commands)."""
    commands = []
    if case['command'] == 'verify-transaction':
        monkeypatch.setattr(cli.subprocess, 'run', simulated(case['simulation'], commands))
        argv = ['verify-transaction', case['package'], '--plan', str(directory / 'plan.json'),
                '--image-target', case['image_target'], '--image', case['image']]
    else:
        monkeypatch.setattr(portable_add.signed_apt, 'acquire_catalog', functools.partial(
            signed_apt.acquire_catalog, fetch=offline_fetch(case['offline_source'])))
        argv = ['plan', case['package']]
        for option, key in (('--variant', 'variants'), ('--flavor', 'flavors'), ('--platform', 'platforms')):
            for value in case[key]:
                argv += [option, value]
    return cli.main(argv), commands


@pytest.mark.parametrize('name', CASES)
def test_case(name, monkeypatch, capsys):
    directory, case, expected = load(name)
    try:
        code, commands = invoke(directory, case, monkeypatch)
        captured = capsys.readouterr()
        if 'rejected' in expected:
            assert code == 1, f'accepted: {captured.out}'
            assert captured.err.startswith('ERROR: ') and expected['rejected'] in captured.err
        else:
            assert code == 0, captured.err
            assert json.loads(captured.out) == expected
            assert all('--pull=never' in command for command in commands)
    except Exception:
        if 'xfail' in case:
            pytest.xfail(case['xfail'])
        raise
    assert 'xfail' not in case, f'{name} now passes; promote it by removing "xfail": {case["xfail"]}'


def test_every_case_is_complete():
    assert CASES
    for name in CASES:
        directory, case, expected = load(name)
        assert set(expected) == {'rejected'} or 'transaction' in expected, name
        assert case['command'] in {'plan', 'verify-transaction'}
        assert (directory / 'plan.json').is_file() == (case['command'] == 'verify-transaction'), name
