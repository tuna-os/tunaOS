# vim: set ft=make :
# ujust reads /usr/share/ublue-os/just/00-entry.just from projectbluefin/common.
# That file imports 60-custom.just but not other names. This file imports the
# tunaOS recipe modules so that ujust shows them.

import? "/usr/share/ublue-os/just/60-tunaos-luks.just"
