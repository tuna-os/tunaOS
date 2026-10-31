"""Bounded draft coverage plans are inventory, never execution evidence."""
from collections import Counter
from datetime import timedelta
import importlib.util
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
spec = importlib.util.spec_from_file_location('iso_coverage_plan', ROOT / 'scripts/plan-iso-coverage.py')
planner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(planner)


def test_inventory_matches_admissions():
    cells = planner.inventory(planner.load())
    assert len({c['id'] for c in cells}) == len(cells)
    assert not any(c['variant'] == 'flounder' and c['flavor'] == 'gnome' for c in cells)
    assert not any(c['variant'] == 'grouper' and c['flavor'] == 'niri' for c in cells)
    tuna = [c for c in cells if c['flavor'] == 'tuna']
    assert tuna and all(not c['install_admitted'] and not c['required_modes'] for c in tuna)
    assert any(c['flavor'] == 'pantheon' for c in cells)
    assert any(c['variant'] == 'sailfin' and c['flavor'] == 'kde' for c in cells)
    assert all(c['strict_gui_status'] == 'unqualified' for c in cells)


def test_complete_bounded_repeatable_rotation():
    config = planner.load()
    seen = Counter()
    for offset in range(28):
        day = planner.EPOCH + timedelta(days=offset)
        result = planner.plan(config, day)
        assert len(result['selected']) <= 2
        assert result['selected'] == planner.plan(config, day + timedelta(days=28))['selected']
        assert not result['execution_enabled']
        for cell in result['selected']:
            assert cell['platform'] == 'linux/amd64'
            assert cell['required_modes'] == ['plain', 'luks']
            seen[cell['id']] += 1
    expected = {c['id'] for c in planner.inventory(config) if c['install_admitted'] and c['platform'] == 'linux/amd64'}
    assert set(seen) == expected
    assert set(seen.values()) == {1}


def test_capacity_cannot_silently_drop_cells():
    with pytest.raises(ValueError, match='exceed'):
        planner.plan(planner.load(), planner.EPOCH, period=1, capacity=2)


@pytest.mark.parametrize('cell', ['flounder:gnome:linux/amd64', 'marlin:tuna:linux/amd64', 'bonito:kde:linux/arm64'])
def test_explicit_selection_fails_closed(cell):
    with pytest.raises(ValueError, match='non-admitted'):
        planner.plan(planner.load(), planner.EPOCH, selected=[cell])


def test_changed_cells_and_empty_selection():
    config = planner.load()
    ids = [c['id'] for c in planner.inventory(config) if c['install_admitted'] and c['platform'] == 'linux/amd64']
    assert [c['id'] for c in planner.plan(config, planner.EPOCH, selected=ids[:2])['selected']] == ids[:2]
    assert planner.plan(config, planner.EPOCH, selected=[])['selected'] == []
    with pytest.raises(ValueError, match='exceeds budget'):
        planner.plan(config, planner.EPOCH, selected=ids[:3])


def test_draft_workflow_schedule_is_gated_and_default_dispatch_is_plan_only():
    workflow = (ROOT / '.github/workflows/iso-coverage-plan.yml').read_text()
    assert "vars.TUNAOS_ISO_COVERAGE_ENABLED == 'true'" in workflow
    assert "needs.plan.outputs.ready == 'true'" in workflow
    assert "cron: '15 4 * * *'" in workflow
    assert 'default: false' in workflow
    assert 'max-parallel: 2' in workflow
    assert 'uses: ./.github/workflows/luks-e2e.yml' in workflow
    assert 'checkpoint_strict: false' in workflow
    assert 'retention-days: 90' in workflow


def test_receipt_cli_never_executes_unresolved_or_receipt_supplied_cells(tmp_path):
    import json
    import subprocess
    receipts = tmp_path / 'receipts.json'
    expected = tmp_path / 'expected.json'
    receipts.write_text('{"schema_version":1,"receipts":[]}')
    expected.write_text('{}')
    result = subprocess.run([sys.executable, str(ROOT / 'scripts/plan-iso-coverage.py'),
                             '--date', '2026-10-23', '--receipts', str(receipts),
                             '--expected-inputs', str(expected), '--now', '2026-10-23T12:00:00Z'],
                            check=True, capture_output=True, text=True)
    report = json.loads(result.stdout)
    assert report['selected'] == []
    assert len(report['catchup']['blocked']) == 64
    assert report['legacy_selected_timeout_ceiling_minutes'] == 0


def test_changed_path_cli_reports_deferred_scope():
    import json
    import subprocess
    result = subprocess.run([sys.executable, str(ROOT / 'scripts/plan-iso-coverage.py'),
                             '--date', '2026-10-23', '--changed-path', 'tunaos.toml'],
                            check=True, capture_output=True, text=True)
    report = json.loads(result.stdout)
    assert len(report['selected']) == 2
    assert len(report['changes']['deferred']) == report['baseline_install_cells'] - 2
    assert report['changes']['selection_kind'] == 'representative sample'


def test_execution_reruns_cannot_bypass_daily_receipt_budget():
    workflow = (ROOT / '.github/workflows/iso-coverage-plan.yml').read_text()
    assert 'if [[ "$GITHUB_RUN_ATTEMPT" != "1" ]]' in workflow
    assert 'Execution reruns are disabled' in workflow
    assert 'iso-coverage-plan-${{ github.run_id }}-${{ github.run_attempt }}' in workflow


def test_failed_job_reruns_cannot_reuse_a_prior_budgeted_plan():
    workflow = (ROOT / '.github/workflows/iso-coverage-plan.yml').read_text()
    callee = (ROOT / '.github/workflows/luks-e2e.yml').read_text()
    assert "github.run_attempt == '1' && needs.plan.outputs.ready" in workflow
    assert "inputs.coverage_capture && github.run_attempt != '1'" in callee
    assert callee.index('Refuse coverage execution reruns') < callee.index('- name: Checkout')
