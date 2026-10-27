"""Keep EGLDevice enumeration visible when initialization crashes."""

import os
import shutil
import signal
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
REPRODUCER = ROOT / "scripts/repro-egldevice-swrast.c"
CC = shutil.which("cc")


@pytest.mark.skipif(CC is None, reason="C compiler is required for the reproducer")
def test_device_enumeration_is_flushed_before_egl_initialize_crashes(tmp_path):
    egl_shim = tmp_path / "egl-shim.c"
    egl_shim.write_text(
        r"""
#include <signal.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

typedef int EGLint;
typedef unsigned int EGLBoolean;
typedef unsigned int EGLenum;
typedef void *EGLDisplay;
typedef void *EGLDeviceEXT;
#define EGL_DRM_DEVICE_FILE_EXT 0x3233

static EGLBoolean query_devices(EGLint max_devices, EGLDeviceEXT *devices,
                                EGLint *num_devices)
{
    *num_devices = 1;
    if (max_devices > 0)
        devices[0] = (EGLDeviceEXT)(uintptr_t)1;
    return 1;
}

static const char *query_device_string(EGLDeviceEXT device, EGLint name)
{
    (void)device;
    if (name == EGL_DRM_DEVICE_FILE_EXT)
        return getenv("TUNAOS_FAKE_DRM_DEVICE");
    return "EGL_EXT_device_drm";
}

static EGLDisplay get_platform_display(EGLenum platform, void *native_display,
                                      const EGLint *attributes)
{
    (void)platform;
    (void)native_display;
    (void)attributes;
    return (EGLDisplay)(uintptr_t)1;
}

void *eglGetProcAddress(const char *name)
{
    if (strcmp(name, "eglQueryDevicesEXT") == 0)
        return (void *)query_devices;
    if (strcmp(name, "eglQueryDeviceStringEXT") == 0)
        return (void *)query_device_string;
    if (strcmp(name, "eglGetPlatformDisplayEXT") == 0)
        return (void *)get_platform_display;
    return NULL;
}

EGLBoolean eglInitialize(EGLDisplay display, EGLint *major, EGLint *minor)
{
    (void)display;
    (void)major;
    (void)minor;
    raise(SIGSEGV);
    return 0;
}

EGLBoolean eglTerminate(EGLDisplay display)
{
    (void)display;
    return 1;
}

const char *eglQueryString(EGLDisplay display, EGLint name)
{
    (void)display;
    (void)name;
    return "test EGL";
}

EGLint eglGetError(void)
{
    return 0;
}
"""
    )
    ioctl_shim = tmp_path / "ioctl-shim.c"
    ioctl_shim.write_text(
        "#include <stdarg.h>\n"
        "int ioctl(int fd, unsigned long request, ...) {\n"
        "  (void)fd; (void)request; return 0;\n"
        "}\n"
    )
    egl_library = tmp_path / "libEGL.so.1"
    ioctl_library = tmp_path / "libioctl-shim.so"
    binary = tmp_path / "repro-egldevice-swrast"
    subprocess.run(
        [CC, "-shared", "-fPIC", "-Wall", "-Wextra", "-Werror", str(egl_shim), "-o", str(egl_library)],
        check=True,
    )
    subprocess.run(
        [CC, "-shared", "-fPIC", "-Wall", "-Wextra", "-Werror", str(ioctl_shim), "-o", str(ioctl_library)],
        check=True,
    )
    subprocess.run(
        [CC, "-O0", "-g", "-Wall", "-Wextra", "-Werror", str(REPRODUCER), "-o", str(binary), "-ldl"],
        check=True,
    )

    env = os.environ.copy()
    env.update(
        LD_LIBRARY_PATH=str(tmp_path),
        LD_PRELOAD=str(ioctl_library),
        TUNAOS_FAKE_DRM_DEVICE="/dev/null",
    )
    result = subprocess.run(
        [str(binary), "/dev/null"], env=env, capture_output=True, text=True, check=False
    )
    assert result.returncode == -signal.SIGSEGV
    assert "egl_device[0]=/dev/null" in result.stdout
