"""The installer probe label gives the same evidence as the layer scan (tunaOS#4905).

installer-medium/evidence/probe_facts.py reads the probe's inputs from an
image root directory and writes them as the value of the label
`org.tunaos.installer.probe`. scan-images.py reads that label from the image
config and reads the layers only when the label is absent or not usable.

These tests hold four contracts:

- a root directory and the layers of the same tree give the same facts;
- every record in the checked-in images.json survives the label round trip;
- a label that is absent, of another schema, or hostile sends the cell to
  the layer scan and writes nothing outside the probe tree;
- a full run takes a labelled cell from the config and another cell from
  its layers, and --layer-scan ignores the label.

No test uses the network. The registry calls are replaced by fixtures.
"""

import concurrent.futures
import importlib.util
import io
import json
import os
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "installer-medium/evidence/images.json"
SCRIPT = ROOT / "installer-medium/evidence/probe_facts.py"


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


scan = module("scan_images_label", ROOT / "installer-medium/evidence/scan-images.py")
facts_module = scan.probe_facts
RECORDS = {r["cell"]: r for r in json.loads(EVIDENCE.read_text())["images"]}
MEASURED = [r for r in RECORDS.values() if "facts" in r]


def fedora_tree(root: Path) -> Path:
    """An image root with each kind of tracked path, and paths the probe ignores."""
    for rel in (
        "usr/lib/bootupd/updates/EFI.json",
        "usr/lib/efi/grub2/1:2.12-66.fc44/EFI/fedora/grubx64.efi",
        "usr/lib/efi/shim/15.8-3/EFI/fedora/shimx64.efi",
        "usr/lib/systemd/boot/efi/systemd-bootx64.efi",
        "usr/lib/systemd/boot/efi/systemd-bootx64.efi.signed",
        "usr/lib/systemd/boot/efi/linuxx64.efi.stub",
        "usr/lib/modules/7.0.4-200.fc44.x86_64/vmlinuz",
        "usr/lib/modules/readme.txt",
        "usr/bin/bash",
    ):
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_bytes(b"x")
    (root / "usr/lib/modules/6.99.0-1.fc44.x86_64").mkdir()
    (root / "usr/lib/ostree").mkdir(parents=True)
    (root / "usr/lib/ostree/prepare-root.conf").write_text("[composefs]\nenabled = no\n")
    (root / "usr/lib/os-release").write_text('NAME="Fedora Linux"\nID=fedora\nVERSION_ID=44\nVARIANT_ID=bonito\n')
    (root / "etc").mkdir()
    (root / "etc/os-release").symlink_to("../usr/lib/os-release")
    return root


def layer_of(root: Path) -> io.BytesIO:
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w") as archive:
        archive.add(root, arcname=".")
    stream.seek(0)
    return stream


def config_with(value):
    return {"config": {"Labels": {"containers.bootc": "1", facts_module.LABEL: value}}}


def test_a_root_directory_and_its_layer_give_the_same_facts(tmp_path):
    root = fedora_tree(tmp_path / "root")
    from_layers = scan.facts_of(scan.merge([scan.tar_rows(layer_of(root))]))
    assert facts_module.facts_from_rootfs(root) == from_layers
    assert from_layers == {
        "files": [
            "usr/lib/bootupd/updates/EFI.json",
            "usr/lib/efi/grub2/1:2.12-66.fc44/EFI/fedora/grubx64.efi",
            "usr/lib/efi/shim/15.8-3/EFI/fedora/shimx64.efi",
            "usr/lib/systemd/boot/efi/systemd-bootx64.efi",
            "usr/lib/systemd/boot/efi/systemd-bootx64.efi.signed",
        ],
        "kernels": ["6.99.0-1.fc44.x86_64", "7.0.4-200.fc44.x86_64"],
        "prepare_root_conf": "[composefs]\nenabled = no\n",
        "os_release": "ID=fedora\nVERSION_ID=44\nVARIANT_ID=bonito\n",
    }


def test_os_release_is_read_through_the_etc_link(tmp_path):
    root = fedora_tree(tmp_path / "root")
    (root / "usr/lib/os-release").unlink()
    (root / "etc/os-release").unlink()
    (root / "etc/os-release").write_text("ID=debian\n")
    assert facts_module.facts_from_rootfs(root)["os_release"] == "ID=debian\n"
    assert scan.facts_of(scan.merge([scan.tar_rows(layer_of(root))]))["os_release"] == "ID=debian\n"


def test_a_link_out_of_the_tree_is_not_followed(tmp_path):
    outside = tmp_path / "host-os-release"
    outside.write_text("ID=hostdistro\n")
    root = fedora_tree(tmp_path / "root")
    (root / "usr/lib/os-release").unlink()
    (root / "etc/os-release").unlink()
    (root / "etc/os-release").symlink_to(outside)
    assert "os_release" not in facts_module.facts_from_rootfs(root)


@pytest.mark.parametrize("record", MEASURED, ids=lambda r: r["cell"])
def test_every_recorded_image_survives_the_label_round_trip(tmp_path, record):
    facts = record["facts"]
    assert facts_module.facts_from_rootfs(facts_module.build_tree(facts, tmp_path)) == facts
    value = facts_module.encode_label(facts)
    assert len(value) < 1024
    assert facts_module.decode_label(value) == (facts, None)
    fresh = {"cell": record["cell"]}
    assert scan.from_label(fresh, config_with(value)) is None
    assert fresh["facts"] == facts
    assert list(fresh["facts"]) == list(facts)
    assert fresh["facts_from"] == "label"
    assert fresh.get("probe") == record.get("probe")


def test_an_image_with_no_label_goes_to_the_layer_scan():
    record = {"cell": "bonito:gnome"}
    assert scan.from_label(record, {"config": {"Labels": {"containers.bootc": "1"}}}) == (
        "no org.tunaos.installer.probe label"
    )
    assert scan.from_label(record, {"config": {}}) == "no org.tunaos.installer.probe label"
    # The build clears an inherited label with an empty value.
    assert scan.from_label(record, config_with("")) == "no org.tunaos.installer.probe label"
    assert record == {"cell": "bonito:gnome"}


def hostile_labels():
    good = RECORDS["bonito:gnome"]["facts"]

    def label(schema=facts_module.LABEL_SCHEMA, **changes):
        return json.dumps({"schema": schema, "facts": {**good, **changes}})

    return {
        "unknown schema": (label(schema=2), "label schema 2 is not schema 1"),
        "schema as text": (label(schema="1"), "label has no schema number"),
        "not JSON": ("{schema: 1", "label is not JSON"),
        "a list": ("[1]", "label has no schema number"),
        "too long": (label(prepare_root_conf="x" * (20 << 10)), "the limit is"),
        "path leaves the tree": (
            label(files=["usr/lib/efi/grub2/../../../../../../tmp/grubx64.efi"]),
            "is not a tracked path",
        ),
        "absolute path": (label(files=["/usr/lib/bootupd/updates/EFI.json"]), "is not a tracked path"),
        "untracked path": (label(files=["usr/bin/bash"]), "is not a tracked path"),
        "kernel with a slash": (label(kernels=["../../../tmp/owned"]), "is not a kernel release"),
        "shell in os-release": (label(os_release='ID=fedora\nID_LIKE="$(touch /tmp/owned)"\n'), "is not a plain"),
        "extra os-release key": (label(os_release="ID=fedora\nPATH=/tmp\n"), "is not a plain"),
        "unsorted files": (label(files=sorted(good["files"], reverse=True)), "sorted and unique"),
        "extra fact": (label(bootc="1.5"), "expected only the fields"),
        "extra field": (json.dumps({"schema": 1, "facts": good, "probe": {}}), "expected the fields schema and facts"),
        "files missing": (json.dumps({"schema": 1, "facts": {"kernels": []}}), "expected a list"),
    }


@pytest.mark.parametrize("case", hostile_labels().items(), ids=lambda item: item[0])
def test_a_label_that_is_not_usable_goes_to_the_layer_scan(case, monkeypatch):
    _, (value, reason) = case
    built = []
    monkeypatch.setattr(scan, "run_probe", lambda facts: built.append(facts) or ({}, None))
    record = {"cell": "bonito:gnome"}
    assert reason in scan.from_label(record, config_with(value))
    assert record == {"cell": "bonito:gnome"}
    # The label was refused before a tree was built or the probe ran.
    assert built == []


def test_facts_the_probe_cannot_classify_go_to_the_layer_scan():
    record = {"cell": "bonito:gnome"}
    value = facts_module.encode_label({"files": [], "kernels": []})
    assert "probe cannot classify the label facts" in scan.from_label(record, config_with(value))
    assert record == {"cell": "bonito:gnome"}


def test_a_config_that_cannot_be_read_goes_to_the_layer_scan(monkeypatch):
    def fail(*_):
        raise subprocess.CalledProcessError(22, "curl")

    monkeypatch.setattr(scan, "read_config", fail)
    assert scan.label_job(({"cell": "x:gnome"}, "ghcr.io", "tuna-os/x", "sha256:" + "0" * 64)).startswith(
        "config not readable"
    )
    assert scan.label_job(({"cell": "x:gnome"}, "ghcr.io", "tuna-os/x", None)) == "image manifest names no config"


class Threads(concurrent.futures.ThreadPoolExecutor):
    """Stands in for the process pool, so the fixtures below reach the workers."""


def run_scan(tmp_path, monkeypatch, *extra):
    """A full run on two cells: bonito:gnome carries the label, albacore:gnome does not."""
    labelled, plain = RECORDS["bonito:gnome"], RECORDS["albacore:gnome"]
    root = facts_module.build_tree(plain["facts"], tmp_path / "albacore-root")
    rows = scan.tar_rows(layer_of(root))
    layer_reads, config_reads = [], []

    def plan(cell, ref, arch, today):
        record = {"cell": cell, "image": ref, "read": today, "digest": RECORDS[cell]["digest"], "platform": "linux/amd64"}
        return record, "ghcr.io", ref.split("/", 1)[1].split(":")[0], [{"digest": f"sha256:{cell}"}], f"config:{cell}"

    def read_config(registry, repo, digest):
        config_reads.append(digest)
        if digest == "config:bonito:gnome":
            return config_with(facts_module.encode_label(labelled["facts"]))
        return {"config": {"Labels": {"containers.bootc": "1"}}}

    def read_layer(registry, repo, layer, cache):
        layer_reads.append(layer["digest"])
        if layer["digest"] == "sha256:albacore:gnome":
            return rows
        return scan.tar_rows(layer_of(facts_module.build_tree(labelled["facts"], tmp_path / "bonito-root")))

    monkeypatch.setattr(scan, "plan", plan)
    monkeypatch.setattr(scan, "read_config", read_config)
    monkeypatch.setattr(scan, "read_layer", read_layer)
    monkeypatch.setattr(scan.concurrent.futures, "ProcessPoolExecutor", Threads)
    out = tmp_path / "images.json"
    assert scan.main(["--cell", "bonito:gnome", "--cell", "albacore:gnome", "--out", str(out),
                      "--cache", str(tmp_path / "cache"), *extra]) == 0
    return {r["cell"]: r for r in json.loads(out.read_text())["images"]}, layer_reads, config_reads


def test_a_run_reads_the_label_and_scans_only_the_unlabelled_cell(tmp_path, monkeypatch):
    records, layer_reads, config_reads = run_scan(tmp_path, monkeypatch)
    assert sorted(config_reads) == ["config:albacore:gnome", "config:bonito:gnome"]
    assert layer_reads == ["sha256:albacore:gnome"]
    assert records["bonito:gnome"]["facts_from"] == "label"
    assert "facts_from" not in records["albacore:gnome"]
    for cell in ("bonito:gnome", "albacore:gnome"):
        for key in ("facts", "probe", "digest", "platform"):
            assert records[cell][key] == RECORDS[cell][key], (cell, key)


def test_layer_scan_flag_ignores_the_label(tmp_path, monkeypatch):
    records, layer_reads, config_reads = run_scan(tmp_path, monkeypatch, "--layer-scan")
    assert config_reads == []
    assert sorted(layer_reads) == ["sha256:albacore:gnome", "sha256:bonito:gnome"]
    assert "facts_from" not in records["bonito:gnome"]
    assert records["bonito:gnome"]["facts"] == RECORDS["bonito:gnome"]["facts"]


def test_the_resolver_reads_a_label_record_like_a_scan_record():
    medium = module("c", ROOT / "scripts/lib/tunaos_config.py").installer_medium_policy()
    record = {**RECORDS["bonito:gnome"], "facts_from": "label"}
    assert medium._measured(record) == medium._measured(RECORDS["bonito:gnome"])
    assert medium._os_words(record) == {"fedora"}


def cli(*args):
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True)


def test_the_build_script_prints_one_label_argument(tmp_path):
    root = fedora_tree(tmp_path / "root")
    done = cli(str(root))
    assert done.returncode == 0, done.stderr
    name, _, value = done.stdout.rstrip("\n").partition("=")
    assert name == "org.tunaos.installer.probe"
    assert "\n" not in value
    assert facts_module.decode_label(value) == (facts_module.facts_from_rootfs(root), None)
    assert "bootloader=grub2 composeFsBackend=false filesystem=btrfs" in done.stderr
    assert json.loads(cli(str(root), "--facts").stdout) == facts_module.facts_from_rootfs(root)


def test_the_build_script_prints_no_label_for_an_image_it_cannot_classify(tmp_path):
    root = tmp_path / "root"
    (root / "usr/lib").mkdir(parents=True)
    (root / "usr/lib/os-release").write_text("ID=fedora\n")
    done = cli(str(root))
    assert (done.returncode, done.stdout) == (1, "")
    assert "the probe cannot classify the image" in done.stderr


def test_the_build_script_prints_no_label_for_facts_over_a_limit(tmp_path):
    root = fedora_tree(tmp_path / "root")
    (root / "usr/lib/os-release").write_text('ID=fedora\nID_LIKE="$(id)"\n')
    done = cli(str(root))
    assert (done.returncode, done.stdout) == (1, "")
    assert "no label: facts.os_release" in done.stderr


def test_the_build_script_refuses_a_path_that_is_not_an_image_root(tmp_path):
    done = cli(str(tmp_path))
    assert (done.returncode, done.stdout) == (1, "")
    assert "is not an image root" in done.stderr
    assert cli().returncode == 2
    assert os.listdir(tmp_path) == []
