"""#3965 candidate isolation: inert callbacks only, never open host KVM or a VM.

Falsification: inject vsock credentials, widen KVM access, or permit a TCG
fallback and these command-boundary tests fail. Ordinary modes stay intact.
"""
import os
from pathlib import Path
import stat
import subprocess
import sys
from types import SimpleNamespace

import pytest
import yaml

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from lib.xfce_launch import check_kvm
SOURCE=(ROOT/'scripts/iso-e2e.sh').read_text()


def function(name):
    return name+'() {'+SOURCE.split(name+'() {',1)[1].split('\n}\n',1)[0]+'\n}\n'


@pytest.mark.parametrize('fault',[None,'not-root','denied','not-device','wrong-api','ioctl-denied'])
def test_direct_kvm_access_without_permission_mutation(fault):
    calls=[]
    def opener(path,flags):
        calls.append(('open',path,flags))
        if fault=='denied':raise PermissionError('inert denial')
        return 42
    def ioctl(fd,request,arg):
        calls.append(('ioctl',fd,request,arg))
        if fault=='ioctl-denied':raise PermissionError('inert ioctl denial')
        return 11 if fault=='wrong-api' else 12
    def run():
        check_kvm(geteuid=lambda:1000 if fault=='not-root' else 0,opener=opener,
            fstat=lambda fd:SimpleNamespace(st_mode=stat.S_IFREG if fault=='not-device' else stat.S_IFCHR),
            ioctl=ioctl,close=lambda fd:calls.append(('close',fd)))
    if fault:
        with pytest.raises((ValueError,PermissionError)):run()
    else:run()
    if fault=='not-root':assert calls==[]
    else:
        assert calls[0]==('open','/dev/kvm',os.O_RDWR|os.O_CLOEXEC)
        if fault!='denied':assert calls[-1]==('close',42)
    assert all(call[0] in ('open','ioctl','close') for call in calls)


def test_candidate_setup_never_invokes_injected_access_helpers(tmp_path):
    script=function('setup_vsock')+'''
modprobe() { echo forbidden >> "$TRACE"; }
sudo() { echo forbidden >> "$TRACE"; }
ssh-keygen() { echo forbidden >> "$TRACE"; }
socat() { echo forbidden >> "$TRACE"; }
VSOCK_ARGS=(injected)
setup_vsock
[[ ${#VSOCK_ARGS[@]} == 0 ]]
'''
    result=subprocess.run(['bash','-e','-c',script],capture_output=True,text=True,timeout=2,
        env=dict(os.environ,TUNAOS_XFCE_CANDIDATE='1',TRACE=str(tmp_path/'trace')))
    assert result.returncode==0,result.stderr
    assert not (tmp_path/'trace').exists()


@pytest.mark.parametrize('launcher',['boot_live_iso','strict_launch_installed'])
@pytest.mark.parametrize('candidate,injected,expected',[(True,False,91),(True,True,77),(False,True,91)])
def test_actual_launch_arguments_exclude_candidate_guest_credentials(tmp_path,launcher,candidate,injected,expected):
    disk=tmp_path/'inert-disk';disk.touch()
    # The QEMU command is a shell function that records argv and exits. No
    # image utility, VM, mount, device, or guest command can execute.
    # strict_launch_installed refuses to launch over a live owned QEMU via
    # strict_require_vm_stopped (f0cb2643); extract the real guard, with no
    # pidfile present, so the launcher runs exactly as it does in the script.
    helpers=function('candidate_require_no_injected_access')
    if launcher=='strict_launch_installed':helpers+=function('strict_require_vm_stopped')
    script=helpers+function(launcher)+'''
qemu-img() { exit 98; }
reset_qemu_sockets() { :; }
e2e_phase() { :; }
fake_qemu() { printf '%s\\n' "$@" > "$TRACE"; exit 91; }
QEMU=fake_qemu
QEMU_GPU_ARGS=()
E2E_SERIAL_ARGS=(-serial file:inert)
VSOCK_ARGS=()
if [[ "$INJECT" == 1 ]]; then
 VSOCK_ARGS=(-device vhost-vsock-pci,guest-cid=123 -smbios type=11,value=io.systemd.credential.binary:ssh.authorized_keys.root=inert)
fi
'''+(launcher+' "$INSTALL_DISK" "" cold\n' if launcher=='strict_launch_installed' else launcher+'\n')
    env=dict(os.environ,TUNAOS_XFCE_CANDIDATE=str(int(candidate)),INJECT=str(int(injected)),
        TRACE=str(tmp_path/'args'),OUTPUT_DIR=str(tmp_path),INSTALL_DISK=str(disk),SWAP_DISK=str(disk),SCRATCH_DISK=str(disk),
        QEMU_PIDFILE=str(tmp_path/'no-previous-vm.pid'))
    result=subprocess.run(['bash','-c',script],env=env,capture_output=True,text=True,timeout=2)
    assert result.returncode==expected,result.stderr
    trace=tmp_path/'args'
    if expected==77:assert not trace.exists()
    else:
        args=trace.read_text()
        assert ('vhost-vsock' in args) is (not candidate)
        assert ('ssh.authorized_keys' in args) is (not candidate)
        assert ('io.systemd.credential' in args) is (not candidate)


def test_workflow_candidate_skips_world_writable_kvm_and_checks_root_access():
    doc=yaml.safe_load((ROOT/'.github/workflows/iso-e2e.yml').read_text())
    steps=doc['jobs']['e2e']['steps']
    rule=next(s for s in steps if s.get('name')=='Enable KVM group permissions')
    assert rule['if']=="${{ !inputs.installed_boot_diagnostic && steps.filter.outputs.skip != 'true' && !inputs.candidate_xfce }}"
    assert 'MODE="0666"' in rule['run'] # ordinary-job policy is unchanged
    check=next(s for s in steps if s.get('name')=='Check candidate direct KVM access')
    assert check['if']=="${{ !inputs.installed_boot_diagnostic && steps.filter.outputs.skip != 'true' && inputs.candidate_xfce }}"
    assert check['run']=='sudo python3 scripts/preflight-xfce-candidate.py kvm'
    assert steps.index(check)<next(i for i,s in enumerate(steps) if s.get('name')=='Install QEMU and helpers')
    runner=(ROOT/'scripts/run-xfce-candidate.py').read_text()
    assert 'check_acceleration()' in runner
    assert "command.append('--no-kvm')" not in runner


def test_candidate_teardown_uses_acpi_without_ssh(tmp_path):
    script=function('poweroff_and_wait_vm')+'''
ssh_fake() { echo forbidden >> "$TRACE"; }
socat() { cat > "$ACPI"; }
sleep() { :; }
GUEST_SSH=(ssh_fake)
poweroff_and_wait_vm
'''
    result=subprocess.run(['bash','-c',script],capture_output=True,text=True,timeout=2,
        env=dict(os.environ,TUNAOS_XFCE_CANDIDATE='1',TRACE=str(tmp_path/'ssh'),ACPI=str(tmp_path/'acpi'),
                 QEMU_PIDFILE=str(tmp_path/'absent'),MONITOR_SOCK=str(tmp_path/'unused')))
    assert result.returncode==0,result.stderr
    assert not (tmp_path/'ssh').exists()
    assert (tmp_path/'acpi').read_text()=='system_powerdown\n'


def test_ordinary_vsock_setup_still_arms_existing_fallback(tmp_path):
    body=function('setup_vsock').replace('[[ ! -e /dev/vhost-vsock ]]','true').replace('[[ ! -w /dev/vhost-vsock ]]','false')
    script=body+'''
modprobe() { echo module >> "$TRACE"; }
socat() { echo VSOCK; }
ssh-keygen() { echo keygen >> "$TRACE"; echo inert-public-key > "${VSOCK_SSH_KEY}.pub"; }
VSOCK_ARGS=()
setup_vsock
declare -p VSOCK_ARGS
'''
    result=subprocess.run(['bash','-e','-c',script],capture_output=True,text=True,timeout=2,
        env=dict(os.environ,TUNAOS_XFCE_CANDIDATE='0',TRACE=str(tmp_path/'trace'),
                 VSOCK_SSH_KEY=str(tmp_path/'inert-key'),VSOCK_CID='123'))
    assert result.returncode==0,result.stderr
    assert (tmp_path/'trace').read_text()=='module\nkeygen\n'
    assert 'ssh.authorized_keys.root=' in result.stdout
    assert 'ssh.ephemeral-authorized_keys-all=' in result.stdout


@pytest.mark.parametrize('candidate',[True,False])
@pytest.mark.parametrize('timeout',[0,1])
def test_readiness_probe_does_not_use_ssh_for_candidate(tmp_path,candidate,timeout):
    script=function('wait_for_ready')+"""
e2e_phase() { :; }
date() { echo 0; }
sleep() { exit 79; }
sshpass() { echo ssh >> "$TRACE"; return 1; }
wait_for_ready
"""
    result=subprocess.run(['bash','-c',script],capture_output=True,text=True,timeout=2,
        env=dict(os.environ,TUNAOS_XFCE_CANDIDATE=str(int(candidate)),TIMEOUT=str(timeout),LIVE_MARKER='inert',
                 SERIAL_LOG=str(tmp_path/'absent'),TRACE=str(tmp_path/'trace')))
    assert result.returncode==(79 if timeout else 2),result.stderr
    assert (tmp_path/'trace').exists() is (not candidate)


def test_candidate_cannot_run_historical_smoke_with_inherited_ssh():
    doc=yaml.safe_load((ROOT/'.github/workflows/iso-e2e.yml').read_text())
    smoke=next(s for s in doc['jobs']['e2e']['steps'] if s.get('id')=='native_smoke')
    assert smoke['if']=="${{ !inputs.installed_boot_diagnostic && inputs.source == 'native-artifact' && inputs.native_run_id != format('{0}', github.run_id) && !inputs.candidate_xfce }}"
