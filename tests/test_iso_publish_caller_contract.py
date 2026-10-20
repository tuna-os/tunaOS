"""Falsification: PR3431's publisher passed an undeclared workflow input and omitted Actions read permission."""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def workflows():
    caller = yaml.load((ROOT / '.github/workflows/publish-isos.yml').read_text(), Loader=yaml.BaseLoader)
    callee = yaml.load((ROOT / '.github/workflows/reusable-build-artifacts.yml').read_text(), Loader=yaml.BaseLoader)
    return caller['jobs']['build-and-publish'], callee


def test_iso_publish_only_passes_declared_reusable_inputs():
    """Falsification: an undeclared input prevents GitHub from creating the job."""
    caller, callee = workflows()
    assert caller['uses'] == './.github/workflows/reusable-build-artifacts.yml'
    assert set(caller['with']) <= set(callee['on']['workflow_call']['inputs'])
    assert 'cutover-check' not in caller['with']


def test_iso_publish_grants_existing_callee_actions_read():
    """Falsification: explicit caller permissions cannot omit a callee's read grant."""
    caller, callee = workflows()
    assert callee['permissions']['actions'] == 'read'
    assert caller['permissions']['actions'] == 'read'
    assert caller['permissions'] == {
        'contents': 'read', 'packages': 'read', 'id-token': 'write', 'actions': 'read'
    }


def test_iso_publish_keeps_upload_opt_out():
    """Falsification: fixing the call contract must not force publication."""
    caller, _ = workflows()
    assert caller['with']['upload-r2'] == '${{ inputs.skip_upload != true }}'
