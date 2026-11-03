"""Bounded HMP exchange; command echo is not command completion."""
import socket


def command(path, value):
    if '\n' in value or '\r' in value:
        raise ValueError('monitor command must be one line')
    with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as sock:
        sock.settimeout(10);sock.connect(str(path))
        def read_prompt():
            data=b''
            while not data.rstrip().endswith(b'(qemu)'):
                chunk=sock.recv(65536)
                if not chunk:
                    raise ValueError('monitor disconnected before completion')
                data+=chunk
                if len(data)>1024*1024:
                    raise ValueError('monitor response exceeds bound')
            return data
        read_prompt()
        sock.sendall(value.encode()+b'\n')
        result=read_prompt()
        if b'Error' in result or b'unknown command' in result.lower():
            raise ValueError('monitor command failed')
        return result
