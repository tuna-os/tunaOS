/* SPDX-License-Identifier: MIT */
/* Emulator-only PID1: no block-device access, shell, network or installer. */
#include <fcntl.h>
#include <stdio.h>
#include <string.h>
#include <sys/mount.h>
#include <sys/reboot.h>
#include <sys/utsname.h>
#include <unistd.h>

int main(void) {
    char cmdline[4096] = {0};
    struct utsname identity;
    int ok = mount("proc", "/proc", "proc", MS_NOSUID | MS_NODEV | MS_NOEXEC, NULL) == 0;
    int fd = open("/proc/cmdline", O_RDONLY);
    ssize_t n = fd < 0 ? -1 : read(fd, cmdline, sizeof(cmdline) - 1);
    if (fd >= 0) close(fd);
    ok = ok && n > 0 && uname(&identity) == 0;
    cmdline[strcspn(cmdline, "\n")] = 0;
    printf("X13S_FIXTURE_CMDLINE=%s\n", cmdline);
    if (ok) printf("X13S_FIXTURE_UNAME=%s\n", identity.release);
    ok = ok && strcmp(identity.release, "7.2.11-200.fc44.aarch64") == 0;
    /* Spaces bound the nonce, avoiding a substring match to another argument. */
    char bounded[4100];
    snprintf(bounded, sizeof(bounded), " %s ", cmdline);
    ok = ok && strstr(bounded, " x13s.fixture=external-initrd-v1 ") != NULL;
    if (mount("sysfs", "/sys", "sysfs", MS_RDONLY | MS_NOSUID | MS_NODEV | MS_NOEXEC, NULL) == 0) {
        char compatible[256] = {0};
        fd = open("/sys/firmware/devicetree/base/compatible", O_RDONLY);
        ssize_t length = fd < 0 ? -1 : read(fd, compatible, sizeof(compatible) - 1);
        if (fd >= 0) close(fd);
        if (length > 0) {
            for (ssize_t i = 0; i < length - 1; i++) if (!compatible[i]) compatible[i] = ',';
            printf("X13S_FIXTURE_DTB=%s\n", compatible);
        } else printf("X13S_FIXTURE_DTB=unobserved\n");
    }
    printf("X13S_FIXTURE_%s\n", ok ? "PASS" : "FAIL");
    fflush(stdout);
    sync();
    reboot(RB_POWER_OFF);
    for (;;) pause();
}
