"""Real pointer protocol and shell transport with inert bytes; no guest execution."""
import importlib.util
import json
from pathlib import Path
import stat
import struct
import subprocess
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from lib import gnome_installer_driver as pointer
from lib import visual_console
from lib import xfce_installer_driver as xfce

spec = importlib.util.spec_from_file_location('xfce_transport_fixtures', ROOT / 'tests/test_xfce_candidate_producer.py')
fixtures = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixtures)


def rfb(monkeypatch, on_click, geometry=(1280, 800)):
    """Replace only socket I/O; production click_unix validates and frames input."""
    clicks = []
    class Wire:
        def __init__(self):
            self.data = (b'RFB 003.008\n\x01\x01' + b'\0'*4 +
                         struct.pack('!HH', *geometry) + b'\0'*16 + struct.pack('!I', 0) +
                         struct.pack('!BBHHHHHi', 0, 0, 1, 0, 0, 1, 1, 0))
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def settimeout(self, timeout): assert 0 < timeout <= 5
        def connect(self, path): assert path == 'fixture-vnc'
        def recv(self, count):
            chunk, self.data = self.data[:min(count, 3)], self.data[min(count, 3):]
            return chunk
        def sendall(self, data):
            if data[0] == 5:
                _, button, x, y = struct.unpack('!BBHH', data)
                clicks.append((button, x, y))
                if button == 1:
                    on_click(x, y)
    monkeypatch.setattr(pointer.socket, 'socket', lambda *args: Wire())
    original = Path.lstat
    monkeypatch.setattr(Path, 'lstat', lambda path: SimpleNamespace(st_mode=stat.S_IFSOCK, st_uid=pointer.os.getuid()) if str(path) == 'fixture-vnc' else original(path))
    monkeypatch.setattr(pointer.time, 'sleep', lambda _: None)
    return clicks


@pytest.mark.parametrize('mode', ['plain', 'luks'])
def test_wizard_uses_real_pointer_protocol(tmp_path, monkeypatch, mode):
    wizard = fixtures.Wizard('tuna12345678', mode)
    wizard.width, wizard.height = 1280, 800
    clicks = rfb(monkeypatch, lambda x, y: wizard.pointer('fixture-vnc', x, y, 1280, 800))
    assert xfce.drive(tmp_path, mode, 'fixture-vnc', wizard.capture, wizard.keys, wizard.type,
                      'sha256:'+fixtures.COMMIT, 'b'*32, wizard.user, 'a'*32,
                      screen_factory=lambda _: wizard, sleep=lambda _: None, clock=lambda: 0) == 0
    assert clicks and len(clicks) % 3 == 0
    assert json.loads((tmp_path/'walkthrough-xfce.json').read_text())['completed'] is True


def test_installed_login_uses_real_pointer_protocol(tmp_path, monkeypatch):
    phase = fixtures.PHASE
    monkeypatch.setenv('TUNAOS_XFCE_USER', 'tuna12345678')
    monkeypatch.setenv('TUNAOS_XFCE_PASSWORD', 'a'*32)
    args = SimpleNamespace(action='session', console='fixture-console', monitor='fixture-monitor',
                           vnc='fixture-vnc', phase='cold', mode='plain', directory=tmp_path,
                           boot_log=tmp_path/'boot')
    args.boot_log.write_text('TUNAOS_DESKTOP_CONTRACT_OK desktop=xfce experience=tunaos/xfce\n')
    clicks = rfb(monkeypatch, lambda x, y: None)
    monkeypatch.setattr(phase, 'monitor', lambda *args: None)
    monkeypatch.setattr(phase, 'type_text', lambda *args: None)
    class Console:
        def __init__(self, *args): pass
        def execute(self, *args, **kwargs): return {'pending': True}
        def close(self): pass
    screen = SimpleNamespace(width=1280, height=800, box=lambda _: (10, 20, 30, 40))
    with pytest.raises(ValueError, match='did not complete'):
        phase.collect(args, console_factory=Console, capture=lambda *args: screen, sleep=lambda _: None)
    assert clicks == [(button, 20, 30) for _ in range(2) for button in (0, 1, 0)]


def test_pointer_rejects_capture_server_geometry_mismatch(tmp_path, monkeypatch):
    wizard = fixtures.Wizard('tuna12345678', 'plain')
    wizard.width, wizard.height = 1280, 800
    clicks = rfb(monkeypatch, lambda *args: pytest.fail('must not click'), (1024, 768))
    with pytest.raises(xfce.Unverified, match='geometry differs'):
        xfce.drive(tmp_path, 'plain', 'fixture-vnc', wizard.capture, wizard.keys, wizard.type,
                   'sha256:'+fixtures.COMMIT, 'b'*32, wizard.user, 'a'*32,
                   screen_factory=lambda _: wizard, sleep=lambda _: None, clock=lambda: 0)
    assert not clicks


def test_actual_observer_chunks_roundtrip_through_shell(tmp_path, monkeypatch):
    monkeypatch.setenv('TUNAOS_XFCE_USER', 'tunaabcdefhkmnpr')
    log = tmp_path/'boot'
    log.write_text('TUNAOS_DESKTOP_CONTRACT_OK desktop=xfce experience=tunaos/xfce\n')
    source = fixtures.PHASE.observer_source(SimpleNamespace(boot_log=log, mode='plain', phase='cold'))
    monkeypatch.setattr(visual_console.secrets, 'token_hex', lambda size: 'a'*(size*2))
    expected, _ = visual_console.envelope(source, 'tunaabcdefhkmnpr', 'a'*32, argument=True)
    assert len(expected) > 3000
    lines = []
    console = visual_console.VisualConsole('tunaabcdefhkmnpr', 'fixture-password', lambda _: None,
        lambda: '', lambda: 'BEGIN_'+'a'*32+'\n{}\nEND_'+'a'*32+'\n', sleep=lambda _: None)
    console.type = lines.append
    console.prompt = lambda _: None
    assert console.execute(source) == {}
    assignments = [line for line in lines if line.startswith('TUNA_OBSERVER_DATA=')]
    assert len(assignments) >= 3 and all(len(line) < 1600 for line in assignments)
    # Execute only captured variable assignments; never execute the observer/sudo command.
    result = subprocess.run(['bash', '-c', '\n'.join(assignments)+'\nprintf %s "$TUNA_OBSERVER_DATA"'],
                            capture_output=True, text=True, check=True)
    assert result.stdout == expected
    assert all(visual_console.key_for(char) is not None for line in assignments for char in line)


@pytest.mark.parametrize('geometry', [(1280, 800), (1024, 768), (1920, 1200)])
def test_capture_supplies_measured_png_geometry(tmp_path, monkeypatch, geometry):
    path = tmp_path/'capture.png'
    path.write_bytes(b'\x89PNG\r\n\x1a\n'+struct.pack('!I', 13)+b'IHDR'+struct.pack('!II', *geometry))
    monkeypatch.setattr(xfce.subprocess, 'run', lambda *args, **kwargs: SimpleNamespace(stdout=''))
    screen = xfce.Screen(path)
    assert (screen.width, screen.height) == geometry


@pytest.mark.parametrize('header', [b'', b'not a png',
    b'\x89PNG\r\n\x1a\n'+struct.pack('!I', 13)+b'IHDR'+struct.pack('!II', 4000, 800)])
def test_invalid_capture_fails_before_ocr(tmp_path, monkeypatch, header):
    path = tmp_path/'capture.png'
    path.write_bytes(header)
    monkeypatch.setattr(xfce.subprocess, 'run', lambda *args, **kwargs: pytest.fail('OCR must not run'))
    with pytest.raises(xfce.Unverified):
        xfce.Screen(path)
