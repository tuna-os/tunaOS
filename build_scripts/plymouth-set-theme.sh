#!/usr/bin/env bash
# Select this variant's boot animation, before the initramfs is built.
#
#   plymouth-set-theme.sh [variant]
#   plymouth-set-theme.sh --print [variant]   # name the theme, change nothing
#
# Each variant boots into its own Noto Emoji animation
# (system_files/usr/share/plymouth/themes/<theme>/). Until this script, only
# the EL10 path selected one (26-packages-post.sh); every other base built its
# initramfs with the distro's own splash, so marlin, grouper, flounder,
# sailfin and guppy booted with upstream artwork although the themes sat in
# the image. The theme must be chosen BEFORE dracut runs, because dracut
# copies the configured theme into the initramfs, and on the Arch, Debian and
# Gentoo bases dracut runs before system_files is copied in. So the theme
# directory is taken from the build context when the image lacks it.
#
# Callers: 26-packages-post.sh (EL10), bootc/dracut-config.sh (Arch, Debian,
# Gentoo), bootc/finalize.sh (Ubuntu), and Containerfile.opensuse.

set -euo pipefail

print_only=false
if [[ "${1:-}" == --print ]]; then
	print_only=true
	shift
fi
variant="${1:-${IMAGE_NAME_VARIANT:-${IMAGE_NAME:-}}}"
if [[ -z "$variant" && -r /usr/lib/os-release ]]; then
	variant="$(sed -n 's/^VARIANT_ID=//p' /usr/lib/os-release | tr -d '"')"
fi

# The theme is each variant's branding.plymouth in tunaos.toml, through the
# generated adapters beside this script. Base-derived names ("opensuse") fold
# onto their variant first; anything else gets the project default.
lib="$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/lib"
# shellcheck source=lib/identity.env
source "${lib}/identity.env"
canonical="$(awk -F'\t' -v alias="$variant" '$1 == alias { print $2 }' "${lib}/variant-aliases.tsv")"
theme="$(awk -F'\t' -v id="${canonical:-$variant}" '$1 == id { print $6 }' "${lib}/variant-identity.tsv")"
theme="${theme:-${TUNAOS_PLYMOUTH_THEME}}"
if $print_only; then
	echo "$theme"
	exit 0
fi

dest="/usr/share/plymouth/themes/${theme}"
if [[ ! -f "${dest}/${theme}.plymouth" ]]; then
	src="/run/context/files/usr/share/plymouth/themes/${theme}"
	if [[ ! -f "${src}/${theme}.plymouth" ]]; then
		echo "plymouth-set-theme: no ${theme} theme in the image or the build context; leaving the default" >&2
		exit 0
	fi
	install -d "$dest"
	cp -a "${src}/." "$dest/"
fi

# No plymouth, nothing to theme (base images without a desktop may lack it).
if ! command -v plymouthd >/dev/null 2>&1 && ! compgen -G "/usr/*bin/plymouthd" >/dev/null; then
	echo "plymouth-set-theme: plymouth is not installed; nothing to select"
	exit 0
fi

# Our themes use the script plugin. Selecting one without it boots to plain
# text, which is worse than the distro splash, so keep that instead.
if ! compgen -G "/usr/lib*/plymouth/script.so" >/dev/null &&
	! compgen -G "/usr/lib*/*/plymouth/script.so" >/dev/null; then
	echo "plymouth-set-theme: the plymouth script plugin is missing; keeping the distro theme" >&2
	exit 0
fi

# plymouthd.conf is what every distro's plymouth reads; write it directly
# rather than trusting plymouth-set-default-theme, which Debian implements
# with alternatives and some bases do not ship at all.
conf=/etc/plymouth/plymouthd.conf
install -d "$(dirname "$conf")"
if [[ -f "$conf" ]] && grep -q '^\[Daemon\]' "$conf"; then
	if grep -q '^Theme=' "$conf"; then
		sed -i "s/^Theme=.*/Theme=${theme}/" "$conf"
	else
		sed -i "/^\[Daemon\]/a Theme=${theme}" "$conf"
	fi
else
	printf '[Daemon]\nTheme=%s\n' "$theme" >>"$conf"
fi
# Debian and Ubuntu keep the default theme in the dpkg alternative
# default.plymouth (/etc/alternatives/default.plymouth), and the initramfs
# follows THAT, not plymouthd.conf and not the hand-made themes/default.plymouth
# link. Measured on the published grouper image (iso-builder run 42318386139):
# themes/default.plymouth pointed at coral and plymouthd.conf said Theme=coral,
# yet the initramfs carried only the bgrt theme and no script.so, because the
# alternative still pointed at bgrt (plymouth-set-default-theme does not exist
# in that image). The LUKS prompt booted as unbranded text.
# Register our theme as an alternative of higher priority and select it; the
# alternative owns the default.plymouth link, so it is not replaced by hand.
alternatives_done=false
if command -v update-alternatives >/dev/null 2>&1 &&
	{ [[ -L /etc/alternatives/default.plymouth ]] || [[ -f /var/lib/dpkg/alternatives/default.plymouth ]]; }; then
	if update-alternatives --install /usr/share/plymouth/themes/default.plymouth default.plymouth \
		"${dest}/${theme}.plymouth" 200 &&
		update-alternatives --set default.plymouth "${dest}/${theme}.plymouth"; then
		alternatives_done=true
	else
		echo "plymouth-set-theme: update-alternatives failed for ${theme}" >&2
	fi
fi
if command -v plymouth-set-default-theme >/dev/null 2>&1; then
	plymouth-set-default-theme "$theme" || true
fi
if ! $alternatives_done; then
	ln -sfn "${theme}/${theme}.plymouth" /usr/share/plymouth/themes/default.plymouth
fi

# plymouthd shows the graphical splash only when the kernel command line asks
# for one ("splash" or "rhgb"; plymouth_should_show_default_splash). The
# Debian/Ubuntu installers add "quiet splash" through GRUB defaults, which bootc
# never reads, so a bootc grouper booted with no such karg and plymouth fell
# back to text: the rebuilt image's initramfs held coral and script.so, yet the
# LUKS prompt was the plain console agent (iso-builder run 42374980522). bootc
# applies kargs.d at install and on upgrade. Where the alternative path above
# ran (the Debian family), on openSUSE, whose "splash=silent" likewise lives
# only in /etc/default/grub, and on Gentoo; Fedora/EL already boot their splash.
# Gentoo measured by booting guppy:gnome's kernel and initramfs (plymouth
# 22.02.122) against a LUKS2 disk: with `splash` the rainbow theme drew the
# passphrase prompt, without it the prompt was the bare console agent.
splash_karg=$alternatives_done
if grep -qsE '^ID_LIKE=.*suse' /usr/lib/os-release || command -v emerge >/dev/null 2>&1; then
	splash_karg=true
fi
if $splash_karg; then
	install -d /usr/lib/bootc/kargs.d
	printf 'kargs = ["splash"]\n' >/usr/lib/bootc/kargs.d/10-tunaos-plymouth-splash.toml
fi

# Script themes draw the LUKS prompt with Image.Text, i.e. plymouth's
# label-freetype plugin, which asks `/usr/bin/fc-match` for a font path. The
# initramfs has no fc-match, and plymouth before upstream commit 792fe74
# (EL10 ships 24.004.60) then opens "" instead of its Plymouth.ttf fallback:
# no font, no text, and the passphrase prompt is invisible (tunaOS#4090).
# Ship fc-match and its config into the initramfs; dracut pulls in the
# libraries. Harmless where plymouth already falls back correctly.
if [[ -x /usr/bin/fc-match && -f /etc/fonts/fonts.conf ]]; then
	install -d /usr/lib/dracut/dracut.conf.d
	echo 'install_items+=" /usr/bin/fc-match /etc/fonts/fonts.conf "' \
		>/usr/lib/dracut/dracut.conf.d/45-tunaos-plymouth-fonts.conf
else
	echo "plymouth-set-theme: no fc-match/fontconfig; the LUKS prompt text may not render" >&2
fi

# plymouth 22.02 (Gentoo's stable sys-boot/plymouth; 24.004.60 is masked in
# ::gentoo) predates the populate-initrd that installs a label plugin and its
# fonts, so its initramfs carries script.so and no label.so at all: every
# Image.Text in the theme, the LUKS prompt included, draws nothing. Measured
# on guppy:gnome with plymouth-22.02.122-r4: lsinitrd listed details, text,
# script and the drm/frame-buffer renderers, no label. Where the populate
# script does not install a label plugin itself, ship it with the fonts
# fontconfig resolves for the default faces; dracut pulls in its libraries.
# Upstream 23.360+ installs it with a code line
# `inst ${PLYMOUTH_PLUGIN_PATH}/label-freetype.so $INITRDDIR`; 22.02.122 has
# no label line at all. Only such an inst line counts: the word "label" in a
# comment or another identifier does not install anything.
populate_installs_label() {
	grep -Eq '^[[:space:]]*inst[[:space:]]+[^#]*/label(-[a-z]+)?\.so([[:space:]]|$)' "$1"
}
populate="$(compgen -G "/usr/libexec/plymouth/plymouth-populate-initrd" || compgen -G "/usr/lib*/plymouth/plymouth-populate-initrd" || true)"
populate="${populate%%$'\n'*}"
label="$(compgen -G "/usr/lib*/plymouth/label.so" || true)"
label="${label%%$'\n'*}"
if [[ -n "$populate" && -n "$label" ]] && ! populate_installs_label "$populate"; then
	fonts=()
	for face in sans-serif monospace; do
		font="$(fc-match -f '%{file}' "$face" 2>/dev/null || true)"
		[[ -n "$font" && -f "$font" ]] && fonts+=("$font")
	done
	if ((${#fonts[@]} == 0)); then
		echo "plymouth-set-theme: no font for ${label}; the LUKS prompt text will not render" >&2
		exit 1
	fi
	install -d /usr/lib/dracut/dracut.conf.d
	printf 'install_items+=" %s %s "\n' "$label" "${fonts[*]}" \
		>/usr/lib/dracut/dracut.conf.d/46-tunaos-plymouth-label.conf
fi

echo "plymouth-set-theme: ${variant:-unknown} -> ${theme}"
