"""Promotion must not depend on unrelated runner apt repositories.

The 2026-09-09 matrix had four images reach Promote and fail before any
promotion work began.  Two skipjack cells and bonito hit a transient Google
Chrome ``Hash Sum mismatch``; marlin hit a Microsoft repository 403.  All four
failures came from the generic ``apt-get update`` used only to install Ubuntu's
skopeo package.

GitHub-hosted runners enable those vendor repositories for preinstalled tools,
but they are not inputs to image promotion.  Keep this final matrix step scoped
to Ubuntu's repository and retain apt's bounded retry for the repository it
actually needs.
"""

from pathlib import Path

import pytest


yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/reusable-build-image.yml"
STEP = "Install skopeo"


@pytest.fixture(scope="module")
def install_step():
    workflow = yaml.safe_load(WORKFLOW.read_text())
    steps = workflow["jobs"]["tag-image"]["steps"]
    return next(step for step in steps if step.get("name") == STEP)


def test_skopeo_uses_only_the_ubuntu_runner_source(install_step):
    body = install_step["run"]
    assert "Dir::Etc::sourcelist=/etc/apt/sources.list.d/ubuntu.sources" in body
    assert 'Dir::Etc::sourceparts=-' in body


def test_every_apt_call_uses_the_scoped_options(install_step):
    commands = [
        line.strip()
        for line in install_step["run"].splitlines()
        if "apt-get" in line and not line.lstrip().startswith("#")
    ]
    assert commands, "the promotion job no longer installs skopeo"
    assert all('"${APT_OPTIONS[@]}"' in command for command in commands), commands


def test_the_required_ubuntu_repository_is_retried(install_step):
    assert "Acquire::Retries=5" in install_step["run"]
