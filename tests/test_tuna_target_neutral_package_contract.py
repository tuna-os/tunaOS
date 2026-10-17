"""Execute the actual installed-package query functions for each backend.

Command adapters expose exact requested argv and database answers; they do not
qualify any built image or convert a metadata check into a login proof.
"""

import json
import os
import shlex
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "build_scripts/checks/verify-desktop-experience.sh"
FUNCTIONS = (
    SCRIPT.read_text()
    .split("tuna_package_backend() {", 1)[1]
    .split("TUNAOS_CONTRACT_WAIVED=0", 1)[0]
)
FUNCTIONS = "tuna_package_backend() {" + FUNCTIONS


def execute(tmp_path, command, output="", returncode=0, body=""):
    tools = tmp_path / "tools"
    tools.mkdir(exist_ok=True)
    log = tmp_path / "argv.json"
    for name in ("pacman", "rpm", "dpkg-query", "qlist", "qfile"):
        tool = tools / name
        tool.write_text(
            "#!/usr/bin/env python3\nimport json,os,sys\nfrom pathlib import Path\n"
            'Path(os.environ["QUERY_LOG"]).write_text(json.dumps(sys.argv))\n'
            'sys.stdout.write(os.environ["QUERY_OUTPUT"])\n'
            'sys.exit(int(os.environ["QUERY_EXIT"]))\n'
        )
        tool.chmod(0o755)
    env = dict(
        os.environ,
        PATH=str(tools) + os.pathsep + os.environ["PATH"],
        QUERY_LOG=str(log),
        QUERY_OUTPUT=output,
        QUERY_EXIT=str(returncode),
    )
    result = subprocess.run(
        ["bash", "-euo", "pipefail", "-c", (body or FUNCTIONS) + "\n" + command],
        env=env,
        check=False,
        text=True,
        capture_output=True,
    )
    return result, json.loads(log.read_text()) if log.exists() else None


@pytest.mark.parametrize(
    "backend,output,wanted,argv",
    [
        ("pacman", "tuna-desktop\nother\n", "tuna-desktop\nother\n", ["-Qq"]),
        ("rpm", "tuna-desktop\nother\n", "tuna-desktop\nother\n", ["-qa", "--qf", "%{NAME}\\n"]),
        (
            "dpkg",
            "tuna-desktop:amd64\tinstalled\nroost\tconfig-files\nforeign\tunpacked\n",
            "tuna-desktop\n",
            ["-W", "-f", "${binary:Package}\\t${db:Status-Status}\\n"],
        ),
        ("portage", "tuna-desktop\nother\n", "tuna-desktop\nother\n", ["-ICF", "%[PN]"]),
    ],
)
def test_actual_installed_names_queries_exclude_virtual_provides(
    tmp_path, backend, output, wanted, argv
):
    result, recorded = execute(tmp_path, f"tuna_installed_package_names {backend}", output)
    assert result.returncode == 0, result.stderr
    assert result.stdout == wanted
    assert recorded[1:] == argv


@pytest.mark.parametrize(
    "backend,output,argv",
    [
        ("pacman", "tuna-desktop\n", ["-Qqo", "/usr/bin/tuna-compositor"]),
        ("rpm", "tuna-desktop\n", ["-qf", "--qf", "%{NAME}\\n", "/usr/bin/tuna-compositor"]),
        (
            "dpkg",
            "tuna-desktop:amd64: /usr/bin/tuna-compositor\n",
            ["-S", "/usr/bin/tuna-compositor"],
        ),
        ("portage", "tuna-desktop\n", ["-CqPF", "%[PN]", "/usr/bin/tuna-compositor"]),
    ],
)
def test_actual_owner_queries_bind_binary_to_package(tmp_path, backend, output, argv):
    result, recorded = execute(
        tmp_path, f"tuna_installed_file_owner {backend} /usr/bin/tuna-compositor", output
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == "tuna-desktop\n"
    assert recorded[1:] == argv


@pytest.mark.parametrize("backend", ["pacman", "rpm", "dpkg", "portage"])
def test_database_query_failure_never_passes(tmp_path, backend):
    result, _ = execute(tmp_path, f"tuna_installed_package_names {backend}", returncode=9)
    assert result.returncode != 0


def test_ambiguous_dpkg_owner_fails(tmp_path):
    result, _ = execute(
        tmp_path,
        "tuna_installed_file_owner dpkg /usr/bin/tuna-compositor",
        "tuna-desktop: /usr/bin/tuna-compositor\nforeign: /usr/bin/tuna-compositor\n",
    )
    assert result.returncode != 0


@pytest.mark.parametrize(
    "owner,returncode",
    [
        ("foreign-package\n", 0),
        ("", 9),
    ],
)
def test_actual_tuna_branch_rejects_foreign_or_failed_owner_query(
    tmp_path, owner, returncode
):
    tools = tmp_path / "tools"
    tools.mkdir()
    for binary in (
        "tuna-compositor",
        "tuna-session",
        "tuna-shell-host",
        "tuna-shell-gtk",
        "tuna-ibus-bridge",
        "tuna-greeter",
    ):
        command = tools / binary
        command.write_text("#!/bin/sh\nexit 0\n")
        command.chmod(0o755)

    case = SCRIPT.read_text().split("\ntuna)\n", 1)[1].split("\n\t;;", 1)[0]
    owner_loop = "for binary " + case.split("\tfor binary ", 1)[1].split(
        "\n\tdone", 1
    )[0] + "\n\tdone"
    body = (
        FUNCTIONS
        + "\nrequire_command() { command -v \"$1\" >/dev/null; }\n"
        + "tuna_installed_file_owner() { printf '%s' \"$QUERY_OUTPUT\"; return \"$QUERY_EXIT\"; }\n"
        + "tuna_backend=dpkg\n"
        + owner_loop
    )
    result, _ = execute(tmp_path, ":", owner, returncode, body)
    assert result.returncode != 0
    assert "is not owned by the installed tuna-desktop package" in result.stderr


@pytest.mark.parametrize(
    "present",
    [
        "usr/lib/gnome-shell-calendar-server",
        "usr/libexec/gnome-shell-calendar-server",
        "usr/libexec/gnome-shell/gnome-shell-calendar-server",
        None,
    ],
)
def test_actual_calendar_server_paths_are_cross_distribution(tmp_path, present):
    if present is not None:
        path = tmp_path / present
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()

    source = SCRIPT.read_text()
    helper = "require_any_glob() {" + source.split(
        "require_any_glob() {", 1
    )[1].split("\n}", 1)[0] + "\n}"
    tuna_case = source.split("\ntuna)\n", 1)[1].split("\n\t;;", 1)[0]
    calendar_call = next(
        line.strip()
        for line in tuna_case.splitlines()
        if "gnome-shell-calendar-server" in line
    )
    paths = [tmp_path / path.lstrip("/") for path in shlex.split(calendar_call)[1:]]
    result = subprocess.run(
        ["bash", "-euo", "pipefail", "-c", helper + "\nrequire_any_glob " + " ".join(
            shlex.quote(str(path)) for path in paths
        )],
        text=True,
        capture_output=True,
        check=False,
    )
    assert (result.returncode == 0) == (present is not None)


@pytest.mark.parametrize(
    "os_id,backend",
    [
        ("arch", "pacman"),
        ("ubuntu", "dpkg"),
        ("debian", "dpkg"),
        ("gentoo", "portage"),
        ("almalinux", "rpm"),
        ("centos", "rpm"),
        ("fedora", "rpm"),
        ("eln", "rpm"),
        ("hummingbird", "rpm"),
        ("opensuse-tumbleweed", "rpm"),
    ],
)
def test_runtime_backend_uses_os_release_without_build_context(tmp_path, os_id, backend):
    release = tmp_path / "os-release"
    release.write_text(f"ID={os_id}\n")
    body = FUNCTIONS.replace("source /etc/os-release", f'source "{release}"')
    result, _ = execute(tmp_path, "tuna_package_backend", body=body)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == backend


def test_unknown_backend_cannot_default_to_rpm(tmp_path):
    release = tmp_path / "os-release"
    release.write_text("ID=unknown\n")
    result, _ = execute(
        tmp_path,
        "tuna_package_backend",
        body=FUNCTIONS.replace("source /etc/os-release", f'source "{release}"'),
    )
    assert result.returncode != 0


def test_installed_contract_reaches_query_and_portal_after_overlay():
    case = SCRIPT.read_text().split("\ntuna)\n", 1)[1].split("\n\t;;", 1)[0]
    assert 'tuna_installed_package_names "$tuna_backend"' in case
    assert 'tuna_installed_file_owner "$tuna_backend" "/usr/bin/$binary"' in case
    assert "org.freedesktop.impl.portal.Lockdown tuna" in case
    routing = ROOT / "experiences/tuna/files/usr/share/xdg-desktop-portal/tuna-portals.conf"
    assert routing.read_text().splitlines().count("org.freedesktop.impl.portal.Lockdown=tuna;") == 1


@pytest.mark.parametrize(
    "answer",
    [
        "tuna-desktop-debug\tinstalled\n",
        "roost\tinstalled\n",
        "tuna-desktop\tinstalled\nroost\tinstalled\n",
    ],
)
def test_actual_tuna_branch_rejects_old_or_nonmatching_installed_name(tmp_path, answer):
    case = SCRIPT.read_text().split("\ntuna)\n", 1)[1].split("\n\tfor binary", 1)[0]
    result, _ = execute(
        tmp_path,
        case,
        answer,
        body=FUNCTIONS.replace("tuna_package_backend() {", "unused_backend() {")
        + "\ntuna_package_backend() { echo dpkg; }\n",
    )
    assert result.returncode != 0


@pytest.mark.parametrize(
    "replacement",
    [
        "",
        "org.freedesktop.impl.portal.Lockdown=gnome;\n",
        "org.freedesktop.impl.portal.Lockdown=tuna;gnome;\n",
        "org.freedesktop.impl.portal.Lockdown=tuna;\n" * 2,
    ],
)
def test_actual_portal_parser_rejects_missing_wrong_or_ambiguous_privacy_route(
    tmp_path, replacement
):
    source = SCRIPT.read_text()
    parser = (
        "require_portal_preference() {"
        + source.split("require_portal_preference() {", 1)[1].split("\nrequire_unit()", 1)[0]
    )
    config = tmp_path / "portals.conf"
    config.write_text("[preferred]\n" + replacement)
    result = subprocess.run(
        [
            "bash",
            "-euo",
            "pipefail",
            "-c",
            parser
            + f'\nrequire_portal_preference "{config}" org.freedesktop.impl.portal.Lockdown tuna',
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode != 0
