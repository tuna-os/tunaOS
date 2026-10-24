"""Primary configuration documentation survives the supported edit boundaries."""
import copy
import hashlib
import json
from pathlib import Path
import re

from scripts.lib import package_authoring as author
from scripts.lib import tunaos_config as config
from scripts.lib import iso_builder_config as builder

ROOT = Path(__file__).resolve().parents[1]


def full_line_comments(source):
    return [line for line in source.splitlines() if line.lstrip().startswith(b'#')]


def test_package_edit_preserves_all_primary_section_comments():
    source = (ROOT / 'tunaos.toml').read_bytes()
    anchor = b'"gnome-base/gnome-light",'
    assert source.count(anchor) == 1
    source = source.replace(anchor, anchor + b' # inline edit sentinel', 1)
    document = config.validate(config.parse(source))
    scope = {'gnome:emerge': ('gnome', 'emerge')}
    resolved = {'gnome:emerge': 'sys-process/tunaos-comment-test'}
    edited = author.edit(source, document, scope, resolved)
    assert full_line_comments(edited) == full_line_comments(source)
    inserted = b'  "sys-process/tunaos-comment-test",\n'
    assert edited.count(inserted) == 1
    assert edited.replace(inserted, b'', 1) == source
    assert b'"gnome-base/gnome-light", # inline edit sentinel' in edited
    expected = copy.deepcopy(document)
    expected['desktops']['gnome']['packages']['emerge']['required'].append(resolved['gnome:emerge'])
    assert config.parse(edited) == expected
    assert author.edit(edited, expected, scope, resolved) == edited


def test_comment_only_edits_do_not_change_generated_adapters():
    source = (ROOT / 'tunaos.toml').read_bytes()
    before = config.validate(config.parse(source))
    after = config.validate(config.parse(b'# Additional author guidance.\n' + source))
    assert before == after
    # Unsorted JSON also pins key order, which the generated adapters inherit.
    assert json.dumps(before, ensure_ascii=False) == json.dumps(after, ensure_ascii=False)
    for render in (config.render, builder.render, builder.render_flavors,
                   config.flatpak_policy().render):
        rendered_after = render(after)
        assert render(before) == rendered_after
    policy = config.package_policy()
    select = lambda document: {key: document[key] for key in ('package_groups', 'desktops')}
    assert policy.desktop_outputs(select(before)) == policy.desktop_outputs(select(after))


def test_comment_only_edit_changes_only_debian_source_provenance():
    source = (ROOT / 'tunaos.toml').read_bytes()
    edited = b'# Source provenance includes comments.\n' + source
    policy = config.package_policy()
    contracts = []
    for raw in (source, edited):
        document = config.validate(config.parse(raw))
        contracts.append(policy.installation_contract(
            document, hashlib.sha256(raw).hexdigest(), 'flounder', 'gnome',
            'linux/amd64', manager='apt', os_id='debian'))
    before, after = contracts
    assert before['source_sha256'] != after['source_sha256']
    before['source_sha256'] = after['source_sha256']
    assert before == after


def test_renovate_pin_match_preserves_comments_and_unrelated_bytes():
    settings = json.loads((ROOT / 'renovate.json').read_text())
    manager = next(item for item in settings['customManagers']
                   if item.get('managerFilePatterns') == [r'/^tunaos\.toml$/'])
    # Convert named captures only; test the checked-in manager, not a parallel regex.
    pattern = re.sub(r'\(\?<([A-Za-z][A-Za-z0-9_]*)>', r'(?P<\1>', manager['matchStrings'][0])
    source_bytes = (ROOT / 'tunaos.toml').read_bytes()
    source = source_bytes.decode('utf-8')
    document = config.parse(source_bytes)
    old = document['variants']['yellowfin']['base_image']
    source = source.replace(f'base_image = "{old}"',
                            f'# Pin guidance sentinel\nbase_image = "{old}" # trailing pin guidance', 1)
    match = next(item for item in re.finditer(pattern, source) if item.group('currentDigest') == old.split('@')[1])
    digest = 'sha256:' + '0' * 64
    start, end = match.span('currentDigest')
    edited = source[:start] + digest + source[end:]
    assert full_line_comments(edited.encode()) == full_line_comments(source.encode())
    assert '# trailing pin guidance' in edited
    assert edited[:start] == source[:start] and edited[start + len(digest):] == source[end:]
    expected = copy.deepcopy(document)
    expected['variants']['yellowfin']['base_image'] = old.split('@')[0] + '@' + digest
    assert config.validate(config.parse(edited.encode('utf-8'))) == expected
