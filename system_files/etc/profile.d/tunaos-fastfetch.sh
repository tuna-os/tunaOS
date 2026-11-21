# shellcheck shell=bash
# neofetch runs fastfetch. There is no `fastfetch` alias: plain fastfetch reads
# ~/.config/fastfetch first, then the variant's /etc/xdg/fastfetch/config.jsonc
# (build_scripts/90-image-info.sh). An alias with --config would hide a user's
# own config. 90-image-info.sh deletes ublue's aliases to Bluefin's config.
alias neofetch='fastfetch'
alias neowofetch='fastfetch'
