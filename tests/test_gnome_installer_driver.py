"""Measured OCR/control fixtures and ordered GUI transaction tests, no VM claims."""
import importlib.util
import json
import os
import socket
import struct
import subprocess
import textwrap
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
spec = importlib.util.spec_from_file_location('gnome_driver', ROOT / 'scripts/lib/gnome_installer_driver.py')
driver = importlib.util.module_from_spec(spec)
spec.loader.exec_module(driver)
FIXTURE = json.loads((ROOT / 'tests/fixtures/gnome-installer/run39619460539.json').read_text())
SOURCE_REF = 'tuna-os/skipjack:gnome'


@pytest.mark.parametrize('name,state', [('encryption', 'encryption'), ('recovery', 'recovery'), ('no_disk', 'no-disk')])
def test_captured_ocr_classification(name, state):
    assert driver.classify(FIXTURE[name]['lines']) == state


def test_progress_tour_is_not_done():
    assert driver.classify(['Installation Finished', 'Reboot your machine']) == 'unknown'
    assert driver.classify(['Finished!', 'Power Off', 'Restart']) == 'unknown'
    assert driver.classify(['Installing', 'Do not power off the computer.', '2:14 elapsed',
                            'Installation Finished']) == 'unknown'  # Text alone cannot prove progress.
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
    def __init__(self, state, mode='plain', encrypted=False, tpm=False, valid=True, product='TunaOS'):
        self.state = state
        self.mode, self.valid = mode, valid
        self.encrypted, self.tpm = encrypted, tpm
        self.product = product
        self.progress_markers = [f'Installing {product}...', 'Do not power off the computer.', '0:00 elapsed', '1%']
        self.lines = [f'Welcome to {product}', f'Install {product}', 'Installs to your internal disk.',
                      'Power Off', 'Strong passphrase'] if state != 'summary' else [
            'Confirm installation', 'Summary', 'Target disk', '/dev/vda (64 GiB)',
            'Filesystem', 'XFS', 'Encryption',
            'No encryption' if mode == 'plain' else 'Passphrase', 'Image', SOURCE_REF,
            'Everything on /dev/vda will be erased. This cannot be undone.']
        if not valid:
            self.lines = ['Confirm installation', 'No encryption']
    def box(self, label):
        if self.state == 'welcome':
            boxes = {f'Welcome to {self.product}': (505,277,775,304),
                     f'Install {self.product}': (395,341,498,355),
                     'Installs to your internal disk.': (395,361,553,374),
                     'Power Off': (367,403,463,418)}
            if label not in boxes:
                raise driver.Unverified('unknown welcome control')
            return boxes[label]
        if self.state == 'summary' and label not in self.lines and label != 'Install':
            raise driver.Unverified('missing summary label')
        return (100, 40, 200, 70) if label == 'Next' else (100, 200, 300, 230)
    def summary_cards(self):
        if not self.valid:
            raise driver.Unverified('missing summary cards')
        return measured_cards(self.mode)
    def summary_warning(self):
        return captured_rows(SUMMARY['warning']['words'])[1]
    def switch(self, label):
        return self.encrypted if label == 'Encrypt this disk' else self.tpm
    def enabled(self, label):
        return True


def execute(tmp_path, screens, mode='plain', digest=driver.BUNDLE_DIGEST,
            pointer_error_at=None, capture_error_at=None, source_ref=SOURCE_REF):
    events = []
    def capture(index, label, *, directory=None):
        path = Path(directory or tmp_path) / f'{index}.png'
        events.append(('capture', label))
        if label == capture_error_at:
            raise FileNotFoundError('monitor socket disappeared')
        path.write_bytes(b'inert captured frame')
        return str(path)
    def factory(path):
        if not screens:
            raise driver.Unverified('fixture exhausted')
        return screens.pop(0)
    def pointer(*args):
        events.append(('click', args))
        if sum(event[0] == 'click' for event in events) == pointer_error_at:
            raise socket.timeout('simulated response missing after release')
        return True
    rc = driver.drive(tmp_path, mode, tmp_path/'vnc.sock', capture,
                      lambda *k: events.append(('key', k)),
                      lambda p: events.append(('type', len(p))), digest,
                      'test-only-passphrase', source_ref, screen_factory=factory,
                      pointer=pointer, sleep=lambda _: None)
    return rc, json.loads((tmp_path/'walkthrough-gnome.json').read_text()), events


def test_plain_toggle_verified_submit_once_then_observe(tmp_path):
    screens = [FakeScreen('welcome'), FakeScreen('encryption', encrypted=True),
               FakeScreen('encryption'), FakeScreen('summary'), FakeScreen('progress'), FakeScreen('done')]
    rc, result, events = execute(tmp_path, screens)
    assert rc == 0 and result['accepted'] and result['completed']
    assert result['driver'] == 'gnome-23e47c51'
    assert result['installer_digest'] == 'sha256:ff28c254d0f0c3fc303cdcd2d7cae1632a55e6f92f1f887c4c6f00559d82417b'
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


@pytest.mark.parametrize('after_acceptance', [False, True])
def test_monitor_disappearance_reports_failure_without_completion(tmp_path, after_acceptance):
    screens = [FakeScreen('welcome'), FakeScreen('encryption'),
               FakeScreen('summary'), FakeScreen('progress')]
    stage = 'await-completion' if after_acceptance else 'await-progress'
    rc, result, events = execute(tmp_path, screens, capture_error_at=stage)
    assert rc == 1 and result['submitted'] and not result['completed']
    assert result['accepted'] is after_acceptance
    assert 'monitor socket disappeared' in result['error']
    submitted = next(i for i, e in enumerate(events) if e == ('capture', 'await-progress'))
    assert all(e[0] == 'capture' for e in events[submitted:])


@pytest.mark.parametrize('fail_entry', [False, True])
def test_secret_entry_frames_and_ocr_are_not_retained(tmp_path, fail_entry):
    screens = [FakeScreen('welcome'), FakeScreen('encryption', encrypted=True),
               FakeScreen('encryption', encrypted=True),
               FakeScreen('encryption', encrypted=True),
               FakeScreen('summary', mode='luks'), FakeScreen('progress'), FakeScreen('done')]
    private = []
    def capture(index, label, *, directory=None):
        path = Path(directory or tmp_path) / f'{index}.png'
        path.write_bytes(b'private password entry' if directory else b'public frame')
        if directory:
            private.append(path)
        return str(path)
    def factory(path):
        screen = screens.pop(0)
        if Path(path) in private:
            screen.lines.append('test-only-passphrase')
            if fail_entry:
                raise driver.Unverified('password entry observation refused')
        return screen
    rc = driver.drive(tmp_path, 'luks', tmp_path/'vnc.sock', capture, lambda *k: None,
                      lambda p: None, driver.BUNDLE_DIGEST, 'test-only-passphrase', SOURCE_REF,
                      screen_factory=factory, pointer=lambda *a: True, sleep=lambda _: None)
    report = (tmp_path/'walkthrough-gnome.json').read_text()
    assert rc == (1 if fail_entry else 0)
    assert private and all(not path.exists() and not path.parent.exists() for path in private)
    assert 'test-only-passphrase' not in report
    assert all(b'private password entry' not in path.read_bytes()
               for path in tmp_path.glob('*.png'))
    assert json.loads(report)['completed'] is not fail_entry


@pytest.mark.parametrize('bad_state', ['recovery', 'no-disk', 'done', 'progress'])
def test_invalid_early_states_never_accept(tmp_path, bad_state):
    rc, result, events = execute(tmp_path, [FakeScreen('welcome'), FakeScreen(bad_state)])
    assert rc == 1 and not result['accepted'] and not result['completed']


@pytest.mark.parametrize('digest', [
    'sha256:'+'0'*64,
    'sha256:04252eaf80ee5675aa37bdb482847c77310efbee058dc63ba161a1d5991f9823',
])
def test_wrong_bundle_no_input_or_capture(tmp_path, digest):
    rc, result, events = execute(tmp_path, [], digest=digest)
    assert rc == 1 and events == []
    assert not result['submitted'] and not result['accepted'] and not result['completed']
    assert result['installer_digest'] == digest


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
    """Real UNIX transport: no close until a fragmented response prefix arrives."""
    from concurrent.futures import ThreadPoolExecutor
    import select
    path = tmp_path/'vnc.sock'
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.settimeout(5)
    server.bind(str(path)); server.listen(1)
    request_seen, allow_reply = threading.Event(), threading.Event()
    received, peers = [], []
    def serve():
        with server.accept()[0] as conn:
            peers.append(conn)
            conn.settimeout(5)
            conn.sendall(b'RFB 003.008\n')
            assert driver._read(conn, 12) == b'RFB 003.008\n'
            conn.sendall(b'\x01\x01')
            assert driver._read(conn, 1) == b'\x01'
            conn.sendall(b'\0'*4)
            assert driver._read(conn, 1) == b'\x01'
            conn.sendall(struct.pack('!HH',1280,800)+b'\0'*16+struct.pack('!I',4)+b'test')
            received.extend([driver._read(conn,8), driver._read(conn,18),
                             driver._read(conn,10)])
            request_seen.set()
            assert allow_reply.wait(3)
            reply = struct.pack('!BBHHHHHi',0,0,1,0,0,16,1,0)
            for chunk in (reply[:2], reply[2:7], reply[7:]):
                conn.sendall(chunk)
            assert conn.recv(1) == b''
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            server_result = pool.submit(serve)
            client_result = pool.submit(driver.click_unix, path,420,490,1280,800)
            try:
                assert request_seen.wait(3)
                assert not client_result.done()
                poll = select.poll()
                poll.register(peers[0], select.POLLIN | select.POLLHUP)
                assert not poll.poll(0)
            finally:
                allow_reply.set()
            assert client_result.result(timeout=5) is True
            server_result.result(timeout=5)
    finally:
        allow_reply.set()
        server.close()
    assert received == [struct.pack('!BBHi',2,0,1,0),
                        b''.join(struct.pack('!BBHH',5,b,420,490) for b in (0,1,0)),
                        struct.pack('!BBHHHH',3,0,0,0,1,1)]
    with pytest.raises(driver.Unverified):
        driver.click_unix(path,-1,490,1280,800)



@pytest.mark.parametrize('state', ['overview', 'failed', 'recovery', 'no-disk', 'summary'])
def test_postaccepted_invalid_state_never_sends_input(tmp_path, state):
    rc, result, events = execute(tmp_path, [FakeScreen('welcome'), FakeScreen('encryption'),
                                          FakeScreen('summary'), FakeScreen('progress'), FakeScreen(state)])
    assert rc == 1 and result['accepted'] and not result['completed']
    accepted = events.index(('capture', 'await-progress'))
    assert all(event[0] == 'capture' for event in events[accepted:])
    assert sum(event[0] == 'click' for event in events) == 3


@pytest.mark.parametrize('final,completed', [('done', True), (None, False)])
def test_postaccepted_progress_and_unknown_remain_observe_only(tmp_path, final, completed):
    waiting = [FakeScreen('unknown'), FakeScreen('progress')] * (2 if completed else 40)
    if final:
        waiting.append(FakeScreen(final))
    rc, result, events = execute(tmp_path, [FakeScreen('welcome'), FakeScreen('encryption'),
                                          FakeScreen('summary'), FakeScreen('progress'), *waiting])
    assert rc == (0 if completed else 1)
    assert result['submitted'] and result['accepted'] and result['completed'] is completed
    if not completed:
        assert 'observation bound' in result['error']
    accepted = events.index(('capture', 'await-progress'))
    assert all(event[0] == 'capture' for event in events[accepted:])
    assert sum(event[0] == 'click' for event in events) == 3


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


def test_done_without_accepted_progress_never_completes(tmp_path):
    rc, result, events = execute(tmp_path, [FakeScreen('welcome'), FakeScreen('encryption'),
                                          FakeScreen('summary'), FakeScreen('done')])
    assert rc == 1 and result['submitted'] and not result['accepted'] and not result['completed']
    submitted = events.index(('capture', 'await-progress'))
    assert all(event[0] == 'capture' for event in events[submitted:])


def test_disabled_install_never_submits(tmp_path):
    summary = FakeScreen('summary')
    summary.enabled = lambda label: False
    rc, result, events = execute(tmp_path, [FakeScreen('welcome'), FakeScreen('encryption'), summary])
    assert rc == 1 and not result['submit_attempted'] and not result['submitted']
    assert not result['accepted'] and not result['completed']
    assert sum(event[0] == 'click' for event in events) == 2


@pytest.mark.parametrize('case', ['good', 'geometry', 'security', 'protocol', 'security-result', 'name', 'truncated-init'])
def test_rfb_protocol_without_socket_creation(monkeypatch, tmp_path, case):
    """Exercise client framing separately; does not substitute for the real socket test."""
    import stat
    from types import SimpleNamespace
    payload = bytearray(b'RFB 003.007\n' if case == 'protocol' else b'RFB 003.008\n')
    payload.extend(b'\x01\x02' if case == 'security' else b'\x01\x01')
    payload.extend(b'\0\0\0\1' if case == 'security-result' else b'\0'*4)
    payload.extend(struct.pack('!HH',1024 if case == 'geometry' else 1280,800)+b'\0'*16+struct.pack('!I',4097 if case == 'name' else 4)+b'test')
    if case == 'truncated-init':
        payload = payload[:20]
    payload.extend(struct.pack('!BBHHHHHi', 0,0,1,0,0,16,1,0))
    sent = []
    class Connection:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def settimeout(self, timeout): assert 0 < timeout <= 5
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
        raw = struct.pack('!BBHi', 2, 0, 1, 0)
        pointer_packets = [struct.pack('!BBHH',5,b,420,490) for b in (0,1,0)]
        assert sent == [b'RFB 003.008\n', b'\x01', b'\x01', raw, *pointer_packets,
                        struct.pack('!BBHHHH',3,0,0,0,1,1)]

        def qemu82_events(packets):
            # Minimal source-path model, not guest input proof:
            # qemu/qemu v8.2.2 ui/vnc.c, set_encodings()/pointer_event().
            # A fresh client starts relative, with last_x == -1.
            absolute, last = False, None
            events = []
            for packet in packets:
                if packet == raw:
                    # Strict harness supplies an already-active USB tablet.
                    absolute = True
                    continue
                kind, buttons, x, y = struct.unpack('!BBHH', packet)
                assert kind == 5
                if absolute:
                    events.append(('absolute', buttons, x, y))
                elif last is not None:
                    events.append(('relative', buttons, x-last[0], y-last[1]))
                last = (x, y)
            return events

        assert qemu82_events(sent[3:-1]) == [
            ('absolute', b, 420, 490) for b in (0,1,0)]
        # Negative control: removing negotiation yields only zero motion.
        assert qemu82_events(pointer_packets) == [
            ('relative', b, 0, 0) for b in (1,0)]


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


def test_welcome_action_accepts_a_label_without_descenders():
    # Run 42157996633 (marlin:gnome, measured): "Install Marlin" is 11px tall.
    screen = object.__new__(driver.Screen)
    screen.width, screen.height = 1280, 800
    screen.rows = [('Welcome to Marlin', [518, 322, 760, 342]),
                   ('Install Marlin', [395, 385, 482, 396]),
                   ('Installs to your internal disk.', [395, 405, 553, 418]),
                   ('Power Off', [367, 447, 463, 462])]
    screen.lines = [row[0] for row in screen.rows]
    assert driver.welcome_action(screen) == 'Install Marlin'
    screen.rows[1] = ('Install Marlin', [395, 385, 482, 394])  # 9px: not a label
    with pytest.raises(driver.Unverified):
        driver.welcome_action(screen)


def test_welcome_action_accepts_a_description_read_without_its_first_word():
    # Run 42233316474 (grouper:gnome, measured): "Installs" is dropped from the
    # small grey row and the power row is read as "() Power off".
    screen = object.__new__(driver.Screen)
    screen.width, screen.height = 1280, 800
    screen.rows = [('Welcome to Grouper', (542, 320, 802, 346)),
                   ('Install Grouper', (428, 383, 524, 398)),
                   ('to your internal disk.', (469, 403, 577, 415)),
                   ('() Power off', (399, 443, 495, 469))]
    screen.lines = [row[0] for row in screen.rows]
    assert driver.welcome_action(screen) == 'Install Grouper'
    # The missing word must account for the gap: a tail far from the action
    # is some other row, not the description.
    screen.rows[2] = ('to your internal disk.', (640, 403, 748, 415))
    with pytest.raises(driver.Unverified):
        driver.welcome_action(screen)

def test_welcome_action_accepts_a_description_with_its_first_word_garbled():
    """albacore:gnome-hwe, iso-builder run 43568689119: 'Installs' read as '~', the full stop as a
    comma, and the Welcome page painted correctly. Falsification: without the tolerance the leg
    fails 'expected one exact control label: Installs to your internal disk.; got 0'."""
    screen = object.__new__(driver.Screen)
    screen.width, screen.height = 1280, 800
    screen.rows = [('Welcome to Albacore', (500, 320, 778, 346)),
                   ('Install Albacore', (394, 383, 503, 398)),
                   ('~ to your internal disk,', (394, 403, 557, 417)),
                   ('Power Off', (394, 447, 463, 462))]
    screen.lines = [row[0] for row in screen.rows]
    assert driver.welcome_action(screen) == 'Install Albacore'
    # A garbled row far from the action is some other row.
    screen.rows[2] = ('~ to your internal disk,', (700, 403, 860, 417))
    with pytest.raises(driver.Unverified):
        driver.welcome_action(screen)


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


def fragmented_welcome():
    data = json.loads((ROOT/'tests/fixtures/gnome-installer/run41255653588-welcome.json').read_text())
    screen = object.__new__(driver.Screen)
    screen.width, screen.height = data['width'], data['height']
    screen.rows = data['rows']
    screen.lines = [row[0] for row in screen.rows]
    screen.path = Path('known-pre-input-welcome.png')
    return screen, data


def test_actual_fragmented_welcome_crosschecks_complete_action_with_original_crop(monkeypatch):
    screen, data = fragmented_welcome()
    calls = []
    def run(command, **options):
        calls.append(command)
        return type('Result', (), {'stdout': data['cropTsv']})()
    monkeypatch.setattr(driver.subprocess, 'run', run)
    assert driver.welcome_action(screen) == 'Install Skipjack'
    assert calls[0][:5] == ['convert', str(screen.path), '-crop', '670x36+305+314', '+repage']
    assert calls[1][0] == 'tesseract' and calls[1][3:] == ['--psm', '7', 'tsv']
    assert len(calls) == 2
    assert not any(flag in command for command in calls for flag in ('-resize', '-threshold', '-colorspace', '-negate'))


@pytest.mark.parametrize('bad', ['wrong-action-product', 'wrong-crop-product', 'duplicate-action',
                                 'duplicate-heading', 'missing-fragment', 'overlapping-fragments',
                                 'uncertain-crop', 'multiple-crop-rows', 'thumbnail'])
def test_fragmented_welcome_keeps_product_ambiguity_and_geometry_refusals(monkeypatch, bad):
    screen, data = fragmented_welcome()
    tsv = data['cropTsv']
    if bad == 'wrong-action-product':
        screen.rows = [(text.replace('Install Skipjack', 'Install Albacore'), box) for text, box in screen.rows]
    elif bad == 'wrong-crop-product':
        tsv = tsv.replace('Skipjack', 'Albacore')
    elif bad == 'duplicate-action':
        screen.rows.append(next(row for row in screen.rows if row[0] == 'Install Skipjack'))
    elif bad == 'duplicate-heading':
        screen.rows.append(next(row for row in screen.rows if row[0].startswith('Welcome to ')))
    elif bad == 'missing-fragment':
        screen.rows = [row for row in screen.rows if row[0] != 'pjack']
    elif bad == 'overlapping-fragments':
        screen.rows.append(next(row for row in screen.rows if row[0] == 'pjack'))
    elif bad == 'uncertain-crop':
        rows = tsv.splitlines()
        word = rows[-1].split('\t')
        word[-2] = '20'
        rows[-1] = '\t'.join(word)
        tsv = '\n'.join(rows) + '\n'
    elif bad == 'multiple-crop-rows':
        word = tsv.splitlines()[-1].split('\t')
        word[4] = '2'
        tsv += '\t'.join(word) + '\n'
    else:
        screen.rows = [(text, [coordinate//2 for coordinate in box]) for text, box in screen.rows]
    screen.lines = [row[0] for row in screen.rows]
    monkeypatch.setattr(driver.subprocess, 'run', lambda *args, **kwargs: type('Result', (), {'stdout': tsv})())
    with pytest.raises(driver.Unverified):
        driver.welcome_action(screen)


def test_qemu_hup_priority_model_discards_readable_release():
    """Linux socket behavior plus QEMU 8.2.2 dispatch model, not a QEMU VM."""
    import select
    sender, receiver = socket.socketpair()
    release = struct.pack('!BBHH',5,0,420,490)
    try:
        sender.sendall(release)
        sender.close()
        poll = select.poll()
        poll.register(receiver, select.POLLIN | select.POLLHUP)
        flags = poll.poll(1000)[0][1]
        assert flags & select.POLLIN and flags & select.POLLHUP
        # ui/vnc.c vnc_client_io checks HUP/ERR before reading.
        consumed = b'' if flags & (select.POLLHUP | select.POLLERR) else receiver.recv(6)
        assert consumed == b''
        assert receiver.recv(6, socket.MSG_PEEK) == release
    finally:
        sender.close()
        receiver.close()


class BarrierSocket:
    def __init__(self, reply):
        self.reply = bytearray(reply)
        self.sent = []
    def settimeout(self, timeout):
        assert 0 < timeout <= 5
    def sendall(self, packet):
        self.sent.append(packet)
    def recv(self, count):
        part = bytes(self.reply[:min(count, 2)])
        del self.reply[:len(part)]
        return part


@pytest.mark.parametrize('size', range(16))
def test_release_barrier_truncated_response_fails(size):
    response = struct.pack('!BBHHHHHi',0,0,1,0,0,16,1,0)
    with pytest.raises(driver.Unverified):
        driver._pointer_barrier(BarrierSocket(response[:size]),1280,800,
                                driver.time.monotonic()+5)


@pytest.mark.parametrize('response', [
    struct.pack('!BBH',2,0,1),
    struct.pack('!BBH',0,0,0),
    struct.pack('!BBH',0,0,4097),
    struct.pack('!BBHHHHHi',0,0,1,0,0,16,1,1),
    struct.pack('!BBHHHHHi',0,0,1,1279,0,16,1,0),
    struct.pack('!BBHHHHHi',0,0,1,0,800,16,1,0),
    struct.pack('!BBHHHHHi',0,0,1,0,0,0,1,0),
])
def test_release_barrier_rejects_unrelated_or_invalid_response(response):
    with pytest.raises(driver.Unverified):
        driver._pointer_barrier(BarrierSocket(response),1280,800,
                                driver.time.monotonic()+5)


def test_release_barrier_timeout_is_not_acknowledgement():
    class TimeoutSocket(BarrierSocket):
        def recv(self, count):
            raise socket.timeout('no reply')
    with pytest.raises(socket.timeout):
        driver._pointer_barrier(TimeoutSocket(b''),1280,800,
                                driver.time.monotonic()+5)


def test_transaction_deadline_bounds_trickled_fragments(monkeypatch):
    ticks = iter(range(20))
    monkeypatch.setattr(driver.time, 'monotonic', lambda: next(ticks))
    with pytest.raises(driver.Unverified, match='deadline'):
        driver._read(BarrierSocket(b'x'*32),32,deadline=5)


@pytest.mark.parametrize('mode', ['plain','luks'])
def test_retained_welcome_does_not_retry_or_submit(tmp_path, mode):
    rc, result, events = execute(tmp_path, [FakeScreen('welcome') for _ in range(13)], mode)
    assert rc == 1
    assert sum(e[0] == 'click' for e in events) == 1
    assert result['transitions'] == ['welcome']
    assert not result['submit_attempted'] and not result['submitted']
    assert not result['accepted'] and not result['completed']
    assert result['clicks'] == [{
        'action': 'welcome-install', 'state': 'welcome',
        'box': [395,341,498,355], 'point': [446,348], 'frame': [1280,800],
        'transport': 'server-response',
    }]


def test_final_submit_response_timeout_records_uncertainty_without_retry(tmp_path):
    rc, result, events = execute(tmp_path, [FakeScreen('welcome'),
        FakeScreen('encryption'), FakeScreen('summary')], pointer_error_at=3)
    assert rc == 1 and result['submit_attempted']
    assert not result['submitted'] and not result['accepted'] and not result['completed']
    assert result['clicks'][-1]['action'] == 'submit-install'
    assert result['clicks'][-1]['transport'] == 'uncertain'
    assert sum(e[0] == 'click' for e in events) == 3
    assert events[-1][0] == 'click'


@pytest.mark.parametrize('kind', ['file','symlink','wrong-owner'])
def test_unowned_or_non_socket_endpoint_rejected_before_connect(monkeypatch, tmp_path, kind):
    import stat
    from types import SimpleNamespace
    path = tmp_path/'vnc.sock'
    if kind == 'file':
        path.write_text('not a socket')
    elif kind == 'symlink':
        path.symlink_to(tmp_path/'missing')
    else:
        monkeypatch.setattr(driver.Path, 'lstat', lambda _: SimpleNamespace(
            st_mode=stat.S_IFSOCK, st_uid=driver.os.getuid()+1))
    def forbidden(*args):
        raise AssertionError('socket creation must not occur')
    monkeypatch.setattr(driver.socket, 'socket', forbidden)
    with pytest.raises(driver.Unverified):
        driver.click_unix(path,420,490,1280,800)


SUMMARY = json.loads((ROOT / 'tests/fixtures/gnome-installer/run41262519173-summary.json').read_text())


def captured_tsv(words):
    import csv
    import io
    fields = ('level', 'page_num', 'block_num', 'par_num', 'line_num',
              'word_num', 'left', 'top', 'width', 'height', 'conf', 'text')
    output = io.StringIO()
    writer = csv.DictWriter(output, fields, delimiter='\t', extrasaction='ignore')
    writer.writeheader()
    writer.writerows(words)
    return output.getvalue()


def captured_rows(words, strict=True):
    return driver.ocr_rows(captured_tsv(words), strict=strict)


def measured_cards(mode='plain'):
    cards = {label: captured_rows(item['words'])[1]
             for label, item in SUMMARY['cards'].items()}
    if mode == 'luks':
        # Explicit test mutation, not captured credential-bearing evidence.
        cards['Encryption'][1] = ('Passphrase', cards['Encryption'][1][1])
    return cards


def measured_summary_screen():
    screen = object.__new__(driver.Screen)
    screen.width, screen.height, screen.state = 1280, 800, 'summary'
    screen.words, screen.rows = captured_rows(SUMMARY['full_frame']['words'], strict=False)
    screen.lines = [text for text, _ in screen.rows]
    screen.path = Path('safe-measured-summary.png')
    screen._summary_verified = False
    screen._install_box_cache = None
    return screen


@pytest.mark.parametrize('mode', ['plain', 'luks'])
def test_measured_summary_ocr_exact_target_and_mode(mode):
    driver.verify_summary_cards(measured_cards(mode), mode, SOURCE_REF)
    assert SUMMARY['mode'] == 'plain'
    assert SUMMARY['source_ref'] == SOURCE_REF
    assert driver.classify(measured_summary_screen().lines) == 'summary'


def mock_measured_summary_ocr(monkeypatch):
    regions = [*SUMMARY['cards'].values(), SUMMARY['warning'], SUMMARY['action']]
    calls, selected = [], []
    def run(args, **kwargs):
        calls.append(args)
        if args[0] == 'convert':
            geometry = args[args.index('-crop')+1]
            selected[:] = [next(item for item in regions if item['geometry'] == geometry)]
            if selected[0] in SUMMARY['cards'].values():
                assert '-resize' in args and args[args.index('-resize')+1] == '300%'
                assert args[args.index('-colorspace')+1] == 'gray'
            else:
                assert '-resize' not in args and '-negate' not in args
            return subprocess.CompletedProcess(args, 0, stdout=b'')
        assert args[0] == 'tesseract'
        assert args[args.index('--psm')+1] == selected[0]['psm']
        return subprocess.CompletedProcess(args, 0, stdout=captured_tsv(selected[0]['words']))
    monkeypatch.setattr(driver.subprocess, 'run', run)
    return calls


def test_actual_summary_frame_proves_four_cards_warning_and_action(monkeypatch):
    calls = mock_measured_summary_ocr(monkeypatch)
    screen = measured_summary_screen()
    driver.verify_summary(screen, 'plain', SOURCE_REF)
    assert screen._summary_verified
    assert screen.box('Install') == (618, 659, 661, 670)
    crops = [args[args.index('-crop')+1] for args in calls if args[0] == 'convert']
    assert len(crops) == 6 and len(set(crops)) == 6


@pytest.mark.parametrize('region', ['Target disk', 'Filesystem', 'Encryption', 'Image'])
def test_each_summary_crop_rejects_low_confidence(monkeypatch, region):
    calls = mock_measured_summary_ocr(monkeypatch)
    screen = measured_summary_screen()
    original = driver.subprocess.run
    def uncertain(args, **kwargs):
        result = original(args, **kwargs)
        if args[0] == 'tesseract' and calls[-2][calls[-2].index('-crop')+1] == SUMMARY['cards'][region]['geometry']:
            words = [dict(word, conf='39') for word in SUMMARY['cards'][region]['words']]
            result.stdout = captured_tsv(words)
        return result
    monkeypatch.setattr(driver.subprocess, 'run', uncertain)
    with pytest.raises(driver.Unverified):
        driver.verify_summary(screen, 'plain', SOURCE_REF)
    assert not screen._summary_verified


@pytest.mark.parametrize('mode', ['plain', 'luks'])
@pytest.mark.parametrize('change', [
    'wrong-device', 'wrong-capacity', 'wrong-unit', 'device-suffix',
    'wrong-encryption', 'wrong-filesystem', 'wrong-image', 'duplicate-row',
    'wrong-row', 'extra-token', 'unassociated-value', 'out-of-bounds',
    'wrong-title', 'missing-card', 'extra-card', 'swapped-values',
])
def test_summary_card_negatives_fail_closed(mode, change):
    cards = measured_cards(mode)
    disk, encryption = cards['Target disk'], cards['Encryption']
    text, box = disk[1]
    if change == 'wrong-device':
        disk[1] = (text.replace('/dev/vda', '/dev/vdb'), box)
    elif change == 'wrong-capacity':
        disk[1] = (text.replace('64', '640'), box)
    elif change == 'wrong-unit':
        disk[1] = (text.replace('GiB', 'GB'), box)
    elif change == 'device-suffix':
        disk[1] = (text.replace('/dev/vda', '/dev/vda1'), box)
    elif change == 'wrong-encryption':
        encryption[1] = ('Passphrase' if mode == 'plain' else 'No encryption', encryption[1][1])
    elif change == 'wrong-filesystem':
        cards['Filesystem'][1] = ('Btrfs', cards['Filesystem'][1][1])
    elif change == 'wrong-image':
        cards['Image'][1] = ('tuna-os/albacore:gnome', cards['Image'][1][1])
    elif change == 'duplicate-row':
        disk.append(disk[1])
    elif change == 'wrong-row':
        disk.reverse()
    elif change == 'extra-token':
        disk[1] = (text + ' /dev/vdb', box)
    elif change == 'unassociated-value':
        disk[1] = (text, (200, 78, 500, 111))
    elif change == 'out-of-bounds':
        disk[1] = (text, (13, 78, 313, 136))
    elif change == 'wrong-title':
        disk[0] = ('Disk', disk[0][1])
    elif change == 'missing-card':
        del cards['Image']
    elif change == 'extra-card':
        cards['Other'] = cards['Image']
    else:
        cards['Filesystem'][1], cards['Image'][1] = cards['Image'][1], cards['Filesystem'][1]
    with pytest.raises(driver.Unverified):
        driver.verify_summary_cards(cards, mode, SOURCE_REF)


@pytest.mark.parametrize('mode', ['plain', 'luks'])
def test_summary_warning_and_full_frame_mode_must_agree(mode):
    screen = FakeScreen('summary', mode=mode)
    driver.verify_summary(screen, mode, SOURCE_REF)
    for lines in (
        [line.replace('/dev/vda', '/dev/vdb') for line in screen.lines],
        screen.lines + ['Everything on /dev/vdb will be erased. This cannot be undone.'],
        [line for line in screen.lines if line not in ('No encryption', 'Passphrase')],
    ):
        changed = FakeScreen('summary', mode=mode)
        changed.lines = lines
        with pytest.raises(driver.Unverified):
            driver.verify_summary(changed, mode, SOURCE_REF)

@pytest.mark.parametrize('right,accepted', [(405, True), (394, False), (447, False)])
def test_summary_warning_width_follows_the_font_not_one_constant(right, accepted):
    # Run 42274770358 (grouper:gnome): Ubuntu's font sets the same warning
    # 405px wide where Adwaita's measured 420-446.
    screen = FakeScreen('summary', mode='plain')
    (text, (left, top, _, bottom)), = screen.summary_warning()
    screen.summary_warning = lambda: [(text, (left, top, right, bottom))]
    if accepted:
        driver.verify_summary(screen, 'plain', SOURCE_REF)
    else:
        with pytest.raises(driver.Unverified):
            driver.verify_summary(screen, 'plain', SOURCE_REF)



@pytest.mark.parametrize('change', [
    'missing-Encryption', 'duplicate-Encryption', 'misplaced-Encryption',
    'missing-heading', 'duplicate-heading', 'misplaced-heading',
    'missing-Summary', 'duplicate-Summary', 'misplaced-Summary', 'resolution', 'state',
])
def test_summary_anchors_reject_before_crop(monkeypatch, change):
    screen = measured_summary_screen()
    if change.endswith('-Encryption'):
        operation, label = change.split('-')
        if operation == 'missing':
            screen.words = [word for word in screen.words if word['text'] != label]
        elif operation == 'duplicate':
            screen.words.append(next(word.copy() for word in screen.words if word['text'] == label))
        else:
            next(word for word in screen.words if word['text'] == label)['left'] = '500'
    elif change.endswith('-heading') or change.endswith('-Summary'):
        operation, name = change.split('-')
        label = 'Confirm installation' if name == 'heading' else 'Summary'
        row = next(row for row in screen.rows if row[0] == label)
        if operation == 'missing':
            screen.rows.remove(row)
        elif operation == 'duplicate':
            screen.rows.append(row)
        else:
            screen.rows[screen.rows.index(row)] = (label, (510, 100, 770, 127))
    elif change == 'resolution':
        screen.width = 1920
    else:
        screen.state = 'overview'
    monkeypatch.setattr(driver.subprocess, 'run',
                        lambda *a, **k: pytest.fail('unverified layout must not invoke crop OCR'))
    with pytest.raises(driver.Unverified):
        screen.summary_cards()


def test_summary_ocr_uncertain_word_is_not_silently_dropped():
    word = dict(SUMMARY['cards']['Target disk']['words'][0], conf=39)
    with pytest.raises(driver.Unverified):
        captured_rows([word])


def run_ocr_install_step(tmp_path, versions=None):
    workflow = (ROOT / '.github/workflows/test.yml').read_text()
    job = workflow.split('  gnome-summary-ocr:', 1)[1].split('  unit-tests:', 1)[0]
    step = job.split('      - name: Install measured OCR dependencies\n', 1)[1]
    body = step.split('        run: |\n', 1)[1].split('      - name:', 1)[0]
    script = textwrap.dedent(body)

    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir(parents=True)
    (bin_dir / 'sudo').write_text('#!/bin/sh\nexec "$@"\n')
    (bin_dir / 'apt-get').write_text(
        '#!/bin/sh\nprintf \'%s\\n\' "$*" >> "$APT_GET_LOG"\n')
    (bin_dir / 'dpkg-query').write_text('''#!/bin/sh
printf '%s\\n' "$@" > "$DPKG_QUERY_LOG"
[ "$1" = '-W' ] || exit 2
shift 2
for package do
  case "$package" in
    imagemagick|imagemagick-6.q16) version="$IMAGEMAGICK_VERSION" ;;
    tesseract-ocr|libtesseract5) version="$TESSERACT_VERSION" ;;
    tesseract-ocr-eng|tesseract-ocr-osd) version="$LANGUAGE_DATA_VERSION" ;;
    *) exit 2 ;;
  esac
  printf '%s\\t%s\\n' "$package" "$version"
done
''')
    for stub in bin_dir.iterdir():
        stub.chmod(0o755)

    versions = {
        'IMAGEMAGICK_VERSION': '8:6.9.12.98+dfsg1-99ubuntu1',
        'TESSERACT_VERSION': '5.3.4-99build99',
        'LANGUAGE_DATA_VERSION': '1:4.1.0-99',
    } | (versions or {})
    env = {
        **os.environ,
        'PATH': f'{bin_dir}:{os.environ["PATH"]}',
        'APT_GET_LOG': str(tmp_path / 'apt-get.log'),
        'DPKG_QUERY_LOG': str(tmp_path / 'dpkg-query.log'),
        **versions,
    }
    result = subprocess.run(
        ['/bin/bash', '-euo', 'pipefail', '-c', script],
        cwd=ROOT, env=env, text=True, capture_output=True, check=False)
    return result, tmp_path


def test_ocr_dependency_install_accepts_only_measured_upstream_versions(tmp_path):

    result, output_dir = run_ocr_install_step(tmp_path / 'later-revision')
    assert result.returncode == 0, result.stderr
    assert (output_dir / 'apt-get.log').read_text().splitlines() == [
        'update -qq',
        'install -y --no-install-recommends python3-pytest imagemagick '
        'imagemagick-6.q16 tesseract-ocr libtesseract5 tesseract-ocr-eng '
        'tesseract-ocr-osd',
    ]
    assert all('=' not in package for package in
               (output_dir / 'apt-get.log').read_text().splitlines()[1].split()[3:])
    assert (output_dir / 'dpkg-query.log').read_text().splitlines()[2:] == [
        'imagemagick', 'imagemagick-6.q16', 'tesseract-ocr', 'libtesseract5',
        'tesseract-ocr-eng', 'tesseract-ocr-osd',
    ]

    for name, wrong_versions in [
        ('imagemagick', {'IMAGEMAGICK_VERSION': '8:6.9.12.97+dfsg1-99ubuntu1'}),
        ('tesseract', {'TESSERACT_VERSION': '5.3.40-99build99'}),
        ('language-data', {'LANGUAGE_DATA_VERSION': '1:4.1.01-99'}),
    ]:
        wrong_version, _ = run_ocr_install_step(tmp_path / f'wrong-{name}', wrong_versions)
        assert wrong_version.returncode != 0
        assert 'does not match upstream' in wrong_version.stderr

BUTTON = json.loads((ROOT / 'tests/fixtures/gnome-installer/button39897665901.json').read_text())


def test_measured_button_words_map_to_original_pixels():
    _, rows = captured_rows(SUMMARY['action']['words'])
    assert driver.install_box_from_rows(rows, 595, 645) == (618, 659, 661, 670)


@pytest.mark.parametrize('rows', [
    [], [('Install', (23, 14, 66, 25))]*2,
    [('Install now', (23, 14, 66, 25))],
    [('Cancel', (23, 14, 66, 25))],
    [('Install', (0, 14, 43, 25))],
    [('Install', (23, 0, 66, 11))],
    [('Install', (23, 14, 90, 25))],
    [('Install', (23, 14, 66, 35))],
])
def test_final_label_rejects_wrong_ambiguous_or_misplaced_text(rows):
    with pytest.raises(driver.Unverified):
        driver.install_box_from_rows(rows, 595, 645)


@pytest.mark.parametrize('change', [
    'unverified', 'state', 'resolution', 'heading', 'duplicate-heading', 'extra-install',
])
def test_final_control_requires_summary_and_unique_foreground(monkeypatch, change):
    screen = measured_summary_screen()
    screen._summary_verified = True
    screen.rows = [('Confirm installation', (511, 175, 768, 196)),
                   ('Summary', (352, 316, 421, 330))]
    if change == 'unverified': screen._summary_verified = False
    elif change == 'state': screen.state = 'overview'
    elif change == 'resolution': screen.width = 1920
    elif change == 'heading': screen.rows[0] = ('Confirm installation', (510, 100, 770, 127))
    elif change == 'duplicate-heading': screen.rows *= 2
    else: screen.rows.append(('Install', (800, 580, 850, 600)))
    monkeypatch.setattr(driver.subprocess, 'run',
                        lambda *a, **k: pytest.fail('invalid layout must fail before OCR'))
    with pytest.raises(driver.Unverified):
        screen.box('Install')


@pytest.mark.parametrize('box', [(-1, 0, 20, 20), (0, 0, 1281, 20),
                                (0, 0, 20, 801), (20, 0, 0, 20),
                                (True, 0, 20, 20)])
def test_control_target_rejects_invalid_coordinates_before_input(box):
    screen = FakeScreen('summary')
    screen.box = lambda label: box
    with pytest.raises(driver.Unverified):
        driver.control_target(screen, 'Install', enabled=True)


def test_failed_summary_invalidates_prior_proof():
    screen = FakeScreen('summary')
    driver.verify_summary(screen, 'plain', SOURCE_REF)
    assert screen._summary_verified
    screen.lines = [line.replace('/dev/vda', '/dev/vdb') for line in screen.lines]
    with pytest.raises(driver.Unverified):
        driver.verify_summary(screen, 'plain', SOURCE_REF)
    assert not screen._summary_verified


@pytest.mark.parametrize('source_ref', [
    '', ' ', 'tuna-os/skipjack:gnome other', 'https://ghcr.io/tuna-os/skipjack:gnome',
    'user:secret@ghcr.io/tuna-os/skipjack:gnome',
])
def test_unsupported_source_ref_rejects_before_input_or_capture(tmp_path, source_ref):
    rc, result, events = execute(tmp_path, [], source_ref=source_ref)
    assert rc == 1 and events == []
    assert not result['submit_attempted'] and not result['submitted']
    assert not result['accepted'] and not result['completed']


def test_failed_card_recheck_invalidates_prior_proof():
    screen = FakeScreen('summary')
    driver.verify_summary(screen, 'plain', SOURCE_REF)
    assert screen._summary_verified
    cards = measured_cards()
    cards['Image'][1] = ('tuna-os/albacore:gnome', cards['Image'][1][1])
    screen.summary_cards = lambda: cards
    with pytest.raises(driver.Unverified):
        driver.verify_summary(screen, 'plain', SOURCE_REF)
    assert not screen._summary_verified


def test_source_ref_is_generic_but_image_equality_is_exact():
    cards = measured_cards()
    other = 'tuna-os/albacore:gnome'
    with pytest.raises(driver.Unverified):
        driver.verify_summary_cards(cards, 'plain', other)
    cards['Image'][1] = (other, cards['Image'][1][1])
    driver.verify_summary_cards(cards, 'plain', other)


@pytest.mark.parametrize('change', ['missing', 'duplicate', 'wrong-device', 'clipped', 'misplaced'])
def test_warning_crop_refuses_bad_proof_and_invalidates_previous_summary(change):
    screen = FakeScreen('summary')
    driver.verify_summary(screen, 'plain', SOURCE_REF)
    rows = captured_rows(SUMMARY['warning']['words'])[1]
    text, box = rows[0]
    if change == 'missing':
        rows = []
    elif change == 'duplicate':
        rows *= 2
    elif change == 'wrong-device':
        rows = [(text.replace('/dev/vda', '/dev/vdb'), box)]
    elif change == 'clipped':
        rows = [(text, (0, 8, 436, 30))]
    else:
        rows = [(text, (60, 8, 491, 22))]
    screen.summary_warning = lambda: rows
    with pytest.raises(driver.Unverified):
        driver.verify_summary(screen, 'plain', SOURCE_REF)
    assert not screen._summary_verified


@pytest.mark.parametrize('label', ['Target disk', 'Filesystem', 'Encryption', 'Image'])
@pytest.mark.parametrize('change', ['missing', 'duplicate', 'misplaced', 'clipped'])
def test_every_card_requires_its_own_visible_unique_label(label, change):
    cards = measured_cards()
    title, value = cards[label]
    if change == 'missing':
        cards[label] = [value]
    elif change == 'duplicate':
        cards[label] = [title, title, value]
    elif change == 'misplaced':
        cards[label][0] = (title[0], (200, 17, 450, 61))
    else:
        cards[label][0] = (title[0], (13, 0, 241, 61))
    with pytest.raises(driver.Unverified):
        driver.verify_summary_cards(cards, 'plain', SOURCE_REF)


def test_failed_real_summary_recheck_cannot_reuse_cached_action(monkeypatch):
    mock_measured_summary_ocr(monkeypatch)
    screen = measured_summary_screen()
    driver.verify_summary(screen, 'plain', SOURCE_REF)
    screen.box('Install')
    cards = measured_cards()
    del cards['Image']
    screen.summary_cards = lambda: cards
    with pytest.raises(driver.Unverified):
        driver.verify_summary(screen, 'plain', SOURCE_REF)
    with pytest.raises(driver.Unverified):
        screen.box('Install')


def test_action_low_confidence_rejects_before_pointer(monkeypatch):
    mock_measured_summary_ocr(monkeypatch)
    screen = measured_summary_screen()
    driver.verify_summary(screen, 'plain', SOURCE_REF)
    original = driver.subprocess.run
    def uncertain(args, **kwargs):
        result = original(args, **kwargs)
        if args[0] == 'tesseract':
            result.stdout = captured_tsv([dict(SUMMARY['action']['words'][0], conf='39')])
        return result
    monkeypatch.setattr(driver.subprocess, 'run', uncertain)
    with pytest.raises(driver.Unverified):
        driver.control_target(screen, 'Install', enabled=True)


def measured_action_pixels(capture):
    data = SUMMARY['action_pixels'][capture]
    cx, cy = data['sample_center']
    pixels = {(cx+item['offset'][0], cy+item['offset'][1]): tuple(item['rgb'])
              for item in data['points']}
    left, top, right, bottom = data['label_region']['box']
    for y, row in enumerate(data['label_region']['rgb_rows'], top):
        raw = bytes.fromhex(row)
        for x in range(left, right):
            offset = (x-left)*3
            pixels[(x, y)] = tuple(raw[offset:offset+3])
    return pixels


def test_original_destructive_action_is_enabled_after_summary_proof(monkeypatch):
    mock_measured_summary_ocr(monkeypatch)
    screen = measured_summary_screen()
    driver.verify_summary(screen, 'plain', SOURCE_REF)
    pixels = measured_action_pixels('published_plain_enabled')
    screen.rgb = lambda x, y: pixels[(x, y)]
    assert screen.enabled('Install')
    assert SUMMARY['action_pixels']['published_plain_enabled']['dark_red_count'] == 155


@pytest.mark.parametrize('capture,expected,count', [
    ('native_enabled', True, 133), ('native_disabled', False, 0),
    ('native_reenabled', True, 133),
])
def test_native_destructive_style_sensitivity_isolated_from_layout(capture, expected, count):
    data = SUMMARY['action_pixels'][capture]
    screen = object.__new__(driver.Screen)
    screen._install_center = tuple(data['sample_center'])
    screen.box = lambda label: tuple(data['label_region']['box'])
    pixels = measured_action_pixels(capture)
    screen.rgb = lambda x, y: pixels[(x, y)]
    # Isolated native style proof; this does not accept the component window as
    # the driver's required 1280x800 desktop summary or submit an installation.
    assert screen.enabled('Install') is expected
    assert data['dark_red_count'] == count
    assert data['provenance']['confirmation_signal_count'] == 0


@pytest.mark.parametrize('change', ['purple', 'dimmed', 'covered', 'missing-text', 'wrong-background'])
def test_destructive_action_rejects_noncanonical_or_obscured_pixels(monkeypatch, change):
    mock_measured_summary_ocr(monkeypatch)
    screen = measured_summary_screen()
    driver.verify_summary(screen, 'plain', SOURCE_REF)
    pixels = measured_action_pixels('published_plain_enabled')
    if change == 'purple':
        for point in ((610, 665), (670, 665), (640, 651), (640, 679)):
            pixels[point] = (145, 65, 172)
    elif change == 'dimmed':
        pixels = {point: (180, 180, 180) for point in pixels}
    elif change == 'covered':
        pixels[(610, 665)] = (180, 180, 180)
    elif change == 'missing-text':
        for y in range(659, 670):
            for x in range(618, 661):
                pixels[(x, y)] = (242, 213, 214)
    else:
        pixels[(580, 665)] = (242, 213, 214)
    screen.rgb = lambda x, y: pixels[(x, y)]
    assert not screen.enabled('Install')


def test_retained_button_failures_remain_negative_evidence():
    assert len(BUTTON['rejected']) == 4
    assert all(item['words'] == [] for item in BUTTON['rejected'])


PROGRESS_ROWS = [
    ('Almost ready...', (506, 35, 1292, 118)),
    ('Do not power off the computer.', (335, 32, 864, 70)),
    ('0:00 elapsed', (16, 23, 239, 61)),
    ('1%', (65, 20, 133, 55)),
]


@pytest.mark.parametrize('title', sorted(driver.PROGRESS_TITLES) + ['Installing Skipjack'])
def test_source_progress_titles_need_same_frame_markers(title):
    rows = [(title+'...', PROGRESS_ROWS[0][1])] + PROGRESS_ROWS[1:]
    assert driver.verify_progress_rows(rows, title+'...')[0] == title+'...'


@pytest.mark.parametrize('index', range(4))
@pytest.mark.parametrize('mutation', ['missing', 'duplicate', 'wrong-position'])
def test_progress_marker_ambiguity_or_geometry_fails(index, mutation):
    rows = list(PROGRESS_ROWS)
    if mutation == 'missing':
        rows.pop(index)
    elif mutation == 'duplicate':
        rows.append(rows[index])
    else:
        rows[index] = (rows[index][0], (0, 0, 10, 10))
    with pytest.raises(driver.Unverified):
        driver.verify_progress_rows(rows, 'Almost ready...')


@pytest.mark.parametrize('index,value', [(0, 'Installation Finished'), (0, 'Installing'),
    (1, 'Do not pawer off the computer.'), (2, '0:60 elapsed'),
    (2, '159 elapsed'), (2, '1000:00 elapsed'), (3, '101%'), (3, '-1%'), (3, 'A%')])
def test_progress_wrong_text_is_not_fuzzily_accepted(index, value):
    rows = list(PROGRESS_ROWS)
    rows[index] = (value, rows[index][1])
    with pytest.raises(driver.Unverified):
        driver.verify_progress_rows(rows, 'Almost ready...')


@pytest.mark.parametrize('clock', ['0:00 elapsed', '0:59 elapsed', '1:00 elapsed', '999:59 elapsed'])
@pytest.mark.parametrize('percent', ['0%', '1%', '99%', '100%'])
def test_progress_clock_and_percentage_boundaries(clock, percent):
    rows = list(PROGRESS_ROWS)
    rows[2] = (clock, rows[2][1])
    rows[3] = (percent, rows[3][1])
    assert driver.verify_progress_rows(rows, 'Almost ready...')[2:] == [clock, percent]


def test_progress_title_crop_must_agree_with_full_frame():
    with pytest.raises(driver.Unverified):
        driver.verify_progress_rows(PROGRESS_ROWS, 'Securing your drive...')


@pytest.mark.parametrize('state,line', [('failed', 'Installation failed'),
    ('done', 'Skipjack is installed'), ('recovery', 'Save your recovery key'),
    ('summary', 'Confirm installation'), ('unknown', 'Authentication required'),
    ('unknown', 'Restart now')])
def test_progress_never_overrides_foreground_state(monkeypatch, state, line):
    screen = object.__new__(driver.Screen)
    screen.width, screen.height, screen.state = 1280, 800, state
    screen.lines = ['Almost ready...', line]
    screen.rows = [('Almost ready...', (230, 675, 359, 692))]
    monkeypatch.setattr(driver.subprocess, 'run', lambda *a, **kw: pytest.fail('excluded page reached OCR'))
    screen.verify_progress_panel()
    assert screen.state == state


@pytest.mark.parametrize('mutation', ['title-only', 'duplicate-title', 'duplicate-clock',
    'wrong-title-position', 'wrong-clock-position', 'editable', 'dimmed', 'missing-bar'])
def test_current_progress_refuses_incomplete_or_covered_panel(monkeypatch, mutation):
    screen = object.__new__(driver.Screen)
    screen.width, screen.height, screen.state = 1280, 800, 'unknown'
    screen.rows = [('Installing Skipjack...', (509, 527, 771, 554)),
                   ('0:11 elapsed', (340, 623, 415, 636))]
    screen.lines = [text for text, _ in screen.rows]
    screen.rgb = lambda x, y: (220, 220, 221) if y == 607 and 340 <= x <= 940 else (250, 250, 251)
    if mutation == 'title-only':
        screen.rows.pop()
    elif mutation == 'duplicate-title':
        screen.rows.append(screen.rows[0])
    elif mutation == 'duplicate-clock':
        screen.rows.append(screen.rows[1])
    elif mutation == 'wrong-title-position':
        screen.rows[0] = (screen.rows[0][0], (230, 675, 450, 692))
    elif mutation == 'wrong-clock-position':
        screen.rows[1] = (screen.rows[1][0], (500, 623, 575, 636))
    elif mutation == 'editable':
        screen.lines.append('Install')
    elif mutation == 'dimmed':
        screen.rgb = lambda x, y: (180, 180, 180)
    elif mutation == 'missing-bar':
        screen.rgb = lambda x, y: (250, 250, 251)
    if mutation == 'title-only':
        # The clock may be re-read once from its own band; an empty read admits nothing.
        from types import SimpleNamespace
        empty = 'level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n'
        screen.path = Path('progress.png')
        monkeypatch.setattr(driver.subprocess, 'run', lambda *a, **kw: SimpleNamespace(stdout=empty))
    else:
        monkeypatch.setattr(driver.subprocess, 'run', lambda *a, **kw: pytest.fail('unverified page reached OCR'))
    screen.verify_progress_panel()
    assert screen.state == 'unknown'


def test_progress_clock_is_read_from_its_band_when_full_frame_drops_it(monkeypatch):
    # Run 42283316580 (grouper:gnome): "1:53 elapsed" came back as 'mi'. The band
    # read returns the clock, its unit and the ETA's clipped '-'; only the first
    # two make the clock row.
    from types import SimpleNamespace
    screen = object.__new__(driver.Screen)
    screen.width, screen.height = 1280, 800
    screen.path = Path('progress.png')
    tsv = ('level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n'
           '5\t1\t1\t1\t1\t1\t18\t23\t65\t29\t95\t1:53\n'
           '5\t1\t1\t1\t1\t2\t93\t20\t124\t38\t95\telapsed\n'
           '5\t1\t1\t1\t1\t3\t256\t35\t14\t8\t60\t-\n')
    monkeypatch.setattr(driver.subprocess, 'run', lambda *a, **kw: SimpleNamespace(stdout=tsv))
    (text, box), = screen._clock_from_band()
    assert text == '1:53 elapsed'
    assert 338 <= box[0] <= 345 and 620 <= box[1] <= 630 and 400 <= box[2] <= 460 and 632 <= box[3] <= 640


@pytest.mark.parametrize('after_acceptance', [False, True])
def test_wrong_progress_product_never_completes_or_receives_input(tmp_path, after_acceptance):
    screens = [FakeScreen('welcome'), FakeScreen('encryption'), FakeScreen('summary')]
    if after_acceptance:
        screens.append(FakeScreen('progress'))
    screens.append(FakeScreen('progress', product='Wrong Product'))
    rc, result, events = execute(tmp_path, screens)
    assert rc == 1 and result['submitted'] and not result['completed']
    assert result['accepted'] is after_acceptance
    assert 'product differs' in result['error']
    submitted = events.index(('capture', 'await-progress'))
    assert all(event[0] == 'capture' for event in events[submitted:])


@pytest.mark.parametrize('title', sorted(driver.PROGRESS_TITLES))
@pytest.mark.parametrize('after_acceptance', [False, True])
def test_generic_progress_stage_keeps_observing_until_real_done(tmp_path, title, after_acceptance):
    stage = FakeScreen('progress')
    stage.progress_markers[0] = title + '...'
    screens = [FakeScreen('welcome'), FakeScreen('encryption'), FakeScreen('summary')]
    if after_acceptance:
        screens.append(FakeScreen('progress'))
    screens.extend([stage, FakeScreen('done')])
    rc, result, events = execute(tmp_path, screens)
    assert rc == 0 and result['accepted'] and result['completed']
    submitted = events.index(('capture', 'await-progress'))
    assert all(event[0] == 'capture' for event in events[submitted:])


@pytest.mark.parametrize('rows', [[], [('Restart', (39, 27, 293, 60))],
    [('Restart now', (39, 27, 293, 60))]*2,
    [('Restart now', (0, 27, 293, 60))], [('Restart now', (39, 27, 330, 60))],
    [('Restart now', (39, 27, 293, 90))], [('Restart now', (True, 27, 293, 60))]])
def test_completion_restart_label_is_exact_and_bounded(rows):
    with pytest.raises(driver.Unverified):
        driver.verify_restart_rows(rows)


def test_completion_restart_label_observation_only():
    assert driver.verify_restart_rows([('Restart now', (39, 27, 293, 60))]) == 'Restart now'


BARE_INSTRUCTION = 'Remove the installation media and restart the computer.'
TIMED_INSTRUCTION = 'Installed in 2:05. '+BARE_INSTRUCTION


def completion_screen(instruction, media_box):
    """Unit panel in retained desktop geometry, not proof of a new live render."""
    screen = object.__new__(driver.Screen)
    screen.path = Path('unit-completion.png')
    screen.width, screen.height = 1280, 800
    screen.rows = [('TunaOS is installed', (511, 321, 767, 348)),
                   (instruction, media_box)]
    screen.lines = [text for text, _ in screen.rows]
    screen.state = driver.classify(screen.lines)
    screen.rgb = lambda x, y: ((145, 65, 172) if (x, y) in ((645, 419), (780, 419))
                              else (250, 250, 251))
    return screen


RESTART_TSV = (
    'level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n'
    '5\t1\t1\t1\t1\t1\t39\t27\t170\t33\t96\tRestart\n'
    '5\t1\t1\t1\t1\t2\t220\t27\t73\t33\t96\tnow\n'
)


@pytest.mark.parametrize('instruction,media_box', [
    (BARE_INSTRUCTION, (447, 358, 832, 372)),
    ('Installed in 0:01. '+BARE_INSTRUCTION, (393, 358, 887, 372)),
    ('Installed in 0:59. '+BARE_INSTRUCTION, (393, 358, 887, 372)),
    ('Installed in 1:00. '+BARE_INSTRUCTION, (393, 358, 887, 372)),
    (TIMED_INSTRUCTION, (393, 358, 887, 372)),
    ('Installed in 999:59. '+BARE_INSTRUCTION, (384, 358, 895, 372)),
])
@pytest.mark.parametrize('full_restart', [False, True])
def test_completion_panel_then_observes_without_input(tmp_path, monkeypatch, full_restart,
                                                    instruction, media_box):
    from types import SimpleNamespace
    screen = completion_screen(instruction, media_box)
    if full_restart:
        screen.rows.append(('Restart now', (670, 414, 755, 425)))
        screen.lines.append('Restart now')
        screen.state = driver.classify(screen.lines)
    monkeypatch.setattr(driver.subprocess, 'run',
                        lambda *a, **kw: SimpleNamespace(stdout=RESTART_TSV))
    screen.verify_completion_panel()
    assert screen.state == 'done'
    assert screen.completion_markers == ['TunaOS is installed', instruction, 'Restart now']
    rc, result, events = execute(tmp_path, [
        FakeScreen('welcome'), FakeScreen('encryption'), FakeScreen('summary'),
        FakeScreen('progress'), screen])
    assert rc == 0 and result['accepted'] and result['completed']
    accepted = events.index(('capture', 'await-progress'))
    assert all(event[0] == 'capture' for event in events[accepted:])


@pytest.mark.parametrize('height,accepted', [(20, True), (18, True), (17, False)])
def test_completion_title_without_descenders_is_still_the_done_page(monkeypatch, height, accepted):
    # "Marlin is installed" has no descenders: about 20px tall, not 26-28px.
    from types import SimpleNamespace
    screen = completion_screen(BARE_INSTRUCTION, (447, 358, 832, 372))
    screen.rows[0] = ('Marlin is installed', (540, 321, 740, 321 + height))
    screen.lines = [text for text, _ in screen.rows]
    screen.state = driver.classify(screen.lines)
    monkeypatch.setattr(driver.subprocess, 'run',
                        lambda *a, **kw: SimpleNamespace(stdout=RESTART_TSV))
    screen.verify_completion_panel()
    assert (screen.state == 'done') is accepted


@pytest.mark.parametrize('instruction,low,high', [
    (BARE_INSTRUCTION, 370, 400), (TIMED_INSTRUCTION, 490, 515),
])
@pytest.mark.parametrize('edge', ['below', 'low', 'high', 'above'])
def test_completion_width_bounds_are_specific_to_instruction(monkeypatch, instruction, low, high, edge):
    from types import SimpleNamespace
    width = {'below': low-1, 'low': low, 'high': high, 'above': high+1}[edge]
    left = 640-width//2
    screen = completion_screen(instruction, (left, 358, left+width, 372))
    accepted = edge in ('low', 'high')
    def run(*args, **kwargs):
        assert accepted, 'out-of-bound media width reached button OCR'
        return SimpleNamespace(stdout=RESTART_TSV)
    monkeypatch.setattr(driver.subprocess, 'run', run)
    screen.verify_completion_panel()
    assert screen.state == ('done' if accepted else 'unknown')


@pytest.mark.parametrize('instruction,media_box', [
    (BARE_INSTRUCTION, (451, 281, 829, 295)),
    ('Installed in 0:01. '+BARE_INSTRUCTION, (393, 281, 887, 295)),
    (TIMED_INSTRUCTION, (393, 281, 887, 295)),
    ('Installed in 999:59. '+BARE_INSTRUCTION, (384, 281, 895, 295)),
    (BARE_INSTRUCTION, (447, 314, 832, 328)),
    (TIMED_INSTRUCTION, (393, 314, 887, 328)),
])
def test_native_media_rows_do_not_repin_retained_desktop_geometry(monkeypatch, instruction, media_box):
    screen = completion_screen(instruction, media_box)
    monkeypatch.setattr(driver.subprocess, 'run',
                        lambda *a, **kw: pytest.fail('native media Y bypassed desktop guard'))
    screen.verify_completion_panel()
    assert screen.state == 'unknown'


@pytest.mark.parametrize('instruction', [
    'Installed in 0:00. '+BARE_INSTRUCTION,
    'Installed in 00:01. '+BARE_INSTRUCTION,
    'Installed in 01:00. '+BARE_INSTRUCTION,
    'Installed in 1:1. '+BARE_INSTRUCTION,
    'Installed in 1:60. '+BARE_INSTRUCTION,
    'Installed in 1000:00. '+BARE_INSTRUCTION,
    'Installed in -1:00. '+BARE_INSTRUCTION,
    'Installed in 1:00 elapsed. '+BARE_INSTRUCTION,
    'Installed in 2:05 '+BARE_INSTRUCTION,
    'Installed in 2:05.  '+BARE_INSTRUCTION,
    'Installed in 2:05. Installed in 2:05. '+BARE_INSTRUCTION,
    'Prefix '+BARE_INSTRUCTION,
    BARE_INSTRUCTION+' Suffix',
    'Prefix '+TIMED_INSTRUCTION,
    TIMED_INSTRUCTION+' Suffix',
    'Installed in 0:01. '+BARE_INSTRUCTION+' Suffix',
    'Installed in 2:05. '+BARE_INSTRUCTION.lower(),
    'Installed in 2:05. '+BARE_INSTRUCTION+'\n',
    'Installed in 2:05:00. '+BARE_INSTRUCTION,
    'Installed in 2:05.0. '+BARE_INSTRUCTION,
    'Installed in 2:5. '+BARE_INSTRUCTION,
    'Installed in 2:005. '+BARE_INSTRUCTION,
    'Installed in +2:05. '+BARE_INSTRUCTION,
    'Installed in 02:05. '+BARE_INSTRUCTION,
    BARE_INSTRUCTION.lower(),
    'Finished! '+BARE_INSTRUCTION,
    'Installation Finished. '+BARE_INSTRUCTION,
])
def test_completion_instruction_requires_exact_grammar(monkeypatch, instruction):
    width = 494 if instruction.startswith('Installed in ') else 385
    left = 640-width//2
    screen = completion_screen(instruction, (left, 358, left+width, 372))
    from types import SimpleNamespace
    empty = 'level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n'
    def run(command, **options):
        # Only the media line's own band may be re-read (an empty read admits
        # nothing); the Restart button crop must never run for a bad sentence.
        if any(str(a).startswith('900x') for a in command) or command[0] == 'tesseract':
            return SimpleNamespace(stdout=empty)
        pytest.fail('bad instruction reached button OCR')
    monkeypatch.setattr(driver.subprocess, 'run', run)
    screen.verify_completion_panel()
    assert screen.state == 'unknown'


@pytest.mark.parametrize('mutation', ['failed', 'recovery', 'overview', 'authentication',
    'progress', 'elapsed', 'finished', 'password', 'confirm-password', 'editable-next',
    'editable-install', 'missing-title', 'duplicate-title', 'wrong-title-box',
    'title-off-center', 'title-height', 'title-width',
    'missing-media', 'duplicate-media', 'wrong-media', 'wrong-media-box',
    'media-off-center', 'media-height',
    'extra-restart', 'duplicate-restart', 'dimensions', 'dimmed', 'disabled', 'covered'])
@pytest.mark.parametrize('initial', ['unknown', 'done'])
@pytest.mark.parametrize('timed', [False, True])
def test_completion_never_bypasses_same_frame_guards(monkeypatch, mutation, initial, timed):
    screen = completion_screen(TIMED_INSTRUCTION if timed else BARE_INSTRUCTION,
                               (393, 358, 887, 372) if timed else (447, 358, 832, 372))
    screen.state = initial
    left, top, right, bottom = screen.rows[1][1]
    extra = {'failed': 'Installation failed', 'recovery': 'Save your recovery key',
             'overview': 'Type to search', 'authentication': 'Authentication required',
             'progress': 'Almost ready...', 'elapsed': '5:00 elapsed',
             'finished': 'Installation Finished', 'password': 'Password',
             'confirm-password': 'Confirm Password', 'editable-next': 'Next',
             'editable-install': 'Install'}
    if mutation in extra:
        screen.rows.append((extra[mutation], (230, 675, 450, 695)))
    elif mutation == 'missing-title': screen.rows.pop(0)
    elif mutation == 'duplicate-title': screen.rows.append(screen.rows[0])
    elif mutation == 'wrong-title-box': screen.rows[0] = (screen.rows[0][0], (511, 177, 767, 204))
    elif mutation == 'title-off-center': screen.rows[0] = (screen.rows[0][0], (521, 321, 777, 348))
    elif mutation == 'title-height': screen.rows[0] = (screen.rows[0][0], (511, 321, 767, 354))
    elif mutation == 'title-width': screen.rows[0] = (screen.rows[0][0], (330, 321, 950, 348))
    elif mutation == 'missing-media': screen.rows.pop(1)
    elif mutation == 'duplicate-media': screen.rows.append(screen.rows[1])
    elif mutation == 'wrong-media': screen.rows[1] = ('Remove the installation media later.', screen.rows[1][1])
    elif mutation == 'wrong-media-box': screen.rows[1] = (screen.rows[1][0], (left, top-100, right, bottom-100))
    elif mutation == 'media-off-center': screen.rows[1] = (screen.rows[1][0], (left+10, top, right+10, bottom))
    elif mutation == 'media-height': screen.rows[1] = (screen.rows[1][0], (left, top, right, top+19))
    elif mutation in ('extra-restart', 'duplicate-restart'):
        screen.rows += [('Restart now', (900, 500, 990, 515))] * (2 if mutation == 'duplicate-restart' else 1)
    elif mutation == 'dimensions': screen.width = 1024
    screen.lines = [text for text, _ in screen.rows]
    def rgb(x, y):
        if mutation == 'dimmed': return (180, 180, 180)
        if mutation == 'covered' and (x, y) == (220, 314): return (180, 180, 180)
        if (x, y) in ((645, 419), (780, 419)):
            return (220, 220, 220) if mutation == 'disabled' else (145, 65, 172)
        return (250, 250, 251)
    screen.rgb = rgb
    calls = []
    empty = 'level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n'
    def run(command, **options):
        calls.append(command)
        # A missing title or media line may be re-read once from its own band
        # of the same frame; nothing else may run, and an empty read admits nothing.
        if mutation in ('missing-title', 'missing-media', 'wrong-media') and any(str(a).startswith('900x') for a in command) \
                or command[0] == 'tesseract' and mutation in ('missing-title', 'missing-media', 'wrong-media'):
            from types import SimpleNamespace
            return SimpleNamespace(stdout=empty)
        pytest.fail('invalid completion reached OCR')
    monkeypatch.setattr(driver.subprocess, 'run', run)
    screen.verify_completion_panel()
    assert screen.state == 'unknown'
    assert not any('300%' in command for command in calls)


@pytest.mark.parametrize('flavor,explicit,candidate', [
    ('gnome', True, False), ('xfce', True, True), ('kde', True, False),
])
def test_actual_walkthrough_capture_route(tmp_path, monkeypatch, flavor, explicit, candidate):
    """Capture a frame through a native HMP peer, not callback-route echoes."""
    import ast
    import types
    import zlib
    from concurrent.futures import ThreadPoolExecutor

    source = ROOT / 'scripts/installer-walkthrough.py'
    functions = [node for node in ast.parse(source.read_text()).body
                 if isinstance(node, ast.FunctionDef)
                 and node.name in ('settle', 'hmp', 'vnc_capture', 'shot', 'png_geometry')]
    monkeypatch.syspath_prepend(str(ROOT / 'scripts'))
    elapsed = 0
    scale = 0.25
    def sleep(seconds):
        nonlocal elapsed
        assert seconds > 0
        elapsed += seconds

    pixels = b'\x12\x34\x56'
    ppm_frame = b'P6\n1 1\n255\n' + pixels
    def chunk(kind, data):
        return (struct.pack('!I', len(data)) + kind + data
                + struct.pack('!I', zlib.crc32(kind + data)))
    png_frame = (b'\x89PNG\r\n\x1a\n'
                 + chunk(b'IHDR', struct.pack('!IIBBBBB', 1, 1, 8, 2, 0, 0, 0))
                 + chunk(b'IDAT', zlib.compress(b'\0' + pixels)) + chunk(b'IEND', b''))
    def convert(ppm, png):
        # Verify the frame and scaled redraw wait before crossing the converter boundary.
        assert Path(ppm).read_bytes() == ppm_frame
        assert elapsed == pytest.approx((1.5 if candidate else 0.2 + 0.4 + 1.5) * scale)
        assert not Path(png).exists()
        Path(png).write_bytes(png_frame)

    monitor = tmp_path / 'monitor.sock'
    vnc = tmp_path / 'vnc.sock'
    if flavor != 'kde':
        vnc.touch()  # Strict capture must not inspect VNC tooling even with a path present.
    def forbidden_tool(name):
        pytest.fail(f'unexpected VNC tool lookup: {name}')
    namespace = dict(os=types.SimpleNamespace(path=os.path, remove=os.remove,
                         environ={'TUNAOS_XFCE_CANDIDATE': '1'} if candidate else {}),
                     socket=socket, time=types.SimpleNamespace(sleep=sleep),
                     wait_scale=scale, mode_explicit=explicit, flavor=flavor,
                     outdir=str(tmp_path), mon_path=str(monitor), vm_gone=None,
                     vnc_sock=str(vnc), shutil=types.SimpleNamespace(which=forbidden_tool),
                     _ppm_to_png=convert)
    exec(compile(ast.Module(body=functions, type_ignores=[]), str(source), 'exec'), namespace)
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.settimeout(5)
    server.bind(str(monitor))
    server.listen(1)
    ppm = tmp_path / f'walkthrough-{flavor}-00.ppm'
    def serve():
        with server.accept()[0] as conn:
            conn.settimeout(5)
            conn.sendall(b'QEMU monitor\r\n(qemu) ')
            command = b''
            while not command.endswith(b'\n'):
                data = conn.recv(4096)
                assert data, 'capture disconnected before its screendump command'
                command += data
            assert command == f'screendump {ppm}\n'.encode()
            ppm.write_bytes(ppm_frame)
            conn.sendall(b'\r\n(qemu) ')
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            peer = pool.submit(serve)
            captured = namespace['shot'](0, 'native monitor frame')
            peer.result(timeout=5)
    finally:
        server.close()
    assert Path(captured).read_bytes() == png_frame
    assert namespace['png_geometry'](captured) == (1, 1)
    assert not ppm.exists()
    assert namespace['vm_gone'] is None


@pytest.mark.parametrize('kind,expected', [
    ('browser', 'tuna-os/skipjack:gnome'),
    ('native-qemu', 'ghcr.io/tuna-os/skipjack:gnome'),
])
def test_display_reference_keeps_provenance_and_tracking_distinct(kind, expected):
    environment = {
        'TUNAOS_QUAL_EXECUTION_KIND': kind,
        'TUNAOS_QUAL_SOURCE_REF': 'tuna-os/skipjack:gnome' if kind == 'browser' else 'localhost/skipjack:gnome',
        'TUNAOS_QUAL_INSTALLER_IMAGE_REF': 'ghcr.io/tuna-os/skipjack:gnome',
    }
    original = environment.copy()
    assert driver.image_ref_from_environment(environment) == expected
    assert environment == original


@pytest.mark.parametrize('kind,missing', [
    ('browser', 'TUNAOS_QUAL_SOURCE_REF'),
    ('native-qemu', 'TUNAOS_QUAL_INSTALLER_IMAGE_REF'),
])
def test_display_reference_has_no_cross_producer_fallback(kind, missing):
    environment = {
        'TUNAOS_QUAL_EXECUTION_KIND': kind,
        'TUNAOS_QUAL_SOURCE_REF': 'localhost/skipjack:gnome',
        'TUNAOS_QUAL_INSTALLER_IMAGE_REF': 'ghcr.io/tuna-os/skipjack:gnome',
    }
    del environment[missing]
    with pytest.raises(driver.Unverified):
        driver.image_ref_from_environment(environment)


@pytest.mark.parametrize('kind', ['', 'native', 'unknown'])
def test_unknown_display_identity_producer_refused(kind):
    with pytest.raises(driver.Unverified):
        driver.image_ref_from_environment({
            'TUNAOS_QUAL_EXECUTION_KIND': kind,
            'TUNAOS_QUAL_SOURCE_REF': SOURCE_REF,
            'TUNAOS_QUAL_INSTALLER_IMAGE_REF': SOURCE_REF,
        })


@pytest.mark.parametrize('rgb,fill', [
    ((145, 65, 172), True),    # skipjack purple (fixture)
    ((53, 132, 228), True),    # blue accent switch (marlin run 42163966337)
    ((230, 97, 0), True),      # orange accent
    ((255, 199, 2), True),     # yellow accent
    ((152, 191, 239), False),  # marlin's disabled Next, measured beside its label
    ((242, 176, 127), False),  # orange at half opacity over white
    ((200, 160, 213), False),  # purple at half opacity over white
    ((250, 250, 251), False), ((220, 220, 221), False),
])
def test_accent_fill_is_hue_agnostic_and_rejects_washed_out_controls(rgb, fill):
    assert driver.accent_fill(rgb) is fill


def _tsv(*words):
    head = 'level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n'
    return head + ''.join(
        f'5\t1\t1\t1\t1\t{i}\t{left}\t{top}\t{width}\t{height}\t96\t{text}\n'
        for i, (text, left, top, width, height) in enumerate(words, 1))


def test_completion_rejoins_fragmented_title_and_media_from_their_bands(monkeypatch):
    # Run 42171054605 (bonito:gnome): full-frame OCR returned 'Bonito' | 'installed'
    # and 'Remove the installation ma' | 'and restart the computer.'; the page
    # also has a Show Log button left of Restart now.
    from types import SimpleNamespace
    screen = completion_screen(BARE_INSTRUCTION, (447, 358, 832, 372))
    screen.rows = [('Bonito', (525, 322, 608, 342)), ('installed', (642, 321, 754, 342)),
                   ('Remove the installation ma', (447, 358, 632, 369)),
                   ('and restart the computer.', (658, 358, 832, 372)),
                   ('Show Log', (524, 413, 594, 427))]
    screen.lines = [text for text, _ in screen.rows]
    screen.state = 'unknown'
    title = _tsv(('Bonito', 335, 10, 83, 20), ('is', 428, 10, 20, 20), ('installed', 452, 9, 112, 21))
    media = _tsv(*[(w, 257 + 48 * i, 6, 44, 14) for i, w in enumerate(BARE_INSTRUCTION.split())])
    crops, reads = [], iter([title, media, RESTART_TSV])

    def run(command, **options):
        if command[0] == 'convert' and any(str(a).startswith('900x') for a in command):
            crops.append(command[command.index('-crop') + 1])
        if command[0] == 'tesseract':
            return SimpleNamespace(stdout=next(reads))
        return SimpleNamespace(stdout='')
    monkeypatch.setattr(driver.subprocess, 'run', run)
    screen.verify_completion_panel()
    assert crops == ['900x38+190+312', '900x26+190+352']
    assert screen.state == 'done'
    assert screen.completion_markers[0] == 'Bonito is installed'


def _header_screen(monkeypatch, pill, wallpaper=False):
    from types import SimpleNamespace
    screen = object.__new__(driver.Screen)
    screen.width, screen.height = 1280, 800
    screen.path = Path('header.png')
    screen._pixels = None
    def rgb(x, y):
        if pill[0] <= x < pill[2] and pill[1] <= y < pill[3] and not 950 <= x < 966:
            return (237, 91, 0)             # accent fill, label pixels white
        if wallpaper and y >= 80 and (x * 7 + y * 13) % 31 == 0 and x > 1040:
            return (232, 120, 40)           # textured accent-like wallpaper
        return (250, 250, 251)
    screen.rgb = rgb
    tsv = ('level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n'
           '5\t1\t1\t1\t1\t1\t30\t20\t80\t45\t95\tNext\n')
    monkeypatch.setattr(driver.subprocess, 'run', lambda *a, **kw: SimpleNamespace(stdout=tsv))
    return screen


def test_header_next_is_recovered_from_a_solid_accent_pill(monkeypatch):
    # Run 42244397865 (grouper:gnome): white-on-orange Next is dropped by the
    # full-frame threshold; the pill is at (929,82)-(997,116).
    screen = _header_screen(monkeypatch, (929, 82, 997, 116), wallpaper=True)
    (text, box), = screen._header_next()
    assert text == 'Next'
    assert 929 <= box[0] < box[2] <= 997 and 82 <= box[1] < box[3] <= 116


@pytest.mark.parametrize('pill', [(700, 82, 1000, 116), (929, 82, 940, 116), (0, 0, 0, 0)])
def test_header_next_needs_one_pill_of_button_size(monkeypatch, pill):
    assert _header_screen(monkeypatch, pill)._header_next() == []


def _card_png(tmp_path, left, width=900):
    import shutil
    import subprocess as sp
    if not shutil.which('convert'):
        pytest.skip('ImageMagick convert is not installed')
    path = tmp_path / 'card.png'
    sp.run(['convert', '-size', '1280x800', 'xc:rgb(40,60,90)', '-fill', 'rgb(250,250,251)',
            '-draw', f'rectangle {left},76 {left+width-1},756', str(path)], check=True)
    return path


@pytest.mark.parametrize('left,shift', [(190, 0), (223, 33), (160, -30)])
def test_layout_shift_measures_the_installer_card_offset(tmp_path, left, shift):
    # Grouper's Ubuntu dock puts the 900px card at 223..1123 (run 42255160593).
    assert driver.layout_shift(_card_png(tmp_path, left), 1280) == shift


@pytest.mark.parametrize('left,width', [(223, 700), (223, 1000), (400, 900)])
def test_layout_shift_ignores_what_is_not_the_card(tmp_path, left, width):
    assert driver.layout_shift(_card_png(tmp_path, left, width), 1280) == 0


def test_clicks_are_moved_back_by_the_layout_shift():
    screen = FakeScreen('welcome')
    box, point = driver.control_target(screen, 'Install TunaOS')
    screen.layout_shift = 33
    shifted_box, shifted_point = driver.control_target(screen, 'Install TunaOS')
    assert shifted_box == box and shifted_point == [point[0] + 33, point[1]]


def test_completion_rereads_a_media_row_that_holds_the_sentence_but_is_not_it(monkeypatch):
    # Run 42296268212 (grouper:gnome): full-frame OCR returned
    # 'Remove the installation media and restart. the computer.' for the sentence.
    from types import SimpleNamespace
    screen = completion_screen('Remove the installation media and restart. the computer.', (447, 358, 832, 372))
    words = BARE_INSTRUCTION.split()
    media = ('level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n'
             + ''.join(f'5\t1\t1\t1\t1\t{i}\t{257 + 48 * (i - 1)}\t6\t44\t14\t95\t{w}\n' for i, w in enumerate(words, 1)))
    reads = iter([media, RESTART_TSV])
    monkeypatch.setattr(driver.subprocess, 'run',
                        lambda command, **kw: SimpleNamespace(stdout=next(reads) if command[0] == 'tesseract' else ''))
    screen.verify_completion_panel()
    assert screen.state == 'done'
    assert screen.completion_markers[1] == BARE_INSTRUCTION


def sailfin_welcome(action='Install Saitfin'):
    # Run 42776474139 (sailfin:gnome): heading read whole, small action
    # label misread ("l" as "t"). Geometry as measured on marlin/grouper.
    screen = object.__new__(driver.Screen)
    screen.width, screen.height = 1280, 800
    screen.rows = [('Welcome to Sailfin', [530, 320, 750, 344]),
                   (action, [410, 385, 500, 398]),
                   ('Installs to your internal disk.', [410, 405, 568, 418]),
                   ('Power Off', [382, 447, 478, 462])]
    screen.lines = [row[0] for row in screen.rows]
    screen.path = Path('sailfin-welcome.png')
    return screen


def crop_tsv(text, conf='96'):
    header = 'level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext'
    words, left, out = text.split(), 10, [header]
    for n, word in enumerate(words, 1):
        out.append(f'5\t1\t1\t1\t1\t{n}\t{left}\t8\t{len(word)*20}\t30\t{conf}\t{word}')
        left += len(word)*20 + 15
    return '\n'.join(out) + '\n'


def test_misread_action_label_is_reread_from_original_pixels(monkeypatch):
    screen = sailfin_welcome()
    calls = []
    def run(command, **options):
        calls.append(command)
        return type('Result', (), {'stdout': crop_tsv('Install Sailfin')})()
    monkeypatch.setattr(driver.subprocess, 'run', run)
    assert driver.welcome_action(screen) == 'Install Sailfin'
    assert calls[0][:5] == ['convert', 'sailfin-welcome.png', '-crop', '106x25+402+379', '+repage']
    assert calls[1][0] == 'tesseract' and calls[1][3:] == ['--psm', '7', 'tsv']
    # The click target is the same measured row.
    assert screen.box('Install Sailfin') == [410, 385, 500, 398]


@pytest.mark.parametrize('crop', ['Install Saitfin', 'Install Albacore', 'Install Sailfin Sailfin', 'uncertain'])
def test_reread_action_label_fails_closed(monkeypatch, crop):
    screen = sailfin_welcome()
    tsv = crop_tsv('Install Sailfin', conf='20') if crop == 'uncertain' else crop_tsv(crop)
    monkeypatch.setattr(driver.subprocess, 'run', lambda *a, **k: type('Result', (), {'stdout': tsv})())
    with pytest.raises(driver.Unverified):
        driver.welcome_action(screen)


@pytest.mark.parametrize('action', ['Install Albacore', 'Install Sailfish', 'Install Xyzwvut'])
def test_other_products_are_not_reread(monkeypatch, action):
    screen = sailfin_welcome(action)
    calls = []
    monkeypatch.setattr(driver.subprocess, 'run',
                        lambda command, **k: calls.append(command) or type('Result', (), {'stdout': crop_tsv('Install Sailfin')})())
    with pytest.raises(driver.Unverified):
        driver.welcome_action(screen)
    if action != 'Install Sailfish':
        assert not any(c[0] == 'convert' and '-resize' in c for c in calls)


def test_unix_rfb_drag_is_only_a_pressed_left_button(tmp_path):
    """Falsification: without the guard a drag without a click, or with a wheel button, is sent."""
    for options in ({'drag_to': (640, 55), 'click': False}, {'drag_to': (640, 55), 'buttons': 8}):
        with pytest.raises(driver.Unverified):
            driver.click_unix(tmp_path/'vnc.sock', 820, 747, 1280, 800, **options)
    with pytest.raises(driver.Unverified):
        driver.click_unix(tmp_path/'vnc.sock', 820, 747, 1280, 800, drag_to=(1280, 55))
