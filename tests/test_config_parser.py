"""The declared TOML grammar and setup must not depend on the host stdlib."""
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


@pytest.mark.parametrize('version', ['2.2.1', '2.3.1', '2.4.0', '2.5.0', None])
def test_unsupported_backend_fails_before_any_parse(version):
    code = '''import runpy, sys, types
parser = types.ModuleType('tomli')
parser.__version__ = %r
def unexpected(*args, **kwargs):
    raise AssertionError('wrong backend was called')
parser.loads = unexpected
sys.modules['tomli'] = parser
runpy.run_path(sys.argv[1])
''' % version
    result = subprocess.run([sys.executable, '-c', code, str(ROOT / 'scripts/lib/tunaos_config.py')],
                            text=True, capture_output=True)
    assert result.returncode != 0
    assert 'requires tomli==2.3.2' in result.stderr
    assert 'python3 -m pip install -r requirements-config.txt' in result.stderr
    assert 'Traceback' not in result.stderr
    assert 'wrong backend was called' not in result.stderr


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


def config_steps():
    return yaml.safe_load((ROOT / '.github/actions/prepare-config/action.yml').read_text())['runs']['steps']


@pytest.mark.parametrize('pip_status', [0, 42])
def test_ci_installs_private_portable_parser_before_first_parse(tmp_path, pip_status):
    steps = config_steps()
    assert [step['name'] for step in steps] == [
        'Install primary config parser', 'Generate build configuration']
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir()
    python = bin_dir / 'python3'
    python.write_text(f'#!{sys.executable}\n' + '''import json, os, pathlib, sys
args = sys.argv[1:]
with open(os.environ['CALL_LOG'], 'a') as log:
    log.write(json.dumps(args) + '\\n')
if args[:3] == ['-m', 'pip', 'install']:
    assert '--only-binary=:all:' in args
    assert args[args.index('--platform') + 1] == 'any'
    assert '--no-deps' in args
    assert args[args.index('-r') + 1] == 'requirements-config.txt'
    if int(os.environ['PIP_STATUS']):
        sys.exit(int(os.environ['PIP_STATUS']))
    target = pathlib.Path(args[args.index('--target') + 1])
    assert target.parent == pathlib.Path(os.environ['RUNNER_TEMP'])
    (target / 'installed-parser').write_text('2.3.2')
else:
    assert args == ['scripts/config.py', 'generate']
    target = pathlib.Path(os.environ['PYTHONPATH'].split(os.pathsep)[0])
    assert (target / 'installed-parser').read_text() == '2.3.2'
''')
    python.chmod(0o755)
    github_env = tmp_path / 'github-env'
    github_env.touch()
    log = tmp_path / 'calls'
    env = {**os.environ, 'PATH': str(bin_dir) + os.pathsep + os.environ['PATH'],
           'RUNNER_TEMP': str(tmp_path), 'GITHUB_ENV': str(github_env),
           'CALL_LOG': str(log), 'PIP_STATUS': str(pip_status), 'PYTHONPATH': '/prior/path'}
    install = subprocess.run(['bash', '-e', '-o', 'pipefail', '-c', steps[0]['run']],
                             cwd=tmp_path, env=env, text=True, capture_output=True)
    assert install.returncode == pip_status, install.stderr
    if pip_status:
        assert github_env.read_text() == ''
        assert len(log.read_text().splitlines()) == 1
        return
    name, value = github_env.read_text().strip().split('=', 1)
    assert name == 'PYTHONPATH' and value.endswith(':/prior/path')
    env[name] = value
    generate = subprocess.run(['bash', '-e', '-o', 'pipefail', '-c', steps[1]['run']],
                              cwd=tmp_path, env=env, text=True, capture_output=True)
    assert generate.returncode == 0, generate.stderr
    assert len(log.read_text().splitlines()) == 2


def test_local_setup_precedes_test_config_read_and_normal_reads_do_not_install():
    recipes = (ROOT / 'just/utilities.just').read_text()
    assert 'setup: setup-config _ensure_test_deps' in recipes
    setup = recipes.split('\nsetup-config:', 1)[1].split('\n\n', 1)[0]
    assert 'python3 -m pip install -r "{{ justfile_directory() }}/requirements-config.txt"' in setup
    assert 'subprocess' not in (ROOT / 'scripts/lib/tunaos_config.py').read_text().split('def table(', 1)[0]


def test_wolfi_manifest_installs_pip_before_config_setup():
    workflow = yaml.safe_load((ROOT / '.github/workflows/reusable-build-image.yml').read_text())
    steps = workflow['jobs']['manifest']['steps']
    setup = next(i for i, step in enumerate(steps) if step.get('uses') == './.github/actions/prepare-config')
    install = next(i for i, step in enumerate(steps) if 'apk_install jq' in step.get('run', ''))
    assert install < setup
    assert 'yq python3 py3-pip' in steps[install]['run']


def test_new_stdlib_host_cannot_skip_the_grammar_gate():
    workflow = yaml.safe_load((ROOT / '.github/workflows/test.yml').read_text())
    job = workflow['jobs']['primary-config-python315']
    assert not job.get('continue-on-error', False)
    assert any(step.get('with', {}).get('python-version') == '3.15' for step in job['steps'])
    assert any('tests/test_config_parser.py' in step.get('run', '') for step in job['steps'])
    assert 'pytest.skip' not in (ROOT / 'tests/test_primary_config.py').read_text()


def test_target_build_consumers_use_generated_adapters_without_host_pythonpath():
    desktop = (ROOT / 'build_scripts/desktop/install-desktop.sh').read_text()
    contract = (ROOT / 'build_scripts/lib/desktop-contract.sh').read_text()
    assert 'manifests/desktops/' in desktop
    assert 'manifests/desktop-contracts/' in desktop
    assert 'sha256sum "$source"' in contract
    for text in (desktop, contract):
        assert 'scripts/config.py' not in text
        assert 'tunaos_config' not in text
        assert 'PYTHONPATH' not in text
    build = (ROOT / 'scripts/build-image-inner.sh').read_text()
    assert build.index('scripts/config.py prepare-debian-context') < build.index('${BUILDER} build')
