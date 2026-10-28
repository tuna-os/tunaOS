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
 * This program dynamically loads the guest's libEGL.so.1 and needs no EGL
 * development headers or guest image changes. Build on a Linux host with a C
 * compiler and libc development files:
 *
 *   cc -O0 -g -Wall -Wextra -Werror repro-egldevice-swrast.c \
 *      -o repro-egldevice-swrast -ldl
 *
 * Run inside the affected AlmaLinux guest, under QEMU `-vga virtio` without
 * virgl, as root and with GDM stopped so the reproducer can own the DRM master:
 *
 *   systemctl stop gdm.service
 *   ./repro-egldevice-swrast /dev/dri/card1
 *   env LIBGL_ALWAYS_SOFTWARE=1 ./repro-egldevice-swrast /dev/dri/card1
 *   env MESA_LOADER_DRIVER_OVERRIDE=swrast ./repro-egldevice-swrast /dev/dri/card1
 *   env LIBGL_ALWAYS_SOFTWARE=1 MESA_LOADER_DRIVER_OVERRIDE=swrast \
 *      ./repro-egldevice-swrast /dev/dri/card1
 *   systemctl start gdm.service
 *
 * `card1` was the recorded QEMU virtio_gpu node in the original failing guest
 * (simpledrm was card0). Inspect /sys/class/drm/cardN/device/driver and use the
 * exact virtio_gpu primary node reported in the tested guest. Preserve each
 * process exit status, stdout/stderr, image digest, package versions, QEMU and
 * runner details. A passing EGL init is not a GNOME session; the normal
 * visible GDM, Wayland login, lock and unlock gate remains required.
 */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <unistd.h>

typedef int EGLint;
typedef unsigned int EGLBoolean;
typedef unsigned int EGLenum;
typedef void *EGLDisplay;
typedef void *EGLDeviceEXT;
typedef void *(*EGLGetProcAddress)(const char *name);
typedef EGLBoolean (*EGLQueryDevicesEXT)(EGLint max_devices,
                                         EGLDeviceEXT *devices,
                                         EGLint *num_devices);
typedef const char *(*EGLQueryDeviceStringEXT)(EGLDeviceEXT device,
                                                EGLint name);
typedef EGLDisplay (*EGLGetPlatformDisplayEXT)(EGLenum platform,
                                                void *native_display,
                                                const EGLint *attributes);
typedef EGLBoolean (*EGLInitialize)(EGLDisplay display,
                                    EGLint *major,
                                    EGLint *minor);
typedef EGLBoolean (*EGLTerminate)(EGLDisplay display);
typedef const char *(*EGLQueryString)(EGLDisplay display, EGLint name);
typedef EGLint (*EGLGetError)(void);

#define EGL_NONE 0x3038
#define EGL_VENDOR 0x3053
#define EGL_EXTENSIONS 0x3055
#define EGL_PLATFORM_DEVICE_EXT 0x313f
#define EGL_DRM_DEVICE_FILE_EXT 0x3233
#define EGL_DRM_MASTER_FD_EXT 0x333c
#define EGL_NO_DISPLAY NULL
#define EGL_NO_DEVICE_EXT NULL
#define DRM_IOCTL_SET_MASTER _IO('d', 0x1e)
#define DRM_IOCTL_DROP_MASTER _IO('d', 0x1f)

static void *load_symbol(void *handle, const char *name)
{
    dlerror();
    void *symbol = dlsym(handle, name);
    const char *error = dlerror();
    if (error || !symbol) {
        fprintf(stderr, "missing EGL symbol %s: %s\n", name,
                error ? error : "not found");
        exit(2);
    }
    return symbol;
}

static void *load_proc(EGLGetProcAddress get_proc, const char *name)
{
    void *symbol = get_proc(name);
    if (!symbol) {
        fprintf(stderr, "missing EGL entry point: %s\n", name);
        exit(2);
    }
    return symbol;
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
           requested, software ? software : "<unset>",
           override ? override : "<unset>");
    fflush(stdout);

    void *handle = dlopen("libEGL.so.1", RTLD_NOW | RTLD_LOCAL);
    if (!handle) {
        fprintf(stderr, "cannot load guest libEGL.so.1: %s\n", dlerror());
        return 2;
    }
    EGLGetProcAddress get_proc = (EGLGetProcAddress)
        load_symbol(handle, "eglGetProcAddress");
    EGLQueryDevicesEXT query_devices = (EGLQueryDevicesEXT)
        load_proc(get_proc, "eglQueryDevicesEXT");
    EGLQueryDeviceStringEXT query_device_string = (EGLQueryDeviceStringEXT)
        load_proc(get_proc, "eglQueryDeviceStringEXT");
    EGLGetPlatformDisplayEXT get_platform_display = (EGLGetPlatformDisplayEXT)
        load_proc(get_proc, "eglGetPlatformDisplayEXT");
    EGLInitialize egl_initialize = (EGLInitialize)
        load_symbol(handle, "eglInitialize");
    EGLTerminate egl_terminate = (EGLTerminate)
        load_symbol(handle, "eglTerminate");
    EGLQueryString egl_query_string = (EGLQueryString)
        load_symbol(handle, "eglQueryString");
    EGLGetError egl_get_error = (EGLGetError)
        load_symbol(handle, "eglGetError");

    EGLint count = 0;
    if (!query_devices(0, NULL, &count) || count <= 0) {
        fprintf(stderr, "eglQueryDevicesEXT found no devices (EGL error 0x%04x)\n",
                egl_get_error());
        dlclose(handle);
        return 3;
    }
    EGLDeviceEXT *devices = calloc((size_t) count, sizeof(*devices));
    if (!devices) {
        perror("calloc");
        dlclose(handle);
        return 2;
    }
    if (!query_devices(count, devices, &count)) {
        fprintf(stderr, "eglQueryDevicesEXT failed (EGL error 0x%04x)\n",
                egl_get_error());
        free(devices);
        dlclose(handle);
        return 3;
    }

    EGLDeviceEXT selected = EGL_NO_DEVICE_EXT;
    for (EGLint i = 0; i < count; i++) {
        const char *device_path =
            query_device_string(devices[i], EGL_DRM_DEVICE_FILE_EXT);
        const char *extensions = query_device_string(devices[i], EGL_EXTENSIONS);
        printf("egl_device[%d]=%s extensions=%s\n", i,
               device_path ? device_path : "<no-drm-device-file>",
               extensions ? extensions : "<none>");
        if (device_path && strcmp(device_path, requested) == 0) {
            selected = devices[i];
            break;
        }
    }
    /* Preserve device selection evidence even if eglInitialize crashes. */
    if (fflush(stdout) == EOF) {
        perror("fflush EGL device enumeration");
        free(devices);
        dlclose(handle);
        return 9;
    }
    free(devices);
    if (selected == EGL_NO_DEVICE_EXT) {
        fprintf(stderr, "no EGLDeviceEXT matches requested KMS device %s\n",
                requested);
        dlclose(handle);
        return 4;
    }

    int fd = open(requested, O_RDWR | O_CLOEXEC);
    if (fd < 0) {
        perror("open DRM device");
        dlclose(handle);
        return 5;
    }
    if (ioctl(fd, DRM_IOCTL_SET_MASTER, 0) != 0) {
        perror("DRM_IOCTL_SET_MASTER");
        close(fd);
        dlclose(handle);
        return 6;
    }

    const EGLint attributes[] = { EGL_DRM_MASTER_FD_EXT, fd, EGL_NONE };
    EGLDisplay display = get_platform_display(EGL_PLATFORM_DEVICE_EXT,
                                               selected,
                                               attributes);
    int result = 0;
    if (display == EGL_NO_DISPLAY) {
        fprintf(stderr,
                "eglGetPlatformDisplayEXT returned EGL_NO_DISPLAY (EGL error 0x%04x)\n",
                egl_get_error());
        result = 7;
        goto cleanup;
    }

    EGLint major = 0, minor = 0;
    if (!egl_initialize(display, &major, &minor)) {
        fprintf(stderr, "eglInitialize returned false (EGL error 0x%04x)\n",
                egl_get_error());
        result = 8;
        goto cleanup;
    }

    const char *vendor = egl_query_string(display, EGL_VENDOR);
    printf("eglInitialize=success version=%d.%d vendor=%s\n", major, minor,
           vendor ? vendor : "<none>");
    fflush(stdout);

cleanup:
    if (display != EGL_NO_DISPLAY)
        egl_terminate(display);
    ioctl(fd, DRM_IOCTL_DROP_MASTER, 0);
    close(fd);
    dlclose(handle);
    return result;
}
