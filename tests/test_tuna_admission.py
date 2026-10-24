"""Tuna Desktop (formerly Roost) admission must preserve signed sourcing and an installed-session gate."""
import hashlib
import subprocess
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
        assert flavor.get("promotion_hold", False) == (variant["id"] == "guppy")
        assert not flavor["build_iso"]
        assert not flavor["build_qcow2"]
        assert flavor["luks_e2e"] is False
    manifest = yaml.safe_load((ROOT / "manifests/desktops/tuna.yaml").read_text())
    assert "tunaos/tuna-desktop=1.0.0beta.1-1" in manifest["packages"]["pacman"]
    assert "orca" in manifest["packages"]["pacman"], "the Screen Reader key needs distribution Orca"
    assert manifest["display_manager"] == "gdm"
    assert "tuna-gdm-theme.sh" in manifest["post_install"]


def test_guppy_tuna_promotion_hold_reaches_reusable_workflow():
    matrix_workflow = (ROOT / ".github/workflows/build-variant.yml").read_text()
    reusable_workflow = (ROOT / ".github/workflows/reusable-build-image.yml").read_text()
    assert "promotion_hold: (.promotion_hold // false)" in matrix_workflow
    assert "promotion_hold: .promotion_hold" in matrix_workflow
    assert "promote: ${{ !matrix.promotion_hold }}" in matrix_workflow
    assert "inputs.promote" in reusable_workflow


def test_all_tuna_bases_use_gdm_and_remove_greetd_components():
    arch = yaml.safe_load((ROOT / "manifests/desktops/tuna-arch.yaml").read_text())
    assert arch["display_manager"] == "gdm"
    assert "tuna-gdm-theme.sh" in arch["post_install"]
    assert "gdm" in arch["packages"]["pacman"]

    shared = yaml.safe_load((ROOT / "manifests/desktops/tuna.yaml").read_text())
    assert shared["display_manager"] == "gdm"
    assert "tuna-gdm-theme.sh" in shared["post_install"]
    removed = {"greetd", "greetd-gtkgreet", "gtkgreet", "cage"}
    assert removed.isdisjoint(arch["packages"]["pacman"])
    for target in ("el10", "fedora", "eln", "rawhide", "zypper"):
        section = shared["packages"][target]
        assert section["display_manager"] == "gdm", target
        assert "gdm" in section["packages"], target
        assert removed.isdisjoint(section["packages"]), target
    apt = shared["packages"]["apt"]
    assert apt["display_manager"] == "gdm"
    assert {"gdm3", "gjs"} <= set(apt["packages"])
    assert removed.isdisjoint(apt["packages"])
    assert not any("greetd" in script for script in shared["post_install"])


def test_pull_requests_build_every_admitted_tuna_image_in_ci():
    config = rollout()
    admitted = {
        variant["id"]
        for variant in config["variants"]
        if config["tuna_rollout"][variant["id"]]["status"] == "admitted"
    }
    workflow = yaml.safe_load((ROOT / ".github/workflows/test.yml").read_text())
    event = workflow.get("on", workflow.get(True))
    assert "pull_request" in event
    assert {".github/**", "build_scripts/**", "system_files_overrides/**", "tunaos.toml"} <= set(
        event["pull_request"]["paths"]
    )
    assert workflow["permissions"]["contents"] == "read"
    detector = workflow["jobs"]["tuna_build_inputs"]
    assert detector["if"] == "github.event_name == 'pull_request'"
    assert detector["permissions"] == {"contents": "read", "pull-requests": "read"}
    assert detector["outputs"]["relevant"] == "${{ steps.filter.outputs.relevant }}"

    job = workflow["jobs"]["tuna_pr_images"]
    assert job["needs"] == "tuna_build_inputs"
    assert job["if"] == (
        "github.event_name == 'pull_request' && "
        "needs.tuna_build_inputs.outputs.relevant == 'true'"
    )
    assert job["permissions"] == {
        "contents": "read",
        "packages": "write",
        "id-token": "write",
    }
    assert "secrets" not in job
    assert job["uses"] == "./.github/workflows/build-variant.yml"
    assert job["with"]["flavor"] == "tuna"
    assert job["with"]["variant"] == "${{ matrix.variant }}"
    assert set(job["strategy"]["matrix"]["variant"]) == admitted
    assert len(job["strategy"]["matrix"]["variant"]) == len(admitted)
    variant_workflow = yaml.safe_load((ROOT / ".github/workflows/build-variant.yml").read_text())
    build_base = variant_workflow["jobs"]["build_base"]["with"]
    assert build_base["publish"] == "${{ github.event_name != 'pull_request' }}"
    assert build_base["sbom"] == "${{ github.event_name != 'pull_request' }}"


def test_tuna_build_input_filter_catches_sources_and_ignores_docs():
    script = ROOT / ".github/scripts/tuna-pr-build-inputs.sh"

    def matches(path):
        result = subprocess.run(
            ["bash", str(script)],
            input=path + "\n",
            text=True,
            capture_output=True,
        )
        return result.returncode == 0

    for path in (
        "tunaos.toml",
        "build_scripts/desktop/tuna-gdm-theme.sh",
        ".github/scripts/tuna-pr-build-inputs.sh",
        "system_files_overrides/tuna/example.conf",
    ):
        assert matches(path), path
    assert not matches("docs/CI_SPEC.md")

def test_rpm_cells_install_the_pinned_beta_from_signed_factory_repositories():
    manifest = yaml.safe_load((ROOT / "manifests/desktops/tuna.yaml").read_text())
    for target, nevr in (("el10", "tuna-desktop-1.0.0~beta.1-1.el10"), ("fedora", "tuna-desktop-1.0.0~beta.1-1.fc44"), ("rawhide", "tuna-desktop-1.0.0~beta.1-1.fc46"), ("eln", "tuna-desktop-1.0.0~beta.1-1.eln159")):
        section = manifest["packages"][target]
        assert section["display_manager"] == "gdm"
        assert nevr in section["packages"]
        for package in ("gdm", "xdg-desktop-portal-gnome", "xdg-desktop-portal-gtk", "gnome-keyring"):
            assert package in section["packages"], (target, package)
        assert {"greetd", "greetd-gtkgreet", "gtkgreet", "cage"}.isdisjoint(section["packages"]), target
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
    # The ELN repository supplies Tuna Desktop; the login manager comes from ELN.
    assert manifest["packages"]["eln"]["repos"] == [{"name": "tunaos-eln", "baseurl": "https://repo.tunaos.org/rpm/eln/x86_64/", "priority": 100}]
    containerfile = (ROOT / "Containerfile.el10").read_text()
    context = containerfile.split("FROM scratch as context\n", 1)[1].split("FROM ", 1)[0]
    assert "COPY experiences/tuna /experiences/tuna" in context
    stage = containerfile.split("FROM base-no-de AS tuna\n", 1)[1]
    assert "install-desktop.sh tuna" in stage


def test_apt_cells_install_the_pinned_beta_from_the_signed_tideforge_index_for_their_base():
    manifest = yaml.safe_load((ROOT / "manifests/desktops/tuna.yaml").read_text())
    section = manifest["packages"]["apt"]
    assert section["display_manager"] == "gdm"
    assert "tuna-desktop=1.0.0~beta.1-1" in section["packages"]
    for package in ("gdm3", "gjs", "xdg-desktop-portal-gnome", "xdg-desktop-portal-gtk", "gnome-keyring", "orca", "power-profiles-daemon"):
        assert package in section["packages"], package
    assert {"greetd", "greetd-gtkgreet", "gtkgreet", "cage"}.isdisjoint(section["packages"])
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
    for package in ("dbus-1-tools", "google-noto-coloremoji-fonts", "gdm", "xdg-desktop-portal-gnome", "xdg-desktop-portal-gtk", "gnome-keyring", "orca", "power-profiles-daemon"):
        assert package in section["packages"], package
    assert {"greetd", "greetd-gtkgreet", "gtkgreet", "cage"}.isdisjoint(section["packages"])
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


def test_gentoo_cell_installs_the_pinned_signed_native_package_and_session_dependencies():
    manifest = yaml.safe_load((ROOT / "manifests/desktops/tuna.yaml").read_text())
    section = manifest["packages"]["emerge"]
    assert section["display_manager"] == "gdm"
    assert "=gui-wm/tuna-desktop-1.0.0_beta1::tunaos" in section["packages"]
    for package in (
        "gnome-base/gdm",
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
    assert "source_repositories" not in section
    assert section["binrepos"] == [{
        "name": "tunaos",
        "priority": 10,
        "sync_uri": "https://repo.tunaos.org/gentoo/binpkgs/amd64",
        "verify_signature": True,
        "key": "experiences/tuna/tideforge-public.gpg",
        "fingerprint": "4E5CC9F8B3B521793D95266E629BE6EA45188366",
    }]
    assert "emerge_accept_keywords" not in manifest

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

    result = subprocess.run(
        ["/bin/bash", str(ROOT / "build_scripts/desktop/gentoo-pipewire-user-services.sh")],
        env={"PKG_MGR": "emerge", "PATH": str(tmp_path / "missing")},
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "requires systemctl" in result.stderr

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


def test_gdm_migration_removes_tuna_specific_greetd_assets():
    assert not (ROOT / "experiences/tuna/files/etc/greetd/environments").exists()
    assert not (ROOT / "experiences/tuna/files/usr/bin/Tuna").exists()


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


def test_portage_backend_requires_an_installed_database_entry(tmp_path):
    import subprocess

    script = (ROOT / "build_scripts/checks/verify-desktop-experience.sh").read_text()
    function = script.split("tuna_package_backend() {", 1)[1].split(
        "\ntuna_installed_package_names()", 1
    )[0]
    database = tmp_path / "var/db/pkg"
    database.mkdir(parents=True)
    command = "tuna_package_backend() {" + function + "\ntuna_package_backend"
    env = {
        "PATH": str(tmp_path / "no-tools"),
        "TUNAOS_PORTAGE_DB": str(database),
    }

    empty = subprocess.run(
        ["/bin/bash", "-c", command], capture_output=True, text=True, env=env
    )
    assert empty.returncode != 0

    package = database / "gui-wm/tuna-desktop-1"
    package.mkdir(parents=True)
    (package / "PF").write_text("tuna-desktop-1\n")
    populated = subprocess.run(
        ["/bin/bash", "-c", command], capture_output=True, text=True, env=env
    )
    assert populated.returncode == 0, populated.stderr
    assert populated.stdout.strip() == "portage"

def test_portage_package_names_and_file_owners_use_the_installed_database(tmp_path):
    import subprocess

    script = (ROOT / "build_scripts/checks/verify-desktop-experience.sh").read_text()
    names = script.split("tuna_installed_package_names() {", 1)[1].split("\ntuna_installed_file_owner()", 1)[0]
    owners = script.split("tuna_installed_file_owner() {", 1)[1].split("\n# How many requirements", 1)[0]
    database = tmp_path / "var/db/pkg"
    tuna = database / "gui-wm/tuna-desktop-1.0.0_beta1-r1"
    power = database / "sys-power/power-profiles-daemon-0.30.0"
    tuna.mkdir(parents=True)
    power.mkdir(parents=True)
    (tuna / "PF").write_text("tuna-desktop-1.0.0_beta1-r1\n")
    (power / "PF").write_text("power-profiles-daemon-0.30.0\n")
    (tuna / "CONTENTS").write_text(
        "obj /usr/bin/tuna-session deadbeef 1\n"
        "obj /usr/bin/not-the-session deadbeef 1\n"
    )
    (power / "CONTENTS").write_text("obj /usr/bin/powerprofilesctl deadbeef 1\n")
    command = (
        "tuna_installed_package_names() {" + names
        + "\ntuna_installed_file_owner() {" + owners
        + "\ntuna_installed_package_names portage\n"
        + "tuna_installed_file_owner portage /usr/bin/tuna-session"
    )
    result = subprocess.run(
        ["bash", "-c", command], capture_output=True, text=True,
        env={
            "PATH": "/usr/bin:/bin",
            "TUNAOS_PORTAGE_DB": str(database),
        },
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == [
        "tuna-desktop",
        "power-profiles-daemon",
        "tuna-desktop",
    ]



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
