"""Exercise the native job budget without pinning workflow source spelling."""

from pathlib import Path

import yaml

from tests.test_a_job_budget_covers_its_own_steps import _budgets

ROOT = Path(__file__).resolve().parents[1]


def test_native_job_retains_its_bounded_budget_choices():
    workflow = yaml.safe_load((ROOT / '.github/workflows/iso-e2e.yml').read_text())
    assert _budgets(workflow['jobs']['e2e']['timeout-minutes']) == [120, 160, 90, 30]
