"""Candidate launch limits; checks are read-only and never resize a VM."""
import ctypes
import fcntl
import stat
import os
from pathlib import Path
import shutil
import signal
import subprocess
import time
import threading

GIB=1024**3
HARNESS_SECONDS=3300
TERM_SECONDS=15
COLLECT_SECONDS=120
# 8 GiB guest plus 4 GiB for host QEMU, OCR and filesystem work.
MIN_MEMORY=12*GIB
MIN_CPUS=4
# Producer: 3 payload copies at 4 GiB + two ISO copies at 10 GiB + 8 GiB scratch.
BUILD_DISK=40*GIB
# Consumer: archive12 + ISO10 + extracted payload10 + installed writes16 + scratch8.
CONSUMER_DISK=56*GIB


def check_kvm(*, geteuid=os.geteuid, opener=os.open, fstat=os.fstat,
              ioctl=fcntl.ioctl, close=os.close):
    """Open the existing device as the same root user that will run QEMU.

    GET_API_VERSION does not create a VM. No chmod, ACL or group changes.
    """
    if geteuid()!=0:
        raise ValueError('candidate KVM check must run as the QEMU root user')
    fd=opener('/dev/kvm',os.O_RDWR|os.O_CLOEXEC)
    try:
        if not stat.S_ISCHR(fstat(fd).st_mode) or ioctl(fd,0xAE00,0)!=12:
            raise ValueError('candidate requires an accessible KVM API version 12 device')
    finally:
        close(fd)


def preflight(path, kind, *, which=shutil.which, memory=None, cpus=None, free=None):
    if kind not in ('build','consumer','vm','tools'):
        raise ValueError('unknown preflight kind')
    if which('yq') is None:
        raise ValueError('candidate requires yq before publication resolution')
    if kind=='tools':
        return
    if memory is None:
        fields=dict(line.split(':',1) for line in Path('/proc/meminfo').read_text().splitlines())
        memory=int(fields['MemAvailable'].split()[0])*1024
    cpus=len(os.sched_getaffinity(0)) if cpus is None else cpus
    free=shutil.disk_usage(path).free if free is None else free
    disk=BUILD_DISK if kind=='build' else 24*GIB if kind=='vm' else CONSUMER_DISK
    if memory<MIN_MEMORY or cpus<MIN_CPUS or free<disk:
        raise ValueError(f'candidate resources insufficient: available memory={memory}, cpus={cpus}, disk={free}; required memory={MIN_MEMORY}, cpus={MIN_CPUS}, disk={disk}')


def direct_children():
    # /proc task/children requires CONFIG_CHECKPOINT_RESTORE; stat does not.
    result=[]
    with os.scandir('/proc') as entries:
        for index,entry in enumerate(entries):
            if index>=32768:
                raise ValueError('process enumeration exceeds candidate bound')
            if not entry.name.isdecimal():continue
            try:
                fields=Path(entry.path,'stat').read_text().rsplit(')',1)[1].split()
                if int(fields[1])==os.getpid():result.append(int(entry.name))
            except (FileNotFoundError,ProcessLookupError):pass
    return result


def supervised(command, *, env, cwd, check=False, seconds=HARNESS_SECONDS, grace=TERM_SECONDS):
    """Linux subreaper owns daemon descendants as well as the harness group.

    The runner has no concurrent child work. Refuse an existing child instead
    of risking another owner's process. Do not export child stdout or argv.
    """
    if direct_children():
        raise ValueError('candidate supervisor requires exclusive child ownership')
    libc=ctypes.CDLL(None,use_errno=True)
    process=None
    reader=None
    log_errors=[]
    code=124
    log_path=env.get('TUNAOS_XFCE_OUTPUT')
    def drain(stream):
        try:
            drain_log(stream)
        except (OSError,ValueError):
            log_errors.append(True)
        finally:
            stream.close()

    def drain_log(stream):
        # Keep the first bounded failure log privately; collector sanitizes it.
        limit=16*1024*1024
        with Path(log_path,'candidate-harness.log').open('xb') as output:
            remaining=limit-64
            truncated=False
            while chunk:=stream.read(65536):
                output.write(chunk[:remaining])
                if len(chunk)>remaining:truncated=True
                remaining=max(0,remaining-len(chunk))
            if truncated:output.write(b'\n[candidate harness log truncated at byte limit]\n')
    cancelled=False
    def cancel(signum, frame):
        # Defer cancellation until Popen has assigned ownership. Repeated TERM
        # during cleanup must not interrupt reaping or bypass its deadlines.
        nonlocal cancelled
        cancelled=True

    previous_term=signal.signal(signal.SIGTERM,cancel)
    try:
        if libc.prctl(36,1,0,0,0)!=0:  # PR_SET_CHILD_SUBREAPER
            raise OSError('candidate requires Linux child subreaper')
        process=subprocess.Popen(command,env=env,cwd=cwd,start_new_session=True,
                                 stdout=subprocess.PIPE if log_path else subprocess.DEVNULL,stderr=subprocess.STDOUT)
        if log_path:
            reader=threading.Thread(target=drain,args=(process.stdout,),daemon=True)
            reader.start()
        deadline=time.monotonic()+seconds
        while not cancelled:
            remaining=deadline-time.monotonic()
            if remaining<=0:break
            try:
                code=process.wait(timeout=min(.1,remaining))
                break
            except subprocess.TimeoutExpired:
                pass
    finally:
        try:
            if process is not None:
                try: os.killpg(process.pid,signal.SIGTERM)
                except ProcessLookupError: pass
                # Allow the shell's EXIT trap to flush and reap its owned VM.
                try: process.wait(timeout=grace)
                except subprocess.TimeoutExpired:
                    try: os.killpg(process.pid,signal.SIGKILL)
                    except ProcessLookupError: pass
                    process.wait(timeout=grace)
            # setsid/double-fork daemons get adopted here; reap each generation.
            deadline=time.monotonic()+grace
            while direct_children():
                for child in direct_children():
                    try: os.kill(int(child),signal.SIGKILL)
                    except ProcessLookupError: pass
                while True:
                    try: pid,_=os.waitpid(-1,os.WNOHANG)
                    except ChildProcessError: break
                    if pid==0: break
                if time.monotonic()>=deadline:
                    raise ValueError('candidate child cleanup exceeded deadline')
                time.sleep(.01)
            if reader is not None:
                reader.join(timeout=grace)
                if reader.is_alive():raise ValueError('candidate log drain exceeded deadline')
                if log_errors:raise ValueError('candidate private log retention failed')
        finally:
            libc.prctl(36,0,0,0,0)
            signal.signal(signal.SIGTERM,previous_term)
    if cancelled:code=128+signal.SIGTERM
    return subprocess.CompletedProcess(command,code)
