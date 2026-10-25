#!/usr/bin/env python3
"""Inert recipe-boundary check against the immutable XFCE source checkout.

Only AST-extracted pure recipe functions run; no GTK, host_run, disk or guest
operation is imported or executed. No source code is copied into this repository.
"""
import argparse
import ast
from pathlib import Path
import subprocess
from types import SimpleNamespace

PIN='9259ef88876f0eabab2499edaf09829ded5dc609'


def check(root):
    head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip()
    if head!=PIN:
        raise ValueError('source checkout is not the reviewed immutable revision')
    source=root/'frontends/xfce/tuna_installer_xfce'
    def extract(path, name, cls=None):
        tree=ast.parse(path.read_text())
        nodes=tree.body
        if cls:
            nodes=next(node for node in nodes if isinstance(node,ast.ClassDef) and node.name==cls).body
        node=next(node for node in nodes if isinstance(node,ast.FunctionDef) and node.name==name)
        return ast.Module(body=[node],type_ignores=[])
    core={'BRANDING':SimpleNamespace(id='tunaos'),'needs_passphrase':lambda value:value=='luks-passphrase'}
    exec(compile(extract(source/'core.py','build_recipe'),str(source/'core.py'),'exec'),core)
    namespace={'core':SimpleNamespace(build_recipe=core['build_recipe'])}
    for name in ('needs_user_creation','selected_leaf','build_recipe'):
        exec(compile(extract(source/'app.py',name,'InstallerWindow'),str(source/'app.py'),'exec'),namespace)
    class Entry:
        def __init__(self,value): self.value=value
        def get_text(self): return self.value
    for mode in ('plain','luks'):
        password='syntheticnotlogged'
        pages={
            'source':SimpleNamespace(selection=lambda:{'live':True}),
            'destination':SimpleNamespace(selected_disk=lambda:{'path':'/dev/vda'}),
            'identity':SimpleNamespace(hostname=Entry('tuna-candidate'),username=Entry('tuna12345678'),
                fullname=Entry('tuna12345678'),password=Entry(password)),
            'setup':SimpleNamespace(default_filesystem=lambda _: 'ext4',subvol_check=SimpleNamespace(get_active=lambda:False),
                enc_type=lambda:'none' if mode=='plain' else 'luks-passphrase',pass1=Entry(password))}
        instance=SimpleNamespace(pages=pages)
        instance.selected_leaf=lambda:namespace['selected_leaf'](instance)
        instance.needs_user_creation=lambda:namespace['needs_user_creation'](instance)
        recipe=namespace['build_recipe'](instance)
        assert recipe['user']==dict(username='tuna12345678',fullname='tuna12345678',password=password,groups=['wheel'])
        assert recipe['image']=='' and recipe['disk']=='/dev/vda'
        assert recipe['selinuxDisabled'] is False
        assert 'composeFsBackend' not in recipe
        assert ('passphrase' in recipe['encryption'])==(mode=='luks')
    # Read the upstream's retained widget captures, never launch GTK/Xvfb.
    from lib.xfce_installer_driver import Screen
    captures=root/'frontends/xfce/docs/screenshots'
    for filename,label in (('01-welcome.png','Get started'),('04-setup.png','No encryption'),
                           ('05-identity.png','Username'),('06-confirm.png','Install'),
                           ('08-done.png','Restart now')):
        Screen(captures/filename).box(label)
    summary=Screen(captures/'06-confirm.png')
    assert summary.summary('Target disk')=='/dev/sda'
    assert summary.summary('Encryption')=='No encryption'
    print('PASS: OCR/control geometry on the exact source retained captures')
    print('PASS: pinned GUI widgets produce live-self-install and user recipes for plain/LUKS; no guest execution')
    print('Runtime caveat: source requests wheel; Grouper account creation/group policy must pass the real GUI run')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source',type=Path)
    check(parser.parse_args().source)
