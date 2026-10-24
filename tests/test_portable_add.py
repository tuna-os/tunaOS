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


def source_result(source, names):
    return {'source': source, 'role': 'build' if source == 'tailscale' else 'base',
            'source_url': f'https://example.invalid/{source}/InRelease', 'release': 'trixie',
            'architecture': 'amd64', 'signed_at': '2026-10-23T00:00:00+00:00',
            'retrieved_at': NOW.isoformat(), 'inrelease_sha256': 'a' * 64,
            'keyring_sha256': 'b' * 64, 'indexes': [{'url': 'u', 'sha256': 'c' * 64, 'size': 1}],
            'names': set(names), 'signers': ['A' * 40],
            'freshness': {'mode': 'signed-valid-until', 'expires': None}}


def acquirer(base_names=('htop', 'btop', 'bashtop'), calls=None):
    def acquire(catalog, keyring_for, now):
        assert [len(keyring_for(source)) for source in catalog['sources']] == [55918, 55918, 55918, 2288]
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
        assert record['configuration_observed_at'] == '2026-10-24T02:30:03Z'
    json.dumps(report)  # Evidence is serializable; no sets leak into the plan.


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
    for name in ('config', 'build_scripts'):
        shutil.copytree(ROOT / name, tmp_path / name)
    shutil.copy(ROOT / 'Containerfile.debian', tmp_path / 'Containerfile.debian')
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
    for name in ('tunaos.toml', 'Containerfile.debian'):
        shutil.copy(ROOT / name, tmp_path / name)
    for name in ('config', 'build_scripts'):
        shutil.copytree(ROOT / name, tmp_path / name)
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


@pytest.mark.parametrize('arguments', [['--target', 'kde:apt'], ['--write'], ['--index', 'a=b']])
def test_cli_plan_rejects_write_and_receipt_options(arguments, capsys):
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
