#!/usr/bin/env bats
# The runtime branding contract: build_scripts/checks/verify-branding-runtime.sh
# (sourced by verify-branding.sh --runtime), the COSMIC/XFCE/Pantheon checkers
# and install-branding-contract.sh. Every assertion runs over a fixture root
# (TUNAOS_BRANDING_ROOT) with stub binaries on PATH, so each failure mode the
# installed system can show is produced here on purpose.

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
CHECKS="${REPO_ROOT}/build_scripts/checks"

setup() {
	ROOT="$(mktemp -d)"
	STUB="${ROOT}.bin"
	mkdir -p "$STUB"
	export PATH="${STUB}:${PATH}"
	export TUNAOS_BRANDING_ROOT="$ROOT"
	mkdir -p "$ROOT"/{etc,usr/lib,usr/share/ublue-os,usr/share/tunaos/branding,proc/sys/kernel,usr/share/backgrounds/tunaos}
	cat >"$ROOT/usr/lib/os-release" <<'EOF'
NAME="Yellowfin"
PRETTY_NAME="Yellowfin"
ID="almalinux"
ID_LIKE="rhel centos fedora"
VARIANT_ID="yellowfin"
DEFAULT_HOSTNAME="yellowfin"
LOGO="tunaos"
HOME_URL="https://github.com/tuna-os/tunaos"
EOF
	ln -s ../usr/lib/os-release "$ROOT/etc/os-release"
	printf '{\n  "image-name": "yellowfin",\n  "image-flavor": "gnome"\n}\n' >"$ROOT/usr/share/ublue-os/image-info.json"
	printf "TUNAOS_VARIANT='yellowfin'\n" >"$ROOT/usr/share/tunaos/identity.env"
	printf 'TUNAOS_PLYMOUTH_THEME=tunaos\n' >"$ROOT/usr/share/tunaos/identity-config.env"
	printf '# header\nyellowfin\t#FFC702\tyellow\tAlmaLinux Kitten\thomage\ttropical-fish\n' \
		>"$ROOT/usr/share/tunaos/branding/variant-identity.tsv"
	echo yellowfin >"$ROOT/proc/sys/kernel/hostname"
	# shellcheck source=build_scripts/checks/verify-branding-runtime.sh
	source "${CHECKS}/verify-branding-runtime.sh"
}

teardown() {
	rm -rf "$ROOT" "$STUB"
}

stub() { # <name> <body>
	printf '#!/usr/bin/env bash\n%s\n' "$2" >"${STUB}/$1"
	chmod +x "${STUB}/$1"
}

status_of() { echo "${BRANDING_CHECK_STATUS[$1]:-unrecorded}"; }

@test "the denylist matches brand words, not substrings" {
	# Falsification: use a substring test and "research" or "x86_64 arch" match.
	[ "$(deny_hits 'fedora-logo-icon')" = fedora ]
	[ "$(deny_hits 'AlmaLinux Kitten')" = "almalinux kitten" ]
	[ "$(deny_hits 'https://almalinux.org/')" = almalinux ]
	[ -z "$(deny_hits 'research x86_64 arch Yellowfin')" ]
	[ "$(deny_hits 'Arch Linux \r (\l)')" = "arch linux" ]
}

@test "the 'built on' attribution is the one allowed upstream name" {
	# Falsification: drop strip_attribution and the issue banner fails.
	printf '\e[1;38;2;255;199;2m\\S{PRETTY_NAME}\e[0m - built on AlmaLinux Kitten\n\\r (\\l)\n\n' >"$ROOT/etc/issue"
	check_issue
	[ "$(status_of issue)" = pass ]
}

@test "an upstream login banner fails the issue check" {
	# Falsification: skip the denylist pass over /etc/issue and this passes.
	printf 'Yellowfin\nFedora Linux 43 \\r (\\l)\n' >"$ROOT/etc/issue"
	check_issue
	[ "$(status_of issue)" = fail ]
}

@test "os-release: a real /etc copy that disagrees with /usr/lib fails" {
	# Falsification: compare only /usr/lib/os-release and this passes.
	rm "$ROOT/etc/os-release"
	sed 's/^PRETTY_NAME=.*/PRETTY_NAME="AlmaLinux Kitten 10"/' "$ROOT/usr/lib/os-release" >"$ROOT/etc/os-release"
	check_os_release
	[ "$(status_of os-release.agree)" = fail ]
	[ "$(status_of os-release.name)" = fail ]
	[ "$(status_of os-release.denylist)" = fail ]
	[[ "${BRANDING_CHECK_DETAIL[os-release.agree]}" == *"PRETTY_NAME"* ]]
}

@test "os-release: the branded identity passes and ID_LIKE may name the base" {
	# Falsification: add ID_LIKE to the judged keys and fedora/rhel fail this.
	check_os_release
	[ "$(status_of os-release.agree)" = pass ]
	[ "$(status_of os-release.name)" = pass ]
	[ "$(status_of os-release.denylist)" = pass ]
}

@test "hostname: DEFAULT_HOSTNAME and an installer-set name pass" {
	# Falsification: require DEFAULT_HOSTNAME only and the installer case fails.
	check_hostname
	[ "$(status_of hostname)" = pass ]
	BRANDING_CHECK_STATUS=()
	echo kitchen-pc >"$ROOT/proc/sys/kernel/hostname"
	echo kitchen-pc >"$ROOT/etc/hostname"
	check_hostname
	[ "$(status_of hostname)" = pass ]
}

@test "hostname: an upstream or fallback name fails (t68 'fedora login:')" {
	# Falsification: accept any hostname matching /etc/hostname and fedora passes.
	echo fedora >"$ROOT/proc/sys/kernel/hostname"
	echo fedora >"$ROOT/etc/hostname"
	check_hostname
	[ "$(status_of hostname)" = fail ]
	BRANDING_CHECK_STATUS=()
	echo localhost >"$ROOT/proc/sys/kernel/hostname"
	rm "$ROOT/etc/hostname"
	check_hostname
	[ "$(status_of hostname)" = fail ]
}

@test "hostname: an initramfs naming another default host fails" {
	# Falsification: skip initrd-release and early boot's 'fedora' goes unseen.
	mkdir -p "$ROOT/usr/lib/modules/6.12.0"
	touch "$ROOT/usr/lib/modules/6.12.0/initramfs.img"
	export TUNAOS_BRANDING_KVER=6.12.0
	stub lsinitrd 'printf "NAME=\"Fedora Linux\"\nDEFAULT_HOSTNAME=\"fedora\"\n"'
	check_hostname
	[ "$(status_of hostname)" = fail ]
	[[ "${BRANDING_CHECK_DETAIL[hostname]}" == *"initrd-release DEFAULT_HOSTNAME='fedora'"* ]]
}

@test "an initramfs whose initrd-release names upstream fails (yellowfin:xfce)" {
	# Falsification: drop check_initramfs_identity's denylist and this passes.
	mkdir -p "$ROOT/usr/lib/modules/6.12.0"
	touch "$ROOT/usr/lib/modules/6.12.0/initramfs.img"
	export TUNAOS_BRANDING_KVER=6.12.0
	stub lsinitrd 'printf "NAME=\"AlmaLinux Kitten\"\nPRETTY_NAME=\"AlmaLinux Kitten 10 (Lion Cub) dracut-107 (Initramfs)\"\n"'
	check_initramfs_identity
	[ "$(status_of initramfs.identity)" = fail ]
	BRANDING_CHECK_STATUS=()
	stub lsinitrd 'printf "NAME=\"Yellowfin\"\nPRETTY_NAME=\"Yellowfin (Initramfs)\"\n"'
	check_initramfs_identity
	[ "$(status_of initramfs.identity)" = pass ]
}

@test "boot entries must be titled with PRETTY_NAME" {
	# Falsification: pass on any title and the CentOS entry is accepted.
	mkdir -p "$ROOT/boot/loader/entries"
	printf 'title Yellowfin (ostree:0)\nversion 1\n' >"$ROOT/boot/loader/entries/ostree-1.conf"
	check_boot_bls
	[ "$(status_of boot.bls)" = pass ]
	BRANDING_CHECK_STATUS=()
	printf 'title CentOS Stream 10 (ostree:1)\n' >"$ROOT/boot/loader/entries/ostree-2.conf"
	check_boot_bls
	[ "$(status_of boot.bls)" = fail ]
}

@test "no readable boot entries is a failure, not a pass" {
	# Falsification: record skip when nothing is found and this reads skip.
	check_boot_bls
	[ "$(status_of boot.bls)" = fail ]
}

# EFI_LOAD_OPTION bytes for efivarfs: 4 attribute bytes, UINT32 Attributes,
# UINT16 FilePathListLength, UCS-2 description, NUL, then a device path.
ucs2() { # <ascii>
	local c i
	for ((i = 0; i < ${#1}; i++)); do
		c="${1:i:1}"
		printf "\\x$(printf '%02x' "'$c")\\x00"
	done
}

efivar() { # <BootNNNN> <label> [loader path]
	local f="$ROOT/sys/firmware/efi/efivars/$1-8be4df61-93ca-11d2-aa0d-00e098032b8c"
	mkdir -p "${f%/*}"
	{
		printf '\x07\x00\x00\x00\x01\x00\x00\x00\x04\x00'
		ucs2 "$2"
		printf '\x00\x00'
		if [[ -n "${3:-}" ]]; then
			printf '\x04\x04\x40\x00'
			ucs2 "$3"
			printf '\x00\x00'
		fi
		printf '\x7f\xff\x04\x00'
	} >"$f"
}

@test "an upstream firmware boot entry fails (t38 'AlmaLinux Kitten')" {
	# Falsification: break the UCS-2 decoder and no label matches the denylist.
	efivar Boot0001 "UEFI QEMU HARDDISK"
	efivar Boot000A "AlmaLinux Kitten" '\EFI\almalinux\shimx64.efi'
	check_boot_efi
	[ "$(status_of boot.efi)" = fail ]
	[[ "${BRANDING_CHECK_DETAIL[boot.efi]}" == *"Boot000A 'AlmaLinux Kitten'"* ]]
}

@test "variant-labelled firmware entries pass; BIOS boots skip" {
	# Falsification: fail when /sys/firmware/efi is absent and BIOS reads fail.
	check_boot_efi
	[ "$(status_of boot.efi)" = skip ]
	BRANDING_CHECK_STATUS=()
	efivar Boot0001 "Yellowfin" '\EFI\almalinux\shimx64.efi'
	check_boot_efi
	[ "$(status_of boot.efi)" = pass ]
	[[ "${BRANDING_CHECK_DETAIL[boot.efi]}" == *"shim entries: Boot0001='Yellowfin'"* ]]
}

@test "a shim entry must carry os-release NAME, even with a neutral label" {
	# Falsification: judge labels by the denylist only and 'Linux' passes.
	efivar Boot0003 "Linux" '\EFI\almalinux\shimx64.efi'
	check_boot_efi
	[ "$(status_of boot.efi)" = fail ]
	[[ "${BRANDING_CHECK_DETAIL[boot.efi]}" == *"is not labelled NAME 'Yellowfin'"* ]]
}

@test "the booted initramfs must carry the variant's own splash theme" {
	# Falsification: expect the project default (tunaos) and yellowfin passes
	# with the wrong theme.
	mkdir -p "$ROOT/usr/sbin" "$ROOT/usr/lib/modules/6.12.0/" "$ROOT/etc/plymouth"
	touch "$ROOT/usr/sbin/plymouthd" "$ROOT/usr/lib/modules/6.12.0/initramfs.img"
	printf '[Daemon]\nTheme=tunaos\n' >"$ROOT/etc/plymouth/plymouthd.conf"
	check_initramfs_plymouth
	[[ "${BRANDING_CHECK_DETAIL[initramfs.plymouth]}" == *"Theme='tunaos', want 'tropical-fish'"* ]]
	BRANDING_CHECK_STATUS=()
	printf '[Daemon]\nTheme=tropical-fish\n' >"$ROOT/etc/plymouth/plymouthd.conf"
	export TUNAOS_BRANDING_KVER=6.12.0
	stub lsinitrd 'echo "-rw-r--r-- 1 root root 244 Jan 1 1970 usr/share/plymouth/themes/tunaos/tunaos.plymouth"'
	check_initramfs_plymouth
	[ "$(status_of initramfs.plymouth)" = fail ]
	[[ "${BRANDING_CHECK_DETAIL[initramfs.plymouth]}" == *"lacks themes/tropical-fish; themes present: tunaos"* ]]
	BRANDING_CHECK_STATUS=()
	stub lsinitrd 'echo "usr/share/plymouth/themes/tropical-fish/tropical-fish.plymouth"'
	check_initramfs_plymouth
	[ "$(status_of initramfs.plymouth)" = pass ]
}

@test "flatpak remotes must equal the configured set (bonito's fedora remotes fail)" {
	# Falsification: test containment instead of equality and the extra
	# fedora remote passes.
	printf 'flathub\thttps://dl.flathub.org/repo/\ntuna-os\toci+https://tunaos.org/flatpak\n' \
		>"$ROOT/usr/share/tunaos/flatpak-remotes.expected"
	stub flatpak 'printf "flathub\thttps://dl.flathub.org/repo/\ntuna-os\toci+https://tunaos.org/flatpak\nfedora\toci+https://registry.fedoraproject.org/\n"'
	check_flatpak_remotes
	[ "$(status_of flatpak.remotes)" = fail ]
	BRANDING_CHECK_STATUS=()
	stub flatpak 'printf "tuna-os\toci+https://tunaos.org/flatpak\nflathub\thttps://dl.flathub.org/repo\n"'
	check_flatpak_remotes
	[ "$(status_of flatpak.remotes)" = pass ]
}

@test "the live session's installer-local remote is excluded on live boots only" {
	# Falsification: drop the live filter and the live boot fails.
	printf 'flathub\thttps://dl.flathub.org/repo/\n' >"$ROOT/usr/share/tunaos/flatpak-remotes.expected"
	stub flatpak 'printf "flathub\thttps://dl.flathub.org/repo/\ninstaller-local\tfile:///run/x\n"'
	echo 'BOOT_IMAGE=/vmlinuz root=live:CDLABEL=TUNAOS rd.live.image' >"$ROOT/proc/cmdline"
	check_flatpak_remotes
	[ "$(status_of flatpak.remotes)" = pass ]
	BRANDING_CHECK_STATUS=()
	echo 'BOOT_IMAGE=/vmlinuz root=UUID=1' >"$ROOT/proc/cmdline"
	check_flatpak_remotes
	[ "$(status_of flatpak.remotes)" = fail ]
}

@test "the installer catalog lists this project's images only (t68 Aurora entry fails)" {
	# Falsification: compare only the recipe imgref and the Aurora leaf passes.
	mkdir -p "$ROOT/etc/bootc-installer"
	echo '{"imgref": "ghcr.io/tuna-os/bonito:niri"}' >"$ROOT/etc/bootc-installer/recipe.json"
	printf '[{"name":"Bonito","imgref": "ghcr.io/tuna-os/bonito:niri"},{"name":"Aurora DX","imgref": "ghcr.io/ublue-os/aurora-dx:43"}]\n' >"$ROOT/etc/bootc-installer/images.json"
	check_installer_catalog
	[ "$(status_of installer.catalog)" = fail ]
	[[ "${BRANDING_CHECK_DETAIL[installer.catalog]}" == *"ghcr.io/ublue-os/aurora-dx:43"* ]]
	BRANDING_CHECK_STATUS=()
	printf '[{"imgref": "ghcr.io/tuna-os/bonito:niri"},{"imgref":"ghcr.io/tuna-os/bonito:gnome"}]\n' >"$ROOT/etc/bootc-installer/images.json"
	check_installer_catalog
	[ "$(status_of installer.catalog)" = pass ]
}

@test "fastfetch must name the variant through the user's aliases; the attribution is allowed" {
	# Falsification: run fastfetch without an interactive login shell and the
	# alias to Bluefin's config below is never seen.
	printf "TUNAOS_PROJECT_NAME=TunaOS\n" >>"$ROOT/usr/share/tunaos/identity-config.env"
	stub fastfetch 'if [[ "${1:-}" == --config ]]; then printf "OS: Bluefin\n"; else printf "root@x\n---\nsystem    Yellowfin  ·  part of TunaOS, built on AlmaLinux Kitten\nkernel 6.12\n"; fi'
	check_fastfetch
	[ "$(status_of fastfetch)" = pass ]
	[ "$(status_of motd)" = pass ]
	BRANDING_CHECK_STATUS=()
	stub fastfetch 'printf "OS: AlmaLinux Kitten 10 x86_64\n"'
	check_fastfetch
	[ "$(status_of fastfetch)" = fail ]
}

@test "an account showing an upstream system wallpaper fails; its own picture passes" {
	# Falsification: classify every non-empty value as variant and both pass.
	mkdir -p "$ROOT/home/alice" "$ROOT/home/bob"
	printf 'root:x:0:0::/root:/bin/bash\nalice:x:1000:1000::/home/alice:/bin/bash\nbob:x:1001:1001::/home/bob:/bin/bash\n' >"$ROOT/etc/passwd"
	stub dconf 'case "$HOME" in *alice) echo "'"'"'file:///usr/share/backgrounds/gnome/adwaita-l.jxl'"'"'" ;; *) echo "'"'"'file:///home/bob/cat.png'"'"'" ;; esac'
	check_user_look gnome
	[ "$(status_of desktop.gnome.user)" = fail ]
	[[ "${BRANDING_CHECK_DETAIL[desktop.gnome.user]}" == *"alice"* ]]
	[[ "${BRANDING_CHECK_DETAIL[desktop.gnome.user]}" != *"bob:"* ]]
}

@test "no human account yet skips the per-account readback" {
	# Falsification: pass with zero accounts and the report overstates coverage.
	printf 'root:x:0:0::/root:/bin/bash\n' >"$ROOT/etc/passwd"
	check_user_look kde
	[ "$(status_of desktop.kde.user)" = skip ]
}

# ── per-desktop checkers ─────────────────────────────────────────────────────

wallpapers() { # <desktop>
	printf 'variant' >"$ROOT/usr/share/backgrounds/tunaos/yellowfin.jpg"
	cp "$ROOT/usr/share/backgrounds/tunaos/yellowfin.jpg" "$ROOT/usr/share/backgrounds/tunaos/tunaos-default.jpg"
}

dm() { # <unit>
	mkdir -p "$ROOT/etc/systemd/system"
	ln -sfn "/usr/lib/systemd/system/$1" "$ROOT/etc/systemd/system/display-manager.service"
}

@test "cosmic: the stock cosmic-bg default fails, the variant's passes" {
	# Falsification: check only that the config file exists and stock passes.
	wallpapers
	dm cosmic-greeter.service
	mkdir -p "$ROOT/usr/share/cosmic/com.system76.CosmicBackground/v1"
	echo '(output: "all", source: Path("/usr/share/backgrounds/cosmic/orion.jpg"))' >"$ROOT/usr/share/cosmic/com.system76.CosmicBackground/v1/all"
	run "${CHECKS}/verify-branding-cosmic.sh" yellowfin
	[ "$status" -eq 1 ]
	[[ "$output" == *"source=/usr/share/backgrounds/cosmic/orion.jpg"* ]]
	echo '(output: "all", source: Path("/usr/share/backgrounds/tunaos/tunaos-default.jpg"))' >"$ROOT/usr/share/cosmic/com.system76.CosmicBackground/v1/all"
	run "${CHECKS}/verify-branding-cosmic.sh" yellowfin
	[ "$status" -eq 0 ]
	[[ "$output" == *"TUNAOS_BRANDING_COSMIC_OK variant=yellowfin"* ]]
}

xfce_applier() {
	mkdir -p "$ROOT/etc/xdg/autostart" "$ROOT/usr/libexec/tunaos"
	printf '[Desktop Entry]\nExec=/usr/libexec/tunaos/xfce-wallpaper\nOnlyShowIn=XFCE;\n' >"$ROOT/etc/xdg/autostart/tunaos-xfce-wallpaper.desktop"
	printf '#!/bin/sh\nwallpaper=/usr/share/backgrounds/tunaos/tunaos-default.jpg\n' >"$ROOT/usr/libexec/tunaos/xfce-wallpaper"
	chmod +x "$ROOT/usr/libexec/tunaos/xfce-wallpaper"
}

@test "xfce: the LightDM GTK greeter's last background= wins" {
	# Falsification: read the first conf.d file only and Debian's 01 wins wrongly.
	wallpapers
	xfce_applier
	dm lightdm.service
	mkdir -p "$ROOT/usr/share/lightdm/lightdm-gtk-greeter.conf.d" "$ROOT/etc/lightdm"
	printf '[greeter]\nbackground=/usr/share/images/desktop-base/login.svg\n' >"$ROOT/usr/share/lightdm/lightdm-gtk-greeter.conf.d/01_debian.conf"
	printf '[greeter]\nbackground=/usr/share/backgrounds/tunaos/tunaos-default.jpg\n' >"$ROOT/usr/share/lightdm/lightdm-gtk-greeter.conf.d/90-tunaos.conf"
	run "${CHECKS}/verify-branding-xfce.sh" yellowfin --runtime
	[ "$status" -eq 0 ]
	printf '[greeter]\nbackground=#000000\n' >"$ROOT/etc/lightdm/lightdm-gtk-greeter.conf"
	run "${CHECKS}/verify-branding-xfce.sh" yellowfin --runtime
	[ "$status" -eq 1 ]
	[[ "$output" == *"lightdm-gtk-greeter background=#000000"* ]]
}

@test "xfce: a greetd wrapper script is followed to gtkgreet's stylesheet (yellowfin:xfce)" {
	# Falsification: judge the command name only and the wrapper fails.
	wallpapers
	xfce_applier
	dm greetd.service
	mkdir -p "$ROOT/etc/greetd"
	printf '[default_session]\ncommand = "/usr/libexec/tunaos/greetd-session"\n' >"$ROOT/etc/greetd/config.toml"
	printf '#!/usr/bin/env bash\nexec cage -s -- gtkgreet -s /etc/greetd/gtkgreet.css\n' >"$ROOT/usr/libexec/tunaos/greetd-session"
	echo 'window { background-image: url("file:///usr/share/backgrounds/tunaos/tunaos-default.jpg"); }' >"$ROOT/etc/greetd/gtkgreet.css"
	run "${CHECKS}/verify-branding-xfce.sh" yellowfin --runtime
	[ "$status" -eq 0 ]
}

@test "xfce: xfdesktop's compiled default backdrop must be the variant wallpaper" {
	# Falsification: skip the compiled-default check and stock xfce-x.svg passes.
	wallpapers
	xfce_applier
	dm greetd.service
	mkdir -p "$ROOT/etc/greetd" "$ROOT/usr/bin" "$ROOT/usr/share/backgrounds/xfce"
	printf '[default_session]\ncommand = "gtkgreet"\n' >"$ROOT/etc/greetd/config.toml"
	echo 'url("file:///usr/share/backgrounds/tunaos/tunaos-default.jpg")' >"$ROOT/etc/greetd/gtkgreet.css"
	printf 'ELF\0/usr/share/backgrounds/xfce/xfce-x.svg\0/usr/share/backgrounds/xfce/xfce-teal.png\0' >"$ROOT/usr/bin/xfdesktop"
	echo stock >"$ROOT/usr/share/backgrounds/xfce/xfce-x.svg"
	run "${CHECKS}/verify-branding-xfce.sh" yellowfin --runtime
	[ "$status" -eq 1 ]
	[[ "$output" == *"compiled default /usr/share/backgrounds/xfce/xfce-x.svg is not the variant wallpaper"* ]]
	ln -sfn ../tunaos/tunaos-default.jpg "$ROOT/usr/share/backgrounds/xfce/xfce-x.svg"
	run "${CHECKS}/verify-branding-xfce.sh" yellowfin --runtime
	[ "$status" -eq 0 ]
}

@test "cosmic: a theme-specific default naming stock art fails; the greeter fallback is only noted" {
	# Falsification: ignore CosmicBackground.Dark and the stock dark default passes.
	wallpapers
	dm cosmic-greeter.service
	for id in com.system76.CosmicBackground com.system76.CosmicBackground.Dark; do
		mkdir -p "$ROOT/usr/share/cosmic/$id/v1"
		echo '(source: Path("/usr/share/backgrounds/tunaos/tunaos-default.jpg"))' >"$ROOT/usr/share/cosmic/$id/v1/all"
	done
	run "${CHECKS}/verify-branding-cosmic.sh" yellowfin --runtime
	[ "$status" -eq 0 ]
	[[ "$output" == *"compiled-in fallback (open, not judged)"* ]]
	echo '(source: Path("/usr/share/backgrounds/cosmic/orion_nebula.jpg"))' >"$ROOT/usr/share/cosmic/com.system76.CosmicBackground.Dark/v1/all"
	run "${CHECKS}/verify-branding-cosmic.sh" yellowfin --runtime
	[ "$status" -eq 1 ]
}

@test "xfce: a missing first-login applier fails" {
	# Falsification: skip the autostart check and stock xfdesktop passes.
	wallpapers
	dm greetd.service
	run "${CHECKS}/verify-branding-xfce.sh" yellowfin --runtime
	[ "$status" -eq 1 ]
	[[ "$output" == *"nothing applies the wallpaper at first login"* ]]
}

@test "pantheon: the schema default is read as Pantheon reads it" {
	# Falsification: drop XDG_CURRENT_DESKTOP=Pantheon and the stub answers the
	# plain section, a false pass (gurnard:pantheon 263de4c818f4).
	wallpapers
	stub gsettings 'if [[ "${XDG_CURRENT_DESKTOP:-}" == Pantheon ]]; then echo "'"'"'file:///usr/share/backgrounds/elementaryos-default'"'"'"; else echo "'"'"'file:///usr/share/backgrounds/tunaos/tunaos-default.jpg'"'"'"; fi'
	ln -s tunaos/tunaos-default.jpg "$ROOT/usr/share/backgrounds/elementaryos-default"
	run "${CHECKS}/verify-branding-pantheon.sh" yellowfin --runtime
	[ "$status" -eq 1 ]
	[[ "$output" == *"session picture-uri='file:///usr/share/backgrounds/elementaryos-default'"* ]]
	stub gsettings 'echo "'"'"'file:///usr/share/backgrounds/tunaos/tunaos-default.jpg'"'"'"'
	run "${CHECKS}/verify-branding-pantheon.sh" yellowfin --runtime
	[ "$status" -eq 0 ]
}

@test "pantheon: the greeter's no-account fallback must be the variant wallpaper" {
	# Falsification: skip the elementaryos-default check and this passes.
	wallpapers
	stub gsettings 'echo "'"'"'file:///usr/share/backgrounds/tunaos/tunaos-default.jpg'"'"'"'
	run "${CHECKS}/verify-branding-pantheon.sh" yellowfin --runtime
	[ "$status" -eq 1 ]
	[[ "$output" == *"elementaryos-default is absent"* ]]
}

# ── installer and wiring ─────────────────────────────────────────────────────

@test "the installer lays down the checker, every desktop checker, the table and an enabled unit" {
	# Falsification: forget one desktop checker or the enable symlink and this fails.
	DEST="${ROOT}/img"
	TUNAOS_BUILD_CONTEXT="$REPO_ROOT" TUNAOS_BRANDING_DEST="$DEST" \
		run "${REPO_ROOT}/build_scripts/install-branding-contract.sh"
	[ "$status" -eq 0 ]
	for f in verify-branding verify-branding-gnome verify-branding-kde verify-branding-niri \
		verify-branding-cosmic verify-branding-xfce verify-branding-pantheon; do
		[ -x "$DEST/usr/libexec/tunaos/$f" ]
	done
	[ -f "$DEST/usr/libexec/tunaos/verify-branding-runtime.sh" ]
	[ -f "$DEST/usr/share/tunaos/branding/variant-identity.tsv" ]
	unit="$DEST/usr/lib/systemd/system/tunaos-branding-contract.service"
	grep -qx 'ExecStart=/usr/libexec/tunaos/verify-branding --runtime' "$unit"
	! grep -q 'ExecStart=-' "$unit"
	[ -L "$DEST/etc/systemd/system/multi-user.target.wants/tunaos-branding-contract.service" ]
	TUNAOS_BRANDING_DEST="$DEST" run "${REPO_ROOT}/build_scripts/install-branding-contract.sh" --desktop xfce
	grep -qx 'Environment=TUNAOS_BRANDING_DESKTOP=xfce' "$DEST/usr/lib/systemd/system/tunaos-branding-contract.service.d/10-desktop.conf"
}

@test "the installer is reached on every base: 90-image-info.sh calls it after its last exit" {
	# Falsification: move the call into 40-services.sh (whose apt/pacman paths
	# exit early and which Gentoo never runs) and this fails.
	info="${REPO_ROOT}/build_scripts/90-image-info.sh"
	call="$(grep -n '^/run/context/build_scripts/install-branding-contract.sh$' "$info" | cut -d: -f1)"
	[ -n "$call" ]
	last_exit="$(grep -nE '^[[:space:]]*exit[[:space:]]+0' "$info" | tail -1 | cut -d: -f1)"
	[ -z "$last_exit" ] || [ "$call" -gt "$last_exit" ]
	grep -q 'install-branding-contract.sh" --desktop "${_TD_DESKTOP}"' "${REPO_ROOT}/build_scripts/desktop/install-desktop.sh"
	grep -q 'install-branding-contract.sh --desktop "$desktop"' "${REPO_ROOT}/build_scripts/desktop/configure-desktop-runtime.sh"
}

@test "no unit runs a branding checker with failures ignored" {
	# Falsification: restore ExecStart=-/usr/libexec/tunaos/verify-branding.
	! grep -rn 'ExecStart=-/usr/libexec/tunaos/verify-branding' "${REPO_ROOT}/build_scripts"
}
