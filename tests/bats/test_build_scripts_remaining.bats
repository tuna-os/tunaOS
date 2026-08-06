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
  for de in gnome kde niri cosmic xfce; do
    grep -qE "^${de}\)|\| ${de}\)|${de} \|" "$script"
  done
  # Runtime DM validation must use the distro-agnostic alias, not raw unit
  # names (gdm vs gdm3 vs lightdm drift across variants).
  grep -qF 'display-manager.service' "$script"
}

@test "disk gate requires the desktop contract marker" {
  # The gate wakes on either marker (both prove the contract service ran)
  # but only OK passes; FAIL surfaces its reason lines and exits nonzero.
  run grep -F 'TUNAOS_DESKTOP_CONTRACT_(OK|FAIL)' "${REPO_ROOT}/scripts/iso-e2e.sh"
  [ "$status" -eq 0 ]
  grep -qF 'desktop experience contract FAILED' "${REPO_ROOT}/scripts/iso-e2e.sh"
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
# configure-desktop-runtime.sh — KDE LookAndFeelPackage (#1008)
#
# Extracts the real _kde_set_lnf out of the script and runs it against
# fixtures, so the tests track the implementation rather than restating it.
# ═══════════════════════════════════════════════════════════════════════════

_lnf_fn() {
  sed -n '/^\t\t_kde_set_lnf() {$/,/^\t\t}$/p' \
    "${REPO_ROOT}/build_scripts/desktop/configure-desktop-runtime.sh" |
    sed 's/^\t\t//'
}

_run_lnf() { # $1 = file
  bash -c "$(_lnf_fn)"$'\n'"_kde_set_lnf '$1'"
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
