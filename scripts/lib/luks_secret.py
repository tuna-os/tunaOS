"""Bounded private stdin transport; never include input bytes in errors."""
import os
import select
import time


def read_passphrase(fd=0, timeout=5):
    deadline=time.monotonic()+timeout
    data=bytearray()
    while len(data)<=256:
        remaining=deadline-time.monotonic()
        if remaining<=0 or not select.select([fd],[],[],remaining)[0]:
            raise ValueError('passphrase input timed out')
        chunk=os.read(fd,257-len(data))
        if not chunk:
            break
        data.extend(chunk)
        if b'\n' in data:
            break
    if data.endswith(b'\n'):
        data.pop()
    if not 1<=len(data)<=256 or any(c<32 or c==127 for c in data):
        raise ValueError('invalid passphrase input')
    try:
        return data.decode('utf-8')
    except UnicodeError:
        raise ValueError('invalid passphrase encoding') from None


class RedactedSerial:
    """Keep a match-width suffix so split serial reads cannot expose a secret."""
    def __init__(self, secret, output):
        if not secret:
            raise ValueError('empty passphrase cannot be redacted')
        self.secret=secret.encode()
        self.output=output
        self.pending=b''

    def write(self, data):
        self.pending+=data
        # Emit complete matches atomically, retain any possible partial match.
        while self.pending:
            index=self.pending.find(self.secret)
            if index>=0:
                self.output.write(self.pending[:index]+b'[REDACTED]')
                self.pending=self.pending[index+len(self.secret):]
            else:
                keep=0
                for size in range(1,min(len(self.secret),len(self.pending)+1)):
                    if self.pending.endswith(self.secret[:size]):keep=size
                end=len(self.pending)-keep
                self.output.write(self.pending[:end])
                self.pending=self.pending[end:]
                break

    def finish(self):
        if self.pending:
            self.output.write(b'[REDACTED-PARTIAL]')
            self.pending=b''
