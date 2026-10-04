"""Roost admission must preserve signed sourcing and an installed-session gate."""
import hashlib
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_roost_is_one_arch_cell_without_iso_expansion():
    config = yaml.safe_load((ROOT / ".github/build-config.yml").read_text())
    variant = next(v for v in config["variants"] if v["id"] == "marlin")
    flavor = next(f for f in variant["flavors"] if f["id"] == "roost")
    assert flavor["stage"] == 2
    assert flavor["platforms"] == ["linux/amd64"]
    assert not flavor["build_iso"]
    assert not flavor["build_qcow2"]
    manifest = yaml.safe_load((ROOT / "manifests/desktops/roost.yaml").read_text())
    assert "tunaos/roost" in manifest["packages"]["pacman"]
    assert manifest["display_manager"] == "greetd"
    assert "greetd-gtkgreet.sh" in manifest["post_install"]


def test_roost_package_signatures_cannot_be_silently_disabled():
    key = (ROOT / "experiences/roost/tideforge-public.gpg").read_bytes()
    assert hashlib.sha256(key).hexdigest() == "4de5dfede473d4d56d79719a23e7b0925336719adfc142ea638735118039a82e"
    containerfile = (ROOT / "Containerfile.arch").read_text()
    context = containerfile.split("FROM scratch AS context\n", 1)[1].split("FROM ", 1)[0]
    assert "COPY experiences /experiences" in context, "public key is missing from the mounted build context"
    stage = containerfile.split("FROM base-no-de AS roost\n", 1)[1].split("FROM ", 1)[0]
    assert "SigLevel = Required DatabaseOptional" in stage
    assert "pacman-key --lsign-key 4E5CC9F8B3B521793D95266E629BE6EA45188366" in stage
    assert "install-desktop.sh roost" in stage
    assert "RUN bootc container lint" in stage


def test_roost_contract_is_a_known_desktop_with_session_and_pam_requirements():
    script = (ROOT / "build_scripts/checks/verify-desktop-experience.sh").read_text()
    case = script.split("\nroost)\n", 1)[1].split("\n\t;;", 1)[0]
    for requirement in ("Exec=roost-session", "/etc/pam.d/roost-lock", "roost-shell-gtk", "require_unit greetd", "roost-portals.conf"):
        assert requirement in case
