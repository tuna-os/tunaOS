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

# Keep in step with the variant's emoji in .github/build-config.yml;
# tests/bats/test_plymouth_themes.bats checks both.
case "$variant" in
yellowfin | almalinux-kitten) theme=tropical-fish ;; # 🐠
albacore | almalinux) theme=tunaos ;;                # 🐟
skipjack | centos) theme=sushi ;;                    # 🍣
wahoo) theme=carp-streamer ;;                        # 🎏
bonito | fedora) theme=fishing-pole ;;               # 🎣
hummingbird) theme=bird ;;                           # 🐦
sailfin | opensuse | tumbleweed) theme=sailboat ;;   # ⛵
guppy | gentoo) theme=rainbow ;;                     # 🌈
bonito-rawhide) theme=dragon ;;                      # 🐉
gurnard | elementary) theme=robot ;;                 # 🤖
grouper | ubuntu) theme=coral ;;                     # 🪸
marlin | arch | archlinux) theme=rocket ;;           # 🚀
flounder | debian) theme=pufferfish ;;               # 🐡
flounder-sid) theme=radioactive ;;                   # ☢️
*) theme=tunaos ;;
esac
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
if command -v plymouth-set-default-theme >/dev/null 2>&1; then
	plymouth-set-default-theme "$theme" || true
fi
ln -sfn "${theme}/${theme}.plymouth" /usr/share/plymouth/themes/default.plymouth

echo "plymouth-set-theme: ${variant:-unknown} -> ${theme}"
