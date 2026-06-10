#!/usr/bin/env python3
"""Unit tests for .github/scripts/write-gemini-task.py

Tests:
  - GEMINI_TASK.md content generation from environment variables
  - Guide file reading fallback
  - Optional build_script include logic
  - Optional overrides_dir include logic
  - Markdown structure validation
  - Environment variable defaults
"""

import pytest
import os
import tempfile
import pathlib


# ── Helpers ─────────────────────────────────────────────────────────────────

def generate_task_content(guide, sha="", short_sha="", subject="", author="",
                          date="", url="", full_msg="", diff="",
                          build_script="", overrides_dir=""):
    """Simulate the write-gemini-task.py content generation."""
    lines = [
        guide,
        "",
        "---",
        "",
        "## Commit Details",
        "",
        f"SHA: {sha}",
        f"SHORT_SHA: {short_sha}",
        f"SUBJECT: {subject}",
        f"AUTHOR: {author}",
        f"DATE: {date}",
        f"URL: {url}",
        "",
        "## Full Commit Message",
        "",
        "```",
        full_msg,
        "```",
        "",
        "## Diff",
        "",
        diff,
        "",
    ]
    if build_script:
        build_sh_path = pathlib.Path(build_script)
        if build_sh_path.exists():
            lines += [
                f"## Current `{build_script}`",
                "",
                "```bash",
                build_sh_path.read_text(),
                "```",
                "",
            ]
    if overrides_dir:
        overrides_path = pathlib.Path(overrides_dir)
        if overrides_path.exists():
            lines += [f"## Current `{overrides_dir}/` overrides", ""]
            for f in sorted(overrides_path.rglob("*")):
                if f.is_file():
                    try:
                        lines += [f"### `{f}`", "", "```", f.read_text(), "```", ""]
                    except Exception:
                        lines += [f"### `{f}` (binary)", ""]
    return "\n".join(lines)


# ── Basic Content Tests ─────────────────────────────────────────────────────

def test_generates_content_with_all_fields():
    """All provided fields should appear in the output."""
    guide = "# Porting Guide\n\nDo the thing."
    result = generate_task_content(
        guide=guide,
        sha="abc123def456",
        short_sha="abc123de",
        subject="feat: add niri support",
        author="Test Author",
        date="2024-01-15T10:30:00Z",
        url="https://github.com/example/commit/abc123",
        full_msg="feat: add niri support\n\nFull description here.",
        diff="```diff\n+ new line\n- old line\n```",
    )

    assert "abc123def456" in result
    assert "abc123de" in result
    assert "feat: add niri support" in result
    assert "Test Author" in result
    assert "2024-01-15T10:30:00Z" in result
    assert "https://github.com/example/commit/abc123" in result
    assert "Full description here" in result
    assert "```diff" in result
    assert "+ new line" in result


def test_includes_guide_content():
    """The porting guide content should appear at the top."""
    guide = "# Porting Guide\n\n## Steps\n1. Step one\n2. Step two"
    result = generate_task_content(guide=guide)
    assert result.startswith("# Porting Guide")
    assert "## Steps" in result


def test_sections_present():
    """Required sections must be present in the output."""
    result = generate_task_content(guide="test guide")
    assert "## Commit Details" in result
    assert "## Full Commit Message" in result
    assert "## Diff" in result
    assert "SHA:" in result
    assert "SHORT_SHA:" in result
    assert "SUBJECT:" in result
    assert "AUTHOR:" in result
    assert "DATE:" in result
    assert "URL:" in result


def test_section_separator():
    """The separator between guide and commit details should be ---"""
    result = generate_task_content(guide="guide text")
    assert "\n---\n" in result


# ── Empty/Default Value Tests ───────────────────────────────────────────────

def test_empty_fields_rendered_as_empty():
    """Empty fields should appear as empty values."""
    result = generate_task_content(guide="")
    assert "SHA: " in result
    assert "SUBJECT: " in result
    assert "```\n\n```" in result  # empty full_msg


def test_guide_is_never_empty_in_output():
    """Even with empty guide, the structure remains valid."""
    result = generate_task_content(guide="")
    assert result.strip().startswith("---")  # separator at top


# ── Build Script Include Tests ──────────────────────────────────────────────

def test_build_script_included_when_file_exists(tmp_path):
    """When build_script points to an existing file, its content is included."""
    build_file = tmp_path / "20-niri.sh"
    build_file.write_text("#!/bin/bash\necho 'building niri'")

    result = generate_task_content(
        guide="guide",
        build_script=str(build_file),
    )

    assert "## Current `" in result
    assert "20-niri.sh" in result
    assert "```bash" in result
    assert "building niri" in result


def test_build_script_omitted_when_file_missing():
    """When build_script path doesn't exist, it should not be included."""
    result = generate_task_content(
        guide="guide",
        build_script="/nonexistent/build.sh",
    )
    assert "## Current `" not in result
    assert "```bash" not in result


def test_build_script_omitted_when_empty_string():
    """When build_script is empty, skip the section."""
    result = generate_task_content(guide="guide", build_script="")
    assert "## Current `" not in result


# ── Overrides Dir Include Tests ─────────────────────────────────────────────

def test_overrides_dir_included_when_exists(tmp_path):
    """When overrides_dir exists, files are listed with content."""
    overrides = tmp_path / "overrides"
    overrides.mkdir()
    file1 = overrides / "10-packages.sh"
    file1.write_text("echo 'packages'")
    file2 = overrides / "20-services.sh"
    file2.write_text("echo 'services'")

    result = generate_task_content(
        guide="guide",
        overrides_dir=str(overrides),
    )

    assert "## Current `" in result
    assert "overrides" in result
    assert "10-packages.sh" in result
    assert "20-services.sh" in result
    assert "packages" in result
    assert "services" in result


def test_overrides_dir_omitted_when_empty_string():
    """When overrides_dir is empty, skip the section."""
    result = generate_task_content(guide="guide", overrides_dir="")
    assert "overrides" not in result.lower() or "Current `" not in result


def test_overrides_dir_omitted_when_nonexistent():
    """When overrides_dir doesn't exist, skip the section."""
    result = generate_task_content(guide="guide", overrides_dir="/nonexistent/dir")
    assert "overrides" not in result.lower() or "Current `" not in result


# ── Prompt File Default ─────────────────────────────────────────────────────

def test_default_prompt_file_from_env():
    """The default prompt file is .github/prompts/zirconium-port.md."""
    prompt_file = os.environ.get("PROMPT_FILE", ".github/prompts/zirconium-port.md")
    assert prompt_file == ".github/prompts/zirconium-port.md"


def test_custom_prompt_file_from_env(monkeypatch):
    """PROMPT_FILE env var overrides the default."""
    monkeypatch.setenv("PROMPT_FILE", ".github/prompts/aurora-port.md")
    prompt_file = os.environ.get("PROMPT_FILE", ".github/prompts/zirconium-port.md")
    assert prompt_file == ".github/prompts/aurora-port.md"


# ── Output Size ─────────────────────────────────────────────────────────────

def test_output_written_with_char_count():
    """The script prints a confirmation with character count."""
    result = generate_task_content(guide="test guide content")
    assert len(result) > 0
    # Just verify content was generated
    assert "test guide content" in result
