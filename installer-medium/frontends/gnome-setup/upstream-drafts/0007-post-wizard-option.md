# Draft MR: build: Make the post-wizard command configurable

Submit `patches/0007-*.patch` to https://gitlab.gnome.org/Teams/STF/setup.
Do NOT post from an agent account; a human submits this file's content.
Replace the placeholder author (`installer@tunaos.invalid`) with your
own identity first (`git commit --amend --author` after `git am`).

## Title

build: Make the post-wizard command configurable

## Description

The user unit always starts `gnome-initial-setup` after the wizard
exits. A distribution that ships a different next step (or none)
must change the unit before it can reuse it. This adds a
`post-wizard-command` meson option (default `gnome-initial-setup`,
resolved relative to libexecdir; an absolute path is used as-is; an
empty value drops the second `ExecStart`). Default builds behave
exactly as before.

## Checklist

- Patch applies on the pinned commit in `PIN` after 0001-0006.
- `meson setup` with defaults emits both `ExecStart` lines; with
  `-Dpost-wizard-command=` the second line is gone (verified).
