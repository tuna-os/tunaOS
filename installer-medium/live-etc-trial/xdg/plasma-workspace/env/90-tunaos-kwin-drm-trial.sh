# TEST ONLY (tmp/kde-greeter-wait): albacore:kde, black screen after login
# while plasmashell draws (run 46132247425). startplasma sources this before
# it starts kwin_wayland, so the session compositor gets the variables (a
# systemd user drop-in did not reach it, run 46136778491).
export KWIN_DRM_NO_AMS=1
export KWIN_DRM_USE_MODIFIERS=0
export KWIN_USE_OVERLAYS=0
