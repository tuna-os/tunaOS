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
    assert {v["id"] for v in admitted} == {"marlin", "yellowfin", "albacore", "skipjack", "wahoo", "bonito", "bonito-rawhide", "hummingbird", "grouper", "flounder", "flounder-sid", "sailfin"}
    for variant in admitted:
        flavor = next(f for f in variant["flavors"] if f["id"] == "tuna")
        assert flavor["stage"] == 2
        assert flavor["platforms"] == ["linux/amd64"]
        assert not flavor["build_iso"]
        assert not flavor["build_qcow2"]
        assert flavor["luks_e2e"] is False
    manifest = yaml.safe_load((ROOT / "manifests/desktops/tuna.yaml").read_text())
    assert "tunaos/tuna-desktop=1.0.0beta.1-1" in manifest["packages"]["pacman"]
    assert "orca" in manifest["packages"]["pacman"], "the Screen Reader key needs distribution Orca"
    assert manifest["display_manager"] == "greetd"
    assert "greetd-gtkgreet.sh" in manifest["post_install"]


def test_marlin_runs_tuna_on_gdm_while_other_flavors_stay_on_greetd():
    """tunaOS#3438, Marlin first: the -arch override moves Marlin to stock
    GDM while every other tuna flavor keeps greetd. A second display
    manager beside GDM would race it for seat0/VT1, so the Arch list must
    not name any greetd frontend, and no greetd post-install may run."""
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
    # The shared manifest is untouched: other flavors keep their DM.
    shared = yaml.safe_load((ROOT / "manifests/desktops/tuna.yaml").read_text())
    assert shared["display_manager"] == "greetd"
    assert "greetd-gtkgreet.sh" in shared["post_install"]


def test_tuna_contract_expects_gdm_on_marlin_and_greetd_elsewhere():
    """The desktop contract must match the manifest per base: GDM on
    Marlin (pacman) and greetd everywhere else."""
    script = (ROOT / "build_scripts/checks/verify-desktop-experience.sh").read_text()
    case = script.split("\ntuna)\n", 1)[1].split("\n\t;;", 1)[0]
    assert "dm_pattern='^gdm\\.service$'" in case
    assert "dm_pattern='^greetd\\.service$'" in case
    assert "require_unit gdm" in case

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


def test_hummingbird_cell_uses_the_pinned_native_signed_target():
    manifest = yaml.safe_load((ROOT / "manifests/desktops/tuna.yaml").read_text())
    section = manifest["packages"]["hummingbird"]
    assert section["display_manager"] == "greetd"
    assert section["repos"] == [
        {
            "name": "tunaos-hummingbird",
            "baseurl": "https://repo.tunaos.org/hummingbird/20251124-$basearch/",
            "priority": 5,
        },
        {
            "name": "utah-packages",
            "baseurl": "file:///run/utah-packages",
            "priority": 4,
            "unsigned": True,
        },
    ]
    assert section["packages"][0] == "tuna-desktop-1.0.0~beta.1-1.bfin1"
    for package in (
        "dbus-tools", "orca", "greetd", "gtkgreet", "cage",
        "xorg-x11-server-Xwayland", "ibus", "gnome-shell",
        "evolution-data-server", "xdg-desktop-portal-gnome",
        "xdg-desktop-portal-gtk", "gvfs", "nautilus", "NetworkManager",
        "NetworkManager-wifi", "linux-firmware", "amd-gpu-firmware",
        "intel-gpu-firmware", "iwlwifi-mvm-firmware", "wireless-regdb", "iw",
        "pipewire", "wireplumber", "pipewire-gstreamer",
        "gstreamer1-plugins-good", "gstreamer1-plugin-libav", "ffmpeg",
        "tuned-ppd", "flatpak",
    ):
        assert package in section["packages"], package

    config = rollout()
    variant = next(v for v in config["variants"] if v["id"] == "hummingbird")
    flavor = next(f for f in variant["flavors"] if f["id"] == "tuna")
    assert flavor == {
        "id": "tuna",
        "stage": 2,
        "platforms": ["linux/amd64"],
        "build_image": True,
        "build_iso": False,
        "build_qcow2": False,
        "luks_e2e": False,
    }
    assert variant["base_image"] == (
        "quay.io/hummingbird-community/bootc-os:latest@"
        "sha256:a3a06793169af39bf14f49f497ad243984343617ef22725507ddc66b4c8e9413"
    )

    stage = (ROOT / "Containerfile.el10").read_text().split("FROM base-no-de AS tuna\n", 1)[1]
    assert "install-desktop.sh tuna" in stage
    assert "--mount=type=bind,from=utah-packages,source=/repository,target=/run/utah-packages" in stage
    base_packages = (ROOT / "build_scripts/10-base-packages.sh").read_text()
    hummingbird = base_packages.split(
        "if [[ $IS_HUMMINGBIRD == true ]]; then", 1
    )[1].split("\nelif", 1)[0]
    assert "gpgcheck=1" in hummingbird
    assert "gpgkey=https://repo.tunaos.org/public.gpg" in hummingbird


def test_hummingbird_bootstrap_waiver_excludes_admitted_tuna():

    import re
    import subprocess

    script = (ROOT / "build_scripts/checks/verify-desktop-experience.sh").read_text()
    guard = re.search(
        r'if \[\[ "\$\{IS_HUMMINGBIRD:-false\}" == "true" && "\$\{desktop:-\}" != cosmic && "\$\{desktop:-\}" != tuna \]\]; then',
        script,
    )
    assert guard, "the Hummingbird waiver must exclude admitted Tuna"
    command = (
        'IS_HUMMINGBIRD=true; desktop="$1"; '
        f"{guard.group(0)} exit 0; else exit 1; fi"
    )
    for desktop, accepted in (("gnome", True), ("cosmic", False), ("tuna", False)):
        result = subprocess.run(
            ["bash", "-c", command, "waiver-test", desktop],
            capture_output=True,
            text=True,
        )
        assert (result.returncode == 0) is accepted, (desktop, result.stderr)

def test_hummingbird_tuna_promotion_requires_the_release_gate():
    build_variant = (ROOT / ".github/workflows/build-variant.yml").read_text()
    assert (
        "promote: ${{ matrix.variant != 'hummingbird' || matrix.flavor != 'tuna' }}"
        in build_variant
    )
    reusable = (ROOT / ".github/workflows/reusable-build-image.yml").read_text()
    promote = reusable.split("  tag-image:", 1)[1].split("  promote:", 1)[0]
    assert "inputs.promote" in promote


def test_hummingbird_tuna_required_packages_do_not_use_best_effort_fallback():
    installer = (ROOT / "build_scripts/desktop/install-desktop.sh").read_text()
    strict = installer.split('if [[ "${_TD_DESKTOP}" == "tuna" ]]; then', 1)[1].split(
        "elif ", 1
    )[0]
    assert "dnf_retry -y install" in strict
    assert "--skip-unavailable" not in strict
    library = (ROOT / "build_scripts/lib.sh").read_text()
    assert "--qf '%{name}-%{version}-%{release}\\n'" in library


def test_hummingbird_tuna_fails_direct_contract_checks():
    import re
    import subprocess

    script = (ROOT / "build_scripts/checks/verify-desktop-experience.sh").read_text()
    guards = re.findall(
        r'(?m)^\s*((?:if|elif) \[\[ "\$\{IS_HUMMINGBIRD:-false\}" != "true" \|\| "\$\{desktop:-\}" == tuna \]\]; then)$',
        script,
    )
    assert len(guards) >= 5, "the direct Hummingbird failure guards changed"
    for guard in guards:
        condition = guard.replace("elif ", "if ", 1)
        command = (
            'IS_HUMMINGBIRD=true; desktop="$1"; '
            f"{condition} exit 0; else exit 1; fi"
        )
        for desktop, accepted in (("tuna", True), ("gnome", False)):
            result = subprocess.run(
                ["bash", "-c", command, "guard-test", desktop],
                capture_output=True,
                text=True,
            )
            assert (result.returncode == 0) is accepted, (guard, desktop)

def _hummingbird_codec_block() -> str:
    source = (ROOT / "build_scripts/checks/verify-desktop-experience.sh").read_text()
    return source.split("\t# ── Codec baseline ──\n", 1)[1].split(
        "\n\t# ── KDE version-skew guard", 1
    )[0]


def _run_hummingbird_tuna_codec_case(tmp_path: Path, *, decoders_rc: int):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True)
    ffmpeg = bin_dir / "ffmpeg"
    ffmpeg.write_text(
        "#!/usr/bin/env bash\n"
        'if [[ "$*" == *"-decoders"* ]]; then exit "$DECODERS_RC"; fi\n'
        "exit 0\n"
    )
    ffmpeg.chmod(0o755)
    script = "\n".join(
        [
            "set -euo pipefail",
            "desktop=tuna",
            "IS_HUMMINGBIRD=true",
            "IS_ELN=false",
            "TUNAOS_CONTRACT_WAIVED=0",
            "waive() { TUNAOS_CONTRACT_WAIVED=$((TUNAOS_CONTRACT_WAIVED + 1)); }",
            "require_any_glob() { :; }",
            "require_command() { :; }",
            _hummingbird_codec_block(),
        ]
    )
    return subprocess.run(
        ["bash", "-c", script],
        capture_output=True,
        text=True,
        env={
            "PATH": f"{bin_dir}:/usr/bin:/bin",
            "DECODERS_RC": str(decoders_rc),
        },
    )


def test_hummingbird_tuna_codec_failures_are_not_waived(tmp_path):
    cannot_run = _run_hummingbird_tuna_codec_case(tmp_path / "cannot-run", decoders_rc=7)
    assert cannot_run.returncode == 1, cannot_run.stdout + cannot_run.stderr
    assert "would not run" in cannot_run.stderr

    no_h264 = _run_hummingbird_tuna_codec_case(tmp_path / "no-h264", decoders_rc=0)
    assert no_h264.returncode == 1, no_h264.stdout + no_h264.stderr
    assert "cannot decode h264" in no_h264.stderr

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
