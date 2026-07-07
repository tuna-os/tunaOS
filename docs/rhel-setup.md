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

All desktops are supported — redfin uses the same EL10 code path as yellowfin/albacore/skipjack:

```bash
# Individual flavors
just build redfin base
just build redfin gnome
just build redfin kde
just build redfin niri
just build redfin cosmic
just build redfin xfce

# All flavors
just build redfin all

# HWE/nvidia layers
just build redfin gnome-hwe
just build redfin gnome-nvidia
just build redfin kde-nvidia
```

The RHSM credentials are passed securely via BuildKit secrets (never baked into image history). Set them before building:

```bash
export RHSM_USER="your-rh-username"
export RHSM_PASSWORD="your-rh-password"
# Or use activation key:
export RHSM_ORG="your-org-id"
export RHSM_ACTIVATION_KEY="your-key"
```

## Deploying

### Option 1: Generate an ISO (recommended for first install)

```bash
# Build + ISO in one command (dev=1 enables SSH for VM testing)
export RHSM_USER="..." RHSM_PASSWORD="..."
just iso redfin gnome local "" 1

# Or step by step:
just build redfin gnome
sudo ./scripts/build-iso-tacklebox.sh redfin gnome local

# Output: ./redfin-gnome-10-x86_64.iso
```

The ISO uses tacklebox (same as all other TunaOS variants) — UEFI live boot with systemd-boot + dmsquash-live. Boot it, run the installer, done.

### Option 2: bootc switch (from an existing RHEL system)

```bash
# Switch a running RHEL 10 system to any redfin flavor
sudo bootc switch localhost/redfin:gnome
sudo bootc switch localhost/redfin:kde
sudo bootc switch localhost/redfin:niri
sudo bootc switch localhost/redfin:cosmic
```

### Option 3: Direct disk install (VMs)

```bash
# Generate a QCOW2 for QEMU/KVM
just qcow2 redfin gnome local
```

## Testing in Corral VMs

```bash
# Build with SSH enabled
just build redfin gnome "" "0" "latest" "" "1"

# Create a corral VM from the local image
corral bootc create redfin-gnome \
  --image localhost/redfin:gnome \
  --cpu 4 --mem 8G --node karnataka

# Start and SSH in
corral start redfin-gnome
corral ssh redfin-gnome -u root -c "systemctl is-active gdm"

# Clean up
corral delete redfin-gnome --force
```

## Auto-Update (Local Image Factory)

For ongoing updates without internet access to GHCR (since images can't be published), set up a local auto-rebuild:

```bash
# 1. Build updated image periodically (cron or systemd timer)
just build redfin gnome

# 2. Push to local registry (optional — for multi-machine deployments)
podman push localhost/redfin:gnome registry.internal.example.com/redfin:gnome

# 3. Running systems pull updates
sudo bootc switch registry.internal.example.com/redfin:gnome
# After first switch, updates happen automatically via uupd timer
```

See [renner0e/server](https://github.com/renner0e/server) for a systemd timer pattern that automates this.

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
