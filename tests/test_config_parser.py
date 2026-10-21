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
    exported = dict(line.split('=', 1) for line in github_env.read_text().splitlines())
    assert exported['PYTHONPATH'] == exported['TUNAOS_CONFIG_PYTHONPATH'] + ':/prior/path'
    env.update(exported)
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


@pytest.mark.parametrize('filename,job', [
    ('check-base-image-pins.yml', 'package-repos'), ('corral-boot-gate.yml', 'gate'),
    ('live-iso-bootc.yml', 'build'), ('iso-e2e.yml', 'e2e'),
])
def test_independent_jobs_prepare_parser_after_checkout_before_commands(filename, job):
    steps = yaml.safe_load((ROOT / '.github/workflows' / filename).read_text())['jobs'][job]['steps']
    checkout = next(i for i, step in enumerate(steps) if step.get('uses', '').startswith('actions/checkout@'))
    setup = next(i for i, step in enumerate(steps) if step.get('uses') == './.github/actions/prepare-config')
    assert setup == checkout + 1


def privileged_prefixes():
    paths = ['reusable-build-image.yml', 'publish-iso-groups.yml', 'live-iso-bootc.yml',
             'iso-e2e.yml', 'installer-smoke.yml', 'installer-screenshots.yml',
             'luks-e2e.yml', 'weekly-desktop-screenshots.yml']
    result = []
    for name in paths:
        workflow = yaml.safe_load((ROOT / '.github/workflows' / name).read_text())
        for job in workflow['jobs'].values():
            for step in job.get('steps', []):
                for line in step.get('run', '').replace('\\\n', ' ').splitlines():
                    if line.lstrip().startswith('sudo ') and ('just iso' in line or 'just build' in line or '"$just" build' in line):
                        marker = 'timeout --kill-after' if 'timeout --kill-after' in line else 'just '
                        result.append((name, line[:line.index(marker)].strip()))
    workflow = yaml.safe_load((ROOT / '.github/workflows/luks-e2e.yml').read_text())
    for job in workflow['jobs'].values():
        for step in job.get('steps', []):
            for line in step.get('run', '').replace('\\\n', ' ').splitlines():
                if line.lstrip().startswith('sudo ') and './scripts/iso-e2e.sh' in line and '--luks' in line:
                    result.append(('luks-install', line[:line.index('./scripts/iso-e2e.sh')].strip()))
    for script in ('build-iso-group.sh', 'build-iso-tacklebox.sh'):
        line = next(line for line in (ROOT / 'Justfile').read_text().splitlines() if 'sudo ' in line and script in line)
        result.append(('Justfile:' + script, line[:line.index('bash ./scripts/' + script)].strip()))
    return result


@pytest.mark.parametrize('name,prefix', privileged_prefixes())
def test_private_parser_survives_sanitized_privileged_boundary(tmp_path, name, prefix):
    import shlex
    assert 'PYTHONPATH=${TUNAOS_CONFIG_PYTHONPATH:-}' in prefix, name
    private = tmp_path / 'private'
    private.mkdir()
    (private / 'private_parser_marker.py').write_text('VALUE = 232\n')
    bins = tmp_path / 'bin'
    bins.mkdir()
    sudo = bins / 'sudo'
    sudo.write_text(f'#!{sys.executable}\n' + '''import os, sys
args = sys.argv[1:]
keep = set()
while args and args[0].startswith('-'):
    flag = args.pop(0)
    if flag == '-E':
        keep.update(os.environ)
    elif flag.startswith('--preserve-env='):
        keep.update(flag.split('=', 1)[1].split(','))
env = {k: v for k, v in os.environ.items() if k in keep or k == 'PATH'}
env.pop('PYTHONPATH', None)
os.execvpe(args[0], args, env)
''')
    sudo.chmod(0o755)
    command = prefix + ' ' + shlex.quote(sys.executable) + ' -c ' + shlex.quote('import private_parser_marker; assert private_parser_marker.VALUE == 232')
    env = {**os.environ, 'PATH': str(bins) + os.pathsep + os.environ['PATH'],
           'TUNAOS_CONFIG_PYTHONPATH': str(private), 'PYTHONPATH': '/must/not/be/forwarded',
           'FISHERMAN_OVERRIDE': '', 'E2E_WALL_CLOCK_DEADLINE': '',
           'TUNAOS_E2E_VERIFY_TPM_AUTOUNLOCK': '', 'E2E_CHECKPOINT_STRICT': ''}
    result = subprocess.run(['/bin/bash', '-eu', '-c', command], env=env, text=True, capture_output=True)
    assert result.returncode == 0, (name, result.stderr)


@pytest.mark.parametrize('name', ['corral-build.sh', 'lifecycle-test.sh'])
def test_remote_build_sets_up_its_own_parser_before_build(name):
    source = (ROOT / 'scripts' / name).read_text()
    install = '/data/tunaos/.venv/bin/python -m pip install -r /data/tunaos/requirements-config.txt || exit 1'
    assert source.index('python3 -m venv /data/tunaos/.venv || exit 1') < source.index(install) < source.index('        just build ')
    assert 'export PATH=/data/tunaos/.venv/bin:\\$PATH' in source


@pytest.mark.parametrize('script', ['build-iso-group.sh', 'build-iso-tacklebox.sh'])
@pytest.mark.parametrize('mode', ['active-venv', 'explicit-spaces', 'missing', 'not-executable'])
def test_local_venv_iso_keeps_selected_interpreter_under_sudo(tmp_path, mode, script):
    import shlex
    import shutil
    repo = tmp_path / 'repository'
    (repo / 'scripts/lib').mkdir(parents=True)
    shutil.copyfile(ROOT / 'scripts/lib/build-config.sh', repo / 'scripts/lib/build-config.sh')
    # Use the current tested venv interpreter through a path containing spaces.
    selected = tmp_path / 'operator venv' / 'python3'
    selected.parent.mkdir()
    import tomli
    parser_path = str(Path(tomli.__file__).parent.parent)
    selected.write_text(f'#!/bin/sh\nexec env PYTHONPATH={shlex.quote(parser_path)} {shlex.quote(sys.executable)} -S "$@"\n')
    selected.chmod(0o755)
    (repo / 'scripts/config.py').write_text('import tomli\nassert tomli.__version__ == "2.3.2"\nprint(__file__)\n')
    (repo / 'scripts' / script).write_text('source ./scripts/lib/build-config.sh\ntunaos_build_config\n')
    bins = tmp_path / 'bin'
    bins.mkdir()
    sudo = bins / 'sudo'
    sudo.write_text('#!/bin/bash\nwhile [[ "$1" == -* ]]; do shift; done\nexec /usr/bin/env -i PATH=/usr/bin:/bin "$@"\n')
    sudo.chmod(0o755)
    (bins / 'python3').symlink_to(selected)
    line = next(line.strip() for line in (ROOT / 'Justfile').read_text().splitlines() if 'sudo ' in line and script in line)
    env = {**os.environ, 'PATH': str(bins) + os.pathsep + os.environ['PATH'], '_repo': 'local', '_tag': 'gnome'}
    env.pop('TUNAOS_CONFIG_PYTHONPATH', None)
    env.pop('TUNAOS_CONFIG_PYTHON', None)
    invalid = mode in ('missing', 'not-executable')
    if mode == 'explicit-spaces':
        env['TUNAOS_CONFIG_PYTHON'] = str(selected)
    elif mode == 'missing':
        env['TUNAOS_CONFIG_PYTHON'] = str(tmp_path / 'missing interpreter')
    elif mode == 'not-executable':
        selected.chmod(0o644)
        env['TUNAOS_CONFIG_PYTHON'] = str(selected)
    result = subprocess.run(['/bin/bash', '-eu', '-c', line], cwd=repo, env=env, text=True, capture_output=True)
    if invalid:
        assert result.returncode != 0
        assert 'config Python interpreter is unavailable' in result.stderr
    else:
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == str(repo / 'scripts/config.py')


@pytest.mark.parametrize('script,workflow', [
    ('build-iso-tacklebox.sh', 'live-iso-bootc.yml'),
    ('build-iso-group.sh', 'publish-iso-groups.yml'),
])
@pytest.mark.parametrize('dev', [False, True])
def test_actual_config_resolution_through_both_sudo_boundaries(tmp_path, script, workflow, dev):
    import shlex
    import shutil
    repo = tmp_path / 'repo'
    (repo / 'scripts').mkdir(parents=True)
    shutil.copytree(ROOT / 'scripts/lib', repo / 'scripts/lib', ignore=shutil.ignore_patterns('__pycache__'))
    for name in ('config.py', 'published-image-ref.sh'):
        shutil.copyfile(ROOT / 'scripts' / name, repo / 'scripts' / name)
    shutil.copyfile(ROOT / 'tunaos.toml', repo / 'tunaos.toml')
    bins = tmp_path / 'bin'
    bins.mkdir()
    # Model sudo's removal of Python variables even with -E and its secure PATH.
    sudo = bins / 'sudo'
    sudo.write_text(f'#!{sys.executable}\n' + '''import os, sys
args = sys.argv[1:]
keep = set()
while args and args[0].startswith('-'):
    flag = args.pop(0)
    if flag == '-E': keep.update(os.environ)
    elif flag.startswith('--preserve-env='): keep.update(flag.split('=', 1)[1].split(','))
env = {k: v for k, v in os.environ.items() if k in keep}
env.pop('PYTHONPATH', None)
env['PATH'] = ''' + repr(str(bins) + ':/usr/bin:/bin') + '''
os.execvpe(args[0], args, env)
''')
    sudo.chmod(0o755)
    # Only yq is stubbed: it reads the real generated JSON adapter.
    yq = bins / 'yq'
    yq.write_text(f'#!{sys.executable}\n' + '''import json, os, sys
v = next(v for v in json.load(open(sys.argv[-1]))['variants'] if v['id'] == os.environ['VARIANT_ID'])
print(v.get('tag_suffix', '') if 'tag_suffix' in sys.argv[2] else v.get('publish_name', v['id']))
''')
    yq.chmod(0o755)
    inner = next(line.strip() for line in (ROOT / 'Justfile').read_text().splitlines() if 'sudo ' in line and script in line)
    inner = inner[:inner.index('bash ./scripts/' + script)] + 'bash ./resolve.sh'
    if script == 'build-iso-tacklebox.sh':
        recipe = (ROOT / 'Justfile').read_text().split("iso variant=", 1)[1].split('\n# Build ONE', 1)[0]
        recipe = '\n'.join(line[4:] for line in recipe.splitlines()[1:] if line.startswith('    '))
        for name, value in {'variant': 'skipjack', 'flavor': 'gnome', 'tag': 'gnome', 'repo': 'local', 'dev': str(int(dev)), 'just': 'bash ./dev-build.sh'}.items():
            recipe = recipe.replace('{{ ' + name + ' }}', value)
        recipe = recipe.replace('bash ./scripts/build-iso-tacklebox.sh', 'bash ./resolve.sh')
        inner = recipe
        (repo / 'dev-build.sh').write_text('bash ./scripts/published-image-ref.sh skipjack gnome ghcr > dev-build-ref\n')
    (repo / 'inner.sh').write_text(inner + '\n')
    (repo / 'resolve.sh').write_text('source ./scripts/lib/image.sh\ntunaos_image_ref skipjack gnome ghcr\n')
    steps = yaml.safe_load((ROOT / '.github/workflows' / workflow).read_text())['jobs']
    outer = next(line.strip() for job in steps.values() for step in job.get('steps', [])
                 for line in step.get('run', '').replace('\\\n', ' ').splitlines()
                 if line.lstrip().startswith('sudo ') and 'just iso' in line)
    outer = outer[:outer.index('just iso')] + 'bash ./inner.sh'
    private = tmp_path / 'private parser'
    import tomli
    shutil.copytree(Path(tomli.__file__).parent, private / 'tomli')
    env = {**os.environ, 'PATH': str(bins) + os.pathsep + os.environ['PATH'],
           'TUNAOS_CONFIG_PYTHONPATH': str(private)}
    env.pop('TUNAOS_BUILD_CONFIG', None)
    env.pop('TUNAOS_CONFIG_PYTHON', None)
    result = subprocess.run(['/bin/bash', '-eu', '-c', outer], cwd=repo, env=env, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == 'ghcr.io/tuna-os/skipjack:gnome'
    assert (repo / '.github/build-config.yml').is_file()
    if script == 'build-iso-tacklebox.sh' and dev:
        assert (repo / 'dev-build-ref').read_text().strip() == 'ghcr.io/tuna-os/skipjack:gnome'


def test_remote_lifecycle_iso_uses_the_prepared_remote_interpreter():
    source = (ROOT / 'scripts/lifecycle-test.sh').read_text()
    assert 'sudo env TMPDIR=/data/tmp TUNAOS_CONFIG_PYTHON=/data/tunaos/.venv/bin/python bash ./scripts/build-iso-tacklebox.sh' in source
    custom = (ROOT / 'just/custom-overlay.just').read_text()
    assert '"TUNAOS_CONFIG_PYTHON=${TUNAOS_CONFIG_PYTHON:-$(command -v python3)}" bash ./scripts/build-iso-tacklebox.sh' in custom


@pytest.mark.parametrize('path', ['CONTRIBUTING.md', 'docs/AGENT_GUIDE.md'])
def test_clean_venv_quick_start_installs_workflow_yaml_dependency(path):
    source = (ROOT / path).read_text()
    assert source.index('just setup-config') < source.index('python3 -m pip install PyYAML') < source.index('just fix && just check')
