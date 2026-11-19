"""Pantheon: a fresh greeter after Initial Setup creates the first account.

gurnard-pantheon (iso-builder run 44516439600): /etc/shadow held a `$y$` hash
for the new account, and io.elementary.greeter still showed "Account
disabled" for 13 minutes, because its card was made while the account was
locked.
"""
import os
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "build_scripts" / "desktop" / "pantheon-greeter-refresh.sh"


def run(root):
    return subprocess.run([str(SCRIPT)], env={**os.environ, "TUNAOS_DM_ROOT": str(root)},
                          capture_output=True, text=True, check=True)


def test_initial_setup_is_wrapped_once_and_restarts_lightdm(tmp_path):
    """Falsification: without the wrapper nothing restarts the greeter and the card stays disabled."""
    binary = tmp_path / "usr/bin/io.elementary.initial-setup"
    binary.parent.mkdir(parents=True)
    binary.write_text("#!/bin/sh\necho real\n")
    binary.chmod(0o755)
    run(tmp_path)
    run(tmp_path)  # idempotent: the real binary is not replaced by the wrapper
    real = tmp_path / "usr/libexec/tunaos/io.elementary.initial-setup"
    assert real.read_text() == "#!/bin/sh\necho real\n"
    wrapper = binary.read_text()
    assert "/usr/libexec/tunaos/io.elementary.initial-setup" in wrapper
    assert "systemctl --no-block restart lightdm.service" in wrapper
    rule = (tmp_path / "usr/share/polkit-1/rules.d/49-tunaos-initial-setup-greeter.rules").read_text()
    assert 'action.lookup("unit") == "lightdm.service"' in rule and 'subject.user == "lightdm"' in rule


def test_no_initial_setup_is_left_alone(tmp_path):
    out = run(tmp_path)
    assert "nothing to do" in out.stdout
    assert not (tmp_path / "usr/share/polkit-1").exists()
