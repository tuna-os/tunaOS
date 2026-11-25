# EL10 soft-reboot spike: status for #4909

Nothing here was run in a VM. The author had no KVM or QEMU. The "done when"
test (`albacore:gnome` reaches the installed GDM through a soft reboot in QEMU)
is still open. This note records what the repository now holds and what the
first QEMU run must answer.

## What exists

`hooks/el10-soft-reboot-probe <installed-root>` is a read-only probe. Run it
with the copy mounted. It exits 0 when a soft reboot looks viable and 10 when
the installer should fall back to a normal reboot (ADR 0018 allows that). It
checks:

- The copy ships `/usr/lib/modules/$(uname -r)`. Soft reboot keeps the kernel.
- `systemctl` knows `soft-reboot`.
- The copy has `/usr/lib/systemd/systemd`.

It also reports, without failing:

- Live-only kernel arguments (`utah.live`, `rd.live.*`, `root=live:`, `rd.luks*`).
  A soft reboot keeps the command line, so an initrd or userspace rule must
  ignore them. The probe says so with `cmdline_needs_ignore_rule=1`.
- `kernel.kexec_load_disabled`. kexec stays out of the plan.

`tests/test_el10_soft_reboot_probe.py` covers the probe's decisions with fake
inputs. It does not test a real soft reboot.

## Open questions for the first QEMU run

1. Does `ostree admin prepare-soft-reboot` accept a deployment that was never
   booted, on the copied sysroot? (Source reading says bootc's composefs path
   only handles the booted sysroot; the ostree path is unread.)
2. If not, is the fix a bootc change (alternate sysroot) or the installer's own
   caller of the initrd setup, then `systemctl soft-reboot`?
3. Live session state: autologin user, tmpfs `/home`, NetworkManager state.
   None carries over. The frontends must say so.
4. SELinux on EL10: relabel state and policy load across the soft reboot.
5. Does `/proc/cmdline` of the installed boot hold no live argument? Add that
   check to the e2e `reboot` stage (`scripts/installer-e2e/stages.py`,
   `EL10_REBOOT_TODO`).
6. Does the next cold boot come up clean, with no failed units?

## Decision rule

If question 1 or 5 has no workable answer, EL10 keeps a normal reboot and the
probe's exit 10 path is the installer's behaviour.
