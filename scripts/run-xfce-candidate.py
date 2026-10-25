#!/usr/bin/env python3
"""Run one exact native Bonito/XFCE artifact through the opt-in candidate path.

This entry point executes VMs only when explicitly invoked on an authorized
runner. Local tests substitute the harness command boundary, never a guest.
"""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import secrets as guest_random
import subprocess
import sys
from lib.xfce_candidate import TARGET, COMMIT

ROOT=Path(__file__).resolve().parents[1]


def run(args, execute=subprocess.run):
    output=args.output.resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError('candidate output directory must be fresh and empty')
    output.mkdir(mode=0o700,parents=True,exist_ok=True)
    output.chmod(0o700)
    report={'schema':'XFCECandidateRun/v1','target':list(TARGET),'status':'failed','phase':'preflight','qualified':False}
    try:
        spec=importlib.util.spec_from_file_location('native',ROOT/'scripts/native-iso-qualification.py')
        native=importlib.util.module_from_spec(spec);spec.loader.exec_module(native)
        env=dict(os.environ)
        required=('GITHUB_REPOSITORY','GITHUB_RUN_ID','GITHUB_RUN_ATTEMPT','TUNAOS_NATIVE_BINDING',
            'TUNAOS_NATIVE_ARTIFACT_ID','TUNAOS_NATIVE_ARCHIVE_DIGEST','TUNAOS_NATIVE_SOURCE_SHA',
            *('TUNAOS_QUAL_'+key.upper()+'_DIGEST' for key in native.INPUTS))
        if any(not env.get(key) for key in required):
            raise ValueError('same-run provenance or immutable inputs missing')
        if tuple(env.get(key,expected) for key,expected in zip(('VARIANT','FLAVOR','TUNAOS_QUAL_PLATFORM'),TARGET)) != TARGET:
            raise ValueError('candidate target mismatch; NVIDIA and other cells need separate evidence')
        binding=native.load(env['TUNAOS_NATIVE_BINDING'])
        expected={'repository':env['GITHUB_REPOSITORY'],'producer_run':int(env['GITHUB_RUN_ID']),
            'producer_attempt':int(env['GITHUB_RUN_ATTEMPT']),'artifact_id':int(env['TUNAOS_NATIVE_ARTIFACT_ID']),
            'archive_digest':env['TUNAOS_NATIVE_ARCHIVE_DIGEST'],'producer_sha':env['TUNAOS_NATIVE_SOURCE_SHA'],
            'media_digest':native.digest(args.iso),'producer_build_conclusion':'success'}
        if expected['repository']!='tuna-os/tunaOS' or any(binding.get(k)!=v for k,v in expected.items()):
            raise ValueError('artifact is not the same-run producer output')
        native.validate_artifact_binding({'resolved_inputs':{'media':expected['media_digest']},
            'artifact_binding':binding,'artifact_binding_digest':native.canonical(binding)})
        head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True,timeout=10).strip()
        if binding.get('harness_sha')!=head or binding['producer_sha']!=head:
            raise ValueError('producer/harness source mismatch')
        if env['TUNAOS_QUAL_MEDIA_DIGEST']!=expected['media_digest'] or env['TUNAOS_QUAL_INSTALLER_DIGEST']!='sha256:'+COMMIT:
            raise ValueError('admitted media/frontend digest mismatch')
        for key in native.INPUTS:
            if not native.sha(env['TUNAOS_QUAL_'+key.upper()+'_DIGEST']):
                raise ValueError('immutable input digest malformed')
        env.update(VARIANT=TARGET[0],FLAVOR=TARGET[1],TUNAOS_QUAL_PLATFORM=TARGET[2],
            TUNAOS_XFCE_CANDIDATE='1',TUNAOS_QUAL_EXECUTION_KIND='native-qemu',STRICT_PUBLISHED_MEDIA='1',
            TUNAOS_XFCE_USER='tuna'+''.join(guest_random.choice('abcdefhkmnprstuvwxyz') for _ in range(12)),TUNAOS_XFCE_PASSWORD=guest_random.token_hex(16),
            TUNAOS_WALKTHROUGH_LUKS_PASS=guest_random.token_hex(16))
        report['phase']='install-and-boot'
        command=['bash',str(ROOT/'scripts/iso-e2e.sh'),str(args.iso.resolve()),
            '--strict-offline-gui','--output',str(output),'--memory','8192']
        if env.get('KVM_FLAG')=='--no-kvm':
            command.append('--no-kvm')
        result=execute(command,env=env,cwd=ROOT,check=False)
        report['harness_exit_code']=result.returncode
        if result.returncode:
            raise ValueError('candidate harness failed')
        receipt=native.load(output/'qualification-evidence.json')
        if receipt.get('schema')!=native.DESKTOP_SCHEMA:
            raise ValueError('candidate receipt missing')
        native.validate(receipt)
        report.update(status='pass',phase='candidate-contract',receiptDigest=receipt['receiptDigest'])
        return 0
    finally:
        (output/'candidate-report.json').write_text(json.dumps(report,indent=2)+'\n')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--iso',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    try:
        return run(args)
    except (ValueError,KeyError,OSError,subprocess.SubprocessError):
        print('XFCE candidate failed; no new qualification is admitted',file=sys.stderr)
        return 1


if __name__=='__main__':
    raise SystemExit(main())
