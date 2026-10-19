"""Native RPM/pacman removal evidence in temporary roots, never host packages.

The wrappers redirect paths only. Package dependencies and signature policy are
unchanged. Locally missing tools skip; a required CI family must fail instead.
These fixtures establish backend behavior, not desktop/image qualification.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tarfile

import pytest

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "build_scripts/lib/fork-removals.sh"
FIXTURES = {"fixture-library": "", "fixture-app": "fixture-library", "fixture-spare": ""}
PAYLOAD_DIRECTORY = "usr/share/tunaos-removal-fixtures"
TOOLS = {"rpm": ("rpm", "rpmbuild"), "pacman": ("pacman",)}


def require_native(family):
    missing = [name for name in TOOLS[family] if not shutil.which(name)]
    reason = f"native {family} needs tools {missing}" if missing else ""
    if not reason and os.geteuid() != 0:
        reason = f"native {family} private-root installation needs container root"
    if reason:
        if os.environ.get("TUNAOS_NATIVE_REMOVAL_REQUIRED") == family:
            pytest.fail(reason)
        pytest.skip(reason)


def require_rpm_distro_key(directory=Path("/etc/pki/rpm-gpg")):
    # The native lane uses AlmaLinux; Fedora developer containers ship the same
    # RPM key-file layout. Read a shipped public key, never fetch or generate one.
    for pattern in ("RPM-GPG-KEY-AlmaLinux*", "RPM-GPG-KEY-fedora*"):
        for path in sorted(directory.glob(pattern)):
            if path.is_file() and b"-----BEGIN PGP PUBLIC KEY BLOCK-----" in path.read_bytes():
                return path
    reason = "native rpm needs a shipped AlmaLinux/Fedora public key"
    if os.environ.get("TUNAOS_NATIVE_REMOVAL_REQUIRED") == "rpm":
        pytest.fail(reason)
    pytest.skip(reason)


def assert_dependency_refusal(result):
    # Native tools can split the summary and dependency detail across streams.
    diagnostic = result.stdout + result.stderr
    assert result.returncode != 0
    assert "dependenc" in diagnostic.lower() and "fixture-app" in diagnostic


def seed_pacman_sync(source, destination):
    # The disposable container has already synchronized verified repository
    # metadata. Retain it in the private root to avoid missing-database warnings.
    assert source.is_dir() and list(source.glob("*.db")), "synchronized pacman metadata is required"
    shutil.copytree(source, destination)


def pacman_archive(path, name, dependency):
    """Build a local fixture archive; pacman itself must accept its metadata."""
    payload = f"{name}\n".encode()
    info = (
        f"pkgname = {name}\npkgbase = {name}\npkgver = 1.0-1\n"
        "pkgdesc = Native removal qualification fixture\n"
        "url = https://example.invalid/\nbuilddate = 0\n"
        "packager = Qualification Fixture\narch = any\nlicense = MIT\n"
        f"size = {len(payload)}\n"
        + (f"depend = {dependency}=1.0-1\n" if dependency else "")
    ).encode()
    with tarfile.open(path, "w:gz") as archive:
        for member, content in ((".PKGINFO", info), (f"{PAYLOAD_DIRECTORY}/{name}", payload)):
            entry = tarfile.TarInfo(member)
            entry.mode = 0o644
            entry.size = len(content)
            archive.addfile(entry, io.BytesIO(content))


class NativeRoot:
    def __init__(self, temporary, family, manager):
        self.temporary = temporary
        self.family = family
        self.manager = manager
        self.root = temporary / "root"
        self.root.mkdir()
        self.bin = temporary / "bin"
        self.bin.mkdir()
        self.commands = {name: str(Path(shutil.which(name)).resolve()) for name in TOOLS[family]}
        self.evidence = {
            "family": family,
            "manager": manager,
            "helper_sha256": hashlib.sha256(HELPER.read_bytes()).hexdigest(),
            "os_release": Path("/etc/os-release").read_text(),
            "commands": [],
            "archives": {},
            "steps": [],
        }
        if family == "rpm":
            self.native = [self.commands["rpm"], "--root", str(self.root), "--dbpath", "/var/lib/rpm"]
        else:
            database = self.root / "var/lib/pacman"
            database.mkdir(parents=True)
            seed_pacman_sync(Path("/var/lib/pacman/sync"), database / "sync")
            self.evidence["sync_metadata_sha256"] = {
                path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                for path in sorted((database / "sync").iterdir()) if path.is_file()
            }
            cache = self.root / "var/cache/pacman/pkg"
            cache.mkdir(parents=True)
            self.native = [
                self.commands["pacman"], "--root", str(self.root),
                "--dbpath", str(database), "--cachedir", str(cache),
                "--logfile", str(self.root / "pacman.log"),
            ]
        wrapper = self.bin / family
        wrapper.write_text(f"#!/bin/sh\nexec {shlex.join(self.native)} \"$@\"\n")
        wrapper.chmod(0o755)

    def run(self, command, *, check=True, env=None, timeout=60):
        result = subprocess.run(command, text=True, capture_output=True, timeout=timeout,
                                env=dict(os.environ, LC_ALL="C") if env is None else env)
        self.evidence["commands"].append({
            "argv": command, "returncode": result.returncode,
            "stdout": result.stdout, "stderr": result.stderr,
        })
        if check:
            assert result.returncode == 0, (
                f"{shlex.join(command)}\n{result.stdout}\n{result.stderr}"
            )
        return result

    def setup(self, packages=None):
        for name, executable in self.commands.items():
            self.run([executable, "--version"])
        archives = []
        if self.family == "rpm":
            self.run([*self.native, "--initdb"])
            top = self.temporary / "rpmbuild"
            for directory in ("BUILD", "BUILDROOT", "RPMS", "SOURCES", "SPECS", "SRPMS"):
                (top / directory).mkdir(parents=True)
            for name, dependency in FIXTURES.items():
                spec = top / "SPECS" / f"{name}.spec"
                spec.write_text(
                    f"Name: {name}\nVersion: 1.0\nRelease: 1\n"
                    "Summary: Native removal qualification fixture\nLicense: MIT\n"
                    "BuildArch: noarch\n"
                    + (f"Requires: {dependency} = 1.0-1\n" if dependency else "")
                    + "\n%description\nLocal fixture with one text payload and no scriptlets.\n"
                    "\n%install\nmkdir -p %{buildroot}/" + PAYLOAD_DIRECTORY + "\n"
                    f"printf '%s\\n' '{name}' > %{{buildroot}}/{PAYLOAD_DIRECTORY}/{name}\n"
                    f"\n%files\n%attr(0644,root,root) /{PAYLOAD_DIRECTORY}/{name}\n"
                )
                self.run([self.commands["rpmbuild"], "--define", f"_topdir {top}",
                          "--define", "_buildhost fixture.invalid", "-bb", str(spec)], timeout=90)
                archive = top / "RPMS" / "noarch" / f"{name}-1.0-1.noarch.rpm"
                assert archive.is_file()
                archives.append(archive)
        else:
            # Read the distro configuration; never weaken LocalFileSigLevel.
            self.evidence["pacman_config"] = Path("/etc/pacman.conf").read_text()
            for name, dependency in FIXTURES.items():
                archive = self.temporary / f"{name}-1.0-1-any.pkg.tar.gz"
                pacman_archive(archive, name, dependency)
                archives.append(archive)
        self.evidence["archives"] = {
            archive.name: hashlib.sha256(archive.read_bytes()).hexdigest() for archive in archives
        }
        self.archives = dict(zip(FIXTURES, archives))
        selected = list(FIXTURES) if packages is None else packages
        if selected:
            self.install(*selected)

    def install(self, *packages):
        assert packages, "install needs fixture names"
        operation = ["--install"] if self.family == "rpm" else ["--upgrade", "--noconfirm"]
        self.run([*self.native, *operation, *(str(self.archives[name]) for name in packages)])

    def snapshot(self):
        if self.family == "rpm":
            output = self.run([*self.native, "-qa", "--queryformat",
                               "%{NAME}\\t%{VERSION}-%{RELEASE}.%{ARCH}\\n"]).stdout
        else:
            result = self.run([*self.native, "-Q"], check=False)
            # pacman returns 1 for an empty local package database.
            assert result.returncode == 0 or (result.returncode == 1 and not result.stdout.strip()
                                              and not result.stderr.strip()), result.stderr
            output = result.stdout
        inventory = dict(line.split() for line in output.splitlines())
        payloads = {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted((self.root / PAYLOAD_DIRECTORY).glob("*")) if path.is_file()
        }
        return {"inventory": inventory, "payloads": payloads}

    def remove(self, packages, *, enabled=True):
        environment = dict(os.environ, LC_ALL="C", PATH=f"{self.bin}:{os.environ['PATH']}")
        environment.pop("TUNAOS_FORK_REMOVAL_QUALIFICATION", None)
        if enabled:
            environment["TUNAOS_FORK_REMOVAL_QUALIFICATION"] = "1"
        before = self.snapshot()
        result = self.run([
            "bash", "-c", 'source "$1"; shift; tunaos_qualify_fork_removals "$@"',
            "native-removal-test", str(HELPER), self.manager, *packages,
        ], check=False, env=environment)
        after = self.snapshot()
        self.evidence["steps"].append({
            "targets": packages, "qualification_enabled": enabled,
            "returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr,
            "before": before, "after": after,
        })
        return result, before, after

    def save(self, suffix=""):
        encoded = json.dumps(self.evidence, indent=2, sort_keys=True) + "\n"
        (self.temporary / "evidence.json").write_text(encoded)
        destination = os.environ.get("TUNAOS_NATIVE_REMOVAL_EVIDENCE")
        if destination:
            target = Path(destination)
            target.mkdir(parents=True, exist_ok=True)
            (target / f"{self.family}-{self.manager}{suffix}.json").write_text(encoded)


@pytest.mark.parametrize("family,manager", [("rpm", "dnf"), ("rpm", "zypper"), ("pacman", "pacman")],
                         ids=["rpm-dnf", "rpm-zypper", "pacman"])
def test_native_exact_removal(tmp_path, family, manager):
    require_native(family)
    native = NativeRoot(tmp_path, family, manager)
    try:
        native.setup()
        original = native.snapshot()
        version = "1.0-1.noarch" if family == "rpm" else "1.0-1"
        assert original["inventory"] == dict.fromkeys(FIXTURES, version)
        assert original["payloads"] == {
            name: hashlib.sha256(f"{name}\n".encode()).hexdigest() for name in FIXTURES
        }
        result, before, after = native.remove(["fixture-spare"], enabled=False)
        assert result.returncode != 0 and "qualification" in result.stderr
        assert before == after == original
        for targets in (["fixture-library"], ["fixture-spare", "fixture-library"]):
            result, before, after = native.remove(targets)
            assert_dependency_refusal(result)
            assert before == after == original
        for targets in (["fixture-missing"], ["fixture-spare", "fixture-missing"]):
            result, before, after = native.remove(targets)
            assert result.returncode != 0
            assert before == after == original
        if family == "rpm":
            for selector in ("fixture-spare-1.0", "fixture-spare.noarch", "fixture-spare-1.0-1.noarch"):
                result, before, after = native.remove([selector])
                assert result.returncode != 0
                assert "exact installed package name" in result.stderr
                assert before == after == original
        result, before, after = native.remove(["fixture-spare"])
        assert result.returncode == 0, result.stderr
        expected = {section: {name: value for name, value in entries.items() if name != "fixture-spare"}
                    for section, entries in original.items()}
        assert before == original and after == expected
        result, before, after = native.remove(["fixture-spare"])
        assert result.returncode != 0 and before == after == expected
        for package in ("fixture-app", "fixture-library"):
            result, before, after = native.remove([package])
            assert result.returncode == 0, result.stderr
            assert after == {section: {name: value for name, value in entries.items() if name != package}
                             for section, entries in before.items()}
        assert native.snapshot() == {"inventory": {}, "payloads": {}}
        native.evidence["passed"] = True
    finally:
        native.save()


def test_missing_native_tools_fail_required_family(monkeypatch):
    monkeypatch.setenv("TUNAOS_NATIVE_REMOVAL_REQUIRED", "rpm")
    monkeypatch.setattr(shutil, "which", lambda _name: None)
    with pytest.raises(pytest.fail.Exception, match="native rpm needs tools"):
        require_native("rpm")


def test_missing_native_tools_skip_developer_run(monkeypatch):
    monkeypatch.delenv("TUNAOS_NATIVE_REMOVAL_REQUIRED", raising=False)
    monkeypatch.setattr(shutil, "which", lambda _name: None)
    with pytest.raises(pytest.skip.Exception, match="native pacman needs tools"):
        require_native("pacman")


def test_required_family_without_container_root_fails(monkeypatch):
    monkeypatch.setenv("TUNAOS_NATIVE_REMOVAL_REQUIRED", "pacman")
    monkeypatch.setattr(shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(os, "geteuid", lambda: 1000)
    with pytest.raises(pytest.fail.Exception, match="container root"):
        require_native("pacman")


def test_local_fixture_archive_declares_dependency_and_exact_payload(tmp_path):
    archive = tmp_path / "fixture-app.pkg.tar.gz"
    pacman_archive(archive, "fixture-app", "fixture-library")
    with tarfile.open(archive) as package:
        assert package.getnames() == [".PKGINFO", f"{PAYLOAD_DIRECTORY}/fixture-app"]
        info = package.extractfile(".PKGINFO").read().decode()
        assert "depend = fixture-library=1.0-1\n" in info
        assert package.extractfile(f"{PAYLOAD_DIRECTORY}/fixture-app").read() == b"fixture-app\n"


@pytest.mark.parametrize("family,manager", [("rpm", "dnf"), ("rpm", "zypper"), ("pacman", "pacman")],
                         ids=["rpm-dnf", "rpm-zypper", "pacman"])
def test_native_protected_inventory(tmp_path, family, manager):
    require_native(family)
    public_key = require_rpm_distro_key() if family == "rpm" else None
    image_digest = os.environ.get("TUNAOS_NATIVE_REMOVAL_IMAGE_ID")
    if not image_digest:
        if os.environ.get("TUNAOS_NATIVE_REMOVAL_REQUIRED") == family:
            pytest.fail("protected native qualification needs the actual container image ID")
        pytest.skip("protected native qualification needs the actual container image ID")
    inventory_helper = HELPER.with_name("fork-removal-inventory.py")
    source_files = {
        str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (HELPER, inventory_helper, Path(__file__))
    }
    source_sha256 = hashlib.sha256(json.dumps(source_files, sort_keys=True).encode()).hexdigest()
    native = NativeRoot(tmp_path, family, manager)
    environment = dict(os.environ, LC_ALL="C", PATH=f"{native.bin}:{os.environ['PATH']}",
                       TUNAOS_FORK_REMOVAL_QUALIFICATION="1")
    identity = ["--manager", manager, "--source-sha256", source_sha256,
                "--image-digest", image_digest]
    base, desktop, receipt = [tmp_path / name for name in ("base.json", "desktop.json", "receipt.json")]
    native.evidence.update({"scope": "protected-inventory", "source_files": source_files,
                            "source_sha256": source_sha256, "image_digest": image_digest})
    try:
        native.setup(packages=[])
        key_records = []
        if public_key is not None:
            # --root and --dbpath scope both import and erasure to this fixture;
            # the host keyring and signature policy are never modified.
            native.run([*native.native, "--import", str(public_key)])
            key_output = native.run([
                *native.native, "-q", "--qf",
                "%{NAME}\\t%{EPOCHNUM}:%{VERSION}-%{RELEASE}\\t%{ARCH}\\n", "gpg-pubkey",
            ]).stdout
            key_records = [dict(zip(("name", "version", "architecture"), line.split("\t")))
                           for line in key_output.splitlines()]
            key_records.sort(key=lambda row: (row["name"], row["version"], row["architecture"]))
            assert key_records
            assert all(row["name"] == "gpg-pubkey" and row["architecture"] == "(none)"
                       for row in key_records)
            native.evidence["rpm_public_key"] = {
                "path": str(public_key), "sha256": hashlib.sha256(public_key.read_bytes()).hexdigest(),
                "records": key_records,
            }
        native.install("fixture-library")
        native.run([sys.executable, str(inventory_helper), "capture", *identity,
                    "--stage", "base", "--output", str(base)], env=environment)
        native.install("fixture-app")
        native.run([sys.executable, str(inventory_helper), "capture", *identity,
                    "--stage", "desktop", "--output", str(desktop)], env=environment)
        native.evidence["baselines"] = {"base": json.loads(base.read_text()),
                                         "desktop": json.loads(desktop.read_text())}
        for stage, names in (("base", ["fixture-library"]),
                             ("desktop", ["fixture-app", "fixture-library"])):
            captured = native.evidence["baselines"][stage]["packages"]
            assert [row["name"] for row in captured if row["name"] != "gpg-pubkey"] == names
            assert [row for row in captured if row["name"] == "gpg-pubkey"] == key_records
        native.install("fixture-spare")
        original = native.snapshot()
        qualify = [sys.executable, str(inventory_helper), "qualify", *identity,
                   "--base", str(base), "--desktop", str(desktop), "--receipt", str(receipt)]
        if public_key is not None:
            result = native.run([*qualify, "--remove", "gpg-pubkey"], env=environment, check=False)
            assert result.returncode != 0 and "protected base/desktop" in result.stderr
            assert native.snapshot() == original and not receipt.exists()
            # A missing key must fail closed before removing any fixture package.
            # Erase only the key records just imported into the temporary DB.
            selectors = native.run([*native.native, "-q", "--qf",
                                    "%{NAME}-%{VERSION}-%{RELEASE}\\n", "gpg-pubkey"]).stdout.splitlines()
            native.run([*native.native, "--erase", "--", *selectors])
            missing_key = native.snapshot()
            assert missing_key == {
                section: {name: value for name, value in entries.items() if name != "gpg-pubkey"}
                for section, entries in original.items()
            }
            result = native.run([*qualify, "--remove", "fixture-spare"], env=environment, check=False)
            assert result.returncode != 0 and "protected baseline inventory drift: gpg-pubkey" in result.stderr
            assert native.snapshot() == missing_key and not receipt.exists()
            native.evidence["rpm_public_key"]["missing_key_refusal"] = result.stderr
            native.run([*native.native, "--import", str(public_key)])
            assert native.snapshot() == original
        for name in ("fixture-library", "fixture-app", "fixture-spare"):
            before = native.snapshot()
            result = native.run([*qualify, "--remove", name], env=environment, check=False)
            after = native.snapshot()
            native.evidence["steps"].append({
                "targets": [name], "returncode": result.returncode, "before": before,
                "after": after, "stdout": result.stdout, "stderr": result.stderr,
            })
            if name != "fixture-spare":
                assert result.returncode != 0
                assert "protected base/desktop" in result.stderr
                assert before == after == original
                assert not receipt.exists()
            else:
                assert result.returncode == 0, result.stderr
                assert after == {
                    section: {package: value for package, value in entries.items() if package != name}
                    for section, entries in original.items()
                }
        outcome = json.loads(receipt.read_text())
        assert outcome["status"] == "qualified-fixture-only"
        assert outcome["removed"] == ["fixture-spare"]
        assert outcome["source_sha256"] == source_sha256 and outcome["image_digest"] == image_digest
        assert outcome["before"] == [
            {"name": name, "version": "0:1.0-1" if family == "rpm" else "1.0-1",
             "architecture": "noarch" if family == "rpm" else None}
            for name in sorted(FIXTURES)
        ] + key_records
        assert outcome["after"] == [row for row in outcome["before"] if row["name"] != "fixture-spare"]
        native.evidence["removal_receipt"] = outcome
        native.evidence["passed"] = True
    finally:
        native.save(suffix="-protected")


def test_rpm_public_key_missing_fails_required_family(tmp_path, monkeypatch):
    monkeypatch.setenv("TUNAOS_NATIVE_REMOVAL_REQUIRED", "rpm")
    with pytest.raises(pytest.fail.Exception, match="shipped AlmaLinux/Fedora public key"):
        require_rpm_distro_key(tmp_path)


def test_rpm_public_key_missing_skips_developer_run(tmp_path, monkeypatch):
    monkeypatch.delenv("TUNAOS_NATIVE_REMOVAL_REQUIRED", raising=False)
    with pytest.raises(pytest.skip.Exception, match="shipped AlmaLinux/Fedora public key"):
        require_rpm_distro_key(tmp_path)


def test_rpm_public_key_uses_shipped_distro_armored_file(tmp_path):
    (tmp_path / "RPM-GPG-KEY-AlmaLinux-invalid").write_text("not a public key\n")
    (tmp_path / "RPM-GPG-KEY-third-party").write_text("-----BEGIN PGP PUBLIC KEY BLOCK-----\n")
    public_key = tmp_path / "RPM-GPG-KEY-fedora-fixture"
    public_key.write_text("-----BEGIN PGP PUBLIC KEY BLOCK-----\n")
    assert require_rpm_distro_key(tmp_path) == public_key


@pytest.mark.parametrize("stdout,stderr", [
    ("", "dependency failure: fixture-app"),
    ("fixture-app needs fixture-library", "could not satisfy dependencies"),
    ("dependency failure: fixture-app", ""),
])
def test_dependency_diagnostic_may_span_streams(stdout, stderr):
    assert_dependency_refusal(subprocess.CompletedProcess([], 1, stdout, stderr))


@pytest.mark.parametrize("status,stdout,stderr", [
    (0, "fixture-app", "dependency failure"),
    (1, "", "dependency failure"),
    (1, "fixture-app", "unrelated failure"),
])
def test_dependency_diagnostic_requires_real_failure_and_dependent(status, stdout, stderr):
    with pytest.raises(AssertionError):
        assert_dependency_refusal(subprocess.CompletedProcess([], status, stdout, stderr))


def test_private_pacman_sync_preserves_metadata_bytes(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "core.db").write_bytes(b"fixture metadata")
    (source / "core.db.sig").write_bytes(b"fixture signature")
    target = tmp_path / "target"
    seed_pacman_sync(source, target)
    assert {p.name: p.read_bytes() for p in target.iterdir()} == {
        p.name: p.read_bytes() for p in source.iterdir()
    }


def test_private_pacman_sync_requires_existing_metadata(tmp_path):
    target = tmp_path / "target"
    with pytest.raises(AssertionError, match="synchronized pacman metadata"):
        seed_pacman_sync(tmp_path / "missing", target)
    assert not target.exists()
