"""The Arch base must generate the UTF-8 locale its desktop session boots into.

The stock `archlinux/archlinux` container ships exactly three locales:

    $ locale -a
    C
    C.utf8
    POSIX

`en_US.UTF-8` is NOT among them — Arch leaves locale generation to the
installer (`locale-gen` reading `/etc/locale.gen`), which a container image
never runs. Every other TunaOS base inherits a distro that pre-generates
en_US.UTF-8 (Fedora/RHEL ship `glibc-langpack-en`, openSUSE `glibc-locale`,
Debian/Ubuntu the `locales` package with en_US enabled), so marlin was the
one variant that shipped without it.

That matters because marlin's GNOME session sets `LANG=en_US.UTF-8`
(accountsservice's default, and what GDM exports for a fresh user). glibc
then cannot find the locale and every locale-aware program prints, on a
stock booted marlin:

    locale: Cannot set LC_CTYPE to default locale: No such file or directory
    locale: Cannot set LC_MESSAGES to default locale: No such file or directory
    locale: Cannot set LC_COLLATE to default locale: No such file or directory

before silently falling back to C. Sorting, number/date formatting and
translated messages all revert to the C locale, and the image is immutable
(bootc/composefs, `/usr` mounted ro), so a user cannot `localedef` their way
out at runtime — `/usr/lib/locale/locale-archive` is on a read-only,
fs-verity-sealed mount. The only place this can be fixed is the build.

This test asserts two independent halves of that fix, both in
Containerfile.arch:

  1. the base stage GENERATES en_US.UTF-8 (via locale-gen after enabling it
     in /etc/locale.gen, or an explicit localedef), so the locale archive
     the image ships actually contains it; and
  2. the image DECLARES a valid default in /etc/locale.conf, so nothing is
     left depending on a session-level LANG that points at a locale glibc
     might not have.

Both halves are load-bearing: (1) without generation, declaring the locale
just moves the failure from "session default" to "our default"; (2) without
a shipped locale.conf, the image's systemd-level default is undefined and we
are back to relying on whatever GDM exports.
"""
from __future__ import annotations

import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
CONTAINERFILE = ROOT / "Containerfile.arch"


@pytest.fixture(scope="module")
def arch_containerfile_text() -> str:
    assert CONTAINERFILE.is_file(), (
        f"{CONTAINERFILE} is missing — this test guards the Arch (marlin) "
        "base build; if the file moved, point this test at its new home "
        "rather than deleting the guard."
    )
    return CONTAINERFILE.read_text(encoding="utf-8")


def test_the_locale_this_test_names_is_the_one_the_session_uses():
    """Guard against the test drifting off the locale marlin actually boots.

    If marlin ever changes its default LANG, this literal must change with
    it or the two assertions below would happily pass while guarding a
    locale nothing uses. Keeping the string in one place makes that coupling
    visible.
    """
    assert LOCALE == "en_US.UTF-8"


LOCALE = "en_US.UTF-8"


def test_the_arch_base_generates_en_us_utf8(arch_containerfile_text: str):
    """The build must actually generate the locale, not just name it.

    Accepts either of the two idioms that produce a populated locale in the
    image's archive:

      * enabling the entry in /etc/locale.gen and running `locale-gen`, or
      * an explicit `localedef -i en_US -f UTF-8 en_US.UTF-8`.

    A bare mention of the string (e.g. only in locale.conf) does NOT count:
    that is the failure mode this guards, so the match requires the
    generating command to be present.
    """
    text = arch_containerfile_text

    runs_locale_gen = re.search(r"\blocale-gen\b", text) is not None
    # locale-gen only emits en_US.UTF-8 if the entry is enabled first; an
    # uncommented locale.gen line, or a heredoc/echo that writes one.
    enables_entry = re.search(
        r"en_US\.UTF-8\s+UTF-8", text
    ) is not None

    runs_localedef = re.search(
        r"localedef\b[^\n]*\ben_US\b[^\n]*\bUTF-8\b", text
    ) is not None

    assert (runs_locale_gen and enables_entry) or runs_localedef, (
        "Containerfile.arch never generates the en_US.UTF-8 locale.\n"
        "The stock archlinux base ships only C / C.UTF-8 / POSIX, but "
        "marlin's session sets LANG=en_US.UTF-8, so a booted image prints "
        "glibc 'Cannot set LC_* to default locale' warnings and falls back "
        "to C. Generate it in the base-no-de stage, e.g.\n\n"
        "    RUN echo 'en_US.UTF-8 UTF-8' >> /etc/locale.gen && locale-gen\n\n"
        "or with an explicit `localedef -i en_US -f UTF-8 en_US.UTF-8`."
    )


def test_the_arch_base_ships_a_default_locale_conf(arch_containerfile_text: str):
    """The image must declare a valid default locale in /etc/locale.conf.

    Generating the locale is necessary but not sufficient: something has to
    point the system at it, or the image's default stays whatever a session
    happens to export. We accept the default being written to
    /etc/locale.conf as either LANG=en_US.UTF-8 or LANG=C.UTF-8 — both are
    valid, since C.UTF-8 is a glibc built-in that always exists — but the
    file must be written by the build.
    """
    text = arch_containerfile_text
    writes_locale_conf = re.search(
        r"/etc/locale\.conf", text
    ) is not None
    declares_lang = re.search(
        r"LANG=(?:en_US\.UTF-8|C\.UTF-8)", text
    ) is not None

    assert writes_locale_conf and declares_lang, (
        "Containerfile.arch does not write a default /etc/locale.conf.\n"
        "Without it the image has no defined system locale and depends on "
        "whatever LANG the desktop session exports — which is exactly the "
        "en_US.UTF-8 that triggered the glibc fallback. Write one, e.g.\n\n"
        "    RUN echo 'LANG=en_US.UTF-8' > /etc/locale.conf\n"
    )
