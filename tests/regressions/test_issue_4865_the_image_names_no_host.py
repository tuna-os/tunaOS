"""tunaOS#4865: the image ships no /etc/hostname, so DEFAULT_HOSTNAME names the host.

The published grouper image shipped /etc/hostname containing
"localhost.localdomain". docker.io/library/ubuntu:resolute, grouper's base,
ships that file, and no build step removed it. systemd uses DEFAULT_HOSTNAME
only while /etc/hostname is absent or empty, so grouper booted as
localhost.localdomain and the Gate's runtime branding check failed `hostname`
(grouper:gnome, run 44926166422).

A RUN step cannot see that file: the builder bind-mounts its own
/etc/hostname over it, and `rm` fails with EBUSY (podman 4.9.3 and
buildah 1.33.7, the CI runner's versions). build-image-inner.sh now builds
with --no-hostname, 90-image-info.sh removes the file, and
verify-image-hostname.sh reads the finished image with `podman cp`.
tests/bats/test_image_hostname.bats covers that check and its wiring.

Falsification: behavioural. Delete the `rm -f /etc/hostname` in
90-image-info.sh and the first test fails with the base's file still there.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests"))
from test_anime_finalization import Image  # noqa: E402


def test_90_image_info_removes_the_base_images_hostname(tmp_path):
    image = Image(tmp_path, "grouper")
    hostname = image.root / "etc/hostname"
    hostname.write_text("localhost.localdomain\n")
    image.info()
    assert not hostname.exists()
    assert 'DEFAULT_HOSTNAME="grouper"' in (image.root / "usr/lib/os-release").read_text()


def test_90_image_info_runs_without_a_hostname_file(tmp_path):
    image = Image(tmp_path, "grouper")
    image.info()
    assert not (image.root / "etc/hostname").exists()
