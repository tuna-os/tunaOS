"""CLI orchestration tests; transport and config parser are explicit test doubles."""
import importlib.util
import json
import sys
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
SPEC = importlib.util.spec_from_file_location('search_base_packages', ROOT / 'scripts/search-base-packages.py')
cli = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cli)
ARGS = ['htop', '--catalog', 'debian-trixie', '--variant', 'flounder',
        '--flavor', 'base', '--release', 'trixie', '--platform', 'linux/amd64']


def pipeline(monkeypatch, tmp_path):
    path = tmp_path / 'tunaos.toml'
    path.write_text('# untouched config\n')
    monkeypatch.setattr(cli.tunaos_config, 'parse', lambda *a, **k: {}, raising=False)
    monkeypatch.setattr(cli.tunaos_config, 'validate', lambda doc: doc)
    monkeypatch.setattr(cli.catalogs, 'select', lambda *a: {})
    monkeypatch.setattr(
        cli.catalogs, 'bind_observation',
        lambda *a: ({'base_image': 'pinned-test-image'}, {}))
    monkeypatch.setattr(
        cli.catalogs, 'bind_target_configuration',
        lambda *a: {'observed_at': '2026-10-24T00:00:00Z'})
    return path


def test_result_is_explicitly_complete(monkeypatch, tmp_path, capsys):
    path = pipeline(monkeypatch, tmp_path)
    monkeypatch.setattr(cli.signed_apt, 'acquire_catalog', lambda *a: [
        {'source': name, 'names': {'htop', 'other'}, 'freshness': {'expires': None}}
        for name in ['trixie', 'trixie-updates', 'trixie-security', 'tailscale']])
    assert cli.main(ARGS + ['--config', str(path)]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output['coverage'] == 'configured-target'
    assert output['cell_coverage_complete'] is True
    assert output['add_supported'] is False
    assert output['flavor'] == 'base'
    assert len(output['sources']) == 4
    assert all(source['matches'] == ['htop'] for source in output['sources'])
    assert path.read_text() == '# untouched config\n'


def test_failed_source_prints_no_partial_results(monkeypatch, tmp_path, capsys):
    path = pipeline(monkeypatch, tmp_path)
    def fail(*args):
        raise cli.catalogs.CatalogError('security source expired')
    monkeypatch.setattr(cli.signed_apt, 'acquire_catalog', fail)
    assert cli.main(ARGS + ['--config', str(path)]) == 1
    output = capsys.readouterr()
    assert output.out == '' and 'security source expired' in output.err
    assert path.read_text() == '# untouched config\n'


@pytest.mark.parametrize('query', ['', 'a' * 257, 'line\nbreak'])
def test_query_guard_precedes_reads(monkeypatch, query, capsys):
    def unexpected(*args):
        pytest.fail('invalid query must not read a config')
    monkeypatch.setattr(cli.author, 'read_config', unexpected)
    assert cli.main([query] + ARGS[1:]) == 1
    assert capsys.readouterr().out == ''


@pytest.mark.parametrize('option', ['--write', '--add'])
def test_no_write_interface(option):
    with pytest.raises(SystemExit) as exc:
        cli.main(ARGS + [option])
    assert exc.value.code == 2


@pytest.mark.parametrize('source', [b'\xff', b'key=' + b'[' * 1500 + b'0' + b']' * 1500,
                                     b'key=' + b'9' * 5000])
def test_real_parser_clean_error_before_acquisition(tmp_path, source):
    import subprocess
    path = tmp_path / 'tunaos.toml'
    path.write_bytes(source)
    result = subprocess.run([sys.executable, str(ROOT / 'scripts/search-base-packages.py'),
                             *ARGS, '--config', str(path)], text=True, capture_output=True)
    assert result.returncode == 1
    assert 'Traceback' not in result.stderr and str(path) in result.stderr
    assert result.stdout == '' and path.read_bytes() == source


def test_real_config_and_observation_without_network(monkeypatch, capsys):
    # Keep the actual parser, schema, target matching and both observation bindings.
    def checked(catalog, keyring_for, now):
        assert catalog['coverage'] == 'configured-target'
        assert [len(keyring_for(source)) for source in catalog['sources']] == [
            55918, 55918, 55918, 2288]
        return []
    monkeypatch.setattr(cli.signed_apt, 'acquire_catalog', checked)
    assert cli.main(ARGS + ['--config', str(ROOT / 'tunaos.toml')]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output['cell_coverage_complete'] is True
    assert output['configuration_observed_at'] == '2026-10-24T02:30:03Z'
