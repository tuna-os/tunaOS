# Draft MR: main: Don't force demo mode and the debug overrides

Submit `patches/0001-*.patch` to https://gitlab.gnome.org/Teams/STF/setup.
Do NOT post from an agent account; a human submits this file's content.

## Title

main: Don't force demo mode and the debug overrides

## Description

`main()` sets `SETUP_DEMO` and the `SETUP_OVERRIDE_*` variables
unconditionally, so any build from a clean checkout ignores the real
session class and os-release type and never talks to
systemd-sysinstall or systemd-cryptenroll. Development builds can set
the same variables in the environment (`SETUP_DEMO=true gnome-setup`).

This keeps the debug path and makes release builds work.

## Checklist

- Patch applies on the pinned commit in `PIN`.
- `meson setup` passes with no new option.
