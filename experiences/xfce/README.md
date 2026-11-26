# XFCE experience

This is the contributor-owned home for TunaOS XFCE defaults: panel/session
behavior, greeter styling, and portable user defaults. Keep defaults in
`files/` portable across supported distributions. Do not add packages or
external repositories here.

## Screen reader

Orca's own autostart entry lists `OnlyShowIn=GNOME;MATE;Unity;Cinnamon;`, and
xfce4-session does not read `AutostartCondition`. So no XFCE session starts
Orca from the GSettings key
`org.gnome.desktop.a11y.applications screen-reader-enabled`.
`files/etc/xdg/autostart/tunaos-xfce-screen-reader.desktop` runs
`/usr/libexec/tunaos/xfce-screen-reader`, which starts `orca --replace` when
the key is on. The installer's first-login script (fishermand, ConfigureTarget
`accessibility`) sets that key. The wrapper waits up to 15 s for that script.
Orca itself comes from the desktop's package list (tunaOS#5015).
`tests/test_xfce_screen_reader.py` runs the wrapper with stand-ins.
