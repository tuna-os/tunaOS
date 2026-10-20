"""Tuna Desktop (formerly Roost) admission must preserve signed sourcing and an installed-session gate."""
import hashlib
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[1]


def rollout():
    return yaml.safe_load((ROOT / ".github/build-config.yml").read_text())


def test_every_variant_has_an_explicit_tuna_rollout_record():
    """ADR 0008: each variant ships a tuna flavor or is published as unsupported
    with a recorded reason. Neither may be a silent omission."""
    config = rollout()
    records = config["tuna_rollout"]
    assert set(records) == {v["id"] for v in config["variants"]}
    for variant in config["variants"]:
        record = records[variant["id"]]
        has_cell = any(f["id"] == "tuna" for f in variant["flavors"])
        assert record["package_target"]
        if record["status"] == "admitted":
            assert has_cell, f"{variant['id']} is admitted but has no tuna flavor"
        else:
            assert record["status"] == "unsupported"
            assert record["reason"].startswith(f"unsupported until package target {record['package_target']} ")
            assert not has_cell, f"{variant['id']} is unsupported but still builds a tuna flavor"


def test_tuna_cells_are_amd64_images_without_iso_expansion():
    config = rollout()
    admitted = [v for v in config["variants"] if config["tuna_rollout"][v["id"]]["status"] == "admitted"]
    assert {v["id"] for v in admitted} == {"marlin", "yellowfin", "albacore", "skipjack", "wahoo", "bonito", "bonito-rawhide", "grouper", "flounder", "flounder-sid", "sailfin"}
    for variant in admitted:
        flavor = next(f for f in variant["flavors"] if f["id"] == "tuna")
        assert flavor["stage"] == 2
        assert flavor["platforms"] == ["linux/amd64"]
        assert not flavor["build_iso"]
        assert not flavor["build_qcow2"]
        assert flavor["luks_e2e"] is False
    manifest = yaml.safe_load((ROOT / "manifests/desktops/tuna.yaml").read_text())
    assert "tunaos/tuna-desktop=1.0.0beta.1-1" in manifest["packages"]["pacman"]
    assert "accountsservice" in manifest["packages"]["pacman"]
    assert "glib2" in manifest["packages"]["pacman"]
    assert "orca" in manifest["packages"]["pacman"], "the Screen Reader key needs distribution Orca"
    assert manifest["display_manager"] == "gdm"
    assert "tuna-gdm.sh" in manifest["post_install"]


def test_tuna_runs_gdm_across_shared_and_arch_manifests():
    """tunaOS#3438: every Tuna flavor uses the stock GDM login path."""
    arch = yaml.safe_load((ROOT / "manifests/desktops/tuna-arch.yaml").read_text())
    assert arch["display_manager"] == "gdm"
    packages = arch["packages"]["pacman"]
    assert "tunaos/tuna-desktop=1.0.0beta.1-1" in packages, "the beta pin moves with the manifest"
    assert "orca" in packages, "the Screen Reader key needs distribution Orca"
    assert "gdm" in packages
    for absent in ("greetd", "greetd-gtkgreet", "gtkgreet", "cage"):
        assert absent not in packages, f"{absent} would race GDM for the login screen"
    for script in arch["post_install"]:
        assert "greetd" not in script, f"{script} wires the display manager Marlin just left"
    shared = yaml.safe_load((ROOT / "manifests/desktops/tuna.yaml").read_text())
    assert shared["display_manager"] == "gdm"
    assert "tuna-gdm.sh" in shared["post_install"]
    assert not {"greetd", "greetd-gtkgreet", "gtkgreet", "cage"} & set(shared["packages"]["pacman"])


def test_tuna_contract_expects_gdm_on_every_tuna_cell():
    """The desktop contract must match the GDM migration on every Tuna cell."""
    script = (ROOT / "build_scripts/checks/verify-desktop-experience.sh").read_text()
    case = script.split("\ntuna)\n", 1)[1].split("\n\t;;", 1)[0]
    assert "dm_pattern='^(gdm|gdm3)\\.service$'" in case
    assert "require_any_unit gdm gdm3" in case

def test_rpm_cells_install_the_pinned_beta_from_signed_factory_repositories():
    manifest = yaml.safe_load((ROOT / "manifests/desktops/tuna.yaml").read_text())
    for target, nevr in (("el10", "tuna-desktop-1.0.0~beta.1-1.el10"), ("fedora", "tuna-desktop-1.0.0~beta.1-1.fc44"), ("rawhide", "tuna-desktop-1.0.0~beta.1-1.fc46"), ("eln", "tuna-desktop-1.0.0~beta.1-1.eln159")):
        section = manifest["packages"][target]
        assert section["display_manager"] == "gdm"
        assert nevr in section["packages"]
        for package in ("gdm", "accountsservice", "glib2-devel", "xdg-desktop-portal-gnome", "xdg-desktop-portal-gtk", "gnome-keyring"):
            assert package in section["packages"], (target, package)
        # tuned-ppd, as each base's GNOME flavor ships, conflicts with
        # power-profiles-daemon (the yellowfin/skipjack package-set dry-run).
        assert "power-profiles-daemon" not in section["packages"], target
        # beta.1 imports the session environment with
        # dbus-update-activation-environment (tuna-os/tuna-desktop#691).
        assert "dbus-tools" in section["packages"], target
        for repo in section["repos"]:
            assert repo["baseurl"].startswith("https://repo.tunaos.org/")
            assert not repo.get("unsigned"), "factory packages must keep gpgcheck"
            # Behind the distro repositories: the factory tiers only fill gaps.
            assert repo["priority"] > 99
    assert "tuned-ppd" in manifest["packages"]["fedora"]["packages"]
    assert "tuned-ppd" in manifest["packages"]["rawhide"]["packages"]
    assert "tuned-ppd" in manifest["packages"]["eln"]["packages"]
    installer = (ROOT / "build_scripts/desktop/install-desktop.sh").read_text()
    assert '_TD_OS="rawhide"' in installer, "a Rawhide base must read the rawhide section"
    base_packages = (ROOT / "build_scripts/10-base-packages.sh").read_text()
    el10_base = base_packages.split("\nelse\n", 1)[1]
    assert "\t\ttuned-ppd \\\n" in el10_base, "the EL10 base must keep supplying tuned-ppd"
    # ELN receives GDM from its base repositories; the Tuna manifest no longer
    # carries the separate greetd/gtkgreet/cage stack.
    assert manifest["packages"]["eln"]["repos"] == [{"name": "tunaos-eln", "baseurl": "https://repo.tunaos.org/rpm/eln/x86_64/", "priority": 100}]
    containerfile = (ROOT / "Containerfile.el10").read_text()
    context = containerfile.split("FROM scratch as context\n", 1)[1].split("FROM ", 1)[0]
    assert "COPY experiences/tuna /experiences/tuna" in context
    stage = containerfile.split("FROM base-no-de AS tuna\n", 1)[1]
    assert "install-desktop.sh tuna" in stage


def test_apt_cells_install_the_pinned_beta_from_the_signed_tideforge_index_for_their_base():
    manifest = yaml.safe_load((ROOT / "manifests/desktops/tuna.yaml").read_text())
    section = manifest["packages"]["apt"]
    assert "tuna-desktop=1.0.0~beta.1-1" in section["packages"]
    assert section["display_manager"] == "gdm3"
    for package in ("gdm3", "accountsservice", "libglib2.0-bin", "libglib2.0-dev-bin", "xdg-desktop-portal-gnome", "xdg-desktop-portal-gtk", "gnome-keyring", "orca", "power-profiles-daemon"):
        assert package in section["packages"], package
    repos = {repo["condition"]: repo for repo in section["repos"]}
    assert set(repos) == {"ubuntu", "debian-sid", "debian-trixie"}
    # trixie's tuna-desktop carries a private gtk4-layer-shell; Debian's 1.0
    # library must not be installed beside it.
    assert not any(p.startswith("libgtk4-layer-shell") for p in section["packages"])
    for index in ("ubuntu", "debian-sid", "debian-trixie"):
        repo = repos[index]
        assert repo["uri"] == f"https://repo.tunaos.org/tideforge/{index}/"
        # signed-by: apt refuses the index unless the keyring signs it.
        assert repo["keyring_url"] == f"https://repo.tunaos.org/tideforge/{index}/tideforge.gpg"
    installer = (ROOT / "build_scripts/desktop/install-desktop.sh").read_text()
    assert "deb [signed-by=${_TD_AR_KEYRING_PATH}]" in installer
    assert "debian-sid) [[" in installer
    assert "debian-trixie) [[" in installer
    gdm_hook = (ROOT / "build_scripts/desktop/tuna-gdm.sh").read_text()
    assert "gdm3.service" in gdm_hook
    assert "display-manager.service" in gdm_hook
    for name in ("Containerfile.ubuntu", "Containerfile.debian"):
        containerfile = (ROOT / name).read_text()
        context = containerfile.split("FROM scratch AS context\n", 1)[1].split("FROM ", 1)[0]
        assert "COPY experiences/tuna /experiences/tuna" in context, name
        stage = containerfile.split("FROM base-no-de AS tuna\n", 1)[1]
        assert "install-desktop.sh tuna" in stage, name


def test_zypper_cell_installs_the_pinned_beta_from_the_signed_factory_index():
    manifest = yaml.safe_load((ROOT / "manifests/desktops/tuna.yaml").read_text())
    section = manifest["packages"]["zypper"]
    assert section["display_manager"] == "gdm"
    assert "tuna-desktop-1.0.0~beta.1-1" in section["packages"]
    # dbus-update-activation-environment (tuna-os/tuna-desktop#691) and
    # Tumbleweed's emoji font name.
    for package in ("dbus-1-tools", "google-noto-coloremoji-fonts", "gdm", "accountsservice", "glib2-tools", "xdg-desktop-portal-gnome", "xdg-desktop-portal-gtk", "gnome-keyring", "orca", "power-profiles-daemon"):
        assert package in section["packages"], package
    (repo,) = section["repos"]
    assert repo["baseurl"] == "https://repo.tunaos.org/rpm/opensuse-tumbleweed/x86_64/"
    # No priority: Tumbleweed's newer GDM must win over the factory's.
    assert "priority" not in repo
    installer = (ROOT / "build_scripts/desktop/install-desktop.sh").read_text()
    assert ".packages.zypper.repos[$i].baseurl" in installer
    assert 'echo "pkg_gpgcheck=1"' in installer
    containerfile = (ROOT / "Containerfile.opensuse").read_text()
    context = containerfile.split("FROM scratch AS context\n", 1)[1].split("FROM ", 1)[0]
    assert "COPY experiences/tuna /experiences/tuna" in context
    assert "\nFROM desktop AS tuna\n" in containerfile


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
    for requirement in ("Exec=tuna-session", "/etc/pam.d/tuna-lock", "tuna-shell-gtk", "tuna-session.target", "require_any_unit gdm gdm3", "tuna-portals.conf", "require_command orca", "Session", "tuna.desktop", "/etc/accountsservice/user-templates/standard", "/etc/accountsservice/user-templates/administrator", "AutomaticLoginEnable"):
        assert requirement in case


def test_tuna_gdm_configuration_selects_wayland_session_without_autologin():
    """GDM selects the Tuna Wayland session and never enables autologin."""
    manifest = yaml.safe_load((ROOT / "manifests/desktops/tuna.yaml").read_text())
    assert manifest["display_manager"] == "gdm"
    assert manifest["packages"]["apt"]["display_manager"] == "gdm3"
    for target in ("pacman", "el10", "fedora", "eln", "rawhide", "apt", "zypper"):
        packages = manifest["packages"][target]
        expected = "gdm3" if target == "apt" else "gdm"
        package_list = packages if target == "pacman" else packages["packages"]
        assert expected in package_list
        assert not {"greetd", "gtkgreet", "greetd-gtkgreet", "cage"} & set(package_list)

    for name in ("etc/gdm/custom.conf", "etc/gdm3/custom.conf", "etc/gdm3/daemon.conf"):
        config = (ROOT / "experiences/tuna/files" / name).read_text()
        assert "WaylandEnable=true" in config
        assert "DefaultSession" not in config
        assert "AutomaticLoginEnable=false" in config

    for template_name in ("standard", "administrator"):
        template = (ROOT / "experiences/tuna/files/etc/accountsservice/user-templates" / template_name).read_text()
        assert "[User]" in template
        assert "Session=tuna\n" in template
        assert "Session=tuna.desktop" not in template
    contract = (ROOT / "build_scripts/checks/verify-desktop-experience.sh").read_text()
    assert "IS_UBUNTU" in contract
    assert "IS_DEBIAN" in contract
    assert "tuna_gdm_config=/etc/gdm3/custom.conf" in contract
    assert "tuna_gdm_config=/etc/gdm3/daemon.conf" in contract

    css = (ROOT / "experiences/tuna/files/usr/share/gnome-shell/theme/tuna-gdm.css").read_text()
    assert "TunaOS GDM theme overrides" in css
    assert "tunaos-default.jpg" in css
    assert not (ROOT / "experiences/tuna/files/etc/greetd/environments").exists()
    assert not (ROOT / "experiences/tuna/files/usr/bin/Tuna").exists()
    hook = (ROOT / "build_scripts/desktop/tuna-gdm.sh").read_text()
    assert "ln -sfn /dev/null /etc/systemd/system/greetd.service" in hook
    assert "glib-compile-resources" in hook

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


def test_dpkg_installed_names_keep_held_packages_and_drop_removed_ones(tmp_path):
    import subprocess

    script = (ROOT / "build_scripts/checks/verify-desktop-experience.sh").read_text()
    function = script.split("tuna_installed_package_names() {", 1)[1].split("\ntuna_installed_file_owner()", 1)[0]
    fake = tmp_path / "dpkg-query"
    fake.write_text(
        "#!/bin/sh\n"
        "printf 'ii  tuna-desktop\\nhi  power-profiles-daemon\\nrc  roost\\nun  absent\\n'\n"
    )
    fake.chmod(0o755)
    command = "tuna_installed_package_names() {" + function + "\ntuna_installed_package_names dpkg"
    result = subprocess.run(
        ["bash", "-c", command], capture_output=True, text=True,
        env={"PATH": f"{tmp_path}:/usr/bin:/bin"},
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["tuna-desktop", "power-profiles-daemon"]



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
    assert 'require_glob "$compat_link"' in case
    assert 'if compgen -G "$compat_link" >/dev/null' in case
    assert 'readlink -- "$compat_link"' in case
    assert 'cannot read compatibility link' in case
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
