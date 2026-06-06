# Building the Redfin (RHEL 10) Variant

**Redfin** is TunaOS built on Red Hat Enterprise Linux 10. Because the RHEL EULA prohibits redistribution of derived images, this variant is **local-build only** — images are not published to the public ghcr.io registry.

## Prerequisites

### 1. Red Hat Account

You need a Red Hat account with an active subscription. The free **Red Hat Developer Subscription** (up to 16 systems for personal use) works perfectly:

- Sign up at <https://developers.redhat.com/register>
- After registration, activate the Developer Subscription at <https://access.redhat.com/management>

### 2. Authenticate to registry.redhat.io

The RHEL 10 bootc base image is hosted on `registry.redhat.io` and requires authentication before building:

```bash
# For rootless builds
podman login registry.redhat.io

# For root builds (required for ISO/VM generation)
sudo podman login registry.redhat.io
```

Enter your Red Hat Customer Portal username and password, or use a **Registry Service Account token** (recommended for scripts/automation):

- Create a service account token at <https://access.redhat.com/terms-based-registry/>
- Use the token username/password in place of your portal credentials

### 3. Build Host Requirements

The build host must have network access to Red Hat's Content Delivery Network (CDN) to install packages during the build. This works automatically when:

- You are authenticated to `registry.redhat.io` (step 2 above)
- The `rhel-bootc` base image carries embedded entitlement certificates that grant CDN access during `podman build`

You do **not** need to run `subscription-manager register` on the build host itself.

## Building

```bash
# Build the base GNOME image
just redfin

# Build all flavors
just redfin base
just redfin gdx

# Or use the generic build command
just build redfin base
```

## Deploying

The built image is available locally as `localhost/redfin:latest`. To deploy:

```bash
# Switch a running RHEL system to the new image
sudo bootc switch localhost/redfin:latest

# Or generate an ISO for bare-metal installation
sudo just iso redfin base local
```

Each deployed system must be covered by a RHEL subscription (the same free Developer Subscription works).

## Why No Public Images?

The RHEL End User License Agreement (EULA) prohibits redistribution of RHEL-based binaries and images to the general public. This is fundamentally different from:

- **AlmaLinux** (yellowfin/albacore) — freely redistributable binary-compatible clone
- **CentOS Stream** (skipjack) — freely redistributable upstream RHEL contribution
- **Fedora** (bonito) — freely redistributable upstream

If you need a publicly distributable RHEL-compatible OS image, use **albacore** (AlmaLinux 10) or **yellowfin** (AlmaLinux Kitten 10) instead — they are binary-compatible with RHEL 10 and can be published freely.

## Subscription-Manager Notes

`subscription-manager` is kept installed in the redfin image (unlike skipjack where it is removed). This allows deployed systems to register with Red Hat for support and updates:

```bash
# On a deployed redfin system
sudo subscription-manager register --username <your-rh-username>
```
