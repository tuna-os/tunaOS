"""Portable add resolves every selected target first and never guesses names.

Planning uses the real primary config, catalog schema and both reviewed
observation bindings; only signed network acquisition is replaced. Transaction
verification uses a fake process runner; no image is pulled or run.
"""
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from lib import package_catalogs, portable_add, tunaos_config  # noqa: E402

NOW = datetime(2026, 10, 24, tzinfo=timezone.utc)
FLOUNDER_COVERED = ['flounder:base:linux/amd64', 'flounder:kde:linux/amd64',
                    'flounder:xfce:linux/amd64']
SPEC = importlib.util.spec_from_file_location('config_packages_cli', ROOT / 'scripts/config-packages.py')
cli = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cli)


def target_tree(root):
    """Copy the files the reviewed target observation binds."""
    for name in ('config', 'build_scripts'):
        shutil.copytree(ROOT / name, root / name)
    (root / 'scripts').mkdir()
    for name in ('Containerfile.debian', 'image-versions.yaml', 'scripts/build-image-inner.sh'):
        shutil.copy(ROOT / name, root / name)


def source_result(source, names):
    build = source == 'tailscale'
    result = {'source': source, 'role': 'build' if build else 'base',
              'source_url': f'https://example.invalid/{source}/InRelease', 'release': 'trixie',
              'architecture': 'amd64', 'signed_at': '2026-10-23T00:00:00+00:00',
              'retrieved_at': NOW.isoformat(), 'inrelease_sha256': 'a' * 64,
              'keyring_sha256': 'b' * 64, 'indexes': [{'url': 'u', 'sha256': 'c' * 64, 'size': 1}],
              'names': set(names), 'signers': ['A' * 40],
              'freshness': {'mode': 'signed-valid-until', 'expires': None}}
    if build:
        result.update(declaration_sha256='d' * 64, remote_keyring_sha256='b' * 64)
    return result


OBSERVED_AT = json.loads(
    (ROOT / 'config/package-observations/flounder-target-amd64.json').read_text(encoding='utf-8'))['observed_at']


def acquirer(base_names=('htop', 'btop', 'bashtop'), calls=None):
    def acquire(catalog, keyring_for, now):
        assert all(len(keyring_for(source)) > 0 for source in catalog['sources'])
        if calls is not None:
            calls.append(catalog['variant'])
        return [source_result('trixie', base_names), source_result('trixie-updates', ()),
                source_result('trixie-security', ()), source_result('tailscale', ('tailscale',))]
    return acquire


def plan(query='htop', native=None, acquire=None, document=None, root=ROOT, **selection):
    document = document or tunaos_config.load()
    selected = portable_add.select_targets(document, **selection)
    return portable_add.plan(document, root, query, selected, native, now=NOW,
                             acquire=acquire or acquirer())


def flounder_covered():
    return dict(variants=['flounder'], flavors=['base', 'kde', 'xfce'], platforms=['linux/amd64'])


def failure(**kwargs):
    with pytest.raises(portable_add.PortableAddError) as raised:
        plan(**kwargs)
    return raised.value.report, str(raised.value)


def by_target(report):
    return {record['target']: record for record in report['targets']}


def test_htop_resolves_on_every_covered_target_with_separate_evidence_layers():
    calls = []
    report = plan(acquire=acquirer(calls=calls), **flounder_covered())
    assert report['complete'] is True and report['resolved_targets'] == 3
    assert calls == ['flounder']  # One authenticated collection serves all three flavors.
    for name, record in by_target(report).items():
        assert name in FLOUNDER_COVERED
        assert record['status'] == 'resolved' and record['native_name'] == 'htop'
        assert record['mapping'] == 'exact'
        assert record['index_availability']['status'] == 'present'
        assert record['index_availability']['matched_sources'] == ['trixie']
        assert len(record['index_availability']['sources']) == 4
        assert record['transaction'] == {'status': 'not-run'}
        assert record['installed_image'] == {'status': 'not-run'}
        assert record['base_image'].startswith('docker.io/library/debian:trixie@sha256:')
        assert record['configuration_observed_at'] == OBSERVED_AT
    json.dumps(report)  # Evidence is serializable; no sets leak into the plan.


def test_native_acquisition_results_resolve_the_supported_plan_without_authorizing_a_write():
    from tests.test_signed_apt import fake_catalog

    catalog, fetch, verify, *_ = fake_catalog()
    acquired = portable_add.signed_apt.acquire_catalog(
        catalog, lambda _: b'key', datetime(2026, 10, 21, tzinfo=timezone.utc), fetch, verify,
    )
    report = plan(acquire=lambda *_: acquired, **flounder_covered())
    assert report['complete'] is True
    assert {row['native_name'] for row in report['targets']} == {'htop'}
    assert report['emission']['status'] == 'blocked'
    sources = report['targets'][0]['index_availability']['sources']
    for source in sources:
        native = next(item for item in acquired if item['source'] == source['source'])
        assert source['signers'] == native['signers']
        if source['role'] == 'base':
            assert 'declaration_sha256' not in source
            assert 'remote_keyring_sha256' not in source
        else:
            expected = next(item for item in catalog['sources'] if item['id'] == source['source'])
            assert source['declaration_sha256'] == expected['declaration_sha256']
            assert source['remote_keyring_sha256'] == expected['keyring_sha256']


def test_subset_never_claims_variant_or_all_base_emission():
    report = plan(**flounder_covered())
    assert report['emission']['status'] == 'blocked'
    for uncovered in ('flounder:base:linux/arm64', 'flounder:tuna:linux/amd64',
                      'flounder:kde-nvidia:linux/amd64', 'flounder:xfce-nvidia:linux/amd64'):
        assert uncovered in report['emission']['reason']


def test_all_targets_fail_atomically_with_actionable_per_target_results():
    report, message = failure()
    records = by_target(report)
    assert report['complete'] is False
    assert report['selected_targets'] == len(portable_add.enabled_targets(tunaos_config.load()))
    assert report['resolved_targets'] == 3
    assert report['emission']['status'] == 'blocked'
    for variant in ('yellowfin', 'guppy', 'marlin', 'gurnard', 'grouper', 'flounder-sid'):
        record = next(r for r in records.values() if r['variant'] == variant)
        assert record['status'] == 'unsupported'
        assert 'native-adapter-inventory' in record['reason']
        assert 'native_name' not in record
        assert record['index_availability'] == {'status': 'not-collected'}
    assert records['flounder:base:linux/arm64']['status'] == 'unsupported'
    assert 'nothing emitted' in message


def test_gentoo_atom_is_never_guessed_even_with_an_explicit_mapping():
    target = 'guppy:base:linux/amd64'
    report, _ = failure(native={target: 'sys-process/htop'}, variants=['guppy'])
    record = by_target(report)[target]
    assert record['status'] == 'unsupported' and record['mapping'] == 'explicit'
    assert 'native_name' not in record


def test_differently_named_package_needs_explicit_mapping_present_in_index():
    target = 'flounder:kde:linux/amd64'
    report = plan(query='htop', native={target: 'btop'}, **flounder_covered())
    assert by_target(report)[target]['native_name'] == 'btop'
    assert by_target(report)[target]['mapping'] == 'explicit'
    report, _ = failure(query='htop', native={target: 'htop-renamed'}, **flounder_covered())
    assert by_target(report)[target]['status'] == 'missing'
    assert by_target(report)[target]['index_availability']['status'] == 'absent'


def test_similar_names_are_not_matches():
    report, message = failure(query='htopx', **flounder_covered())
    assert {record['status'] for record in report['targets']} == {'missing'}
    assert '3 of 3' in message
    report, _ = failure(query='bash', acquire=acquirer(('bashtop',)), **flounder_covered())
    assert all('native_name' not in record for record in report['targets'])


def test_mapping_must_name_a_selected_target_and_be_unique():
    with pytest.raises(portable_add.PortableAddError, match='must name selected targets'):
        plan(native={'yellowfin:base:linux/amd64': 'htop'}, **flounder_covered())
    with pytest.raises(cli.author.AuthoringError, match='unique'):
        cli.assignments(['flounder:kde:linux/amd64=a', 'flounder:kde:linux/amd64=b'], '--native')


def test_names_differing_within_one_variant_block_emission():
    document = tunaos_config.load()
    records = [{'target': t, 'variant': 'flounder', 'native_name': 'htop'}
               for t in (portable_add.target_id(*x) for x in portable_add.enabled_targets(document)
                         if x[0] == 'flounder')]
    assert portable_add.emission(document, records)['status'] == 'ready'
    records[0]['native_name'] = 'btop'
    result = portable_add.emission(document, records)
    assert result['status'] == 'blocked' and 'differ' in result['reason']


@pytest.mark.parametrize('error', ['signed metadata expired', 'signed archive identity mismatch',
                                   'signed archive does not declare selected architecture/component',
                                   'index hash or size differs from signed Release'])
def test_stale_wrong_release_arch_or_partial_indexes_fail_every_dependent_target(error):
    calls = []
    def acquire(catalog, keyring_for, now):
        calls.append(catalog['variant'])
        raise package_catalogs.CatalogError(error)
    report, _ = failure(acquire=acquire, **flounder_covered())
    assert calls == ['flounder']  # A failed collection is not retried per target.
    for record in report['targets']:
        assert record['status'] == 'source-error' and record['reason'] == error
        assert record['index_availability'] == {'status': 'not-collected'}


def test_unsupported_platform_selection_fails_closed():
    report, _ = failure(variants=['flounder'], flavors=['base'], platforms=['linux/arm64'])
    assert by_target(report)['flounder:base:linux/arm64']['status'] == 'unsupported'
    with pytest.raises(portable_add.PortableAddError, match='no enabled image target'):
        plan(variants=['flounder'], platforms=['linux/riscv64'])


def test_changed_base_image_blocks_lookup_without_network():
    document = tunaos_config.load()
    document['variants']['flounder']['base_image'] = 'docker.io/library/debian:trixie@sha256:' + 'f' * 64
    calls = []
    report, _ = failure(document=document, acquire=acquirer(calls=calls), **flounder_covered())
    assert all('refresh' in record['reason'] for record in report['targets'])
    assert calls == []


def test_changed_source_configuration_blocks_lookup_without_network(tmp_path):
    target_tree(tmp_path)
    (tmp_path / 'build_scripts/20-packages.sh').write_text('changed\n')
    calls = []
    report, _ = failure(root=tmp_path, acquire=acquirer(calls=calls), **flounder_covered())
    assert calls == []
    assert all('configuration changed' in record['reason'] for record in report['targets'])


def test_conflicting_apt_exclusion_is_rejected_before_any_collection(tmp_path, monkeypatch, capsys):
    # The primary schema has no apt exclusion field, so an exclusion that would
    # conflict with an apt addition cannot reach planning or acquisition.
    config = tmp_path / 'tunaos.toml'
    source = (ROOT / 'tunaos.toml').read_text()
    header = '[desktops.kde-debian.packages.apt]\n'
    assert source.count(header) == 1
    config.write_text(source.replace(header, header + 'exclude = ["htop"]\n'))
    calls = []
    monkeypatch.setattr(portable_add.signed_apt, 'acquire_catalog', acquirer(calls=calls))
    assert cli.main(['plan', 'htop', '--config', str(config), '--variant', 'flounder']) == 1
    assert 'desktops.kde-debian.packages.apt' in capsys.readouterr().err
    assert calls == []


def test_cli_plan_is_read_only_and_repeatable(tmp_path, monkeypatch, capsys):
    target_tree(tmp_path)
    shutil.copy(ROOT / 'tunaos.toml', tmp_path / 'tunaos.toml')
    config = tmp_path / 'tunaos.toml'
    before = config.read_bytes()
    monkeypatch.setattr(portable_add.signed_apt, 'acquire_catalog', acquirer())
    arguments = ['plan', 'htop', '--config', str(config), '--variant', 'flounder',
                 '--flavor', 'base', '--flavor', 'kde', '--flavor', 'xfce', '--platform', 'linux/amd64']
    outputs = []
    for _ in range(2):
        assert cli.main(arguments) == 0
        outputs.append(json.loads(capsys.readouterr().out))
    assert outputs[0] == outputs[1]
    assert config.read_bytes() == before
    assert not list(tmp_path.glob('.*.lock'))
    assert cli.main(['plan', 'htop', '--config', str(config), '--variant', 'yellowfin']) == 1
    captured = capsys.readouterr()
    assert json.loads(captured.out)['complete'] is False and 'nothing emitted' in captured.err
    assert config.read_bytes() == before


def test_defaults_scope_editor_updates_primary_package_table():
    import tomlkit

    edited = tomlkit.parse((ROOT / 'tunaos.toml').read_text())
    del edited['variants']['guppy']
    del edited['tuna_rollout']['guppy']
    for facet in edited['iso_builder']['selection']['facets']:
        if facet['id'] == 'base':
            for position in reversed(range(len(facet['values']))):
                if facet['values'][position]['id'] == 'guppy':
                    del facet['values'][position]
    source = tomlkit.dumps(edited).encode()
    document = tunaos_config.validate(tunaos_config.parse(source, '<apt/rpm/arch derivative>'))
    result = cli.author.edit_image_additions(
        source, document,
        {'status': 'ready', 'scope': 'defaults', 'additions': {'defaults': ['commonpkg']}})
    updated = tunaos_config.validate(tunaos_config.parse(result, '<edited config>'))
    assert updated['defaults']['packages']['add'] == ['commonpkg']
    assert '[defaults.packages]' in result.decode()
    assert result != source


def test_defaults_editor_keeps_native_family_validation():
    document = tunaos_config.load()
    source = (ROOT / 'tunaos.toml').read_bytes()
    with pytest.raises(tunaos_config.ConfigError, match='category/name'):
        cli.author.edit_image_additions(
            source, document,
            {'status': 'ready', 'scope': 'defaults', 'additions': {'defaults': ['htop']}})


@pytest.mark.parametrize('scope', ['defaults', 'variants'])
def test_portable_writer_refuses_optional_conflicts_without_writing(tmp_path, scope):
    import tomlkit

    edited = tomlkit.parse((ROOT / 'tunaos.toml').read_text())
    edited['variants']['flounder']['packages'] = {'optional': ['htop']}
    source = tomlkit.dumps(edited).encode()
    path = tmp_path / 'tunaos.toml'
    path.write_bytes(source)
    document = tunaos_config.validate(tunaos_config.parse(source, path))
    additions = {'defaults' if scope == 'defaults' else 'flounder': ['htop']}
    with pytest.raises((cli.author.AuthoringError, tunaos_config.ConfigError),
                       match='optional'):
        result = cli.author.edit_image_additions(
            source, document, {'status': 'ready', 'scope': scope, 'additions': additions})
        cli.author.atomic_write(path, source, result)
    assert path.read_bytes() == source
    assert not list(tmp_path.glob('.*.lock'))




def test_cli_plan_write_requires_complete_scope_and_writes_variant_policy(tmp_path, monkeypatch, capsys):
    target_tree(tmp_path)
    shutil.copy(ROOT / 'tunaos.toml', tmp_path / 'tunaos.toml')
    config = tmp_path / 'tunaos.toml'
    import tomlkit

    edited = tomlkit.parse(config.read_text())
    for flavor in edited['variants']['flounder']['flavors']:
        flavor['build_image'] = flavor['id'] in ('base', 'kde', 'xfce')
        flavor['platforms'] = ['linux/amd64']
        if not flavor['build_image']:
            flavor['build_iso'] = False
            flavor['build_qcow2'] = False
    config.write_text(tomlkit.dumps(edited))
    monkeypatch.setattr(portable_add.signed_apt, 'acquire_catalog', acquirer())
    before_preview = config.read_bytes()
    assert cli.main(['plan', 'htop', '--config', str(config), '--variant', 'flounder']) == 0
    preview = capsys.readouterr()
    assert json.loads(preview.out)['emission']['status'] == 'ready'
    assert '+add = ["htop"]' in preview.err
    assert 'Dry run; use --write to apply.' in preview.err
    assert config.read_bytes() == before_preview
    assert cli.main(['plan', 'htop', '--config', str(config), '--variant', 'flounder', '--write']) == 0
    captured = capsys.readouterr()
    report = json.loads(captured.out)
    assert report['emission'] == {'status': 'ready', 'scope': 'variants', 'additions': {'flounder': ['htop']}}
    assert 'Written atomically.' in captured.err
    updated = tunaos_config.load(config)
    assert updated['variants']['flounder']['packages']['add'] == ['htop']
    assert '[variants.flounder.packages]' in config.read_text()
    assert tunaos_config.image_packages(updated)['flounder']['add'] == ['htop']
    before_repeat = config.read_bytes()
    assert cli.main(['plan', 'htop', '--config', str(config), '--variant', 'flounder', '--write']) == 0
    repeated = capsys.readouterr()
    assert json.loads(repeated.out)['emission']['status'] == 'ready'
    assert 'No change.' in repeated.err
    assert config.read_bytes() == before_repeat


@pytest.fixture
def writable_flounder_config(tmp_path, monkeypatch):
    import tomlkit

    target_tree(tmp_path)
    edited = tomlkit.parse((ROOT / 'tunaos.toml').read_text())
    for flavor in edited['variants']['flounder']['flavors']:
        flavor['build_image'] = flavor['id'] in ('base', 'kde', 'xfce')
        flavor['platforms'] = ['linux/amd64']
        if not flavor['build_image']:
            flavor['build_iso'] = False
            flavor['build_qcow2'] = False
    config = tmp_path / 'tunaos.toml'
    config.write_text(tomlkit.dumps(edited))
    monkeypatch.setattr(portable_add.signed_apt, 'acquire_catalog', acquirer())
    return config


@pytest.mark.parametrize('refusal', ['variant-optional', 'defaults-optional', 'missing-tomlkit'])
def test_cli_refused_preview_remains_a_transaction_plan(
        writable_flounder_config, refusal, monkeypatch, capsys):
    import tomlkit

    config = writable_flounder_config
    if refusal == 'missing-tomlkit':
        monkeypatch.setitem(sys.modules, 'tomlkit', None)
    else:
        edited = tomlkit.parse(config.read_text())
        holder = edited['defaults'] if refusal == 'defaults-optional' else edited['variants']['flounder']
        holder['packages'] = {'optional': ['htop']}
        config.write_text(tomlkit.dumps(edited))
    before = config.read_bytes()
    arguments = ['plan', 'htop', '--config', str(config), '--variant', 'flounder']

    assert cli.main(arguments) == 0
    preview = capsys.readouterr()
    report = json.loads(preview.out)
    assert report['complete'] is True
    assert report['resolved_targets'] == 3
    assert {row['target'] for row in report['targets']} == set(FLOUNDER_COVERED)
    assert report['emission']['status'] == 'blocked'
    assert config.read_bytes() == before
    assert not list(config.parent.glob('.*.lock'))

    assert cli.main([*arguments, '--write']) == 1
    failed = capsys.readouterr()
    assert json.loads(failed.out) == report
    assert config.read_bytes() == before
    assert not list(config.parent.glob('.*.lock'))

    plan_path = config.parent / 'refused-preview.json'
    plan_path.write_text(preview.out)
    monkeypatch.setattr(cli.subprocess, 'run', run_returning(
        0, 'Inst htop (3.4.1-5 Debian:13/stable [amd64])\n'))
    assert cli.main([
        'verify-transaction', 'htop', '--config', str(config), '--plan', str(plan_path),
        '--image-target', TARGET, '--image', IMAGE,
    ]) == 0
    transaction = json.loads(capsys.readouterr().out)
    assert transaction['transaction']['status'] == 'solvable'
    assert transaction['installed_image'] == {'status': 'not-run'}
    assert config.read_bytes() == before


def test_cli_atomic_write_failure_preserves_plan_report(writable_flounder_config, capsys):
    config = writable_flounder_config
    before = config.read_bytes()
    # A real filesystem refusal exercises the writer without replacing it.
    config.with_name('.' + config.name + '.packages.lock').mkdir()
    assert cli.main([
        'plan', 'htop', '--config', str(config), '--variant', 'flounder', '--write',
    ]) == 1
    failed = capsys.readouterr()
    report = json.loads(failed.out)
    assert report['complete'] is True
    assert report['emission']['status'] == 'blocked'
    assert config.read_bytes() == before


def test_cli_plan_write_refuses_partial_effective_scope_without_touching_config(tmp_path, monkeypatch, capsys):
    target_tree(tmp_path)
    shutil.copy(ROOT / 'tunaos.toml', tmp_path / 'tunaos.toml')
    config = tmp_path / 'tunaos.toml'
    before = config.read_bytes()
    monkeypatch.setattr(portable_add.signed_apt, 'acquire_catalog', acquirer())
    arguments = ['plan', 'htop', '--config', str(config), '--variant', 'flounder',
                 '--flavor', 'base', '--flavor', 'kde', '--flavor', 'xfce',
                 '--platform', 'linux/amd64', '--write']
    assert cli.main(arguments) == 1
    captured = capsys.readouterr()
    report = json.loads(captured.out)
    assert report['complete'] is True
    assert report['emission']['status'] == 'blocked'
    assert 'complete effective-scope evidence' in captured.err
    assert config.read_bytes() == before
    assert not list(tmp_path.glob('.*.lock'))


@pytest.mark.parametrize('arguments', [['--target', 'kde:apt'], ['--dry-run'], ['--index', 'a=b']])
def test_cli_plan_rejects_receipt_and_dry_run_options(arguments, capsys):
    assert cli.main(['plan', 'htop', *arguments]) == 1
    assert 'does not accept' in capsys.readouterr().err


def test_cli_existing_commands_still_require_explicit_targets(capsys):
    assert cli.main(['add', 'htop']) == 1
    assert 'requires --target' in capsys.readouterr().err
    assert cli.main(['search', 'htop', '--target', 'kde:apt', '--variant', 'flounder']) == 1
    assert 'does not accept plan' in capsys.readouterr().err


# Separate non-installing transaction verification.

IMAGE = 'ghcr.io/tuna-os/flounder@sha256:' + 'e' * 64
TARGET = 'flounder:kde:linux/amd64'


def resolved_plan():
    report = plan(**flounder_covered())
    return report, json.dumps(report).encode()


def run_returning(returncode, stdout='', stderr='', commands=None):
    def run(command, **kwargs):
        if commands is not None:
            commands.append(command)
        assert kwargs == {'text': True, 'capture_output': True}
        return subprocess.CompletedProcess(command, returncode, stdout, stderr)
    return run


def test_transaction_consumes_plan_and_only_simulates():
    report, data = resolved_plan()
    commands = []
    result = portable_add.verify_transaction(
        report, data, TARGET, IMAGE,
        run_returning(0, 'Inst libhwloc15 (2.12)\nInst htop (3.4.1-5 Debian:13/stable [amd64])\n', commands=commands))
    assert result['transaction']['status'] == 'solvable'
    assert result['transaction']['installs'] == ['libhwloc15', 'htop']
    assert result['index_availability'] == 'present'
    assert result['installed_image'] == {'status': 'not-run'}
    assert 'not authenticated' in result['image_binding']
    [command] = commands
    assert command[:6] == ['podman', 'run', '--rm', '--pull=never', '--entrypoint', 'sh']
    assert command[6] == IMAGE and command[-1] == 'htop'
    script = command[8]
    assert '--simulate' in script and '--no-remove' in script
    assert 'LC_ALL=C LANG=C' in script
    assert 'apt-get update --error-on=any' in script
    assert 'install -- "$@"' in script and 'htop' not in script


@pytest.mark.parametrize('returncode,output,status', [
    (0, 'htop is already the newest version (3.4.1-5).\n', 'already-installed'),
    (100, 'E: Unable to locate package htop\n', 'missing'),
    (100, 'The following packages have unmet dependencies:\n htop : Depends: libx\n'
          'E: Unable to correct problems, you have held broken packages.\n', 'solver-gap'),
    (100, 'E: Packages need to be removed but remove is disabled.\n', 'protected-removal'),
    (0, 'Remv systemd-boot [1]\nInst htop (1)\n', 'protected-removal'),
    (90, 'tunaos: image package-source refresh failed\n', 'source-error'),
    (125, 'Error: image not known\n', 'error'),
    (0, 'Inst other (1)\n', 'error'),
])
def test_transaction_failures_are_explicit(returncode, output, status):
    report, data = resolved_plan()
    run = run_returning(returncode, stderr=output)
    if status == 'already-installed':
        result = portable_add.verify_transaction(report, data, TARGET, IMAGE, run)
        assert result['transaction']['status'] == status
        return
    with pytest.raises(portable_add.PortableAddError) as raised:
        portable_add.verify_transaction(report, data, TARGET, IMAGE, run)
    assert raised.value.report['transaction']['status'] == status


def test_transaction_rejects_mutable_images_unresolved_targets_and_other_families():
    report, data = resolved_plan()
    never = run_returning(0, commands=[])
    with pytest.raises(portable_add.PortableAddError, match='pinned'):
        portable_add.verify_transaction(report, data, TARGET, 'ghcr.io/tuna-os/flounder:kde', never)
    with pytest.raises(portable_add.PortableAddError, match='not a resolved target'):
        portable_add.verify_transaction(report, data, 'yellowfin:base:linux/amd64', IMAGE, never)
    incomplete = dict(report, complete=False)
    with pytest.raises(portable_add.PortableAddError, match='incomplete'):
        portable_add.verify_transaction(incomplete, data, TARGET, IMAGE, never)
    other = json.loads(data)
    for record in other['targets']:
        record['family'] = 'emerge'
    with pytest.raises(portable_add.PortableAddError) as raised:
        portable_add.verify_transaction(other, data, TARGET, IMAGE, never)
    assert raised.value.report['transaction']['status'] == 'unsupported'


def test_cli_transaction_requires_matching_plan_intent(tmp_path, capsys):
    report, data = resolved_plan()
    path = tmp_path / 'plan.json'
    path.write_bytes(data)
    assert cli.main(['verify-transaction', 'btop', '--plan', str(path),
                     '--image-target', TARGET, '--image', IMAGE]) == 1
    assert 'different package intent' in capsys.readouterr().err
    assert cli.main(['verify-transaction', 'htop', '--plan', str(path)]) == 1
    assert 'requires --plan, --image-target and --image' in capsys.readouterr().err


def synthetic_resolved_report():
    record = {'target': TARGET, 'status': 'resolved', 'family': 'apt', 'native_name': 'htop',
              'index_availability': {'status': 'present'}}
    report = {'schema_version': portable_add.PLAN_SCHEMA, 'complete': True, 'targets': [record]}
    return report, json.dumps(report).encode()


def test_missing_container_runtime_is_a_reported_transaction_error():
    report, data = synthetic_resolved_report()

    def no_podman(command, **kwargs):
        raise FileNotFoundError(2, 'No such file or directory', command[0])

    with pytest.raises(portable_add.PortableAddError) as raised:
        portable_add.verify_transaction(report, data, TARGET, IMAGE, no_podman)
    assert raised.value.report['transaction']['status'] == 'error'
    assert 'podman' in raised.value.report['transaction']['detail']


def test_an_ambiguous_name_is_present_in_the_index_not_absent(monkeypatch):
    document = tunaos_config.load()
    fake_catalogs = type('Catalogs', (), {})()
    fake_catalogs.CatalogError = portable_add.catalogs.CatalogError
    fake_catalogs.select = lambda *args: None
    fake_catalogs.bind_target_configuration = lambda *args: {'observed_at': '2026-10-25T00:00:00Z'}
    fake_catalogs.bind_observation = lambda catalog, directory: ({'base_image': 'x@sha256:' + 'a' * 64},
                                                                  {s['id']: b'k' for s in catalog['sources']})
    monkeypatch.setattr(portable_add, 'catalogs', fake_catalogs)

    def resolve(query, names, family):
        raise portable_add.author.AmbiguousNameError('htop: ambiguous: a/htop, b/htop', {'htop'})

    monkeypatch.setattr(portable_add.author, 'resolve', resolve)
    selected = portable_add.select_targets(document, **flounder_covered())
    with pytest.raises(portable_add.PortableAddError) as raised:
        portable_add.plan(document, ROOT, 'htop', selected, None, now=NOW, acquire=acquirer())
    first = raised.value.report['targets'][0]
    assert first['status'] == 'ambiguous'
    assert first['index_availability']['status'] == 'present'
    assert first['index_availability']['matched_sources'] == ['trixie']
