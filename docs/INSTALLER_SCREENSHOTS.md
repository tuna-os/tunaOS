# TunaOS Installer Walkthrough

TunaOS features an intuitive GUI installer built to make deploying bootc-based operating systems to bare-metal or virtual machines as straightforward as possible.

Below are step-by-step visual guides of the installation flow for both the standard GNOME/XFCE variant and the Cosmic Desktop variant.

> These images are captured automatically: the
> [Installer Walkthrough Screenshots](../.github/workflows/installer-screenshots.yml)
> workflow boots a freshly built live ISO in QEMU every Monday, drives the
> installer with `scripts/run-walkthrough.sh`, and commits the screendumps
> here. If a screenshot looks stale or wrong, dispatch that workflow (or run
> the script locally against any built ISO) to refresh them.

## GNOME / XFCE Installer Flow

This carousel walks through the steps of installing the standard TunaOS desktop:

````carousel
### 1. Welcome Screen
The installer welcomes the user and prompts them to begin the setup.
![01_welcome](images/installer/01_welcome.png)
<!-- slide -->
### 2. Disk Selection
Select the target disk drive where TunaOS will be installed.
![02_disk_select](images/installer/02_disk_select.png)
<!-- slide -->
### 3. Installation Confirmation
Confirm the installation settings and disk target before formatting begins.
![03_confirm](images/installer/03_confirm.png)
<!-- slide -->
### 4. Setup Initiated
The installer begins preparing the partitions and file system.
![04_installing](images/installer/04_installing.png)
<!-- slide -->
### 5. Installing Packages
System files and bootc chunks are copied to the disk.
![05_installing_progress](images/installer/05_installing_progress.png)
<!-- slide -->
### 6. Installation Complete
The installation has finished successfully. Reboot to start using TunaOS!
![06_done](images/installer/06_done.png)
````

---

## Cosmic Desktop Installer Flow

This carousel shows the installation flow customized for the Cosmic desktop:

````carousel
### 1. Welcome Screen
The Cosmic-themed welcome screen.
![cosmic_01_welcome](images/installer/cosmic_01_welcome.png)
<!-- slide -->
### 2. Disk Selection
Select the destination drive in the Cosmic installer.
![cosmic_02_disk_select](images/installer/cosmic_02_disk_select.png)
<!-- slide -->
### 3. Installation Confirmation
Review partition layout and confirm deployment.
![cosmic_03_confirm](images/installer/cosmic_03_confirm.png)
<!-- slide -->
### 4. Setup Initiated
Cosmic installer prepares the block devices.
![cosmic_04_installing](images/installer/cosmic_04_installing.png)
<!-- slide -->
### 5. Deployment Progress
Writing the Cosmic system image and bootloader configuration.
![cosmic_05_installing_progress](images/installer/cosmic_05_installing_progress.png)
<!-- slide -->
### 6. Finished
Installation completes successfully. Ready for the first boot!
![cosmic_06_done](images/installer/cosmic_06_done.png)
````
