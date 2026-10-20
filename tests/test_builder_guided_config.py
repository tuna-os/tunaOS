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
