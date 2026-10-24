"""PR #3736: verify-branding.sh expects the namespace the build resolved.

The build workflow preserves the resolved publish namespace through sudo, so a
zero-config fork's 90-image-info.sh stamps image-vendor with the fork owner.
The verifier ran under `set -e` in configure-desktop-runtime.sh and insisted on
'tuna-os', so every such fork desktop build failed. These tests run the real
90-image-info.sh and the real verifier against one redirected root.
"""
import json
from pathlib import Path
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from test_anime_finalization import Image, ROOT  # noqa: E402

VERIFIER = ROOT / "build_scripts/checks/verify-branding.sh"


def verify(image, **env):
    """Run the verifier with filesystem roots redirected into the image root."""
    source = VERIFIER.read_text()
    source = source.replace("/usr/", f"{image.root}/usr/").replace("/etc/", f"{image.root}/etc/")
    source = source.replace(f"#!{image.root}/usr/bin/env bash", "#!/usr/bin/env bash")
    script = Path(image.context) / "verify-branding.sh"
    script.write_text(source)
    script.chmod(0o755)
    run_env = {**image.env, "TUNAOS_OS_RELEASE": str(image.root / "usr/lib/os-release")}
    run_env.pop("IMAGE_VENDOR", None)
    run_env.update(env)
    result = subprocess.run(["bash", str(script), "yellowfin"], env=run_env,
                            capture_output=True, text=True)
    return result.stdout + result.stderr


def vendor_lines(output):
    prefixes = ("ok: image-vendor", "FAIL: image-vendor", "FAIL: persisted", "FAIL: no persisted")
    return [line.strip() for line in output.splitlines() if line.strip().startswith(prefixes)]


@pytest.mark.parametrize("vendor", ["tuna-os", "fork-owner"])
@pytest.mark.parametrize("at_build_time", [True, False])
def test_resolved_namespace_is_expected(tmp_path, vendor, at_build_time):
    image = Image(tmp_path)
    image.env["IMAGE_VENDOR"] = vendor
    image.info()
    env = {"IMAGE_VENDOR": vendor} if at_build_time else {}
    lines = vendor_lines(verify(image, **env))
    assert lines == [f"ok: image-vendor={vendor}"]


def test_vendor_that_differs_from_the_persisted_namespace_fails(tmp_path):
    image = Image(tmp_path)
    image.env["IMAGE_VENDOR"] = "fork-owner"
    image.info()
    info = image.root / "usr/share/ublue-os/image-info.json"
    data = json.loads(info.read_text())
    data["image-vendor"] = "tuna-os"
    info.write_text(json.dumps(data))
    assert vendor_lines(verify(image)) == ["FAIL: image-vendor is 'tuna-os', want 'fork-owner'"]


def test_build_vendor_that_disagrees_with_the_persisted_namespace_fails(tmp_path):
    image = Image(tmp_path)
    image.env["IMAGE_VENDOR"] = "fork-owner"
    image.info()
    lines = vendor_lines(verify(image, IMAGE_VENDOR="tuna-os"))
    assert lines == ["FAIL: persisted namespace 'fork-owner' disagrees with build IMAGE_VENDOR 'tuna-os'"]


def test_missing_persisted_namespace_fails(tmp_path):
    image = Image(tmp_path)
    image.info()
    (image.root / "usr/share/tunaos/image-vendor").unlink(missing_ok=True)
    (line,) = vendor_lines(verify(image))
    assert line.startswith("FAIL: no persisted publish namespace")
