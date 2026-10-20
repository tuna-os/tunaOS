"""Presentation config cannot replace catalog authority or drift from primary TOML."""
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('builder_config', ROOT / 'scripts/lib/iso_builder_config.py')
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)
SPEC2 = importlib.util.spec_from_file_location('primary_config', ROOT / 'scripts/lib/tunaos_config.py')
primary = importlib.util.module_from_spec(SPEC2)
SPEC2.loader.exec_module(primary)


def config():
    return builder.project(primary.load())


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
def test_duplicate_ids_rejected(field):
    doc = config()
    doc[field].append(copy.deepcopy(doc[field][0]))
    with pytest.raises(builder.ConfigError):
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
    doc['iso_builder']['default_selection']['platform'] = 'linux/amd64/v3'
    with pytest.raises(builder.ConfigError):
        builder.project(doc)
    doc = primary.load()
    doc.pop('iso_builder')
    with pytest.raises(builder.ConfigError, match='no stock fallback'):
        builder.project(doc)


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
