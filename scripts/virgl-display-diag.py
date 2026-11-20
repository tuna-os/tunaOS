#!/usr/bin/env python3
"""DIAGNOSTIC (tunaOS#4768): watch the guest display from the host side.

Holds one shared RFB client on QEMU's VNC unix socket for the whole live leg
and keeps an incremental FramebufferUpdateRequest outstanding, so QEMU sends
an update whenever the presented frame changes (QEMU compares 16-pixel
blocks, so the pixel count is real change, not flush traffic). Every
--interval seconds it logs how many updates and changed pixels arrived, and
the CPU time and state of every QEMU thread, so a freeze shows up as the time
updates stop and what QEMU was doing then.

Holding a client also tests the hypothesis that egl-headless only presents
while a VNC client is attached. Read-only: no pointer or key events.
"""
import argparse
import os
import select
import signal
import socket
import struct
import sys
import time

running = True


def stop(*_):
    global running
    running = False


def recv_exact(sock, n):
    buf = b''
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError('VNC server closed the connection')
        buf += chunk
    return buf


def handshake(sock):
    if recv_exact(sock, 12) != b'RFB 003.008\n':
        raise ConnectionError('not an RFB 3.8 server')
    sock.sendall(b'RFB 003.008\n')
    count = recv_exact(sock, 1)[0]
    if count == 0:
        raise ConnectionError('server refused: no security types')
    if 1 not in recv_exact(sock, count):
        raise ConnectionError('server requires authentication')
    sock.sendall(b'\x01')
    if struct.unpack('!I', recv_exact(sock, 4))[0] != 0:
        raise ConnectionError('security handshake failed')
    sock.sendall(b'\x01')  # shared: never disconnect the harness's own clients
    width, height = struct.unpack('!HH', recv_exact(sock, 4))
    bpp = recv_exact(sock, 16)[0]
    recv_exact(sock, struct.unpack('!I', recv_exact(sock, 4))[0])
    # Raw plus the DesktopSize pseudo-encoding (-223).
    sock.sendall(struct.pack('!BBHii', 2, 0, 2, 0, -223))
    return width, height, bpp // 8


def request(sock, width, height, incremental):
    sock.sendall(struct.pack('!BBHHHH', 3, incremental, 0, 0, width, height))


def threads(pid):
    out = {}
    try:
        tids = os.listdir(f'/proc/{pid}/task')
    except OSError:
        return None
    for tid in tids:
        try:
            with open(f'/proc/{pid}/task/{tid}/stat') as f:
                stat = f.read()
            with open(f'/proc/{pid}/task/{tid}/wchan') as f:
                wchan = f.read().strip() or '-'
        except OSError:
            continue
        comm = stat[stat.index('(') + 1:stat.rindex(')')]
        fields = stat[stat.rindex(')') + 2:].split()
        out[tid] = (comm, fields[0], int(fields[11]) + int(fields[12]), wchan)
    return out


def qemu_pid(pidfile):
    try:
        with open(pidfile) as f:
            pid = int(f.read().strip())
        os.kill(pid, 0)
        return pid
    except (OSError, ValueError):
        return None

def virtqueues(path):
    """virtio-gpu ctrl (0) and cursor (1) queue indexes over a dedicated QMP socket."""
    import json
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as qmp:
            qmp.settimeout(3)
            qmp.connect(path)
            reader = qmp.makefile('rb')

            def call(cmd, **arguments):
                qmp.sendall(json.dumps({'execute': cmd, 'arguments': arguments}).encode() + b'\n')
                while True:
                    reply = json.loads(reader.readline())
                    if 'return' in reply or 'error' in reply:
                        return reply

            json.loads(reader.readline())  # greeting
            call('qmp_capabilities')
            devices = call('x-query-virtio').get('return', [])
            gpu = next((d['path'] for d in devices if d.get('name') == 'virtio-gpu'), None)
            if gpu is None:
                return f'no-virtio-gpu({devices})'
            out = []
            for queue in (0, 1):
                st = call('x-query-virtio-queue-status', path=gpu, queue=queue).get('return', {})
                out.append(f"q{queue}:avail={st.get('last-avail-idx')}/{st.get('shadow-avail-idx')}"
                           f":used={st.get('used-idx')}:inuse={st.get('inuse')}")
            return ';'.join(out)
    except (OSError, ValueError) as exc:
        return f'qmp-error({exc})'



def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--vnc', required=True)
    ap.add_argument('--pidfile', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--interval', type=float, default=10)
    ap.add_argument('--qmp', help='a QMP socket of its own, for virtio-gpu queue state')
    args = ap.parse_args()
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    hz = os.sysconf('SC_CLK_TCK')
    log = open(args.out, 'a', buffering=1)

    def emit(msg):
        log.write(f'{time.strftime("%H:%M:%S", time.gmtime())} {msg}\n')

    started = time.monotonic()
    sock = None
    width = height = bpp = 0
    pending = b''
    updates = rects = pixels = 0
    last_update = None
    next_report = started + args.interval
    last_request = 0.0
    prev_threads = {}
    pid = None
    while running:
        now = time.monotonic()
        pid = qemu_pid(args.pidfile) or pid
        if pid and not os.path.exists(f'/proc/{pid}'):
            emit('qemu gone; stopping')
            break
        if sock is None:
            try:
                sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                sock.settimeout(10)
                sock.connect(args.vnc)
                width, height, bpp = handshake(sock)
                sock.settimeout(None)
                request(sock, width, height, 0)
                last_request = now
                pending = b''
                emit(f'connected {width}x{height} {bpp * 8}bpp')
            except OSError as exc:
                emit(f'connect failed: {exc}')
                sock.close()
                sock = None
                time.sleep(2)
                continue
        try:
            ready, _, _ = select.select([sock], [], [], 0.5)
            if ready:
                chunk = sock.recv(1 << 20)
                if not chunk:
                    raise ConnectionError('server closed the connection')
                pending += chunk
                while True:
                    parsed = parse(pending, bpp)
                    if parsed is None:
                        break
                    consumed, kind, info = parsed
                    pending = pending[consumed:]
                    if kind == 'update':
                        updates += 1
                        rects += len(info)
                        for rx, ry, rw, rh, enc in info:
                            if enc == -223:
                                width, height = rw, rh
                                emit(f'desktop resize {rw}x{rh}')
                            else:
                                pixels += rw * rh
                        last_update = time.monotonic()
                        request(sock, width, height, 1)
                        last_request = time.monotonic()
            if time.monotonic() - last_request > 1:
                # Keep a request outstanding even if one was answered empty.
                request(sock, width, height, 1)
                last_request = time.monotonic()
        except (OSError, ConnectionError) as exc:
            emit(f'disconnected: {exc}')
            sock.close()
            sock = None
            continue
        if time.monotonic() >= next_report:
            idle = f'{time.monotonic() - last_update:.0f}s' if last_update else 'never'
            line = f'+{time.monotonic() - started:.0f}s updates={updates} rects={rects} pixels={pixels} since_last_update={idle}'
            cur = threads(pid) if pid else None
            if cur:
                parts = []
                for tid, (comm, state, ticks, wchan) in sorted(cur.items(), key=lambda kv: int(kv[0])):
                    delta = ticks - prev_threads.get(tid, (None, None, ticks))[2]
                    parts.append(f'{comm}:{state}:{delta * 100 // (hz * args.interval):.0f}%:{wchan}')
                prev_threads = cur
                line += ' threads=' + ','.join(parts)
            if args.qmp:
                line += ' vq=' + virtqueues(args.qmp)
            emit(line)
            updates = rects = pixels = 0
            next_report += args.interval
    if sock is not None:
        sock.close()
    return 0


def parse(buf, bpp):
    """Return (consumed, kind, info) for one complete server message, or None."""
    if not buf:
        return None
    kind = buf[0]
    if kind == 0:
        if len(buf) < 4:
            return None
        count = struct.unpack('!H', buf[2:4])[0]
        pos, info = 4, []
        for _ in range(count):
            if len(buf) < pos + 12:
                return None
            x, y, w, h, enc = struct.unpack('!HHHHi', buf[pos:pos + 12])
            pos += 12
            if enc == 0:
                pos += w * h * bpp
                if len(buf) < pos:
                    return None
            elif enc != -223:
                raise ConnectionError(f'unexpected encoding {enc}')
            info.append((x, y, w, h, enc))
        return pos, 'update', info
    if kind == 1:
        if len(buf) < 6:
            return None
        n = struct.unpack('!H', buf[4:6])[0]
        return (6 + 6 * n, 'colormap', None) if len(buf) >= 6 + 6 * n else None
    if kind == 2:
        return 1, 'bell', None
    if kind == 3:
        if len(buf) < 8:
            return None
        n = struct.unpack('!I', buf[4:8])[0]
        return (8 + n, 'cut', None) if len(buf) >= 8 + n else None
    raise ConnectionError(f'unexpected server message {kind}')


if __name__ == '__main__':
    sys.exit(main())
