/*
 * Minimal EGLDevice reproducer for tunaOS#3969.
 *
 * Mimics Mutter 49.4 src/backends/native/meta-render-device-egl-stream.c:
 *   1. enumerate EGLDeviceEXT handles;
 *   2. select the handle whose EGL_DRM_DEVICE_FILE_EXT equals the KMS node;
 *   3. open that same primary DRM node as master;
 *   4. call eglGetPlatformDisplayEXT(EGL_PLATFORM_DEVICE_EXT, device,
 *      { EGL_DRM_MASTER_FD_EXT, fd, EGL_NONE });
 *   5. call eglInitialize.
 *
 * Run inside the affected AlmaLinux guest, under QEMU `-vga virtio` without
 * virgl, as root and with GDM stopped so the reproducer can own the DRM master:
 *
 * Install gcc, mesa-libEGL-devel, libdrm-devel, and pkgconf-pkg-config in the
 * ephemeral test guest before this experiment; do not modify the TunaOS image.
 *   cc -O0 -g -Wall -Wextra -Werror repro-egldevice-swrast.c \
 *      -o repro-egldevice-swrast $(pkg-config --cflags --libs egl)
 *   systemctl stop gdm.service
 *   ./repro-egldevice-swrast /dev/dri/card1
 *   env LIBGL_ALWAYS_SOFTWARE=1 ./repro-egldevice-swrast /dev/dri/card1
 *   env MESA_LOADER_DRIVER_OVERRIDE=swrast ./repro-egldevice-swrast /dev/dri/card1
 *   env LIBGL_ALWAYS_SOFTWARE=1 MESA_LOADER_DRIVER_OVERRIDE=swrast \
 *      ./repro-egldevice-swrast /dev/dri/card1
 *   systemctl start gdm.service
 *
 * `card1` is the recorded QEMU virtio_gpu node in the failing run (simpledrm
 * was card0); inspect /sys/class/drm/card<N>/device/driver and use the exact
 * node reported in the failed guest rather than assuming this name elsewhere.
 * Preserve exit status 139/signature and logs. A pass here is not a GNOME
 * session; the normal login/lock/unlock gate remains independently required.
 */
#define _GNU_SOURCE
#include <EGL/egl.h>
#include <EGL/eglext.h>
#include <fcntl.h>
#include <libdrm/drm.h>
#include <sys/ioctl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>


static void *proc(const char *name)
{
    void *value = (void *) eglGetProcAddress(name);
    if (!value) {
        fprintf(stderr, "missing EGL entry point: %s\n", name);
        exit(2);
    }
    return value;
}

int main(int argc, char **argv)
{
    if (argc != 2) {
        fprintf(stderr, "usage: %s /dev/dri/cardN\n", argv[0]);
        return 2;
    }

    const char *requested = argv[1];
    const char *software = getenv("LIBGL_ALWAYS_SOFTWARE");
    const char *override = getenv("MESA_LOADER_DRIVER_OVERRIDE");
    printf("requested_drm_device=%s LIBGL_ALWAYS_SOFTWARE=%s MESA_LOADER_DRIVER_OVERRIDE=%s\n",
           requested, software ? software : "<unset>", override ? override : "<unset>");
    fflush(stdout);

    PFNEGLQUERYDEVICESEXTPROC query_devices = (PFNEGLQUERYDEVICESEXTPROC)
        proc("eglQueryDevicesEXT");
    PFNEGLQUERYDEVICESTRINGEXTPROC query_device_string = (PFNEGLQUERYDEVICESTRINGEXTPROC)
        proc("eglQueryDeviceStringEXT");
    PFNEGLGETPLATFORMDISPLAYEXTPROC get_platform_display = (PFNEGLGETPLATFORMDISPLAYEXTPROC)
        proc("eglGetPlatformDisplayEXT");

    EGLint count = 0;
    if (!query_devices(0, NULL, &count) || count <= 0) {
        fprintf(stderr, "eglQueryDevicesEXT found no devices (EGL error 0x%04x)\n",
                eglGetError());
        return 3;
    }
    EGLDeviceEXT *devices = calloc((size_t) count, sizeof(*devices));
    if (!devices) {
        perror("calloc");
        return 2;
    }
    if (!query_devices(count, devices, &count)) {
        fprintf(stderr, "eglQueryDevicesEXT failed (EGL error 0x%04x)\n", eglGetError());
        free(devices);
        return 3;
    }

    EGLDeviceEXT selected = EGL_NO_DEVICE_EXT;
    for (EGLint i = 0; i < count; i++) {
        const char *device_path = query_device_string(devices[i], EGL_DRM_DEVICE_FILE_EXT);
        const char *extensions = query_device_string(devices[i], EGL_EXTENSIONS);
        printf("egl_device[%d]=%s extensions=%s\n", i,
               device_path ? device_path : "<no-drm-device-file>",
               extensions ? extensions : "<none>");
        if (device_path && strcmp(device_path, requested) == 0)
            selected = devices[i];
    }
    free(devices);
    if (selected == EGL_NO_DEVICE_EXT) {
        fprintf(stderr, "no EGLDeviceEXT matches requested KMS device %s\n", requested);
        return 4;
    }

    int fd = open(requested, O_RDWR | O_CLOEXEC);
    if (fd < 0) {
        perror("open DRM device");
        return 5;
    }
    if (ioctl(fd, DRM_IOCTL_SET_MASTER, 0) != 0) {
        perror("DRM_IOCTL_SET_MASTER");
        close(fd);
        return 6;
    }

    const EGLint attributes[] = { EGL_DRM_MASTER_FD_EXT, fd, EGL_NONE };
    EGLDisplay display = get_platform_display(EGL_PLATFORM_DEVICE_EXT,
                                               (void *) selected,
                                               attributes);
    int result = 0;
    if (display == EGL_NO_DISPLAY) {
        fprintf(stderr, "eglGetPlatformDisplayEXT returned EGL_NO_DISPLAY (EGL error 0x%04x)\n",
                eglGetError());
        result = 7;
        goto cleanup;
    }

    EGLint major = 0, minor = 0;
    if (!eglInitialize(display, &major, &minor)) {
        fprintf(stderr, "eglInitialize returned false (EGL error 0x%04x)\n", eglGetError());
        result = 8;
        goto cleanup;
    }

    printf("eglInitialize=success version=%d.%d vendor=%s\n", major, minor,
           eglQueryString(display, EGL_VENDOR) ? eglQueryString(display, EGL_VENDOR) : "<none>");
    fflush(stdout);

cleanup:
    if (display != EGL_NO_DISPLAY)
        eglTerminate(display);
    ioctl(fd, DRM_IOCTL_DROP_MASTER, 0);
    close(fd);
    return result;
}
