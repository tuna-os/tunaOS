"""Real pointer/key driver for XFCE GTK3 wizard at source 9259ef88.

Source: frontends/xfce/tuna_installer_xfce/{app,pages}.py. Never invokes
fisherman or writes a recipe. GUI fields alone select live self-install and user.
"""
import json
import os
import shutil
import hashlib
from pathlib import Path
import re
import subprocess
import time
import tempfile
from lib.gnome_installer_driver import Unverified, normal, ocr_rows, click_unix
from lib.xfce_candidate import TRANSITIONS


class Screen:
    def __init__(self, path):
        self.path = Path(path)
        with tempfile.NamedTemporaryFile(suffix='.png') as enlarged:
            subprocess.run(['convert', str(path), '-resize', '300%', enlarged.name],
                           capture_output=True, check=True, timeout=20)
            result = subprocess.run(['tesseract', enlarged.name, 'stdout', '--psm', '11', 'tsv'],
                                    capture_output=True, text=True, check=True, timeout=30)
        _, rows = ocr_rows(result.stdout)
        self.rows = [(text, tuple(value//3 for value in box)) for text,box in rows]
        self.lines = [text for text, _ in self.rows]

    def box(self, label):
        boxes = [box for text, box in self.rows if normal(text)==normal(label)
                 or (label=='No encryption' and normal(text)=='o no encryption')]
        if not boxes and label in ('Install','Restart now'):
            boxes=self.action_boxes(label)
        if len(boxes)!=1:
            raise Unverified('GUI control missing or ambiguous: '+label)
        return boxes[0]

    def action_boxes(self, label):
        # GTK suggested/destructive actions use colored backgrounds. Locate
        # bounded colored components, then read their actual label interiors.
        # Whole-frame OCR omits these labels in the source's retained captures.
        width,height=map(int,subprocess.check_output(['identify','-format','%w %h',str(self.path)],text=True).split())
        if width>1920 or height>1200:
            raise Unverified('framebuffer exceeds supported bounds')
        raw=subprocess.check_output(['convert',str(self.path),'-depth','8','rgb:-'],timeout=20)
        pixels=set()
        for y in range(height):
            for x in range(width):
                r,g,b=raw[3*(y*width+x):3*(y*width+x)+3]
                if max(r,g,b)-min(r,g,b)>70 and (b>r+40 or r>b+40):
                    pixels.add((x,y))
        boxes=[]
        while pixels:
            seed=pixels.pop(); component=[seed]; todo=[seed]
            while todo:
                x,y=todo.pop()
                for point in ((x-1,y),(x+1,y),(x,y-1),(x,y+1)):
                    if point in pixels:
                        pixels.remove(point);component.append(point);todo.append(point)
            left=min(p[0] for p in component);right=max(p[0] for p in component)
            top=min(p[1] for p in component);bottom=max(p[1] for p in component)
            if not (45<=right-left<=240 and 22<=bottom-top<=65):
                continue
            with tempfile.NamedTemporaryFile(suffix='.png') as crop:
                subprocess.run(['convert',str(self.path),'-crop',f'{right-left-12}x{bottom-top-12}+{left+6}+{top+6}',
                    '+repage','-resize','400%','-colorspace','gray','-negate',crop.name],check=True,capture_output=True,timeout=20)
                text=subprocess.check_output(['tesseract',crop.name,'stdout','--psm','7'],stderr=subprocess.DEVNULL,text=True,timeout=20).strip()
            if normal(text)==normal(label):
                boxes.append((left,top,right,bottom))
        return boxes

    def summary(self, label):
        anchor=self.box(label+':')
        center=(anchor[1]+anchor[3])/2
        rows=[text for text,box in self.rows if box[0]>anchor[2] and abs((box[1]+box[3])/2-center)<8]
        if len(rows)!=1:
            raise Unverified('summary value absent or ambiguous: '+label)
        return rows[0]

    def contains(self, text):
        return any(normal(text) in normal(line) for line in self.lines)

    def entry(self, label, labels):
        # GTK Grid column_spacing=12; entry follows the widest label in this
        # grid. A bounded interior point avoids theme-dependent widget borders.
        boxes = [self.box(item) for item in labels]
        box = self.box(label)
        return max(b[2] for b in boxes)+35, (box[1]+box[3])//2


def drive(outdir, mode, vnc, capture, keys, type_text, installer_digest, password,
          user, user_password, screen_factory=Screen, pointer=click_unix,
          sleep=time.sleep, clock=time.monotonic):
    if mode not in ('plain','luks') or not re.fullmatch(r'tuna[a-z0-9]{8,20}', user):
        raise ValueError('candidate mode/account invalid')
    for secret in (password, user_password):
        if not re.fullmatch(r'[a-z0-9]{16,64}', secret):
            raise ValueError('candidate credential invalid')
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    result = dict(driver='xfce-9259ef88', desktop='xfce', frontend='org.tunaos.InstallerXfce',
                  mode=mode, installer_digest=installer_digest, transitions=[],
                  frontmost=False, submitted=False, accepted=False, completed=False,
                  account_digest='sha256:'+hashlib.sha256(user.encode()).hexdigest(), source_selection='live-self-install')
    deadline = clock()+min(1800,int(os.environ.get('TUNAOS_XFCE_GUI_TIMEOUT','1800')))
    counter = 0

    def observe():
        nonlocal counter
        if clock() >= deadline or counter >= 400:
            raise Unverified('XFCE GUI deadline exceeded')
        path = capture(counter, 'xfce')
        counter += 1
        screen = screen_factory(path)
        if any(screen.contains(s) for s in ('Installation failed','Authentication required','No disk of at least')):
            raise Unverified('XFCE GUI reports failure or unexpected authentication')
        return screen

    def wait(text):
        for _ in range(30):
            screen=observe()
            if screen.contains(text):
                return screen
            sleep(1)
        raise Unverified('XFCE expected page not reached: '+text)

    def click(screen, label):
        x1,y1,x2,y2=screen.box(label)
        pointer(vnc,(x1+x2)//2,(y1+y2)//2)

    def field(screen, label, labels, value):
        x,y=screen.entry(label, labels)
        pointer(vnc,x,y)
        keys('ctrl-a')
        type_text(value)

    def advance(screen, label='Next'):
        click(screen,label)
        sleep(1)

    try:
        screen=wait('Get started'); screen.box('Get started')
        # Capture only before any credential input; later frames stay private.
        if isinstance(screen,Screen):
            shutil.copyfile(screen.path,outdir/'safe-welcome.png')
        result['frontmost']=True; result['transitions'].append('welcome')
        advance(screen,'Get started')
        screen=wait('What do you want to install?')
        live=[text for text,_ in screen.rows if '(this system)' in text]
        if len(live)!=1 or not screen.contains('available offline'):
            raise Unverified('unique offline live-self-install row missing')
        click(screen,live[0]); result['transitions'].append('source'); advance(screen)
        screen=wait('be installed?')
        devices=set(re.findall(r'/dev/[a-z]+[0-9]*', ' '.join(screen.lines)))
        if devices!={'/dev/vda'} or not screen.contains('will be erased'):
            raise Unverified('destination is not the sole owned /dev/vda disk')
        result['transitions'].append('destination'); advance(screen)
        screen=wait('Disk encryption')
        # The passphrase radio and its entry label share text; choose the radio
        # by keyboard from the unique first radio, preserving the source order.
        click(screen,'No encryption')
        if mode=='luks':
            keys('down'); sleep(1); screen=observe()
            # Passphrase occurs twice; Confirm uniquely anchors the second entry.
            x,y=screen.entry('Confirm',['Confirm'])
            x += 50
            pointer(vnc,x,y); type_text(password)
            keys('shift-tab'); type_text(password)
        result['transitions'].append('setup'); advance(observe())
        screen=wait('Name this computer')
        for label in ('Your account','Username','Full name','Password'):
            screen.box(label)
        field(screen,'Hostname',['Hostname'],'tuna-candidate')
        for label,value in (('Username',user),('Full name',user),('Password',user_password)):
            field(screen,label,['Username','Full name','Password'],value)
        result['transitions'].append('identity'); advance(observe())
        screen=wait('Confirm installation')
        for label,expected in (('Target disk','/dev/vda'),('Hostname','tuna-candidate'),('User',user)):
            if screen.summary(label)!=expected:
                raise Unverified('XFCE summary identity mismatch')
        if not screen.summary('Image') or not screen.summary('Filesystem'):
            raise Unverified('XFCE source/filesystem summary absent')
        expected='Passphrase' if mode=='luks' else 'No encryption'
        if screen.summary('Encryption')!=expected or not screen.contains('/dev/vda') or not screen.contains('erased'):
            raise Unverified('XFCE summary encryption/disk mismatch')
        result['transitions'].append('confirm')
        advance(screen,'Install'); result['submitted']=True
        screen=wait('Do not power off')
        if not screen.contains('Installing'):
            raise Unverified('XFCE progress title missing')
        result['accepted']=True; result['transitions'].append('progress')
        while True:
            screen=observe()
            if screen.contains('is installed'):
                if not screen.contains('Remove the installation'):
                    raise Unverified('XFCE completion instruction missing')
                screen.box('Restart now')
                result['transitions'].append('done'); result['completed']=True
                break
            sleep(5)
        if result['transitions']!=TRANSITIONS:
            raise Unverified('XFCE ordered transitions incomplete')
        return 0
    finally:
        # Passwords and raw OCR text are never serialized into this receipt.
        (outdir/'walkthrough-xfce.json').write_text(json.dumps(result,indent=2)+'\n')
