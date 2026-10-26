"""Inert contracts; synthetic fixtures are never actual runtime qualification."""
import importlib.util
import hashlib
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from contracts.iso_qualification import DESKTOPS, manifest, select, validate_session

spec = importlib.util.spec_from_file_location('native_fixtures', ROOT / 'tests/test_native_iso_qualification.py')
fixtures = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixtures)
NATIVE = fixtures.NATIVE


def session(desktop):
    _, process, names, types = DESKTOPS[desktop]
    return dict(desktop=desktop, architecture='x86_64', desktop_contract=True,
                active=True, remote=False, uid=1000, process_uid=1000, process_pid=123,
                session_id='1', scope='session-1.scope', process_cgroup='/user.slice/user-1000.slice/session-1.scope',
                session_desktop=names[0], type=types[0], process=process, **{'class': 'user'})


def evidence(desktop='xfce'):
    data = fixtures.evidence()
    data.update(schema=NATIVE.DESKTOP_SCHEMA, flavor=desktop, platform='linux/amd64',
                cpu_baseline='x86-64-v3', storage_backend='ostree', manifest_digest=manifest()['manifestDigest'])
    binding = data['artifact_binding']
    binding.update(variant=data['variant'], flavor=desktop, platform=data['platform'],
                   source_digest=data['resolved_inputs']['source'], storage_backend='ostree')
    data['consumer_target']={key:binding[key] for key in ('variant','flavor','platform','source_digest','storage_backend')}
    data['artifact_binding_digest'] = NATIVE.canonical(binding)
    for mode, row in data['observed'].items():
        row.update(fresh_install=True, storage_backend='ostree', flavor=desktop,
                   platform=data['platform'], sessions={p:session(desktop) for p in ('cold','warm')})
        row['target_imgref'] = 'ghcr.io/tuna-os/skipjack:' + desktop
        for phase, observed_session in row['sessions'].items():
            observed_session.update(phase=phase, mode=mode, source_digest=data['resolved_inputs']['source'],
                boot_id=({'plain': {'cold':'a','warm':'b'}, 'luks': {'cold':'c','warm':'d'}}[mode][phase])*8+'-1111-2222-3333-444444444444')
        row['gui'].update(desktop=desktop, frontend=DESKTOPS[desktop][0])
    if desktop=='xfce':
        from lib.xfce_candidate import APP, COMMIT, TRANSITIONS
        data['resolved_inputs']['installer']='sha256:'+COMMIT
        for row in data['observed'].values():
            row['frontend_identity']=dict(app=APP,commit=COMMIT,receipt_app=APP,receipt_revision=COMMIT,receipt_digest=COMMIT,architecture='x86_64',running_app=APP,host_fisherman_matches_deployment=True,host_fisherman_digest='sha256:'+'d'*64)
            row['frontend_identity']['media_input']=dict(schemaVersion=1,platform=data['platform'],image=row['target_imgref'],targetImgref=row['target_imgref'],platformManifestDigest=data['resolved_inputs']['source'],ociLayoutPath='/usr/lib/tunaos/xfce-candidate-oci')
            row['gui'].update(installer_digest='sha256:'+COMMIT,transitions=TRANSITIONS,account_digest='sha256:'+hashlib.sha256(b'tuna12345678').hexdigest(),source_selection='live-self-install')
            for value in row['sessions'].values():
                value.update(account_digest='sha256:'+hashlib.sha256(b'tuna12345678').hexdigest(),storage_backend='ostree')
    return fixtures.seal(data)


def test_inventory_reconciles_all_rows_without_claims():
    doc = manifest()
    assert doc['counts'] == dict(flavor_pairs=62, configured=92, image_supported=92)
    assert len(doc['targets']) == 92
    assert all('required' not in row for row in doc['targets'])
    from lib.tunaos_config import load, matrix
    config = matrix(load())
    expected = {(v['id'], f['id'], p) for v in config['variants'] for f in v['flavors']
                if f.get('build_iso') for p in f.get('platforms', v['platforms'])}
    assert {tuple(r['target'][k] for k in ('variant', 'flavor', 'platform')) for r in doc['targets']} == expected
    assert all(r['result'] == 'unrun' for r in doc['targets'])
    assert {'gnome','kde','xfce','cosmic','niri','pantheon','base'} <= {r['desktop'] for r in doc['targets']}
    hummingbird = [r for r in doc['targets'] if r['target']['variant'] == 'hummingbird' and r['configured']]
    assert {r['desktop'] for r in hummingbird} == {'base','gnome','cosmic'}
    assert all(r['target']['platform']=='linux/amd64' for r in hummingbird)
    assert doc['unsupported'][0]['flavor'] == 'tuna'


@pytest.mark.parametrize('keys,parallel', [([],1), (['all'],1),
    (['skipjack:gnome:linux/amd64']*2,1), (['skipjack:gnome:linux/amd64'],0),
    (['skipjack:gnome:linux/amd64'],3), (['skipjack:gnome:linux/amd64'],True),
    (['hummingbird:tuna:linux/amd64'],1), (['hummingbird:base:linux/amd64'],1),
    (['skipjack:gnome:linux/amd64/v2'],1), (['skipjack:xfce:linux/amd64'],1),
    (['yellowfin:gnome-nvidia:linux/amd64'],1), (['hummingbird:gnome:linux/arm64'],1)])
def test_campaign_fails_closed(keys, parallel):
    with pytest.raises(ValueError): select(manifest(), keys, parallel)


def test_bounded_gnome_control_stays_unrun():
    plan = select(manifest(), ['skipjack:gnome:linux/amd64'], 1)
    assert plan['result']=='unrun' and plan['include'][0]['cpuBaseline']=='x86-64-v3'


@pytest.mark.parametrize('desktop', ['gnome','kde','xfce'])
def test_generalized_receipt_contract(desktop):
    NATIVE.validate(evidence(desktop))


@pytest.mark.parametrize('path,value', [
    (('observed','luks','sessions','cold','boot_id'),'aaaaaaaa-1111-2222-3333-444444444444'),
    (('observed','plain','sessions','cold','process_cgroup'),'/user.slice/user-1000.slice/session-2.scope'),
    (('observed','plain','target_imgref'),'ghcr.io/tuna-os/skipjack:gnome'),
    (('observed','plain','sessions','warm','boot_id'),'aaaaaaaa-1111-2222-3333-444444444444'),
    (('observed','luks','sessions','cold','mode'),'plain'),
    (('flavor',),'kde'), (('platform',),'linux/arm64'), (('storage_backend',),'native-composefs'),
    (('manifest_digest',),'sha256:'+'0'*64), (('flavor',),'base'),
    (('consumer_target','source_digest'),'sha256:'+'b'*64),
    (('consumer_target','flavor'),'gnome'), (('consumer_target','platform'),'linux/arm64'),
    (('observed','plain','fresh_install'),False), (('observed','luks','fresh_install'),'true'),
    (('observed','plain','desktop_contract'),False), (('observed','luks','warm_boot'),False),
    (('observed','plain','sessions'),{}), (('observed','luks','sessions','warm','active'),False),
    (('observed','luks','sessions','cold','class'),'greeter'),
    (('observed','plain','sessions','cold','process'),'gnome-shell'),
    (('observed','plain','sessions','cold','process_uid'),0),
    (('observed','plain','sessions','warm','architecture'),'aarch64'),
    (('observed','plain','sessions','warm','desktop_contract'),False),
    (('observed','plain','gui','frontend'),'org.bootcinstaller.Installer'),
    (('observed','plain','gui','desktop'),'gnome'),
    (('observed','plain','gui','completed'),False),
])
def test_swapped_missing_skipped_or_fabricated_coverage_fails(path, value):
    data = evidence(); cursor = data
    for key in path[:-1]: cursor=cursor[key]
    cursor[path[-1]]=value
    data['artifact_binding_digest']=NATIVE.canonical(data['artifact_binding'])
    with pytest.raises(ValueError): NATIVE.validate(fixtures.seal(data))


def test_v2_cannot_be_relabelled_as_expanded_proof():
    data=fixtures.evidence(); data['schema']=NATIVE.DESKTOP_SCHEMA
    with pytest.raises(ValueError): NATIVE.validate(fixtures.seal(data))


@pytest.mark.parametrize('desktop', list(DESKTOPS))
def test_session_contracts_are_desktop_specific(desktop):
    validate_session(session(desktop), desktop, 'linux/amd64')
    with pytest.raises(ValueError): validate_session(session(desktop), 'base', 'linux/amd64')


def test_candidate_contract_cannot_enter_strict_workflow(tmp_path):
    import json
    import subprocess
    receipt = tmp_path / 'receipt.json'
    receipt.write_text(json.dumps(evidence()))
    script = str(ROOT / 'scripts/native-iso-qualification.py')
    denied = subprocess.run([sys.executable, script, 'validate', str(receipt)], capture_output=True)
    assert denied.returncode == 1 and b'not admitted' in denied.stderr
    candidate = subprocess.run([sys.executable, script, 'validate-candidate', str(receipt)], capture_output=True)
    assert candidate.returncode == 0 and b'candidate contract only' in candidate.stdout


def test_guest_session_observer_uses_real_session_and_process(tmp_path):
    import json
    observer_spec = importlib.util.spec_from_file_location('observe_session', ROOT/'scripts/observe-iso-session.py')
    observer = importlib.util.module_from_spec(observer_spec)
    observer_spec.loader.exec_module(observer)
    proc = tmp_path/'proc'; process = proc/'123'; process.mkdir(parents=True)
    (process/'status').write_text('Uid:\t1000\t1000\t1000\t1000\n')
    (process/'comm').write_text('xfce4-session\n')
    (process/'cgroup').write_text('0::/user.slice/user-1000.slice/session-1.scope\n')
    boot = proc/'sys/kernel/random'; boot.mkdir(parents=True)
    (boot/'boot_id').write_text('aaaaaaaa-1111-2222-3333-444444444444\n')
    responses = {
        'journalctl': 'TUNAOS_DESKTOP_CONTRACT_OK desktop=xfce experience=tunaos/xfce',
        'pgrep': '123', 'uname': 'x86_64',
        'bootc': json.dumps({'status': {'booted': {'image': {'imageDigest': 'sha256:'+'a'*64,'image':{'image':'ghcr.io/tuna-os/grouper:xfce'}}}}}),
    }
    properties = 'Active=yes\nClass=user\nRemote=no\nUser=1000\nDesktop=XFCE\nType=x11\nScope=session-1.scope'
    def command(*args):
        if args[0]=='loginctl':
            return '1 1000 tester seat0 tty2' if args[1]=='list-sessions' else properties
        if args[0]=='pgrep': assert args == ('pgrep','-u','1000','-x','xfce4-session')
        return responses[args[0]]
    observed = observer.observe('xfce','linux/amd64','plain','cold',command,proc)
    assert observed['uid']==1000 and observed['process']=='xfce4-session'
    for wrong in ['Class=greeter', 'Remote=yes', 'Active=no', 'Desktop=GNOME', 'Type=tty']:
        key = wrong.split('=')[0]
        before = properties
        properties = '\n'.join(wrong if line.startswith(key+'=') else line for line in properties.splitlines())
        with pytest.raises(ValueError): observer.observe('xfce','linux/amd64','plain','cold',command,proc)
        properties = before
    responses['journalctl'] += '\nTUNAOS_DESKTOP_CONTRACT_FAIL reason=dm_inactive'
    with pytest.raises(ValueError): observer.observe('xfce','linux/amd64','plain','cold',command,proc)


def test_workflow_bounds_and_explicit_native_platform():
    import yaml
    e2e=yaml.safe_load((ROOT/'.github/workflows/iso-e2e.yml').read_text())
    jobs=e2e['jobs']
    assert jobs['e2e']['strategy']['max-parallel']=='${{ fromJson(needs.generate-matrix.outputs.max_parallel) }}'
    step=next(s for s in jobs['generate-matrix']['steps'] if s.get('id')=='gen')
    assert step['env']['MAX_PARALLEL']=='${{ inputs.max_parallel }}'
    assert '--target "$DISPATCH_VARIANT:$DISPATCH_FLAVORS:$REQUESTED_PLATFORM"' in step['run']
    assert '-le 4' in step['run']
    producer=yaml.safe_load((ROOT/'.github/workflows/live-iso-bootc.yml').read_text())
    assert producer['jobs']['build']['needs']=='preflight'
    assert producer['jobs']['qualify-native-iso']['with']['platform']=="${{ inputs.platform || 'linux/amd64' }}"


def test_v2_native_baseline_uses_variant_policy():
    receipt=fixtures.evidence()
    receipt.update(platform='linux/amd64', cpu_baseline='x86-64-v3')
    NATIVE.validate(fixtures.seal(receipt))
    receipt['cpu_baseline']='x86-64'
    with pytest.raises(ValueError, match='baseline'): NATIVE.validate(fixtures.seal(receipt))


def test_current_toml_support_does_not_invent_missing_architectures(monkeypatch):
    import contracts.iso_qualification as inventory
    from lib.tunaos_config import load
    config = load()
    flavor = next(f for f in config['variants']['bonito']['flavors'] if f['id']=='xfce')
    flavor['platforms'] = ['linux/amd64/v3']
    flavor['build_image'] = False
    monkeypatch.setattr(inventory, 'load', lambda path=None: config)
    doc = inventory.manifest()
    rows = [r for r in doc['targets'] if r['target']['variant']=='bonito' and r['target']['flavor']=='xfce']
    assert len(rows)==1
    assert rows[0]['target']['platform']=='linux/amd64/v3'
    assert rows[0]['target']['cpuBaseline']=='x86-64-v3'
    assert not rows[0]['image_supported'] and not rows[0]['runnable']
    assert 'source image build disabled' in rows[0]['gaps']
    with pytest.raises(ValueError): inventory.select(doc,['bonito:xfce:linux/amd64'],candidate_xfce=True)


def test_current_publication_identity_matches_shared_shell_resolver():
    import os
    import subprocess
    rows=manifest()['targets']
    for variant in ('bonito','albacore'):
        row=next(r for r in rows if r['target']['variant']==variant and r['target']['flavor']=='xfce')
        expected=subprocess.check_output(['bash','scripts/published-image-ref.sh',variant,'xfce','ghcr'],
            cwd=ROOT,env=os.environ,text=True).strip()
        assert row['publication']['repository']+':'+row['publication']['tag']==expected


def test_configured_cpu_conflict_cannot_pass_candidate_receipt():
    data=evidence('gnome')
    data.update(platform='linux/amd64/v2',cpu_baseline='x86-64-v2')
    with pytest.raises(ValueError,match='support or hardware gaps'):
        NATIVE.validate(fixtures.seal(data))


def test_bare_alma_and_v2_keep_distinct_native_baselines():
    rows=[r for r in manifest()['targets'] if r['target']['variant']=='albacore' and r['target']['flavor']=='gnome']
    baselines={r['target']['platform']:r['target']['cpuBaseline'] for r in rows}
    assert baselines['linux/amd64']=='x86-64-v3'
    assert baselines['linux/amd64/v2']=='x86-64-v2'
