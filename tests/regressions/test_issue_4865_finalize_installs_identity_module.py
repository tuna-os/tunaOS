"""bootc/finalize.sh must install the identity module before its dracut run.

grouper:tuna failed verify-initrd-hostname.sh with PRETTY_NAME
'Grouper dracut-110-11ubuntu0.1 (Initramfs)' (run 45685666728): finalize.sh
runs dracut directly, bypassing dracut-config.sh, so initrd-hostname.sh (which
installs 99tunaos-identity and its add_dracutmodules drop-in) never ran.
"""
from pathlib import Path

FINALIZE = Path(__file__).resolve().parents[2] / "build_scripts/bootc/finalize.sh"


def test_initrd_hostname_runs_before_dracut():
    lines = FINALIZE.read_text().splitlines()
    code = [l for l in lines if not l.lstrip().startswith("#")]
    setup = next(i for i, l in enumerate(code) if "build_scripts/initrd-hostname.sh" in l)
    dracut = next(i for i, l in enumerate(code) if l.startswith("dracut --force"))
    assert setup < dracut
