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


def test_roost_is_a_selectable_greetd_session():
    environments = ROOT / "experiences/roost/files/etc/greetd/environments"
    assert environments.read_text().splitlines() == ["roost-session"]


def test_installed_portal_contract_rejects_missing_or_ambiguous_consent_routing(tmp_path):
    import subprocess

    script = (ROOT / "build_scripts/checks/verify-desktop-experience.sh").read_text()
    function = script.split("require_portal_preference() {", 1)[1].split("\nrequire_unit()", 1)[0]
    command = "require_portal_preference() {" + function + "\nrequire_portal_preference \"$1\" org.freedesktop.impl.portal.Access gtk"
    shipped = (ROOT / "experiences/roost/files/usr/share/xdg-desktop-portal/roost-portals.conf").read_text()
    for content, accepted in (
        (shipped, True),
        (shipped.replace("org.freedesktop.impl.portal.Access=gtk;\n", ""), False),
        (shipped.replace("Access=gtk;", "Access=gnome;"), False),
        (shipped.replace("Access=gtk;", "Access=gtk;gnome;"), False),
        (shipped + "org.freedesktop.impl.portal.Access=gnome;\n", False),
        (shipped.replace("[preferred]", "[unrelated]"), False),
    ):
        config = tmp_path / "roost-portals.conf"
        config.write_text(content)
        result = subprocess.run(["bash", "-c", command, "portal-contract", str(config)], capture_output=True)
        assert (result.returncode == 0) is accepted, result.stderr.decode()
