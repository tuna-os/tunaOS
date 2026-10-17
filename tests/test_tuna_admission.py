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
    assert {v["id"] for v in admitted} == {"marlin", "yellowfin", "albacore", "skipjack", "wahoo", "bonito", "bonito-rawhide", "grouper", "flounder", "flounder-sid", "sailfin", "guppy"}
    for variant in admitted:
        flavor = next(f for f in variant["flavors"] if f["id"] == "tuna")
        assert flavor["stage"] == 2
        assert flavor["platforms"] == ["linux/amd64"]
        assert flavor.get("promotion_hold", False) is (variant["id"] == "guppy")
        assert not flavor["build_iso"]
        assert not flavor["build_qcow2"]
        assert flavor["luks_e2e"] is False
    manifest = yaml.safe_load((ROOT / "manifests/desktops/tuna.yaml").read_text())
    assert "tunaos/tuna-desktop=1.0.0beta.1-1" in manifest["packages"]["pacman"]
    assert "orca" in manifest["packages"]["pacman"], "the Screen Reader key needs distribution Orca"
    assert manifest["display_manager"] == "greetd"
    assert "greetd-gtkgreet.sh" in manifest["post_install"]


def test_guppy_tuna_promotion_hold_reaches_reusable_workflow():
    matrix_workflow = (ROOT / ".github/workflows/build-variant.yml").read_text()
    reusable_workflow = (ROOT / ".github/workflows/reusable-build-image.yml").read_text()
    assert "promotion_hold: (.promotion_hold // false)" in matrix_workflow
    assert "promotion_hold: .promotion_hold" in matrix_workflow
    assert "promote: ${{ !matrix.promotion_hold }}" in matrix_workflow
    assert "inputs.promote" in reusable_workflow


def test_rpm_cells_install_the_pinned_beta_from_signed_factory_repositories():
    manifest = yaml.safe_load((ROOT / "manifests/desktops/tuna.yaml").read_text())
    for target, nevr in (("el10", "tuna-desktop-1.0.0~beta.1-1.el10"), ("fedora", "tuna-desktop-1.0.0~beta.1-1.fc44"), ("rawhide", "tuna-desktop-1.0.0~beta.1-1.fc46"), ("eln", "tuna-desktop-1.0.0~beta.1-1.eln159")):
        section = manifest["packages"][target]
        assert section["display_manager"] == "greetd"
        assert nevr in section["packages"]
        for package in ("greetd", "gtkgreet", "cage", "xdg-desktop-portal-gnome", "xdg-desktop-portal-gtk", "gnome-keyring"):
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
    # ELN ships no gtkgreet; the eln factory index fills it (tunaos-packages#874).
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
    for package in ("greetd", "gtkgreet", "cage", "xdg-desktop-portal-gnome", "xdg-desktop-portal-gtk", "gnome-keyring", "orca", "power-profiles-daemon"):
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
    greeter = (ROOT / "build_scripts/desktop/greetd-gtkgreet.sh").read_text()
    assert "greetd greeter _greetd" in greeter, "Debian and Ubuntu name the greeter account _greetd"
    assert "Conflicts=getty@tty1.service" in greeter, "Debian's greetd.service is written for vt 7"
    for name in ("Containerfile.ubuntu", "Containerfile.debian"):
        containerfile = (ROOT / name).read_text()
        context = containerfile.split("FROM scratch AS context\n", 1)[1].split("FROM ", 1)[0]
        assert "COPY experiences/tuna /experiences/tuna" in context, name
        stage = containerfile.split("FROM base-no-de AS tuna\n", 1)[1]
        assert "install-desktop.sh tuna" in stage, name


def test_zypper_cell_installs_the_pinned_beta_from_the_signed_factory_index():
    manifest = yaml.safe_load((ROOT / "manifests/desktops/tuna.yaml").read_text())
    section = manifest["packages"]["zypper"]
    assert section["display_manager"] == "greetd"
    assert "tuna-desktop-1.0.0~beta.1-1" in section["packages"]
    # dbus-update-activation-environment (tuna-os/tuna-desktop#691) and
    # Tumbleweed's emoji font name.
    for package in ("dbus-1-tools", "google-noto-coloremoji-fonts", "greetd", "gtkgreet", "cage", "xdg-desktop-portal-gnome", "xdg-desktop-portal-gtk", "gnome-keyring", "orca", "power-profiles-daemon"):
        assert package in section["packages"], package
    (repo,) = section["repos"]
    assert repo["baseurl"] == "https://repo.tunaos.org/rpm/opensuse-tumbleweed/x86_64/"
    # No priority: Tumbleweed's newer greetd must win over the factory's.
    assert "priority" not in repo
    installer = (ROOT / "build_scripts/desktop/install-desktop.sh").read_text()
    assert ".packages.zypper.repos[$i].baseurl" in installer
    assert 'echo "pkg_gpgcheck=1"' in installer
    containerfile = (ROOT / "Containerfile.opensuse").read_text()
    context = containerfile.split("FROM scratch AS context\n", 1)[1].split("FROM ", 1)[0]
    assert "COPY experiences/tuna /experiences/tuna" in context
    assert "\nFROM desktop AS tuna\n" in containerfile


def test_gentoo_cell_installs_the_pinned_signed_native_package_and_session_dependencies():
    manifest = yaml.safe_load((ROOT / "manifests/desktops/tuna.yaml").read_text())
    section = manifest["packages"]["emerge"]
    assert section["display_manager"] == "greetd"
    assert "=gui-wm/tuna-desktop-1.0.0_beta1::tunaos" in section["packages"]
    for package in (
        "gui-libs/greetd",
        "gui-apps/gtkgreet",
        "=gui-wm/cage-0.3.1::guru",
        "x11-base/xwayland",
        "app-i18n/ibus",
        "app-accessibility/orca",
        "gnome-base/gnome-shell",
        "gnome-base/gnome-settings-daemon",
        "gnome-base/gnome-control-center",
        "gnome-base/gnome-keyring",
        "gnome-extra/evolution-data-server",
        "sys-apps/xdg-desktop-portal-gnome",
        "sys-apps/xdg-desktop-portal-gtk",
        "media-video/pipewire",
        "media-video/wireplumber",
        "sys-power/power-profiles-daemon",
    ):
        assert package in section["packages"], package
    assert section["source_repositories"] == [
        {"name": "guru", "sync_uri": "https://github.com/gentoo/guru.git"}
    ]
    assert section["binrepos"] == [{
        "name": "tunaos",
        "priority": 10,
        "sync_uri": "https://repo.tunaos.org/gentoo/binpkgs/amd64",
        "verify_signature": True,
        "key": "experiences/tuna/tideforge-public.gpg",
        "fingerprint": "4E5CC9F8B3B521793D95266E629BE6EA45188366",
    }]
    assert {"gui-apps/gtkgreet", "gui-wm/cage::guru"} <= set(manifest["emerge_accept_keywords"])

    installer = (ROOT / "build_scripts/desktop/install-desktop.sh").read_text()
    for trust_step in (
        "getuto",
        "--quick-lsign-key",
        "--check-trustdb",
        'FEATURES="binpkg-request-signature"',
        "verify-signature = true",
    ):
        assert trust_step in installer
    assert "emaint sync --repo" in installer
    assert ".packages.emerge.packages[]" in installer

    containerfile = (ROOT / "Containerfile.gentoo").read_text()
    context = containerfile.split("FROM scratch AS context\n", 1)[1].split("FROM ", 1)[0]
    assert "COPY experiences /experiences" in context
    assert "\nFROM desktop AS tuna\n" in containerfile

def test_gentoo_tuna_configures_wlroots_and_user_audio_services(tmp_path):
    import subprocess

    manifest = yaml.safe_load((ROOT / "manifests/desktops/tuna.yaml").read_text())
    assert "gentoo-pipewire-user-services.sh" in manifest["post_install"]
    containerfile = (ROOT / "Containerfile.gentoo").read_text()
    wlroots = 'echo "gui-libs/wlroots x11-backend" >> /etc/portage/package.use/wlroots'
    assert wlroots in containerfile
    assert containerfile.index(wlroots) < containerfile.index(
        "RUN emerge --verbose --deep --newuse @world"
    )

    record = tmp_path / "systemctl-args"
    systemctl = tmp_path / "systemctl"
    systemctl.write_text(
        "#!/bin/sh\nprintf '%s\\n' \"$@\" > \"$TUNAOS_SYSTEMCTL_ARGS\"\n"
    )
    systemctl.chmod(0o755)
    env = {
        "PKG_MGR": "emerge",
        "PATH": f"{tmp_path}:/usr/bin:/bin",
        "TUNAOS_SYSTEMCTL_ARGS": str(record),
    }
    result = subprocess.run(
        ["bash", str(ROOT / "build_scripts/desktop/gentoo-pipewire-user-services.sh")],
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert record.read_text().splitlines() == [
        "--global",
        "enable",
        "pipewire.socket",
        "pipewire-pulse.socket",
        "wireplumber.service",
    ]

    record.unlink()
    env["PKG_MGR"] = "dnf"
    result = subprocess.run(
        ["bash", str(ROOT / "build_scripts/desktop/gentoo-pipewire-user-services.sh")],
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert not record.exists()


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
    for requirement in ("Exec=tuna-session", "/etc/pam.d/tuna-lock", "tuna-shell-gtk", "tuna-session.target", "require_unit greetd", "tuna-portals.conf", "require_command orca"):
        assert requirement in case


def test_tuna_is_a_selectable_greetd_session_listed_by_name(tmp_path):
    """gtkgreet lists environments lines verbatim and greetd runs the chosen
    line as `exec <line>` (tunaOS#3110): the picker shows "Tuna Desktop", and
    that line runs the shipped launcher, which starts tuna-session."""
    import os
    import subprocess

    environments = ROOT / "experiences/tuna/files/etc/greetd/environments"
    assert environments.read_text().splitlines() == ["Tuna Desktop"]
    launcher = ROOT / "experiences/tuna/files/usr/bin/Tuna"
    assert os.access(launcher, os.X_OK), "cp -a must install the launcher executable"
    (tmp_path / "tuna-session").write_text("#!/bin/sh\necho \"tuna-session $# $XDG_SESSION_TYPE\"\n")
    (tmp_path / "tuna-session").chmod(0o755)
    env = {**os.environ, "PATH": f"{launcher.parent}:{tmp_path}:{os.environ['PATH']}",
           "XDG_SESSION_TYPE": "tty"}
    started = subprocess.run(["sh", "-c", f"exec {environments.read_text().strip()}"],
                             env=env, capture_output=True, text=True)
    assert started.returncode == 0, started.stderr
    assert started.stdout == "tuna-session 0 wayland\n"
    for argv in (["Tuna"], ["Tuna", "Desktop", "extra"], ["Tuna", "desktop"]):
        refused = subprocess.run(argv, env=env, capture_output=True, text=True)
        assert refused.returncode == 64
        assert "tuna-session" not in refused.stdout


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


def test_portage_package_names_and_file_owners_use_the_installed_database(tmp_path):
    import subprocess

    script = (ROOT / "build_scripts/checks/verify-desktop-experience.sh").read_text()
    names = script.split("tuna_installed_package_names() {", 1)[1].split("\ntuna_installed_file_owner()", 1)[0]
    owners = script.split("tuna_installed_file_owner() {", 1)[1].split("\n# How many requirements", 1)[0]
    qlist = tmp_path / "qlist"
    qlist.write_text("#!/bin/sh\nprintf 'gui-wm/tuna-desktop\\nsys-power/power-profiles-daemon\\n'\n")
    qlist.chmod(0o755)
    qfile = tmp_path / "qfile"
    qfile.write_text("#!/bin/sh\nprintf 'gui-wm/tuna-desktop\\n'\n")
    qfile.chmod(0o755)
    command = (
        "tuna_installed_package_names() {" + names
        + "\ntuna_installed_file_owner() {" + owners
        + "\ntuna_installed_package_names portage\n"
        + "tuna_installed_file_owner portage /usr/bin/tuna-session"
    )
    result = subprocess.run(
        ["bash", "-c", command], capture_output=True, text=True,
        env={"PATH": f"{tmp_path}:/usr/bin:/bin"},
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["tuna-desktop", "power-profiles-daemon", "tuna-desktop"]



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
