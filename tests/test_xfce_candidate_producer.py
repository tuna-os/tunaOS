"""Inert end-to-end command-boundary fixtures; never launch QEMU or a guest."""
import copy
import importlib.util
import json
import hashlib
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

ROOT=Path(__file__).parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from lib.xfce_candidate import APP, COMMIT, TRANSITIONS, validate_frontend
from lib.xfce_installer_driver import drive, Unverified


def module(path,name):
    spec=importlib.util.spec_from_file_location(name,ROOT/path)
    result=importlib.util.module_from_spec(spec);spec.loader.exec_module(result)
    return result

FIXTURE=module('tests/test_iso_desktop_expansion.py','expanded_fixture')
NATIVE=FIXTURE.NATIVE
RUNNER=module('scripts/run-xfce-candidate.py','candidate_runner')
PHASE=module('scripts/xfce-candidate-phase.py','candidate_phase')


def frontend():
    return dict(app=APP,commit=COMMIT,receipt_app=APP,receipt_revision=COMMIT,
                receipt_digest=COMMIT,architecture='x86_64',running_app=APP,
                host_fisherman_digest='sha256:'+'d'*64)


class Wizard:
    """The exact eight-page source order, driven only by pointer/key callbacks."""
    def __init__(self,user,mode,missing_identity=False):
        self.page=0;self.field=None;self.fields={};self.user=user;self.mode=mode
        self.controls={};self.missing_identity=missing_identity;self.progress_seen=False
        self.selected='none';self.keys_seen=[]
    @property
    def lines(self):
        return [['Welcome to TunaOS','Get started'],['What do you want to install?','Install TunaOS (this system)','available offline'],
            ['Where should TunaOS be installed?','/dev/vda','Everything will be erased'],['Disk encryption','No encryption'],
            ['Name this computer','Your account','Username','Full name','Password'],
            ['Confirm installation','/dev/vda will be erased'],['Installing TunaOS','Do not power off'],
            ['TunaOS is installed','Remove the installation media','Restart now']][self.page]
    @property
    def rows(self): return [(line,(10,10,50,30)) for line in self.lines]
    def contains(self,text): return any(text.lower() in line.lower() for line in self.lines)
    def box(self,label):
        if self.missing_identity and label=='Your account': raise Unverified('identity missing')
        if label=='Next' or label=='Install' or self.contains(label):
            y=30+len(self.controls)*20; self.controls[(20,y+5)]=label
            return (10,y,30,y+10)
        raise Unverified(label)
    def entry(self,label,labels):
        y=200+['Hostname','Username','Full name','Password','Confirm'].index(label)*20
        self.controls[(100,y)]=label
        self.controls[(150,y)]=label
        return (100,y)
    def pointer(self,path,x,y):
        label=self.controls.get((x,y))
        if label in ('Get started','Next','Install'):
            self.page+=1
        elif label=='No encryption': self.selected='none'
        elif label in ('Hostname','Username','Full name','Password','Confirm'):
            self.field=label
        elif label and '(this system)' in label:
            self.fields['source']='live'
    def keys(self,key):
        self.keys_seen.append(key)
        if key=='down': self.selected='luks-passphrase'
        elif key=='shift-tab': self.field='Passphrase'
        elif key=='ctrl-a': self.fields[self.field]=''
    def type(self,value): self.fields[self.field]=value
    def capture(self,*args):
        if self.page==6:
            if self.progress_seen:self.page=7
            self.progress_seen=True
        return 'fixture.png'
    def summary(self,label):
        return {'Target disk':'/dev/vda','Hostname':self.fields.get('Hostname'),
            'User':self.fields.get('Username'),'Image':'this live system','Filesystem':'ext4',
            'Encryption':'Passphrase' if self.selected=='luks-passphrase' else 'No encryption'}[label]


def gui(directory, mode, user, password='a'*32, luks='b'*32, missing=False):
    wizard=Wizard(user,mode,missing)
    code=drive(directory,mode,'fixture-vnc',wizard.capture,wizard.keys,wizard.type,
        'sha256:'+COMMIT,luks,user,password,screen_factory=lambda _:wizard,
        pointer=wizard.pointer,sleep=lambda _:None,clock=lambda:0)
    assert code==0
    assert wizard.fields['source']=='live'
    assert wizard.fields['Username']==user and wizard.fields['Password']==password
    if mode=='luks': assert wizard.fields['Confirm']==wizard.fields['Passphrase']==luks
    receipt=json.loads((directory/'walkthrough-xfce.json').read_text())
    assert receipt['transitions']==TRANSITIONS
    assert password not in json.dumps(receipt) and luks not in json.dumps(receipt)
    return receipt


@pytest.mark.parametrize('mode',['plain','luks'])
def test_real_page_order_includes_identity_and_live_source(tmp_path,mode):
    gui(tmp_path,mode,'tuna12345678')


def test_missing_identity_never_submits(tmp_path):
    with pytest.raises(Unverified): gui(tmp_path,'plain','tuna12345678',missing=True)
    assert json.loads((tmp_path/'walkthrough-xfce.json').read_text())['submitted'] is False


@pytest.mark.parametrize('field,value',[('commit','0'*64),('receipt_revision','0'*64),
    ('receipt_app','org.bootcinstaller.Installer'),('architecture','aarch64'),
    ('running_app',''),('host_fisherman_digest','unknown')])
def test_actual_frontend_identity_required(field,value):
    data=frontend();data[field]=value
    with pytest.raises(ValueError):validate_frontend(data)


@pytest.mark.parametrize('failure',[None,'source','backend','desktop','uid','boot_missing','boot_replay','account','frontend','interrupted'])
def test_producer_to_validator_at_harness_boundary(tmp_path,monkeypatch,failure):
    data=FIXTURE.evidence('xfce')
    iso=tmp_path/'grouper-xfce.iso';iso.write_bytes(b'inert ISO fixture; never booted')
    media=NATIVE.digest(iso)
    head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    binding=copy.deepcopy(data['artifact_binding'])
    binding.update(producer_sha=head,harness_sha=head,media_digest=media)
    for key in ('variant','flavor','platform','source_digest','storage_backend'):binding.pop(key,None)
    binding_file=tmp_path/'binding.json';binding_file.write_text(json.dumps(binding))
    inputs=dict(data['resolved_inputs'],media=media)
    for key,value in {'GITHUB_REPOSITORY':'tuna-os/tunaOS','GITHUB_RUN_ID':'123',
        'GITHUB_RUN_ATTEMPT':'1','TUNAOS_NATIVE_BINDING':str(binding_file),
        'TUNAOS_NATIVE_ARTIFACT_ID':'789','TUNAOS_NATIVE_ARCHIVE_DIGEST':binding['archive_digest'],
        'TUNAOS_NATIVE_SOURCE_SHA':head,'VARIANT':'grouper','FLAVOR':'xfce','TUNAOS_QUAL_PLATFORM':'linux/amd64',
        **{'TUNAOS_QUAL_'+key.upper()+'_DIGEST':value for key,value in inputs.items()}}.items():
        monkeypatch.setenv(key,value)
    qemu=tmp_path/'qemu';qemu.write_bytes(b'inert executable identity')
    monkeypatch.setattr(NATIVE.shutil,'which',lambda _:str(qemu))
    actual_check=NATIVE.subprocess.check_output
    monkeypatch.setattr(NATIVE.subprocess,'check_output',lambda command,**kw:
        'QEMU fixture version\n' if command[0]==str(qemu) else actual_check(command,**kw))
    output=tmp_path/'out'
    def execute(command,env,cwd,check):
        assert command[:2]==['bash',str(ROOT/'scripts/iso-e2e.sh')]
        assert env['TUNAOS_XFCE_CANDIDATE']=='1'
        assert '--strict-offline-gui' in command
        if failure=='interrupted':return SimpleNamespace(returncode=7)
        for mode in ('plain','luks'):
            frag=copy.deepcopy(data['observed'][mode])
            for key in ('gui','sessions','frontend_identity'):frag.pop(key,None)
            frag['target_imgref']='ghcr.io/tuna-os/grouper:xfce'
            (output/f'strict-qual-{mode}.json').write_text(json.dumps(frag))
            gui(output/f'walkthrough-{mode}',mode,env['TUNAOS_XFCE_USER'],env['TUNAOS_XFCE_PASSWORD'],env['TUNAOS_WALKTHROUGH_LUKS_PASS'])
            actual_frontend=frontend()
            if failure=='frontend':actual_frontend['commit']='0'*64
            (output/f'frontend-{mode}.json').write_text(json.dumps(actual_frontend))
            for phase in ('cold','warm'):
                observed=copy.deepcopy(data['observed'][mode]['sessions'][phase])
                observed['account_digest']='sha256:'+hashlib.sha256(env['TUNAOS_XFCE_USER'].encode()).hexdigest()
                if mode=='luks' and phase=='warm':
                    if failure=='source':observed['source_digest']='sha256:'+'0'*64
                    if failure=='backend':observed['storage_backend']='native-composefs'
                    if failure=='desktop':observed['desktop']='gnome'
                    if failure=='uid':observed['uid']=0
                    if failure=='boot_missing':observed.pop('boot_id')
                    if failure=='boot_replay':observed['boot_id']=data['observed']['plain']['sessions']['cold']['boot_id']
                    if failure=='account':observed['account_digest']='sha256:'+'0'*64
                (output/f'session-{mode}-{phase}.json').write_text(json.dumps(observed))
        args=SimpleNamespace(command='emit-candidate',binding=binding_file,directory=output,
            output=output/'qualification-evidence.json',repository='tuna-os/tunaOS',run_id=123,attempt=1,
            artifact_id=789,archive_digest=binding['archive_digest'],source_sha=head,qemu=str(qemu),
            variant='grouper',flavor='xfce',platform='linux/amd64',cpu_model='host',**inputs)
        NATIVE.emit(args)
        return SimpleNamespace(returncode=0)
    if failure:
        with pytest.raises(ValueError):RUNNER.run(SimpleNamespace(iso=iso,output=output),execute)
        assert json.loads((output/'candidate-report.json').read_text())['status']=='failed'
    else:
        assert RUNNER.run(SimpleNamespace(iso=iso,output=output),execute)==0
        receipt=NATIVE.load(output/'qualification-evidence.json')
        NATIVE.validate(receipt)
        assert receipt['artifact_binding']==binding
        assert json.loads((output/'candidate-report.json').read_text())['qualified'] is False


def test_live_probe_is_unprivileged(tmp_path):
    class Guest:
        def __init__(self,*args):assert args[1:]==('liveuser','')
        def execute(self,source,sudo):
            assert sudo is False and 'runuser' not in source
            return frontend()
        def close(self):pass
    result=PHASE.collect(SimpleNamespace(action='live',console=tmp_path/'owned.sock'),console_factory=Guest)
    assert result['commit']==COMMIT


def test_candidate_preflight_cannot_claim_nvidia_or_all_cells():
    from contracts.iso_qualification import manifest,select
    doc=manifest()
    assert select(doc,['grouper:xfce:linux/amd64'],1,True)['result']=='unrun'
    for targets in (['grouper:xfce-nvidia:linux/amd64'],['grouper:xfce:linux/amd64','skipjack:gnome:linux/amd64']):
        with pytest.raises(ValueError):select(doc,targets,1,True)


@pytest.mark.parametrize('fault',[None,'wrong_login','interrupted','echo_only'])
def test_authenticated_console_framing_and_no_password_in_command(monkeypatch,fault):
    import base64
    import re
    import zlib
    from lib import guest_console
    class Wire:
        def __init__(self):self.pending=[];self.sent=[];self.closed=False
        def settimeout(self,_):pass
        def connect(self,path):assert path=='owned-qemu.sock'
        def sendall(self,value):
            self.sent.append(value)
            if value==b'\r':self.pending.append(b'guest login: ')
            elif value==b'tuna12345678\r':self.pending.append(b'Password: ')
            elif value==b'secret\r':self.pending.append(b'\x1b[?2004huser$ ')
            elif value.startswith(b'python3 -c'):
                encoded=re.search(rb'b64decode\(.*?([A-Za-z0-9+/=]{50,})',value).group(1)
                source=zlib.decompress(base64.b64decode(encoded)).decode()
                start=re.search("BEGIN_[a-f0-9]{32}",source).group()
                end=re.search("END_[a-f0-9]{32}",source).group()
                result='wronguser' if fault=='wrong_login' else 'tuna12345678'
                if 'answer' in source:result={'answer':42}
                response=start+'\r\n'+json.dumps(result)+'\r\n'+end+'\r\n'
                self.pending.append(value if fault=='echo_only' else response.encode())
            elif value==b'exit\r':pass
            else:raise AssertionError('unexpected console input')
        def recv(self,_):
            if fault=='interrupted':return b''
            return self.pending.pop(0) if self.pending else b''
        def close(self):self.closed=True
    wire=Wire();monkeypatch.setattr(guest_console.socket,'socket',lambda *args:wire)
    if fault:
        with pytest.raises(ValueError):guest_console.Console('owned-qemu.sock','tuna12345678','secret')
    else:
        console=guest_console.Console('owned-qemu.sock','tuna12345678','secret')
        assert console.execute("print(json.dumps({'answer':42}))",sudo=False)=={'answer':42}
        console.close()
    assert all(b'secret' not in line for line in wire.sent if b'python3' in line)


def test_interrupted_gui_login_never_yields_session_receipt(tmp_path,monkeypatch):
    args=SimpleNamespace(action='session',console=tmp_path/'owned.sock',mode='plain',phase='cold',
        monitor=tmp_path/'monitor',vnc=tmp_path/'vnc',directory=tmp_path,boot_log=tmp_path/'serial')
    args.boot_log.write_text('TUNAOS_DESKTOP_CONTRACT_OK desktop=xfce experience=tunaos/xfce\n')
    monkeypatch.setenv('TUNAOS_XFCE_USER','tuna12345678');monkeypatch.setenv('TUNAOS_XFCE_PASSWORD','a'*32)
    class Guest:
        def __init__(self,*args):pass
        def execute(self,source,sudo):assert sudo is False;return {'pending':True}
        def close(self):pass
    screen=SimpleNamespace(box=lambda _: (0,0,10,10))
    monkeypatch.setattr(PHASE,'click_unix',lambda *args:None)
    monkeypatch.setattr(PHASE,'type_text',lambda *args:None)
    monkeypatch.setattr(PHASE,'monitor',lambda *args:None)
    with pytest.raises(ValueError,match='did not complete'):
        PHASE.collect(args,console_factory=Guest,capture=lambda *args:screen,sleep=lambda _:None)


@pytest.mark.parametrize('failed',[False,True])
def test_hmp_waits_for_fragmented_completion_and_late_error(monkeypatch,failed):
    from lib import qemu_monitor
    class Wire:
        def __init__(self): self.parts=[b'QEMU monitor\r\n(qe',b'mu) '];self.read=0
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def settimeout(self,_):pass
        def connect(self,_):pass
        def recv(self,_): self.read+=1;return self.parts.pop(0)
        def sendall(self,value):
            assert value==b'screendump fixture.ppm\n'
            self.parts=[b'screendump fixture.ppm\r\n',b'Error: capture failed\r\n' if failed else b'',b'(qe',b'mu) ']
            if not failed:self.parts.remove(b'')
    wire=Wire();monkeypatch.setattr(qemu_monitor.socket,'socket',lambda *args:wire)
    if failed:
        with pytest.raises(ValueError,match='command failed'):qemu_monitor.command('fixture.sock','screendump fixture.ppm')
    else:
        qemu_monitor.command('fixture.sock','screendump fixture.ppm')
    assert wire.parts==[] and wire.read>=5
