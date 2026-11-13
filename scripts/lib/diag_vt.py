"""DIAG ONLY (tunaOS#4538 and sailfin:xfce): when the live session never shows
the installer, dump kernel task state to serial and photograph a VT2 shell."""
from lib.visual_console import key_for

COMMANDS = (
    'clear; ps -eo pid,stat,wchan:16,args | grep -E "gree|cosm|plym|cat|Xway|Xorg|light|xfce|flatpak" | cut -c1-150',
    'clear; ls -l /dev/dri; loginctl --no-pager; systemctl --no-pager is-active display-manager greetd lightdm plymouth-quit plymouth-quit-wait; id',
    'clear; journalctl -b -o cat --no-pager -u display-manager -u greetd -u lightdm | tail -40',
    'clear; journalctl -b -o cat --no-pager -t tunaos-live-session -t cosmic-session -t cosmic-comp -t lightdm | tail -40',
    'clear; cat /var/log/lightdm/lightdm.log 2>&1 | tail -40',
    'clear; journalctl -b --no-pager -p warning | tail -40',
)


def probe(keys, observe, sleep):
    def typed(text):
        for c in text:
            keys(key_for(c) or {'|': 'shift-backslash', '*': 'shift-8'}[c])
    for k in ('alt-sysrq-t', 'alt-sysrq-w'):
        keys(k)
        sleep(3)
    keys('ctrl-alt-f2')
    sleep(4)
    observe('diag-vt2')
    typed('liveuser')
    keys('ret')
    sleep(4)
    keys('ret')
    sleep(4)
    observe('diag-vt2-login')
    for cmd in COMMANDS:
        typed(cmd)
        keys('ret')
        sleep(6)
        observe('diag-vt2-cmd')
    keys('ctrl-alt-f1')
    sleep(4)
    observe('diag-vt1')
