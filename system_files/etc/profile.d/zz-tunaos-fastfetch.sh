# shellcheck shell=bash
# The variant's own fastfetch (build_scripts/90-image-info.sh). Sorts after
# ublue-fastfetch.sh, whose aliases point at Bluefin's config and logos.
if [ -r /etc/xdg/fastfetch/config.jsonc ]; then
	alias fastfetch='fastfetch --config /etc/xdg/fastfetch/config.jsonc'
	alias neofetch='fastfetch --config /etc/xdg/fastfetch/config.jsonc'
	alias neowofetch='fastfetch --config /etc/xdg/fastfetch/config.jsonc'
fi
