"""Measured OCR/control fixtures and ordered GUI transaction tests, no VM claims."""
import importlib.util
import json
from pathlib import Path
import socket
import struct
import threading

import pytest

ROOT = Path(__file__).parents[1]
spec = importlib.util.spec_from_file_location('gnome_driver', ROOT / 'scripts/lib/gnome_installer_driver.py')
driver = importlib.util.module_from_spec(spec)
spec.loader.exec_module(driver)
FIXTURE = json.loads((ROOT / 'tests/fixtures/gnome-installer/run39619460539.json').read_text())


@pytest.mark.parametrize('name,state', [('encryption', 'encryption'), ('recovery', 'recovery'), ('no_disk', 'no-disk')])
def test_captured_ocr_classification(name, state):
    assert driver.classify(FIXTURE[name]['lines']) == state


def test_progress_tour_is_not_done():
    assert driver.classify(['Installation Finished', 'Reboot your machine']) == 'unknown'
    assert driver.classify(['Installing', 'Do not power off the computer.', '2:14 elapsed',
                            'Installation Finished']) == 'progress'
    assert driver.classify(['TunaOS is installed', 'Remove the installation media and restart the computer.',
                            'Restart now']) == 'done'
    assert driver.classify(['Save your recovery key', 'Installing']) == 'recovery'


def test_captured_controls_and_ambiguous_labels():
    data = FIXTURE['encryption']
    screen = object.__new__(driver.Screen)
    screen.rows = data['rows']
    def captured_pixel(x, y):
        for region in data['pixel_regions']:
            dx, dy = x-region['left'], y-region['top']
            if 0 <= dx < region['width'] and 0 <= dy < len(region['rows']):
                return tuple(bytes.fromhex(region['rows'][dy][dx*6:dx*6+6]))
        return data['next_background']
    screen.rgb = captured_pixel
    assert screen.switch('Encrypt this disk') is True
    assert screen.switch('Use hardware-backed encryption') is False
    assert not screen.enabled('Next')
    assert screen.box('Confirm Password') == [367, 484, 493, 495]
    screen.rows = screen.rows + [screen.rows[2]]
    with pytest.raises(driver.Unverified):
        screen.box('Next')
    screen.rgb = lambda x, y: (128, 128, 128)
    with pytest.raises(driver.Unverified):
        screen.switch('Encrypt this disk')


class FakeScreen:
    width, height = 1280, 800
    def __init__(self, state, mode='plain', encrypted=False, tpm=False, valid=True):
        self.state = state
        self.encrypted, self.tpm = encrypted, tpm
        self.lines = ['Welcome to TunaOS', 'Install TunaOS', 'Installs to your internal disk.',
                      'Power Off', 'Strong passphrase'] if state != 'summary' else [
            'Disk', '/dev/vda (64.0 GiB)', 'Encryption',
            'No encryption' if mode == 'plain' else 'Passphrase',
            'Everything on /dev/vda will be erased. This cannot be undone.']
        if not valid:
            self.lines = ['Confirm installation', 'No encryption']
    def box(self, label):
        if self.state == 'welcome':
            boxes = {'Welcome to TunaOS': (505,277,775,304),
                     'Install TunaOS': (395,341,498,355),
                     'Installs to your internal disk.': (395,361,553,374),
                     'Power Off': (367,403,463,418)}
            if label not in boxes:
                raise driver.Unverified('unknown welcome control')
            return boxes[label]
        if self.state == 'summary' and label not in self.lines and label != 'Install':
            raise driver.Unverified('missing summary label')
        return (100, 40, 200, 70) if label == 'Next' else (100, 200, 300, 230)
    def switch(self, label):
        return self.encrypted if label == 'Encrypt this disk' else self.tpm
    def enabled(self, label):
        return True


def execute(tmp_path, screens, mode='plain', digest=driver.BUNDLE_DIGEST):
    events = []
    def capture(index, label):
        events.append(('capture', label))
        return str(tmp_path / f'{index}.png')
    def factory(path):
        if not screens:
            raise driver.Unverified('fixture exhausted')
        return screens.pop(0)
    rc = driver.drive(tmp_path, mode, tmp_path/'vnc.sock', capture,
                      lambda *k: events.append(('key', k)),
                      lambda p: events.append(('type', len(p))), digest,
                      'test-only-passphrase', screen_factory=factory,
                      pointer=lambda *p: events.append(('click', p)), sleep=lambda _: None)
    return rc, json.loads((tmp_path/'walkthrough-gnome.json').read_text()), events


def test_plain_toggle_verified_submit_once_then_observe(tmp_path):
    screens = [FakeScreen('welcome'), FakeScreen('encryption', encrypted=True),
               FakeScreen('encryption'), FakeScreen('summary'), FakeScreen('progress'), FakeScreen('done')]
    rc, result, events = execute(tmp_path, screens)
    assert rc == 0 and result['accepted'] and result['completed']
    assert result['transitions'] == ['welcome', 'encryption', 'summary', 'progress', 'done']
    assert sum(event[0] == 'click' for event in events) == 4
    accepted = next(i for i, e in enumerate(events) if e == ('capture', 'await-progress'))
    assert all(e[0] == 'capture' for e in events[accepted:])


def test_luks_explicit_tpm_off_and_two_fields(tmp_path):
    screens = [FakeScreen('welcome'), FakeScreen('encryption', encrypted=True, tpm=True),
               FakeScreen('encryption', encrypted=True), FakeScreen('encryption', encrypted=True),
               FakeScreen('encryption', encrypted=True), FakeScreen('summary', mode='luks'),
               FakeScreen('progress'), FakeScreen('done')]
    rc, result, events = execute(tmp_path, screens, 'luks')
    assert rc == 0 and result['completed']
    assert sum(e[0] == 'type' for e in events) == 2
    assert sum(e == ('key', ('ctrl-a',)) for e in events) == 2


@pytest.mark.parametrize('bad_state', ['recovery', 'no-disk', 'done', 'progress'])
def test_invalid_early_states_never_accept(tmp_path, bad_state):
    rc, result, events = execute(tmp_path, [FakeScreen('welcome'), FakeScreen(bad_state)])
    assert rc == 1 and not result['accepted'] and not result['completed']


def test_wrong_bundle_no_input_or_capture(tmp_path):
    rc, result, events = execute(tmp_path, [], digest='sha256:'+'0'*64)
    assert rc == 1 and events == []


def test_empty_summary_cannot_submit(tmp_path):
    rc, result, events = execute(tmp_path, [FakeScreen('welcome'), FakeScreen('encryption'),
                                          FakeScreen('summary', valid=False)])
    assert rc == 1 and not result['submitted']


def test_overview_preserves_before_after_and_fails(tmp_path):
    rc, result, events = execute(tmp_path, [FakeScreen('overview')])
    assert rc == 1 and result['overview_after_escape'] == '1.png'
    assert events == [('capture', 'await-welcome'), ('key', ('esc',)),
                      ('capture', 'overview-after-escape')]


def test_unix_rfb_pointer_and_geometry(tmp_path):
    path = tmp_path/'vnc.sock'
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(path)); server.listen(1)
    received = []
    def serve():
        with server.accept()[0] as conn:
            conn.sendall(b'RFB 003.008\n')
            assert driver._read(conn, 12) == b'RFB 003.008\n'
            conn.sendall(b'\x01\x01')
            assert driver._read(conn, 1) == b'\x01'
            conn.sendall(b'\0'*4)
            assert driver._read(conn, 1) == b'\x01'
            conn.sendall(struct.pack('!HH',1280,800)+b'\0'*16+struct.pack('!I',4)+b'test')
            received.append(driver._read(conn,18))
    thread = threading.Thread(target=serve); thread.start()
    driver.click_unix(path, 420, 490, 1280, 800)
    thread.join(timeout=5); server.close()
    assert not thread.is_alive()
    assert received == [b''.join(struct.pack('!BBHH',5,button,420,490) for button in (0,1,0))]
    with pytest.raises(driver.Unverified):
        driver.click_unix(path, -1, 490, 1280,800)


def test_strict_harness_capacity_and_unix_pointer():
    text = (ROOT/'scripts/iso-e2e.sh').read_text()
    strict = text.split('run_strict_gui_install() {',1)[1].split('\n}',1)[0]
    assert 'qemu-img create -f qcow2 "$disk" 64G' in strict
    assert 'df -h "$OUTPUT_DIR"' in strict
    assert '--vnc=${OUTPUT_DIR}/vnc.sock' in strict
    assert 'QEMU_NEEDS_VNC_SURFACE:-0}" == "1" || "$STRICT_OFFLINE_GUI" -eq 1' in text
    assert 'QEMU_GPU_ARGS+=(-device qemu-xhci -device usb-tablet)' in text
    walkthrough = (ROOT/'scripts/installer-walkthrough.py').read_text()
    assert 'TCP-LISTEN:{vnc_port},bind=127.0.0.1,reuseaddr,fork' in walkthrough
    assert 'if not (mode_explicit and flavor == "gnome") and vnc_capture(png):' in walkthrough


def test_postaccepted_overview_never_sends_input(tmp_path):
    rc, result, events = execute(tmp_path, [FakeScreen('welcome'), FakeScreen('encryption'),
                                          FakeScreen('summary'), FakeScreen('progress'), FakeScreen('overview')])
    assert rc == 1 and result['accepted'] and not result['completed']
    assert not any(e[0] == 'key' for e in events)


def test_install_failure_is_terminal():
    assert driver.classify(['Installation failed', 'View logs']) == 'failed'
    assert driver.classify(['Install Location']) == 'disk'


def test_toggle_that_does_not_change_fails(tmp_path):
    rc, result, events = execute(tmp_path, [FakeScreen('welcome'),
        FakeScreen('encryption', encrypted=True), FakeScreen('encryption', encrypted=True)])
    assert rc == 1 and not result['submitted']


def test_disabled_next_after_passwords_fails(tmp_path):
    final = FakeScreen('encryption', encrypted=True)
    final.enabled = lambda label: False
    rc, result, events = execute(tmp_path, [FakeScreen('welcome'),
        FakeScreen('encryption', encrypted=True), FakeScreen('encryption', encrypted=True), final], 'luks')
    assert rc == 1 and not result['submitted']


def test_fair_strength_full_copy_passes(tmp_path):
    final = FakeScreen('encryption', encrypted=True)
    final.lines = ['Fair — consider making it longer']
    rc, result, events = execute(tmp_path, [FakeScreen('welcome'),
        FakeScreen('encryption', encrypted=True), FakeScreen('encryption', encrypted=True), final,
        FakeScreen('summary', mode='luks'), FakeScreen('progress'), FakeScreen('done')], 'luks')
    assert rc == 0


def test_rejected_submit_is_never_accepted_or_retried(tmp_path):
    rc, result, events = execute(tmp_path, [FakeScreen('welcome'), FakeScreen('encryption'),
        FakeScreen('summary')] + [FakeScreen('summary') for _ in range(12)])
    assert rc == 1 and result['submitted'] and not result['accepted']
    assert sum(e[0] == 'click' for e in events) == 3


@pytest.mark.parametrize('case', ['good', 'geometry', 'security', 'protocol'])
def test_rfb_protocol_without_socket_creation(monkeypatch, tmp_path, case):
    """Exercise client framing separately; does not substitute for the real socket test."""
    import stat
    from types import SimpleNamespace
    payload = bytearray(b'RFB 003.007\n' if case == 'protocol' else b'RFB 003.008\n')
    payload.extend(b'\x01\x02' if case == 'security' else b'\x01\x01')
    payload.extend(b'\0'*4)
    payload.extend(struct.pack('!HH',1024 if case == 'geometry' else 1280,800)+b'\0'*16+struct.pack('!I',4)+b'test')
    sent = []
    class Connection:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def settimeout(self, timeout): assert timeout == 5
        def connect(self, path): assert path == str(tmp_path/'vnc.sock')
        def recv(self, count):
            chunk = bytes(payload[:min(count,3)])
            del payload[:len(chunk)]
            return chunk
        def sendall(self, data): sent.append(data)
    def constructor(family, kind):
        assert family == socket.AF_UNIX and kind == socket.SOCK_STREAM
        return Connection()
    monkeypatch.setattr(driver.socket, 'socket', constructor)
    monkeypatch.setattr(driver.Path, 'lstat', lambda _: SimpleNamespace(st_mode=stat.S_IFSOCK, st_uid=driver.os.getuid()))
    monkeypatch.setattr(driver.time, 'sleep', lambda _: None)
    if case != 'good':
        with pytest.raises(driver.Unverified):
            driver.click_unix(tmp_path/'vnc.sock',420,490,1280,800)
        assert not any(data[:1] == b'\x05' for data in sent)
    else:
        driver.click_unix(tmp_path/'vnc.sock',420,490,1280,800)
        assert sent[-3:] == [struct.pack('!BBHH',5,b,420,490) for b in (0,1,0)]


@pytest.mark.parametrize('mode', ['plain', 'luks'])
def test_real_welcome_action_is_not_header_next(mode):
    data = json.loads((ROOT/'tests/fixtures/gnome-installer/run39647418167.json').read_text())[mode]
    screen = object.__new__(driver.Screen)
    screen.width, screen.height = data['width'], data['height']
    screen.rows = data['rows']; screen.lines = [row[0] for row in screen.rows]
    assert driver.classify(screen.lines) == 'welcome'
    assert driver.welcome_action(screen) == 'Install Skipjack'
    with pytest.raises(driver.Unverified):
        screen.box('Next')


@pytest.mark.parametrize('bad', ['duplicate', 'wrong-product', 'missing-subtitle', 'thumbnail', 'misaligned', 'header-next-only'])
def test_welcome_action_fails_closed_for_ambiguous_or_wrong_geometry(bad):
    data = json.loads((ROOT/'tests/fixtures/gnome-installer/run39647418167.json').read_text())['plain']
    screen = object.__new__(driver.Screen)
    screen.width, screen.height = data['width'], data['height']
    screen.rows = data['rows']
    action = next(row for row in screen.rows if row[0] == 'Install Skipjack')
    if bad == 'duplicate': screen.rows.append(action)
    elif bad == 'wrong-product': action[0] = 'Install Albacore'
    elif bad == 'missing-subtitle': screen.rows = [row for row in screen.rows if row[0] != 'Installs to your internal disk.']
    elif bad == 'thumbnail':
        screen.rows = [(text, [coordinate//2 for coordinate in box]) for text, box in screen.rows]
    elif bad == 'misaligned': action[1][0] += 250
    else: action[0] = 'Next'; action[1] = [960,45,1000,60]
    screen.lines = [row[0] for row in screen.rows]
    with pytest.raises(driver.Unverified): driver.welcome_action(screen)
