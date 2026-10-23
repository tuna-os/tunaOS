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
    def __init__(self, state, mode='plain', encrypted=False, tpm=False, valid=True):
        self.state = state
        self.mode, self.valid = mode, valid
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
    def summary_cards(self):
        if not self.valid:
            raise driver.Unverified('missing summary cards')
        return {
            'Disk': [('Disk', (14, 17, 102, 52)),
                     ('/dev/vda (64 GiB)', (13, 78, 313, 111))],
            'Encryption': [('Encryption', (15, 17, 234, 61)),
                           ('No encryption' if self.mode == 'plain' else 'Passphrase',
                            (15, 81, 255, 117))],
        }
    def switch(self, label):
        return self.encrypted if label == 'Encrypt this disk' else self.tpm
    def enabled(self, label):
        return True


def execute(tmp_path, screens, mode='plain', digest=driver.BUNDLE_DIGEST,
            pointer_error_at=None):
    events = []
    def capture(index, label):
        events.append(('capture', label))
        return str(tmp_path / f'{index}.png')
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
                      'test-only-passphrase', screen_factory=factory,
                      pointer=pointer, sleep=lambda _: None)
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


SUMMARY = json.loads((ROOT / 'tests/fixtures/gnome-installer/summary39891435048.json').read_text())


def captured_rows(words, strict=True):
    import csv
    import io
    fields = ('level', 'page_num', 'block_num', 'par_num', 'line_num',
              'word_num', 'left', 'top', 'width', 'height', 'conf', 'text')
    output = io.StringIO()
    writer = csv.DictWriter(output, fields, delimiter='\t', extrasaction='ignore')
    writer.writeheader()
    writer.writerows(words)
    return driver.ocr_rows(output.getvalue(), strict=strict)


def measured_cards(mode, key='gray_crop'):
    return {item['region'].title(): captured_rows(item['words'])[1]
            for item in SUMMARY[key] if item['mode'] == mode}


@pytest.mark.parametrize('mode', ['plain', 'luks'])
def test_retained_summary_ocr_exact_target_and_mode(mode):
    cards = measured_cards(mode)
    driver.verify_summary_cards(cards, mode)
    with pytest.raises(driver.Unverified):
        driver.verify_summary_cards(measured_cards(mode, 'threshold_crop'), mode)
    original = next(item for item in SUMMARY['full_frame'] if item['mode'] == mode)
    screen = object.__new__(driver.Screen)
    screen.words, screen.rows = captured_rows(original['words'])
    with pytest.raises(driver.Unverified):
        screen.box('Disk')  # Captured icon token shares the title's OCR line.


@pytest.mark.parametrize('mode', ['plain', 'luks'])
@pytest.mark.parametrize('change', [
    'wrong-device', 'wrong-capacity', 'wrong-unit', 'device-suffix',
    'wrong-encryption', 'duplicate-row', 'wrong-row', 'extra-token',
    'unassociated-value', 'out-of-bounds', 'wrong-title',
])
def test_summary_card_negatives_fail_closed(mode, change):
    cards = measured_cards(mode)
    disk, encryption = cards['Disk'], cards['Encryption']
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
        disk[0] = ('Other Disk', disk[0][1])
    with pytest.raises(driver.Unverified):
        driver.verify_summary_cards(cards, mode)


@pytest.mark.parametrize('mode', ['plain', 'luks'])
def test_summary_warning_and_full_frame_mode_must_agree(mode):
    screen = FakeScreen('summary', mode=mode)
    driver.verify_summary(screen, mode)
    for lines in (
        [line.replace('/dev/vda', '/dev/vdb') for line in screen.lines],
        screen.lines + ['Everything on /dev/vdb will be erased. This cannot be undone.'],
        [line for line in screen.lines if line not in ('No encryption', 'Passphrase')],
    ):
        changed = FakeScreen('summary', mode=mode)
        changed.lines = lines
        with pytest.raises(driver.Unverified):
            driver.verify_summary(changed, mode)


@pytest.mark.parametrize('change', [
    'missing-Disk', 'duplicate-Disk', 'misplaced-Disk',
    'missing-Encryption', 'duplicate-Encryption', 'misplaced-Encryption',
    'missing-heading', 'duplicate-heading', 'misplaced-heading', 'resolution', 'state',
])
def test_summary_anchors_reject_before_crop(monkeypatch, change):
    screen = object.__new__(driver.Screen)
    screen.width, screen.height, screen.state = 1280, 800, 'summary'
    source = SUMMARY['full_frame'][0]
    screen.words, screen.rows = captured_rows(source['words'])
    screen.rows.append(('Confirm installation', (510, 277, 770, 304)))
    if change.endswith('-Disk') or change.endswith('-Encryption'):
        operation, label = change.split('-')
        if operation == 'missing':
            screen.words = [word for word in screen.words if word['text'] != label]
        elif operation == 'duplicate':
            screen.words.append(next(word.copy() for word in screen.words if word['text'] == label))
        else:
            next(word for word in screen.words if word['text'] == label)['left'] = '500'
    elif change == 'missing-heading':
        screen.rows = [row for row in screen.rows if row[0] != 'Confirm installation']
    elif change == 'duplicate-heading':
        screen.rows.append(screen.rows[-1])
    elif change == 'misplaced-heading':
        screen.rows[-1] = ('Confirm installation', (510, 100, 770, 127))
    elif change == 'resolution':
        screen.width = 1920
    else:
        screen.state = 'overview'
    monkeypatch.setattr(driver.subprocess, 'run',
                        lambda *a, **k: pytest.fail('unverified layout must not invoke crop OCR'))
    with pytest.raises(driver.Unverified):
        screen.summary_cards()


def test_summary_ocr_uncertain_word_is_not_silently_dropped():
    word = dict(SUMMARY['gray_crop'][0]['words'][0], conf=39)
    with pytest.raises(driver.Unverified):
        captured_rows([word])


def test_retained_image_regression_is_explicit_ci_job():
    workflow = (ROOT / '.github/workflows/test.yml').read_text()
    job = workflow.split('  gnome-summary-ocr:', 1)[1].split('  unit-tests:', 1)[0]
    assert 'ubuntu-24.04' in job
    assert 'tesseract-ocr=5.3.4-1build5' in job
    assert 'imagemagick=8:6.9.12.98+dfsg1-5.2build2' in job
    assert 'python3 -m pytest -q tests/ocr/gnome_summary_capture.py' in job
    assert 'continue-on-error' not in job
    assert 'if:' not in job


BUTTON = json.loads((ROOT / 'tests/fixtures/gnome-installer/button39897665901.json').read_text())


@pytest.mark.parametrize('capture', BUTTON['inverted'])
def test_real_button_words_map_to_original_pixels(capture):
    _, rows = captured_rows(capture['words'])
    assert driver.install_box_from_rows(rows, 605, 579) == (618, 588, 662, 599)


@pytest.mark.parametrize('rows', [
    [], [('Install', (39, 27, 169, 60))]*2,
    [('Install now', (39, 27, 169, 60))],
    [('Cancel', (39, 27, 169, 60))],
    [('Install', (0, 27, 130, 60))],
    [('Install', (39, 0, 169, 33))],
    [('Install', (39, 27, 209, 60))],
    [('Install', (39, 27, 169, 90))],
])
def test_final_label_rejects_wrong_ambiguous_or_misplaced_text(rows):
    with pytest.raises(driver.Unverified):
        driver.install_box_from_rows(rows, 605, 579)


@pytest.mark.parametrize('change', [
    'unverified', 'state', 'resolution', 'heading', 'duplicate-heading', 'extra-install',
])
def test_final_control_requires_summary_and_unique_foreground(monkeypatch, change):
    screen = object.__new__(driver.Screen)
    screen.width, screen.height, screen.state = 1280, 800, 'summary'
    screen._summary_verified = True
    screen.rows = [('Confirm installation', (510, 277, 770, 304))]
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
    driver.verify_summary(screen, 'plain')
    assert screen._summary_verified
    screen.lines = [line.replace('/dev/vda', '/dev/vdb') for line in screen.lines]
    with pytest.raises(driver.Unverified):
        driver.verify_summary(screen, 'plain')
    assert not screen._summary_verified


def test_retained_button_failures_remain_negative_evidence():
    assert len(BUTTON['rejected']) == 4
    assert all(item['words'] == [] for item in BUTTON['rejected'])


PROGRESS_ROWS = [
    ('Almost ready...', (16, 30, 400, 81)),
    ('Do not power off the computer.', (18, 168, 543, 203)),
    ('0:00 elapsed', (18, 255, 237, 290)),
    ('1%', (2390, 87, 2469, 132)),
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
