# TunaOS for Computer Science & Teaching Labs

**Target Audience**: Computer Science Department IT Admins, Lab Managers, and Systems Instructors  
**Tracks**: [#1600](https://github.com/tuna-os/tunaOS/issues/1600) (Education & Teaching Lab Adoption Pitch)  
**Supports**: [#1367](https://github.com/tuna-os/tunaOS/issues/1367) (Production / Academic Adoption Program)

---

## 🎓 The Teaching Lab Challenge: State Drift & Maintenance Overhead

Computer science and engineering teaching labs face a persistent operational headache:

1. **State Drift & Machine Corruption**: Students modify system packages, break shell configurations, or leave residual artifacts, resulting in inconsistent lab environments across the term.
2. **Re-imaging Friction**: Traditional PXE/Ghost re-imaging is slow, network-heavy, and disruptive between back-to-back lab sections.
3. **Hardware & Driver Variance**: Managing separate images for workstations with NVIDIA GPUs, different display layouts, or virtualized environments creates image sprawl.

---

## 🚀 The Solution: Immutable bootc Container Desktops

TunaOS applies cloud-native, OCI-container patterns to desktop operating systems using Red Hat's `bootc` (bootable container) engine:

- **100% Stateless & Immutable**: System root `/usr` is read-only. Student home directories (`/var/home`) can be wiped or reset on reboot, guaranteeing a pristine environment for every class.
- **OCI Container Pipeline**: Lab images are built like standard Docker container images (using standard `Containerfile` / `Dockerfile` syntax) and hosted in standard container registries (GHCR / Quay).
- **Atomic Updates & Instant Rollbacks**: Updating a 30-station lab requires pulling container layers. If an update fails, rolling back to the previous known-good deployment takes one `bootc rollback` command.
- **Zero-Risk VM Pilots**: Instructors and lab admins can evaluate TunaOS inside QEMU/KVM or VirtualBox in 20 minutes without modifying physical disk partitions.

---

## 🛠️ 20-Minute Pilot Architecture for CS Labs

### Step 1: Evaluate in a Local VM
Deploy TunaOS in a VM using the standard Just recipe:
```bash
just vm-run bonito kde
```
Alternatively, test via QEMU/KVM:
```bash
qemu-system-x86_64 -m 4096 -smp 4 \
  -drive file=tunaos-bonito-kde.qcow2,format=qcow2 \
  -enable-kvm -cpu host -net nic -net user
```

### Step 2: Customize Your Department Image (`Containerfile.cs-lab`)
Extend any standard TunaOS variant (e.g. `Yellowfin` AlmaLinux 10 or `Bonito` Fedora 44) with department-specific compilers, IDEs, and tools:

```dockerfile
FROM ghcr.io/tuna-os/yellowfin:gnome

# Install CS curriculum tooling
RUN dnf install -y \
    gcc gcc-c++ gdb \
    clang lldb \
    python3-pip python3-numpy \
    valgrind strace \
    code \
    && dnf clean all

# Apply default lab shell & dconf presets
COPY cs-lab-dconf.ini /etc/dconf/db/distro.d/01-cs-lab
RUN dconf update
```

### Step 3: Deployment & Maintenance Model
- **Central Build**: Run your `Containerfile.cs-lab` through GitHub Actions or internal CI/CD to push to your university's internal OCI registry (`registry.cs.university.edu/lab/desktop:latest`).
- **Fleet Sync**: Lab workstations run `bootc update` via a nightly systemd timer, fetching delta layers seamlessly.

---

## 📈 Academic Pilot Program & Community Handoff

### Pilot Process
1. **Maintainer Consultation**: Lab admins open an issue or discussion tagged `education-pilot` on `tuna-os/tunaOS`.
2. **Custom Layer Assistance**: Core maintainers provide template Containerfiles and Ansible/just recipes tailored for academic software stacks.
3. **Adopter Recognition**: Participating academic institutions and CS labs are credited in `ADOPTERS.md` under the Academic & Production Users registry (#1367).

---

## 🔗 Related Resources
- [QEMU/KVM VM Evaluation Guide](../docs/IMPROVEMENT_PLAN.md)
- [Variant Selection Decision Guide](choosing-a-variant.md)
- [ADOPTERS.md Ecosystem & Production Registry](../ADOPTERS.md)
