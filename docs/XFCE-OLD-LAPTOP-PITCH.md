# Give an old laptop a second life with XFCE Linux

> **Draft for maintainer review** — outreach material for
> [#1682](https://github.com/tuna-os/tunaOS/issues/1682). This is a pitch for
> the separate [`tuna-os/xfce-linux`](https://github.com/tuna-os/xfce-linux)
> project, not a new TunaOS variant or a promise of universal old-hardware
> support.

## The angle

An aging laptop does not have to become e-waste just because its original
operating system is no longer pleasant to use. XFCE Linux is a lightweight,
immutable XFCE Wayland OCI image built with BuildStream. Its system image is
updated atomically with `bootc`, so a refurbisher or home user can test an
update and roll back if it is not usable.

The useful promise is modest: a clean, reproducible desktop image that is
worth evaluating on hardware that is still functional. It is not a claim
that every ten-year-old laptop will be fast, that every Wi-Fi adapter will
work, or that Linux support replaces a hardware repair.

## Safe evaluation path

1. **Back up the laptop first.** A refurbisher should record its model,
   firmware mode, CPU architecture, memory, storage health, Wi-Fi chipset,
   and display behavior. Do not overwrite a customer's disk for a marketing
   test.
2. **Start in a VM or on a spare disk.** Pull the published OCI image on an
   existing bootc-capable test system:

   ```bash
   podman pull ghcr.io/tuna-os/xfce-linux:latest
   ```

   The project README documents the corresponding `bootc switch` workflow;
   use a disposable test deployment and keep the current deployment available
   for rollback. For a physical refurbishing workflow, use the project's
   published live ISO and installation documentation rather than improvising
   partitioning commands.
3. **Test the actual work.** Check suspend/resume, Wi-Fi, audio, display
   brightness, browser/video playback, USB devices, and a clean reboot. Record
   what works and what does not; those results are more useful than a generic
   benchmark number.
4. **Only then install.** Confirm a backup, boot mode, and recovery path before
   installing on the laptop. Keep a known-good live USB available for the next
   owner.

## Who this is for

- **Community refurbishers and repair cafés:** a repeatable image to evaluate
  on donated x86_64 laptops before handing them to a new owner.
- **Schools and nonprofits:** a low-cost test path for a small pool of
  machines, with atomic updates reducing per-machine repair work.
- **Home users:** a way to try a clean desktop on a spare laptop without
  treating a successful VM boot as proof that every device driver will work.

## Honest current status

- XFCE Linux is a companion project in the TunaOS organization, not a
  canonical TunaOS variant.
- The project publishes an OCI image and a live ISO channel; consult its
  [README](https://github.com/tuna-os/xfce-linux) and
  [TunaOS documentation](https://tunaos.org/docs/xfce-linux) for the current
  release names and download locations.
- The practical first target is compatible amd64/x86_64 hardware. Do not
  advertise an ARM image or ISO unless the companion project documents and
  tests one.
- XFCE Wayland and individual laptop hardware are still evaluation concerns:
  GPU, firmware, Wi-Fi, suspend, and media support must be checked on the
  specific model.

## Maintainer-ready post

**Title:** Give an old laptop a second life with XFCE Linux

**Body:**

> Have an older x86_64 laptop that still works but is no longer enjoyable to
> use? We are building [XFCE Linux](https://github.com/tuna-os/xfce-linux), a
> lightweight immutable XFCE Wayland OCI image in the TunaOS ecosystem.
>
> It is designed for evaluation on low-resource systems: the desktop image is
> built reproducibly with BuildStream, updates use the atomic `bootc` model,
> and a failed deployment can be rolled back. Start with a VM, spare disk, or
> live ISO, then test the hardware that matters — Wi-Fi, suspend, audio,
> brightness, USB, and video playback — before installing.
>
> This is a companion project, not a claim that every old laptop is supported.
> The current practical target is compatible amd64/x86_64 hardware, and the
> project README is the source of truth for image and ISO availability:
> https://github.com/tuna-os/xfce-linux
>
> If you try it on a donated or spare laptop, please report the model, CPU,
> memory, GPU/Wi-Fi hardware, and both successes and failures. That evidence
> is more valuable than a benchmark screenshot and helps the project learn
> which machines can be kept in service.

## Posting checklist

- Have a maintainer post from a clearly identified human account; do not
  astroturf or use automated engagement.
- Read the current rules for `r/linux`, `r/linuxhardware`, and the selected
  Lemmy instance before posting.
- Prefer one focused post and a useful hardware-results thread over repeated
  promotion. Cross-post only where the topic is on-topic.
- Link to the companion project and its current docs, not to an invented
  TunaOS variant page.
- Ask permission before naming a refurbisher, school, or nonprofit in a case
  study; record confirmed results in `ADOPTERS.md` only after consent.
