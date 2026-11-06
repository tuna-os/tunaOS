"""scripts/r2-dependency-report.py measures from native indexes, not from a typed table.

The parsers run against small real-format fixtures, the scan runs against a
temporary tree, and the registry calls are injected, so nothing here needs a
network.
"""

from __future__ import annotations

import gzip
import importlib.util
import io
import tarfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("r2_report", ROOT / "scripts" / "r2-dependency-report.py")
report = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(report)

PRIMARY = b"""<?xml version="1.0"?>
<metadata xmlns="http://linux.duke.edu/metadata/common" xmlns:rpm="http://linux.duke.edu/metadata/rpm" packages="2">
<package type="rpm"><name>a</name><size package="1000" installed="5" archive="5"/></package>
<package type="rpm"><name>b</name><size package="234" installed="5" archive="5"/></package>
</metadata>"""
REPOMD = b'<repomd><data type="primary"><location href="repodata/abc-primary.xml.gz"/></data></repomd>'


def test_rpm_totals_sum_the_package_sizes_not_the_installed_sizes():
    assert report.rpm_totals(PRIMARY) == (2, 1234)


def test_apt_totals_read_the_size_field_of_each_stanza():
    text = "Package: a\nSize: 10\n\nPackage: b\nSize: 32\n\nPackage: c\nVersion: 1\n"
    assert report.apt_totals(text) == (2, 42)


def test_pacman_totals_use_the_compressed_size_of_each_desc():
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for name, size in (("a-1/desc", 7), ("b-1/desc", 5)):
            data = f"%NAME%\n{name}\n\n%CSIZE%\n{size}\n".encode()
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    assert report.pacman_totals(buffer.getvalue()) == (2, 12)


def test_measure_prefix_follows_repomd_to_primary_and_expands_the_arch():
    asked = []

    def get(url):
        asked.append(url)
        if url.endswith("repomd.xml"):
            return REPOMD
        return gzip.compress(PRIMARY)

    got = report.measure_prefix("hummingbird/20251124-$basearch/", get)
    assert (got["kind"], got["packages"], got["bytes"]) == ("rpm", 2, 1234)
    assert asked[0] == "https://repo.tunaos.org/hummingbird/20251124-x86_64/repodata/repomd.xml"
    assert asked[1].endswith("/repodata/abc-primary.xml.gz")


def test_measure_prefix_kinds():
    assert report.kind("public.gpg") == "key"
    assert report.kind("tideforge/ubuntu/tideforge.gpg") == "key"
    assert report.kind("tideforge/ubuntu/") == "apt"
    assert report.kind("pacman/arch/$arch") == "pacman"
    assert report.kind("xfce/44-x86_64/") == "rpm"
    key = report.measure_prefix("public.gpg", lambda url: b"12345")
    assert (key["kind"], key["packages"], key["bytes"]) == ("key", None, 5)


def test_a_failed_measurement_is_a_visible_row_not_a_silent_gap():
    def get(url):
        raise OSError("boom")

    out = report.render_measurements({"xfce/44-x86_64/": ["x"]}, get)
    assert "ERROR" in out and "boom" in out


def test_scan_names_the_toml_table_or_the_file_and_skips_comments(tmp_path):
    (tmp_path / "build_scripts").mkdir()
    (tmp_path / "tunaos.toml").write_text(
        "# https://repo.tunaos.org/comment-only/\n"
        "[[desktops.a.packages.el10.repos]]\n"
        'baseurl = "https://repo.tunaos.org/one/"\n'
        "[[desktops.b.packages.apt.repos]]\n"
        'uri = "https://repo.tunaos.org/one/"\n'
    )
    (tmp_path / "Containerfile.arch").write_text(
        "printf 'Server = https://repo.tunaos.org/pacman/arch/$arch\\n'\n"
    )
    (tmp_path / "build_scripts" / "x.sh").write_text("# https://repo.tunaos.org/skipped/\n")
    found = report.scan(tmp_path)
    assert found == {
        "one/": [
            "tunaos.toml [desktops.a.packages.el10.repos]",
            "tunaos.toml [desktops.b.packages.apt.repos]",
        ],
        "pacman/arch/$arch": ["Containerfile.arch"],
    }


def test_oci_family_tags_skip_signature_referrer_and_candidate_tags():
    tags = ["gnome50-el10-x86_64", "sha256-" + "a" * 64 + ".sig", "sha256-" + "b" * 64,
            "gnome50-el10-x86_64-candidate-1-1", "hummingbird-aarch64"]

    def get_json(url, token, accept=""):
        if url.endswith("tags/list?n=1000"):
            return {"tags": tags}
        sizes = {"gnome50-el10-x86_64": [5], "hummingbird-aarch64": [19_508_954_174]}
        return {"layers": [{"size": s} for s in sizes[url.rsplit("/", 1)[1]]]}

    rows = report.oci_family_tags(get_json, lambda: "token")
    assert rows == [{"tag": "gnome50-el10-x86_64", "layers": [5]},
                    {"tag": "hummingbird-aarch64", "layers": [19_508_954_174]}]
    assert "19,508,954,174" in report.render_oci(rows)


def test_the_repository_scan_runs_offline(capsys):
    assert report.main(["--offline"]) == 0
    out = capsys.readouterr().out
    assert "hummingbird/20251124-$basearch/" in out and "Measured" not in out


@pytest.mark.parametrize("name", ["xz", "zst"])
def test_unsupported_compression_is_an_error_not_garbage(name):
    if name == "zst":
        with pytest.raises(ValueError):
            report.decompress("primary.xml.zst", b"x")
    else:
        import lzma
        assert report.decompress("p.xml.xz", lzma.compress(b"ok")) == b"ok"


def test_same_count_and_bytes_with_different_packages_have_different_content():
    one = PRIMARY
    other = PRIMARY.replace(b'<name>a</name>', b'<name>a</name><checksum type="sha256" pkgid="YES">aa</checksum>')
    assert report.rpm_totals(one) == report.rpm_totals(other)
    assert report.fingerprint(report.rpm_checksums(one)) != report.fingerprint(report.rpm_checksums(other))
    # Order does not matter, membership does.
    assert report.fingerprint(["b", "a"]) == report.fingerprint(["a", "b"])
    assert report.fingerprint(["a", "b"]) != report.fingerprint(["a", "c"])
    assert report.fingerprint([]) != report.fingerprint(["aa"])


def test_measure_prefix_reports_the_content_fingerprint_of_each_kind():
    primary = PRIMARY.replace(b'<name>a</name>', b'<name>a</name><checksum type="sha256" pkgid="YES">aa</checksum>')

    def get(url):
        return REPOMD if url.endswith("repomd.xml") else gzip.compress(primary)

    assert report.measure_prefix("xfce/44-x86_64/", get)["content"] == report.fingerprint(["aa"])
    text = "Package: a\nSize: 1\nSHA256: " + "1" * 64 + "\n"
    got = report.measure_prefix("tideforge/ubuntu/", lambda url: gzip.compress(text.encode()))
    assert got["content"] == report.fingerprint(["1" * 64])


def test_an_oci_image_index_is_resolved_to_the_layers_of_its_children():
    def get_json(url, token, accept=""):
        if url.endswith("tags/list?n=1000"):
            return {"tags": ["multi", "single"]}
        if url.endswith("/manifests/multi"):
            return {"manifests": [
                {"digest": "sha256:" + "a" * 64, "platform": {"os": "linux", "architecture": "amd64"}},
                {"digest": "sha256:" + "b" * 64, "platform": {"os": "linux", "architecture": "arm64"}}]}
        if url.endswith("a" * 64):
            return {"layers": [{"size": 11}, {"size": 22}]}
        if url.endswith("b" * 64):
            return {"layers": [{"size": 33}]}
        return {"layers": [{"size": 44}]}

    rows = report.oci_family_tags(get_json, lambda: "t")
    assert rows == [
        {"tag": "multi [linux/amd64]", "layers": [11, 22]},
        {"tag": "multi [linux/arm64]", "layers": [33]},
        {"tag": "single", "layers": [44]},
    ]


def test_an_unrecognised_oci_manifest_is_an_error_not_zero_layers():
    def get_json(url, token, accept=""):
        return {"tags": ["odd"]} if url.endswith("tags/list?n=1000") else {"config": {}}

    with pytest.raises(ValueError, match="neither an image manifest nor an image index"):
        report.oci_family_tags(get_json, lambda: "t")
