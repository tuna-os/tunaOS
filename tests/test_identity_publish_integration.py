"""F1/F3a integration: one primary config controls destination and identity.

The real writer and verifier run on a redirected filesystem, not a built image.
No legacy fork manifest participates in this contract.
"""
import copy
import json
from pathlib import Path
import shutil
import sys

sys.path.insert(0, str(Path(__file__).parent))
from test_anime_finalization import Image  # noqa: E402
from test_identity_config import config  # noqa: E402
from test_publish_destination import resolve  # noqa: E402
from test_verify_branding_vendor import verify, vendor_lines  # noqa: E402


def test_primary_identity_and_publish_destination_share_the_consumer_path(tmp_path):
    fork = copy.deepcopy(config.load())
    fork["build"]["publish"] = {"registry": "quay.io", "namespace": "acme"}
    fork["project"] = {"name": "Acme OS", "id": "acmeos", "cpe_vendor": "acme"}
    fork["defaults"]["branding"] = {
        key: f"https://acme.example/{key}" for key in config.BRANDING_URLS
    }
    fork["variants"]["yellowfin"]["codename"] = "Wile E"
    config.validate(fork)
    adapter = tmp_path / "build-config.yml"
    adapter.write_text(config.render(fork), encoding="utf-8")
    registry, namespace = resolve(adapter).split()
    assert (registry, namespace) == ("quay.io", "acme")

    image = Image(tmp_path)
    (image.context / "build_scripts/lib/identity.env").write_text(
        config.render_identity(fork), encoding="utf-8")
    image.env.update(IMAGE_REGISTRY=registry, IMAGE_VENDOR=namespace)
    image.info()
    info = json.loads((image.root / "usr/share/ublue-os/image-info.json").read_text())
    assert info["image-vendor"] == "acme"
    assert info["image-ref"] == "ostree-image-signed:docker://quay.io/acme/yellowfin"
    release = (image.root / "usr/lib/os-release").read_text()
    assert 'VERSION_CODENAME="Wile E"' in release
    assert 'HOME_URL="https://acme.example/homepage"' in release
    assert not (image.context / "manifests/fork-config.json").exists()
    # configure-desktop-runtime.sh installs this adapter separately from the
    # final identity writer. Model that copy for the verifier's runtime path.
    shutil.copyfile(image.context / "build_scripts/lib/identity.env",
                    image.root / "usr/share/tunaos/identity-config.env")
    for env in ({}, {"IMAGE_VENDOR": namespace}):
        output = verify(image, **env)
        assert vendor_lines(output) == ["ok: image-vendor=acme"]
        assert "ok: HOME_URL=https://acme.example/homepage" in output
