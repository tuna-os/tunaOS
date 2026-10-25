"""Offline consumer contract; fake native tools, no registry or image claims."""
import hashlib
import importlib.util
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('consumer', ROOT / 'scripts/install-oci-rpm-repository.py')
consumer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(consumer)


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    tool, key, packages, repos = [tmp_path / n for n in ('transport.py', 'key', 'packages', 'repos')]
    tool.write_text('# fixture')
    key.write_text('fixture public key')
    packages.write_text('gnome-shell\ngdm\n')
    repos.mkdir()
    (repos / 'distro.repo').write_text('[distro]\nbaseurl=https://distro.example/repo\nenabled=1\ngpgcheck=1\nrepo_gpgcheck=1\ngpgkey=' + key.as_uri() + '\n')
    monkeypatch.setattr(consumer, 'TRANSPORT_SHA256', hashlib.sha256(tool.read_bytes()).hexdigest())
    runtime = tmp_path / 'etc'
    runtime.mkdir()
    args = SimpleNamespace(runtime_config_root=runtime, transport=tool, key=key, packages=packages, upstream_repos=repos,
                           key_sha256=hashlib.sha256(key.read_bytes()).hexdigest(),
                           reference='ghcr.io/example/repository@sha256:' + 'a' * 64,
                           identity='https://github.com/example/repository/.github/workflows/publish.yml@refs/heads/main',
                           target='el10-x86_64', architecture='x86_64', priority=1)
    calls, workdirs = [], []

    def run(command, **kwargs):
        calls.append(command)
        if command[0] == 'dnf' and '--version' in command:
            return SimpleNamespace(stdout='4.24.0\n')
        if 'pull' in command:
            repo = Path(command[command.index('--destination') + 1])
            workdirs.append(repo.parent)
            (repo / 'repodata').mkdir(parents=True)
            (repo / 'repodata/repomd.xml').write_text('<repomd/>')
            (repo / 'repodata/repomd.xml.asc').write_text('signature')
            (repo / 'fixture.rpm').write_text('rpm')
        elif command[0] == 'dnf':
            root = workdirs[-1]
            assert 'best=1\n' in (root / 'dnf.conf').read_text()  # no silent older-package fallback
            config = (root / 'repos/tunaos-oci.repo').read_text()
            for required in ('gpgcheck=1\n', 'repo_gpgcheck=1\n', 'gpgkey=file://', 'baseurl=file://'):
                assert required in config
            assert not consumer.CONTROLLED.search(config)
            assert 'priority=1\n' in config
            assert '--noplugins' in command and '--config' in command
            assert command[-3:] == ['install', 'gnome-shell', 'gdm']
            assert (root / 'repos/distro.repo').is_file()
        if '--checksig' in command:
            return SimpleNamespace(stdout='fixture: digests signatures OK\n')
        if '-qp' in command:
            return SimpleNamespace(stdout='x86_64')
        return SimpleNamespace(stdout='gdm\t51.0-1\tx86_64\ngnome-shell\t51.0-1\tx86_64\n')

    monkeypatch.setattr(consumer.subprocess, 'run', run)
    return args, calls, workdirs, run


def test_pull_solver_inventory_order_and_cleanup(fixture):
    args, calls, workdirs, _ = fixture
    receipt = consumer.install(args)
    assert calls[0][0] == 'dnf' and '--version' in calls[0]
    assert 'pull' in calls[1]
    for flag in ('identity', 'target', 'reference', 'architecture'):
        assert calls[1][calls[1].index('--' + flag) + 1] == getattr(args, flag)
    dnf_index = next(i for i, c in enumerate(calls) if c[0] == 'dnf' and '--version' not in c)
    assert any('--verify' in c for c in calls[:dnf_index])
    assert any('--checksig' in c for c in calls[:dnf_index])
    assert calls[-1][0] == 'rpm' and '-qa' in calls[-1]
    assert receipt['priority'] == 1
    assert receipt['requested_packages'] == ['gnome-shell', 'gdm']
    assert len(receipt['installed_rpms']) == 2
    assert all(not p.exists() for p in workdirs)
    assert args.key.exists() and args.upstream_repos.exists()


@pytest.mark.parametrize('field,value', [
    ('reference', 'ghcr.io/example/repository:latest'), ('identity', 'https://github.com/example/.*'),
    ('priority', 0), ('priority', 100), ('target', '../escape'), ('architecture', 'ppc64le'), ('key_sha256', 'b' * 64),
])
def test_invalid_input_before_commands(fixture, field, value):
    args, calls, _, _ = fixture
    setattr(args, field, value)
    with pytest.raises(ValueError):
        consumer.install(args)
    assert calls == []


@pytest.mark.parametrize('name', ['transport', 'key'])
@pytest.mark.parametrize('failure', ['missing', 'changed', 'symlink'])
def test_required_reviewed_local_inputs(fixture, tmp_path, name, failure):
    args, calls, _, _ = fixture
    path = getattr(args, name)
    if failure == 'missing':
        path.unlink()
    elif failure == 'changed':
        path.write_text('changed')
    else:
        link = tmp_path / 'link'
        link.symlink_to(path)
        setattr(args, name, link)
    with pytest.raises(ValueError):
        consumer.install(args)
    assert calls == []


@pytest.mark.parametrize('url', ['https://repo.tunaos.org/public.gpg', 'https://download.tunaos.org/repo',
                                  'https://bucket.r2.cloudflarestorage.com/repo', 'https://public.r2.dev/key'])
def test_no_r2_in_upstream_keys_or_baseurls(fixture, url):
    args, calls, _, _ = fixture
    (args.upstream_repos / 'distro.repo').write_text('[distro]\ngpgkey=' + url)
    with pytest.raises(ValueError, match='R2 URL remains'):
        consumer.install(args)
    assert calls == []


@pytest.mark.parametrize('packages', ['', '--nogpgcheck\n', 'gnome-shell\n\n', 'https://host/rpm\n'])
def test_inventory_cannot_inject_flags(fixture, packages):
    args, calls, _, _ = fixture
    args.packages.write_text(packages)
    with pytest.raises(ValueError):
        consumer.install(args)
    assert calls == []


@pytest.mark.parametrize('stage', ['pull', 'dnf', 'rpm'])
def test_failures_clean_staging_and_no_fallback(fixture, monkeypatch, stage):
    args, calls, workdirs, run = fixture

    def fail(command, **kwargs):
        result = run(command, **kwargs)
        if stage in command and '--version' not in command:
            raise subprocess.CalledProcessError(1, command)
        return result

    monkeypatch.setattr(consumer.subprocess, 'run', fail)
    with pytest.raises(subprocess.CalledProcessError):
        consumer.install(args)
    assert all(not p.exists() for p in workdirs)
    assert not any('curl' in c or 'wget' in c for c in calls)
    if stage == 'pull':
        assert len(calls) == 2


def test_missing_metadata_blocks_solver(fixture, monkeypatch):
    args, calls, workdirs, run = fixture

    def missing(command, **kwargs):
        result = run(command, **kwargs)
        if 'pull' in command:
            (workdirs[-1] / 'repository/repodata/repomd.xml').unlink()
        return result

    monkeypatch.setattr(consumer.subprocess, 'run', missing)
    with pytest.raises(ValueError, match='metadata'):
        consumer.install(args)
    assert len(calls) == 2
    assert all(not p.exists() for p in workdirs)


@pytest.mark.parametrize('when', ['before', 'after'])
def test_persistent_r2_configs_block_even_if_disabled(fixture, monkeypatch, when):
    args, calls, workdirs, run = fixture
    target = args.runtime_config_root / 'yum.repos.d/legacy.repo'
    target.parent.mkdir()

    def write():
        target.write_text('[old]\nenabled=0\ngpgkey=https://repo.tunaos.org/public.gpg\n')

    if when == 'before':
        write()
    else:
        def generated(command, **kwargs):
            result = run(command, **kwargs)
            if command[0] == 'dnf' and '--version' not in command:
                write()
            return result
        monkeypatch.setattr(consumer.subprocess, 'run', generated)
    with pytest.raises(ValueError, match='R2 URL remains'):
        consumer.install(args)
    assert all(not p.exists() for p in workdirs)
    if when == 'before':
        assert calls == []


@pytest.mark.parametrize('content', [
    '[distro]\ngpgcheck=0\n', '[main]\nplugins=1\n',
    '[tunaos-oci]\nbaseurl=https://example.org\n',
    '[distro]\nbaseurl=https://${host}/repo\n',
    '[distro]\nmirrorlist=https://example.org\n',
    '[DEFAULT]\ngpgcheck=1\n',
])
def test_unsafe_upstream_config_rejected_before_transport(fixture, content):
    args, calls, _, _ = fixture
    (args.upstream_repos / 'distro.repo').write_text(content)
    with pytest.raises(ValueError):
        consumer.install(args)
    assert calls == []


@pytest.mark.parametrize('content', ['[main]\nreposdir=/etc/other\n',
                                     '[main]\nvarsdir=/tmp/vars\n',
                                     '[old]\nbaseurl=https://${host}/repo\n'])
def test_indirect_runtime_configs_fail_closed(fixture, content):
    args, calls, _, _ = fixture
    (args.runtime_config_root / 'yum.conf').write_text(content)
    with pytest.raises(ValueError):
        consumer.install(args)
    assert calls == []


@pytest.mark.parametrize('bad', ['unsigned', 'wrong-arch', 'missing-signature', 'bad-key'])
def test_native_trust_rejection_precedes_dnf(fixture, monkeypatch, bad):
    args, calls, workdirs, run = fixture

    def reject(command, **kwargs):
        result = run(command, **kwargs)
        if 'pull' in command and bad == 'missing-signature':
            (workdirs[-1] / 'repository/repodata/repomd.xml.asc').unlink()
        if '--checksig' in command and bad == 'unsigned':
            return SimpleNamespace(stdout='fixture: digests OK\n')
        if '-qp' in command and bad == 'wrong-arch':
            return SimpleNamespace(stdout='aarch64')
        if '--verify' in command and bad == 'bad-key':
            raise subprocess.CalledProcessError(1, command)
        return result

    monkeypatch.setattr(consumer.subprocess, 'run', reject)
    with pytest.raises((ValueError, subprocess.CalledProcessError)):
        consumer.install(args)
    assert not any(c[0] == 'dnf' and '--version' not in c for c in calls)
    assert all(not p.exists() for p in workdirs)


@pytest.mark.parametrize('url', ['https://repo%2Etunaos.org/repo', 'https://repo\\.tunaos.org/repo'])
def test_noncanonical_url_rejected(fixture, url):
    args, calls, _, _ = fixture
    path = args.upstream_repos / 'distro.repo'
    path.write_text(path.read_text().replace('https://distro.example/repo', url))
    with pytest.raises(ValueError):
        consumer.install(args)
    assert calls == []


def test_dnf5_refused_before_transport(fixture, monkeypatch):
    args, calls, _, run = fixture

    def version(command, **kwargs):
        result = run(command, **kwargs)
        if command[0] == 'dnf' and '--version' in command:
            return SimpleNamespace(stdout='dnf5 version 5.2.0\n')
        return result

    monkeypatch.setattr(consumer.subprocess, 'run', version)
    with pytest.raises(ValueError, match='only DNF4'):
        consumer.install(args)
    assert len(calls) == 1


def test_upstream_key_snapshotted_and_receipted(fixture, monkeypatch):
    args, _calls, workdirs, run = fixture
    original = args.key.read_bytes()

    def replaced(command, **kwargs):
        if 'pull' in command:
            args.key.write_text('changed after validation')
        result = run(command, **kwargs)
        if command[0] == 'dnf' and '--version' not in command:
            root = workdirs[-1]
            config = (root / 'repos/distro.repo').read_text()
            assert args.key.as_uri() not in config
            assert (root / ('upstream-key-' + hashlib.sha256(original).hexdigest())).read_bytes() == original
            assert kwargs['stdout'] is consumer.sys.stderr
        return result

    monkeypatch.setattr(consumer.subprocess, 'run', replaced)
    receipt = consumer.install(args)
    assert receipt['upstream_keys'][args.key.as_uri()] == hashlib.sha256(original).hexdigest()



def test_transport_isolated_and_dnf_vars_filtered(fixture, monkeypatch):
    args, _calls, _workdirs, run = fixture
    monkeypatch.setenv('DNF_VAR_HOST', 'repo.tunaos.org')

    def isolated(command, **kwargs):
        if 'pull' in command:
            assert command[1] == '-I'
            assert kwargs['stdout'] is consumer.sys.stderr
        if command[0] == 'dnf':
            assert '--noplugins' in command and '--config' in command
            assert 'DNF_VAR_HOST' not in kwargs['env']
            assert any(c.startswith('--setopt=varsdir=') for c in command)
        return run(command, **kwargs)

    monkeypatch.setattr(consumer.subprocess, 'run', isolated)
    consumer.install(args)



def test_overlapping_key_paths_rewritten_per_section(fixture, monkeypatch):
    args, _calls, workdirs, run = fixture
    extra = args.key.with_name(args.key.name + '-extra')
    extra.write_text('other reviewed public key')
    path = args.upstream_repos / 'distro.repo'
    path.write_text(path.read_text() + path.read_text().replace('[distro]', '[extra]').replace(args.key.as_uri(), extra.as_uri()))

    def check(command, **kwargs):
        result = run(command, **kwargs)
        if command[0] == 'dnf' and '--version' not in command:
            parser = consumer.configparser.ConfigParser()
            parser.read(workdirs[-1] / 'repos/distro.repo')
            for section, original in [('distro', args.key), ('extra', extra)]:
                path = Path(consumer.urlsplit(parser[section]['gpgkey']).path)
                assert path.read_bytes() == original.read_bytes()
        return result

    monkeypatch.setattr(consumer.subprocess, 'run', check)
    consumer.install(args)


@pytest.fixture
def el10_layout(fixture, monkeypatch):
    """Mirror the pinned centos-bootc c10s /etc: yum/vars -> ../dnf/vars, yum.conf -> dnf/dnf.conf."""
    args, calls, _, _ = fixture
    etc = args.runtime_config_root
    monkeypatch.setattr(consumer, 'TRUSTED_UID', os.getuid())
    (etc / 'dnf/vars').mkdir(parents=True)
    (etc / 'dnf/vars/stream').write_text('10-stream\n')
    (etc / 'dnf/dnf.conf').write_text('[main]\ngpgcheck=1\ninstallonly_limit=3\n')
    (etc / 'yum.repos.d').mkdir()
    (etc / 'yum').mkdir()
    (etc / 'yum/vars').symlink_to('../dnf/vars')
    (etc / 'yum.conf').symlink_to('dnf/dnf.conf')
    for path in (etc / 'dnf', etc / 'dnf/vars', etc / 'yum.repos.d', etc / 'yum'):
        path.chmod(0o755)
    (etc / 'dnf/dnf.conf').chmod(0o644)
    (etc / 'dnf/vars/stream').chmod(0o644)
    return args, calls, etc


def test_observed_el10_symlink_layout_is_admitted(el10_layout):
    args, calls, _ = el10_layout
    consumer.check_runtime_configs(args.runtime_config_root)
    consumer.install(args)
    assert any(command[0] == 'dnf' and 'install' in command for command in calls)


def test_symlinked_config_content_is_still_scanned(el10_layout):
    args, _, etc = el10_layout
    (etc / 'dnf/vars/infra').write_text('https://repo.tunaos.org/x\n')
    with pytest.raises(ValueError, match='controlled R2'):
        consumer.check_runtime_configs(etc)
    (etc / 'dnf/vars/infra').unlink()
    (etc / 'dnf/dnf.conf').write_text('[main]\nreposdir=/elsewhere\n')
    with pytest.raises(ValueError, match='alternate config'):
        consumer.check_runtime_configs(etc)


def escape_outside(etc):
    outside = etc.parent / 'outside-vars'
    outside.mkdir()
    (etc / 'yum/vars').unlink()
    (etc / 'yum/vars').symlink_to(outside)


def dangling(etc):
    (etc / 'yum/vars').unlink()
    (etc / 'yum/vars').symlink_to('../dnf/missing')


def chained(etc):
    (etc / 'dnf/real-vars').mkdir()
    (etc / 'dnf/vars/stream').unlink()
    (etc / 'dnf/vars').rmdir()
    (etc / 'dnf/vars').symlink_to('real-vars')


def world_writable_target(etc):
    (etc / 'dnf/vars').chmod(0o777)


def group_writable_parent(etc):
    (etc / 'dnf').chmod(0o775)


def foreign_owner(etc):
    consumer.TRUSTED_UID = os.getuid() + 1


@pytest.mark.parametrize('mutate,message', [
    (escape_outside, 'leaves the reviewed tree'),
    (dangling, 'dangling'),
    (chained, 'not a plain root-owned path'),
    (world_writable_target, 'not a plain root-owned path'),
    (group_writable_parent, 'not a plain root-owned path'),
    (foreign_owner, 'not owned by the trusted user'),
])
def test_unsafe_runtime_symlinks_are_refused_before_dnf(el10_layout, mutate, message):
    args, calls, etc = el10_layout
    mutate(etc)
    with pytest.raises(ValueError, match=message):
        consumer.install(args)
    assert calls == []


def test_symlinked_parent_directory_is_refused(el10_layout):
    args, calls, etc = el10_layout
    (etc / 'yum/vars').unlink()
    (etc / 'yum').rmdir()
    (etc / 'yum').symlink_to('dnf')
    with pytest.raises(ValueError, match='parent is a symlink'):
        consumer.install(args)
    assert calls == []


def test_file_symlink_escaping_the_tree_is_refused(el10_layout):
    args, calls, etc = el10_layout
    (etc / 'yum.conf').unlink()
    (etc / 'yum.conf').symlink_to('../outside.conf')
    with pytest.raises(ValueError, match='leaves the reviewed tree'):
        consumer.install(args)
    assert calls == []


EPEL = ('[epel]\nbaseurl=https://dl.fedoraproject.org/pub/epel/10/Everything/x86_64/\nenabled=1\n'
        'gpgcheck=1\nrepo_gpgcheck=0\npriority=99\ngpgkey=KEY\n')


def test_only_the_reviewed_epel_repo_may_skip_metadata_signatures(fixture):
    args, _, _, _ = fixture
    key = args.key.as_uri()
    (args.upstream_repos / 'epel.repo').write_text(EPEL.replace('KEY', key))
    assert [n for n, _, _ in consumer.upstream_configs(args.upstream_repos)] == ['distro.repo', 'epel.repo']


@pytest.mark.parametrize('change', [
    ('[epel]', '[centos]'),
    ('dl.fedoraproject.org', 'mirrors.fedoraproject.org'),
    ('dl.fedoraproject.org', 'dl.fedoraproject.org.evil.example'),
    ('gpgcheck=1', 'gpgcheck=0'),
    ('repo_gpgcheck=0', 'repo_gpgcheck=false'),
    ('enabled=1', 'enabled=0'),
])
def test_metadata_signature_exception_is_exactly_epel(fixture, change):
    args, calls, _, _ = fixture
    (args.upstream_repos / 'distro.repo').write_text(EPEL.replace('KEY', args.key.as_uri()).replace(*change))
    with pytest.raises(ValueError, match='signatures'):
        consumer.install(args)
    assert calls == []


def test_other_repository_cannot_disable_metadata_signatures(fixture):
    args, calls, _, _ = fixture
    (args.upstream_repos / 'distro.repo').write_text(
        '[distro]\nbaseurl=https://distro.example/repo\nenabled=1\ngpgcheck=1\nrepo_gpgcheck=0\ngpgkey=' + args.key.as_uri() + '\n')
    with pytest.raises(ValueError, match='signatures'):
        consumer.install(args)
    assert calls == []


@pytest.mark.parametrize('entry', ['unsigned.rpm', 'UNSIGNED.RPM', 'gdm.rpm', 'a.b.rpm', './unsigned.rpm',
                                   '/tmp/unsigned.rpm', '@gnome-desktop', '-y', '*', 'a b', 'gdm;x',
                                   'https://h/x.rpm', '$(id)', 'a\tb'])
def test_inventory_admits_repository_package_names_only(fixture, entry):
    args, calls, _, _ = fixture
    args.packages.write_text(f'gdm\n{entry}\n')
    with pytest.raises(ValueError, match='explicit package name'):
        consumer.install(args)
    assert calls == []


def test_a_local_rpm_never_reaches_dnf_even_when_present_in_the_working_directory(fixture, tmp_path, monkeypatch):
    args, calls, _, _ = fixture
    monkeypatch.chdir(tmp_path)
    (tmp_path / 'unsigned.rpm').write_bytes(b'unsigned')
    args.packages.write_text('unsigned.rpm\n')
    with pytest.raises(ValueError):
        consumer.install(args)
    assert not any('unsigned.rpm' in str(command) for command in calls)


def test_symlink_text_is_walked_in_traversal_order(el10_layout):
    """yum/vars -> ../dnf/redirect/../vars with dnf/redirect -> an outside dir reaches <outside>/vars."""
    args, calls, etc = el10_layout
    outside = etc.parent / 'outside' / 'subdir'
    outside.mkdir(parents=True)
    (outside.parent / 'vars').mkdir()
    (outside.parent / 'vars/infra').write_text('https://repo.tunaos.org/x\n')
    (etc / 'dnf/redirect').symlink_to(outside)
    (etc / 'yum/vars').unlink()
    (etc / 'yum/vars').symlink_to('../dnf/redirect/../vars')
    assert os.path.realpath(etc / 'yum/vars') == str(outside.parent / 'vars')  # what the kernel reaches
    with pytest.raises(ValueError, match='not a plain root-owned path'):
        consumer.install(args)
    with pytest.raises(ValueError, match='not a plain root-owned path'):
        consumer.check_runtime_configs(etc)
    assert calls == []


def test_file_link_through_a_symlinked_component_is_refused(el10_layout):
    args, calls, etc = el10_layout
    outside = etc.parent / 'outside' / 'subdir'
    outside.mkdir(parents=True)
    (outside.parent / 'dnf.conf').write_text('[main]\nreposdir=/evil\n')
    (etc / 'dnf/redirect').symlink_to(outside)
    (etc / 'yum.conf').unlink()
    (etc / 'yum.conf').symlink_to('dnf/redirect/../dnf.conf')
    with pytest.raises(ValueError, match='not a plain root-owned path'):
        consumer.install(args)
    assert calls == []


@pytest.mark.parametrize('text,message', [
    ('../../etc/dnf/vars', 'leaves the reviewed tree'),
    ('../..', 'leaves the reviewed tree'),
    ('..', 'leaves the reviewed tree'),
    ('../yum', 'leaves the reviewed tree'),
    ('../dnf/vars/../../yum', 'leaves the reviewed tree'),
    ('../dnf/../dnf/vars', None),
    ('../dnf/./vars', None),
    ('..//dnf//vars', None),
])
def test_dot_dot_and_empty_components_never_widen_the_tree(el10_layout, text, message):
    args, _, etc = el10_layout
    (etc / 'yum/vars').unlink()
    (etc / 'yum/vars').symlink_to(text)
    if message is None:
        consumer.check_runtime_configs(etc)
    else:
        with pytest.raises(ValueError, match=message):
            consumer.check_runtime_configs(etc)
