"""Inert launch-boundary regression: #3965 pre-launch review, no guest execution.

Falsification: positional passphrases, missing deadlines/resources, raw exports,
and daemon children surviving a timeout must fail these tests.
"""
import ctypes
import hashlib
import importlib.util
from io import BytesIO
import json
import os
from pathlib import Path
import subprocess
import signal
import time
import sys

import pytest
import yaml

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from lib.luks_secret import read_passphrase, RedactedSerial
from lib.xfce_launch import preflight, supervised, GIB, HARNESS_SECONDS, TERM_SECONDS, COLLECT_SECONDS


def module(path):
    spec=importlib.util.spec_from_file_location(Path(path).stem,ROOT/path)
    result=importlib.util.module_from_spec(spec);spec.loader.exec_module(result)
    return result


@pytest.mark.parametrize('raw',[b'',b'a'*257,b'abc\nxyz',b'\xff',b'abc\x00'])
def test_invalid_secret_input_has_no_value_in_exception(raw):
    r,w=os.pipe()
    try:
        os.write(w,raw);os.close(w)
        with pytest.raises(ValueError):read_passphrase(r,.1)
    finally:os.close(r)


def test_missing_secret_input_times_out():
    r,w=os.pipe()
    try:
        with pytest.raises(ValueError,match='timed out'):read_passphrase(r,.01)
    finally:os.close(r);os.close(w)


@pytest.mark.parametrize('phase',['cold','warm'])
def test_actual_cold_warm_call_transports_secret_only_on_stdin(tmp_path,phase):
    # Execute the exact harness helper call against an inert Python replacement.
    shell=(ROOT/'scripts/iso-e2e.sh').read_text()
    end=shell.index(' || '+phase+'_unlock_rc=$?')
    start=shell.rindex('\t\tTUNAOS_LUKS_NO_POWEROFF=1',0,end)
    call=shell[start:end]
    helper=tmp_path/'python3'
    helper.write_text('#!'+sys.executable+'\n'+"import sys,os,json,hashlib\n"+
        f"sys.path.insert(0,{str(ROOT/'scripts')!r})\n"+
        "from lib.luks_secret import read_passphrase\n"+
        "value=read_passphrase()\n"+
        "assert all(key not in os.environ for key in ('TUNAOS_XFCE_PASSWORD','TUNAOS_WALKTHROUGH_LUKS_PASS','E2E_LUKS_PASS'))\n"+
        "json.dump(dict(argv=sys.argv[1:],digest=hashlib.sha256(value.encode()).hexdigest()),open(os.environ['RESULT'],'w'))\n")
    helper.chmod(0o700)
    secret='synthetic-passphrase-41279'
    script='\n'.join(['set -euo pipefail','unlock_bound=()',
        'mode=luks','fb_serial=owned.sock','fb_serial2=owned2.sock','MONITOR_SOCK=owned-monitor.sock',
        'SCRIPT_DIR=scripts','installed_log="$OUTPUT_DIR/cold.log"',call])
    env=dict(os.environ,PATH=str(tmp_path)+':'+os.environ['PATH'],OUTPUT_DIR=str(tmp_path),
        E2E_LUKS_PASS=secret,TUNAOS_XFCE_PASSWORD='account-password',TUNAOS_WALKTHROUGH_LUKS_PASS=secret,
        RESULT=str(tmp_path/'result.json'))
    result=subprocess.run(['bash','-c',script],env=env,capture_output=True,text=True,timeout=5)
    assert result.returncode==0,result.stderr
    value=json.loads((tmp_path/'result.json').read_text())
    assert '--passphrase-stdin' in value['argv'] and secret not in str(value['argv'])
    assert value['digest']==hashlib.sha256(secret.encode()).hexdigest()
    assert secret not in result.stdout+result.stderr
    assert all(secret not in p.read_text() for p in tmp_path.glob('*.log'))


@pytest.mark.parametrize('split',range(1,18))
def test_serial_echo_redacted_across_every_read_boundary(split):
    sink=BytesIO();writer=RedactedSerial('long-secret-value',sink)
    data=b'prefix long-secret-value suffix'
    writer.write(data[:split]);writer.write(data[split:]);writer.finish()
    assert sink.getvalue()==b'prefix [REDACTED] suffix'


def test_empty_secret_redactor_rejected():
    with pytest.raises(ValueError):RedactedSerial('',BytesIO())


@pytest.mark.parametrize('kind,floor',[('build',40),('consumer',56),('vm',24)])
def test_resource_floors_and_negative_controls(tmp_path,kind,floor):
    values=dict(which=lambda _: '/pinned/yq',memory=12*GIB,cpus=4,free=floor*GIB)
    preflight(tmp_path,kind,**values)
    for key,bad in [('memory',12*GIB-1),('cpus',3),('free',floor*GIB-1),('which',lambda _:None)]:
        with pytest.raises(ValueError):preflight(tmp_path,kind,**dict(values,**{key:bad}))


def test_tools_check_needs_no_vm_resources(tmp_path):
    preflight(tmp_path,'tools',which=lambda _: '/pinned/yq',memory=0,free=0,cpus=0)
    with pytest.raises(ValueError):preflight(tmp_path,'tools',which=lambda _:None)


def test_shared_deadline_clamps_all_phase_budgets():
    bound=module('scripts/candidate-bounded.py')
    assert bound.command(['610','python3','driver'],1000,100)[3]=='610'
    assert bound.command(['610','python3','driver'],300,100)[3]=='195'
    for deadline in (100,104,105):
        with pytest.raises(ValueError):bound.command(['610','driver'],deadline,100)
    assert HARNESS_SECONDS+4*TERM_SECONDS+COLLECT_SECONDS<60*60
    source=(ROOT/'scripts/iso-e2e.sh').read_text()
    assert 'candidate-bounded.py" 610' in source
    assert 'candidate-bounded.py" 300' in source
    assert 'candidate-bounded.py" 240' in source
    runner=(ROOT/'scripts/run-xfce-candidate.py').read_text()
    assert "TUNAOS_XFCE_DEADLINE=str(int(time.time())+3240)" in runner
    assert "'--cpus','4','--timeout','180'" in runner


def supervisor_code(tmp_path):
    # Discovery is restricted to PIDs recorded by this fixture, including its
    # daemon. Read only those /proc stat files, never enumerate host PIDs.
    return f"""import sys,os,signal
sys.path.insert(0,{str(ROOT/'scripts')!r})
from pathlib import Path
from lib import xfce_launch
owned=[]
original_popen=xfce_launch.subprocess.Popen
class FixturePopen(original_popen):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        owned.append(self.pid)
xfce_launch.subprocess.Popen=FixturePopen
def fixture_children():
    known=set(owned)
    for path in Path({str(tmp_path)!r}).glob('*.pid'):
        value=path.read_text()
        if value:known.add(int(value))
    children=[]
    for pid in known:
        try:
            fields=Path('/proc',str(pid),'stat').read_text().rsplit(')',1)[1].split()
            if int(fields[1])==os.getpid():children.append(pid)
        except FileNotFoundError:pass
    return children
xfce_launch.direct_children=fixture_children
from lib.xfce_launch import supervised
"""


@pytest.mark.parametrize('mode',['timeout','success','sigterm'])
def test_supervisor_reaps_owned_child_and_setsid_daemon(tmp_path,mode):
    # Only inert Python sleepers, in a separate supervisor process so no pytest
    # process can accidentally be adopted/reaped by the implementation.
    child=tmp_path/'child.py';pidfile=tmp_path/'owned.pid'
    childpid=tmp_path/'child.pid'
    child.write_text("import os,time,sys,signal\n"+
        f"open({str(childpid)!r},'w').write(str(os.getpid()))\n"+
        "signal.signal(signal.SIGTERM,signal.SIG_IGN)\n"+
        "if os.fork()==0:\n os.setsid()\n"+
        f" open({str(pidfile)!r},'w').write(str(os.getpid()))\n time.sleep(30)\n os._exit(0)\n"+
        ('time.sleep(.2)\n' if mode=='success' else 'time.sleep(30)\n'))
    seconds=.5 if mode=='timeout' else 30
    code=supervisor_code(tmp_path)+(
        "previous=signal.getsignal(signal.SIGTERM);"
        f"r=supervised([sys.executable,{str(child)!r}],env=dict(os.environ),cwd={str(tmp_path)!r},seconds={seconds},grace=.3);"
        "assert signal.getsignal(signal.SIGTERM) is previous;print(r.returncode)")
    # Adopt only for failure teardown: baseline SIGTERM exits without reaping.
    # pidfds retain exact identities, and waitpid below targets recorded PIDs.
    libc=ctypes.CDLL(None,use_errno=True)
    prior=ctypes.c_int()
    assert libc.prctl(37,ctypes.byref(prior),0,0,0)==0
    assert libc.prctl(36,1,0,0,0)==0
    handles={}
    try:
        # A sibling is owned by this test, not the supervisor, and must survive.
        with subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)']) as sibling:
            with subprocess.Popen([sys.executable,'-c',code],stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE,text=True) as process:
                try:
                    deadline=time.monotonic()+3
                    while len(handles)<2:
                        for path in (childpid,pidfile):
                            if path.exists() and path.read_text():
                                pid=int(path.read_text())
                                if pid not in handles:handles[pid]=os.pidfd_open(pid)
                        assert process.poll() is None
                        assert time.monotonic()<deadline,'fixture did not become ready'
                        if len(handles)<2:time.sleep(.01)
                    if mode=='sigterm':
                        process.send_signal(signal.SIGTERM)
                        # Repeated cancellation during TERM grace cannot bypass
                        # cleanup of the TERM-resistant owned children.
                        time.sleep(.05)
                        process.send_signal(signal.SIGTERM)
                    stdout,stderr=process.communicate(timeout=5)
                    assert process.returncode==0,stderr
                    assert stdout.strip()=={'timeout':'124','success':'0','sigterm':'143'}[mode]
                    assert sibling.poll() is None
                    for pid in handles:
                        assert not Path('/proc',str(pid)).exists()
                finally:
                    if process.poll() is None:process.kill()
                    process.wait(timeout=2)
                    for fd in handles.values():
                        try:signal.pidfd_send_signal(fd,signal.SIGKILL)
                        except ProcessLookupError:pass
                    for pid in handles:
                        try:os.waitpid(pid,0)
                        except ChildProcessError:pass
                        assert not Path('/proc',str(pid)).exists(),'owned fixture was not reaped'
                    sibling.terminate()
                    sibling.wait(timeout=2)
    finally:
        for fd in handles.values():os.close(fd)
        assert libc.prctl(36,prior.value,0,0,0)==0


def test_supervisor_restores_sigterm_handler_when_launch_fails(tmp_path):
    code=supervisor_code(tmp_path)+"""
signal.signal(signal.SIGTERM,signal.SIG_IGN)
try:
    supervised(['/nonexistent/fixture-command'],env=dict(os.environ),cwd='.',seconds=.1,grace=.1)
except FileNotFoundError:
    assert signal.getsignal(signal.SIGTERM) is signal.SIG_IGN
else:
    raise AssertionError('missing command succeeded')
"""
    result=subprocess.run([sys.executable,'-c',code],capture_output=True,text=True,timeout=3)
    assert result.returncode==0,result.stderr


def test_candidate_retention_redacts_and_rejects_private_paths(tmp_path):
    collector=module('scripts/collect-iso-diagnostics.py')
    secret='abcdef0123456789';user='tunasynthetic'
    (tmp_path/'serial.log').write_text('failure '+secret+' '+user+'\n'+ '\x1b[31m'.join(secret)+'\n'+'\r\n'.join(secret))
    (tmp_path/'candidate-report.json').write_text('{"status":"failed"}')
    (tmp_path/'xfce-login.png').write_bytes(secret.encode())
    wt=tmp_path/'walkthrough-plain';wt.mkdir()
    (wt/'safe-welcome.png').write_bytes(b'pre-identity-frame')
    (wt/'frame-010.png').write_bytes(secret.encode())
    (wt/'walkthrough-xfce.json').write_text('{"completed":false}')
    (tmp_path/'frontend-luks.json').symlink_to(tmp_path/'serial.log')
    collector.collect(tmp_path,candidate_secrets=[secret,user])
    dest=tmp_path/'strict-diagnostics'
    for path in dest.rglob('*'):
        if path.is_file():assert secret.encode() not in path.read_bytes() and user.encode() not in path.read_bytes()
    assert (dest/'walkthrough-plain/safe-welcome.png').read_bytes()==b'pre-identity-frame'
    assert not (dest/'xfce-login.png').exists()
    assert not (dest/'walkthrough-plain/frame-010.png').exists()
    assert not (dest/'frontend-luks.json').exists()
    assert '[REDACTED]' in (dest/'serial.log').read_text()


def test_retention_file_and_aggregate_limits(tmp_path,monkeypatch):
    collector=module('scripts/collect-iso-diagnostics.py')
    monkeypatch.setattr(collector,'MAX_FILE',8)
    monkeypatch.setattr(collector,'MAX_TOTAL',10)
    (tmp_path/'serial.log').write_bytes(b'X'*9)
    (tmp_path/'frontend-plain.json').write_bytes(b'123456')
    (tmp_path/'frontend-luks.json').write_bytes(b'123456')
    collector.collect(tmp_path,candidate_secrets=['secret'])
    report=json.loads((tmp_path/'strict-diagnostics/collection.json').read_text())
    assert report['bytes']==6 and report['files']==1 and report['skipped_count']==2


def test_all_candidate_jobs_bounded_and_exports_sanitized():
    live=yaml.safe_load((ROOT/'.github/workflows/live-iso-bootc.yml').read_text())
    consumer=yaml.safe_load((ROOT/'.github/workflows/iso-e2e.yml').read_text())
    for workflow,job in [(live,'preflight'),(live,'build'),(consumer,'generate-matrix'),(consumer,'e2e')]:
        assert 'timeout-minutes' in workflow['jobs'][job]
        assert "'xfce-candidate'" in workflow['concurrency']['group']
        assert workflow['concurrency']['cancel-in-progress']=='${{ !inputs.candidate_xfce }}'
    for workflow,job in [(live,'preflight'),(live,'build'),(consumer,'generate-matrix'),(consumer,'e2e')]:
        steps=workflow['jobs'][job]['steps']
        yq=next(i for i,s in enumerate(steps) if s.get('uses')=='./.github/actions/setup-yq')
        gate=next(i for i,s in enumerate(steps) if 'preflight-xfce-candidate.py' in s.get('run',''))
        assert yq<gate
    steps=consumer['jobs']['e2e']['steps']
    upload=next(s for s in steps if s.get('name')=='Upload artifacts')['with']['path']
    assert 'iso-e2e-out/xfce-candidate/strict-diagnostics/' in upload
    assert 'iso-e2e-out/xfce-candidate/*.json' not in upload
    assert 'iso-e2e-out/xfce-candidate/walkthrough-*/*.json' not in upload
    assert '&& !inputs.candidate_xfce' in next(s for s in steps if s.get('name')=='Stage bounded strict diagnostics')['if']


def test_supervisor_private_log_is_bounded_and_not_console_output(tmp_path):
    code=supervisor_code(tmp_path)+f"r=supervised([sys.executable,'-c',\"print('X'*(17*1024*1024))\"],env=dict(os.environ,TUNAOS_XFCE_OUTPUT={str(tmp_path)!r}),cwd={str(tmp_path)!r},seconds=3,grace=1);print(r.returncode)"
    result=subprocess.run([sys.executable,'-c',code],capture_output=True,text=True,timeout=8)
    assert result.returncode==0,result.stderr
    assert result.stdout.strip()=='0'
    log=(tmp_path/'candidate-harness.log').read_bytes()
    assert len(log)<=16*1024*1024
    assert log.endswith(b'[candidate harness log truncated at byte limit]\n')


def test_candidate_build_caps_fit_step_and_job():
    workflow=yaml.safe_load((ROOT/'.github/workflows/live-iso-bootc.yml').read_text())
    steps=workflow['jobs']['build']['steps']
    os_build=next(s for s in steps if s.get('name')=='Build OS image')
    live=next(s for s in steps if s.get('name')=='Build Live ISO')
    assert 'timeout-minutes' not in os_build and 'timeout-minutes' not in live
    assert 'bound=(timeout --signal=TERM --kill-after=120 2880)' in os_build['run']
    assert 'exec timeout --signal=TERM --kill-after=120 4980 bash -e \"$0\"' in live['run']
    assert 'TUNAOS_XFCE_BUILD_BOUNDED=1' in live['run']
    assert 2880+120==50*60 and 4980+120==85*60
    assert live['env']['TUNAOS_TACKLEBOX_TIMEOUT_SECONDS']=="${{ inputs.candidate_xfce && '2400' || '4800' }}"
    overlay=(ROOT/'scripts/build-native-live-overlay.sh').read_text()
    assert '[[ "${TUNAOS_XFCE_CANDIDATE:-0}" == 1 ]] && overlay_timeout=1800' in overlay
    assert 1800+120+2400+120 < 85*60
    assert 50+85+25==160


def test_positional_luks_input_is_rejected_before_socket_access():
    result=subprocess.run([sys.executable,str(ROOT/'scripts/luks-first-boot.py'),
        '/unopened-serial','/unopened-monitor','invalid-positional-input'],
        capture_output=True,text=True,timeout=2)
    assert result.returncode!=0
    assert 'use --passphrase-stdin' in result.stderr
    assert 'invalid-positional-input' not in result.stderr


@pytest.mark.parametrize('candidate',['0','1'])
def test_live_iso_timeout_reexec_runs_once_and_only_for_candidate(tmp_path,candidate):
    workflow=yaml.safe_load((ROOT/'.github/workflows/live-iso-bootc.yml').read_text())
    step=next(s for s in workflow['jobs']['build']['steps'] if s.get('name')=='Build Live ISO')
    prefix=step['run'].split('# Resolve operation inputs once.',1)[0]
    script=tmp_path/'action.sh';script.write_text(prefix+'echo reached\n')
    timeout=tmp_path/'timeout'
    timeout.write_text('#!/bin/bash\n[[ "$1 $2 $3" == "--signal=TERM --kill-after=120 4980" ]] || exit 98\necho bounded >> "$TRACE"\nshift 3\nexec "$@"\n')
    timeout.chmod(0o700)
    env=dict(os.environ,PATH=str(tmp_path)+':'+os.environ['PATH'],TUNAOS_XFCE_CANDIDATE=candidate,TRACE=str(tmp_path/'trace'))
    env.pop('TUNAOS_XFCE_BUILD_BOUNDED',None)
    result=subprocess.run(['bash','-e',str(script)],env=env,capture_output=True,text=True,timeout=3)
    assert result.returncode==0,result.stderr
    assert result.stdout.strip()=='reached'
    if candidate=='1':assert (tmp_path/'trace').read_text()=='bounded\n'
    else:assert not (tmp_path/'trace').exists()
