# Hacker News "Show HN" Launch Playbook & Response Strategy

> Status: **draft** — maintainer review before post.  
> Issue: [#1759](https://github.com/tuna-os/tunaOS/issues/1759).  
> Prepared: 2026-08-30. Fact-checked against `PRESSKIT.md`, `ROADMAP.md`, and
> `VARIANT-LIFECYCLE.md` per [#1667](https://github.com/tuna-os/tunaOS/issues/1667).

---

## 1. Objectives & Hacker News Dynamics

Hacker News is a primary discovery channel for systems engineering and Linux tooling. A successful post on Show HN brings traffic, stars, and user feedback.

**HN Cultural Rules for Success:**
- **Extreme Honesty:** Readers on Hacker News do not like promotional hype or artificial voting. Concrete details and honest discussion of limits earn respect.
- **Single Maintainer Voice:** Submissions and replies must come from one maintainer account. No sockpuppets or organized vote rings.

---

## 2. Launch Timing & Readiness Gates

### Recommended Timing Windows
| Option | Day & Time | Rationale |
|---|---|---|
| **Primary (Recommended)** | Tuesday or Wednesday, 08:00–09:00 US/Eastern (12:00–13:00 UTC) | Captures East Coast US morning readers and European afternoon peak traffic. |
| **Secondary** | Thursday, 08:00–09:00 US/Eastern | Reliable fallback window before weekend traffic drop-off. |

> [!WARNING]
> **Launch Readiness Gates (Gating Criteria per #1759):**  
> Do not submit the Show HN post until maintainers verify all three gates:
> 1. **Image Matrix Health:** Flagship images (Albacore and Yellowfin) pass CI with verified boot reports.
> 2. **Website:** https://tunaos.org is up and download links work.
> 3. **Documentation:** The `README.md` file explains the status of each variant.

---

## 3. Submission Draft

### Post Title
```text
Show HN: TunaOS – Atomic, container-native bootc desktops on Enterprise Linux
```

### URL
https://tunaos.org (or https://github.com/tuna-os/tunaOS)

### Author's First Comment (Submit immediately upon posting)

```text
Hi HN,

I'm the creator/maintainer of TunaOS (https://github.com/tuna-os/tunaOS).

TunaOS is an open-source family of container-native, image-based (bootc) Linux desktops designed to bring modern desktop environments to Enterprise Linux lifecycles.

Why did we build this?
Linux enterprise distributions (AlmaLinux, RHEL, CentOS Stream) offer decade-long stability and reliability, but workstation users often face stale desktop environments or complex manual package compilation. Meanwhile, traditional rolling distributions are fast but vulnerable to partial upgrade breakage.

TunaOS solves this by packaging the entire operating system as a bootable OCI container image:
1. Atomic Updates & Instant Rollback: System updates execute as a single atomic image switch via bootc upgrade. If an update ever causes an issue, bootc rollback instantly restores the exact previous deployment at boot.
2. Flagship Enterprise Variants: 
   - Albacore: AlmaLinux 10 / RHEL 10 base with modern GNOME, KDE Plasma, COSMIC, and Niri desktop environments.
   - Yellowfin: AlmaLinux Kitten 10 base tracking upstream package streams.
3. Keyless Supply Chain Security: Every image layer is signed using Sigstore/cosign keyless signatures with verifiable Rekor transparency log entries and embedded SBOMs.
4. Multi-Distro Matrix: Beyond EL10, we build experimental and beta images for Fedora (Bonito), Arch/CachyOS (Marlin), and Ubuntu LTS (Gurnard).

Honest Current Status
- GA / Stable: Albacore & Yellowfin GNOME on x86_64.
- Beta / Preview: KDE Plasma, COSMIC, Niri flavors, and Marlin (Arch/CachyOS).
- Experimental: ARM Snapdragon X Elite builds and Apple Silicon installer previews.

We're a small community project and would love your technical feedback, architectural critiques, and testing reports. Happy to answer any questions in the thread!
```

---

## 4. Anticipated Questions & Pre-Drafted Answers

- **Q: "How does this compare to Universal Blue / Bluefin or Fedora Silverblue?"**  
  *A:* "TunaOS originated as a fork of Bluefin. It shares the same container-native philosophy. However, we support Enterprise Linux and provide a multi-base build system."

- **Q: "How do application installations work if `/usr` is read-only?"**  
  *A:* "Desktop applications run in Flatpak for isolation. Developer workflows use container toolboxes like `distrobox` or `toolbox`. For system packages, client container layers or `bootc usroverlay` tests are available."

- **Q: "What is the security model?"**  
  *A:* "We avoid private keys with Sigstore and OIDC in GitHub Actions. Every published image contains an SBOM. The client verifies signatures against Rekor before deployment."

---

## 5. First-24-Hour Engagement Protocol

1. **Maintain Continuous Presence:** The maintainer should actively monitor and reply to comments during the first 6–8 hours of submission.
2. **Technical Transparency:** Respond directly with links to Containerfiles, CI workflows, or issue discussions when asked about technical specifics.
3. **Post-Mortem & Metrics:** After the thread concludes, capture traffic spikes, star deltas, and community issues in `docs/ADOPTION-OUTREACH-STATUS.md` and monthly adoption reports.
