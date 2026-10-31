"""Authenticate an existing VT; serial is output only, never a login assumption."""
import base64
import hashlib
import json
import re
import secrets
import shlex
import time
import zlib


def key_for(char):
    if char.isascii() and char.isalpha():
        return char.lower() if char.islower() else 'shift-'+char.lower()
    if char.isdigit():
        return char
    return {' ':'spc','-':'minus','_':'shift-minus','.':'dot',',':'comma',
            '/':'slash',':':'shift-semicolon',';':'semicolon',"'":'apostrophe',
            '"':'shift-apostrophe','(':'shift-9',')':'shift-0','=':'equal',
            '+':'shift-equal','[':'bracket_left',']':'bracket_right',
            '$':'shift-4','&':'shift-7','!':'shift-1','\\':'backslash','>':'shift-dot'}.get(char)


def envelope(source, user, nonce, argument=False):
    # Root restores only the existing graphical session of the authenticated user.
    # No account, service, guest file, boot argument or login session is created.
    body = '''import contextlib,io,json,os,re,subprocess,time
assert os.environ.get('SUDO_USER') == USER, 'wrong sudo account'
def cmd(*args):
    return subprocess.check_output(args,text=True,timeout=10).strip()
sessions=[]
for line in cmd('loginctl','list-sessions','--no-legend','--no-pager').splitlines():
    sid=line.split()[0]
    assert re.fullmatch('[A-Za-z0-9]+',sid)
    props=dict(v.split('=',1) for v in cmd('loginctl','show-session',sid,'--no-pager').splitlines() if '=' in v)
    if props.get('Name')==USER and props.get('Class')=='user' and props.get('Remote')=='no' and props.get('Type') in ('x11','wayland'):
        sessions.append(props)
assert len(sessions)==1, 'missing/ambiguous graphical login'
vt=sessions[0].get('VTNr','')
assert vt.isdigit() and 1 <= int(vt) <= 12, 'invalid graphical VT'
subprocess.run(['chvt',vt],check=True,timeout=10)
for attempt in range(36):
    try:
        output=io.StringIO()
        with contextlib.redirect_stdout(output):
            exec(SOURCE, {})
        result=json.loads(output.getvalue())
        if result.get('pending') is True:
            raise ValueError('login pending')
        break
    except Exception:
        if attempt==35:
            raise
        time.sleep(5)
'''
    body = 'USER='+repr(user)+'\nSOURCE='+repr(source)+'\n'+body
    wrapped = "try:\n"+'\n'.join('    '+line for line in body.splitlines())+"\nexcept Exception as exc:\n    result={'error':type(exc).__name__}\n"
    wrapped += f"with open('/dev/ttyS0','w') as channel:\n    channel.write({('BEGIN_'+nonce+chr(10))!r}+json.dumps(result)+{(chr(10)+'END_'+nonce+chr(10))!r})\n    channel.flush()\n"
    # Imports for the error path also precede the guarded program.
    wrapped = 'import json\n'+wrapped
    data=wrapped.encode()
    encoded=base64.b64encode(zlib.compress(data)).decode()
    digest=hashlib.sha256(data).hexdigest()
    value='__import__(\"sys\").argv[1]' if argument else repr(encoded)
    launcher=f"import base64,zlib,hashlib; p=zlib.decompress(base64.b64decode({value})); assert hashlib.sha256(p).hexdigest()=='{digest}'; exec(p)"
    return (encoded,launcher) if argument else launcher


class VisualConsole:
    def __init__(self, user, password, key, capture, serial, sleep=time.sleep, clock=time.monotonic):
        self.user=user;self.password=password;self.key=key;self.capture=capture
        self.serial=serial;self.sleep=sleep;self.clock=clock

    def type(self, value):
        for char in value:
            key=key_for(char)
            if key is None:
                raise ValueError('unsupported keyboard character')
            self.key(key)
            self.sleep(.015)

    def prompt(self, pattern):
        for _ in range(20):
            text=self.capture()
            if re.search(pattern,text,re.I):
                return
            self.sleep(.5)
        raise ValueError('required visible authentication prompt absent')

    def execute(self, source, sudo=True):
        if sudo is not True:
            raise ValueError('visual observer needs normal administrative authorization')
        self.key('ctrl-alt-f3')
        self.prompt(r'login:\s*$')
        self.type(self.user);self.key('ret')
        self.prompt(r'password:\s*$')
        self.type(self.password);self.key('ret')
        # No capture occurs while a password is being typed.
        self.prompt(r'[$]\s*$')
        nonce=secrets.token_hex(16)
        token='AUTH'+secrets.token_hex(8)
        prompt=''.join('\\%03o'%ord(c) for c in token)
        encoded,launcher=envelope(source,self.user,nonce,argument=True)
        if len(encoded)>16384:
            raise ValueError('observer transfer exceeds bound')
        for offset in range(0,len(encoded),1500):
            assignment='TUNA_OBSERVER_DATA='+('' if offset==0 else '"$TUNA_OBSERVER_DATA"')+shlex.quote(encoded[offset:offset+1500])
            self.type(assignment);self.key('ret')
            self.prompt(r'[$]\s*$')
        command='sudo -k -p "$(printf \''+prompt+'\')" python3 -c '+shlex.quote(launcher)+' "$TUNA_OBSERVER_DATA"; unset TUNA_OBSERVER_DATA; exit'
        if len(command)>3900:
            raise ValueError('observer exceeds terminal line bound')
        self.type(command);self.key('ret')
        deadline=self.clock()+210
        submitted=False
        start='BEGIN_'+nonce;end='END_'+nonce
        while self.clock()<deadline:
            data=self.serial()
            match=re.search(re.escape(start)+r'\r?\n([^\r\n]{1,65536})\r?\n'+re.escape(end),data)
            if match:
                result=json.loads(match[1])
                if 'error' in result:
                    raise ValueError('authenticated observer failed')
                return result
            if not submitted:
                text=self.capture()
                # Prompt token is octal-encoded in command echo, never literal.
                if text.rstrip().endswith(token):
                    self.type(self.password);self.key('ret');submitted=True
            self.sleep(.5)
        raise ValueError('authenticated observer timed out')

    def close(self):
        pass
