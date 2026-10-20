"""Primary desktop policy retains complete native semantics during migration."""
import copy
import importlib.util
import json
from pathlib import Path
import sys

import pytest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from lib import tunaos_config, tunaos_packages as r
FIXTURES=ROOT/'tests/fixtures/primary-packages'


def historical():
    return tunaos_config.tomllib.loads((FIXTURES/'source-at-f3682af7.toml').read_text())


def live():
    d=tunaos_config.load()
    return {k:d[k] for k in ('package_groups','desktops')}


@pytest.mark.parametrize('name',sorted(json.loads((FIXTURES/'profiles-at-f3682af7.json').read_text())))
def test_complete_ordered_profile_parity(name):
    expected=json.loads((FIXTURES/'profiles-at-f3682af7.json').read_text())
    assert r.legacy_profiles(historical())[name]==expected[name]


def test_live_primary_source_owns_all_profiles():
    assert len(r.legacy_profiles(live()))==15
    d=live()
    d['desktops']['gnome-debian']['packages']['apt']['required'].append('fixture-native-tool')
    assert r.resolve(d,'gnome',manager='apt',os_id='debian')['sections'][-1][1]['required'][-1]=='fixture-native-tool'


def fixture_requested_packages(requested, targets, evidence):
    """Fixture-only intent preflight, not a repository lookup or production add."""
    r.string_list(requested, 'requested')
    resolved = {}
    for target in targets:
        native = []
        for intent in requested:
            matches = evidence.get(target, {}).get(intent, [])
            if len(matches) != 1:
                raise r.PolicyError(f'{target}: {intent} unavailable or ambiguous')
            if matches[0] not in native:
                native.append(matches[0])
        resolved[target] = native
    return resolved


@pytest.mark.parametrize('desktop,target,profile,family', [
    ('gnome',dict(manager='apt',os_id='debian'),'gnome-debian','apt'),
    ('gnome',dict(manager='apt',os_id='ubuntu'),'gnome','apt'),
    ('gnome',dict(manager='pacman',os_id='arch'),'gnome-arch','pacman'),
    ('gnome',dict(manager='dnf',os_id='hummingbird',hummingbird=True),'gnome','hummingbird'),
    ('gnome',dict(manager='dnf',os_id='fedora',eln=True,fedora=True),'gnome','eln'),
    ('gnome',dict(manager='dnf',os_id='fedora',fedora=True,rawhide=True),'gnome','fedora'),
    ('tuna',dict(manager='dnf',os_id='fedora',fedora=True,rawhide=True),'tuna','rawhide'),
    ('gnome',dict(manager='zypper',os_id='opensuse'),'gnome','zypper'),
    ('gnome',dict(manager='emerge',os_id='gentoo'),'gnome','emerge'),
])
def test_selectors(desktop,target,profile,family):
    contract=r.resolve(live(),desktop,**target)
    assert (contract['profile'],contract['family']) == (profile,family)

def test_cachyos_overlay_precedes_pacman():
    result=r.resolve(live(),'kde',manager='pacman',os_id='cachyos',cachyos=True)
    assert [name for name,_ in result['sections']] == ['cachyos','pacman']

def test_unknown_operation_rejected():
    d=live();d['desktops']['gnome']['after_install']=['../../arbitrary.sh']
    with pytest.raises(r.PolicyError,match='unknown trusted operation'):r.validate(d)

def test_unknown_fields_rejected():
    d=live();d['desktops']['gnome']['shell']='echo arbitrary'
    with pytest.raises(r.PolicyError,match='known fields'):r.validate(d)

@pytest.mark.parametrize('value',['missing','gnome-fedora'])
def test_missing_and_cyclic_groups_rejected(value):
    d=live();d['package_groups']['gnome-fedora']['include']=[value]
    with pytest.raises(r.PolicyError,match='unknown group or inclusion cycle'):r.validate(d)

def test_direct_native_edit_is_scoped():
    d=live();before=r.legacy_profiles(d)
    d['desktops']['gnome-debian']['packages']['apt']['required'].append('fixture-native-tool')
    after=r.legacy_profiles(d)
    assert [name for name in before if before[name]!=after[name]]==['gnome-debian']
    assert after['gnome-debian']['packages']['apt'][-1]=='fixture-native-tool'

def test_supported_verifier_is_explicit():
    assert r.resolve(live(),'gnome',manager='apt',os_id='debian')['verification_supported']
    assert not r.resolve(live(),'gnome',manager='dnf',os_id='fedora',fedora=True)['verification_supported']
    with pytest.raises(r.PolicyError,match='unsupported'):
        r.resolve(live(),'pantheon',manager='emerge',os_id='gentoo')

def test_fixture_htop_intent_is_idempotent_and_measured():
    evidence={'debian':{'htop':['htop']},'gentoo':{'htop':['sys-process/htop']}}
    assert fixture_requested_packages(['htop','htop'],evidence,evidence)=={
        'debian':['htop'],'gentoo':['sys-process/htop']}
    assert evidence['debian']['htop']==['htop']

@pytest.mark.parametrize('matches',[[],['sys-process/htop','custom/htop']])
def test_fixture_htop_fails_without_unique_all_target_evidence(matches):
    evidence={'debian':{'htop':['htop']},'gentoo':{'htop':matches}}
    before=copy.deepcopy(evidence)
    with pytest.raises(r.PolicyError,match='gentoo: htop unavailable or ambiguous'):
        fixture_requested_packages(['htop'],evidence,evidence)
    assert evidence==before


def test_unknown_dnf_is_not_assumed_el10():
    with pytest.raises(r.PolicyError,match='explicit supported base-family'):
        r.resolve(live(),'gnome',manager='dnf',os_id='unknown')
    result=r.resolve(live(),'gnome',manager='dnf',os_id='almalinux',el10=True)
    assert result['family']=='el10'
    with pytest.raises(r.PolicyError,match='unsupported OS identity'):
        r.resolve(live(),'gnome',manager='dnf',os_id='unknown',el10=True)


def test_package_groups_is_required_consistently():
    d=live();del d['package_groups']
    for operation in [r.validate,r.legacy_profiles]:
        with pytest.raises(r.PolicyError,match='required table'):operation(d)


@pytest.mark.parametrize('character',['\n','\r','\t','\x00','\x1b','\x7f'])
def test_control_characters_are_rejected(character):
    d=live();d['desktops']['gnome']['display_manager']='gdm'+character
    with pytest.raises(r.PolicyError,match='single-line'):r.validate(d)


@pytest.mark.parametrize('section',['desktops','package_groups'])
def test_profile_and_group_ids_are_validated(section):
    d=live();d[section]['../../unsafe']=next(iter(d[section].values()))
    with pytest.raises(r.PolicyError,match='invalid identifier'):r.validate(d)


@pytest.mark.parametrize('failure,expected_rc,expected_commands',[
    ('none',0,3),('upgrade',9,1),('compat',9,2),('remove',0,3)])
def test_named_preinstall_commands_and_failure_behavior(tmp_path,failure,expected_rc,expected_commands):
    import subprocess,os
    commands=list(r.OPERATIONS['before'].values())
    script='''set -e
record() { printf '%s\\n' "$*" >> "$RECORD"; }
dnf() { record dnf "$@"; if [ "$FAIL" = upgrade ]; then return 9; fi; }
dnf_retry() {
  record dnf_retry "$@"
  if [ "$FAIL" = compat ] && [ "$2" = install ]; then return 9; fi
  if [ "$FAIL" = remove ] && [ "$2" = remove ]; then return 9; fi
  return 0
}
warn_on_fail() { "$@" || true; }
'''+ '\n'.join(commands)+'\n'
    record=tmp_path/'commands'
    result=subprocess.run(['bash','-c',script],env={**os.environ,'FAIL':failure,'RECORD':str(record)})
    assert result.returncode==expected_rc
    expected=[
        'dnf -y upgrade glib2 fontconfig gobject-introspection gjs',
        'dnf_retry -y install --allowerasing gnome50-el10-compat',
        'dnf_retry -y remove --noautoremove gnome-shell-common']
    assert record.read_text().splitlines()==expected[:expected_commands]


@pytest.mark.parametrize('field,value',[
    ('unknown',True),('priority',True),('unsigned','true'),('baseurl','http://example.com/repo'),
    ('baseurl','file:///etc/private'),('baseurl','https://example.com/repo\nextra'),
])
def test_repository_records_fail_closed(field,value):
    d=live();record=d['desktops']['gnome']['packages']['hummingbird']['repos'][0]
    record[field]=value
    with pytest.raises(r.PolicyError):r.validate(d)


def test_remote_unsigned_source_is_rejected():
    d=live();d['desktops']['gnome']['packages']['hummingbird']['repos'][0]['unsigned']=True
    with pytest.raises(r.PolicyError,match='unsigned remote'):r.validate(d)

@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("verify_signature", False, "must require package signatures"),
        ("sync_uri", "https://example.invalid/binpkgs", "TunaOS HTTPS source"),
    ],
)
def test_emerge_binrepo_trust_matches_installer_contract(field, value, message):
    d = live()
    binrepo = d["desktops"]["tuna"]["packages"]["emerge"]["binrepos"][0]
    binrepo[field] = value
    with pytest.raises(r.PolicyError, match=message):
        r.validate(d)


def test_projection_is_deterministic_and_matches_frozen_profiles():
    document=historical()
    outputs=r.desktop_outputs(document)
    assert outputs==r.desktop_outputs(document)
    baseline=json.loads((FIXTURES/'profiles-at-f3682af7.json').read_text())
    for name,profile in baseline.items():
        assert json.loads(outputs[f'manifests/desktops/{name}.yaml'])==profile
    contract=json.loads(outputs['manifests/desktop-plans/gnome-debian.apt.json'])
    assert contract['required']==baseline['gnome-debian']['packages']['apt']


def test_unsupported_apt_policy_is_rejected_instead_of_ignored():
    document=live()
    document['desktops']['gnome-debian']['packages']['apt']['optional']=['fixture-tool']
    with pytest.raises(r.PolicyError,match='known fields'):
        r.validate(document)


def test_group_cannot_hide_unsupported_family_policy():
    document=live()
    document['package_groups']['unsupported-apt']={'optional':['fixture-tool']}
    document['desktops']['gnome-debian']['packages']['apt']['include']=['unsupported-apt']
    with pytest.raises(r.PolicyError,match='known fields'):
        r.validate(document)


def expected_contract():
    import hashlib
    source=(ROOT/'tunaos.toml').read_bytes()
    document=tunaos_config.load()
    return r.installation_contract(document,hashlib.sha256(source).hexdigest(),
                                   'flounder','gnome','linux/amd64',manager='apt',os_id='debian')


def test_installed_receipt_still_requires_native_state_checks():
    expected=expected_contract();queried=[]
    r.verify_installed_receipt(expected,expected,lambda name: queried.append(name) or True)
    assert queried==expected['required']
    with pytest.raises(r.PolicyError,match='not installed'):
        r.verify_installed_receipt(expected,expected,lambda name:name!=expected['required'][0])


@pytest.mark.parametrize('field,value',[
    ('source_sha256','0'*64),('variant','flounder-sid'),('platform','linux/arm64'),
    ('desktop','kde'),('family','dnf'),('profile','gnome')])
def test_stale_or_mismatched_receipt_is_rejected_before_native_queries(field,value):
    expected=expected_contract();receipt=copy.deepcopy(expected);receipt[field]=value
    queried=[]
    with pytest.raises(r.PolicyError,match='stale or does not match'):
        r.verify_installed_receipt(receipt,expected,lambda name:queried.append(name) or True)
    assert queried==[]


@pytest.mark.parametrize('failure',['none','install','hook','source-change'])
def test_debian_contract_records_install_and_commits_only_after_success(tmp_path,failure):
    import os,subprocess,shutil
    yq=shutil.which('yq')
    if not yq:pytest.skip('mikefarah yq required for shell contract tests')
    contract=expected_contract()
    source=tmp_path/'tunaos.toml';source.write_bytes((ROOT/'tunaos.toml').read_bytes())
    plan=tmp_path/'contract.json';plan.write_text(json.dumps(contract))
    receipt=tmp_path/'installed.json';record=tmp_path/'commands'
    script='''set -e
source "$HELPER"
pkg_install() {
  printf '%s\\n' "$@" > "$RECORD"
  if [[ "$FAIL" == install ]]; then return 7; fi
}
tunaos_desktop_contract_install "$CONTRACT" "$SOURCE" flounder gnome linux/amd64
if [[ "$FAIL" == hook ]]; then exit 8; fi
if [[ "$FAIL" == source-change ]]; then printf '# changed\\n' >> "$SOURCE"; fi
tunaos_desktop_contract_commit "$RECEIPT"
'''
    result=subprocess.run(['bash','-c',script],env={**os.environ,'YQ':yq,'HELPER':str(ROOT/'build_scripts/lib/desktop-contract.sh'),
        'RECORD':str(record),'CONTRACT':str(plan),'SOURCE':str(source),'RECEIPT':str(receipt),'FAIL':failure},capture_output=True,text=True)
    assert record.read_text().splitlines()==contract['required']
    assert (result.returncode==0)==(failure=='none'),result.stderr
    assert receipt.exists()==(failure=='none')
    if receipt.exists():assert json.loads(receipt.read_text())==contract


def test_image_verifier_queries_dpkg_state_with_exact_arguments():
    from types import SimpleNamespace
    expected=expected_contract();calls=[]
    def run(argv,**kwargs):
        calls.append(argv)
        return SimpleNamespace(returncode=0,stdout=json.dumps(expected) if argv[4]=='cat' else 'installed')
    r.verify_debian_image_receipt('fixture/image:gnome',expected,run)
    assert calls[0]==['podman','run','--rm','--entrypoint','cat','fixture/image:gnome',
                      '/usr/share/tunaos/desktop-package-contract.json']
    assert [call[-1] for call in calls[1:]]==expected['required']
    assert all(call[4]=='dpkg-query' and call[-2]=='-f=${db:Status-Status}' for call in calls[1:])


def test_image_verifier_rejects_config_files_only_package_state():
    from types import SimpleNamespace
    expected=expected_contract()
    def run(argv,**kwargs):
        return SimpleNamespace(returncode=0,stdout=json.dumps(expected) if argv[4]=='cat' else 'config-files')
    with pytest.raises(r.PolicyError,match='not installed'):
        r.verify_debian_image_receipt('fixture/image:gnome',expected,run)


def test_generation_changes_context_content_before_hashing(tmp_path):
    import hashlib
    source=tmp_path/'tunaos.toml';source.write_bytes((ROOT/'tunaos.toml').read_bytes())
    targets=tunaos_config.prepare_desktops(tmp_path)
    def digest():
        return hashlib.sha256(b''.join(path.read_bytes() for path in targets)).hexdigest()
    before=digest()
    # Mutate only the primary source; preparation replaces the stale projection.
    old='"gnome-core",'
    assert source.read_text().count(old)==1
    source.write_text(source.read_text().replace(old,'"gnome-core", "fixture-native-tool",'))
    tunaos_config.prepare_desktops(tmp_path)
    assert digest()!=before
    profile=json.loads((tmp_path/'manifests/desktops/gnome-debian.yaml').read_text())
    assert profile['packages']['apt'][1]=='fixture-native-tool'
    unchanged={p:p.stat().st_mtime_ns for p in targets}
    tunaos_config.prepare_desktops(tmp_path)
    assert {p:p.stat().st_mtime_ns for p in targets}==unchanged


def test_invalid_primary_source_does_not_reuse_or_overwrite_desktop_adapters(tmp_path):
    source=tmp_path/'tunaos.toml';source.write_bytes((ROOT/'tunaos.toml').read_bytes())
    targets=tunaos_config.prepare_desktops(tmp_path)
    before={p:p.read_bytes() for p in targets}
    source.write_text(source.read_text()+'\ninvalid = [\n')
    with pytest.raises(tunaos_config.ConfigError):tunaos_config.prepare_desktops(tmp_path)
    assert {p:p.read_bytes() for p in targets}==before


def tracked_context_source(tmp_path):
    import subprocess
    root=tmp_path/'source';root.mkdir()
    (root/'tunaos.toml').write_bytes((ROOT/'tunaos.toml').read_bytes())
    (root/'executable.sh').write_text('#!/bin/sh\ntrue\n')
    (root/'executable.sh').chmod(0o755)
    subprocess.run(['git','init','-q',str(root)],check=True)
    subprocess.run(['git','-C',str(root),'add','.'],check=True)
    return root


def context_receipt(path):
    return json.loads((path/'desktop-context-receipt.json').read_text())


def test_two_target_contexts_ignore_stale_files_and_generation_order(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    root=tracked_context_source(tmp_path)
    stale=root/'manifests/desktop-contracts/obsolete.json';stale.parent.mkdir(parents=True)
    stale.write_text('stale receipt')
    def build(name,variant):
        return tunaos_config.prepare_debian_build_context(root,tmp_path/name,variant,'gnome',['linux/amd64'])
    with ThreadPoolExecutor(max_workers=2) as pool:
        first=pool.submit(build,'first','flounder')
        second=pool.submit(build,'second','flounder-sid')
        first,second=first.result(),second.result()
    stale.write_text('different stale receipt')
    sid_again=build('sid-again','flounder-sid')
    main_again=build('main-again','flounder')
    assert context_receipt(first)==context_receipt(main_again)
    assert context_receipt(second)==context_receipt(sid_again)
    assert context_receipt(first)['sha256']!=context_receipt(second)['sha256']
    for path,variant in [(first,'flounder'),(second,'flounder-sid')]:
        contracts=list((path/'manifests/desktop-contracts').rglob('*.json'))
        assert len(contracts)==1
        assert json.loads(contracts[0].read_text())['variant']==variant
        assert (path/'executable.sh').stat().st_mode & 0o777==0o755


def test_uncommitted_hand_edit_is_captured_and_changes_context_digest(tmp_path):
    root=tracked_context_source(tmp_path)
    before=tunaos_config.prepare_debian_build_context(root,tmp_path/'before','flounder','gnome',['linux/amd64'])
    source=root/'tunaos.toml'
    source.write_text(source.read_text().replace('"gnome-core",','"gnome-core", "fixture-native-tool",'))
    after=tunaos_config.prepare_debian_build_context(root,tmp_path/'after','flounder','gnome',['linux/amd64'])
    assert (after/'tunaos.toml').read_bytes()==source.read_bytes()
    assert context_receipt(before)['sha256']!=context_receipt(after)['sha256']
    contract=json.loads(next((after/'manifests/desktop-contracts').rglob('*.json')).read_text())
    assert 'fixture-native-tool' in contract['required']


def test_prepared_context_preserves_only_referenced_verified_local_assets(tmp_path):
    import hashlib
    root=tracked_context_source(tmp_path)
    assets=root/'manifests/fork-assets';assets.mkdir(parents=True)
    data=b'previously decoded fixture JPEG';digest=hashlib.sha256(data).hexdigest()
    asset=assets/f'{digest}.jpg';asset.write_bytes(data)
    (assets/'unreferenced.jpg').write_bytes(b'ignore me')
    payload=root/'manifests/fork-config.json'
    payload.write_text(json.dumps({'assets':{'wallpaper':{'path':f'fork-assets/{digest}.jpg','sha256':digest}}}))
    output=tunaos_config.prepare_debian_build_context(root,tmp_path/'prepared','flounder','gnome',['linux/amd64'])
    assert (output/'manifests/fork-config.json').read_bytes()==payload.read_bytes()
    assert list((output/'manifests/fork-assets').iterdir())[0].read_bytes()==data
    assert len(list((output/'manifests/fork-assets').iterdir()))==1
    asset.write_bytes(b'changed')
    with pytest.raises(tunaos_config.ConfigError,match='missing or has changed'):
        tunaos_config.prepare_debian_build_context(root,tmp_path/'invalid','flounder','gnome',['linux/amd64'])


def test_context_detects_edits_during_capture(tmp_path,monkeypatch):
    import shutil
    root=tracked_context_source(tmp_path)
    original=shutil.copy2
    def racing_copy(source,target,*args,**kwargs):
        result=original(source,target,*args,**kwargs)
        if Path(source).name=='tunaos.toml':
            (root/'executable.sh').write_text('#!/bin/sh\nfalse\n')
        return result
    monkeypatch.setattr(shutil,'copy2',racing_copy)
    with pytest.raises(tunaos_config.ConfigError,match='sources changed'):
        tunaos_config.prepare_debian_build_context(root,tmp_path/'raced','flounder','gnome',['linux/amd64'])
    assert not (tmp_path/'raced/desktop-context-receipt.json').exists()


@pytest.mark.parametrize('variant,arch',[('flounder','amd64'),('flounder','arm64'),('flounder-sid','amd64')])
def test_actual_apt_consumer_installs_selected_bound_contract(tmp_path,variant,arch):
    import os,subprocess,shutil
    if not shutil.which('yq'):pytest.skip('mikefarah yq required')
    root=tracked_context_source(tmp_path)
    context=tunaos_config.prepare_debian_build_context(root,tmp_path/'context',variant,'gnome',[f'linux/{arch}'])
    helper=context/'build_scripts/lib/desktop-contract.sh';helper.parent.mkdir(parents=True)
    helper.write_bytes((ROOT/'build_scripts/lib/desktop-contract.sh').read_bytes())
    source=(ROOT/'build_scripts/desktop/install-desktop.sh').read_text()
    block=source[source.index('\t# Install packages (under .packages.apt'):source.index('\t# Enable display manager',source.index('\t# Install packages (under .packages.apt'))]
    record=tmp_path/'record'
    script='''set -euo pipefail
pkg_install() { printf '%s\\n' "$@" > "$RECORD"; }
dpkg() { [[ "$1" == --print-architecture ]]; printf '%s\\n' "$ARCH"; }
'''+block
    env={**os.environ,'YQ':shutil.which('yq'),'_TD_CTX':str(context),'_TD_MANIFEST':str(context/'manifests/desktops/gnome-debian.yaml'),
         '_TD_APT_TYPE':'!!seq','IS_DEBIAN':'true','TUNAOS_IMAGE_FLAVOR':'gnome','_TD_DESKTOP':'gnome',
         'IMAGE_NAME_VARIANT':variant,'ARCH':arch,'RECORD':str(record)}
    result=subprocess.run(['bash','-c',script],env=env,text=True,capture_output=True)
    assert result.returncode==0,result.stderr
    expected=json.loads(next((context/'manifests/desktop-contracts').rglob('*.json')).read_text())
    assert record.read_text().splitlines()==expected['required']
    assert source.index('tunaos_desktop_contract_commit')>source.index('emit_packages_manifest')>source.index('.post_install_inline[]')


def test_build_engine_passes_isolated_context_and_containerfile(tmp_path):
    import subprocess
    text=(ROOT/'scripts/build-image-inner.sh').read_text()
    assert text.index('prepare-debian-context')<text.index('# Build scripts hash for cache invalidation')<text.index('build_primary_image()')
    assert "'.sha256' \"${BUILD_CONTEXT}/desktop-context-receipt.json\"" in text
    block=text[text.index('build_primary_image() {'):text.index('\n}',text.index('build_primary_image() {'))+2]
    context=tmp_path/'selected-context'
    script='''set -e
builder() { printf '%s\\n' "$@"; }
BUILDER=builder PLATFORM=linux/amd64 DESKTOP_FLAVOR=gnome PRE_CHUNK_TAG=fixture PULL_FLAG=--pull=never
BUILD_ARGS=(--build-arg FIXTURE=1)
BUILD_CONTEXT="$1"
BUILD_CONTAINERFILE="$1/Containerfile.debian"
'''+block+'\nbuild_primary_image\n'
    result=subprocess.run(['bash','-c',script,'--',str(context)],text=True,capture_output=True)
    assert result.returncode==0,result.stderr
    argv=result.stdout.splitlines()
    assert argv[-1]==str(context)
    assert argv[argv.index('--file')+1]==str(context/'Containerfile.debian')


@pytest.mark.parametrize('condition',[None,'debian-sid','debian-trixie'])
def test_ppa_condition_must_match_actual_consumer(condition):
    document=live()
    ppa={'repo':'ppa:hepp3n/cosmic-epoch'}
    if condition is not None:ppa['condition']=condition
    document['desktops']['cosmic']['packages']['apt']['ppa']=[ppa]
    with pytest.raises(r.PolicyError,match='missing required|explicit ubuntu'):
        r.validate(document)


def test_non_debian_variant_cannot_receive_debian_contract():
    import hashlib
    with pytest.raises(r.PolicyError,match='not supported Debian GNOME'):
        r.installation_contract(tunaos_config.load(),hashlib.sha256((ROOT/'tunaos.toml').read_bytes()).hexdigest(),
                                'yellowfin','gnome','linux/amd64',manager='apt',os_id='debian')


@pytest.mark.parametrize('command',['generate-debian-contract','verify-debian-image'])
def test_public_entrypoints_reject_wrong_native_target_before_output_or_image_access(command,tmp_path):
    import os,subprocess
    root=tracked_context_source(tmp_path)
    args=[sys.executable,str(ROOT/'scripts/config.py'),command,'--root',str(root),
          '--variant','yellowfin','--desktop','gnome','--platform','linux/amd64']
    if command=='verify-debian-image':args+=['--image','fixture/never-access:gnome']
    result=subprocess.run(args,text=True,capture_output=True)
    assert result.returncode==1
    assert 'not supported Debian GNOME' in result.stderr
    assert not (root/'manifests/desktop-contracts').exists()
