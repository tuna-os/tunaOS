"""tunaOS#2071: CI workflow steps downloaded unverified mutable yq latest binary.

Multiple GitHub Actions workflow files downloaded mikefarah/yq from
`releases/latest/download/yq_linux_amd64` directly into system binary paths
without an explicit version pin or checksum verification. Because the `latest`
redirect is mutable, upstream asset changes could compromise workflow
runners executing as root. All CI steps now route through the verified
`.github/actions/setup-yq` installer (or verify SHA-256 checksums before installation)
pinned to the repository-aligned `v4.53.3` release.

Falsification: structural -- reverting any workflow's yq download to an unpinned URL
or unverified download fails `test_no_workflow_downloads_latest_yq`,
`test_no_action_downloads_latest_yq`, or `test_no_unverified_yq_downloads`
(which checks each download on its own rather than any `sha256sum` in the same
file). Loosening the setup-yq version guard fails
`test_setup_yq_version_guard_is_exact`.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS_DIR = ROOT / ".github" / "workflows"
ACTIONS_DIR = ROOT / ".github" / "actions"

UNPINNED_YQ = re.compile(r"github\.com/mikefarah/yq/releases/latest/download")
YQ_DOWNLOAD = re.compile(r"(?:https?://)?github\.com/mikefarah/yq/releases/download/[^\s\"']+")


def _get_workflow_files() -> list[Path]:
    return sorted(
        [p for p in WORKFLOWS_DIR.iterdir() if p.suffix in (".yml", ".yaml")]
    )


def _get_action_files() -> list[Path]:
    return sorted(
        [p for p in ACTIONS_DIR.rglob("*") if p.suffix in (".yml", ".yaml")]
    )


def test_no_workflow_downloads_latest_yq():
    offenders = []
    for wf in _get_workflow_files():
        content = wf.read_text(encoding="utf-8")
        matches = UNPINNED_YQ.findall(content)
        if matches:
            offenders.append(f"{wf.name}: {len(matches)} unpinned yq download(s)")

    assert not offenders, (
        f"Found mutable yq latest downloads in workflow files:\n"
        + "\n".join(offenders)
    )


def test_no_action_downloads_latest_yq():
    offenders = []
    for act in _get_action_files():
        content = act.read_text(encoding="utf-8")
        matches = UNPINNED_YQ.findall(content)
        if matches:
            offenders.append(f"{act.name}: {len(matches)} unpinned yq download(s)")

    assert not offenders, (
        f"Found mutable yq latest downloads in action files:\n"
        + "\n".join(offenders)
    )


# How far below a download the matching `sha256sum -c` may sit.
VERIFY_WINDOW = 3
# Destination of a download: `fetch "<url>" <dest>`, `curl ... -o <dest>`, or
# `wget -O <dest>` / `wget -qO <dest>`.
FETCH_DEST = re.compile(r"""fetch\s+["']?\S+?["']?\s+["']?([^\s"']+)""")
CURL_DEST = re.compile(r"""(?:-o|-[a-zA-Z]*O)\s+["']?([^\s"']+)""")


def _is_comment(line: str) -> bool:
    return line.lstrip().startswith("#")


def unverified_yq_downloads(content: str) -> list[int]:
    """Return 1-based line numbers of yq downloads not checksum-verified.

    Each download is checked on its own: its destination file must be passed
    to `sha256sum -c` within VERIFY_WINDOW lines. A `sha256sum` elsewhere in
    the same file (for example for another tool) does not count.
    """
    lines = content.splitlines()
    bad = []
    for idx, line in enumerate(lines):
        if _is_comment(line) or not YQ_DOWNLOAD.search(line):
            continue
        dest_match = FETCH_DEST.search(line) or CURL_DEST.search(line)
        if dest_match is None:
            bad.append(idx + 1)
            continue
        dest = dest_match.group(1)
        # The whole path, not a substring: `$D/yq.backup` must not pass for `$D/yq`.
        dest_token = re.compile(r"(?<![^\s\"'])" + re.escape(dest) + r"(?![^\s\"'])")
        window = lines[idx + 1 : idx + 1 + VERIFY_WINDOW]
        if not any(
            "sha256sum -c" in w and dest_token.search(w) and not _is_comment(w)
            for w in window
        ):
            bad.append(idx + 1)
    return bad


def test_no_unverified_yq_downloads():
    """Every individual yq download must be followed by its own SHA-256 check."""
    offenders = []
    for p in _get_workflow_files() + _get_action_files():
        for lineno in unverified_yq_downloads(p.read_text(encoding="utf-8")):
            offenders.append(
                f"{p.relative_to(ROOT)}:{lineno}: yq download without SHA-256 verification"
            )

    assert not offenders, (
        "Found unverified yq downloads without SHA-256 verification:\n"
        + "\n".join(offenders)
    )


YQ_URL = "https://github.com/mikefarah/yq/releases/download/${YQ_VERSION}/yq_linux_${YQ_ARCH}"


def test_detector_flags_download_whose_check_was_removed():
    """Falsification: another tool's sha256sum in the same file is not enough."""
    content = "\n".join(
        [
            'YQ_SHA256="abc"',
            f'fetch "{YQ_URL}" /tmp/yq',
            "sudo install -m 0755 /tmp/yq /usr/bin/yq",
            'fetch "https://example.invalid/just.tgz" /tmp/just.tgz',
            'echo "${JUST_SHA256}  /tmp/just.tgz" | sha256sum -c -',
        ]
    )
    assert unverified_yq_downloads(content) == [2]


def test_detector_flags_check_of_other_file():
    content = "\n".join(
        [
            f'curl -fsSL -o /tmp/yq "{YQ_URL}"',
            'echo "${SHA}  /tmp/other" | sha256sum -c -',
        ]
    )
    assert unverified_yq_downloads(content) == [1]


def test_detector_flags_check_of_same_prefix_file():
    content = "\n".join(
        [
            f'fetch "{YQ_URL}" "$YQ_TMP/yq"',
            'echo "${SHA}  $YQ_TMP/yq.backup" | sha256sum -c -',
        ]
    )
    assert unverified_yq_downloads(content) == [1]


def test_detector_accepts_verified_download():
    content = "\n".join(
        [
            f'fetch "{YQ_URL}" /tmp/yq',
            'echo "${YQ_SHA256}  /tmp/yq" | sha256sum -c -',
        ]
    )
    assert unverified_yq_downloads(content) == []


def test_detector_flags_commented_out_check():
    content = "\n".join(
        [
            f'fetch "{YQ_URL}" /tmp/yq',
            '# echo "${YQ_SHA256}  /tmp/yq" | sha256sum -c -',
        ]
    )
    assert unverified_yq_downloads(content) == [1]


def test_detector_ignores_commented_download():
    assert unverified_yq_downloads(f"# see {YQ_URL}") == []


@pytest.mark.parametrize("flag", ["-O", "-qO"])
def test_detector_handles_wget_destination(flag):
    download = f'wget {flag} /tmp/yq "{YQ_URL}"'
    verified = "\n".join([download, 'echo "${SHA}  /tmp/yq" | sha256sum -c -'])
    assert unverified_yq_downloads(verified) == []
    assert unverified_yq_downloads(download) == [1]


def _yq_is_pinned_function() -> tuple[str, str]:
    action = (ACTIONS_DIR / "setup-yq" / "action.yml").read_text(encoding="utf-8")
    version = re.search(r'YQ_VERSION="([^"]+)"', action)
    func = re.search(r"^( *)yq_is_pinned\(\) \{\n.*?^\1\}$", action, re.M | re.S)
    assert version and func, "setup-yq must define YQ_VERSION and yq_is_pinned()"
    return f'YQ_VERSION="{version.group(1)}"\n{func.group(0)}', version.group(1)


@pytest.mark.parametrize(
    ("reported", "pinned"),
    [
        ("{v}", True),
        ("{v}0", False),
        ("{v}-rc1", False),
        ("v4.44.1", False),
    ],
)
def test_setup_yq_version_guard_is_exact(tmp_path, reported, pinned):
    """The action may skip the download only for the exact pinned version."""
    func, version = _yq_is_pinned_function()
    fake = tmp_path / "yq"
    fake.write_text(
        "#!/bin/sh\n"
        f"echo 'yq (https://github.com/mikefarah/yq/) version {reported.format(v=version)}'\n"
    )
    fake.chmod(0o755)
    env = {**os.environ, "PATH": f"{tmp_path}{os.pathsep}{os.environ['PATH']}"}
    result = subprocess.run(
        ["bash", "-c", f"{func}\nyq_is_pinned"], env=env, check=False
    )
    assert (result.returncode == 0) is pinned
