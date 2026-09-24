# The variant's own fastfetch (build_scripts/90-image-info.sh), ahead of ublue's.
if test -r /etc/xdg/fastfetch/config.jsonc
    alias fastfetch 'command fastfetch --config /etc/xdg/fastfetch/config.jsonc'
    alias neofetch 'command fastfetch --config /etc/xdg/fastfetch/config.jsonc'
end
