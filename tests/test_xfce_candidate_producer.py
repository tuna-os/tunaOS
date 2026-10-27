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
                host_fisherman_matches_deployment=True,host_fisherman_digest='sha256:'+'d'*64,media_input=dict(schemaVersion=1,platform='linux/amd64',image='ghcr.io/tuna-os/bonito:xfce',targetImgref='ghcr.io/tuna-os/bonito:xfce',platformManifestDigest='sha256:'+'a'*64,ociLayoutPath='/usr/lib/tunaos/xfce-candidate-oci'))


class Wizard:
    """The exact eight-page source order, driven only by pointer/key callbacks."""
    def __init__(self,user,mode,missing_identity=False):
        self.width=1280;self.height=800
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
    def pointer(self,path,x,y,width,height):
        assert (width,height)==(1280,800)
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
    iso=tmp_path/'bonito-xfce.iso';iso.write_bytes(b'inert ISO fixture; never booted')
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
        'TUNAOS_NATIVE_SOURCE_SHA':head,'VARIANT':'bonito','FLAVOR':'xfce','TUNAOS_QUAL_PLATFORM':'linux/amd64',
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
            frag['target_imgref']='ghcr.io/tuna-os/bonito:xfce'
            (output/f'strict-qual-{mode}.json').write_text(json.dumps(frag))
            gui(output/f'walkthrough-{mode}',mode,env['TUNAOS_XFCE_USER'],env['TUNAOS_XFCE_PASSWORD'],env['TUNAOS_WALKTHROUGH_LUKS_PASS'])
            actual_frontend=frontend()
            actual_frontend['media_input']['platformManifestDigest']=inputs['source']
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
            variant='bonito',flavor='xfce',platform='linux/amd64',cpu_model='host',**inputs)
        NATIVE.emit(args)
        return SimpleNamespace(returncode=0)
    if failure:
        with pytest.raises(ValueError):RUNNER.run(SimpleNamespace(iso=iso,output=output),execute,check_resources=lambda *args:None,check_acceleration=lambda:None)
        assert json.loads((output/'candidate-report.json').read_text())['status']=='failed'
    else:
        assert RUNNER.run(SimpleNamespace(iso=iso,output=output),execute,check_resources=lambda *args:None,check_acceleration=lambda:None)==0
        receipt=NATIVE.load(output/'qualification-evidence.json')
        NATIVE.validate(receipt)
        assert receipt['artifact_binding']==binding
        assert json.loads((output/'candidate-report.json').read_text())['qualified'] is False


def test_live_probe_is_unprivileged(tmp_path,monkeypatch):
    class Guest:
        def __init__(self,*args):assert args[1:]==('liveuser','')
        def execute(self,source,sudo):
            assert sudo is False and 'runuser' not in source
            return frontend()
        def close(self):pass
    monkeypatch.setenv('TUNAOS_QUAL_SOURCE_DIGEST','sha256:'+'a'*64)
    result=PHASE.collect(SimpleNamespace(action='live',console=tmp_path/'owned.sock'),console_factory=Guest)
    assert result['commit']==COMMIT


def test_candidate_preflight_cannot_claim_nvidia_or_all_cells():
    from contracts.iso_qualification import manifest,select
    doc=manifest()
    assert select(doc,['bonito:xfce:linux/amd64'],1,True)['result']=='unrun'
    for targets in (['grouper:xfce:linux/amd64'],['albacore:xfce:linux/amd64'],['bonito:xfce-nvidia:linux/amd64'],['bonito:xfce:linux/amd64','skipjack:gnome:linux/amd64']):
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
    screen=SimpleNamespace(width=1280,height=800,box=lambda _: (0,0,10,10))
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


@pytest.mark.parametrize('target',['ghcr.io/tuna-os/bonito:xfce','quay.io/review-fixture/bonito:xfce'])
@pytest.mark.parametrize('fault',[None,'digest','layer','architecture','missing','index_arch','empty_layers','size','media_type','schema','source_leak'])
def test_native_payload_descriptor_checks_actual_bytes(tmp_path,fault,target):
    adapter=module('live-iso/common/src/xfce-media-input.py','media_adapter')
    layout=tmp_path/'oci'; blobs=layout/'blobs/sha256';blobs.mkdir(parents=True)
    def put(data):
        value=data if isinstance(data,bytes) else json.dumps(data).encode()
        digest='sha256:'+hashlib.sha256(value).hexdigest()
        (blobs/digest[7:]).write_bytes(value)
        return dict(digest=digest,size=len(value))
    config=put(dict(architecture='arm64' if fault=='architecture' else 'amd64',os='linux'))
    layer=put(b'fixture layer, no image or guest execution')
    manifest=put(dict(schemaVersion=2,config=config,layers=[] if fault=='empty_layers' else [layer]))
    manifest['mediaType']='invalid' if fault=='media_type' else 'application/vnd.oci.image.manifest.v1+json'
    if fault=='index_arch':manifest['platform']=dict(os='linux',architecture='arm64')
    if fault=='size':manifest['size']=True
    (layout/'oci-layout').write_text(json.dumps(dict(imageLayoutVersion='1.0.0')))
    (layout/'index.json').write_text(json.dumps(dict(schemaVersion=1 if fault=='schema' else 2,manifests=[manifest])))
    if fault=='source_leak':(layout/'repository.py').write_text('unrelated source')
    if fault=='layer':(blobs/layer['digest'][7:]).write_bytes(b'corrupt')
    if fault=='missing':(blobs/layer['digest'][7:]).unlink()
    expected='sha256:'+'0'*64 if fault=='digest' else manifest['digest']
    if fault:
        with pytest.raises(ValueError):adapter.descriptor(layout,expected,target)
    else:
        descriptor=adapter.descriptor(layout,expected,target)
        assert descriptor['platformManifestDigest']==expected
        assert descriptor['targetImgref']==target and descriptor['image']==target
        assert descriptor['ociLayoutPath']==adapter.LAYOUT
        assert 'composeFsBackend' not in descriptor


def test_candidate_producer_retains_ostree_gate_and_isolates_overlay():
    producer=(ROOT/'.github/workflows/live-iso-bootc.yml').read_text()
    adapter=(ROOT/'scripts/build-iso-tacklebox.sh').read_text()
    overlay=(ROOT/'scripts/build-native-live-overlay.sh').read_text()
    custom=(ROOT/'live-iso/common/src/customize-live.sh').read_text()
    assert 'native qualification needs the OSTree offline store' in producer
    assert '"$payload_digest" == "$TUNA_LIVE_BASE_DIGEST"' in producer
    assert "inputs.candidate_xfce && '1' || '0'" in producer
    assert 'export TUNAOS_XFCE_CANDIDATE=0' in overlay
    assert 'bonito:xfce:linux/amd64' in adapter
    assert 'skopeo copy --preserve-digests' in adapter
    assert 'containers-storage:${SOURCE_IMAGE_REF}@${TUNA_LIVE_BASE_DIGEST}' in adapter
    assert adapter.index('skopeo copy --preserve-digests') < adapter.index('export TUNAOS_XFCE_CANDIDATE')
    assert 'xfce-media-input.py' in adapter and 'xfce-media-input.py' in custom
    assert '/etc/bootc-installer/media-input.json' in custom
    assert 'TUNAOS_XFCE_CANDIDATE:-0}" != 1' in custom


@pytest.mark.parametrize('field,value',[('platformManifestDigest','sha256:'+'0'*64),
    ('targetImgref','ghcr.io/tuna-os/grouper:xfce'),('ociLayoutPath','/tmp/unbound'),('platform','linux/arm64')])
def test_live_source_descriptor_mismatch_fails(tmp_path,monkeypatch,field,value):
    monkeypatch.setenv('TUNAOS_QUAL_SOURCE_DIGEST','sha256:'+'a'*64)
    class Guest:
        def __init__(self,*args):pass
        def execute(self,*args,**kwargs):
            result=frontend();result['media_input'][field]=value;return result
        def close(self):pass
    with pytest.raises(ValueError,match='source descriptor'):
        PHASE.collect(SimpleNamespace(action='live',console=tmp_path/'owned.sock'),console_factory=Guest)


def test_stale_host_fisherman_is_rejected():
    result=frontend();result['host_fisherman_matches_deployment']=False
    with pytest.raises(ValueError):validate_frontend(result)
    probe=__import__('lib.xfce_candidate',fromlist=['LIVE_PROBE']).LIVE_PROBE
    assert "'--show-location'" in probe and 'assert host == bundled' in probe


@pytest.mark.parametrize('kind,limit_name',[('payload','PAYLOAD_LIMIT'),('iso','ISO_LIMIT')])
def test_candidate_size_budget_is_fail_closed(tmp_path,monkeypatch,kind,limit_name):
    adapter=module('live-iso/common/src/xfce-media-input.py','size_adapter')
    monkeypatch.setattr(adapter,limit_name,16)
    path=tmp_path/'item'
    if kind=='payload':path.mkdir();data=path/'blob'
    else:data=path
    data.write_bytes(b'x'*16)
    assert adapter.check_budget(path,kind)['bytes']==16
    data.write_bytes(b'x'*17)
    with pytest.raises(ValueError,match='size budget'):adapter.check_budget(path,kind)


def test_oversized_source_fails_before_export(tmp_path,monkeypatch):
    adapter=module('live-iso/common/src/xfce-media-input.py','source_size_adapter')
    monkeypatch.setattr(adapter,'PAYLOAD_LIMIT',64)
    path=tmp_path/'manifest';path.write_text(json.dumps(dict(config={'size':1},layers=[{'size':65}])))
    digest='sha256:'+hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(ValueError,match='budget'):adapter.source_budget(path,digest)
    script=(ROOT/'scripts/build-iso-tacklebox.sh').read_text()
    assert script.index('--source-budget') < script.index('skopeo copy --preserve-digests')
    workflow=(ROOT/'.github/workflows/live-iso-bootc.yml').read_text()
    step=workflow[workflow.index('- name: Enforce candidate ISO'):workflow.index('# RETENTION IS NOT OPTIONAL')]
    assert 'if: inputs.candidate_xfce' in step and '--iso-budget' in step
    assert workflow.index('--iso-budget') < workflow.index('- name: Upload Artifact')


@pytest.mark.parametrize('fault',[None,'no_login','no_password','no_sudo','interrupted'])
def test_visual_console_authentication_boundaries(monkeypatch,fault):
    from lib import visual_console as vc
    monkeypatch.setattr(vc.secrets,'token_hex',lambda count:'a'*(count*2))
    state={'stage':0,'clock':0,'keys':[],'captures':[],'line':[]}
    password='secret123'
    def key(value):
        state['keys'].append(value)
        if value=='ret':
            if state['stage']==2 and state['line'][:4]==['shift-t','shift-u','shift-n','shift-a']:
                pass
            else:state['stage']+=1
            state['line']=[]
        elif value!='ctrl-alt-f3':state['line'].append(value)
    def capture():
        stage=state['stage'];state['captures'].append(stage)
        if fault=='no_login':return 'no console'
        if stage==0:return 'hostname login:'
        if stage==1:return 'Password:' if fault!='no_password' else 'no prompt'
        if stage==2:return 'user $'
        if stage==3:return 'AUTH'+'a'*16 if fault!='no_sudo' else 'sudo unavailable'
        raise AssertionError('capture after secret submission')
    def serial():
        if state['stage']==4 and fault!='interrupted':
            return 'BEGIN_'+'a'*32+'\n{"active":true}\nEND_'+'a'*32+'\n'
        return ''
    def clock():state['clock']+=20;return state['clock']
    console=vc.VisualConsole('tunauser',password,key,capture,serial,sleep=lambda _:None,clock=clock)
    if fault:
        with pytest.raises(ValueError):console.execute("print('{}')")
    else:
        assert console.execute("print('{}')")=={'active':True}
        assert state['keys'][0]=='ctrl-alt-f3'
        assert state['captures'][:3]==[0,1,2] and state['captures'][-1]==3
        assert all(stage==2 for stage in state['captures'][3:-1])


@pytest.mark.parametrize('fault',[None,'sudo','session','vt','restore','inactive'])
def test_visual_observer_verifies_bytes_and_restores_graphical_vt(monkeypatch,fault):
    import builtins
    import io
    import os
    from lib.visual_console import envelope
    state={'active':False,'writes':''}
    monkeypatch.setenv('SUDO_USER','other' if fault=='sudo' else 'tunauser')
    def command(args,**kwargs):
        if args==['fixture-active']:return 'yes' if state['active'] else 'no'
        assert args[0]=='loginctl'
        if args[1]=='list-sessions':return '' if fault=='session' else '2 1000 tunauser seat0 tty2\n'
        return 'Name=tunauser\nClass=user\nRemote=no\nType=x11\nVTNr='+('99' if fault=='vt' else '2')+'\n'
    def run(args,**kwargs):
        assert args==['chvt','2']
        if fault=='restore':raise ValueError('restore failed')
        state['active']=fault!='inactive'
    class Channel(io.StringIO):
        def close(self):state['writes']=self.getvalue();super().close()
    monkeypatch.setattr(subprocess,'check_output',command)
    monkeypatch.setattr(subprocess,'run',run)
    monkeypatch.setattr(builtins,'open',lambda path,mode:Channel() if path=='/dev/ttyS0' and mode=='w' else pytest.fail('unexpected file write'))
    # Inert source checks the restored-state fixture; no guest command executes.
    monkeypatch.setattr(__import__('time'),'sleep',lambda _:None)
    source="import json,subprocess; assert subprocess.check_output(['fixture-active'])=='yes'; print(json.dumps({'active':True}))"
    launcher=envelope(source,'tunauser','a'*32)
    exec(launcher,{})
    if fault:
        assert '"error"' in state['writes'] and '"active"' not in state['writes']
    else:
        assert state['active'] and '"active": true' in state['writes']
    assert state['writes'].startswith('BEGIN_'+'a'*32)
    state['active']=False
    # Alter expected checksum: execution must stop before chvt or observation.
    import re
    altered=re.sub(r"hexdigest\(\)=='[a-f0-9]{64}'", "hexdigest()=='"+'0'*64+"'",launcher)
    with pytest.raises(AssertionError):exec(altered,{})
    assert state['active'] is False


def test_visual_transfer_has_bounded_lines_and_no_guest_file():
    from lib.visual_console import envelope
    encoded,launcher=envelope('print("large fixed observer")\n'*1000,'tunauser','a'*32,argument=True)
    assert 'sha256' in launcher and 'argv[1]' in launcher
    assert all(len(encoded[offset:offset+1500])<=1500 for offset in range(0,len(encoded),1500))
    assert 'password' not in launcher
    source=(ROOT/'scripts/lib/visual_console.py').read_text()
    assert "ctrl-alt-f3" in source and "['chvt',vt]" in source
    assert 'serial-getty' not in source and 'console=ttyS0' not in source


def test_observer_real_source_fits_bounded_transfer(tmp_path,monkeypatch):
    from lib.visual_console import envelope
    monkeypatch.setenv('TUNAOS_XFCE_USER','tunaabcdefhkmnpr')
    log=tmp_path/'boot';log.write_text('TUNAOS_DESKTOP_CONTRACT_OK desktop=xfce experience=tunaos/xfce\n')
    source=PHASE.observer_source(SimpleNamespace(boot_log=log,mode='plain',phase='cold'))
    encoded,launcher=envelope(source,'tunaabcdefhkmnpr','a'*32,argument=True)
    assert len(encoded)<16384 and len(launcher)<1500


def test_gui_password_keys_release_before_next_character(monkeypatch):
    events=[]
    monkeypatch.setattr(PHASE,'monitor',lambda path,value:events.append(value))
    monkeypatch.setattr(PHASE.time,'sleep',lambda delay:events.append(delay))
    PHASE.type_text('monitor','a1')
    assert events==['sendkey a 10',.05,'sendkey 1 10',.05]


def test_guest_credentials_still_use_python_secure_random():
    import ast
    tree=ast.parse((ROOT/'scripts/run-xfce-candidate.py').read_text())
    assert any(isinstance(n,ast.Import) and any(a.name=='secrets' and a.asname=='guest_random' for a in n.names) for n in tree.body)
    calls=[n for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute)
           and isinstance(n.func.value,ast.Name) and n.func.value.id=='guest_random']
    assert sum(n.func.attr=='token_hex' and len(n.args)==1 and isinstance(n.args[0],ast.Constant) and n.args[0].value==16 for n in calls)==2
    assert any(n.func.attr=='choice' for n in calls)


def test_candidate_tracking_ref_uses_publication_config(monkeypatch):
    from lib.xfce_candidate import published_ref
    from lib.publish_destination import publish_destination
    monkeypatch.setenv('IMAGE_REGISTRY','quay.io/review-fixture')
    publish_destination.cache_clear()
    try:
        assert published_ref()=='quay.io/review-fixture/bonito:xfce'
    finally:
        publish_destination.cache_clear()


def test_live_probe_uses_resolved_tracking_ref_and_rejects_stock_substitution(tmp_path,monkeypatch):
    monkeypatch.setenv('TUNAOS_QUAL_SOURCE_DIGEST','sha256:'+'a'*64)
    monkeypatch.setattr(PHASE,'published_ref',lambda:'quay.io/review-fixture/bonito:xfce')
    value=frontend()
    class Guest:
        def __init__(self,*args):pass
        def execute(self,*args,**kwargs):return value
        def close(self):pass
    args=SimpleNamespace(action='live',console='unused',directory=tmp_path,output=tmp_path/'probe.json',mode='plain',phase='cold')
    with pytest.raises(ValueError,match='source descriptor'): PHASE.collect(args,console_factory=Guest)
    value['media_input'].update(image='quay.io/review-fixture/bonito:xfce',targetImgref='quay.io/review-fixture/bonito:xfce')
    result=PHASE.collect(args,console_factory=Guest)
    assert result['media_input']['image']=='quay.io/review-fixture/bonito:xfce'


@pytest.mark.parametrize('target',['','unqualified','https://registry/repo:tag','registry/repo:tag@sha256:bad','registry/repo:tag\n','registry//repo:tag','registry:wrong/repo:tag'])
def test_media_adapter_rejects_malformed_tracking_ref(tmp_path,target):
    adapter=module('live-iso/common/src/xfce-media-input.py','bad_tracking_adapter')
    with pytest.raises(ValueError,match='tracking target'):
        adapter.descriptor(tmp_path,'sha256:'+'a'*64,target)


@pytest.mark.parametrize('destination',['ghcr.io/tuna-os','quay.io/review-fixture'])
@pytest.mark.parametrize('wrong',[False,True])
def test_real_candidate_source_gate_uses_configured_ref(destination,wrong):
    import os
    source=(ROOT/'scripts/build-iso-tacklebox.sh').read_text()
    start=source.index('\t[[ "$VARIANT:$FLAVOR:$PLATFORM" == bonito:xfce:linux/amd64 ]]')
    body=source[start:source.index('\t# Preserve the exact base manifest',start)]
    digest='sha256:'+'a'*64
    target=destination+'/bonito:xfce'
    payload=('registry.invalid/wrong:xfce' if wrong else target)+'@'+digest
    env=dict(os.environ,IMAGE_REGISTRY=destination,REPO_ORGANIZATION=destination.split('/',1)[1],
        VARIANT='bonito',FLAVOR='xfce',PLATFORM='linux/amd64',TUNA_LIVE_BASE_DIGEST=digest,TUNA_LIVE_PAYLOAD_REF=payload)
    result=subprocess.run(['bash','-eu','-c',body],cwd=ROOT,env=env,capture_output=True,text=True)
    assert (result.returncode==0) is (not wrong),result.stderr
    custom=(ROOT/'live-iso/common/src/customize-live.sh').read_text()
    start=custom.index('\t[[ "$INSTALLER_APP" == org.tunaos.InstallerXfce')
    body=custom[start:custom.index('\t# XFCE reads',start)]
    env.update(INSTALLER_APP=APP,TUNA_LIVE_PLATFORM='linux/amd64',TUNA_LIVE_INSTALL_TARGET=target)
    result=subprocess.run(['bash','-eu','-c',body],env=env,capture_output=True,text=True)
    assert (result.returncode==0) is (not wrong),result.stderr
