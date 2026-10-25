#!/usr/bin/env python3
"""Pinned frontend preflight or authenticated installed GUI-session observation."""
import argparse
import importlib.util
import inspect
import json
import hashlib
import os
from pathlib import Path
import re
import subprocess
import sys
import time

from contracts.iso_qualification import DESKTOPS, validate_session
from lib.guest_console import Console
from lib.xfce_candidate import LIVE_PROBE, validate_frontend
from lib.xfce_installer_driver import Screen
from lib.gnome_installer_driver import click_unix
from lib.qemu_monitor import command as monitor


def type_text(path, value):
    # Fresh credentials deliberately use only this complete supported alphabet.
    if not re.fullmatch(r'[a-z0-9]+', value):
        raise ValueError('unsupported credential characters')
    for char in value:
        monitor(path,'sendkey '+char)
        time.sleep(.05)


def screenshot(args, label):
    ppm=args.directory/(label+'.ppm')
    png=args.directory/(label+'.png')
    monitor(args.monitor, 'screendump '+str(ppm))
    subprocess.run(['convert',str(ppm),str(png)],check=True,capture_output=True,timeout=20)
    return Screen(png)


def observer_source(args):
    spec=importlib.util.spec_from_file_location('session_probe',Path(__file__).with_name('observe-iso-session.py'))
    module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    source='import json, re, subprocess, pwd\nfrom pathlib import Path\n'
    source+='DESKTOPS='+repr(DESKTOPS)+'\n'
    source+=inspect.getsource(validate_session)+'\n'
    for function in (module.run,module.properties,module.observe):
        source+=inspect.getsource(function)+'\n'
    log=args.boot_log.read_text()
    markers=[line for line in log.splitlines() if line.startswith('TUNAOS_DESKTOP_CONTRACT_')]
    contract='\n'.join(markers)
    if 'TUNAOS_DESKTOP_CONTRACT_FAIL' in contract or not re.search(r'^TUNAOS_DESKTOP_CONTRACT_OK desktop=xfce\s',contract,re.M):
        raise ValueError('fresh boot serial lacks matching XFCE desktop contract')
    source+=f"result=observe('xfce','linux/amd64',{args.mode!r},{args.phase!r},contract_log={contract!r})\n"
    source+=f"account=pwd.getpwnam({os.environ['TUNAOS_XFCE_USER']!r})\n"
    source+="assert result['uid']==account.pw_uid and result['account']==account.pw_name, 'wrong installed account'\n"
    source+="args=Path('/proc/cmdline').read_text().split()\nassert any(a.startswith('ostree=') for a in args), 'not an OSTree boot'\n"
    source+="result['storage_backend']='ostree'\nprint(json.dumps(result))\n"
    return source


def collect(args, console_factory=Console, capture=screenshot, sleep=time.sleep):
    user='liveuser' if args.action=='live' else os.environ['TUNAOS_XFCE_USER']
    password='' if args.action=='live' else os.environ['TUNAOS_XFCE_PASSWORD']
    console=console_factory(args.console,user,password)
    try:
        if args.action=='live':
            result=console.execute(LIVE_PROBE,sudo=False)
            validate_frontend(result)
        else:
            # LightDM must visibly offer the account created through the wizard.
            screen=capture(args,'login-'+args.phase)
            box=screen.box(user)
            click_unix(str(args.vnc),(box[0]+box[2])//2,(box[1]+box[3])//2)
            sleep(1)
            screen=capture(args,'password-'+args.phase)
            box=screen.box('Password')
            click_unix(str(args.vnc),(box[0]+box[2])//2,(box[1]+box[3])//2)
            type_text(args.monitor,password)
            monitor(args.monitor,'sendkey ret')
            source=observer_source(args)
            # A failed command has no success frame; no result gets synthesized.
            # Poll using caught guest exceptions so an incomplete login stays
            # explicitly pending until the bounded deadline.
            guarded="try:\n"+'\n'.join('    '+line for line in source.splitlines())+"\nexcept Exception:\n    print(json.dumps({'pending':True}))"
            for _ in range(36):
                result=console.execute(guarded,sudo=False)
                if result.get('pending') is not True:
                    break
                sleep(5)
            else:
                raise ValueError('installed graphical login/observer did not complete')
            validate_session(result,'xfce','linux/amd64')
            if result['source_digest']!=os.environ['TUNAOS_QUAL_SOURCE_DIGEST']:
                raise ValueError('installed session source mismatch')
            if result.get('storage_backend')!='ostree' or result.get('account')!=user:
                raise ValueError('installed session account/backend mismatch')
        if args.action=='session':
            result['account_digest']='sha256:'+hashlib.sha256(result.pop('account').encode()).hexdigest()
        return result
    finally:
        console.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['live','session'])
    for name in ('console','monitor','vnc','directory','output'):
        parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--boot-log',type=Path)
    parser.add_argument('--mode',choices=['plain','luks'],required=True)
    parser.add_argument('--phase',choices=['cold','warm'],default='cold')
    args=parser.parse_args()
    args.directory.mkdir(parents=True,exist_ok=True)
    args.output.unlink(missing_ok=True)
    try:
        result=collect(args)
        args.output.write_text(json.dumps(result,indent=2)+'\n')
    except (ValueError,RuntimeError,OSError,subprocess.SubprocessError) as exc:
        # Do not print guest responses or credential-bearing command arguments.
        print('XFCE candidate phase failed: '+type(exc).__name__,file=sys.stderr)
        return 1
    return 0


if __name__=='__main__':
    raise SystemExit(main())
