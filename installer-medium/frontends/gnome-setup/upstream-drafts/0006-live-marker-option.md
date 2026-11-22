# Draft MR: build: Make the live-medium marker path configurable

Submit `patches/0006-*.patch` to https://gitlab.gnome.org/Teams/STF/setup.
Do NOT post from an agent account; a human submits this file's content.
Replace the placeholder author (`installer@tunaos.invalid`) with your
own identity first (`git commit --amend --author` after `git am`).

## Title

build: Make the live-medium marker path configurable

## Description

The user unit gates on `ConditionPathExists=/run/gnomeos/is-live`,
and the polkit rule probes the same path. A distribution that already
marks its live medium elsewhere cannot use either file without
patching. This adds a `live-marker-path` meson option (default
`/run/gnomeos/is-live`) and substitutes it into both files. The rules
file moves from `install_data` to `configure_file` for the
substitution. Default builds behave exactly as before.

## Checklist

- Patch applies on the pinned commit in `PIN` after 0001-0005.
- `meson setup` with defaults emits the current paths; with
  `-Dlive-marker-path=/run/tunaos/live` it emits the new path in the
  unit and the rule (verified); rule output passes `node --check`.
