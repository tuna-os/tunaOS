#!/usr/bin/env bats
# BATS tests for remaining untested build scripts and live-iso scripts

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"

# ═══════════════════════════════════════════════════════════════════════════
# build_scripts/26-packages-post.sh
# ═══════════════════════════════════════════════════════════════════════════

@test "build_scripts/26-packages-post.sh: exists" {
  run test -f "${REPO_ROOT}/build_scripts/26-packages-post.sh"
  [ "$status" -eq 0 ]
}

@test "build_scripts/26-packages-post.sh: has bash shebang" {
  run head -1 "${REPO_ROOT}/build_scripts/26-packages-post.sh"
  [[ "$output" =~ ^#!/.*bash ]]
}

@test "build_scripts/26-packages-post.sh: has set flags" {
  run grep 'set -xeuo pipefail' "${REPO_ROOT}/build_scripts/26-packages-post.sh"
  [ "$status" -eq 0 ]
}

@test "build_scripts/26-packages-post.sh: defines SCRIPTS_PATH" {
  run grep 'SCRIPTS_PATH=' "${REPO_ROOT}/build_scripts/26-packages-post.sh"
  [ "$status" -eq 0 ]
}

@test "build_scripts/26-packages-post.sh: creates DOWNLOADS_DIR" {
  run grep 'DOWNLOADS_DIR' "${REPO_ROOT}/build_scripts/26-packages-post.sh"
  [ "$status" -eq 0 ]
}

@test "build_scripts/26-packages-post.sh: passes shellcheck" {
  if command -v shellcheck &>/dev/null; then
    run shellcheck --exclude=SC1091 "${REPO_ROOT}/build_scripts/26-packages-post.sh"
    [ "$status" -eq 0 ]
  else
    skip "shellcheck not installed"
  fi
}

# ═══════════════════════════════════════════════════════════════════════════
# live-iso/common/src/desktop-gnome.sh
# ═══════════════════════════════════════════════════════════════════════════

@test "live-iso/common/src/desktop-gnome.sh: exists" {
  run test -f "${REPO_ROOT}/live-iso/common/src/desktop-gnome.sh"
  [ "$status" -eq 0 ]
}

@test "live-iso/common/src/desktop-gnome.sh: has bash shebang" {
  run head -1 "${REPO_ROOT}/live-iso/common/src/desktop-gnome.sh"
  [[ "$output" =~ ^#!/.*bash ]]
}

@test "live-iso/common/src/desktop-gnome.sh: has set -euo pipefail" {
  run grep 'set -euo pipefail' "${REPO_ROOT}/live-iso/common/src/desktop-gnome.sh"
  [ "$status" -eq 0 ]
}

@test "live-iso/common/src/desktop-gnome.sh: configures GNOME dock" {
  run grep 'favorite-apps' "${REPO_ROOT}/live-iso/common/src/desktop-gnome.sh"
  [ "$status" -eq 0 ]
}

@test "live-iso/common/src/desktop-gnome.sh: disables suspend" {
  run grep 'suspend\|sleep' "${REPO_ROOT}/live-iso/common/src/desktop-gnome.sh"
  [ "$status" -eq 0 ]
}

@test "live-iso/common/src/desktop-gnome.sh: passes shellcheck" {
  if command -v shellcheck &>/dev/null; then
    run shellcheck --exclude=SC1091 "${REPO_ROOT}/live-iso/common/src/desktop-gnome.sh"
    [ "$status" -eq 0 ]
  else
    skip "shellcheck not installed"
  fi
}

# ═══════════════════════════════════════════════════════════════════════════
# live-iso/common/src/desktop-kde.sh
# ═══════════════════════════════════════════════════════════════════════════

@test "live-iso/common/src/desktop-kde.sh: exists" {
  run test -f "${REPO_ROOT}/live-iso/common/src/desktop-kde.sh"
  [ "$status" -eq 0 ]
}

@test "live-iso/common/src/desktop-kde.sh: has bash shebang" {
  run head -1 "${REPO_ROOT}/live-iso/common/src/desktop-kde.sh"
  [[ "$output" =~ ^#!/.*bash ]]
}

@test "live-iso/common/src/desktop-kde.sh: has set -euo pipefail" {
  run grep 'set -euo pipefail' "${REPO_ROOT}/live-iso/common/src/desktop-kde.sh"
  [ "$status" -eq 0 ]
}

@test "live-iso/common/src/desktop-kde.sh: configures SDDM autologin" {
  run grep 'sddm\|autologin' "${REPO_ROOT}/live-iso/common/src/desktop-kde.sh"
  [ "$status" -eq 0 ]
}

@test "live-iso/common/src/desktop-kde.sh: disables screen lock" {
  run grep 'lock\|suspend' "${REPO_ROOT}/live-iso/common/src/desktop-kde.sh"
  [ "$status" -eq 0 ]
}

@test "live-iso/common/src/desktop-kde.sh: passes shellcheck" {
  if command -v shellcheck &>/dev/null; then
    run shellcheck --exclude=SC1091 "${REPO_ROOT}/live-iso/common/src/desktop-kde.sh"
    [ "$status" -eq 0 ]
  else
    skip "shellcheck not installed"
  fi
}

@test "desktop experience contract covers upstream experience families" {
  local script="${REPO_ROOT}/build_scripts/checks/verify-desktop-experience.sh"
  run grep -F 'projectbluefin/bluefin-lts' "$script"
  [ "$status" -eq 0 ]
  run grep -F 'ublue-os/aurora' "$script"
  [ "$status" -eq 0 ]
  run grep -F 'zirconium-dev/zirconium' "$script"
  [ "$status" -eq 0 ]
}

@test "desktop experience contract covers every shipped DE" {
  local script="${REPO_ROOT}/build_scripts/checks/verify-desktop-experience.sh"
  for de in gnome kde niri cosmic xfce pantheon; do
    grep -qE "^${de}\)|\| ${de}\)|${de} \|" "$script"
  done
  # Runtime DM validation must use the distro-agnostic alias, not raw unit
  # names (gdm vs gdm3 vs lightdm drift across variants).
  grep -qF 'display-manager.service' "$script"
}

@test "every desktop with a Containerfile runtime-config call is in the contract family" {
  # configure-desktop-runtime.sh's DM case ends in `*) exit 0` — a desktop
  # that reaches it gets NO display-manager enable, NO graphical.target
  # default, and NO tunaos-desktop-contract.service, silently. That is not a
  # hypothetical: pantheon fell through it from its introduction until
  # 2026-08-07, so gurnard:pantheon passed every LUKS gate with
  # desktop_contract=absent (run 31074188677) — a green cell whose desktop
  # was never proven. Every desktop any Containerfile passes to the script
  # must therefore appear BOTH in its DM case and in the contract-family
  # case, so a new desktop stage cannot re-open the hole.
  local runtime="${REPO_ROOT}/build_scripts/desktop/configure-desktop-runtime.sh"
  local de fail=0
  while read -r de; do
    grep -qE "^${de}\)|\| ${de}\)|${de} \|" "$runtime" || {
      echo "FAIL: ${de} is passed to configure-desktop-runtime.sh by a" >&2
      echo "      Containerfile but has no DM branch — it exits 0 silently" >&2
      fail=1
    }
    # The contract-family case is the single pipe-separated line; the DM
    # branches are one-per-desktop. Require two distinct mentions so being
    # in the DM case alone (or the family alone) is not enough.
    [ "$(grep -cE "^${de}\)|\| ${de}\)|${de} \|" "$runtime")" -ge 2 ] || {
      echo "FAIL: ${de} appears in only one of the two cases in" >&2
      echo "      configure-desktop-runtime.sh (DM branch + contract family" >&2
      echo "      are both required)" >&2
      fail=1
    }
  done < <(grep -hoE 'configure-desktop-runtime\.sh [a-z]+' "${REPO_ROOT}"/Containerfile.* |
    awk '{print $2}' | sort -u)
  [ "$fail" -eq 0 ]
}

@test "xfce DM selection defers to the apt family's default-display-manager claim" {
  # Debian-family DMs (gdm3, lightdm) consult /etc/X11/default-display-manager
  # at startup and refuse to run when it names the other. Preferring
  # lightdm-if-present enabled a Recommends-pulled, debconf-rejected lightdm
  # on grouper:xfce — six crash-loops in the installed serial, gdm3 unenabled,
  # desktop_contract=absent under green LUKS gates (run 31181743606). The
  # branch must read the distro's own claim first; unit-existence fallbacks
  # only apply when no claim exists.
  #
  # Comments stripped before every grep: the rationale comments in the script
  # name the same file, and a test the comment can satisfy pins nothing.
  local runtime="${REPO_ROOT}/build_scripts/desktop/configure-desktop-runtime.sh"
  local code
  code="$(grep -v '^[[:space:]]*#' "$runtime")"
  grep -qF 'cat /etc/X11/default-display-manager' <<<"$code" || {
    echo "FAIL: xfce DM selection no longer reads default-display-manager;" >&2
    echo "      a Recommends-pulled lightdm will again beat the debconf DM" >&2
    return 1
  }
  # The claim must be consulted BEFORE the lightdm unit-existence preference.
  local xfce_branch claim_line lightdm_line
  xfce_branch="$(awk '/^xfce\)/{f=1} f{print} f&&/;;/{exit}' "$runtime" | grep -v '^[[:space:]]*#')"
  claim_line="$(grep -n 'default-display-manager' <<<"$xfce_branch" | head -1 | cut -d: -f1)"
  lightdm_line="$(grep -n 'list-unit-files lightdm' <<<"$xfce_branch" | head -1 | cut -d: -f1)"
  [ -n "$claim_line" ] && [ -n "$lightdm_line" ] && [ "$claim_line" -lt "$lightdm_line" ] || {
    echo "FAIL: the default-display-manager claim must be checked before the" >&2
    echo "      lightdm unit-existence fallback in the xfce branch" >&2
    return 1
  }
}

@test "disk gate requires the desktop contract marker" {
  # The gate wakes on either marker (both prove the contract service ran)
  # but only OK passes; FAIL surfaces its reason lines and exits nonzero.
  # --contract selects the marker prefix; desktop is the default and base
  # cells assert TUNAOS_BASE_CONTRACT instead.
  run grep -F 'TUNAOS_DESKTOP_CONTRACT_(OK|FAIL)' "${REPO_ROOT}/scripts/iso-e2e.sh"
  [ "$status" -eq 0 ]
  grep -qF 'CONTRACT_PREFIX="TUNAOS_DESKTOP_CONTRACT"' "${REPO_ROOT}/scripts/iso-e2e.sh"
  grep -qF 'CONTRACT_PREFIX="TUNAOS_BASE_CONTRACT"' "${REPO_ROOT}/scripts/iso-e2e.sh"
  grep -qF 'contract FAILED:' "${REPO_ROOT}/scripts/iso-e2e.sh"
  # The FLAG must be parsed, not just the mapping present: the base Gate's
  # first sailfin run (32047331620) died in 0.05s on 'Unknown flag:
  # --contract' because the disk-mode logic landed without a parser case.
  grep -qE '^\s+--contract\)' "${REPO_ROOT}/scripts/iso-e2e.sh"
}

@test "runtime contract never asserts graphical.target is active" {
  # The contract service is WantedBy=graphical.target; targets gain implicit
  # After= on their wants, so is-active graphical.target inside the service
  # self-deadlocks into a guaranteed failure. get-default is the safe assert.
  run grep -F 'is-active --quiet graphical.target' \
    "${REPO_ROOT}/build_scripts/checks/verify-desktop-experience.sh"
  [ "$status" -ne 0 ]
  grep -qF 'systemctl get-default' \
    "${REPO_ROOT}/build_scripts/checks/verify-desktop-experience.sh"
}

@test "desktop installer makes graphical target the boot default" {
  run grep -F 'systemctl set-default graphical.target' \
    "${REPO_ROOT}/build_scripts/desktop/install-desktop.sh"
  [ "$status" -eq 0 ]
}

@test "every contract-required application is declared in its manifests" {
  # The contract runs at BUILD time, so a requirement that some variant's
  # manifest never asks for turns a working build red. Each application the
  # contract demands must therefore be named in every manifest that builds
  # that desktop. This is the check that keeps the gate honest as manifests
  # drift — it is why the KDE contract asserts dolphin and konsole but not
  # xdg-desktop-portal-kde (absent from the emerge list, and guppy builds KDE).
  local script="${REPO_ROOT}/build_scripts/checks/verify-desktop-experience.sh"
  local fail=0
  # desktop:command:manifest,manifest,...
  local specs=(
    "kde:dolphin:kde.yaml,kde-arch.yaml,kde-debian.yaml"
    "kde:konsole:kde.yaml,kde-arch.yaml,kde-debian.yaml"
    "xfce:thunar:xfce.yaml,xfce-arch.yaml"
  )
  # NB: a plain-list match is the point. cosmic-files is declared inside
  # cosmic.yaml's el10 COPR block, where installs are best-effort — indentation
  # alone would match it and wrongly imply the package is guaranteed. That is
  # why cosmic is absent from this table and from the contract.
  for spec in "${specs[@]}"; do
    local de="${spec%%:*}" rest="${spec#*:}"
    local cmd="${rest%%:*}" manifests="${rest#*:}"
    # The contract must actually require it...
    if ! grep -qF "require_command $cmd" "$script"; then
      echo "FAIL: contract does not require $cmd for $de" >&2
      fail=1
    fi
    # ...and every manifest that builds this desktop must declare it.
    local IFS=,
    for m in $manifests; do
      if ! grep -qE "^\s*-\s+${cmd}\s*$" "${REPO_ROOT}/manifests/desktops/${m}"; then
        echo "FAIL: contract requires $cmd for $de but ${m} never installs it" >&2
        fail=1
      fi
    done
  done
  [ "$fail" -eq 0 ]
}

@test "flatpak baseline: manifests, preinstall script and contract cannot drift" {
  # Same discipline as the contract-required-application table above: every
  # piece of curated Flatpak content is (a) laid down by a post_install
  # script every desktop manifest lists, and (b) asserted by the build
  # contract — change any one of the three and this test names the others.
  local contract="${REPO_ROOT}/build_scripts/checks/verify-desktop-experience.sh"
  local preinstall="${REPO_ROOT}/build_scripts/desktop/flatpak-preinstall.sh"
  local remote="${REPO_ROOT}/build_scripts/desktop/tuna-flatpak-remote.sh"
  local fail=0

  # (a) every desktop manifest runs both post_install scripts.
  local m
  for m in "${REPO_ROOT}"/manifests/desktops/*.yaml; do
    for script in tuna-flatpak-remote.sh flatpak-preinstall.sh; do
      if ! grep -qE "^\s*-\s+${script}\s*$" "$m"; then
        echo "FAIL: $(basename "$m") post_install never runs ${script}" >&2
        fail=1
      fi
    done
  done

  # (b) the remote script bakes Flathub, and the contract requires it.
  grep -qF 'flathub.flatpakrepo' "$remote" || { echo "FAIL: tuna-flatpak-remote.sh no longer bakes flathub" >&2; fail=1; }
  grep -qF "require_glob '/etc/flatpak/remotes.d/flathub.flatpakrepo'" "$contract" || { echo "FAIL: contract does not require the flathub remote" >&2; fail=1; }
  grep -qF "require_glob '/usr/share/flatpak/preinstall.d/*.preinstall'" "$contract" || { echo "FAIL: contract does not require a preinstall declaration" >&2; fail=1; }

  # (c) the app set is identical in the script that declares it and the
  # contract that asserts it — extracted from both, compared as sets.
  local declared asserted
  declared="$(grep -oE '^_fp_add_app [A-Za-z0-9._-]+' "$preinstall" | awk '{print $2}' | sort)"
  asserted="$(grep -oE 'for _fp_app in [A-Za-z0-9._ -]+;' "$contract" | sed 's/for _fp_app in //; s/;$//' | tr ' ' '\n' | sed '/^$/d' | sort)"
  [ -n "$declared" ] || { echo "FAIL: no _fp_add_app lines found in flatpak-preinstall.sh" >&2; fail=1; }
  if [ "$declared" != "$asserted" ]; then
    echo "FAIL: preinstall set drifted — script declares [$declared] but contract asserts [$asserted]" >&2
    fail=1
  fi

  # (d) the service that makes declarations real is enabled by the script
  # and enforced by the contract wherever the unit exists.
  grep -qF 'systemctl enable flatpak-preinstall.service' "$preinstall" || { echo "FAIL: flatpak-preinstall.sh does not enable the service" >&2; fail=1; }
  grep -qF 'flatpak-preinstall.service is shipped but not enabled' "$contract" || { echo "FAIL: contract does not enforce the preinstall service" >&2; fail=1; }

  [ "$fail" -eq 0 ]
}

@test "greetd greeter degrades to software rendering without a render node" {
  # cage is wlroots-based: on a VM with virtio-gpu but no virgl there is a DRM
  # card and NO render node, GL init fails, cage exits and greetd restart-loops
  # on a black screen. Boot-time detection is required — a baked-in renderer
  # either breaks virgl-less VMs or needlessly softens every GPU machine.
  local script="${REPO_ROOT}/build_scripts/desktop/greetd-gtkgreet.sh"
  grep -qF '/dev/dri/renderD*' "$script"
  grep -qF 'WLR_RENDERER=pixman' "$script"
  # greetd must launch the wrapper, not cage directly, or the detection never runs.
  grep -qF 'command = "/usr/libexec/tunaos/greetd-session"' "$script"
  run grep -F 'command = "cage -s --' "$script"
  [ "$status" -ne 0 ]

  # Behavioural: extract the wrapper and prove BOTH branches. The probed path
  # is redirected into the test tmpdir so the result does not depend on whether
  # the machine running the tests happens to have a GPU.
  local base="${BATS_TEST_TMPDIR}/dri"
  local w="${BATS_TEST_TMPDIR}/greetd-session"
  awk '/<<.SESSION_EOF.$/{f=1;next} /^SESSION_EOF$/{f=0} f' "$script" \
    | sed -e "s|/dev/dri/renderD\*|${base}/renderD*|" \
      -e "s|/dev/dri/card\*|${base}/card*|" \
      -e 's|^\tsleep 0.5|\t:|' \
      -e 's|^exec cage.*|echo "R=${WLR_RENDERER:-hw}"|' > "$w"

  # No render node (virgl-less VM) -> software renderer. card* present so the
  # wait loop does not spin.
  mkdir -p "$base"
  touch "${base}/card0"
  run bash "$w"
  [ "$status" -eq 0 ]
  [[ "$output" == *"R=pixman"* ]]

  # Render node present (real GPU) -> left on hardware GL.
  touch "${base}/renderD128"
  run bash "$w"
  [ "$status" -eq 0 ]
  [[ "$output" == *"R=hw"* ]]

  # The wait loop must be bounded: with no DRM device at all it still has to
  # exec the greeter rather than hang greetd forever.
  rm -f "${base}"/card0 "${base}"/renderD128
  run bash "$w"
  [ "$status" -eq 0 ]
  [[ "$output" == *"R=pixman"* ]]
}

@test "greetd greeter account is resolved, not hardcoded" {
  # greetd getpwnam()s the configured user and chowns its socket to it during
  # startup, so a name that does not resolve kills it in milliseconds: "unable
  # to get user info", exit 1, Restart=always, display-manager.service never
  # active. Fedora/EL name that account `greetd`; openSUSE moved it into
  # system-user-greeter, which creates `greeter` and no `greetd` user at all —
  # which is why sailfin:niri booted to a black screen with zero failed units.
  local script="${REPO_ROOT}/build_scripts/desktop/greetd-gtkgreet.sh"
  run grep -F 'user = "greetd"' "$script"
  [ "$status" -ne 0 ]
  grep -qF 'user = "${_GG_USER}"' "$script"
  # An unquoted heredoc, or the name is written literally.
  grep -qE '<<GREETD_EOF$' "$script"

  # Behavioural: extract the probe and drive all three cases against a stub
  # getent, so the result does not depend on the accounts that happen to exist
  # on the machine running the suite.
  local probe="${BATS_TEST_TMPDIR}/probe.sh"
  sed -n '/^\t_GG_USER=""$/,/^\techo "greetd greeter account/p' "$script" \
    | sed -e 's/^\t//' -e 's/^\treturn 1$/exit 1/' -e 's/^return 1$/exit 1/' >"$probe"
  grep -q 'getent passwd' "$probe"

  local stub="${BATS_TEST_TMPDIR}/bin"
  mkdir -p "$stub"
  cat >"${stub}/getent" <<'STUB'
#!/usr/bin/env bash
# Only the accounts named in EXISTING_USERS resolve.
for u in ${EXISTING_USERS:-}; do
  [[ "$2" == "$u" ]] && { echo "$u:x:900:900::/var/lib/greetd:/usr/sbin/nologin"; exit 0; }
done
exit 2
STUB
  chmod +x "${stub}/getent"

  # openSUSE: only `greeter` exists.
  run env EXISTING_USERS=greeter PATH="${stub}:${PATH}" bash "$probe"
  [ "$status" -eq 0 ]
  [[ "$output" == *"greetd greeter account: greeter"* ]]

  # Fedora/EL: only `greetd` exists.
  run env EXISTING_USERS=greetd PATH="${stub}:${PATH}" bash "$probe"
  [ "$status" -eq 0 ]
  [[ "$output" == *"greetd greeter account: greetd"* ]]

  # Neither: fail the build instead of shipping a greeter that cannot start.
  run env EXISTING_USERS= PATH="${stub}:${PATH}" bash "$probe"
  [ "$status" -ne 0 ]
  [[ "$output" == *"no greetd greeter account found"* ]]
}

@test "desktop installer claims the display-manager.service alias" {
  # openSUSE's displaymanager-sysconfig owns /etc/systemd/system/display-manager.service
  # and points it at its own legacy launcher. systemd refuses to write an
  # [Install] Alias over an existing symlink, so `systemctl enable <dm>` fails
  # outright and safe_enable swallows it — the alias keeps resolving to
  # display-manager-legacy.service. The runtime contract asserts on that alias,
  # so a working desktop fails its own contract unless the installer forces it.
  local script="${REPO_ROOT}/build_scripts/desktop/install-desktop.sh"
  grep -qF '/etc/systemd/system/display-manager.service' "$script"
  # It must be forced (ln -sf), not left to systemctl enable.
  grep -qF 'ln -sf "/usr/lib/systemd/system/${_TD_DM}.service" \' "$script"
}

@test "desktop installer does not stomp a valid display-manager alias" {
  # Plasma 6.6 renamed SDDM to PlasmaLogin. plasma-login-manager sets
  # display-manager.service -> plasmalogin.service and does NOT obsolete sddm,
  # so both units exist on yellowfin:kde while kde.yaml still says
  # display_manager: sddm. Forcing the alias unconditionally would repoint
  # every EL10/Fedora KDE image away from the DM the distro picked and
  # re-create tunaOS#824 (autologin written for one DM, another one running).
  # The force must be scoped to absent/dangling/legacy-shim only.
  local script="${REPO_ROOT}/build_scripts/desktop/install-desktop.sh"
  grep -qF 'display-manager-legacy.service' "$script"
  grep -qF 'leaving it' "$script"
  # The bare unconditional force must be gone.
  run grep -cE '^\t\tln -sf "/usr/lib/systemd/system/\$\{_TD_DM\}\.service" \\$' "$script"
  [ "$output" -le 1 ]
}

@test "desktop installer reads both shapes of a zypper section" {
  # The zypper section is a plain list on most desktops and a map (packages +
  # display_manager) on XFCE. mikefarah yq ERRORS when indexing a sequence
  # with a string, and `//` rescues a null, not an error — so the shape has to
  # be branched on explicitly, exactly as the apt and el10 paths do.
  local script="${REPO_ROOT}/build_scripts/desktop/install-desktop.sh"
  grep -qF ".packages.zypper | type" "$script"
  grep -qF '.packages.zypper.packages[]' "$script"
  grep -qF '.packages.zypper[]' "$script"
}

@test "desktop installer refuses to build a zypper image with no desktop" {
  # Parsing zero packages used to produce a desktop-flavored image containing
  # no desktop, and still exit 0. The pacman and apt paths already fail loudly
  # here; zypper must too.
  run grep -F 'This would yield an image tagged ${_TD_DESKTOP} with no desktop in it.' \
    "${REPO_ROOT}/build_scripts/desktop/install-desktop.sh"
  [ "$status" -eq 0 ]
}

@test "every zypper desktop installs the display manager it enables" {
  # sailfin:xfce shipped with NO display manager enabled: the manifest's
  # top-level display_manager is gdm (right for Fedora/EL10) but openSUSE's
  # XFCE installs lightdm. safe_enable no-ops on a missing unit and the
  # graphical.target.wants link is guarded by the unit file existing, so the
  # image booted to graphical.target with no greeter and no build error.
  # Resolve the DM the same way install-desktop.sh does — per-section override
  # beats the top-level key — and assert the list actually installs it.
  command -v yq &>/dev/null || skip "yq not installed"
  for manifest in "${REPO_ROOT}"/manifests/desktops/*.yaml; do
    local shape dm pkgs
    # yq reports a missing node as the tag "!!null", not "null".
    shape="$(yq -r '.packages.zypper | type' "$manifest")"
    [ "$shape" = "!!null" ] && continue

    if [ "$shape" = "!!map" ]; then
      pkgs="$(yq -r '.packages.zypper.packages[]' "$manifest")"
      dm="$(yq -r '.packages.zypper.display_manager // ""' "$manifest")"
    else
      pkgs="$(yq -r '.packages.zypper[]' "$manifest")"
      dm=""
    fi
    [ -n "$dm" ] || dm="$(yq -r '.display_manager // ""' "$manifest")"
    [ -n "$dm" ] || continue

    # On openSUSE the display manager's package name matches its unit name.
    if ! grep -qx -- "$dm" <<<"$pkgs"; then
      echo "FAIL: $(basename "$manifest") enables ${dm}.service but its zypper list never installs ${dm}" >&2
      return 1
    fi
  done
}

@test "Ubuntu desktop stages configure display manager after package installation" {
  run grep -F 'configure-desktop-runtime.sh niri' "${REPO_ROOT}/Containerfile.ubuntu"
  [ "$status" -eq 0 ]
  grep -q 'systemctl enable "${dm}.service"' \
    "${REPO_ROOT}/build_scripts/desktop/configure-desktop-runtime.sh"
  grep -q 'tunaos-desktop-contract.service' \
    "${REPO_ROOT}/build_scripts/desktop/configure-desktop-runtime.sh"
}

@test "published image contract executes and records pinned Remora" {
  # The remora install moved out of 26-packages-post.sh into its own script so
  # Containerfile.opensuse — which runs none of the numbered scripts — can
  # install it too. The pin, the checksum gate and the smoke test must survive
  # that move.
  local remora="${REPO_ROOT}/build_scripts/install-remora.sh"
  grep -q 'sha256sum --check --strict' "$remora"
  grep -q "remora --help" "$remora"
  grep -q 'experience-contracts/remora' "$remora"
  # Runtime contract still gates on remora being present in the image.
  grep -q 'remora_not_found' \
    "${REPO_ROOT}/build_scripts/checks/verify-desktop-experience.sh"
}

@test "every base that ships images installs Remora" {
  # sailfin shipped with no remora at all and every sailfin Gate failed on
  # reason=remora_not_found — a desktop that booted fine reported as broken.
  # The dnf bases get it via 26-packages-post.sh; every base that does not run
  # that script (openSUSE, Ubuntu, Debian, Arch, Gentoo) must call the
  # split-out script directly. Every route must stay wired up.
  grep -q 'install-remora.sh' "${REPO_ROOT}/build_scripts/26-packages-post.sh"
  for base in opensuse ubuntu debian arch gentoo; do
    grep -q 'install-remora.sh' "${REPO_ROOT}/Containerfile.${base}"
  done
  [ -x "${REPO_ROOT}/build_scripts/install-remora.sh" ]
}

@test "desktop contract unit runs the installed-system TAP checks on all DEs" {
  # Both installer paths (manifest-driven and Ubuntu runtime-configure) must
  # bake e2e-runtime-checks and run it as a non-fatal second ExecStart.
  for script in install-desktop.sh configure-desktop-runtime.sh; do
    grep -q 'e2e-runtime-checks.sh' "${REPO_ROOT}/build_scripts/desktop/${script}"
    grep -qF 'ExecStart=-/usr/libexec/tunaos/e2e-runtime-checks' \
      "${REPO_ROOT}/build_scripts/desktop/${script}"
    # Contract gate covers every DE, not just gnome/kde/niri.
    grep -q 'cosmic' "${REPO_ROOT}/build_scripts/desktop/${script}"
    grep -q 'xfce' "${REPO_ROOT}/build_scripts/desktop/${script}"
  done
}

@test "build contract statically verifies units and launchers, hard-fails KDE skew" {
  local script="${REPO_ROOT}/build_scripts/checks/verify-desktop-experience.sh"
  # secureblue pattern: validate the enabled unit graph (system + user).
  grep -qF 'systemd-analyze verify --recursive-errors=yes graphical.target' "$script"
  grep -qF 'systemd-analyze verify --user --recursive-errors=yes default.target' "$script"
  grep -q 'SYSTEMD_VERIFY_FATAL' "$script"
  # aurora pattern: desktop-file-validate shipped launchers (warn-only default).
  grep -q 'desktop-file-validate' "$script"
  grep -q 'DESKTOP_VALIDATE_FATAL' "$script"
  # aurora pattern: Plasma/Qt version-skew is a hard build failure.
  grep -q 'KDE version skew' "$script"
  grep -q 'Qt version skew' "$script"
  # runtime side re-verifies the unit graph on the installed system.
  grep -qF 'systemd-analyze verify --recursive-errors=yes graphical.target' \
    "${REPO_ROOT}/build_scripts/checks/e2e-runtime-checks.sh"
}

@test "EL10 KDE does not copy nonexistent Aurora files from Bluefin common" {
  run grep -F 'COPY --from=common /system_files/aurora' \
    "${REPO_ROOT}/Containerfile.el10"
  [ "$status" -ne 0 ]
}

@test "Sailfin's initramfs is built with LUKS support (cryptsetup + device-mapper)" {
  # dracut's dm module is `require_binaries dmsetup` and its crypt module is
  # `require_binaries cryptsetup` plus a dependency on dm. The openSUSE base
  # ships neither, so the system stage's dracut run dropped crypt and
  # systemd-cryptsetup, and the installed encrypted disk had no way to unlock:
  # the initrd ignored fisherman's rd.luks.name karg, never prompted for a
  # passphrase, and dropped to the dracut emergency shell waiting for a root
  # UUID that only appears once the LUKS volume opens (tunaOS#953).
  local containerfile="${REPO_ROOT}/Containerfile.opensuse"
  local pkg_line dracut_line
  pkg_line=$(grep -nE '^ +btrfs-progs .*cryptsetup.* device-mapper ' "$containerfile" | cut -d: -f1)
  [ -n "$pkg_line" ]
  # The packages must land BEFORE the initramfs is built, not via the desktop
  # stage's pattern (which only the GNOME flavor happens to pull them in with).
  dracut_line=$(grep -nF 'dracut --force --no-hostonly' "$containerfile" | cut -d: -f1)
  [ "$dracut_line" -gt "$pkg_line" ]

  # Requested by name so an in-image rebuild (dev ISO, kernel update) with
  # openSUSE's hostonly default cannot silently drop them either.
  grep -qF 'add_dracutmodules+=" bootc crypt dm "' "$containerfile"

  # And the build fails loudly if the modules are missing from the initramfs.
  # The assertion targets the systemd unlock path (systemd-cryptsetup and the
  # dm-crypt module), NOT a standalone `cryptsetup` binary: dracut-ng 110 keeps
  # the CLI out of a systemd initrd, so checking for it failed an initramfs
  # that could unlock fine.
  grep -qF 'for mod in crypt dm' "$containerfile"
  grep -qF 'for path in usr/bin/systemd-cryptsetup usr/sbin/dmsetup dm-crypt.ko' \
    "$containerfile"
  run grep -qF 'sbin/cryptsetup ' "$containerfile"
  [ "$status" -ne 0 ]
}

@test "Sailfin installs shared Bluefin config and GNOME-only Bluefin branding" {
  local containerfile="${REPO_ROOT}/Containerfile.opensuse"
  grep -qF 'FROM ${COMMON_IMAGE_REF} AS common' "$containerfile"
  grep -qF 'COPY --from=common /system_files/shared /' "$containerfile"
  grep -qF 'COPY --from=common /system_files/bluefin /' "$containerfile"

  # GNOME branding must remain at the GNOME target, not the shared system base.
  local gnome_line shared_line
  gnome_line=$(grep -nF 'FROM desktop AS gnome' "$containerfile" | cut -d: -f1)
  shared_line=$(grep -nF 'COPY --from=common /system_files/shared /' "$containerfile" | cut -d: -f1)
  [ "$gnome_line" -gt "$shared_line" ]
}

# ═══════════════════════════════════════════════════════════════════════════
# build_scripts/checks/verify-branding.sh
# ═══════════════════════════════════════════════════════════════════════════

@test "build_scripts/checks/verify-branding.sh: has bash shebang and set flags" {
  local script="${REPO_ROOT}/build_scripts/checks/verify-branding.sh"
  run head -1 "$script"
  [[ "$output" =~ ^#!/.*bash ]]
  grep -q 'set -euo pipefail' "$script"
}

@test "verify-branding.sh: reads /usr/lib/os-release when /etc/os-release is absent" {
  # /etc/os-release is only conventionally present; /usr/lib/os-release is the
  # canonical file. Reading only /etc would report every field unset.
  local script="${REPO_ROOT}/build_scripts/checks/verify-branding.sh"
  grep -qF '/usr/lib/os-release' "$script"
  grep -qF 'os_release_file' "$script"
}

@test "verify-branding.sh: upstream denylist covers every shipped base family" {
  # el10, Ubuntu, Debian, openSUSE, Gentoo and Arch are all built from
  # scripts/resolve-flavor.sh; a family missing here lets an unbranded image
  # ship its upstream PRETTY_NAME and LOGO through the check.
  local script="${REPO_ROOT}/build_scripts/checks/verify-branding.sh"
  for name in ubuntu debian fedora centos almalinux rocky rhel opensuse suse gentoo arch; do
    grep -qE "\b${name}\b" "$script" || {
      echo "FAIL: upstream denylist missing ${name}" >&2
      return 1
    }
  done
  # Both the name check and the logo check must use the shared denylist.
  [ "$(grep -c 'names_upstream' "$script")" -ge 3 ]
}

@test "verify-branding.sh: reports unset fields instead of exiting at the first one" {
  # The bug class this script exists to catch: dying under set -e at the first
  # absent field, so the run produces no verdict. A near-empty os-release must
  # still walk every section and emit the FAIL marker.
  local script="${REPO_ROOT}/build_scripts/checks/verify-branding.sh"
  local fixture="${BATS_TEST_TMPDIR}/os-release"
  printf 'PRETTY_NAME="AlmaLinux 10"\nLOGO=archlinux-logo\n' >"$fixture"

  run env TUNAOS_OS_RELEASE="$fixture" bash "$script" grouper
  [ "$status" -eq 1 ]
  [[ "$output" == *"VERSION_CODENAME is ''"* ]]
  [[ "$output" == *"PRETTY_NAME is 'AlmaLinux 10'"* ]]
  [[ "$output" == *"LOGO=archlinux-logo — upstream logo, not ours"* ]]
  [[ "$output" == *"IMAGE_VERSION is unset"* ]]
  [[ "$output" == *"== desktop assets =="* ]]
  [[ "$output" == *"TUNAOS_BRANDING_FAIL variant=grouper"* ]]
}

@test "verify-branding.sh: passes shellcheck" {
  if command -v shellcheck &>/dev/null; then
    # Same severity and excludes as .github/workflows/lint.yml.
    run shellcheck --severity=error --exclude=SC1091,SC2114 \
      "${REPO_ROOT}/build_scripts/checks/verify-branding.sh"
    [ "$status" -eq 0 ]
  else
    skip "shellcheck not installed"
  fi
}

# ═══════════════════════════════════════════════════════════════════════════
# build_scripts/90-image-info.sh — os-release writing
#
# 90-image-info.sh cannot be run end to end outside a build (it sources
# /run/context/build_scripts/lib.sh and needs the image env), so these tests
# extract the os-release block from the real script and run it against
# fixtures. Extracting rather than restating means the tests track the script:
# rename the function or change the file-selection rule and they stop matching.
# ═══════════════════════════════════════════════════════════════════════════

# Everything from the file-selection block through the end of osr_set().
_osr_block() {
  sed -n '/^OS_RELEASE_USR=/,/^}$/p' "${REPO_ROOT}/build_scripts/90-image-info.sh"
}

@test "90-image-info.sh: writes keys the base omits entirely" {
  # No RPM base defines VERSION_CODENAME and Arch defines neither it nor
  # VARIANT_ID. The old `sed s|^KEY=.*|...|` matched no line and exited 0, so
  # the fish codename never landed on yellowfin/skipjack/albacore (#1007) or
  # marlin (#1015) while the build reported success.
  local usr="${BATS_TEST_TMPDIR}/usr-os-release"
  printf 'NAME="Arch Linux"\nPRETTY_NAME="Arch Linux"\nID=arch\nLOGO=archlinux-logo\n' >"$usr"

  run env TUNAOS_OS_RELEASE_USR="$usr" TUNAOS_OS_RELEASE_ETC=/nonexistent \
    bash -c "$(_osr_block)"$'\n''osr_set VERSION_CODENAME "Makaira nigricans"; osr_set VARIANT_ID marlin; osr_set PRETTY_NAME Marlin; osr_set LOGO tunaos'
  [ "$status" -eq 0 ]

  grep -qF 'VERSION_CODENAME="Makaira nigricans"' "$usr"
  grep -qF 'VARIANT_ID="marlin"' "$usr"
  grep -qF 'PRETTY_NAME="Marlin"' "$usr"
  grep -qF 'LOGO="tunaos"' "$usr"
  # Replaced, not appended: a second PRETTY_NAME makes both readings defensible.
  [ "$(grep -c '^PRETTY_NAME=' "$usr")" -eq 1 ]
  [ "$(grep -c '^LOGO=' "$usr")" -eq 1 ]
}

@test "90-image-info.sh: brands a base that ships a real /etc/os-release" {
  # Arch's filesystem package installs only usr/lib/os-release; the container
  # image adds an independent /etc copy. Writing only /usr/lib left every
  # reader — systemd, GNOME About, fastfetch, verify-branding.sh — looking at
  # a file that still said Arch Linux (run 31013418173).
  local usr="${BATS_TEST_TMPDIR}/usr-os-release"
  local etc="${BATS_TEST_TMPDIR}/etc-os-release"
  printf 'PRETTY_NAME="Arch Linux"\nSUPPORT_URL="https://bbs.archlinux.org/"\n' >"$usr"
  printf 'PRETTY_NAME="Arch Linux"\nSUPPORT_URL="https://bbs.archlinux.org/"\nBASE_IMAGE="docker.io/archlinux/archlinux:latest"\n' >"$etc"

  run env TUNAOS_OS_RELEASE_USR="$usr" TUNAOS_OS_RELEASE_ETC="$etc" \
    bash -c "$(_osr_block)"$'\n''osr_set PRETTY_NAME Marlin; osr_set SUPPORT_URL "https://github.com/tuna-os/tunaos/issues/"'
  [ "$status" -eq 0 ]

  local f
  for f in "$usr" "$etc"; do
    grep -qF 'PRETTY_NAME="Marlin"' "$f"
    grep -qF 'SUPPORT_URL="https://github.com/tuna-os/tunaos/issues/"' "$f"
    run grep -F 'archlinux.org' "$f"
    [ "$status" -ne 0 ]
  done
  # Keys written by other build steps survive — lib.sh reads BASE_IMAGE back
  # out of /etc/os-release.
  grep -qF 'BASE_IMAGE="docker.io/archlinux/archlinux:latest"' "$etc"
}

@test "90-image-info.sh: leaves the conventional /etc symlink alone" {
  # On RPM bases /etc/os-release is a symlink into /usr/lib. `sed -i` replaces
  # a symlink with a regular file, so writing both paths blindly would quietly
  # convert it and split the two files apart on the next boot.
  local usr="${BATS_TEST_TMPDIR}/sym-usr-os-release"
  local etc="${BATS_TEST_TMPDIR}/sym-etc-os-release"
  printf 'PRETTY_NAME="AlmaLinux Kitten 10"\n' >"$usr"
  ln -s "$usr" "$etc"

  run env TUNAOS_OS_RELEASE_USR="$usr" TUNAOS_OS_RELEASE_ETC="$etc" \
    bash -c "$(_osr_block)"$'\n''osr_set PRETTY_NAME Yellowfin; echo "FILES=${#OS_RELEASE_FILES[@]}"'
  [ "$status" -eq 0 ]
  [[ "$output" == *"FILES=1"* ]]
  [ -L "$etc" ]
  grep -qF 'PRETTY_NAME="Yellowfin"' "$etc"
  [ "$(grep -c '^PRETTY_NAME=' "$usr")" -eq 1 ]
}

# ═══════════════════════════════════════════════════════════════════════════
# kde-set-look-and-feel.sh — KDE LookAndFeelPackage (#1008)
#
# Runs the real script against fixtures via its file arguments, so the tests
# exercise the shipped code path rather than a restatement of it.
# ═══════════════════════════════════════════════════════════════════════════

_run_lnf() { # $1 = file
  "${REPO_ROOT}/build_scripts/desktop/kde-set-look-and-feel.sh" "$1"
}

@test "kde LookAndFeel: both desktop install paths re-assert it" {
  # The fix is only correct if BOTH paths run it. install-desktop.sh covers the
  # dnf/zypper/pacman/portage bases (bonito among them) and
  # configure-desktop-runtime.sh covers Ubuntu/Debian; applying it to one left
  # the other shipping Fedora's theme, which is how bonito:kde kept failing
  # verify-branding-kde.sh with the fix nominally in the tree.
  [ -x "${REPO_ROOT}/build_scripts/desktop/kde-set-look-and-feel.sh" ]
  local script
  for script in install-desktop.sh configure-desktop-runtime.sh; do
    grep -qF 'kde-set-look-and-feel.sh' \
      "${REPO_ROOT}/build_scripts/desktop/${script}"
    # ...and before the check that would otherwise fail on Fedora's value.
    local set_line check_line
    set_line=$(grep -nF 'kde-set-look-and-feel.sh' \
      "${REPO_ROOT}/build_scripts/desktop/${script}" | head -1 | cut -d: -f1)
    check_line=$(grep -nF 'verify-branding-kde.sh' \
      "${REPO_ROOT}/build_scripts/desktop/${script}" | head -1 | cut -d: -f1)
    [ "$set_line" -lt "$check_line" ]
  done
}

@test "kde LookAndFeel: default writes both config locations" {
  # kde-settings' profile dir precedes /etc/xdg in XDG_CONFIG_DIRS on
  # Fedora/EL, so branding only /etc/xdg passes the check (it greps /etc/xdg
  # first) while Plasma still loads Fedora's theme.
  local script="${REPO_ROOT}/build_scripts/desktop/kde-set-look-and-feel.sh"
  grep -qF '/etc/xdg/kdeglobals' "$script"
  grep -qF '/usr/share/kde-settings/kde-profile/default/xdg/kdeglobals' "$script"
}

@test "kde LookAndFeel: overwrites Fedora's value (bonito, #1008)" {
  # kde-settings ships this file and owns the path, so installing Plasma
  # replaced our base-stage copy. Measured on bonito:kde:
  # LookAndFeelPackage=org.fedoraproject.fedora.desktop.
  local f="${BATS_TEST_TMPDIR}/kdeglobals"
  printf '[KDE]\nLookAndFeelPackage=org.fedoraproject.fedora.desktop\nSingleClick=false\n\n[General]\nfont=Noto Sans,10\n' >"$f"

  _run_lnf "$f"

  [ "$(grep -c '^LookAndFeelPackage=' "$f")" -eq 1 ]
  grep -qF 'LookAndFeelPackage=org.tunaos.desktop' "$f"
  # The file also carries fonts, colour scheme and widget style — a fix that
  # drops those trades one branding defect for several.
  grep -qF 'SingleClick=false' "$f"
  grep -qF 'font=Noto Sans,10' "$f"
}

@test "kde LookAndFeel: adds the key to an existing [KDE] section" {
  local f="${BATS_TEST_TMPDIR}/kdeglobals"
  printf '[KDE]\nSingleClick=false\n\n[General]\nfont=X\n' >"$f"
  _run_lnf "$f"
  [ "$(grep -c '^LookAndFeelPackage=org.tunaos.desktop$' "$f")" -eq 1 ]
  grep -qF 'font=X' "$f"
}

@test "kde LookAndFeel: handles no [KDE] section, [KDE] last, and no file" {
  local f="${BATS_TEST_TMPDIR}/a" g="${BATS_TEST_TMPDIR}/b" h="${BATS_TEST_TMPDIR}/c"
  printf '[General]\nfont=X\n' >"$f"
  printf '[General]\nfont=X\n\n[KDE]\nSingleClick=false\n' >"$g"

  _run_lnf "$f"
  _run_lnf "$g"
  _run_lnf "$h"

  local each
  for each in "$f" "$g" "$h"; do
    [ "$(grep -c '^LookAndFeelPackage=org.tunaos.desktop$' "$each")" -eq 1 ]
  done
}

@test "kde LookAndFeel: idempotent, and leaves other sections alone" {
  local f="${BATS_TEST_TMPDIR}/kdeglobals"
  printf '[Greeter]\nLookAndFeelPackage=org.kde.breeze.desktop\n\n[KDE]\nSingleClick=false\n' >"$f"

  _run_lnf "$f"
  _run_lnf "$f"

  # Ours set once in [KDE]...
  [ "$(grep -c '^LookAndFeelPackage=org.tunaos.desktop$' "$f")" -eq 1 ]
  # ...and the unrelated [Greeter] key untouched.
  grep -qF 'LookAndFeelPackage=org.kde.breeze.desktop' "$f"
}

@test "verify-branding-kde.sh: a greeter with no themes dir still counts (flounder, #1008)" {
  # Debian trixie's sddm package ships /usr/bin/sddm and
  # /usr/lib/systemd/system/sddm.service but NO /usr/share/sddm/themes and no
  # sddm.conf.d — verified against the package file list. The old check looked
  # only for themes/conf, so it reported "greeter not installed" for an image
  # that had one.
  local script="${REPO_ROOT}/build_scripts/checks/verify-branding-kde.sh"
  grep -qF '/usr/lib/systemd/system/sddm.service' "$script"
  grep -qF '/usr/lib/systemd/system/plasmalogin.service' "$script"
  grep -qF '/usr/bin/sddm' "$script"
  # Debian/Ubuntu newer sddm puts its defaults under /usr/share, not /usr/lib.
  grep -qF '/usr/share/sddm/sddm.conf.d/' "$script"
}

@test "99-cleanup.sh recreates /var/tmp after wiping /var (#1010)" {
  # tacklebox runs dracut inside the built image to rebuild the live-ISO
  # initramfs. No boot happens there, so systemd-tmpfiles never creates
  # /var/tmp, and dracut's --tmpdir default fails with
  # "dracut[F]: Invalid tmpdir '/var/tmp'" — which tacklebox surfaces as
  # "does the image ship dracut?" (that is how #1010 got filed as a missing
  # dracut). The base stages of Containerfile.debian and .arch create it; this
  # script's /var wipe removed it again.
  local script="${REPO_ROOT}/build_scripts/99-cleanup.sh"
  local wipe_line recreate_line
  wipe_line="$(grep -n 'find /var -mindepth 1 -maxdepth 1' "$script" | head -1 | cut -d: -f1)"
  recreate_line="$(grep -n 'mkdir -p /var/tmp' "$script" | head -1 | cut -d: -f1)"
  [ -n "$wipe_line" ] || skip "the /var wipe this guards is gone"
  [ -n "$recreate_line" ] || {
    echo "FAIL: /var is wiped at line ${wipe_line} and /var/tmp never recreated" >&2
    return 1
  }
  # Order matters — recreating before the wipe accomplishes nothing.
  [ "$recreate_line" -gt "$wipe_line" ]
  grep -qF 'chmod 1777 /var/tmp' "$script"
}

@test "base stages that pre-create /var/tmp still do (#1010 belt and braces)" {
  # The ISO build needs the directory present in the image (dracut --tmpdir
  # defaults to /var/tmp). 99-cleanup.sh also recreates it, but a path that
  # skips 99-cleanup would be uncovered without this.
  #
  # The base stages no longer spell it out themselves — build_scripts/bootc/
  # ostree-layout.sh does, once, for all of them. So follow the wiring instead
  # of grepping each Containerfile for a literal that has moved: a stage is
  # covered if it creates /var/tmp itself OR calls the script that does.
  local layout="${REPO_ROOT}/build_scripts/bootc/ostree-layout.sh"
  grep -qF '"${R}/var/tmp"' "$layout"
  grep -qF 'chmod 1777 "${R}/var/tmp"' "$layout"

  local f
  for f in Containerfile.debian Containerfile.arch Containerfile.gentoo; do
    grep -qF '/var/tmp' "${REPO_ROOT}/$f" ||
      grep -qF 'bootc/ostree-layout.sh' "${REPO_ROOT}/$f"
  done
}

@test "install-desktop.sh resolves a PPA suite from UBUNTU_CODENAME, not VERSION_CODENAME" {
  # 90-image-info.sh rewrites VERSION_CODENAME to the variant's fish name and
  # keeps UBUNTU_CODENAME as the Launchpad suite. Anything that resolves a PPA
  # through VERSION_CODENAME therefore asks Launchpad for a suite called
  # "Chelidonichthys lucerna" — which is how gurnard:pantheon died (#1014):
  #
  #   aptsources.distro.NoDistroTemplateException: Error: could not find a
  #   distribution template for Ubuntu/Chelidonichthys lucerna
  #
  # Strip comments before matching: the paragraph above quotes both names.
  local script="${REPO_ROOT}/build_scripts/desktop/install-desktop.sh"
  local code
  code="$(grep -v '^[[:space:]]*#' "$script")"

  # add-apt-repository always asks os-release for the suite and takes no flag
  # to override it, so it must not be the mechanism.
  run grep -c 'add-apt-repository' <<<"$code"
  [ "$output" -eq 0 ]

  # The suite must come from UBUNTU_CODENAME...
  grep -qF '${UBUNTU_CODENAME' <<<"$code"
  # ...and the branded VERSION_CODENAME must never be EXPANDED. Naming it in
  # the error message is fine and useful; substituting its value is the bug.
  run grep -cE '\$\{?VERSION_CODENAME' <<<"$code"
  [ "$output" -eq 0 ]
}

@test "install-desktop.sh fails loudly when a declared PPA cannot be added" {
  # Pantheon exists only in ppa:elementary-os/stable — nothing in the Ubuntu
  # archive — so a silently-skipped PPA is not a degraded desktop, it is no
  # desktop. The old code skipped it and the build died ~40 lines later with
  # "Unable to locate package gala", naming every package and never the repo
  # (LUKS run 31060730479).
  local script="${REPO_ROOT}/build_scripts/desktop/install-desktop.sh"
  local body
  body="$(sed -n '/^_td_add_ppa() {/,/^}/p' "$script")"
  [ -n "$body" ]

  # Every step that can fail must stop the build rather than continue:
  # no codename, no fingerprint, not actually a key.
  [ "$(grep -c 'return 1' <<<"$body")" -ge 3 ]
  # curl must not swallow HTTP errors into a zero-byte keyring.
  grep -qF -- '-fsSL' <<<"$body"
  # And nothing in it may be best-effort.
  run grep -c '|| true' <<<"$(grep -v 'signing_key_fingerprint' <<<"$body")"
  [ "$output" -eq 0 ]
}

@test "40-services.sh enables a network manager on the pacman/zypper/emerge path" {
  # sailfin:cosmic booted its live ISO with sshd running and zero failed units,
  # and was still unreachable: "Connection timed out during banner exchange"
  # x21. Its own contract had the answer — "not ok - a network manager is
  # active" — with the NIC present and unconfigured (LUKS run 31060731552).
  # No path here enabled one for pacman/zypper/emerge.
  #
  # Either/or, never both: two daemons on one link is its own failure mode, and
  # the contract accepts whichever is active.
  local script="${REPO_ROOT}/build_scripts/40-services.sh"
  local code
  code="$(grep -v '^[[:space:]]*#' "$script")"
  grep -qF 'net_unit=NetworkManager.service' <<<"$code"
  grep -qF 'net_unit=systemd-networkd.service' <<<"$code"
  grep -qF 'systemctl enable "$net_unit"' <<<"$code"

  # Not safe_enable: it swallows failures with `|| true`, which is right for
  # units that legitimately may not exist and wrong here, where the enable is
  # the only thing turning networking on.
  run grep -cE 'safe_enable (NetworkManager|systemd-networkd)' <<<"$code"
  [ "$output" -eq 0 ]
}

@test "40-services.sh enables networking before the apt path returns" {
  # tunaOS#1013: the Ubuntu/Grouper path exits before the non-apt branch. A
  # helper call elsewhere in the file is therefore not enough to give the
  # installed LUKS guest an address for its SSH check.
  local script="${REPO_ROOT}/build_scripts/40-services.sh"
  local apt_block
  apt_block="$(awk '/^if \[\[ "\$\{PKG_MGR:-\}" == "apt" \]\]/,/^fi$/' "$script")"
  [ -n "$apt_block" ]

  # Keep the assertion tied to the actual early-return boundary rather than
  # merely counting helper calls across unrelated package-manager branches.
  grep -qF 'tunaos_enable_network_manager' <<<"$apt_block"
  local network_line return_line
  network_line="$(grep -nF 'tunaos_enable_network_manager' <<<"$apt_block" | head -1 | cut -d: -f1)"
  return_line="$(grep -nE '^[[:space:]]*exit 0$' <<<"$apt_block" | head -1 | cut -d: -f1)"
  [ -n "$return_line" ]
  [ "$network_line" -lt "$return_line" ]
}

@test "40-services.sh installs networkd on zypper, which splits it out" {
  # The unit openSUSE needs is not in the `systemd` package. Measured in a
  # tumbleweed container: after `zypper install systemd` there is no
  # systemd-networkd.service, and after `zypper install systemd-network` there
  # is. So sailfin enabled a unit that did not exist, safe_enable hid it, and
  # /usr/lib/systemd/network/20-wired.network sat there as a DHCP profile with
  # no daemon to read it.
  local script="${REPO_ROOT}/build_scripts/40-services.sh"
  local code
  code="$(grep -v '^[[:space:]]*#' "$script")"
  grep -qF 'pkg_install systemd-network' <<<"$code"

  # And the profile it reads must still be shipped, or installing the daemon
  # buys nothing: it would come up with no configured link.
  grep -qF '/usr/lib/systemd/network/20-wired.network' "${REPO_ROOT}/Containerfile.opensuse"
}

@test "40-services.sh fails the build when no network stack is present" {
  # A networkless image presents as an SSH fault 40 minutes later in a VM
  # (banner-exchange timeouts against a guest with no address). Catch it at
  # build time instead. Gentoo is the one exception, warned about rather than
  # failed, because adding an atom there is a source compile and guppy's
  # networking has not been measured.
  local script="${REPO_ROOT}/build_scripts/40-services.sh"

  # The selection and the failure both live in tunaos_enable_network_manager
  # now, because the apt branch needed them too and it returns before the
  # pacman/zypper/emerge branch runs.
  local blk
  blk="$(awk '/^tunaos_enable_network_manager\(\) \{/,/^\}$/' "$script")"
  [ -n "$blk" ]

  # Gentoo warns and carries on; everything else is a hard failure.
  grep -qF 'WARNING: no network manager on the emerge path' <<<"$blk"

  # Two spellings of that hard failure are both correct, and this test asserts
  # the property rather than picking one — pinning a spelling is what made this
  # test and the script disagree twice while the behaviour never changed:
  #
  #   exit 1    — fails whatever the call site does
  #   return 1  — fails only while every call site is a bare command under
  #               `set -e`, so that is checked below when this is the spelling
  local fail_ln
  fail_ln="$(grep -nE '^[[:space:]]*(exit|return) 1$' <<<"$blk" | cut -d: -f1 | tail -1)"
  [ -n "$fail_ln" ]

  if ! grep -qE '^[[:space:]]*exit 1$' <<<"$blk"; then
    # A `|| true`, an `if`, or a `!` would swallow the return exactly the way
    # safe_enable swallowed the absent unit that started all this.
    local code
    code="$(grep -v '^[[:space:]]*#' "$script")"
    [ "$(grep -c '^[[:space:]]*tunaos_enable_network_manager$' <<<"$code")" -ge 2 ]
    run grep -cE 'tunaos_enable_network_manager[[:space:]]*(\|\||&&|;)|(if|!|until|while)[[:space:]]+tunaos_enable_network_manager' <<<"$code"
    [ "$output" -eq 0 ]
  fi

  # The failure must come last, after the emerge warning and after any
  # success return, so a base with no stack at all cannot fall through to
  # warn-and-carry-on or to a bare success.
  local warn_ln last_ok_ln
  warn_ln="$(grep -nF 'WARNING: no network manager on the emerge path' <<<"$blk" | cut -d: -f1 | head -1)"
  last_ok_ln="$(grep -nE '^[[:space:]]*return 0$' <<<"$blk" | cut -d: -f1 | tail -1)"
  [ "$warn_ln" -lt "$fail_ln" ]
  [ -z "$last_ok_ln" ] || [ "$last_ok_ln" -lt "$fail_ln" ]
}

# ═══════════════════════════════════════════════════════════════════════════
# build_scripts/checks/verify-branding-niri.sh: greeter assertion
# ═══════════════════════════════════════════════════════════════════════════

# Fixture helper: a greetd config whose default_session runs $1.
_greetd_fixture() {
  local out="${BATS_TEST_TMPDIR}/greetd-$$.toml"
  cat >"$out" <<EOF
[terminal]
vt = 1

[default_session]
command = "$1"
user = "greeter"
EOF
  echo "$out"
}

# Only the greeter section is under test; the compositor/session/background
# sections read absolute paths that do not exist on a test host, so assert on
# the greeter lines rather than the exit status.
_greeter_lines() {
  TUNAOS_GREETD_CONFIG="$1" bash \
    "${REPO_ROOT}/build_scripts/checks/verify-branding-niri.sh" marlin 2>&1 |
    sed -n '/== greeter ==/,/== compositor/p'
}

@test "verify-branding-niri.sh: flags a greeter greetd cannot exec" {
  # marlin:niri shipped greetd with its packaged config, which runs `agreety`.
  # On Arch agreety is NOT in the greetd package (it is greetd-agreety), so the
  # config named a binary that was not on the image. With Restart=always that
  # is a restart loop, so this must fail rather than be treated as a text-mode
  # fallback.
  local fixture
  fixture="$(_greetd_fixture 'agreety --cmd /bin/sh')"
  run _greeter_lines "$fixture"
  [[ "$output" == *"'agreety', which is NOT installed"* ]]
  [[ "$output" == *"no graphical greeter configured"* ]]
}

@test "verify-branding-niri.sh: flags a greeter wrapper that was never installed" {
  # greetd-gtkgreet.sh writes an absolute path into the config. If the script
  # it points at is missing the login screen never comes up.
  local fixture
  fixture="$(_greetd_fixture '/usr/libexec/tunaos/greetd-session')"
  run _greeter_lines "$fixture"
  [[ "$output" == *"/usr/libexec/tunaos/greetd-session, which is not executable"* ]]
}

@test "verify-branding-niri.sh: accepts any greeter that is actually present" {
  # The point of the fix: three greeters are legitimate here (dms-greeter on
  # Fedora/EL10, gtkgreet under cage on openSUSE and Arch, cosmic-greeter), so
  # the check must assert presence, not one variant's shell.
  local fixture
  fixture="$(_greetd_fixture '/bin/cat')"
  run _greeter_lines "$fixture"
  [[ "$output" == *"ok: greeter command /bin/cat present"* ]]
  [[ "$output" != *FAIL* ]]
}

@test "verify-branding-niri.sh: asserts the DMS shell only where DMS is the greeter" {
  # Hardcoding DMSGreeter.qml is what reddened marlin:niri, which has no DMS
  # packaging at all. A non-DMS greeter must not be measured against it.
  local fixture
  fixture="$(_greetd_fixture '/bin/cat')"
  run _greeter_lines "$fixture"
  [[ "$output" != *DMSGreeter.qml* ]]

  # ...but a config that DOES launch dms-greeter still has to ship it.
  fixture="$(_greetd_fixture 'dms-greeter --command niri')"
  run _greeter_lines "$fixture"
  [[ "$output" == *"DMSGreeter.qml is missing"* ]]
}

@test "verify-branding-niri.sh: passes shellcheck" {
  if command -v shellcheck &>/dev/null; then
    run shellcheck --severity=error --exclude=SC1091,SC2114 \
      "${REPO_ROOT}/build_scripts/checks/verify-branding-niri.sh"
    [ "$status" -eq 0 ]
  else
    skip "shellcheck not installed"
  fi
}

@test "every greetd manifest installs a greeter greetd can actually exec" {
  # greetd packages no greeter frontend with itself on any distro, and its
  # stock config names agreety. So a manifest that sets display_manager: greetd
  # has to declare a greeter AND wire it up, or the image boots to a restart
  # loop. niri-arch.yaml did neither (marlin:niri, LUKS run 31060133575).
  local fail=0 m
  for m in "${REPO_ROOT}"/manifests/desktops/*.yaml; do
    grep -qE '^display_manager:[[:space:]]*greetd[[:space:]]*$' "$m" || continue
    local body name
    name="$(basename "$m")"
    body="$(grep -v '^[[:space:]]*#' "$m")"
    # A greeter frontend, under any of its packaging names.
    if ! grep -qE '^[[:space:]]*-[[:space:]]+(greetd-)?(gtkgreet|dms-greeter|cosmic-greeter|regreet|tuigreet)[[:space:]]*$' <<<"$body"; then
      echo "FAIL: ${name} uses greetd but declares no greeter package" >&2
      fail=1
    fi
    # gtkgreet cannot own a VT, so it is only usable with cage, and it is
    # greetd-gtkgreet.sh that replaces the stock agreety config.
    if grep -qE '^[[:space:]]*-[[:space:]]+(greetd-)?gtkgreet[[:space:]]*$' <<<"$body"; then
      grep -qE '^[[:space:]]*-[[:space:]]+cage[[:space:]]*$' <<<"$body" ||
        { echo "FAIL: ${name} installs gtkgreet without cage" >&2; fail=1; }
      grep -qF 'greetd-gtkgreet.sh' <<<"$body" ||
        { echo "FAIL: ${name} installs gtkgreet but never sources greetd-gtkgreet.sh" >&2; fail=1; }
    fi
  done
  [ "$fail" -eq 0 ]
}

@test "40-services.sh declares liveuser's home so it survives the /var wipe" {
  # `useradd -m` makes /var/home/liveuser at BUILD time; 99-cleanup.sh then
  # deletes everything under /var, and bootc-base-dirs only recreates the
  # PARENT. The live ISO booted with an account whose home did not exist:
  #   Could not chdir to home directory /var/home/liveuser
  #   scp: dest open "/home/liveuser/fisherman-override": No such file
  # SSH still authenticated, so it surfaced as a scp failure handing the
  # installer its binary, not as a login failure (LUKS run 31061836333).
  local script="${REPO_ROOT}/build_scripts/40-services.sh"
  local code
  code="$(grep -v '^[[:space:]]*#' "$script")"
  grep -qF 'tunaos_declare_liveuser_home() {' <<<"$code"
  grep -qF '/var/home/liveuser' <<<"$code"

  # Every branch that creates liveuser must also declare its home — the paths
  # for apt, pacman/zypper/emerge and dnf are separate, and a fix landing in
  # one of them has already been this session's most repeated bug.
  local creates declares
  creates=$(grep -c 'useradd -m .*liveuser' <<<"$code")
  declares=$(grep -c 'tunaos_declare_liveuser_home$' <<<"$code")
  [ "$creates" -ge 3 ]
  # -1 for the function definition line itself.
  [ "$((declares))" -ge 3 ]
}

@test "40-services.sh points /etc/resolv.conf at the stub resolved actually writes" {
  # Enabling systemd-resolved is only half of name resolution: glibc reads
  # /etc/resolv.conf, resolved writes /run/systemd/resolve/stub-resolv.conf,
  # and the symlink joining them cannot be made at build time because podman
  # bind-mounts /etc/resolv.conf ("ln: failed to create symbolic link:
  # Device or resource busy" — a warning the build ignores). gurnard:pantheon
  # shipped the base's 0-byte file and reported `not ok - DNS resolution
  # (ghcr.io)` and `not ok - network connectivity` (LUKS run 31065556710).
  #
  # This asserts the rule's BEHAVIOUR, not its spelling, because the spelling
  # that looks right is the bug: the vendor rule and Containerfile.opensuse
  # both use `L!`, and plain `L` will not replace an existing path.
  local script="${REPO_ROOT}/build_scripts/40-services.sh"
  local blk
  blk="$(awk '/^tunaos_enable_systemd_resolved\(\) \{/,/^\}$/' "$script")"
  [ -n "$blk" ]

  local root="${BATS_TEST_TMPDIR}/root"
  mkdir -p "$root/usr/lib/systemd/system" "$root/etc" "$root/run/systemd/resolve"
  # The unit has to exist or the function correctly does nothing.
  printf '[Service]\nPrivateTmp=yes\n' \
    >"$root/usr/lib/systemd/system/systemd-resolved.service"

  # systemctl is the only thing here that needs a real system; every path the
  # function writes is redirected into $root, so this runs as an unprivileged
  # user and touches nothing outside BATS_TEST_TMPDIR.
  local bin="${BATS_TEST_TMPDIR}/bin"
  mkdir -p "$bin"
  printf '#!/usr/bin/env bash\nexit 0\n' >"$bin/systemctl"
  chmod +x "$bin/systemctl"

  run env \
    TUNAOS_SYSTEMD_SYSTEM_DIR="$root/usr/lib/systemd/system" \
    TUNAOS_TMPFILES_DIR="$root/usr/lib/tmpfiles.d" \
    PATH="$bin:$PATH" \
    bash -c "set -e
      $blk
      tunaos_enable_systemd_resolved"
  [ "$status" -eq 0 ]

  # The unit tweak has to land in the redirected tree, not on the host.
  grep -qF 'PrivateTmp=no' "$root/usr/lib/systemd/system/systemd-resolved.service"

  local rule
  rule="$(cat "$root/usr/lib/tmpfiles.d/"*.conf)"
  # It must name resolved's stub, not some other file.
  grep -qF '/etc/resolv.conf' <<<"$rule"
  grep -qF 'run/systemd/resolve/stub-resolv.conf' <<<"$rule"

  # The property: fed a 0-byte /etc/resolv.conf exactly as every apt and
  # openSUSE base ships one, the rule must end with a symlink. `L!` leaves the
  # file alone and DNS stays broken; `L+!` replaces it.
  if command -v systemd-tmpfiles >/dev/null 2>&1; then
    : >"$root/etc/resolv.conf"
    echo "nameserver 127.0.0.53" >"$root/run/systemd/resolve/stub-resolv.conf"
    mkdir -p "$root/usr/lib/tmpfiles.d"
    systemd-tmpfiles --create --boot --root="$root" >/dev/null 2>&1 || true
    [ -L "$root/etc/resolv.conf" ]
    [ "$(cat "$root/etc/resolv.conf")" = "nameserver 127.0.0.53" ]
  else
    # Same property, statically: a plain `L` cannot replace an existing path.
    grep -qE '^L\+' <<<"$rule"
  fi

  # Both branches that enable resolved must go through the helper — the apt
  # branch returns before the pacman/zypper/emerge one, so a fix in only one
  # of them has been this branch's most repeated bug.
  local code calls
  code="$(grep -v '^[[:space:]]*#' "$script")"
  calls=$(grep -c '^[[:space:]]*tunaos_enable_systemd_resolved$' <<<"$code")
  [ "$calls" -ge 2 ]
}

@test "40-services.sh declares the privsep directory sshd cannot start without" {
  # Gentoo's sshd chroots into /var/empty, and both /var wipes in the build
  # (bootc/ostree-layout.sh's `rm -rf`, 99-cleanup.sh's `find /var -delete`)
  # delete it. guppy's live ISO then booted with "[FAILED] Failed to start
  # OpenSSH server daemon." and never opened port 22, so iso-e2e.sh logged 21 x
  # "Connection timed out during banner exchange" and the cell died just after
  # TUNAOS_LUKS_E2E_INSTALL_STARTED (LUKS run 31091141499, guppy:xfce) with
  # every other guest check green.
  #
  # This asserts the BEHAVIOUR against a stub sshd that answers the way the
  # real one does, because the failure was invisible in the script's text: the
  # directory is compiled into sshd and named nowhere in this repo.
  local script="${REPO_ROOT}/build_scripts/40-services.sh"
  local blk
  # One awk, not two piped ones: the second exiting early SIGPIPEs the first,
  # and this file's assertions run under a shell that would take that status.
  blk="$(awk '/^tunaos_sshd_missing_privsep_dir\(\) \{/{p=1} p{print} p&&/^\}$/{n++; if (n==2) exit}' "$script")"
  grep -qF 'tunaos_declare_sshd_privsep_dir() {' <<<"$blk"

  local root="${BATS_TEST_TMPDIR}/root"
  local bin="${BATS_TEST_TMPDIR}/bin"
  mkdir -p "$root/var" "$bin"

  # Every probe below runs under `set -euo pipefail`, exactly as
  # 40-services.sh does, because the stub exits non-zero in the case being
  # detected: under pipefail a probe that does not absorb that status kills
  # the build on the line that asks the question.
  #
  # A stub that reproduces the two answers the real sshd gives: it refuses to
  # look at anything else until it has a host key (which is why the caller
  # generates a throwaway one — without -h the real probe only ever says
  # "no hostkeys available" and would declare nothing), and it names the
  # missing directory by its unprefixed path.
  cat >"$bin/sshd" <<STUB
#!/usr/bin/env bash
key=""
while [ \$# -gt 0 ]; do
  case "\$1" in
  -h) key="\$2"; shift 2 ;;
  *) shift ;;
  esac
done
if [ -z "\$key" ] || [ ! -s "\$key" ]; then
  echo "sshd: no hostkeys available -- exiting." >&2
  exit 1
fi
if [ -d "${root}/var/empty" ]; then exit 0; fi
# CRLF, because sshd logs to stderr in the SSH protocol's line ending. A
# probe that keeps the CR writes a tmpfiles rule for a path with a carriage
# return in it, which systemd-tmpfiles never creates.
printf 'Missing privilege separation directory: /var/empty\r\n' >&2
exit 255
STUB
  chmod +x "$bin/sshd"

  run env \
    PATH="$bin:$PATH" \
    TUNAOS_SYSROOT="$root" \
    TUNAOS_TMPFILES_DIR="$root/usr/lib/tmpfiles.d" \
    bash -c "set -euo pipefail
      $blk
      tunaos_declare_sshd_privsep_dir"
  [ "$status" -eq 0 ]

  # The rule has to name the directory sshd asked for, unprefixed — it is
  # resolved at boot, not at build time.
  local rule
  rule="$(cat "$root/usr/lib/tmpfiles.d/tunaos-sshd-privsep.conf")"
  [[ "$rule" == "d /var/empty 0755 root root -" ]]
  # And it has to be created now too, root-owned and not group/world writable.
  [ -d "$root/var/empty" ]

  # The property, end to end: fed the rule and a wiped /var, systemd-tmpfiles
  # must put the directory back — that is what runs before sshd.service on the
  # live boot.
  if command -v systemd-tmpfiles >/dev/null 2>&1; then
    rm -rf "$root/var/empty"
    systemd-tmpfiles --create --root="$root" >/dev/null 2>&1 || true
    [ -d "$root/var/empty" ]
  fi

  # A path outside /var must be left alone: /usr ships with the image, and
  # creating /run/sshd would leave a non-empty /run, which bootc lint rejects.
  cat >"$bin/sshd" <<'STUB'
#!/usr/bin/env bash
printf 'Missing privilege separation directory: /run/sshd\r\n' >&2
exit 255
STUB
  chmod +x "$bin/sshd"
  rm -rf "${root:?}/usr/lib/tmpfiles.d" "${root:?}/run"
  run env \
    PATH="$bin:$PATH" \
    TUNAOS_SYSROOT="$root" \
    TUNAOS_TMPFILES_DIR="$root/usr/lib/tmpfiles.d" \
    bash -c "set -euo pipefail
      $blk
      tunaos_declare_sshd_privsep_dir"
  [ "$status" -eq 0 ]
  [ ! -e "$root/run/sshd" ]
  [ ! -e "$root/usr/lib/tmpfiles.d/tunaos-sshd-privsep.conf" ]

  # And a declaration that does not fix the start must fail the build, not warn
  # — a swallowed failure here is the original defect.
  cat >"$bin/sshd" <<'STUB'
#!/usr/bin/env bash
printf 'Missing privilege separation directory: /var/empty\r\n' >&2
exit 255
STUB
  chmod +x "$bin/sshd"
  run env \
    PATH="$bin:$PATH" \
    TUNAOS_SYSROOT="$root" \
    TUNAOS_TMPFILES_DIR="$root/usr/lib/tmpfiles.d" \
    bash -c "set -euo pipefail
      $blk
      tunaos_declare_sshd_privsep_dir"
  [ "$status" -ne 0 ]
  [[ "$output" == *"still cannot find its privilege separation directory"* ]]

  # All three package-manager branches install an SSH server, so all three
  # need the directory it starts in — a fix landing in one of them has been
  # this branch's most repeated bug.
  local code installs declares
  code="$(grep -v '^[[:space:]]*#' "$script")"
  installs=$(grep -c '^[[:space:]]*ensure_openssh_installed$' <<<"$code")
  declares=$(grep -c '^[[:space:]]*tunaos_declare_sshd_privsep_dir$' <<<"$code")
  [ "$installs" -ge 3 ]
  [ "$declares" -ge "$installs" ]
}

@test "the desktop contract Wants (not Requires) the display manager" {
  # Requires= made a failed DM take the contract down as DEPEND — silencing
  # the dm_inactive branch that ships the DM's journal to the serial, which
  # is the only diagnosis channel the E2E has. Both proof cells of run pair
  # 31204811851/31204818233 crash-looped lightdm and left zero journal
  # evidence for exactly this reason. Comments stripped: the rationale names
  # both directives.
  local runtime="${REPO_ROOT}/build_scripts/desktop/configure-desktop-runtime.sh" code
  code="$(grep -v '^[[:space:]]*#' "$runtime")"
  grep -qF 'Wants=display-manager.service' <<<"$code"
  ! grep -qF 'Requires=display-manager.service' <<<"$code"
}

@test "lightdm gets tmpfiles.d for its /var state on bootc systems" {
  # Debian's lightdm ships /var dirs via dpkg/postinst and no tmpfiles.d
  # (measured on ubuntu:noble); a bootc install starts with fresh /var and
  # the DM crash-loops (runs 31204811851, 31204818233). All four measured
  # dirs must be declared, with the lightdm-owned pair owned by lightdm.
  local runtime="${REPO_ROOT}/build_scripts/desktop/configure-desktop-runtime.sh" code
  code="$(grep -v '^[[:space:]]*#' "$runtime")"
  grep -qF 'tunaos-lightdm-state.conf' <<<"$code"
  local d
  for d in /var/lib/lightdm /var/lib/lightdm-data /var/cache/lightdm /var/log/lightdm; do
    grep -qE "^d ${d} " "$runtime" || {
      echo "FAIL: tmpfiles entry for ${d} missing" >&2
      return 1
    }
  done
  grep -qE '^d /var/lib/lightdm 0750 lightdm lightdm' "$runtime"
}

@test "install-desktop.sh signature-verifies manifest-declared yum repos" {
  # tuna-os/tunaOS#1655: this block used to write gpgcheck=0/repo_gpgcheck=0
  # unconditionally for every repo the manifest declares (the xfce-wayland,
  # hummingbird, and fprintd repos), so packages installed on real systems
  # with no authenticity check at all. Every repo.tunaos.org publish pipeline
  # signs its RPMs (tuna-os/tunaos-packages#394's `rpmsign --addsign` step),
  # so gpgcheck=1 + the matching gpgkey= is real protection. repo_gpgcheck
  # stays 0 on purpose: repomd.xml isn't detached-signed (no repomd.xml.asc
  # published), so =1 there would hard-fail every dnf transaction rather than
  # add a check — same tradeoff contrib/install-gnome49.sh already makes in
  # tunaos-packages.
  #
  # One exception, added for utah-packages (tuna-os/tunaos-packages#629): a
  # repo the manifest marks `unsigned: true` may write gpgcheck=0, and ONLY
  # if its baseurl is file:// -- content the Containerfile bind-mounted out of
  # an OCI image pinned by digest in image-versions.yaml, where the digest is
  # the signature. The loop must refuse `unsigned: true` on any other URL.
  # tests/test_hummingbird_gnome_consumes_utah_packages.py runs the loop for
  # real; this test pins the shape of the block.
  local script="${REPO_ROOT}/build_scripts/desktop/install-desktop.sh"
  local block
  block="$(awk '/for \(\(i = 0; i < _TD_REPO_COUNT/,/^\tdone$/' "$script")"
  [ -n "$block" ]
  grep -qF 'echo "gpgcheck=1"' <<<"$block"
  grep -qF 'echo "gpgkey=https://repo.tunaos.org/public.gpg"' <<<"$block"
  grep -qF 'echo "repo_gpgcheck=0"' <<<"$block"
  # gpgcheck=0 exists exactly once, and only under the unsigned branch.
  [ "$(grep -cF 'echo "gpgcheck=0"' <<<"$block")" -eq 1 ]
  grep -qF 'if [[ "${_TD_RU}" == "true" ]]; then' <<<"$block"
  # ...and unsigned is refused unless the baseurl is file://.
  grep -qF '"${_TD_RU}" == "true" && "${_TD_RB}" != file://*' <<<"$block"
  grep -qF 'exit 1' <<<"$block"
}
