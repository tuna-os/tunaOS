#!/usr/bin/env bats
# niri draws no wallpaper itself. Every niri image therefore needs either a
# wallpaper daemon, or dms/quickshell — which draws its own background.
# verify-branding-niri.sh enforces exactly that at build time:
#
#   FAIL: no wallpaper daemon (swaybg/swww/wpaperd) and no dms — background
#         will be blank
#
# sailfin:niri, LUKS run 31087934571. The fedora and pacman sections had
# carried swaybg since niri landed and the zypper section never did — the same
# one-of-N-near-identical-sections shape as the pcsc omit line, the erofs
# driver, and the KDE look-and-feel before it. A per-section assertion is the
# only thing that catches the (N+1)th.
#
# openSUSE is the base with nothing to fall back on: neither dms-greeter nor
# cosmic-greeter is packaged for Tumbleweed, which is why its greeter is
# gtkgreet under cage. el10 legitimately ships no wallpaper daemon and passes
# through the dms branch, so this test accepts either — asserting swaybg
# everywhere would be wrong, not merely strict.

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"

# The daemons verify-branding-niri.sh probes, kept in step with it below.
DAEMONS='swaybg|swww|wpaperd|hyprpaper'

@test "the daemon list here matches the one the branding check probes" {
  # If the check grows a daemon and this file does not, a section could satisfy
  # the check and still fail here — or worse, the reverse.
  local check="${REPO_ROOT}/build_scripts/checks/verify-branding-niri.sh"
  run grep -oE 'for b in [a-z ]+; do' "$check"
  [ "$status" -eq 0 ]
  local listed="${output#for b in }"
  listed="${listed%; do}"
  local want
  want="$(tr '|' ' ' <<<"$DAEMONS")"
  [ "$listed" = "$want" ]
}

@test "every niri package section can draw a background" {
  # A section passes if it lists a wallpaper daemon, or dms-greeter (whose
  # quickshell shell draws its own). Sections consumed only as an OVERLAY on a
  # already-built niri image are exempt: `cachyos` is applied by
  # Containerfile.overlay on top of marlin:niri, so it inherits that image's
  # swaybg rather than installing its own.
  local exempt="cachyos"
  run python3 - "${REPO_ROOT}" "${DAEMONS}" "${exempt}" <<'EOF'
import json, sys, glob, os
import yaml

root, daemons, exempt = sys.argv[1], sys.argv[2].split('|'), sys.argv[3].split()
bad = []
for path in sorted(glob.glob(os.path.join(root, 'manifests/desktops/niri*.yaml'))):
    doc = yaml.safe_load(open(path)) or {}
    for section, body in (doc.get('packages') or {}).items():
        if section in exempt:
            continue
        # Whole-section text: package lists, copr blocks and optional sets all
        # count, since any of them can be what installs the daemon.
        text = json.dumps(body)
        if any(d in text for d in daemons):
            continue
        if 'dms-greeter' in text:
            continue
        bad.append(f"{os.path.basename(path)}:{section}")

for b in bad:
    print(f"FAIL: {b} lists no wallpaper daemon and no dms-greeter.")
    print("      niri draws no background, so the desktop is a solid colour")
    print("      and verify-branding-niri.sh fails the build.")
sys.exit(1 if bad else 0)
EOF
  [ "$status" -eq 0 ] || {
    echo "$output" >&2
    return 1
  }
}
