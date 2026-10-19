"""Exercise xorriso's actual quoted path format without a multi-GB download."""
import importlib.util
from pathlib import Path
import shlex
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("extract_payloads", ROOT / "scripts/extract-iso-payloads.py")
extractor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(extractor)


@pytest.mark.parametrize("path", ["/LiveOS/root.sfs", "/LiveOS/with spaces.squashfs",
                                  "/LiveOS/a'quote.img", "/LiveOS/$(touch evil).sfs"])
def test_quoted_names_are_data(path):
    assert extractor.payload_paths(shlex.quote(path) + "\n") == [path]


@pytest.mark.parametrize("value", ["", "../root.sfs", "'/../root.sfs'", "'//root.sfs'",
                                   "'/root.sfs' extra", "'/root.txt'", "'/a.sfs'\n'/a.sfs'",
                                   "'/bad\npath.sfs'", "'unterminated"])
def test_unexpected_inventory_is_rejected(value):
    with pytest.raises(ValueError):
        extractor.payload_paths(value)


def test_listing_failure_is_not_reported_as_missing_receipt(tmp_path, monkeypatch):
    def fail(*args, **kwargs):
        raise subprocess.CalledProcessError(5, args[0])
    monkeypatch.setattr(extractor.subprocess, "run", fail)
    with pytest.raises(subprocess.CalledProcessError):
        extractor.extract(tmp_path / "test.iso", tmp_path / "out")


@pytest.mark.skipif(not shutil.which("xorriso"), reason="requires xorriso for tiny-media integration")
def test_real_tiny_iso_handles_spaces_and_quotes(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    names = ["with spaces.sfs", "a'quote.squashfs", "$(touch evil).img"]
    for name in names:
        (source / name).write_text(name)
    iso = tmp_path / "tiny.iso"
    subprocess.run(["xorriso", "-as", "mkisofs", "-o", str(iso), str(source)], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    outputs = extractor.extract(iso, tmp_path / "output with spaces")
    assert sorted(Path(path).read_text() for path in outputs) == sorted(names)
    assert not (tmp_path / "evil").exists()


@pytest.mark.skipif(not all(shutil.which(tool) for tool in ("xorriso", "mksquashfs", "unsquashfs")),
                    reason="requires ISO and squashfs tools for tiny receipt integration")
def test_real_embedded_installer_receipt_survives_extraction(tmp_path):
    root = tmp_path / "root"
    info = root / "etc/tunaos/live-installer-info"
    info.parent.mkdir(parents=True)
    receipt = "INSTALLER_APP=org.bootcinstaller.Installer\nINSTALLER_BUNDLE_SHA256=" + "a" * 64 + "\n"
    info.write_text(receipt)
    source = tmp_path / "iso-root"
    source.mkdir()
    squash = source / "with a'quote.squashfs"
    subprocess.run(["mksquashfs", str(root), str(squash), "-noappend", "-processors", "1"],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    iso = tmp_path / "receipt.iso"
    subprocess.run(["xorriso", "-as", "mkisofs", "-o", str(iso), str(source)], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    outputs = extractor.extract(iso, tmp_path / "extracted")
    actual = subprocess.check_output(["unsquashfs", "-cat", outputs[0],
                                      "etc/tunaos/live-installer-info"], text=True)
    assert actual == receipt
