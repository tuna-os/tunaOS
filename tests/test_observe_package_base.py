"""Offline tests for scripts/observe-package-base.py against a synthetic registry."""
from datetime import datetime, timezone
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import shutil
import sys
import tarfile
import types

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from lib import package_catalogs  # noqa: E402
from lib import tunaos_config  # noqa: E402
from lib.package_catalogs import CatalogError  # noqa: E402

NOW = datetime(2026, 10, 29, 6, 0, 0, tzinfo=timezone.utc)


def _tool():
    spec = importlib.util.spec_from_file_location('observe_package_base',
                                                  ROOT / 'scripts/observe-package-base.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _committed_observation():
    return json.loads((ROOT / 'config/package-observations/flounder-amd64.json').read_text())


def _layer(files):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode='w:gz') as archive:
        for name, content in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(content)
            archive.addfile(info, io.BytesIO(content))
    return buffer.getvalue()


def _registry(monkeypatch, tool, *, files=None, layers=1, revision='a' * 40):
    """Serve one index/manifest/layer set; return the exact base image reference."""
    committed = _committed_observation()
    files = files if files is not None else {
        'etc/apt/sources.list.d/debian.sources': committed['source_text'].encode(),
        'usr/lib/os-release': committed['os_release_text'].encode(),
        'usr/share/keyrings/debian-archive-keyring.pgp': (ROOT / 'config/package-keys/debian-trixie.pgp').read_bytes(),
    }
    blob = _layer(files)
    layer = {'mediaType': 'application/vnd.oci.image.layer.v1.tar+gzip',
             'digest': 'sha256:' + hashlib.sha256(blob).hexdigest(), 'size': len(blob)}
    manifest = json.dumps({'schemaVersion': 2, 'layers': [layer] * layers}).encode()
    manifest_digest = 'sha256:' + hashlib.sha256(manifest).hexdigest()
    index = json.dumps({'manifests': [{
        'annotations': {'org.opencontainers.image.revision': revision},
        'digest': manifest_digest, 'mediaType': 'application/vnd.oci.image.manifest.v1+json',
        'platform': {'architecture': 'amd64', 'os': 'linux'}, 'size': len(manifest)}]}).encode()
    index_digest = 'sha256:' + hashlib.sha256(index).hexdigest()
    objects = {f'manifests/{index_digest}': index, f'manifests/{manifest_digest}': manifest,
               f'blobs/{layer["digest"]}': blob}

    class Token(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(tool.urllib.request, 'urlopen', lambda *a, **k: Token(b'{"token": "t"}'))
    # A registry (or mirror) that answers any index request with these bytes.
    monkeypatch.setattr(tool, '_registry_get', lambda repository, path, token, accept=None, limit=0: objects.get(
        path, index if path.startswith('manifests/') else None))
    return f'docker.io/library/debian:trixie@{index_digest}'


def _catalog():
    document = tunaos_config.validate(tunaos_config.parse(
        (ROOT / 'tunaos.toml').read_bytes(), path=str(ROOT / 'tunaos.toml')))
    return document['package_catalogs']['debian-trixie']


def _tree(tmp_path, base_image):
    """A config tree whose flounder base_image is the synthetic digest."""
    for relative in ('config/package-keys', 'config/package-observations'):
        shutil.copytree(ROOT / relative, tmp_path / relative)
    source = (ROOT / 'tunaos.toml').read_text()
    current = tunaos_config.validate(tunaos_config.parse(source.encode(), path='tunaos.toml'))
    flounder = current['variants']['flounder']['base_image']
    line = f'\nbase_image = "{flounder}"\n'
    assert source.count(line) == 1
    (tmp_path / 'tunaos.toml').write_text(source.replace(line, f'\nbase_image = "{base_image}"\n'))
    return tmp_path / 'tunaos.toml'


def test_observation_binds_with_the_reviewed_binding(monkeypatch, tmp_path):
    tool = _tool()
    base_image = _registry(monkeypatch, tool)
    catalog = _catalog()
    pin = catalog['sources'][0]['freshness']['inrelease_sha256']
    raw = tool.observe(base_image, pin, NOW)
    observation = json.loads(raw)
    assert observation['apt_source_members'] == [{
        'path': 'etc/apt/sources.list.d/debian.sources', 'type': '0',
        'size': len(observation['source_text'].encode()), 'linkname': ''}]
    assert list(observation) == list(_committed_observation())
    assert observation['observed_at'] == '2026-10-29T06:00:00Z'
    path = tmp_path / catalog['source_observation']
    shutil.copytree(ROOT / 'config', tmp_path / 'config')
    path.write_bytes(raw)
    candidate = dict(catalog, observed_base_image=base_image,
                     source_observation_sha256=hashlib.sha256(raw).hexdigest())
    package_catalogs.bind_observation(candidate, tmp_path)


def test_registry_bytes_must_match_the_pinned_digest(monkeypatch):
    tool = _tool()
    base_image = _registry(monkeypatch, tool)
    with pytest.raises(CatalogError, match='does not match the pinned digest'):
        tool.observe(base_image[:-1] + ('0' if base_image[-1] != '0' else '1'), 'd' * 64, NOW)


def test_multi_layer_base_and_missing_files_fail_closed(monkeypatch):
    tool = _tool()
    with pytest.raises(CatalogError, match='exactly one layer'):
        tool.observe(_registry(monkeypatch, tool, layers=2), 'd' * 64, NOW)
    with pytest.raises(CatalogError, match='lacks a required'):
        tool.observe(_registry(monkeypatch, tool, files={'usr/lib/os-release': b'ID=debian\n'}), 'd' * 64, NOW)
    with pytest.raises(CatalogError, match='upstream artifact revision'):
        tool.observe(_registry(monkeypatch, tool, revision=''), 'd' * 64, NOW)


def test_extra_apt_source_is_recorded_and_refused_by_binding(monkeypatch, tmp_path):
    tool = _tool()
    committed = _committed_observation()
    files = {
        'etc/apt/sources.list.d/debian.sources': committed['source_text'].encode(),
        'etc/apt/sources.list.d/extra.list': b'deb http://example.invalid/ trixie main\n',
        'usr/lib/os-release': committed['os_release_text'].encode(),
        'usr/share/keyrings/debian-archive-keyring.pgp': (ROOT / 'config/package-keys/debian-trixie.pgp').read_bytes(),
    }
    base_image = _registry(monkeypatch, tool, files=files)
    config = _tree(tmp_path, base_image)
    assert tool.main(['--config', str(config), '--catalog', 'debian-trixie', '--write']) == 1
    # The refused observation is rolled back and no pin moves.
    assert (tmp_path / 'config/package-observations/flounder-amd64.json').read_bytes() == \
        (ROOT / 'config/package-observations/flounder-amd64.json').read_bytes()
    assert 'observed_base_image = "' + base_image not in config.read_text()


@pytest.mark.parametrize('alias', ['././etc/apt/sources.list.d/extra.list',
                                   'etc//apt/./sources.list.d/extra.list'])
def test_aliased_apt_source_path_is_still_inventoried(monkeypatch, alias):
    tool = _tool()
    committed = _committed_observation()
    files = {
        'etc/apt/sources.list.d/debian.sources': committed['source_text'].encode(),
        alias: b'deb http://example.invalid/ trixie main\n',
        'usr/lib/os-release': committed['os_release_text'].encode(),
        'usr/share/keyrings/debian-archive-keyring.pgp': (ROOT / 'config/package-keys/debian-trixie.pgp').read_bytes(),
    }
    observation = json.loads(tool.observe(_registry(monkeypatch, tool, files=files), 'd' * 64, NOW))
    assert [m['path'] for m in observation['apt_source_members']] == [
        'etc/apt/sources.list.d/debian.sources', 'etc/apt/sources.list.d/extra.list']


@pytest.mark.parametrize('name', ['/etc/apt/sources.list.d/extra.list',
                                  'usr/../etc/apt/sources.list.d/extra.list'])
def test_absolute_or_escaping_layer_paths_fail_closed(monkeypatch, name):
    tool = _tool()
    committed = _committed_observation()
    files = {
        'etc/apt/sources.list.d/debian.sources': committed['source_text'].encode(),
        name: b'deb http://example.invalid/ trixie main\n',
        'usr/lib/os-release': committed['os_release_text'].encode(),
        'usr/share/keyrings/debian-archive-keyring.pgp': (ROOT / 'config/package-keys/debian-trixie.pgp').read_bytes(),
    }
    with pytest.raises(CatalogError, match='absolute path|parent-traversal'):
        tool.observe(_registry(monkeypatch, tool, files=files), 'd' * 64, NOW)


def test_unrewritable_pins_leave_the_observation_untouched(monkeypatch, tmp_path):
    tool = _tool()
    base_image = _registry(monkeypatch, tool)
    config = _tree(tmp_path, base_image)
    source = config.read_text()
    line = next(item for item in source.splitlines() if item.startswith('source_observation_sha256 = "'))
    config.write_text(source.replace(line, line + '  # reviewed'))
    before = config.read_text()
    assert tool.main(['--config', str(config), '--catalog', 'debian-trixie', '--write']) == 1
    assert (tmp_path / 'config/package-observations/flounder-amd64.json').read_bytes() == \
        (ROOT / 'config/package-observations/flounder-amd64.json').read_bytes()
    assert config.read_text() == before


def test_failed_config_write_restores_the_observation(monkeypatch, tmp_path):
    tool = _tool()
    base_image = _registry(monkeypatch, tool)
    config = _tree(tmp_path, base_image)
    before = config.read_text()
    write = tool._load_refresh_tool()._atomic_write

    def atomic_write(path, data):
        if Path(path) == config:
            raise OSError('disk full')
        write(path, data)
    monkeypatch.setattr(tool, '_load_refresh_tool', lambda: types.SimpleNamespace(_atomic_write=atomic_write))
    assert tool.main(['--config', str(config), '--catalog', 'debian-trixie', '--write']) == 1
    assert (tmp_path / 'config/package-observations/flounder-amd64.json').read_bytes() == \
        (ROOT / 'config/package-observations/flounder-amd64.json').read_bytes()
    assert config.read_text() == before


def test_write_moves_only_the_two_base_pins(monkeypatch, tmp_path, capsys):
    tool = _tool()
    base_image = _registry(monkeypatch, tool)
    config = _tree(tmp_path, base_image)
    before = config.read_text()
    assert tool.main(['--config', str(config), '--catalog', 'debian-trixie']) == 0
    assert 'dry run' in capsys.readouterr().out
    assert config.read_text() == before
    assert tool.main(['--config', str(config), '--catalog', 'debian-trixie', '--write']) == 0
    after = config.read_text()
    changed = [(a, b) for a, b in zip(before.splitlines(), after.splitlines()) if a != b]
    assert [a.split(' = ')[0] for a, _ in changed] == ['observed_base_image', 'source_observation_sha256']
    observation = (tmp_path / 'config/package-observations/flounder-amd64.json').read_bytes()
    assert f'source_observation_sha256 = "{hashlib.sha256(observation).hexdigest()}"' in after
    assert tool.main(['--config', str(config), '--catalog', 'debian-trixie']) == 0
    assert 'nothing to do' in capsys.readouterr().out
