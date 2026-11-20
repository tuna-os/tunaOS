"""99-cleanup.sh must remove the build-time download scratch dir (#4796)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_cleanup_removes_download_scratch_before_lint():
    text = (ROOT / "build_scripts/99-cleanup.sh").read_text()
    rm = text.index("rm -rf /var/tmp/tunaos-downloads")
    assert rm < text.index("\nlint_image\n")
