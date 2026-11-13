"""niri's live session must load a config that launches the installer.

niri reads ~/.config/niri/config.kdl, then /etc/niri/config.kdl, and when
neither exists it WRITES ITS OWN built-in default into the home directory.
It never reads /usr/share/niri/config.kdl. Fedora's niri package ships an
/etc/skel copy, so liveuser had a config and appending the installer line to
it worked. Arch's does not (marlin:niri): the adapter appended to
/usr/share/niri/config.kdl only, niri generated its default, and marlin-niri
run 43367881313 showed waybar over an empty desktop in 41 frames.

Falsification: behavioural. Delete the "seed liveuser's config" block from
live-iso/common/src/desktop-niri.sh and test_a_missing_skel_config_is_seeded...
fails: the user config does not exist after the adapter runs.
"""
import os
import stat
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ADAPTER = ROOT / 'live-iso/common/src/desktop-niri.sh'
LINE = 'spawn-at-startup "flatpak" "run" "org.tunaos.InstallerNiri"'
SHIPPED = 'spawn-at-startup "swaybg"\nspawn-at-startup "waybar"\n'


def run_adapter(tmp, skel_config=None):
    """Run the real adapter with its absolute paths moved under tmp."""
    for rel in ('etc', 'usr/share/niri', 'usr/lib/systemd/system', 'home/liveuser', 'bin'):
        (tmp / rel).mkdir(parents=True, exist_ok=True)
    (tmp / 'usr/share/niri/config.kdl').write_text(SHIPPED)
    if skel_config is not None:
        user = tmp / 'home/liveuser/.config/niri'
        user.mkdir(parents=True)
        (user / 'config.kdl').write_text(skel_config)
    stubs = {
        'getent': f'echo "liveuser:x:1000:1000::{tmp}/home/liveuser:/bin/bash"',
        'systemctl': 'exit 0',
        # The container build runs as root; here only the ownership flags go.
        'install': 'args=(); skip=0; for a in "$@"; do if [ $skip = 1 ]; then skip=0; continue; fi; '
                   'case "$a" in -o|-g) skip=1;; *) args+=("$a");; esac; done; exec /usr/bin/install "${args[@]}"',
    }
    for name, body in stubs.items():
        path = tmp / 'bin' / name
        path.write_text('#!/bin/sh\n' + body + '\n' if name != 'install' else '#!/bin/bash\n' + body + '\n')
        path.chmod(path.stat().st_mode | stat.S_IXUSR)
    text = ADAPTER.read_text()
    for prefix in ('/etc/', '/usr/share/niri', '/usr/lib/systemd'):
        text = text.replace(prefix, f'{tmp}{prefix}')
    text = text.replace('/var/home/liveuser', f'{tmp}/home/liveuser')
    script = tmp / 'adapter.sh'
    script.write_text(text)
    env = dict(os.environ, PATH=f'{tmp}/bin:{os.environ["PATH"]}')
    return subprocess.run(['bash', str(script)], env=env, capture_output=True, text=True)


def test_a_missing_skel_config_is_seeded_so_niri_loads_the_installer_line(tmp_path):
    result = run_adapter(tmp_path)
    assert result.returncode == 0, result.stderr
    user = (tmp_path / 'home/liveuser/.config/niri/config.kdl').read_text()
    assert user.startswith(SHIPPED), 'seeded from the image default, not an empty file'
    assert user.count(LINE) == 1
    assert (tmp_path / 'usr/share/niri/config.kdl').read_text().count(LINE) == 1


def test_a_skel_config_is_kept_and_gets_exactly_one_installer_line(tmp_path):
    result = run_adapter(tmp_path, skel_config='// skel\n')
    assert result.returncode == 0, result.stderr
    user = (tmp_path / 'home/liveuser/.config/niri/config.kdl').read_text()
    assert user.startswith('// skel\n') and SHIPPED not in user
    assert user.count(LINE) == 1
