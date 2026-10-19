"""Behavioral checks for Gentoo binrepo trust gates.

The harness executes the production emerge branch with only its external
commands sandboxed. A trust/configuration failure must stop before emerge; a
valid key and signed binrepo must reach the package install stub.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
INSTALL = ROOT / "build_scripts" / "desktop" / "install-desktop.sh"


@pytest.fixture(scope="module")
def emerge_branch() -> str:
    source = INSTALL.read_text(encoding="utf-8")
    match = re.search(
        r"^# ── Emerge path .*?^# Add a Launchpad PPA",
        source,
        re.MULTILINE | re.DOTALL,
    )
    assert match, "the production emerge branch marker changed"
    branch = match.group(0).rsplit("\n# Add a Launchpad PPA", 1)[0]
    # The branch writes Portage trust files under /etc in the image. Redirect
    # those writes into the per-test sandbox without changing the code under
    # test or allowing a developer test to mutate the host.
    return branch.replace("/etc/portage", "$TEST_ROOT/etc/portage")


def run_emerge_branch(tmp_path: Path, branch: str, **settings: str) -> subprocess.CompletedProcess[str]:
    fakebin = tmp_path / "bin"
    fakebin.mkdir()
    context = tmp_path / "context"
    key = context / "experiences/tuna/tideforge-public.gpg"
    key.parent.mkdir(parents=True)
    key.write_text("fake key\n", encoding="utf-8")
    lock = context / "build_scripts/desktop/gentoo-binhost-version-lock.sh"
    lock.parent.mkdir(parents=True)
    lock.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    lock.chmod(0o755)

    trust = tmp_path / "etc/portage/gnupg"
    trust.mkdir(parents=True)
    (trust / "trustdb.gpg").write_text("fake trustdb\n", encoding="utf-8")
    (trust / "pubring.kbx").write_text("fake keyring\n", encoding="utf-8")
    (fakebin / "yq").write_text(
        """#!/bin/sh
case "$*" in
  *'packages.emerge | type'*) printf '%s\\n' '!!map' ;;
  *'packages.emerge.packages[]'*) printf '%s\\n' '=gui-wm/tuna-desktop-1.0.0_beta1::tunaos' ;;
  *'packages.emerge[]'*) printf '%s\\n' '=gui-wm/tuna-desktop-1.0.0_beta1::tunaos' ;;
  *'source_repositories // [] | length'*) printf '%s\\n' "${TUNAOS_SOURCE_COUNT:-0}" ;;
  *'source_repositories[0].name'*) printf '%s\\n' guru ;;
  *'source_repositories[0].sync_uri'*) printf '%s\\n' https://github.com/gentoo/guru.git ;;
  *'binrepos // [] | length'*) printf '%s\\n' 1 ;;
  *'binrepos[0].name'*) printf '%s\\n' tunaos ;;
  *'binrepos[0].sync_uri'*) printf '%s\\n' https://repo.tunaos.org/gentoo/binpkgs/amd64 ;;
  *'binrepos[0].key'*) printf '%s\\n' /experiences/tuna/tideforge-public.gpg ;;
  *'binrepos[0].fingerprint'*) printf '%s\\n' 4E5CC9F8B3B521793D95266E629BE6EA45188366 ;;
  *'binrepos[0].priority'*) printf '%s\\n' 10 ;;
  *'binrepos[0].verify_signature'*) printf '%s\\n' "${TUNAOS_VERIFY_SIGNATURE:-true}" ;;
  *'emerge_accept_keywords'*) exit 0 ;;
  *) printf '%s\\n' 0 ;;
esac
""",
        encoding="utf-8",
    )
    (fakebin / "yq").chmod(0o755)
    (fakebin / "emaint").write_text(
        "#!/bin/sh\nexit " + ("1" if settings.get("sync_fail") else "0") + "\n",
        encoding="utf-8",
    )
    (fakebin / "gpg").write_text(
        """#!/bin/sh
case "$*" in
  *'--show-keys'*) printf 'fpr:::::::::%s\\n' "${TUNAOS_ACTUAL_FINGERPRINT:-4E5CC9F8B3B521793D95266E629BE6EA45188366}" ;;
  *'--import'*) exit "${TUNAOS_IMPORT_STATUS:-0}" ;;
  *'--quick-lsign-key'*) exit "${TUNAOS_SIGN_STATUS:-0}" ;;
  *'--check-trustdb'*) exit "${TUNAOS_TRUST_STATUS:-0}" ;;
esac
exit 0
""",
        encoding="utf-8",
    )
    (fakebin / "gpg").chmod(0o755)
    (fakebin / "gpgconf").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    (fakebin / "emerge").write_text(
        "#!/bin/sh\nprintf '%s\\n' reached > \"$TUNAOS_EMERGE_MARKER\"\n",
        encoding="utf-8",
    )
    (fakebin / "emerge").chmod(0o755)

    marker = tmp_path / "emerge-called"
    env = {
        "PATH": f"{fakebin}:/usr/bin:/bin",
        "TEST_ROOT": str(tmp_path),
        "TUNAOS_EMERGE_MARKER": str(marker),
        **{key: value for key, value in settings.items() if value is not None},
    }
    harness = f"""set -euo pipefail
_TD_OS=emerge
_TD_DESKTOP=tuna
_TD_CTX={context}
_TD_MANIFEST={tmp_path / 'tuna.yaml'}
YQ={fakebin / 'yq'}
_TD_EMERGE_NODE_TYPE='!!map'
_TD_EMERGE_PKGS=('=gui-wm/tuna-desktop-1.0.0_beta1::tunaos')
getuto() {{ return 0; }}
{branch}
"""
    (tmp_path / "tuna.yaml").write_text("packages: {}\n", encoding="utf-8")
    return subprocess.run(
        ["bash", "-c", harness],
        env=env,
        capture_output=True,
        text=True,
        cwd=ROOT,
        timeout=60,
    )


@pytest.mark.parametrize(
    "settings",
    [
        {"TUNAOS_ACTUAL_FINGERPRINT": "BAD"},
        {"TUNAOS_VERIFY_SIGNATURE": "false"},
        {"TUNAOS_IMPORT_STATUS": "1"},
        {"sync_fail": "1", "TUNAOS_SOURCE_COUNT": "1"},
    ],
    ids=["fingerprint-mismatch", "unsigned-repo", "key-import", "repo-sync"],
)
def test_trust_failures_reject_before_emerge(tmp_path: Path, emerge_branch: str, settings: dict[str, str]):
    result = run_emerge_branch(tmp_path, emerge_branch, **settings)
    assert result.returncode != 0, result.stdout + result.stderr
    assert not (tmp_path / "emerge-called").exists(), result.stdout + result.stderr


def test_valid_signed_binrepo_reaches_emerge(tmp_path: Path, emerge_branch: str):
    result = run_emerge_branch(tmp_path, emerge_branch)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (tmp_path / "emerge-called").read_text(encoding="utf-8").strip() == "reached"
