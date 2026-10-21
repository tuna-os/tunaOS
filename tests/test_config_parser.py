"""The declared TOML grammar must not depend on the host stdlib.

Falsification: ambient parsers, damaged source copies, or resource-heavy input
change accepted grammar, bypass source verification, or corrupt generated files.
"""
import importlib.util
import os
from pathlib import Path
import subprocess
import sys

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('parser_policy', ROOT / 'scripts/lib/tunaos_config.py')
config = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(config)


@pytest.mark.parametrize('version', ['2.2.1', '2.3.2', '2.4.0', '2.5.0', None])
def test_ambient_backends_are_never_selected(version):
    code = """import runpy, sys, types
parser = types.ModuleType('tomli')
parser.__version__ = %r
def unexpected(*args, **kwargs):
    raise AssertionError('ambient backend was called')
parser.loads = unexpected
sys.modules['tomli'] = parser
sys.modules['tomllib'] = parser
module = runpy.run_path(sys.argv[1])
assert module['parse']('value=1') == {'value': 1}
assert module['tomllib'].__version__ == '2.3.2'
""" % version
    result = subprocess.run([sys.executable, '-S', '-c', code, str(ROOT / 'scripts/lib/tunaos_config.py')],
                            text=True, capture_output=True)
    assert result.returncode == 0, result.stderr


def test_toml10_literals_comments_and_multiline_strings_remain_valid():
    source = '''# literal text: \\x41, \\e, {a=1,}
literal = '\\x41 \\e {a=1,}'
multiline = """line one
line two"""
inline = {key = 1}
array = [1, 2,]
'''
    parsed = config.parse(source)
    assert parsed['literal'] == r'\x41 \e {a=1,}'
    assert parsed['multiline'] == 'line one\nline two'
    assert parsed['inline'] == {'key': 1}
    assert parsed['array'] == [1, 2]


def hostile_sources():
    return ['value = ' + '[' * 1000 + '0' + ']' * 1000,
            '.'.join(['part'] * (sys.getrecursionlimit() + 1)) + '=1',
            b'value = "\xff"', 'value = {key=1,}']


@pytest.mark.parametrize('source', hostile_sources())
def test_parse_limits_and_invalid_utf8_are_config_errors(source):
    with pytest.raises(config.ConfigError, match='input.toml:'):
        config.parse(source, 'input.toml')


@pytest.mark.parametrize('command', ['generate', 'generate-debian-contract', 'verify-debian-image'])
@pytest.mark.parametrize('source', hostile_sources())
def test_rejected_input_preserves_files_and_has_no_traceback(tmp_path, command, source):
    primary = tmp_path / 'tunaos.toml'
    data = source.encode() if isinstance(source, str) else source
    primary.write_bytes(data)
    adapter = tmp_path / '.github/build-config.yml'
    adapter.parent.mkdir()
    adapter.write_bytes(b'prior generated data\n')
    args = [sys.executable, str(ROOT / 'scripts/config.py'), command, '--root', str(tmp_path)]
    if command != 'generate':
        args += ['--variant', 'flounder', '--desktop', 'gnome', '--platform', 'linux/amd64']
    if command == 'verify-debian-image':
        args += ['--image', 'must-not-be-inspected']
    result = subprocess.run(args, text=True, capture_output=True, timeout=15)
    assert result.returncode == 1, result.stderr
    assert 'ERROR:' in result.stderr and 'Traceback' not in result.stderr
    assert primary.read_bytes() == data
    assert adapter.read_bytes() == b'prior generated data\n'
    assert sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob('*') if p.is_file()) == [
        '.github/build-config.yml', 'tunaos.toml']


def test_parser_nesting_limit_also_survives_a_worker_thread():
    # A subprocess makes an interpreter crash a failed test, not a lost suite.
    code = '''import runpy, sys, threading
config = runpy.run_path(sys.argv[1])
errors = []
def parse():
    try:
        config['parse']('value=' + '[' * 1000 + '0' + ']' * 1000)
    except config['ConfigError']:
        errors.append('limited')
worker = threading.Thread(target=parse)
worker.start()
worker.join()
assert errors == ['limited']
'''
    result = subprocess.run([sys.executable, '-c', code, str(ROOT / 'scripts/lib/tunaos_config.py')],
                            text=True, capture_output=True, timeout=15)
    assert result.returncode == 0, result.stderr



def vendor_checker():
    spec = importlib.util.spec_from_file_location('vendor_check', ROOT / 'scripts/check-vendored-parser.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_vendored_source_and_provenance_match():
    assert vendor_checker().check()['version'] == config.TOMLI_VERSION


@pytest.mark.parametrize('change', ['bytes', 'version', 'unknown', 'missing', 'extra'])
def test_vendored_source_drift_fails_offline(tmp_path, change):
    import json
    import shutil
    vendor = tmp_path / 'scripts/lib/_vendor'
    shutil.copytree(ROOT / 'scripts/lib/_vendor', vendor, ignore=shutil.ignore_patterns('__pycache__'))
    manifest = vendor / 'tomli-provenance.json'
    if change == 'bytes':
        (vendor / 'tomli/_parser.py').write_text('# changed\n')
    elif change == 'missing':
        (vendor / 'tomli/_parser.py').unlink()
    elif change == 'extra':
        (vendor / 'tomli/extra.py').write_text('# unexpected\n')
    else:
        data = json.loads(manifest.read_text())
        data['version' if change == 'version' else 'unknown'] = '2.5.0'
        manifest.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        vendor_checker().check(tmp_path)


def test_upstream_comparison_uses_exact_reviewed_bytes(tmp_path):
    import shutil
    upstream = tmp_path / 'upstream'
    shutil.copytree(ROOT / 'scripts/lib/_vendor/tomli', upstream / 'src/tomli', ignore=shutil.ignore_patterns('__pycache__'))
    shutil.copyfile(upstream / 'src/tomli/LICENSE', upstream / 'LICENSE')
    vendor_checker().check(upstream=upstream)
    (upstream / 'src/tomli/_parser.py').write_text('# upstream changed\n')
    with pytest.raises(ValueError, match='upstream parser bytes differ'):
        vendor_checker().check(upstream=upstream)


@pytest.mark.parametrize('style', ['runpy', 'file-spec', 'package'])
def test_parser_loads_without_site_packages_or_pythonpath(style):
    code = {
        'runpy': 'import runpy; c=runpy.run_path("scripts/lib/tunaos_config.py"); assert c["load"]()["schema_version"]==1',
        'file-spec': 'import importlib.util; s=importlib.util.spec_from_file_location("copied_config", "scripts/lib/tunaos_config.py"); c=importlib.util.module_from_spec(s); s.loader.exec_module(c); assert c.load()["schema_version"]==1',
        'package': 'import sys; sys.path.insert(0,"scripts"); from lib import tunaos_config as c; assert c.load()["schema_version"]==1',
    }[style]
    env = {k: v for k, v in os.environ.items() if k not in ('PYTHONPATH', 'TUNAOS_CONFIG_PYTHONPATH', 'TUNAOS_CONFIG_PYTHON')}
    result = subprocess.run([sys.executable, '-S', '-c', code], cwd=ROOT, env=env, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr


def test_supported_host_jobs_keep_the_same_grammar_gate():
    workflow = yaml.safe_load((ROOT / '.github/workflows/test.yml').read_text())
    for version in ('310', '315'):
        job = workflow['jobs']['primary-config-python' + version]
        assert not job.get('continue-on-error', False)
        assert any('tests/test_config_parser.py' in step.get('run', '') for step in job['steps'])
    assert 'pytest.skip' not in (ROOT / 'tests/test_primary_config.py').read_text()
