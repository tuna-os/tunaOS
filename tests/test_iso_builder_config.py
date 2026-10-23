"""Presentation config cannot replace catalog authority or drift from primary TOML."""
import copy
import importlib.util
import json
import re
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('builder_config', ROOT / 'scripts/lib/iso_builder_config.py')
assert SPEC is not None and SPEC.loader is not None, 'cannot load ISO Builder config module'
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)
SPEC2 = importlib.util.spec_from_file_location('primary_config', ROOT / 'scripts/lib/tunaos_config.py')
assert SPEC2 is not None and SPEC2.loader is not None, 'cannot load primary config module'
primary = importlib.util.module_from_spec(SPEC2)
SPEC2.loader.exec_module(primary)


def config():
    return json.loads((ROOT / 'tests/fixtures/builder-config/v1.json').read_text())


def test_generated_artifact_is_exact_primary_projection():
    assert (ROOT / 'docs/iso-builder.config.json').read_text() == builder.render(primary.load())


@pytest.mark.parametrize('path', [(), ('brand',), ('presentation',), ('output',), ('desktops', 0), ('variants', 0), ('default_selection',), ('curated_app_sets', 0), ('ddi_channels', 0)])
def test_unknown_fields_fail_closed(path):
    doc = config()
    current = doc
    for key in path:
        current = current[key]
    current['unexpected'] = True
    with pytest.raises(builder.ConfigError):
        builder.validate(doc)


def test_table_error_reports_unknown_and_missing_fields():
    doc = config()
    doc['brand']['unexpected'] = True
    del doc['brand']['name']
    with pytest.raises(builder.ConfigError) as error:
        builder.validate(doc)
    assert "unknown keys ['unexpected']" in str(error.value)
    assert "missing keys ['name']" in str(error.value)


@pytest.mark.parametrize('section,key,value', [
    (None, 'schema_version', True), (None, 'preview_only', 1),
    ('brand', 'homepage_url', 'javascript:alert(1)'),
    ('brand', 'homepage_url', 'https://user:secret@example.org/'),
    ('brand', 'homepage_url', 'https://example.org:123/'),
    ('brand', 'logo_url', '//evil.org/logo.png'),
    ('brand', 'logo_url', '/../logo.png'),
    ('brand', 'logo_url', '/x\\logo.png'),
    ('brand', 'name', 'bad\nname'),
    ('presentation', 'accent_color', 'red;display:none'),
    ('output', 'filename_prefix', '../escape'),
    ('output', 'volume_label', 'bad label'),
    ('default_selection', 'variant', 'missing'),
    ('default_selection', 'variant', []),
    ('default_selection', 'flavor', 'missing'),
    ('default_selection', 'platform', 'linux/mips64'),
])
def test_invalid_values_fail_closed(section, key, value):
    doc = config()
    target = doc if section is None else doc[section]
    target[key] = value
    with pytest.raises(builder.ConfigError):
        builder.validate(doc)


@pytest.mark.parametrize('field', ['desktops', 'variants', 'curated_app_sets', 'ddi_channels'])
def test_duplicate_ids_rejected_with_collection_and_id(field):
    doc = config()
    duplicate = copy.deepcopy(doc[field][0])
    doc[field].append(duplicate)
    with pytest.raises(builder.ConfigError, match=rf"{field}: duplicate id '{duplicate['id']}'"):
        builder.validate(doc)


def test_duplicate_flatpak_names_desktop_and_app():
    doc = config()
    desktop = doc['desktops'][0]
    app = desktop['default_flatpaks'][0]
    desktop['default_flatpaks'].append(app)
    with pytest.raises(
        builder.ConfigError,
        match=rf"desktops.{desktop['id']}.default_flatpaks: duplicate Flatpak '{re.escape(app)}'",
    ):
        builder.validate(doc)


def test_app_and_channel_references_checked():
    doc = config()
    doc['curated_app_sets'][0]['desktops'] = ['missing']
    with pytest.raises(builder.ConfigError):
        builder.validate(doc)
    doc = config()
    doc['ddi_channels'][0]['desktop'] = 'missing'
    with pytest.raises(builder.ConfigError):
        builder.validate(doc)


def test_primary_default_must_be_build_enabled_cell():
    doc = primary.load()
    doc['iso_builder']['default_selection']['leaf_id'] = 'yellowfin:gnome:linux/amd64/v3'
    with pytest.raises(builder.ConfigError):
        builder.project(doc)
    doc = primary.load()
    doc.pop('iso_builder')
    with pytest.raises(builder.ConfigError, match='no stock fallback'):
        builder.project(doc)


def test_render_is_canonical_across_mapping_insertion_order():
    document = primary.load()
    expected = builder.render(document)
    document['iso_builder'] = dict(reversed(tuple(document['iso_builder'].items())))
    assert builder.render(document) == expected


def test_portable_image_config_has_no_primary_dependency():
    doc = config()
    doc['brand']['name'] = 'Example project'
    doc['variants'] = []
    doc['default_selection'] = {'kind': 'image', 'image': 'ghcr.io/example/image:stable', 'platform': 'linux/amd64'}
    doc['preview_only'] = True
    doc['brand']['disclaimer'] = 'Unofficial example; preview only.'
    assert builder.validate(doc) == doc
    assert not {'relay', 'qualification', 'catalog_url', 'initrd', 'shim'} & doc.keys()


def test_drift_cli_is_read_only_and_detects_changes(tmp_path):
    output = tmp_path / 'config.json'
    cli = [sys.executable, str(ROOT / 'scripts/config.py')]
    assert subprocess.run(cli + ['generate-builder-config', '--output', str(output)]).returncode == 0
    output.write_text('{}\n')
    result = subprocess.run(cli + ['check-builder-config', '--output', str(output)], capture_output=True, text=True)
    assert result.returncode == 1 and 'drift' in result.stderr
    assert output.read_text() == '{}\n'


def test_drift_cli_refuses_symlink_target(tmp_path):
    output = tmp_path / 'config.json'
    victim = tmp_path / 'victim.json'
    victim.write_text(builder.render(primary.load()), encoding='utf-8')
    output.symlink_to(victim)
    cli = [sys.executable, str(ROOT / 'scripts/config.py')]
    result = subprocess.run(
        cli + ['check-builder-config', '--output', str(output)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert 'refusing symlink' in result.stderr

def test_schema_shape_matches_export():
    # jsonschema is optional locally; executable stdlib validation remains mandatory.
    jsonschema = pytest.importorskip('jsonschema')
    schema = json.loads((ROOT / 'docs/iso-builder-config.schema.json').read_text())
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.validate(config(), schema)


@pytest.mark.parametrize('key', ['schema_version', 'preview_only', 'brand', 'presentation', 'output', 'desktops', 'variants', 'default_selection', 'curated_app_sets'])
def test_missing_required_fields_rejected(key):
    doc = config()
    del doc[key]
    with pytest.raises(builder.ConfigError):
        builder.validate(doc)


@pytest.mark.parametrize('apps', ['org.mozilla.firefox', ['bad'], ['org.mozilla.firefox', 'org.mozilla.firefox'], [True]])
def test_flatpak_defaults_are_typed_unique_ids(apps):
    doc = config()
    doc['desktops'][0]['default_flatpaks'] = apps
    with pytest.raises(builder.ConfigError):
        builder.validate(doc)


def test_projection_never_mutates_primary():
    document = primary.load()
    before = copy.deepcopy(document)
    projected = builder.project(document)
    projected['brand']['name'] = 'Changed'
    assert document == before


def test_preview_requires_disclaimer():
    doc = config()
    doc['preview_only'] = True
    with pytest.raises(builder.ConfigError, match='disclaimer'):
        builder.validate(doc)


def _string_paths(value, path=()):
    if isinstance(value, str):
        yield path
    elif isinstance(value, dict):
        for key, child in value.items():
            yield from _string_paths(child, path + (key,))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _string_paths(child, path + (index,))


@pytest.mark.parametrize('suffix', ['\n', '\x00', '\x1f', '\x7f'])
def test_schema_and_reference_reject_controls_in_every_stock_string(suffix):
    jsonschema = pytest.importorskip('jsonschema')
    validator = jsonschema.Draft202012Validator(json.loads((ROOT / 'docs/iso-builder-config.schema.json').read_text()))
    for path in _string_paths(config()):
        doc = config()
        target = doc
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] += suffix
        assert not validator.is_valid(doc), path
        with pytest.raises(builder.ConfigError):
            builder.validate(doc)


@pytest.mark.parametrize('reference,valid', [
    (case['reference'], case['valid'])
    for case in json.loads((ROOT / 'tests/fixtures/builder-config-image-references.json').read_text())
])
def test_schema_and_reference_image_identity_parity(reference, valid):
    jsonschema = pytest.importorskip('jsonschema')
    schema = json.loads((ROOT / 'docs/iso-builder-config.schema.json').read_text())
    doc = config()
    doc['default_selection'] = {'kind': 'image', 'image': reference, 'platform': 'linux/amd64'}
    assert jsonschema.Draft202012Validator(schema).is_valid(doc) is valid
    if valid:
        builder.validate(doc)
    else:
        with pytest.raises(builder.ConfigError):
            builder.validate(doc)


@pytest.mark.parametrize('app_id,valid', [
    (case['id'], case['valid'])
    for case in json.loads((ROOT / 'tests/fixtures/builder-config-flatpak-ids.json').read_text())
])
def test_schema_and_reference_flatpak_identity_parity(app_id, valid):
    # Flatpak 1.16.1 common/flatpak-ref-utils.c: flatpak_is_valid_name.
    jsonschema = pytest.importorskip('jsonschema')
    schema = json.loads((ROOT / 'docs/iso-builder-config.schema.json').read_text())
    doc = config()
    doc['desktops'][0]['default_flatpaks'] = [app_id]
    assert jsonschema.Draft202012Validator(schema).is_valid(doc) is valid
    if valid:
        builder.validate(doc)
    else:
        with pytest.raises(builder.ConfigError):
            builder.validate(doc)


URL_VECTORS = json.loads((ROOT / 'tests/fixtures/builder-config-urls.json').read_text())


@pytest.mark.parametrize('case', URL_VECTORS['cases'], ids=range(len(URL_VECTORS['cases'])))
def test_shared_url_authority_policy(case):
    import jsonschema
    config = builder.project(primary.load())
    key = 'logo_url' if case['asset'] else 'homepage_url'
    config['brand'][key] = case['url']
    schema = json.loads((ROOT / 'docs/iso-builder-config.schema.json').read_text())
    if case['valid']:
        builder.validate(config)
        jsonschema.validate(config, schema)
    else:
        with pytest.raises(builder.ConfigError):
            builder.validate(config)
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(config, schema)


def test_url_fixture_uses_the_production_pattern():
    assert URL_VECTORS['https_pattern'] == builder.HTTPS_URL


@pytest.mark.parametrize('command', ['generate-builder-config', 'check-builder-config', 'generate-builder-flavors', 'check-builder-flavors'])
@pytest.mark.parametrize('kind', ['checkout-link', 'escape', 'external', 'final-link', 'fifo'])
def test_builder_output_directory_contract(tmp_path, command, kind):
    import os
    root = tmp_path / 'checkout'
    root.mkdir()
    (root / 'tunaos.toml').write_bytes((ROOT / 'tunaos.toml').read_bytes())
    docs = root / 'docs'
    outside = tmp_path / 'outside'
    outside.mkdir()
    flavors = command.endswith('-flavors')
    filename = 'iso-builder.flavors.json' if flavors else 'iso-builder.config.json'
    payload = (builder.render_flavors if flavors else builder.render)(primary.load())
    victim = outside / filename
    victim.write_text(payload)
    args = [sys.executable, str(ROOT / 'scripts/config.py'), command, '--root', str(root)]
    if kind == 'escape':
        docs.symlink_to(outside, target_is_directory=True)
    else:
        docs.mkdir()
        (docs / filename).write_text(payload)
    if kind == 'checkout-link':
        alias = tmp_path / 'alias'
        alias.symlink_to(root, target_is_directory=True)
        args[-1] = str(alias)
    elif kind == 'external':
        args += ['--output', str(victim)]
    elif kind in ('final-link', 'fifo'):
        target = outside / 'selected.json'
        if kind == 'final-link':
            target.symlink_to(victim)
        else:
            os.mkfifo(target)
        args += ['--output', str(target)]
    result = subprocess.run(args, capture_output=True, text=True, timeout=10)
    assert result.returncode == (0 if kind in ('checkout-link', 'external') else 1), result.stderr
    assert victim.read_text() == payload
    assert 'Traceback' not in result.stderr


@pytest.mark.parametrize('path,value,expected', [
    (('brand',), [], 'brand:'),
    (('brand', 'name'), '', 'brand.name:'),
    (('brand', 'homepage_url'), 'http://example.org', 'brand.homepage_url:'),
    (('brand', 'logo_url'), '/bad path.png', 'brand.logo_url:'),
    (('presentation', 'intro'), False, 'presentation.intro:'),
    (('presentation', 'accent_color'), 'red', 'presentation.accent_color:'),
    (('output', 'volume_label'), 'bad label', 'output.volume_label:'),
    (('desktops', 0), {}, 'desktops[0]:'),
    (('desktops', 0, 'id'), 'BAD', 'desktops[0].id:'),
    (('desktops', 0, 'description'), '', 'desktops[0].description:'),
    (('desktops', 0, 'default_flatpaks'), ['bad'], 'desktops[0].default_flatpaks[0]:'),
    (('variants', 0, 'name'), '', 'variants[0].name:'),
    (('curated_app_sets', 0, 'url'), 'http://example.org', 'curated_app_sets[0].url:'),
    (('ddi_channels', 0, 'stem'), 'BAD', 'ddi_channels[0].stem:'),
    (('default_selection', 'platform'), 'linux/bad', 'default_selection.platform:'),
])
def test_validation_errors_identify_the_field(path, value, expected):
    document = config()
    target = document
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(builder.ConfigError) as error:
        builder.validate(document)
    assert expected in str(error.value)


def test_named_image_reference_keeps_fixture_acceptance():
    cases = json.loads((ROOT / 'tests/fixtures/builder-config-image-references.json').read_text())
    for case in cases:
        assert bool(re.fullmatch(builder.IMAGE_REFERENCE, case['reference'])) is case['valid']


@pytest.mark.parametrize('failure', ['no-spec', 'no-loader', 'missing-file', 'unreadable-file'])
def test_primary_builder_loader_reports_config_error(monkeypatch, failure):
    document = primary.load()
    original = primary.importlib.util.spec_from_file_location

    class BrokenLoader:
        def create_module(self, spec):
            return None

        def exec_module(self, module):
            if failure == 'missing-file':
                raise FileNotFoundError('synthetic absent validator')
            raise PermissionError('synthetic unreadable validator')

    def spec_for(name, path, *args, **kwargs):
        spec = original(name, path, *args, **kwargs)
        if name != 'iso_builder_config':
            return spec
        if failure == 'no-spec':
            return None
        spec.loader = None if failure == 'no-loader' else BrokenLoader()
        return spec

    monkeypatch.setattr(primary.importlib.util, 'spec_from_file_location', spec_for)
    with pytest.raises(primary.ConfigError) as error:
        primary.validate(document)
    assert 'iso_builder:' in str(error.value)
    assert 'iso_builder_config.py' in str(error.value)
    if failure.endswith('-file'):
        assert isinstance(error.value.__cause__, OSError)


@pytest.mark.parametrize('command', ['generate-builder-config', 'check-builder-config'])
@pytest.mark.parametrize('kind', ['absent', 'regular-file'])
def test_output_parent_error_is_explicit_without_creating_directories(tmp_path, command, kind):
    parent = tmp_path / 'parent'
    if kind == 'regular-file':
        parent.write_text('preserve this file')
    target = parent / 'config.json'
    result = subprocess.run([sys.executable, str(ROOT / 'scripts/config.py'), command,
                             '--output', str(target)], capture_output=True, text=True)
    assert result.returncode == 1
    assert 'output parent must be an existing directory' in result.stderr
    assert str(parent) in result.stderr
    assert 'Traceback' not in result.stderr
    if kind == 'regular-file':
        assert parent.read_text() == 'preserve this file'
    else:
        assert not parent.exists()


@pytest.mark.parametrize('artifact', ['config', 'flavors'])
def test_custom_output_drift_names_matching_regeneration_arguments(tmp_path, artifact):
    target = tmp_path / 'custom.json'
    target.write_text('{}')
    result = subprocess.run([sys.executable, str(ROOT / 'scripts/config.py'),
                             f'check-builder-{artifact}', '--output', str(target)],
                            capture_output=True, text=True)
    assert result.returncode == 1
    assert str(target) in result.stderr
    assert f'generate-builder-{artifact} with the same --root and --output arguments' in result.stderr
    assert target.read_text() == '{}'
