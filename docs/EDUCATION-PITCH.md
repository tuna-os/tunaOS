# TunaOS for Computer Science Teaching Labs

**Audience:** university IT teams, lab managers, and systems instructors

**Supports:** [#1367](https://github.com/tuna-os/tunaOS/issues/1367), the
TunaOS production and evaluation adopter program

## The lab problem

Teaching machines drift during a term. Students install packages, change
system configuration, and leave behind broken state; the next class inherits
an inconsistent environment. Re-imaging between sections is disruptive, and
maintaining separate images for workstation hardware multiplies the work.

TunaOS addresses the system-image part of that problem with an immutable,
bootc-based desktop. Updates are delivered as image versions, and a failed
update can be rolled back to the previous deployment. User data remains a
separate policy decision: a lab can preserve home directories, reset them at
session boundaries, or use temporary student accounts.

## A low-risk pilot

The first evaluation should change no physical disks. Use a published ISO in
QEMU/KVM on one existing lab workstation:

```bash
wget https://download.tunaos.org/live-isos/yellowfin-gnome-latest.iso
./scripts/iso-e2e.sh ./yellowfin-gnome-latest.iso \
  --output ./pilot-e2e --timeout 300
```

The same harness used by CI checks boot readiness, desktop startup, critical
failures, screenshots, and serial logs. The machine can be discarded after
the pilot. Requirements and troubleshooting are documented in
[`docs/TESTING.md`](TESTING.md).

For a department that wants to test its own image, the supported fork workflow
is:

```bash
just build yellowfin gnome
just qcow2 yellowfin gnome
just verify-disk ./yellowfin.qcow2
```

The exact variant and desktop can be changed after the first pilot. A custom
package set can start with the repository's `custom/` overlay:

```bash
just build-custom
just run-custom-vm
```

See [`docs/ROLL_YOUR_OWN.md`](ROLL_YOUR_OWN.md) for the overlay files, image
registry workflow, and the deeper fork-and-customize path.

## Sample CS lab image

Start from a published desktop and add only the tools required by the course.
For example, `custom/packages.yaml` can contain:

```yaml
dnf:
  - gcc
  - gcc-c++
  - gdb
  - clang
  - lldb
  - python3-pip
  - python3-numpy
  - valgrind
  - strace
```

Build the overlay in CI and publish it to the department's OCI registry. Lab
machines can then update from the approved image on a schedule, while the
department retains its existing account, network, and classroom-management
policies.

## Three candidate pilot profiles

These are qualification profiles for a warm introduction, not claims that a
specific institution already uses TunaOS:

1. **Fedora-based introductory programming lab.** A course already using
   Fedora workstations is the shortest technical path to a Bonito or custom
   Fedora-based pilot. Measure setup time, package parity, and reset time
   between two lab sections.
2. **AlmaLinux systems-administration or operating-systems lab.** A lab that
   values an enterprise Linux base can trial Yellowfin or Albacore. Measure
   rollback time after deliberately applying a bad image update.
3. **Mixed-GPU computer-graphics or AI lab.** A lab with NVIDIA and
   non-NVIDIA machines can start with one stock desktop and one NVIDIA flavor.
   Measure whether the image matrix reduces manual driver and re-image work.

The maintainer should offer the brief through existing Fedora, AlmaLinux, and
university Linux communities, asking each candidate for a small pilot rather
than a fleet commitment. A successful pilot should record the variant, image
customizations, hardware, class size, and operational results.

## Adoption handoff

1. Open an issue or discussion tagged `education-pilot` with the lab profile
   and the desired pilot window.
2. Agree on one image, one VM or workstation, and success criteria before
   changing the wider fleet.
3. Publish the results, including limitations and rollback experience.
4. With the institution's permission, add it to the **Development &
   Evaluation** or **Production Users** section of [`ADOPTERS.md`](../ADOPTERS.md).

This gives #1367 verifiable adoption evidence without inventing an adopter or
promising support that has not yet been agreed.
