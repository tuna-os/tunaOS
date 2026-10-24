from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from lib.iso_coverage_changes import affected_cells


def cells():
    return [{'id': f'{v}:{d}:linux/amd64', 'variant': v, 'flavor': d,
             'platform': 'linux/amd64', 'install_admitted': True}
            for v, d in [('skipjack', 'gnome'), ('skipjack', 'kde'), ('marlin', 'kde'), ('gurnard', 'pantheon')]]


def test_shared_changes_are_explicit_sample_plus_deferred():
    result = affected_cells(cells(), ['scripts/iso-e2e.sh'])
    assert len(result['affected_ids']) == 4
    assert len(result['selected']) == 2 and len(result['deferred']) == 2
    assert result['selected'][0]['id'] == 'skipjack:gnome:linux/amd64'
    assert result['overflow'] and not result['complete_coverage']
    assert result == affected_cells(list(reversed(cells())), ['scripts/iso-e2e.sh'])


def test_desktop_and_variant_scope_are_inventory_intersections():
    result = affected_cells(cells(), ['live-iso/common/src/desktop-kde.sh'])
    assert {c['flavor'] for c in result['selected']} == {'kde'}
    assert len(result['selected']) == 2 and not result['overflow']
    result = affected_cells(cells(), ['.github/workflows/build-marlin.yml'])
    assert [c['id'] for c in result['selected']] == ['marlin:kde:linux/amd64']


def test_unknown_and_config_changes_fail_broad_not_green():
    for path in ['tunaos.toml', 'new-runtime-file', 'live-iso/common/src/desktop-unknown.sh']:
        result = affected_cells(cells(), [path])
        assert len(result['affected_ids']) == 4
        assert result['overflow']


def test_docs_only_no_expensive_execution():
    assert affected_cells(cells(), ['docs/TESTING.md', 'tests/test_new.py'])['selected'] == []


@pytest.mark.parametrize('path', ['../outside', '/tmp/path', r'docs\outside', ''])
def test_invalid_paths_rejected(path):
    with pytest.raises(ValueError):
        affected_cells(cells(), [path])


def test_image_only_and_other_architecture_not_queued():
    extra = [dict(cells()[0], id='skipjack:tuna:linux/amd64', flavor='tuna', install_admitted=False),
             dict(cells()[0], id='skipjack:gnome:linux/arm64', platform='linux/arm64')]
    assert len(affected_cells(cells() + extra, ['tunaos.toml'])['affected_ids']) == 4


def test_runtime_test_specs_are_not_static_only():
    for path in ['tests/install-pipeline-screens.yaml', 'tests/installer-screens.yaml']:
        result = affected_cells(cells(), [path])
        assert len(result['affected_ids']) == 4
        assert result['overflow']
