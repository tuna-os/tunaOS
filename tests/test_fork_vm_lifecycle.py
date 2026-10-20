"""Pure lifecycle contract tests; native QEMU proof remains a separate gate."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import pytest

SPEC = importlib.util.spec_from_file_location('fork_vm', Path(__file__).resolve().parents[1] / 'scripts/qualify-fork-vm.py')
VM = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VM)


def make(private, phase, source, target, *args, **kwargs):
    info = target.stat()
    receipt = {'method': 'exclusive-new-file', 'path': str(target), 'device': info.st_dev, 'inode': info.st_ino}
    return VM.VM(private, phase, source, target, *args, target_creation=receipt, **kwargs)


@pytest.fixture
def disks(tmp_path, monkeypatch):
    tmp_path.chmod(0o700)
    source, target = tmp_path / 'source.qcow2', tmp_path / 'target.qcow2'
    source.write_bytes(b'source'); target.write_bytes(b'target')
    source.chmod(0o600); target.chmod(0o600)
    def run(args):
        path = args[-1]
        return json.dumps({'filename': path, 'format': 'qcow2', 'virtual-size': 64 * 1024**3,
                           'format-specific': {'type': 'qcow2', 'data': {}}})
    monkeypatch.setattr(VM, 'run', run)
    code, variables = tmp_path / 'code.fd', tmp_path / 'vars.fd'
    code.write_bytes(b'code'); variables.write_bytes(b'vars')
    monkeypatch.setattr(VM, 'FIRMWARE', [(str(code), str(variables))])
    return tmp_path, source, target


def test_target_boot_has_exact_target_no_source_no_network(disks):
    private, source, target = disks
    vm = make(private, 'target', None, target)
    args = vm.command()
    assert str(source) not in ' '.join(args)
    nodes = [json.loads(args[i+1]) for i,a in enumerate(args) if a == '-blockdev']
    assert len(nodes) == 1 and nodes[0]['file']['filename'] == str(target)
    assert '-netdev' not in args and args[args.index('-nic')+1] == 'none'
    assert 'usb-tablet,bus=xhci.0' in args
    assert (vm.directory / 'uefi-vars.fd').read_bytes() == b'vars'
    assert vm.target_spec['serial'].startswith('fork-target-')


def test_source_boot_is_restricted_to_loopback_ssh(disks):
    private, source, target = disks
    vm = make(private, 'source', source, target, 23456)
    args = vm.command()
    assert args[args.index('-netdev')+1] == 'user,id=net0,restrict=on,hostfwd=tcp:127.0.0.1:23456-:22'
    assert sum(a == '-blockdev' for a in args) == 2
    assert vm.source_spec['serial'] != vm.target_spec['serial']


@pytest.mark.parametrize('phase,source,port,memory', [('bad',True,23456,'8G'),('target',True,None,'8G'),('source',False,23456,'8G'),('target',False,23456,'8G'),('source',True,22,'8G'),('source',True,23456,'64G')])
def test_reject_unbounded_or_inconsistent_configuration(disks, phase, source, port, memory):
    private, src, target = disks
    with pytest.raises(ValueError): make(private, phase, src if source else None, target, port, memory)


def test_reject_source_target_alias(disks):
    private, source, target = disks
    with pytest.raises(ValueError): make(private, 'source', target, target, 23456)


def test_reject_symlink_disk(disks):
    private, source, target = disks
    alias = private/'alias'; alias.symlink_to(target)
    with pytest.raises(ValueError): make(private, 'target', None, alias)


def test_disk_replacement_fails_before_start(disks):
    private, source, target = disks
    vm = make(private, 'target', None, target)
    target.rename(private/'old'); target.write_bytes(b'new')
    with pytest.raises(ValueError): vm.start()


def test_firmware_requires_pair(disks, monkeypatch):
    private, source, target = disks
    monkeypatch.setattr(VM, 'FIRMWARE', [])
    with pytest.raises(ValueError): make(private, 'target', None, target).command()


def test_already_exited_vm_is_not_clean_shutdown(disks):
    private, source, target = disks
    vm = make(private, 'target', None, target)
    vm.process = SimpleNamespace(poll=lambda:0, returncode=0)
    with pytest.raises(RuntimeError, match='without an observed'): vm.stop()


def test_forced_cleanup_never_earns_clean_shutdown(disks):
    private, source, target = disks
    vm = make(private, 'target', None, target)
    vm.process = SimpleNamespace(poll=lambda:0, returncode=0)
    vm.close()
    with pytest.raises(ValueError, match='forcibly'): vm.stop()


def test_extra_block_not_silently_filtered(disks):
    private, source, target=disks
    vm=make(private,'source',source,target,23456); vm.command()
    raw=[{'device':name,'inserted':{'file':path,'drv':'raw','ro':name=='firmware-code'}} for name,path in vm.firmware.items()] + [{'device':'unknown','inserted':{'file':'/not/ours'}}]
    vm.qmp=SimpleNamespace(execute=lambda command, args=None:raw if command=='query-block' else 'serial')
    assert vm.disk_evidence()['query_block']['return']==raw[-1:]


def test_firmware_filter_requires_exact_mapping(disks):
    private, source, target=disks
    vm=make(private,'source',source,target,23456); vm.command()
    vm.qmp=SimpleNamespace(execute=lambda *a:[{'device':'firmware-code','inserted':{'file':'/wrong','drv':'raw','ro':True}}])
    with pytest.raises(ValueError,match='firmware'): vm.disk_evidence()


def test_missing_creation_receipt_fails(disks):
    private, source, target = disks
    with pytest.raises(ValueError, match='creation'):
        VM.VM(private, 'target', None, target, target_creation={})


def test_target_must_be_direct_child(disks):
    private, source, target = disks
    nested=private/'nested';nested.mkdir();other=nested/'target';other.write_bytes(b'x');other.chmod(0o600)
    with pytest.raises(ValueError,match='direct child'): make(private,'target',None,other)


@pytest.mark.parametrize('event,passed', [({'guest':True,'reason':'guest-shutdown'},True),({'guest':True,'reason':'guest-reset'},False),({'guest':False,'reason':'host-qmp-quit'},False)])
def test_shutdown_requires_exact_guest_event(disks,monkeypatch,event,passed):
    import io
    private, source, target=disks
    vm=make(private,'target',None,target)
    class Stream:
        def __init__(self): self.lines=iter([{'QMP':{}},{'return':{}},{'return':{}},{'event':'SHUTDOWN','data':event}]);self.writes=[]
        def readline(self): return (json.dumps(next(self.lines))+'\n').encode()
        def write(self,data):self.writes.append(data)
        def close(self):pass
    stream=Stream()
    sock=SimpleNamespace(settimeout=lambda _:None,connect=lambda _:None,makefile=lambda *a,**k:stream,close=lambda:None)
    monkeypatch.setattr(VM.socket,'socket',lambda *a:sock)
    vm.process=SimpleNamespace(poll=lambda:None,wait=lambda **k:0,returncode=0)
    if passed:
        vm.stop();assert vm.receipt['clean_exit'] is True
    else:
        with pytest.raises(RuntimeError,match='shutdown event'):vm.stop()
        assert 'clean_exit' not in vm.receipt


def test_firmware_missing_or_duplicate_rejected(disks):
    private,source,target=disks
    vm=make(private,'source',source,target,23456);vm.command()
    for raw in ([],[{'device':'firmware-code','inserted':{'file':vm.firmware['firmware-code'],'drv':'raw','ro':True}}]*2):
        vm.qmp=SimpleNamespace(execute=lambda *a:raw)
        with pytest.raises(ValueError,match='firmware'):vm.disk_evidence()


def test_metadata_dependency_mutation_rejected_at_start(disks,monkeypatch):
    private,source,target=disks
    vm=make(private,'target',None,target)
    monkeypatch.setattr(VM,'run',lambda args:json.dumps({'filename':str(target),'format':'qcow2','virtual-size':VM.DISK.TARGET_BYTES,'backing-filename':'/external','format-specific':{'type':'qcow2','data':{}}}))
    with pytest.raises(ValueError,match='dependency'):vm.start()


def test_shutdown_timeout_does_not_record_success(disks, monkeypatch):
    private, source, target = disks
    vm = make(private, 'target', None, target)
    def timeout(*args): raise TimeoutError('socket timed out')
    sock = SimpleNamespace(settimeout=lambda _: None, connect=timeout, close=lambda: None)
    monkeypatch.setattr(VM.socket, 'socket', lambda *args: sock)
    vm.process = SimpleNamespace(poll=lambda: None, returncode=None)
    with pytest.raises(RuntimeError, match='did not shut down cleanly'): vm.stop()
    assert 'clean_exit' not in vm.receipt


def test_full_install_workflow_keeps_read_only_permissions_and_public_evidence_only():
    import yaml
    root = Path(__file__).resolve().parents[1]
    path = root / '.github/workflows/fork-image-qualification.yml'
    workflow = yaml.safe_load(path.read_text())
    assert set(workflow['permissions'].values()) == {'read'}
    job = workflow['jobs']['canary']
    assert job['timeout-minutes'] == 180
    build = next(step['run'] for step in job['steps'] if step.get('name') == 'Qualify RPM canary, then apt canary')
    assert '--installed-proof-observer' in build
    install = next(step['run'] for step in job['steps'] if step.get('name','').startswith('Install exact fork'))
    assert 'qualify-fork-install.py' in install
    assert '--manifest "$out/prepared/${variant}--gnome--linux-amd64/manifests/fork-config.json"' in install
    collection = next(step['run'] for step in job['steps'] if step.get('name') == 'Collect bounded evidence')
    assert "path.suffix not in {'.json', '.png'}" in collection
    assert 'path.is_symlink()' in collection
    assert 'cp -r "$src/installed-proof"' not in collection


def test_qemu_stderr_diagnostics_are_bounded_and_separate_from_serial(disks):
    private, source, target = disks
    vm = make(private, 'target', None, target)
    (vm.directory / 'qemu.log').write_bytes(b'x' * 10000 + b'QEMU failure')
    vm.serial_path.write_text('private guest serial is not copied')
    vm.close()
    assert len(vm.receipt['qemu_stderr_tail']) == 8192
    assert vm.receipt['qemu_stderr_tail'].endswith('QEMU failure')
    assert 'private guest' not in vm.receipt['qemu_stderr_tail']


@pytest.mark.parametrize("phase", ["source", "target"])
def test_observer_channel_is_separate_from_console(disks, phase):
    private, source, target = disks
    vm = make(private, phase, source if phase == "source" else None, target,
              23456 if phase == "source" else None)
    args = vm.command()
    channels = [args[i + 1] for i, arg in enumerate(args) if arg == "-chardev"]
    assert channels == ["file,id=serial0,path=" + str(vm.serial_path),
                        "file,id=fork-observer,path=" + str(vm.observer_path)]
    assert vm.observer_path != vm.serial_path
    assert vm.observer_path.parent == vm.directory
    assert args[args.index("-serial") + 1] == "chardev:serial0"
    assert "virtio-serial-pci,id=fork-observer-controller" in args
    assert "virtserialport,bus=fork-observer-controller.0,chardev=fork-observer,name=org.tunaos.fork-observer" in args
    assert vm.receipt["observer_channel"]["shared_with_console"] is False


def test_preexisting_observer_sink_is_rejected_before_qemu(disks, monkeypatch):
    private, source, target = disks
    vm = make(private, 'target', None, target)
    victim = private / 'unrelated'
    victim.write_bytes(b'keep')
    vm.observer_path.symlink_to(victim)
    def forbidden(*args, **kwargs):
        raise AssertionError('QEMU must not start with a replaced evidence sink')
    monkeypatch.setattr(VM.subprocess, 'Popen', forbidden)
    with pytest.raises(FileExistsError):
        vm.start()
    assert victim.read_bytes() == b'keep'
