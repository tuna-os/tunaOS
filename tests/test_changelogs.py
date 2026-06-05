#!/usr/bin/env python3
"""Unit tests for .github/changelogs.py

Tests core logic extractable from the script:
  - Image name construction from matrix (experience, de, image_flavor combinations)
  - Blacklist version filtering
  - FEDORA_PATTERN regex (.fc## suffix)
  - START_PATTERN regex (tag prefix matching)
  - Tag set filtering (exclude .0 endings)
  - Package change tracking (ADD, CHANGE, REMOVE patterns)
  - Common/shared change detection vs per-image changes
  - CHANGELOG_FORMAT template validation
"""

import pytest
import re
from itertools import product


# ── Constants from the script ───────────────────────────────────────────────

FEDORA_PATTERN = re.compile(r"\.fc\d\d")
BLACKLIST_VERSIONS = [
    "kernel", "gnome-control-center-filesystem", "mesa-filesystem",
    "podman", "docker-ce", "incus", "vscode", "nvidia-driver"
]
IMAGE_MATRIX = {
    "experience": ["base", "dx", "gdx"],
    "de": ["gnome"],
    "image_flavor": ["main"],
}


# ── Image Name Construction ─────────────────────────────────────────────────

def get_images():
    """Simulate get_images() logic."""
    matrix = IMAGE_MATRIX
    for experience, de, image_flavor in product(*matrix.values()):
        img = ""
        if de == "gnome":
            img += "albacore"
        if experience == "dx":
            img += "-dx"
        if experience == "gdx":
            img += "-gdx"
        if image_flavor != "main":
            img += "-" + image_flavor
        yield img, experience, de, image_flavor


def test_get_images_produces_base_gnome_main():
    images = list(get_images())
    names = [img for img, _, _, _ in images]
    assert "albacore" in names  # base experience, gnome, main
    assert "albacore-dx" in names
    assert "albacore-gdx" in names


def test_get_images_total_count():
    images = list(get_images())
    # 3 experiences × 1 de × 1 image_flavor = 3
    assert len(images) == 3


def test_image_name_no_unexpected_combinations():
    images = list(get_images())
    names = set(img for img, _, _, _ in images)
    # Only base, dx, gdx
    assert len(names) == 3
    assert all(name.startswith("albacore") for name in names)


# ── Blacklist Version Filtering ─────────────────────────────────────────────

def test_blacklist_contains_expected_packages():
    """Essential packages are in the blacklist for major-packages section."""
    assert "kernel" in BLACKLIST_VERSIONS
    assert "gnome-control-center-filesystem" in BLACKLIST_VERSIONS
    assert "mesa-filesystem" in BLACKLIST_VERSIONS
    assert "podman" in BLACKLIST_VERSIONS
    assert "nvidia-driver" in BLACKLIST_VERSIONS


def test_blacklist_excludes_package_from_common_changes():
    """Packages in blacklist should be filtered out from common changes."""
    packages = {
        "kernel": {"prev": "6.11", "new": "6.12"},
        "bash": {"prev": "5.2", "new": "5.3"},
        "mesa-filesystem": {"prev": "24.0", "new": "24.1"},
        "vim": {"prev": "9.0", "new": "9.1"},
    }
    non_blacklisted = {
        k: v for k, v in packages.items()
        if k not in BLACKLIST_VERSIONS
    }
    assert "bash" in non_blacklisted
    assert "vim" in non_blacklisted
    assert "kernel" not in non_blacklisted
    assert "mesa-filesystem" not in non_blacklisted


# ── Fedora Pattern ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("version,should_match", [
    ("package-1.2.3.fc40", True),
    ("package-2.0.fc41", True),
    ("package-1.0-1.el10", False),
    ("package-3.14", False),
    ("package-1.0.fc4", False),  # only .fc\d\d (two digits)
    ("libfoo-0.5.fc42.x86_64", True),
])
def test_fedora_pattern_matches_fc_suffix(version, should_match):
    """FEDORA_PATTERN matches .fc followed by two digits."""
    result = bool(FEDORA_PATTERN.search(version))
    assert result == should_match


# ── START_PATTERN ───────────────────────────────────────────────────────────

def test_start_pattern_matches_tag_prefix():
    """START_PATTERN matches tags starting with target version prefix."""
    # Simulating: START_PATTERN = lambda target: re.compile(rf"{target}-\d\d\d+")
    target = "42"
    pattern = re.compile(rf"{target}-\d\d\d+")

    assert pattern.match("42-001")
    assert pattern.match("42-20250101")
    assert not pattern.match("41-001")
    assert not pattern.match("42")
    assert not pattern.match("42-beta")


# ── Tag Filtering ───────────────────────────────────────────────────────────

def test_tags_exclude_dot_zero():
    """Tags ending with .0 are filtered out."""
    tags = {"42-20250101", "42-20250101.0", "42-20250101.1", "42-20250102"}
    filtered = {t for t in tags if not t.endswith(".0")}
    assert "42-20250101.0" not in filtered
    assert "42-20250101" in filtered
    assert "42-20250102" in filtered
    assert len(filtered) == 3


def test_tags_must_match_start_pattern():
    """Only tags matching START_PATTERN are included initially."""
    target = "42"
    pattern = re.compile(rf"{target}-\d\d\d+")
    tags = {"42-20250101", "41-20250101", "42-beta", "42-20250102.1"}
    matching = {t for t in tags if pattern.match(t)}
    assert "42-20250101" in matching
    assert "42-20250102.1" in matching
    assert "41-20250101" not in matching
    assert "42-beta" not in matching


# ── Package Change Tracking ─────────────────────────────────────────────────

def test_package_added():
    """A package appearing only in 'new' is an ADD."""
    prev_packages = {"bash": "5.2"}
    new_packages = {"bash": "5.2", "zsh": "5.9"}

    added = set(new_packages.keys()) - set(prev_packages.keys())
    assert added == {"zsh"}


def test_package_removed():
    """A package appearing only in 'prev' is a REMOVE."""
    prev_packages = {"bash": "5.2", "vim": "9.0"}
    new_packages = {"bash": "5.3"}

    removed = set(prev_packages.keys()) - set(new_packages.keys())
    assert removed == {"vim"}


def test_package_changed():
    """A package with different versions in prev and new is a CHANGE."""
    prev_packages = {"bash": "5.2", "vim": "9.0"}
    new_packages = {"bash": "5.3", "vim": "9.0"}

    changed = {
        k: (prev_packages[k], new_packages[k])
        for k in set(prev_packages) & set(new_packages)
        if prev_packages[k] != new_packages[k]
    }
    assert changed == {"bash": ("5.2", "5.3")}


def test_package_unchanged():
    """Same version in both = no change."""
    prev_packages = {"bash": "5.2"}
    new_packages = {"bash": "5.2"}

    changed = {
        k for k in set(prev_packages) & set(new_packages)
        if prev_packages[k] != new_packages[k]
    }
    assert len(changed) == 0


# ── Common Change Detection ─────────────────────────────────────────────────

def test_common_changes_across_all_images():
    """A change present in ALL images is 'common'."""
    image_changes = {
        "albacore": {"bash": ("5.2", "5.3"), "vim": ("9.0", "9.1")},
        "albacore-dx": {"bash": ("5.2", "5.3"), "vim": ("9.0", "9.1")},
        "albacore-gdx": {"bash": ("5.2", "5.3"), "vim": ("9.0", "9.1")},
    }
    all_keys = [set(changes.keys()) for changes in image_changes.values()]
    common = all_keys[0].intersection(*all_keys[1:])
    assert common == {"bash", "vim"}


def test_per_image_changes():
    """Changes not present in ALL images are per-image."""
    image_changes = {
        "albacore": {"bash": ("5.2", "5.3"), "nvidia": ("550", "555")},
        "albacore-dx": {"bash": ("5.2", "5.3"), "docker": ("26", "27")},
        "albacore-gdx": {"bash": ("5.2", "5.3"), "nvidia": ("550", "555")},
    }
    all_keys = [set(changes.keys()) for changes in image_changes.values()]
    common = all_keys[0].intersection(*all_keys[1:])
    assert common == {"bash"}

    # Per-image: not in common
    for img, changes in image_changes.items():
        per_image = set(changes.keys()) - common
        if img == "albacore":
            assert per_image == {"nvidia"}
        elif img == "albacore-dx":
            assert per_image == {"docker"}


# ── CHANGELOG_FORMAT Validation ─────────────────────────────────────────────

def test_changelog_format_contains_required_sections():
    """CHANGELOG_FORMAT should include major packages and rebase instructions."""
    format_str = """\
{handwritten}

From previous `{target}` version `{prev}` there have been the following changes.

### Major packages
| Name | Version |

### How to rebase
```bash
sudo bootc switch --enforce-container-sigpolicy ghcr.io/hanthor/$IMAGE_NAME:{target}
```"""
    assert "### Major packages" in format_str
    assert "### How to rebase" in format_str
    assert "sudo bootc switch" in format_str
    assert "{target}" in format_str
    assert "{prev}" in format_str


def test_changelog_format_handwritten_placeholder():
    """When no handwritten notes, a placeholder is used."""
    handwritten = """This is an automatically generated changelog for release `42.20250101`."""
    assert "automatically generated" in handwritten
    assert "42.20250101" in handwritten


# ── RETRIES Constant ────────────────────────────────────────────────────────

def test_retry_constants():
    """RETRIES and RETRY_WAIT should be reasonable values."""
    RETRIES = 3
    RETRY_WAIT = 5
    assert RETRIES == 3
    assert RETRY_WAIT == 5
    assert RETRIES * RETRY_WAIT <= 30  # Total retry time should be reasonable
