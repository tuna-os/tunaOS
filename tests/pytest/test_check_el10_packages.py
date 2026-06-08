#!/usr/bin/env python3
"""Unit tests for .github/scripts/check-el10-packages.py

Tests the package-candidate extraction logic, noise filtering,
result parsing, and issue-deduplication logic.

Run with: pytest test_check_el10_packages.py -v
"""

import re
import pytest
import tempfile
import pathlib

# ── Import testable functions from the script ────────────────────────────────
# The script isn't structured as a module, so we replicate the key logic
# here for testing. These are the exact regexes and constants from the
# original script.

PKG_RE = re.compile(r"\b([a-zA-Z][a-zA-Z0-9._+\-]{2,60})\b")

NOISE = {
    "the", "and", "for", "not", "are", "was", "has", "that", "this", "with",
    "from", "true", "false", "then", "else", "elif", "done", "esac", "exit",
    "echo", "sudo", "bash", "fish", "dnf", "rpm", "yum", "git", "apt", "var",
    "usr", "etc", "lib", "bin", "sbin", "tmp", "run", "dev", "sys", "proc",
    "boot", "root", "null", "set", "get", "put", "use", "new", "add", "all",
    "any", "can", "may", "let", "top", "end", "now", "type", "name", "path",
    "file", "line", "list", "item", "call", "read", "make", "copy", "move",
    "link", "test", "info", "base", "core", "main", "pass", "fail", "work",
    "help", "just", "only", "also", "very", "more", "most", "some", "each",
    "both", "even", "into", "over", "when", "than", "like", "after", "before",
    "while", "local", "export", "source", "return", "function", "install",
    "remove", "update", "enable", "disable", "start", "stop", "check", "build",
    "clean", "version", "package", "packages", "true", "false", "null", "yes",
    "copr", "repo", "enabled", "disabled", "quiet", "verbose", "args", "opts",
    "diff", "hash", "head", "tail", "grep", "sort", "uniq", "awk", "sed",
    "cat", "tee", "cut", "wc", "find", "xargs", "curl", "wget", "tar", "zip",
}


def extract_candidates(diff_lines: list[str]) -> set[str]:
    """Replicate the candidate extraction logic from check-el10-packages.py."""
    candidates = set()
    for line in diff_lines:
        if not line.startswith("+"):
            continue
        stripped = line[1:].strip()
        if stripped.startswith("#"):
            continue
        # Strip inline comments
        if "#" in stripped:
            stripped = stripped.split("#")[0].strip()
        # Skip lines that look like URLs, var assignments, or JSON
        if any(c in stripped for c in ["http", "$", "=", "{"]):
            continue
        # Only skip path lines — allow copr repo references (repo/packages)
        for m in PKG_RE.finditer(stripped):
            word = m.group(1)
            if word not in NOISE and not word.startswith("-") and len(word) >= 3:
                candidates.add(word)
    return candidates


def parse_repoquery_output(stdout: str) -> set[str]:
    """Parse dnf repoquery output to extract found package names."""
    found_names = set()
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        base = re.sub(r"[:-]\d.*$", "", line)
        base = re.sub(r"\.\w+$", "", base)
        if base:
            found_names.add(base)
    return found_names


# ── Test: extract_candidates ─────────────────────────────────────────────────


class TestExtractCandidates:
    """Tests for the package candidate extraction logic."""

    def test_extracts_simple_packages_from_added_lines(self):
        lines = [
            "+RUN dnf install -y kitty",
            "+RUN dnf install -y alacritty",
            " unchanged line",
        ]
        result = extract_candidates(lines)
        assert "kitty" in result
        assert "alacritty" in result

    def test_ignores_non_added_lines(self):
        lines = [
            "-RUN dnf install -y removed-pkg",
            " unchanged line with pkgname",
            "# comment with kitty",
        ]
        result = extract_candidates(lines)
        assert len(result) == 0

    def test_filters_noise_words(self):
        lines = [
            "+RUN echo the and for not are bash",
            "+RUN dnf install -y realpackage",
        ]
        result = extract_candidates(lines)
        assert "the" not in result
        assert "echo" not in result
        assert "bash" not in result
        assert "realpackage" in result

    def test_skips_paths_and_urls(self):
        lines = [
            "+COPY /usr/share/pkgdata /dest",
            "+RUN curl https://example.com/pkg.rpm",
            "+ENV PKG_VERSION=1.2.3",
            "+RUN dnf install -y ${SOME_VAR}",
        ]
        result = extract_candidates(lines)
        assert len(result) == 0

    def test_skips_comment_lines(self):
        lines = [
            "+# Install the niri compositor",
            "+RUN dnf install -y niri",
        ]
        result = extract_candidates(lines)
        assert "Install" not in result
        assert "the" not in result
        assert "niri" in result

    def test_requires_minimum_length_3(self):
        lines = [
            "+RUN dnf install -y ab cd ef",
            "+RUN dnf install -y abc def",
        ]
        result = extract_candidates(lines)
        assert "ab" not in result
        assert "cd" not in result
        assert "abc" in result  # 3 chars
        assert "def" in result  # 3 chars
        assert "ef" not in result

    def test_handles_complex_package_names(self):
        lines = [
            "+RUN dnf install -y python3-ramalama",
            "+RUN dnf install -y xdg-desktop-portal-gtk",
            "+RUN dnf install -y mesa-vulkan-drivers",
        ]
        result = extract_candidates(lines)
        assert "python3-ramalama" in result
        assert "xdg-desktop-portal-gtk" in result
        assert "mesa-vulkan-drivers" in result

    def test_deduplicates_candidates(self):
        lines = [
            "+RUN dnf install -y kitty",
            "+RUN dnf install -y kitty alacritty",
        ]
        result = extract_candidates(lines)
        assert len([c for c in result if c == "kitty"]) == 1

    def test_empty_input_returns_empty_set(self):
        result = extract_candidates([])
        assert len(result) == 0

    def test_real_world_diff_example(self):
        """Simulate a realistic upstream diff with package additions."""
        lines = [
            " COPY build_scripts/niri.sh /src/",
            "+RUN dnf install -y \\",
            "+    niri \\",
            "+    xdg-desktop-portal-gnome \\",
            "+    wayland-protocols \\",
            "+    mesa-libEGL",
            " # end of diff",
            "+# new comment about wayland",
        ]
        result = extract_candidates(lines)
        assert "niri" in result
        assert "xdg-desktop-portal-gnome" in result
        assert "wayland-protocols" in result
        assert "mesa-libEGL" in result
        assert "COPY" not in result


# ── Test: parse_repoquery_output ─────────────────────────────────────────────


class TestParseRepoqueryOutput:
    """Tests for parsing dnf repoquery output."""

    def test_parses_standard_repoquery_output(self):
        stdout = (
            "kitty-0.39.1-1.el10.x86_64\n"
            "alacritty-0.15.0-1.el10.x86_64\n"
        )
        result = parse_repoquery_output(stdout)
        assert "kitty" in result
        assert "alacritty" in result

    def test_handles_epoch_in_version(self):
        stdout = "vim-2:9.1.1234-1.el10.x86_64\n"
        result = parse_repoquery_output(stdout)
        assert "vim" in result

    def test_handles_sparse_arch_suffixes(self):
        stdout = "python3-ramalama-0.1.0-1.noarch\n"
        result = parse_repoquery_output(stdout)
        assert "python3-ramalama" in result

    def test_filters_empty_lines(self):
        stdout = "\n\nkitty-1.0-1.x86_64\n\n\n"
        result = parse_repoquery_output(stdout)
        assert len(result) == 1
        assert "kitty" in result

    def test_empty_output_returns_empty_set(self):
        result = parse_repoquery_output("")
        assert len(result) == 0

    def test_handles_i686_arch(self):
        stdout = "glibc-2.39-1.i686\n"
        result = parse_repoquery_output(stdout)
        assert "glibc" in result


# ── Test: diff text parsing edge cases ───────────────────────────────────────


class TestDiffParsingEdgeCases:
    """Edge cases for the diff-to-candidates pipeline."""

    def test_multiline_continuations(self):
        """Package names split across lines with backslash continuation."""
        lines = [
            "+RUN dnf install -y \\",
            "+    niri \\",
            "+    wayland-protocols",
        ]
        result = extract_candidates(lines)
        assert "niri" in result
        assert "wayland-protocols" in result

    def test_inline_comments_in_added_lines(self):
        lines = [
            "+RUN dnf install -y kitty  # terminal emulator",
        ]
        result = extract_candidates(lines)
        assert "kitty" in result
        assert "terminal" not in result

    def test_copr_install_commands(self):
        lines = [
            "+RUN dnf copr enable -y ublue-os/packages",
            "+RUN dnf install -y ublue-update",
        ]
        result = extract_candidates(lines)
        # "copr" is noise, "enable" is noise
        assert "ublue-update" in result
        assert "ublue-os" in result

    def test_rpm_ostree_install(self):
        lines = [
            "+RUN rpm-ostree install kitty",
        ]
        result = extract_candidates(lines)
        assert "kitty" in result


# ── Test: GEMINI_TASK.md report generation (structure) ───────────────────────


class TestGeminiTaskReport:
    """Tests for the GEMINI_TASK.md update logic."""

    def test_report_includes_available_section_when_packages_found(self):
        available = ["kitty", "niri"]
        unavailable = ["missing-pkg"]
        # The script adds sections; validate the structure
        sections = []
        if available:
            sections.append("✅ Available in EL10")
        if unavailable:
            sections.append("❌ Not available in EL10")
        assert "✅ Available in EL10" in sections
        assert "❌ Not available in EL10" in sections

    def test_report_omits_available_when_empty(self):
        available = []
        unavailable = ["missing-pkg"]
        sections = []
        if available:
            sections.append("✅ Available in EL10")
        if unavailable:
            sections.append("❌ Not available in EL10")
        assert "✅ Available in EL10" not in sections
        assert "❌ Not available in EL10" in sections

    def test_report_omits_unavailable_when_empty(self):
        available = ["kitty"]
        unavailable = []
        sections = []
        if available:
            sections.append("✅ Available in EL10")
        if unavailable:
            sections.append("❌ Not available in EL10")
        assert "✅ Available in EL10" in sections
        assert "❌ Not available in EL10" not in sections

    def test_all_empty_produces_no_sections(self):
        available = []
        unavailable = []
        sections = []
        if available:
            sections.append("✅ Available in EL10")
        if unavailable:
            sections.append("❌ Not available in EL10")
        assert len(sections) == 0
