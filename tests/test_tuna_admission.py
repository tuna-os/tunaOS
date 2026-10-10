"""Tuna Desktop (formerly Roost) admission must preserve signed sourcing and an installed-session gate."""
import hashlib
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_tuna_is_one_arch_cell_without_iso_expansion():
    config = yaml.safe_load((ROOT / ".github/build-config.yml").read_text())
    variant = next(v for v in config["variants"] if v["id"] == "marlin")
    flavor = next(f for f in variant["flavors"] if f["id"] == "tuna")
    assert flavor["stage"] == 2
    assert flavor["platforms"] == ["linux/amd64"]
    assert not flavor["build_iso"]
    assert not flavor["build_qcow2"]
    manifest = yaml.safe_load((ROOT / "manifests/desktops/tuna.yaml").read_text())
    assert "tunaos/tuna-desktop" in manifest["packages"]["pacman"]
    assert manifest["display_manager"] == "greetd"
    assert "greetd-gtkgreet.sh" in manifest["post_install"]


def test_tuna_package_signatures_cannot_be_silently_disabled():
    key = (ROOT / "experiences/tuna/tideforge-public.gpg").read_bytes()
    assert hashlib.sha256(key).hexdigest() == "4de5dfede473d4d56d79719a23e7b0925336719adfc142ea638735118039a82e"
    containerfile = (ROOT / "Containerfile.arch").read_text()
    context = containerfile.split("FROM scratch AS context\n", 1)[1].split("FROM ", 1)[0]
    assert "COPY experiences /experiences" in context, "public key is missing from the mounted build context"
    stage = containerfile.split("FROM base-no-de AS tuna\n", 1)[1].split("FROM ", 1)[0]
    assert "SigLevel = Required DatabaseOptional" in stage
    assert "pacman-key --lsign-key 4E5CC9F8B3B521793D95266E629BE6EA45188366" in stage
    assert "install-desktop.sh tuna" in stage
    assert "RUN bootc container lint" in stage


def test_tuna_contract_is_a_known_desktop_with_session_and_pam_requirements():
    script = (ROOT / "build_scripts/checks/verify-desktop-experience.sh").read_text()
    case = script.split("\ntuna)\n", 1)[1].split("\n\t;;", 1)[0]
    for requirement in ("Exec=tuna-session", "/etc/pam.d/tuna-lock", "tuna-shell-gtk", "tuna-session.target", "require_unit greetd", "tuna-portals.conf"):
        assert requirement in case


def test_tuna_is_a_selectable_greetd_session():
    environments = ROOT / "experiences/tuna/files/etc/greetd/environments"
    assert environments.read_text().splitlines() == ["tuna-session"]


def test_installed_portal_contract_rejects_missing_or_ambiguous_consent_routing(tmp_path):
    import subprocess

    script = (ROOT / "build_scripts/checks/verify-desktop-experience.sh").read_text()
    function = script.split("require_portal_preference() {", 1)[1].split("\nrequire_unit()", 1)[0]
    command = "require_portal_preference() {" + function + "\nrequire_portal_preference \"$1\" org.freedesktop.impl.portal.Access gtk"
    shipped = (ROOT / "experiences/tuna/files/usr/share/xdg-desktop-portal/tuna-portals.conf").read_text()
    for content, accepted in (
        (shipped, True),
        (shipped.replace("org.freedesktop.impl.portal.Access=gtk;\n", ""), False),
        (shipped.replace("Access=gtk;", "Access=gnome;"), False),
        (shipped.replace("Access=gtk;", "Access=gtk;gnome;"), False),
        (shipped + "org.freedesktop.impl.portal.Access=gnome;\n", False),
        (shipped.replace("[preferred]", "[unrelated]"), False),
    ):
        config = tmp_path / "tuna-portals.conf"
        config.write_text(content)
        result = subprocess.run(["bash", "-c", command, "portal-contract", str(config)], capture_output=True)
        assert (result.returncode == 0) is accepted, result.stderr.decode()


def test_nothing_in_the_image_still_requires_the_roost_package():
    """tuna-desktop provides roost; installing or asserting `roost` by name would
    pull the retired package (or fail once it is gone) instead of the rename."""
    manifest = yaml.safe_load((ROOT / "manifests/desktops/tuna.yaml").read_text())
    assert not any(p.split("/")[-1] == "roost" for p in manifest["packages"]["pacman"])
    containerfile = (ROOT / "Containerfile.arch").read_text()
    assert "AS roost\n" not in containerfile
    assert "experiences/roost/" not in containerfile
    assert not (ROOT / "manifests/desktops/roost.yaml").exists()
    assert not (ROOT / "experiences/roost").exists()


def test_upgrades_from_the_roost_flavor_are_covered():
    """Users of the roost flavor retain session compatibility after an explicit switch."""
    script = (ROOT / "build_scripts/checks/verify-desktop-experience.sh").read_text()
    case = script.split("\ntuna)\n", 1)[1].split("\n\t;;", 1)[0]
    for requirement in ("/usr/share/wayland-sessions/roost.desktop", "NoDisplay=true", "/etc/pam.d/roost-lock", '/usr/bin/roost-$name', "grep -qx 'tuna-desktop'"):
        assert requirement in case
    # pacman -Q resolves provides, so the old name must be compared exactly.
    assert "pacman -Q roost" not in case and "pacman -Qq roost" not in case
    config = yaml.safe_load((ROOT / ".github/build-config.yml").read_text())
    variant = next(v for v in config["variants"] if v["id"] == "marlin")
    flavor = next(f for f in variant["flavors"] if f["id"] == "tuna")
    assert not flavor.get("tag_aliases")
    assert not any(f["id"] == "roost" for f in variant["flavors"])


def test_retired_roost_tags_cannot_be_promoted_by_the_rename():
    for name in ("build-variant.yml", "reusable-build-image.yml"):
        workflow = (ROOT / ".github/workflows" / name).read_text()
        assert "tag-aliases" not in workflow
        assert "tag_aliases" not in workflow
        assert "TAG_ALIASES" not in workflow


def test_retired_flavor_has_an_explicit_switch_and_recovery_procedure():
    guide = (ROOT / "experiences/tuna/README.md").read_text()
    assert "stop publishing" in guide
    assert "sudo bootc switch --enforce-container-sigpolicy ghcr.io/tuna-os/marlin:tuna" in guide
    assert "sudo bootc status" in guide
    assert "sudo bootc rollback" in guide
    assert "/var/home" in guide
    assert "must still prove" in guide
