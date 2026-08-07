#!/usr/bin/env bats
# No screen in the contract may be credited by a LOGIN GREETER.
#
# WHY THIS EXISTS. Run 31183217981's cosmic leg never got past
# cosmic-greeter — the installer was not running at all — and the parity
# report still said `done: true`. The greeter's power menu offers Restart,
# Power Off and Suspend, and "restart" and "reboot" were `done` keywords.
#
# That is the worst phantom row the matrix can publish: it reports a finished
# installation on a machine where the installer never started, which is the
# exact case the operator most needs to see.
#
# Every existing comment in installer-screens.yaml warns about one keyword
# that matched the wrong SCREEN. This warns about keywords that match
# something which is not a screen of ours at all.

SPEC="${BATS_TEST_DIRNAME}/../installer-screens.yaml"

# Text a stock greeter puts on screen. Deliberately generous — cosmic-greeter,
# GDM and SDDM between them show a clock, the username, a password prompt, and
# session/power/accessibility controls.
GREETER_TEXT="friday august 7 1:55 pm liveuser password login log in
sign in session select session suspend hibernate restart reboot power off
shut down shutdown accessibility keyboard layout settings users guest
authentication failed caps lock is on"

@test "no screen keyword is satisfied by a login greeter" {
  run python3 - "$SPEC" <<'PY'
import sys, yaml
greeter = """friday august 7 1:55 pm liveuser password login log in
sign in session select session suspend hibernate restart reboot power off
shut down shutdown accessibility keyboard layout settings users guest
authentication failed caps lock is on"""
spec = yaml.safe_load(open(sys.argv[1]))
bad = []
for screen in spec["screens"]:
    for kw in screen["keywords"]:
        if kw.lower() in greeter:
            bad.append(f"{screen['id']}: {kw!r}")
if bad:
    print("keywords a login greeter satisfies:")
    for b in bad:
        print("  " + b)
    sys.exit(1)
print("ok")
PY
  [ "$status" -eq 0 ] || {
    echo "$output" >&2
    false
  }
}

@test "done is still reachable from real finished-screen text" {
  # The converse. Tightening the keywords until a greeter cannot match is easy;
  # the risk is tightening until the real screens cannot match either. These
  # are the actual strings the frontends render.
  run python3 - "$SPEC" <<'PY'
import sys, yaml
real = [
    ("kde", "Finished Installation complete TunaOS has been installed. "
            "Remove the installation media and restart to boot into your new system."),
    ("gnome-upstream", "Skipjack is installed"),
]
spec = yaml.safe_load(open(sys.argv[1]))
done = [s for s in spec["screens"] if s["id"] == "done"][0]["keywords"]
missing = []
for name, text in real:
    if not any(k.lower() in text.lower() for k in done):
        missing.append(name)
if missing:
    print("done screen no longer credited for: " + ", ".join(missing))
    sys.exit(1)
print("ok")
PY
  [ "$status" -eq 0 ] || {
    echo "$output" >&2
    false
  }
}
