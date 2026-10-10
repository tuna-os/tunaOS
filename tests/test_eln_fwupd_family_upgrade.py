"""ELN upgrades the complete installed firmware daemon family strictly."""
from pathlib import Path


def test_native_family_upgrade_precedes_new_package_transactions():
    root = Path(__file__).resolve().parents[1]
    source = (root / "build_scripts/10-base-packages.sh").read_text()
    start = source.index("elif [[ ${IS_ELN:-false} == true ]]; then")
    end = source.index("\nelif ", start + 1)
    branch = source[start:end]
    upgrade = branch.index("dnf -y upgrade 'fwupd*'")
    check = branch.index("dnf -y check", upgrade)
    assert upgrade < check < branch.index("dnf -y install")
    assert "--allowerasing" not in branch[:check]
    assert "--skip-broken" not in branch[:check]
    assert "|| true" not in branch[:check]
