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


@pytest.mark.parametrize('field', ['id', 'desktop', 'edition'])
@pytest.mark.parametrize('suffix', ['\n', '\r', '\r\n', '\u0085', '\u2028', '\u2029', '\x00', '\x1f', '\x7f', ' ', '\ufeff'])
def test_flavor_schema_rejects_nonidentifier_suffixes(field, suffix):
    schema = pytest.importorskip('jsonschema')
    document = {'schema_version': 1, 'kind': 'builder-flavor-metadata',
                'flavors': [{'id': 'gnome', 'desktop': 'gnome', 'edition': 'standard'}]}
    document['flavors'][0][field] += suffix
    with pytest.raises(schema.ValidationError):
        schema.validate(document, json.loads((ROOT / 'docs/iso-builder-flavors.schema.json').read_text()))
    with pytest.raises(builder.ConfigError):
        builder.pattern(document['flavors'][0][field], r'[a-z0-9][a-z0-9-]{0,63}')


def test_all_builder_schema_patterns_use_strict_end_assertions():
    # Falsification: adding a terminal-dollar pattern reintroduces LF acceptance.
    patterns = []

    def collect(value):
        if isinstance(value, dict):
            if 'pattern' in value:
                patterns.append(value['pattern'])
            for child in value.values():
                collect(child)
        elif isinstance(value, list):
            for child in value:
                collect(child)

    for name in ('iso-builder-config.schema.json', 'iso-builder-flavors.schema.json'):
        collect(json.loads((ROOT / 'docs' / name).read_text()))
    assert patterns
    assert all(pattern.endswith(r'(?![\s\S])') for pattern in patterns)


def test_flavor_schema_identifier_patterns_match_ecmascript():
    import re
    import shutil
    import subprocess
    node = shutil.which('node')
    if node is None:
        pytest.skip('Node is needed to verify ECMAScript regex behavior')
    schema = json.loads((ROOT / 'docs/iso-builder-flavors.schema.json').read_text())
    patterns = [item['pattern'] for item in schema['properties']['flavors']['items']['properties'].values()]
    values = ['gnome', 'kde-nvidia', 'none', 'a' * 64, 'a' * 65, 'gnome\n',
              'gnome\r', 'gnome\u2028', 'gnome\u2029', 'gnome\x00', 'gnome\ufeff', '']
    cases = [[pattern, value] for pattern in patterns for value in values]
    script = 'let s="";process.stdin.on("data",x=>s+=x);process.stdin.on("end",()=>process.stdout.write(JSON.stringify(JSON.parse(s).map(([p,v])=>new RegExp(p).test(v)))));'
    result = subprocess.run([node, '-e', script], input=json.dumps(cases), text=True,
                            capture_output=True, check=True)
    expected = [bool(re.fullmatch(r'[a-z0-9][a-z0-9-]{0,63}', value)) for _, value in cases]
    assert json.loads(result.stdout) == expected


def test_all_schema_string_constraints_match_ecmascript_corpus():
    import re
    import shutil
    import subprocess
    node = shutil.which('node')
    if node is None:
        pytest.skip('Node is needed to verify ECMAScript regex behavior')
    constraints = []

    def collect(value):
        if isinstance(value, dict):
            if 'pattern' in value:
                constraints.append({key: value[key] for key in ('pattern', 'minLength', 'maxLength') if key in value})
            for child in value.values():
                collect(child)
        elif isinstance(value, list):
            for child in value:
                collect(child)

    for name in ('iso-builder-config.schema.json', 'iso-builder-flavors.schema.json'):
        collect(json.loads((ROOT / 'docs' / name).read_text()))
    unique = {json.dumps(item, sort_keys=True): item for item in constraints}
    samples = ['', 'gnome', 'kde-nvidia', 'linux/amd64', 'linux/amd64/v3',
               'ghcr.io/example/image:stable', '/assets/logo.png', '#abcdef',
               'ORG_LABEL', 'org.example.Application', 'leaf:gnome:linux/amd64',
               'https://example.org/path', 'Readable text', '<', 'a>b']
    suffixes = ['', '\n', '\r\n', '\x00', '\x1f', '\x7f', '\u0085', '\ufeff',
                '\u00a0', '\u1680', '\u2000', '\u2028', '\u2029', '\u202f', '\u205f', '\u3000']
    values = [sample + suffix for sample in samples for suffix in suffixes]
    values += [char * size for char in ('a', '\U0001f41f')
               for size in (1, 31, 32, 33, 63, 64, 65, 127, 128, 129, 191, 192, 193, 254, 255, 256, 2048, 2049)]
    expected = []
    for item in unique.values():
        for value in values:
            expected.append(bool(re.search(item['pattern'], value)) and
                            len(value) >= item.get('minLength', 0) and
                            len(value) <= item.get('maxLength', len(value)))
    script = 'let s="";process.stdin.on("data",x=>s+=x);process.stdin.on("end",()=>{const [ps,vs]=JSON.parse(s);process.stdout.write(JSON.stringify(ps.flatMap(p=>vs.map(v=>{const n=Array.from(v).length;return new RegExp(p.pattern).test(v)&&n>=(p.minLength??0)&&n<=(p.maxLength??n)}))))});'
    result = subprocess.run([node, '-e', script], input=json.dumps([list(unique.values()), values]),
                            text=True, capture_output=True, check=True)
    assert json.loads(result.stdout) == expected


def test_common_text_fields_preserve_python_acceptance():
    schema = pytest.importorskip('jsonschema')
    document = json.loads((ROOT / 'docs/iso-builder-config.schema.json').read_text())
    fixture = json.loads((ROOT / 'tests/fixtures/builder-config-common-text.json').read_text())
    fields = []

    def collect(value):
        if isinstance(value, dict):
            if 'pattern' in value and '[^' + fixture['python_whitespace_class'] + ']' in value['pattern']:
                fields.append(value)
            for child in value.values():
                collect(child)
        elif isinstance(value, list):
            for child in value:
                collect(child)

    collect(document)
    assert len(fields) == 15
    for field in fields:
        validator = schema.Draft202012Validator(field)
        for case in fixture['cases']:
            assert validator.is_valid(case['value']) is case['valid']
            if case['valid']:
                builder.text(case['value'])
            else:
                with pytest.raises(builder.ConfigError):
                    builder.text(case['value'])


@pytest.mark.parametrize('identifier,accepted', [
    ('a' * 64, True), ('a' * 65, False), ('gnome-hwe', True),
    ('gnome\n', False), ('gnome\r\n', False), ('gnome\u2028', False),
    ('gnome\x00', False), ('gnome\ufeff', False), ('foo.bar', False),
    ('foo/bar', False), ('Upper', False), ('', False),
])
def test_flavor_metadata_export_bounds_its_identifier_keys(identifier, accepted):
    schema = pytest.importorskip('jsonschema')
    # Isolate the exporter with matching source IDs; a wide primary identifier
    # must not bypass the narrower portable contract at this boundary.
    document = {
        'variants': {'example': {'flavors': [{'id': identifier}]}},
        'desktops': {'gnome': {}},
        'flavor_metadata': {identifier: {'desktop': 'gnome', 'edition': 'standard'}},
    }
    if accepted:
        exported = builder.flavor_metadata(document)
        assert exported['flavors'][0]['id'] == identifier
        schema.validate(exported, json.loads((ROOT / 'docs/iso-builder-flavors.schema.json').read_text()))
    else:
        with pytest.raises(builder.ConfigError, match='flavor_metadata'):
            builder.flavor_metadata(document)


def test_every_projected_field_boundary_is_schema_valid_or_rejected():
    schema = pytest.importorskip('jsonschema')
    validator = schema.Draft202012Validator(json.loads((ROOT / 'docs/iso-builder-config.schema.json').read_text()))
    source = primary.load()
    v1 = json.loads((ROOT / 'tests/fixtures/builder-config/v1.json').read_text())
    for presentation in (v1, source['iso_builder']):
        baseline = copy.deepcopy(source)
        baseline['iso_builder'] = presentation
        validator.validate(builder.project(baseline))
        fields = []

        def collect(value, path=()):
            if isinstance(value, dict):
                for key, child in value.items():
                    collect(child, (*path, key))
            elif isinstance(value, list):
                fields.append((path, value))
                for index, child in enumerate(value):
                    collect(child, (*path, index))
            elif isinstance(value, str):
                fields.append((path, value))

        collect(presentation)
        for path, original in fields:
            if isinstance(original, str):
                candidates = ['', original + '\n', original + '\r\n', original + '\x00',
                              '\u0085', '\ufeff', 'a' * 64, 'a' * 65,
                              '\U0001f41f' * 2048, '\U0001f41f' * 2049]
            else:
                candidates = [[]]
                if original:
                    candidates += [[copy.deepcopy(original[0]) for _ in range(size)]
                                   for size in (1, 4, 5, 8, 9, 10, 11, 256, 257)]
            for candidate in candidates:
                document = copy.deepcopy(baseline)
                node = document['iso_builder']
                for part in path[:-1]:
                    node = node[part]
                node[path[-1]] = candidate
                try:
                    exported = builder.project(document)
                except builder.ConfigError:
                    continue
                errors = list(validator.iter_errors(exported))
                assert not errors, (path, errors[0].message)


def test_flavor_export_array_and_value_boundaries():
    schema = pytest.importorskip('jsonschema')
    validator = schema.Draft202012Validator(json.loads((ROOT / 'docs/iso-builder-flavors.schema.json').read_text()))
    empty = {'variants': {}, 'desktops': {}, 'flavor_metadata': {}}
    with pytest.raises(builder.ConfigError, match='flavor_metadata'):
        builder.flavor_metadata(empty)
    for count in (1, 64, 256, 257):
        document = {
            'variants': {'example': {'flavors': [{'id': f'flavor-{i}'} for i in range(count)]}},
            'desktops': {'gnome': {}},
            'flavor_metadata': {f'flavor-{i}': {'desktop': 'gnome', 'edition': 'standard'} for i in range(count)},
        }
        validator.validate(builder.flavor_metadata(document))
    for field in ('desktop', 'edition'):
        for value in ('a' * 64, 'a' * 65, 'gnome', 'none', '', 'gnome\n', 'gnome\r\n',
                      'gnome\x00', '\u0085', '\ufeff', 'foo.bar', 'foo/bar'):
            document = {
                'variants': {'example': {'flavors': [{'id': 'gnome'}]}},
                'desktops': {'gnome': {}, 'a' * 64: {}, 'a' * 65: {}},
                'flavor_metadata': {'gnome': {'desktop': 'gnome', 'edition': 'standard'}},
            }
            document['flavor_metadata']['gnome'][field] = value
            try:
                exported = builder.flavor_metadata(document)
            except builder.ConfigError:
                continue
            validator.validate(exported)
