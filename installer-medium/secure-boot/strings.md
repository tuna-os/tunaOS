# Secure Boot strings for the installer frontends

Each frontend shows these strings. The text is the same on each desktop.
`tuna-secure-boot plan` prints the `string=` ID for the done page.
The daemon passes that ID to the frontend. Do not show an ID that the plan
did not print.

Source for each MokManager label: `rhboot/shim` `MokManager.c` at
`e794a714339b`. The labels are English on every machine, because MokManager
has no translations. Translate the text around a label, not the label.

## Before the first boot of the medium

Show this text where the user downloads or writes the medium. It applies
only to a `tunaos-key` cell. A `distro-chain` cell needs no text here.

### `sb.medium.first-boot.title`

> The first start asks you to trust tunaOS

### `sb.medium.first-boot.body`

> This computer has Secure Boot on, and it does not know the tunaOS key yet.
> The first start shows a blue screen. You do five steps, once. You need
> no password.

> 1. Press a key in the first 10 seconds.
> 2. Choose **Enroll key from disk**.
> 3. Choose the volume with the name **TUNAOS-ESP**.
> 4. Choose the file **tunaos-secure-boot.cer**, then **Continue**.
> 5. Answer **Yes**, then choose **Reboot**.

> The computer starts tunaOS after that. It does not ask again.

MokManager shows the FAT label of each volume. With no label it shows a
device path (`lib/simple_file.c:211-219`). So the medium build must give the
ESP the FAT label `TUNAOS-ESP`. Until it does, step 3 must say "the first
volume in the list".

### `sb.medium.first-boot.missed`

> No key press in 10 seconds? The computer shows an error, or it starts
> another system. Start from the tunaOS medium again and press a key when the
> blue screen shows.

### `sb.medium.first-boot.vm`

> In a virtual machine with no keys, tunaOS adds its key by itself. The
> machine restarts once.

## Done page

### `sb.done.on`

> Secure Boot is on. This computer trusts the system that you installed.
> The disk unlocks with no prompt.

### `sb.done.off`

> Secure Boot is off on this computer. tunaOS works without it.
> If you turn Secure Boot on later, the disk asks once for your recovery key.
> Then run `tuna-secure-boot reseal`.

### `sb.done.no-uefi`

> This computer did not start with UEFI, so it has no Secure Boot.

### `sb.done.not-enrolled`

> Secure Boot is on, but this computer does not trust the tunaOS key.
> The disk unlocks with your recovery key until you add the key. Start the
> tunaOS medium again and follow the blue screen.

## Handoff page, before the install starts

### `sb.handoff.setup-mode.title`

> This computer can add the tunaOS key by itself

### `sb.handoff.setup-mode.body`

> The firmware of this computer has no Secure Boot keys. tunaOS can add its
> key and the Microsoft keys now. The computer restarts once, then the
> install continues. You type no password and you open no firmware menu.
> A countdown of 15 seconds shows first. Press a key there to cancel.

### `sb.handoff.setup-mode.accept`

> Add the keys and restart

### `sb.handoff.setup-mode.decline`

> Install without Secure Boot

### `sb.handoff.setup-mode.declined`

> tunaOS installs with Secure Boot off. To add the keys later, choose
> **Enroll Secure Boot keys: auto** in the boot menu. The disk then asks once for
> your recovery key.

## Recovery key page

### `sb.recovery.reason`

> Keep the recovery key. The disk asks for it when the Secure Boot keys of
> this computer change, for example after a firmware update.

## `tuna-secure-boot check`

The command prints its lines in English, for support. Frontends do not show them.
