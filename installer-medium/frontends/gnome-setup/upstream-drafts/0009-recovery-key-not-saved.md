# Draft MR: recovery-key: Stay on the page when the key is not enrolled

Submit `patches/0009-*.patch` to https://gitlab.gnome.org/Teams/STF/setup.
Do NOT post from an agent account; a human submits this file's content.

## Title

<!-- ste-disable: upstream commit subject, must match the patch -->
recovery-key: Stay on the page when the key is not enrolled
<!-- ste-enable -->

## Description

When the enroll fails, `on_done()` only logs it and goes to the done
page. The person then believes that the key on screen unlocks the disk.
But no keyslot holds that key. With a TPM the disk still boots, so
nothing shows the problem until the day the person needs the key.

With this patch the page goes on only after a successful enroll.
Otherwise it stays and tells the person that the system did not
save the key. The person can try again. A second click on Done during an enroll does
nothing.

## Checklist

- Patch applies on the pinned commit in `PIN` after 0008.
- Full build on Fedora 43 with patches 0001-0009 (meson,
  blueprint-compiler 0.22.2).
- Not run against an enroll that fails, on a real medium.
