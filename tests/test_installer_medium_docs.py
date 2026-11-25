"""The generated medium cell table is current and complete (tunaOS#4905).

AGENTS.md, PR quality contract rule 3: a status table is derived, never
transcribed. Falsification: change a cell in tunaos.toml or a record in the
evidence and this fails until scripts/gen-installer-medium-cells.py runs.
"""

import importlib.util
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GENERATOR = ROOT / "scripts/gen-installer-medium-cells.py"


def test_cells_md_is_current():
    done = subprocess.run([sys.executable, str(GENERATOR), "--check"], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr


def test_cells_md_names_every_cell_and_every_variant_target():
    spec = importlib.util.spec_from_file_location("c", ROOT / "scripts/lib/tunaos_config.py")
    config = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(config)
    primary = config.load()
    medium = config.installer_medium_policy()
    text = (ROOT / "installer-medium/docs/cells.md").read_text()
    for row in medium.resolve(primary):
        assert f"`{row['cell']}`" in text
    targets = medium.bootloader_targets(primary)
    assert [t["variant"] for t in targets] == list(primary["variants"])
    for target in targets:
        assert target["target"] in ("systemd-boot", "grub", "unknown") and target["reason"]
        assert f"| `{target['variant']}` |" in text
