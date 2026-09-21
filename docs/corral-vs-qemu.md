# Corral vs raw QEMU — parity for live-ISO testing

`corral` (tuna-os/corral) now implements the same QEMU surface that
`tuna-os/tunaos` hand-rolls in `scripts/iso-e2e.sh`, `bench-gdm-paint.sh`
and `run-walkthrough.sh`. Use it wherever you would invoke
`qemu-system-x86_64` directly.

## What corral covers (a3f4a16+)

| QEMU concern in tunaos | corral equivalent |
|---|---|
| `-device vhost-vsock-pci,guest-cid=X` + per-run `ssh-keygen` + two `type=11` SMBIOS `ssh.*` credentials + `socat VSOCK-CONNECT` (the `setup_vsock` fallback for published-media sshd disabled) | `corral create --vsock [--vsock-cid N]` → per-VM `vhost-vsock-pci` + keypair + SMBIOS; `corral ssh --vsock`, `ExecViaVsock` |
| `swtpm socket --tpm2` + `-chardev socket -tpmdev emulator -device tpm-crb` per-boot with `keep` state across the install→first-boot→verify chain (LUKS `tpm2-luks`) | `corral create --tpm` → per-VM `swtpm` dir/socket + `tpm-crb` wiring + `StartSwtpm/StopSwtpm` lifecycle (GH runner needs `swtpm` package) |
| `-chardev file,append=on -serial` + `BOOT_START` polling of `serial.log` for `TUNAOS_LIVE_READY` / `Reached target Graphical` / `Entering emergency mode` (the evidence that survives no-SSH boot) | `corral logs <vm> --serial [--tail N]` + `WaitSerial`/`BootFailedOnSerial` |
| `screendump` over `qmp.sock` (or VNC `socat` bridge + `vncdotool`) + `convert … standard_deviation` vs `0.02` blank gate | `corral screenshot <vm> [--require-paint]` + `Capture()` (`StdDev`/`Blank()`) + `frame: 0.02` floor identical to `iso-e2e.sh`; QMP path works for `virtio`/`q35` and virgl fallback is VNC |
| ` -qmp unix:qmp.sock,server,nowait` + `send-key type/key` for LUKS/passphrase/greeter (published-media has no agent) | `corral type <vm> 'text'`, `corral key <vm> ret/ctrl alt f2` + `QMPExec`/`qmp <vm> query-status` |
| `journalctl --user -u corral-…` / `virt-launcher` logs + evidence bundle (`serial.log`, `screenshot.png`, `journal.log`, `qmp-status.json`, `diagnostics.txt`) | `corral diagnose <vm> [--bundle-dir DIR] [--json]` (layout matches `scripts/evidence-bundle.sh`) + `corral doctor` host checks: `VSOCK host support` (`/dev/vhost-vsock`, `socat` vsock, `ssh-keygen`), `swtpm`, `OVMF firmware`, `socat`, `qemu-img` |

## Quick replacements

```bash
# Live ISO — was: 3 pages of -machine/-cpu/-accel/-drive/-netdev/-vsock/-tpm/-qmp/-serial...
corral create live --iso ./yellowfin-gnome.iso --firmware uefi --vsock --tpm --mem 4G --cpu 4 --disk 32G
corral start live
corral logs live --serial            # instead of tail -f serial.log
corral screenshot live --require-paint
corral diagnose live --bundle-dir ./diag-out   # serial + screenshot + journal + QMP
corral ssh live --vsock              # fallback when TCP hostfwd reset (published media)
corral type live 'my passphrase' --enter
corral qmp live query-status
corral stop live; corral delete live --force
```

Set `USE_CORRAL=1` in the helpers below and they delegate to corral automatically; raw QEMU remains the fallback (`command -v corral` check).

| Helper | corral path |
|---|---|
| `scripts/bench-gdm-paint.sh <qcow2> --label X` | `USE_CORRAL=1 bench-gdm-paint.sh …` → `corral create --qcow … --vsock --firmware uefi`, `corral screenshot` stddev 0.02 gate, `corral logs --serial`, `corral diagnose --bundle-dir`, auto-cleanup |
| `scripts/run-walkthrough.sh <iso> [out]` | `USE_CORRAL=1 run-walkthrough.sh …` → `corral create --iso … --vsock`, `corral diagnose` |
| `scripts/iso-e2e.sh <iso> …` | `USE_CORRAL=1 iso-e2e.sh …` → `corral create --iso … --vsock --tpm --firmware uefi`, `corral qmp`/`type`/`key` for published-media, `corral diagnose` bundle matches CI artifacts |

Workflows install `corral@latest` (already in `reusable-build-image.yml`) and can set `USE_CORRAL=1` per-job; the raw-QEMU path is unchanged for hosts without corral.

## When to stay on raw QEMU

* You need a one-off `-snapshot` or multi-disk (`swap`/`scratch`) layout that `corral create` does not yet expose — keep the harness or contribute `--extra-disk`.
* You are on `aarch64` `virt` + `AAVMF` (corral's OVMF probe covers `x86_64` `q35` first).

In those cases keep the script; the doctor above will still report what the host is missing.
