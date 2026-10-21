"""Guided presentation never invents targets or duplicates primary semantics."""
import copy
import json
import pytest
from tests.test_iso_builder_config import ROOT, builder, primary


def config():
    return builder.project(primary.load())


def test_v2_generated_and_schema():
    doc = config()
    assert doc['schema_version'] == 2
    assert 'variants' not in doc
    assert all(set(d) == {'id', 'default_flatpaks'} for d in doc['desktops'])
    schema = pytest.importorskip('jsonschema')
    schema.validate(doc, json.loads((ROOT / 'docs/iso-builder-config.schema.json').read_text()))


def test_flavor_metadata_is_exact_and_deterministic():
    doc = primary.load()
    metadata = builder.flavor_metadata(doc)
    assert (ROOT / 'docs/iso-builder.flavors.json').read_text() == builder.render_flavors(doc)
    flavors = {f['id']: f for f in metadata['flavors']}
    assert flavors['gnome-hwe'] == {'id': 'gnome-hwe', 'desktop': 'gnome', 'edition': 'hwe'}
    assert flavors['kde-nvidia'] == {'id': 'kde-nvidia', 'desktop': 'kde', 'edition': 'nvidia'}
    assert flavors['base']['desktop'] == 'none'
    assert list(flavors) == sorted(flavors)
    assert set(flavors) == {f['id'] for v in doc['variants'].values() for f in v['flavors']}
    doc['flavor_metadata'].pop('gnome-hwe')
    with pytest.raises(builder.ConfigError):
        builder.flavor_metadata(doc)


@pytest.mark.parametrize('path', [(), ('selection',), ('selection','paths',0), ('selection','facets',0), ('selection','facets',0,'values',0), ('selection','recommendations',0), ('desktops',0), ('default_selection',)])
def test_unknown_v2_fields_fail_closed(path):
    doc=config();node=doc
    for key in path:
        node=node[key]
    node['unexpected']=True
    with pytest.raises(builder.ConfigError):
        builder.validate(doc)


@pytest.mark.parametrize('mutation', [
    lambda d: d['selection'].update(default_path='missing'),
    lambda d: d['selection']['paths'][0].update(facets=['missing']),
    lambda d: d['selection']['paths'][0].update(facets=['desktop','desktop']),
    lambda d: d['selection']['facets'][0].update(id='unknown'),
    lambda d: d['selection']['facets'][0]['values'].append(copy.deepcopy(d['selection']['facets'][0]['values'][0])),
    lambda d: d['selection']['facets'][0].update(values=[]),
    lambda d: d['selection']['recommendations'].append(copy.deepcopy(d['selection']['recommendations'][0])),
    lambda d: d['default_selection'].update(kind='image',image='ghcr.io/example/example:stable'),
    lambda d: d['desktops'][0].update(id='missing'),
    lambda d: d['default_selection'].update(leaf_id=True),
])
def test_invalid_v2_references_and_types(mutation):
    doc=config();mutation(doc)
    with pytest.raises(builder.ConfigError):
        builder.validate(doc)


def test_portable_none_default_and_preview_leaf():
    doc=config();doc['preview_only']=True;doc['brand']['disclaimer']='Unofficial preview.'
    doc['default_selection']={'kind':'none'}
    assert builder.validate(doc)==doc
    doc['default_selection']={'kind':'leaf','leaf_id':'example/stable/linux/amd64'}
    assert builder.validate(doc)==doc
    # Cross-artifact existence is the guided join's obligation, not a fabricated
    # snapshot or remote fetch by the portable presentation validator.


def test_primary_recommendations_are_enabled_and_visible():
    doc=primary.load();doc['iso_builder']['selection']['recommendations'][0]['leaf_id']='missing:gnome:linux/amd64'
    with pytest.raises(builder.ConfigError):
        builder.project(doc)
    doc=primary.load();doc['iso_builder']['selection']['facets'][0]['values'].pop(0)
    with pytest.raises(builder.ConfigError):
        builder.project(doc)


def test_bounded_card_and_palette():
    doc=config()
    doc['presentation']['colors']={k:'#10151f' for k in ('background','surface','text','muted','accent','accent_text')}
    doc['presentation']['colors'].update(border='#4b4b4b',hover_surface='#343434',focus='#782fdb',selected_surface='#1543b4')
    value=doc['selection']['facets'][0]['values'][0]
    value['card']={'image_url':'/assets/desktop.png','image_alt':'Desktop artwork','badge':'Preview'}
    assert builder.validate(doc)==doc
    value['card']['image_url']='//untrusted.example/image.png'
    with pytest.raises(builder.ConfigError):
        builder.validate(doc)


@pytest.mark.parametrize('bad', ['<script>', 'x'*2049, 'bad\x7ftext'])
def test_selection_text_is_bounded_plain_text(bad):
    doc=config();doc['selection']['paths'][0]['label']=bad
    with pytest.raises(builder.ConfigError):
        builder.validate(doc)


@pytest.mark.parametrize('key,good,bad', [('choice_style','thumbnail','arbitrary-css'),('font_family','inter','https://example.org/font.woff2')])
def test_presentation_style_uses_fixed_tokens(key,good,bad):
    doc=config();doc['presentation'][key]=good
    assert builder.validate(doc)==doc
    doc['presentation'][key]=bad
    with pytest.raises(builder.ConfigError):
        builder.validate(doc)


def test_graphics_generation_is_explicit_supported_facet():
    doc=config()
    doc['selection']['facets'].append({'id':'graphics_generation','label':'NVIDIA generation','values':[{'id':'modern','label':'Modern'},{'id':'legacy','label':'Legacy'}]})
    doc['selection']['paths'][0]['facets'].append('graphics_generation')
    assert builder.validate(doc)==doc
    schema=pytest.importorskip('jsonschema')
    schema.validate(doc,json.loads((ROOT/'docs/iso-builder-config.schema.json').read_text()))


def test_flavor_export_matches_portable_schema():
    schema=pytest.importorskip('jsonschema')
    schema.validate(builder.flavor_metadata(primary.load()),json.loads((ROOT/'docs/iso-builder-flavors.schema.json').read_text()))


SELECTION_TEXT_FIELDS = [
    ('paths', 0, 'label'), ('facets', 0, 'label'),
    ('facets', 0, 'description'), ('facets', 0, 'values', 0, 'label'),
    ('facets', 0, 'values', 0, 'description'),
    ('facets', 0, 'values', 0, 'card', 'image_alt'),
    ('facets', 0, 'values', 0, 'card', 'badge'),
    ('recommendations', 0, 'label'), ('recommendations', 0, 'reason'),
]


@pytest.mark.parametrize('path', SELECTION_TEXT_FIELDS)
@pytest.mark.parametrize('value,accepted', [
    ('Visible text', True), ('a' * 2048, True),
    ('\U0001f41f' * 2048, True), ('\U0001f41f' * 2049, False),
    ('<', False), ('>', False), ('a<b', False), ('a>b', False),
    ('', False), ('   ', False), ('a\n', False), ('a\x7f', False),
    ('a' * 2049, False), ('\u0085', False), ('\ufeff', True),
    ('text\u0085', True), ('text\ufeff', True),
])
def test_selection_text_schema_and_reference_parity(path, value, accepted):
    schema = pytest.importorskip('jsonschema')
    document = config()
    document['selection']['facets'][0]['values'][0]['card'] = {
        'image_url': '/art.png', 'image_alt': 'Artwork', 'badge': 'Preview',
    }
    node = document['selection']
    for part in path[:-1]:
        node = node[part]
    node[path[-1]] = value
    validator = schema.Draft202012Validator(json.loads((ROOT / 'docs/iso-builder-config.schema.json').read_text()))
    assert validator.is_valid(document) is accepted
    if accepted:
        assert builder.validate(document) == document
    else:
        with pytest.raises(builder.ConfigError):
            builder.validate(document)


@pytest.mark.parametrize('facet', builder.FACETS)
@pytest.mark.parametrize('value', [
    'normal-id', 'linux/amd64', 'linux/amd64/v2', 'linux/amd64/v3',
    'linux/arm64', 'linux/mips64', 'foo.bar', 'foo/bar', '<',
    'Upper', 'a' * 64, 'a' * 65, 'id\n', 'id\x7f',
])
def test_facet_value_schema_and_reference_parity(facet, value):
    import re
    schema = pytest.importorskip('jsonschema')
    document = config()
    document['desktops'] = []
    document['curated_app_sets'] = []
    document['ddi_channels'] = []
    document['selection'] = {
        'paths': [{'id': 'choose', 'label': 'Choose', 'facets': [facet]}],
        'default_path': 'choose', 'recommendations': [],
        'facets': [{'id': facet, 'label': 'Choice', 'values': [{'id': value, 'label': 'Value'}]}],
    }
    document['default_selection'] = {'kind': 'none'}
    accepted = value in builder.PLATFORMS if facet == 'platform' else bool(re.fullmatch(r'[a-z0-9][a-z0-9-]{0,63}', value))
    validator = schema.Draft202012Validator(json.loads((ROOT / 'docs/iso-builder-config.schema.json').read_text()))
    assert validator.is_valid(document) is accepted
    if accepted:
        assert builder.validate(document) == document
    else:
        with pytest.raises(builder.ConfigError):
            builder.validate(document)


def test_selection_schema_text_patterns_match_ecmascript_whitespace():
    # Preserve Python strip semantics: lone FEFF is accepted, lone 0085 is not.
    # This is an explicit nonblank policy, not a visible-character guarantee.
    import re
    import shutil
    import subprocess
    node = shutil.which('node')
    if node is None:
        pytest.skip('Node is needed to verify ECMAScript regex behavior')
    document = json.loads((ROOT / 'docs/iso-builder-config.schema.json').read_text())
    patterns = []

    def collect(value):
        if isinstance(value, dict):
            if value.get('maxLength') == 2048 and 'pattern' in value:
                patterns.append(value['pattern'])
            for child in value.values():
                collect(child)
        elif isinstance(value, list):
            for child in value:
                collect(child)

    collect(document['oneOf'][1]['properties']['selection'])
    assert len(patterns) == 9
    fixture = json.loads((ROOT / 'tests/fixtures/builder-config-selection-text.json').read_text())
    values = [case['value'] for case in fixture['cases']]
    cases = [[pattern, value] for pattern in patterns for value in values]
    script = 'let s="";process.stdin.on("data",x=>s+=x);process.stdin.on("end",()=>process.stdout.write(JSON.stringify(JSON.parse(s).map(([p,v])=>Array.from(v).length<=2048&&new RegExp(p).test(v)))));'
    result = subprocess.run([node, '-e', script], input=json.dumps(cases), text=True,
                            capture_output=True, check=True)
    expected = [len(value) <= 2048 and bool(re.search(pattern, value)) for pattern, value in cases]
    assert expected == [case['valid'] for _ in patterns for case in fixture['cases']]
    assert json.loads(result.stdout) == expected
