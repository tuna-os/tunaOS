"""tunaOS#4055: a fresh account on a Tuna image must start the Tuna session.

Shipped: the published marlin:tuna (ghcr.io/tuna-os/marlin@sha256:d9959d1a...,
GDM 51.1) had only `[daemon] DefaultSession=tuna.desktop` in
/etc/gdm/custom.conf and AccountsService's upstream templates with an empty
`Session=`. GDM has no DefaultSession key, so an account with no saved session
started GNOME (tuna-os/tuna-desktop run 40811792200: gnome-session@gnome.target
and gnome-shell for tuna-test in all 5 boots; tuna-session never started).
GDM before 51 has no FallbackSession key at all, so only an AccountsService
user template naming Tuna covers every Tuna flavor.

Held now: build_scripts/desktop/tuna-gdm-default-session.sh turns that
published tree into one whose standard and administrator templates carry
`Session=tuna` in [User] and whose GDM config says `FallbackSession=tuna`, and
the image contract (tuna_fresh_account_session_contract in
build_scripts/checks/verify-desktop-experience.sh) rejects the published tree,
a missing template, a non-Tuna session, Session=tuna outside [User], an /etc
template that shadows a correct data-dir one, and a leftover DefaultSession.

Falsification: behavioural -- the writer and the contract both run on the
published broken configuration. The contract accepts that tree if its template
check is removed, and the writer's output fails it if the writer stops writing
the templates or FallbackSession.
"""
from pathlib import Path
import os
import re
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[2]
WRITER = ROOT / "build_scripts/desktop/tuna-gdm-default-session.sh"
CHECK = ROOT / "build_scripts/checks/verify-desktop-experience.sh"

# What the published marlin:tuna shipped.
PUBLISHED_GDM = "# GDM configuration storage\n\n[daemon]\nDefaultSession=tuna.desktop\n\n[security]\n"
UPSTREAM_TEMPLATE = "[Template]\n#EnvironmentFiles=/etc/os-release;\n\n[User]\nSession=\nIcon=${HOME}/.face\n"
TUNA_TEMPLATE = "[User]\nSession=tuna\n"
TUNA_GDM = "[daemon]\nFallbackSession=tuna\n"


def contract(root):
    source = CHECK.read_text()
    match = re.search(r"^tuna_fresh_account_session_contract\(\) \{.*?^\}", source, re.M | re.S)
    assert match, "the desktop gate has no fresh-account session contract"
    script = match.group(0) + f'\ntuna_fresh_account_session_contract "{root}/etc/gdm/custom.conf" "{root}"'
    return subprocess.run(["/bin/bash", "-c", script], capture_output=True, text=True)


def tree(root, gdm=TUNA_GDM, templates=None):
    """Lay down a GDM config and templates; templates maps relative path -> text."""
    (root / "etc/gdm").mkdir(parents=True)
    (root / "etc/gdm/custom.conf").write_text(gdm)
    for relative, text in (templates or {}).items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)


def both(directory, text):
    return {f"{directory}/accountsservice/user-templates/{kind}": text for kind in ("standard", "administrator")}


def published(root):
    tree(root, PUBLISHED_GDM, both("usr/share", UPSTREAM_TEMPLATE))


def test_the_published_tree_fails_the_contract(tmp_path):
    published(tmp_path)
    result = contract(tmp_path)
    assert result.returncode != 0
    assert "template does not start new accounts in the Tuna session" in result.stderr


def test_the_writer_turns_the_published_tree_into_one_that_starts_tuna(tmp_path):
    published(tmp_path)
    env = dict(os.environ, TUNAOS_GDM_DEFAULT_ROOT=str(tmp_path))
    subprocess.run(["bash", str(WRITER)], check=True, env=env)
    for kind in ("standard", "administrator"):
        text = (tmp_path / f"etc/accountsservice/user-templates/{kind}").read_text()
        assert "Session=tuna" in text.split("[User]", 1)[1]
    result = contract(tmp_path)
    assert result.returncode == 0, result.stderr


def test_valid_templates_pass(tmp_path):
    tree(tmp_path, templates=both("etc", TUNA_TEMPLATE))
    assert contract(tmp_path).returncode == 0


@pytest.mark.parametrize(
    "templates, message",
    [
        ({}, "missing"),
        ({"etc/accountsservice/user-templates/standard": TUNA_TEMPLATE}, "administrator template"),
        (both("etc", "[User]\nSession=gnome\n"), "standard template"),
        (both("etc", "[Template]\nSession=tuna\n\n[User]\nSession=\n"), "standard template"),
        (
            {**both("usr/share", TUNA_TEMPLATE), **both("etc", UPSTREAM_TEMPLATE)},
            "/etc/accountsservice/user-templates/standard",
        ),
    ],
    ids=["missing", "one-missing", "non-tuna", "wrong-group", "etc-shadows-data-dir"],
)
def test_templates_that_do_not_start_tuna_fail(tmp_path, templates, message):
    tree(tmp_path, templates=templates)
    result = contract(tmp_path)
    assert result.returncode != 0
    assert "does not start new accounts in the Tuna session" in result.stderr
    assert message in result.stderr


@pytest.mark.parametrize(
    "gdm, message",
    [
        ("[daemon]\n", "does not fall back to the Tuna session"),
        ("[daemon]\nFallbackSession=gnome\n", "does not fall back to the Tuna session"),
        ("[daemon]\nFallbackSession=tuna\nDefaultSession=tuna.desktop\n", "no DefaultSession key"),
    ],
    ids=["no-fallback", "gnome-fallback", "leftover-default"],
)
def test_gdm_config_that_does_not_fall_back_to_tuna_fails(tmp_path, gdm, message):
    tree(tmp_path, gdm, both("etc", TUNA_TEMPLATE))
    result = contract(tmp_path)
    assert result.returncode != 0
    assert message in result.stderr
