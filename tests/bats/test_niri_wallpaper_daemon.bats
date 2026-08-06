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

@test "the daemon each section ships is the one the shipped niri config spawns" {
  # The test above asks whether SOMETHING can draw a background. It cannot ask
  # whether anything ever starts it, and that is a separate hole: the config we
  # install as the compositor default names its daemon literally —
  #
  #   spawn-at-startup "swaybg" "-i" ".../tunaos-default.png" "-m" "fill"
  #
  # niri does not fail a build, exit non-zero, or log anything when a
  # spawn-at-startup binary is absent. So a section that swapped swaybg for
  # another daemon on this list would satisfy verify-branding-niri.sh AND the
  # assertion above, and still boot to a solid colour with the artwork sitting
  # unused on disk — a green check over the exact defect sailfin:niri had.
  #
  # Sections that ship no daemon at all are not this bug: they are the dms
  # branch (el10), which the check accepts deliberately, so they are left to
  # the assertion above rather than double-judged here.
  local config="${REPO_ROOT}/system_files/usr/share/niri/config.kdl"
  local exempt="cachyos"

  # Which daemon the config starts, read off the config, not restated.
  local spawned="" d
  for d in $(tr '|' ' ' <<<"$DAEMONS"); do
    if grep -qE "^spawn-at-startup \"${d}\"" "$config"; then spawned="$d"; break; fi
  done
  # No spawn line at all would mean the manifests ship a daemon nothing starts,
  # which is the same blank screen from the other end.
  [ -n "$spawned" ] || {
    echo "no spawn-at-startup for any of ($(tr '|' ' ' <<<"$DAEMONS")) in ${config#"$REPO_ROOT"/}" >&2
    return 1
  }

  run python3 - "${REPO_ROOT}" "${DAEMONS}" "${exempt}" "${spawned}" <<'EOF'
import json, sys, glob, os
import yaml

root, daemons, exempt, spawned = sys.argv[1], sys.argv[2].split('|'), sys.argv[3].split(), sys.argv[4]
bad = []
for path in sorted(glob.glob(os.path.join(root, 'manifests/desktops/niri*.yaml'))):
    doc = yaml.safe_load(open(path)) or {}
    for section, body in (doc.get('packages') or {}).items():
        if section in exempt:
            continue
        text = json.dumps(body)
        shipped = [d for d in daemons if d in text]
        if not shipped or spawned in shipped:
            continue
        bad.append(f"{os.path.basename(path)}:{section} ships {', '.join(shipped)}")

for b in bad:
    print(f"FAIL: {b}, but the config we install spawns {spawned!r},")
    print(f"      which that section does not. niri is silent about a")
    print(f"      spawn-at-startup it cannot exec, so the background stays blank.")
sys.exit(1 if bad else 0)
EOF
  [ "$status" -eq 0 ] || {
    echo "$output" >&2
    return 1
  }
}
