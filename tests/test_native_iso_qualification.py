"""Native evidence is a distinct contract, never substituted for browser parity."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest
import yaml

ROOT = Path(__file__).parents[1]

def module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result

NATIVE = module(ROOT/'scripts/native-iso-qualification.py', 'native_qualification')
BROWSER = module(ROOT/'scripts/verify-experience-manifest.py', 'browser_qualification')
BROWSER_TEST = module(ROOT/'tests/test_experience_manifest.py', 'browser_fixture')


def seal(data):
    data.pop('receiptDigest', None)
    data['receiptDigest'] = NATIVE.canonical(data)
    return data


def evidence():
    source = 'sha256:'+'a'*64
    binding = {'repository':'tuna-os/tunaOS', 'producer_workflow':'.github/workflows/live-iso-bootc.yml',
               'producer_build_conclusion':'success', 'producer_status':'in_progress', 'producer_conclusion':None,
               'producer_run':123, 'producer_attempt':1, 'producer_build_job':456, 'artifact_id':789,
               'media_size':1024, 'producer_sha':'a'*40, 'harness_sha':'a'*40,
               'archive_digest':'sha256:'+'b'*64, 'media_digest':'sha256:'+'c'*64,
               'status':'download_verified_not_boot_tested'}
    data = {'schema':NATIVE.SCHEMA, 'execution_kind':'native-qemu', 'variant':'skipjack', 'flavor':'gnome',
            'platform':'linux/amd64/v2', 'cpu_baseline':'x86-64-v2', 'hardware_scope':'qemu',
            'offline_network_disabled':True, 'resolved_inputs':{key:source for key in NATIVE.INPUTS},
            'artifact_binding':binding, 'artifact_binding_digest':NATIVE.canonical(binding),
            'qemu':{'digest':source, 'version':'QEMU emulator version 8.2.2', 'cpu_model':'host'},
            'qualifiedAt':'2026-10-21T16:00:00+00:00', 'observed':{}}
    data['resolved_inputs']['media'] = binding['media_digest']
    for mode in ('plain','luks'):
        data['observed'][mode] = {'mode':mode, 'installed_boot':True, 'desktop_contract':True,
            'cold_boot':True, 'warm_boot':True, 'media_detached':True,
            'passphrase_prompt':mode == 'luks', 'source_digest':source, 'booted_digest':source,
            'target_imgref':'ghcr.io/tuna-os/skipjack:gnome', 'duration_s':100, 'install_duration_s':50,
            'cold_boot_s':25, 'warm_boot_s':25,
            'gui':{'mode':mode,'installer_digest':source,'transitions':NATIVE.TRANSITIONS.copy(),
                   'frontmost':True, 'submitted':True, 'accepted':True, 'completed':True, 'receipt_digest':source}}
    return seal(data)


def test_valid_native_and_browser_are_separate():
    native = evidence()
    NATIVE.validate(native)
    browser = BROWSER_TEST.manifest()
    BROWSER.validate(browser, 'browser')
    with pytest.raises(ValueError): BROWSER.validate(native, 'native')
    with pytest.raises(ValueError): NATIVE.validate(browser)
    native['schema'] = 'QualificationEvidence/v1'
    with pytest.raises(ValueError): BROWSER.validate(seal(native), 'mislabeled native')
    browser['schema'] = NATIVE.SCHEMA
    browser['execution_kind'] = 'native-qemu'
    with pytest.raises(ValueError): NATIVE.validate(seal(browser))


@pytest.mark.parametrize('path,value', [
    (('schema',),'QualificationEvidence/v1'), (('browser',),{'name':'chromium','version':'100'}),
    (('execution_kind',),'browser'), (('offline_network_disabled',),False),
    (('artifact_binding','repository'),'other/repo'),
    (('artifact_binding','producer_build_conclusion'),'failure'),
    (('artifact_binding','producer_status'),'cancelled'),
    (('artifact_binding','producer_sha'),'b'*40),
    (('artifact_binding','artifact_id'),0),
    (('artifact_binding','media_digest'),'sha256:'+'d'*64),
    (('qemu','digest'),'unknown'), (('qemu','cpu_model'),''),
    (('cpu_baseline',),'unknown'), (('platform',),'linux/bogus'),
    (('observed','plain','installed_boot'),False),
    (('observed','luks','warm_boot'),False),
    (('observed','plain','cold_boot'),False),
    (('observed','luks','media_detached'),False),
    (('observed','luks','passphrase_prompt'),False),
    (('observed','plain','passphrase_prompt'),True),
    (('observed','luks','booted_digest'),'sha256:'+'d'*64),
    (('observed','luks','gui','accepted'),False),
    (('observed','plain','gui','completed'),False),
    (('observed','plain','gui','mode'),'luks'),
    (('observed','plain','gui','transitions'),['welcome','summary','done']),
    (('observed','luks','cold_boot_s'),0),
])
def test_native_semantic_refusals_even_with_valid_receipt_hash(path, value):
    data = evidence(); target = data
    for key in path[:-1]: target = target[key]
    target[path[-1]] = value
    data['artifact_binding_digest'] = NATIVE.canonical(data['artifact_binding'])
    with pytest.raises(ValueError): NATIVE.validate(seal(data))


def test_receipt_hash_must_match():
    data = evidence(); data['variant'] = 'yellowfin'
    with pytest.raises(ValueError, match='receipt digest'): NATIVE.validate(data)


@pytest.mark.parametrize('source', ['native-artifact','build','r2-latest',''])
def test_source_specific_dependency_step_executes_without_snap_for_native(tmp_path, source):
    workflow = yaml.safe_load((ROOT/'.github/workflows/iso-e2e.yml').read_text())
    step = next(s for s in workflow['jobs']['e2e']['steps'] if s.get('name') == 'Install QEMU and helpers')
    binpath=tmp_path/'bin';binpath.mkdir();log=tmp_path/'calls';out=tmp_path/'env'
    for name, body in {'sudo':'echo "$*" >> "$CALLS"',
                       'qemu-system-x86_64':'echo "QEMU emulator version 8.2.2"',
                       'chromium':'echo chromium-called >> "$CALLS"; echo "Chromium 130.0"'}.items():
        path=binpath/name;path.write_text('#!/bin/sh\n'+body+'\n');path.chmod(0o755)
    env=dict(os.environ, PATH=str(binpath)+':'+os.environ['PATH'], PLATFORM='linux/amd64', ISO_SOURCE=source,
             GITHUB_ENV=str(out), GITHUB_WORKSPACE=str(tmp_path), CALLS=str(log),
             NATIVE_ARTIFACT_ID='789', NATIVE_ARCHIVE_DIGEST='sha256:'+'b'*64, NATIVE_SOURCE_SHA='a'*40)
    subprocess.run(['bash','-c',step['run']],env=env,check=True,capture_output=True)
    calls=log.read_text(); exported=out.read_text()
    for needed in ('qemu-utils','swtpm','imagemagick','tesseract-ocr','xorriso','squashfs-tools'):
        assert needed in calls
    if source == 'native-artifact':
        assert 'chromium' not in calls and 'BROWSER_' not in exported
        assert 'TUNAOS_QUAL_EXECUTION_KIND=native-qemu' in exported
    else:
        assert 'chromium-called' in calls and 'TUNAOS_QUAL_BROWSER_NAME=chromium' in exported
        assert 'EXECUTION_KIND=native-qemu' not in exported


def test_native_emitter_checks_current_context_and_preserves_failures(tmp_path, monkeypatch):
    data=evidence();binding=tmp_path/'binding.json';binding.write_text(json.dumps(data['artifact_binding']))
    qemu=tmp_path/'qemu';qemu.write_bytes(b'measured qemu executable')
    for mode in ('plain','luks'):
        frag=copy.deepcopy(data['observed'][mode]);gui=frag.pop('gui')
        (tmp_path/f'strict-qual-{mode}.json').write_text(json.dumps(frag))
        directory=tmp_path/f'walkthrough-{mode}';directory.mkdir()
        (directory/'walkthrough-gnome.json').write_text(json.dumps(gui))
    monkeypatch.setattr(NATIVE.subprocess,'check_output',lambda cmd,**kwargs:'a'*40 if cmd[0]=='git' else 'QEMU emulator version 8.2.2\n')
    monkeypatch.setattr(NATIVE.shutil,'which',lambda name:str(qemu))
    args=SimpleNamespace(binding=binding,directory=tmp_path,output=tmp_path/'result.json',repository='tuna-os/tunaOS',
        run_id=123,attempt=1,artifact_id=789,archive_digest=data['artifact_binding']['archive_digest'],source_sha='a'*40,
        qemu='qemu',variant='skipjack',flavor='gnome',platform='linux/amd64/v2',cpu_model='host',**data['resolved_inputs'])
    result=NATIVE.emit(args);assert 'browser' not in result
    assert result['qemu']['digest']==NATIVE.digest(qemu)
    for field,value in [('attempt',2),('run_id',124),('artifact_id',790),('source_sha','b'*40)]:
        changed=copy.copy(args);setattr(changed,field,value)
        with pytest.raises(ValueError):NATIVE.emit(changed)
    frag=json.loads((tmp_path/'strict-qual-luks.json').read_text());frag['warm_boot']=False
    (tmp_path/'strict-qual-luks.json').write_text(json.dumps(frag))
    with pytest.raises(ValueError,match='warm_boot'):NATIVE.emit(args)


def test_harness_native_branch_does_not_reach_browser_emitter():
    script=(ROOT/'scripts/iso-e2e.sh').read_text()
    native=script.split('emit_qualification_evidence() {',1)[1].split('\n\tfi',1)[0]
    assert 'native-iso-qualification.py" emit' in native and 'return $?' in native
    assert 'BROWSER' not in native
    assert '--cpu-model "$CPU_ARG"' in native
    assert 'TUNAOS_QUAL_CPU_BASELINE' not in native
    assert 'rm -f "${OUTPUT_DIR}/strict-qual-${_reset_mode}.json"' in script
    assert 'STRICT_FRAG_PROMPT="$saw_prompt"' in script
    assert '"passphrase_prompt": os.environ["STRICT_FRAG_PROMPT"] == "1"' in script
    parity=(ROOT/'.github/workflows/iso-builder-parity.yml').read_text()
    assert 'TUNAOS_QUAL_EXECUTION_KIND' not in parity


@pytest.mark.parametrize('source', ['native-artifact', 'build', 'r2-latest', ''])
@pytest.mark.parametrize('kind', ['native', 'browser'])
def test_final_workflow_validator_selects_source_contract(tmp_path, source, kind):
    workflow = yaml.safe_load((ROOT/'.github/workflows/iso-e2e.yml').read_text())
    step = next(s for s in workflow['jobs']['e2e']['steps'] if s.get('name') == 'Validate strict qualification evidence')
    assert step['env']['ISO_SOURCE'] == '${{ inputs.source }}'
    scripts = tmp_path/'scripts'; scripts.mkdir()
    for name in ('native-iso-qualification.py', 'verify-experience-manifest.py'):
        (scripts/name).symlink_to(ROOT/'scripts'/name)
    output = tmp_path/'iso-e2e-out'; output.mkdir()
    data = evidence() if kind == 'native' else BROWSER_TEST.manifest()
    (output/'qualification-evidence.json').write_text(json.dumps(data))
    result = subprocess.run(['bash', '-c', step['run']], cwd=tmp_path,
        env=dict(os.environ, ISO_SOURCE=source), capture_output=True, text=True)
    assert (result.returncode == 0) is ((source == 'native-artifact') == (kind == 'native')), result.stderr
