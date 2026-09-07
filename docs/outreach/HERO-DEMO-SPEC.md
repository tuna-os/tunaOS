# README & Landing Page Hero Demo Technical Specification

> Status: **draft** — for maintainer review and asset capture.  
> Tracking issue: [#1760](https://github.com/tuna-os/tunaOS/issues/1760).  
> Supports: [#1333](https://github.com/tuna-os/tunaOS/issues/1333) (DistroWatch),
> [#1346](https://github.com/tuna-os/tunaOS/issues/1346) (Reddit/Lemmy),
> [#1534](https://github.com/tuna-os/tunaOS/issues/1534) (Tech Press),
> [#1759](https://github.com/tuna-os/tunaOS/issues/1759) (Show HN).  
> Fact-checked 2026-08-30 per [#1667](https://github.com/tuna-os/tunaOS/issues/1667).

---

## 1. Objective & Value Proposition

First-time visitors to the GitHub repository (`README.md`) and the project website (`tunaos.org`) currently encounter text descriptions and build matrices without immediate visual proof of the user experience.

A concise, high-polish **25–30 second boot-to-desktop demo** (available as a lightweight animated WebP/GIF and an embedded high-definition MP4/WebM video) serves as the top-of-funnel conversion asset for onboarding new users, contributors, and media reviewers.

---

## 2. Capture Environment & Parameters

| Parameter | Specification |
|---|---|
| **Target Variant** | **Albacore GNOME** (`ghcr.io/tuna-os/albacore:gnome`) on AlmaLinux 10 |
| **Virtualization Platform** | QEMU/KVM with VirtIO-GPU acceleration (per `docs/tunaos/evaluating-in-a-vm.md`) |
| **Capture Resolution** | 1920×1080 (1080p source), downscaled to 1280×720 (720p) for distribution |
| **Framerate** | 30 fps (video source), 15 fps (optimized GIF/WebP) |
| **Duration Limit** | 25 to 30 seconds maximum |
| **Asset Budgets** | **GIF/WebP:** < 500 KB (optimized preview) <br> **MP4 / WebM:** < 3.0 MB (H.264 / VP9 / AV1) |

---

## 3. Storyboard & Scene Breakdown

```mermaid
sequenceDiagram
    autonumber
    participant Boot as 00-05s: UEFI & Splash
    participant Login as 05-12s: GDM & Session
    participant Term as 12-20s: CLI & bootc
    participant Rollback as 20-28s: Upgrade & Rollback
    participant Logo as 28-30s: Outro

    Boot->>Login: Smooth graphical transition
    Login->>Term: Terminal window pops up
    Term->>Rollback: Displays bootc status & instant rollback
    Rollback->>Logo: Clean fade to TunaOS logo
```

### Timeline & Actions:
- **0:00 – 0:05 | System Boot:** Fast UEFI boot sequence displaying the TunaOS Plymouth boot splash.
- **0:05 – 0:12 | Desktop Launch:** Seamless auto-login to GNOME 51 / clean modern desktop wallpaper and top bar.
- **0:12 – 0:20 | Terminal & Diagnostics:** Opening a terminal to execute:
  ```bash
  fastfetch
  bootc status
  ```
  *(Highlights the active container image hash, keyless Sigstore signature status, and AlmaLinux 10 base).*
- **0:20 – 0:28 | Atomic Operations:** Short command showcase:
  ```bash
  sudo bootc upgrade
  sudo bootc rollback
  ```
  *(Demonstrates zero-risk updates and single-transaction rollback safety).*
- **0:28 – 0:30 | Title Card Fade:** Short fade with TunaOS emblem and URL: `https://tunaos.org`.

---

## 4. Generation Pipeline & Optimization Tooling

### Step 1: Capture Raw Video via QEMU / `wf-recorder`
```bash
# Launch VM and record display via PipeWire/Wayland recorder:
wf-recorder -g "0,0 1920x1080" -f /tmp/raw-boot-demo.mp4
```

### Step 2: Transcode to Web-Optimized MP4 / WebM
```bash
ffmpeg -i /tmp/raw-boot-demo.mp4 \
  -vf "scale=1280:-1:flags=lanczos" \
  -c:v libx264 -crf 22 -preset slow -an \
  -movflags +faststart docs/images/hero-demo.mp4
```

### Step 3: Generate Ultra-Lightweight Animated GIF / WebP (< 500 KB)
```bash
# Generate high-efficiency color palette:
ffmpeg -y -i docs/images/hero-demo.mp4 -vf "fps=12,scale=800:-1:flags=lanczos,palettegen=stats_mode=diff" /tmp/palette.png

# Encode gif with palette:
ffmpeg -i docs/images/hero-demo.mp4 -i /tmp/palette.png -lavfi "fps=12,scale=800:-1:flags=lanczos [x]; [x][1:v] paletteuse=dither=bayer:bayer_scale=3" /tmp/hero-demo.gif

# Optimize via gifsicle:
gifsicle -O3 --lossy=80 -o docs/images/hero-demo.gif /tmp/hero-demo.gif
```

---

## 5. Deployment & Integration Locations

1. **README.md Hero Section:** Insert immediately beneath the main project badge row:
   ```markdown
   [![TunaOS Boot & Desktop Demo](docs/images/hero-demo.gif)](https://tunaos.org)
   ```
2. **Landing Page (`tunaos.org`):** Embed responsive HTML5 video with autoplay, loop, muted attributes.
3. **Gallery Index:** Register the asset in `docs/SCREENSHOTS.md` under a new `## Hero Demos & Video Previews` section.
4. **Media Kits:** Reference the MP4 asset in `docs/PRESSKIT.md` and `docs/YOUTUBER-REVIEW-KIT.md`.
