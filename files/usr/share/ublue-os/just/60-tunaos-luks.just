# vim: set ft=make :

# Enroll this machine's TPM2 chip so the encrypted disk unlocks at boot without a passphrase (run once, after install)
enable-luks-tpm2 *ARGS:
    #!/usr/bin/env bash
    # Wraps /usr/bin/tunaos-luks-tpm2-enroll. TPM2 auto-unlock is a post-install
    # step (the PCRs it seals to only exist on the real installed system), so the
    # installer sets a passphrase and you opt in here — same model as Bazzite/
    # ublue-os. Pass --pin to also require a PIN.
    echo 'Enabling TPM2 auto-unlock for your encrypted disk...'
    echo 'Keep your LUKS passphrase — a firmware or Secure Boot change will require it again.'
    sudo /usr/bin/tunaos-luks-tpm2-enroll {{ ARGS }}

# Remove this machine's TPM2 enrollment (revert to passphrase-only unlock)
disable-luks-tpm2:
    #!/usr/bin/env bash
    set -euo pipefail
    uuid=""
    for tok in $(< /proc/cmdline); do
      case "$tok" in
        rd.luks.uuid=luks-*) uuid="${tok#rd.luks.uuid=luks-}" ;;
        rd.luks.uuid=*) uuid="${tok#rd.luks.uuid=}" ;;
        rd.luks.name=*) uuid="${tok#rd.luks.name=}"; uuid="${uuid%%=*}" ;;
      esac
    done
    [[ -n "$uuid" ]] || { echo 'No LUKS device on the kernel cmdline.'; exit 1; }
    dev="/dev/disk/by-uuid/${uuid}"
    echo "Wiping TPM2 keyslots on ${dev} (your passphrase keeps working)..."
    sudo systemd-cryptenroll --wipe-slot=tpm2 "$dev"
