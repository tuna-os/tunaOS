"""Live media turn off NetworkManager's connectivity check.

bonito-kde (iso-builder run 43819011919): the Plasma "Limited Connectivity"
notification covered the installer's "Get started" button on both legs, so the
strict walkthrough stopped on Welcome.
"""
import re
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "live-iso" / "common" / "src" / "customize-live.sh"


def test_the_live_conf_disables_the_check(tmp_path):
    """Falsification: without the function no conf is written and NetworkManager
    keeps probing, so the notification returns on offline live media."""
    text = SCRIPT.read_text()
    fn = re.search(r"^live_no_connectivity_check\(\) \{\n.*?^\}\n", text, re.S | re.M)
    assert fn, "live_no_connectivity_check not found"
    assert "\nlive_no_connectivity_check\n" in text, "the function must be called"
    subprocess.run(["bash", "-c", fn.group(0) + "live_no_connectivity_check"],
                   env={"TUNAOS_LIVE_ROOT": str(tmp_path), "PATH": "/usr/bin:/bin"}, check=True)
    conf = tmp_path / "etc/NetworkManager/conf.d/90-tunaos-live-no-connectivity-check.conf"
    assert conf.read_text() == "[connectivity]\nenabled=false\n"
