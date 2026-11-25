"""Secure Boot policy for the installer medium (tunaOS#4955).

Falsification: a medium that ships an unsigned loader, an unsigned UKI, a key
bundle without the Microsoft certificates, an unsigned or swapped `.auth`
file, or a changed tunaOS certificate fails here, before CI builds a medium.

Every signature in this file comes from a throwaway key that openssl
generates inside the pytest temp dir. No real key is read.
"""

from __future__ import annotations

import datetime
import hashlib
import importlib.util
import os
import shutil
import struct
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SB_DIR = ROOT / "installer-medium/secure-boot"
spec = importlib.util.spec_from_file_location("medium_secureboot", SB_DIR / "secureboot.py")
sb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sb)

TOOLS = ("openssl", "sbsign", "sbverify", "sbvarsign", "sbsiglist")
# The certificate the owner generated on 2026-11-25. sha256 of the DER form.
TUNAOS_SHA256 = "d26e134487fc8f99430e416b3fbd8faeef4bcdfca109b1397e29a7b31b3c482c"
ATTR = "NON_VOLATILE,RUNTIME_ACCESS,BOOTSERVICE_ACCESS,TIME_BASED_AUTHENTICATED_WRITE_ACCESS"


def make_pe(sections: dict[str, bytes]) -> bytes:
    """A minimal PE32+ image that sbsign accepts."""
    align = 0x200
    count = len(sections)
    header_size = -(-(0x40 + 4 + 20 + 240 + 40 * count) // align) * align
    body, rows, offset, address = b"", b"", header_size, 0x1000
    for name, data in sections.items():
        raw = data + b"\0" * (-len(data) % align)
        rows += name.encode()[:8].ljust(8, b"\0")
        rows += struct.pack(
            "<IIIIIIHHI", len(data), address, len(raw), offset, 0, 0, 0, 0, 0x40000040
        )
        body += raw
        offset += len(raw)
        address += -(-len(raw) // 0x1000) * 0x1000
    dos = b"MZ" + b"\0" * 0x3A + struct.pack("<I", 0x40)
    coff = struct.pack("<HHIIIHH", 0x8664, count, 0, 0, 0, 240, 0x0022)
    optional = struct.pack("<HBBIIIII", 0x20B, 1, 0, 0, 0, 0, 0x1000, 0x1000)
    optional += struct.pack(
        "<QIIHHHHHHIIIIHHQQQQII",
        0x400000,
        0x1000,
        align,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        address,
        header_size,
        0,
        10,
        0,
        0,
        0,
        0,
        0,
        0,
        16,
    )
    optional += b"\0" * 128
    return (dos + b"PE\0\0" + coff + optional + rows).ljust(header_size, b"\0") + body


def run(*argv, **kwargs):
    return subprocess.run(
        [str(arg) for arg in argv], capture_output=True, text=True, check=False, **kwargs
    )


class Pki:
    """Throwaway keys, fake Microsoft certificates and signed fixtures."""

    def __init__(self, tmp: Path):
        self.tmp = tmp
        self.keys = tmp / "keys"
        self.keys.mkdir()
        # The tuna certificate has the profile of the real one: a self-signed
        # leaf, CA:FALSE, EKU codeSigning. sbverify and sbvarsign must accept it.
        leaf = (
            "-addext",
            "basicConstraints=critical,CA:FALSE",
            "-addext",
            "extendedKeyUsage=codeSigning",
        )
        for name, subject in (
            ("tuna", "Throwaway tunaOS test key"),
            ("msuefi", "Fake Microsoft UEFI CA 2099"),
            ("mskek", "Fake Microsoft KEK CA 2099"),
            ("distro", "Fake Distro Secure Boot CA"),
            ("other", "Some other key"),
        ):
            done = run(
                "openssl", "req", "-new", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "3",
                "-subj", f"/CN={subject}/", "-keyout", self.keys / f"{name}.key", "-out", self.keys / f"{name}.pem",
                *(leaf if name == "tuna" else ()),
            )  # fmt: skip
            assert done.returncode == 0, done.stderr
        self.certs = tmp / "certs"
        (self.certs / "microsoft").mkdir(parents=True)
        shutil.copy(self.keys / "tuna.pem", self.certs / "tunaos-sb.crt")
        self.tuna_der = self.der("tuna")
        (self.certs / "tunaos-sb.cer").write_bytes(self.tuna_der)
        rows = ""
        for name, variable, subject in (
            ("mskek", "KEK", "Fake Microsoft KEK CA 2099"),
            ("msuefi", "db", "Fake Microsoft UEFI CA 2099"),
        ):
            shutil.copy(self.keys / f"{name}.pem", self.certs / "microsoft" / f"{name}.pem")
            digest = hashlib.sha256(self.der(name)).hexdigest()
            rows += (
                f'[[microsoft]]\nfile = "microsoft/{name}.pem"\nvariable = "{variable}"\n'
                f'subject_cn = "{subject}"\nsha256 = "{digest}"\nurl = "test"\n\n'
            )
        real = sb.load_manifest()["owners"]
        (self.certs / "manifest.toml").write_text(
            f'schema_version = 1\n[owners]\nmicrosoft = "{real["microsoft"]}"\ntunaos = "{real["tunaos"]}"\n\n{rows}'
        )

    def der(self, name: str) -> bytes:
        return sb.pem_to_der((self.keys / f"{name}.pem").read_text())

    def pe(self, path: Path, signer: str | None, sections: dict[str, bytes] | None = None) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        raw = path.with_name(path.name + ".unsigned")
        raw.write_bytes(make_pe(sections or {".text": b"\xc3" * 64}))
        if signer is None:
            raw.rename(path)
            return path
        done = run(
            "sbsign",
            "--key",
            self.keys / f"{signer}.key",
            "--cert",
            self.keys / f"{signer}.pem",
            "--output",
            path,
            raw,
        )
        assert done.returncode == 0, done.stderr
        raw.unlink()
        return path

    def shim(self, path: Path, signer: str = "msuefi", vendor: str = "distro") -> Path:
        cert = self.der(vendor)
        section = struct.pack("<IIII", len(cert), 0, 16, 16 + len(cert)) + cert
        return self.pe(path, signer, {".text": b"\xc3" * 64, ".vendor_": section})

    def auth_dir(
        self, out: Path, signer: str = "tuna", esl: dict[str, bytes] | None = None
    ) -> Path:
        out.mkdir(parents=True, exist_ok=True)
        lists = esl or sb.key_bundle_esl(self.tuna_der, self.certs)
        for name, blob in lists.items():
            (out / f"{name}.esl").write_bytes(blob)
            done = run(
                "sbvarsign", "--attr", ATTR, "--key", self.keys / f"{signer}.key", "--cert", self.keys / f"{signer}.pem",
                "--output", out / f"{name}.auth", name, out / f"{name}.esl",
            )  # fmt: skip
            assert done.returncode == 0, done.stderr
        return out

    def sources(self, base: Path, loader_signer: str | None = "tuna") -> dict[str, Path]:
        auth = self.auth_dir(base / "auth")
        return {
            "shim": self.shim(base / "shim/shimx64.efi"),
            "mokmanager": self.pe(base / "shim/mmx64.efi", "distro"),
            "loader": self.pe(base / "systemd-bootx64.efi.signed", loader_signer),
            "cert": self.certs / "tunaos-sb.cer",
            **{f"{name}.auth": auth / f"{name}.auth" for name in sb.VARIABLES},
        }

    def distro_esp(
        self, esp: Path, kernel_signer: str | None = "distro", loader_signer: str | None = "distro"
    ) -> Path:
        self.shim(esp / "EFI/BOOT/BOOTX64.EFI")
        self.pe(esp / "EFI/BOOT/grubx64.efi", loader_signer)
        self.pe(esp / "EFI/Linux/vmlinuz", kernel_signer)
        entries = esp / "loader/entries"
        entries.mkdir(parents=True)
        (entries / "os.conf").write_text(
            sb.type1_entry("OS", "/EFI/Linux/vmlinuz", ["/EFI/Linux/initrd"], "ro quiet")
        )
        return esp


@pytest.fixture(scope="module")
def pki(tmp_path_factory):
    missing = [tool for tool in TOOLS if not shutil.which(tool)]
    if missing:
        # No skip: test.yml installs sbsigntool, and a silent skip would be a
        # gate that never runs. Locally: apt install sbsigntool.
        pytest.fail(f"Secure Boot tests need {missing} (apt install sbsigntool)")
    return Pki(tmp_path_factory.mktemp("sb-pki"))


# --- committed public certificates ---------------------------------------------


def test_committed_tunaos_certificate_is_pinned_and_not_near_expiry():
    manifest = sb.load_manifest()["tunaos"]
    der = (SB_DIR / "certs" / manifest["der"]).read_bytes()
    pem = (SB_DIR / "certs" / manifest["pem"]).read_text()
    assert hashlib.sha256(der).hexdigest() == TUNAOS_SHA256 == manifest["sha256"]
    assert sb.pem_to_der(pem) == der, "the PEM and DER files hold different certificates"
    not_after = datetime.date.fromisoformat(manifest["not_after"])
    assert (not_after - datetime.date.today()).days > manifest["min_days_left"], (
        "rotate the Secure Boot key"
    )
    if shutil.which("openssl"):
        text = run(
            "openssl",
            "x509",
            "-inform",
            "DER",
            "-in",
            SB_DIR / "certs" / manifest["der"],
            "-noout",
            "-subject",
            "-enddate",
        ).stdout
        assert manifest["subject_cn"] in text
        assert str(not_after.year) in text


def test_no_private_key_is_committed():
    for path in SB_DIR.rglob("*"):
        if path.is_file():
            assert b"PRIVATE KEY" not in path.read_bytes().replace(b"<PRIVATE KEY>", b""), path


def test_microsoft_certificates_match_their_pins():
    rows = sb.microsoft_certs()
    names = {row["subject_cn"] for row in rows}
    # KEK for dbx updates; db for Windows, shim and option ROMs.
    assert {"Microsoft Corporation KEK CA 2011", "Microsoft Corporation KEK 2K CA 2023"} <= names
    assert {
        "Microsoft Windows Production PCA 2011", "Windows UEFI CA 2023", "Microsoft Corporation UEFI CA 2011",
        "Microsoft UEFI CA 2023", "Microsoft Option ROM UEFI CA 2023",
    } <= names  # fmt: skip


def test_real_key_bundle_holds_tunaos_and_every_microsoft_certificate():
    der = (SB_DIR / "certs/tunaos-sb.cer").read_bytes()
    bundle = sb.key_bundle_esl(der)
    assert sb.esl_certs(bundle["PK"]) == [der]
    kek = [row["der"] for row in sb.microsoft_certs() if row["variable"] == "KEK"]
    db = [row["der"] for row in sb.microsoft_certs() if row["variable"] == "db"]
    assert sb.esl_certs(bundle["KEK"]) == [der, *kek] and len(kek) == 2
    assert sb.esl_certs(bundle["db"]) == [der, *db] and len(db) == 5


def test_bundle_refuses_a_missing_or_swapped_microsoft_certificate(pki, tmp_path):
    certs = tmp_path / "certs"
    shutil.copytree(pki.certs, certs)
    (certs / "microsoft/mskek.pem").unlink()
    with pytest.raises(sb.SecureBootError, match="missing"):
        sb.key_bundle_esl(pki.tuna_der, certs)
    shutil.copy(pki.keys / "other.pem", certs / "microsoft/mskek.pem")
    with pytest.raises(sb.SecureBootError, match="sha256 differs"):
        sb.key_bundle_esl(pki.tuna_der, certs)


def test_esl_equals_sbsiglist_output(pki, tmp_path):
    owner = sb.load_manifest()["owners"]["tunaos"]
    (tmp_path / "c.der").write_bytes(pki.tuna_der)
    done = run(
        "sbsiglist",
        "--owner",
        owner,
        "--type",
        "x509",
        "--output",
        tmp_path / "c.esl",
        tmp_path / "c.der",
    )
    assert done.returncode == 0, done.stderr
    assert sb.esl([(owner, pki.tuna_der)]) == (tmp_path / "c.esl").read_bytes()


# --- distro-chain -----------------------------------------------------------------


def test_distro_chain_accepts_a_fully_distro_signed_medium(pki, tmp_path):
    assert sb.check_distro_chain([pki.distro_esp(tmp_path / "esp")], certs_dir=pki.certs) == []


def test_distro_chain_refuses_an_unsigned_or_foreign_loader(pki, tmp_path):
    for index, signer in enumerate((None, "tuna")):
        esp = pki.distro_esp(tmp_path / f"esp{index}", loader_signer=signer)
        problems = sb.check_distro_chain([esp], certs_dir=pki.certs)
        assert any(
            "grubx64.efi: binary is not signed by the distro" in line for line in problems
        ), problems


def test_distro_chain_refuses_an_unsigned_uki(pki, tmp_path):
    esp = pki.distro_esp(tmp_path / "esp")
    pki.pe(esp / "EFI/Linux/tunaos.efi", None, {".text": b"\xc3" * 64, ".linux": b"kernel"})
    problems = sb.check_distro_chain([esp], certs_dir=pki.certs)
    assert problems == [
        "EFI/Linux/tunaos.efi: UKI is not signed by the distro (shim vendor certificate)"
    ]
    # A UKI we signed is no better: this mode has no tunaOS key to trust it.
    pki.pe(esp / "EFI/Linux/tunaos.efi", "tuna", {".text": b"\xc3" * 64, ".linux": b"kernel"})
    assert sb.check_distro_chain([esp], certs_dir=pki.certs) == problems


def test_distro_chain_refuses_a_kernel_under_boot_that_the_distro_did_not_sign(pki, tmp_path):
    esp = pki.distro_esp(tmp_path / "esp")
    boot = tmp_path / "boot"
    pki.pe(boot / "vmlinuz-1", "other")
    (boot / "loader/entries").mkdir(parents=True)
    (boot / "loader/entries/live.conf").write_text("title Live\nlinux /vmlinuz-1\noptions ro\n")
    problems = sb.check_distro_chain([esp, boot], certs_dir=pki.certs)
    assert problems == ["vmlinuz-1: binary is not signed by the distro (shim vendor certificate)"]


def test_distro_chain_finds_a_kernel_that_the_entry_names_with_a_boot_prefix(pki, tmp_path):
    # ostree entries on a root that holds /boot say `linux /boot/ostree/...`.
    esp = pki.distro_esp(tmp_path / "esp")
    boot = tmp_path / "root/boot"
    pki.pe(boot / "ostree/default-abc/vmlinuz-6.12", "distro")
    (boot / "loader/entries").mkdir(parents=True)
    (boot / "loader/entries/ostree-1.conf").write_text(
        "title OS\nlinux /boot/ostree/default-abc/vmlinuz-6.12\noptions ro\n"
    )
    assert sb.check_distro_chain([esp, boot], certs_dir=pki.certs) == []
    pki.pe(boot / "ostree/default-abc/vmlinuz-6.12", None)
    assert sb.check_distro_chain([esp, boot], certs_dir=pki.certs) == [
        "ostree/default-abc/vmlinuz-6.12: binary is not signed by the distro (shim vendor certificate)"
    ]


def test_throwaway_tunaos_certificate_has_the_profile_of_the_real_one(pki):
    def profile(path, form):
        text = run(
            "openssl",
            "x509",
            "-inform",
            form,
            "-in",
            path,
            "-noout",
            "-ext",
            "basicConstraints,extendedKeyUsage",
        ).stdout
        return "CA:FALSE" in text, "Code Signing" in text

    assert profile(pki.keys / "tuna.pem", "PEM") == (True, True)
    assert profile(SB_DIR / "certs/tunaos-sb.cer", "DER") == (True, True)


def test_distro_chain_refuses_a_shim_microsoft_did_not_sign(pki, tmp_path):
    esp = pki.distro_esp(tmp_path / "esp")
    pki.shim(esp / "EFI/BOOT/BOOTX64.EFI", signer="other")
    assert "EFI/BOOT/BOOTX64.EFI: no Microsoft UEFI CA signature" in sb.check_distro_chain(
        [esp], certs_dir=pki.certs
    )


def test_distro_chain_refuses_enrolment_material_and_wrong_pin(pki, tmp_path):
    esp = pki.distro_esp(tmp_path / "esp")
    (esp / "loader/keys/auto").mkdir(parents=True)
    (esp / "tunaos-secure-boot.cer").write_bytes(pki.tuna_der)
    problems = sb.check_distro_chain([esp], certs_dir=pki.certs, pin_sha256=("00" * 32,))
    assert "loader/keys present: distro-chain enrols no key" in problems
    assert "tunaos-secure-boot.cer: distro-chain ships no certificate to enrol" in problems
    assert "shim vendor certificate is not the pinned distro certificate" in problems
    pin = hashlib.sha256(pki.der("distro")).hexdigest()
    assert not any(
        "pinned" in line
        for line in sb.check_distro_chain([esp], certs_dir=pki.certs, pin_sha256=(pin,))
    )


def test_distro_chain_reports_a_missing_entry_target_and_missing_loader(pki, tmp_path):
    esp = pki.distro_esp(tmp_path / "esp")
    (esp / "EFI/Linux/vmlinuz").unlink()
    (esp / "EFI/BOOT/grubx64.efi").unlink()
    problems = sb.check_distro_chain([esp], certs_dir=pki.certs)
    assert "os.conf: linux target missing: /EFI/Linux/vmlinuz" in problems
    assert any("no grubx64.efi next to shim" in line for line in problems)


def test_entry_command_writes_type1_only_for_a_distro_signed_kernel(pki, tmp_path):
    esp = pki.distro_esp(tmp_path / "esp")
    base = [
        "--certs-dir",
        str(pki.certs),
        "entry",
        "--esp",
        str(esp),
        "--name",
        "live",
        "--title",
        "Live",
        "--options",
        "ro tunaos.live",
    ]
    assert sb.main([*base, "--linux", "/EFI/Linux/vmlinuz", "--initrd", "/EFI/Linux/initrd"]) == 0
    text = (esp / "loader/entries/live.conf").read_text()
    assert (
        text
        == "title Live\nlinux /EFI/Linux/vmlinuz\ninitrd /EFI/Linux/initrd\noptions ro tunaos.live\n"
    )
    pki.pe(esp / "EFI/Linux/own", "tuna")
    assert sb.main([*base, "--name", "own", "--linux", "/EFI/Linux/own"]) == 1
    assert not (esp / "loader/entries/own.conf").exists()
    with pytest.raises(sb.SecureBootError):
        sb.type1_entry("UKI", "/EFI/Linux/tunaos.efi", [], "ro")


# --- tunaos-key -------------------------------------------------------------------


def test_tunaos_key_stages_shim_mokmanager_certificate_and_bundle(pki, tmp_path):
    esp = tmp_path / "esp"
    pki.pe(esp / "EFI/Linux/tunaos.efi", "tuna", {".text": b"\xc3" * 64, ".linux": b"kernel"})
    (esp / "loader").mkdir()
    (esp / "loader/loader.conf").write_text("timeout 5\nsecure-boot-enroll force\n")
    sources = pki.sources(tmp_path / "src")
    sb.stage_tunaos_key(esp, sources, pki.tuna_der, certs_dir=pki.certs, log=lambda _line: None)
    for role, target in sb.tunaos_key_plan():
        assert (esp / target).read_bytes() == sources[role].read_bytes(), target
    # MokManager reads DER only and its picker opens at the ESP root.
    assert (esp / "tunaos-secure-boot.cer").read_bytes() == pki.tuna_der
    # shim starts grubx64.efi: that name must be our signed systemd-boot.
    assert sb.signed_by(esp / "EFI/BOOT/grubx64.efi", [pki.tuna_der])
    # systemd-boot enrols by itself only from the directory named `auto`.
    assert sorted(path.name for path in (esp / "loader/keys/auto").iterdir()) == [
        "KEK.auth",
        "PK.auth",
        "db.auth",
    ]
    assert (esp / "loader/loader.conf").read_text() == "timeout 5\nsecure-boot-enroll if-safe\n"
    for name in sb.VARIABLES:
        signed, payload = sb.auth_payload((esp / f"loader/keys/auto/{name}.auth").read_bytes())
        assert signed
        assert pki.tuna_der in sb.esl_certs(payload)
    for name in ("KEK", "db"):
        _, payload = sb.auth_payload((esp / f"loader/keys/auto/{name}.auth").read_bytes())
        assert len(sb.esl_certs(payload)) == 2, "the Microsoft certificate is missing"


def test_tunaos_key_dry_run_writes_nothing(pki, tmp_path):
    esp = tmp_path / "esp"
    esp.mkdir()
    lines = []
    sb.stage_tunaos_key(
        esp,
        pki.sources(tmp_path / "src"),
        pki.tuna_der,
        dry_run=True,
        certs_dir=pki.certs,
        log=lines.append,
    )
    assert list(esp.iterdir()) == []
    assert any("-> loader/keys/auto/PK.auth" in line for line in lines)
    assert lines[-1] == "secure-boot: loader/loader.conf secure-boot-enroll if-safe"


def test_tunaos_key_refuses_an_unsigned_loader_and_an_unsigned_uki(pki, tmp_path):
    esp = tmp_path / "esp"
    pki.pe(esp / "EFI/Linux/tunaos.efi", None, {".text": b"\xc3" * 64, ".linux": b"kernel"})
    pki.pe(esp / "EFI/Linux/medium-live/boot.efi.d/live.addon.efi", "other")
    with pytest.raises(sb.SecureBootError) as error:
        sb.stage_tunaos_key(
            esp,
            pki.sources(tmp_path / "src", loader_signer=None),
            pki.tuna_der,
            certs_dir=pki.certs,
        )
    text = str(error.value)
    assert "loader: systemd-boot is not signed by the tunaOS certificate" in text
    assert "EFI/Linux/tunaos.efi: UKI is not signed by the tunaOS certificate" in text
    assert "live.addon.efi: binary is not signed by the tunaOS certificate" in text
    assert not (esp / "EFI/BOOT").exists(), "a refused medium must stay untouched"


def test_tunaos_key_refuses_a_bundle_without_microsoft_certificates(pki, tmp_path):
    sources = pki.sources(tmp_path / "src")
    owner = sb.load_manifest()["owners"]["tunaos"]
    own_only = {name: sb.esl([(owner, pki.tuna_der)]) for name in sb.VARIABLES}
    auth = pki.auth_dir(tmp_path / "own-only", esl=own_only)
    sources.update({f"{name}.auth": auth / f"{name}.auth" for name in sb.VARIABLES})
    problems = sb.check_tunaos_key_inputs(sources, pki.tuna_der, pki.certs)
    assert problems == [
        "KEK.auth: payload differs from the public key bundle (Microsoft certificates?)",
        "db.auth: payload differs from the public key bundle (Microsoft certificates?)",
    ]


def test_tunaos_key_refuses_an_unsigned_auth_file(pki, tmp_path):
    sources = pki.sources(tmp_path / "src")
    payload = sb.key_bundle_esl(pki.tuna_der, pki.certs)["PK"]
    # EFI_TIME, then a descriptor of 24 bytes: header and type GUID, no signature.
    unsigned = tmp_path / "PK.auth"
    unsigned.write_bytes(
        b"\0" * 16 + struct.pack("<IHH", 24, 0x0200, 0x0EF1) + b"\0" * 16 + payload
    )
    sources["PK.auth"] = unsigned
    assert sb.check_tunaos_key_inputs(sources, pki.tuna_der, pki.certs) == [
        "PK.auth: no signature; CI must sign it (ci-sign.sh auth)"
    ]


def test_tunaos_key_refuses_a_shim_or_mokmanager_from_the_wrong_signer(pki, tmp_path):
    sources = pki.sources(tmp_path / "src")
    pki.shim(sources["shim"], signer="other")
    pki.pe(sources["mokmanager"], "other")
    problems = sb.check_tunaos_key_inputs(sources, pki.tuna_der, pki.certs)
    assert "shim: shimx64.efi has no Microsoft UEFI CA signature" in problems
    assert "mokmanager: not signed by the certificate of this shim" in problems


def test_force_enrolment_needs_the_explicit_opt_in(pki, tmp_path, capsys):
    src = tmp_path / "src"
    sources = pki.sources(src)
    esp = tmp_path / "esp"
    esp.mkdir()
    argv = [
        "--certs-dir", str(pki.certs), "stage", "--esp", str(esp), "--shim-dir", str(src / "shim"),
        "--loader", str(sources["loader"]), "--auth-dir", str(src / "auth"), "--enroll", "force",
    ]  # fmt: skip
    assert sb.main(argv) == 1
    assert "needs --allow-force" in capsys.readouterr().err
    assert sb.main([*argv, "--allow-force"]) == 0
    assert "secure-boot-enroll force" in (esp / "loader/loader.conf").read_text()
    with pytest.raises(sb.SecureBootError):
        sb.loader_conf("", "always")


def test_aarch64_layout_uses_the_aa64_names():
    targets = [target for _, target in sb.tunaos_key_plan("aa64")]
    assert {"EFI/BOOT/BOOTAA64.EFI", "EFI/BOOT/mmaa64.efi", "EFI/BOOT/grubaa64.efi"} <= set(targets)


def test_long_pe_section_names_resolve_through_the_string_table(tmp_path):
    # Real shims name the section `.vendor_cert` (12 bytes) through "/N".
    image = bytearray(make_pe({".text": b"\xc3" * 64, "/4": b"payload"}))
    (pe,) = struct.unpack_from("<I", image, 0x3C)
    struct.pack_into("<II", image, pe + 12, len(image), 0)
    image += struct.pack("<I", 17) + b".vendor_cert\0"
    path = tmp_path / "long.efi"
    path.write_bytes(bytes(image))
    assert ".vendor_cert" in sb.pe_sections(path)
    assert sb.is_shim(path)


# --- CI signing interface ---------------------------------------------------------


def sign_env(pki, **extra):
    env = {
        "PATH": os.environ["PATH"],
        "TUNAOS_SB_CERT": (pki.keys / "tuna.pem").read_text(),
        "TUNAOS_SB_KEY": (pki.keys / "tuna.key").read_text(),
        "TUNAOS_SB_EXPECTED_CERT": str(pki.keys / "tuna.pem"),
        "XDG_RUNTIME_DIR": str(pki.tmp / "run"),
    }
    (pki.tmp / "run").mkdir(exist_ok=True)
    env.update(extra)
    return env


def test_ci_sign_produces_a_medium_that_stages(pki, tmp_path):
    esl = tmp_path / "esl"
    assert sb.main(["--certs-dir", str(pki.certs), "build-esl", "--out", str(esl)]) == 0
    raw = pki.pe(tmp_path / "systemd-bootx64.efi", None)
    signed = tmp_path / "systemd-bootx64.efi.signed"
    env = sign_env(pki)
    done = run("bash", SB_DIR / "ci-sign.sh", "efi", raw, signed, env=env)
    assert done.returncode == 0, done.stderr
    done = run("bash", SB_DIR / "ci-sign.sh", "auth", esl, tmp_path / "auth", env=env)
    assert done.returncode == 0, done.stderr
    # The key never reaches the output or stays behind on disk.
    key_body = (pki.keys / "tuna.key").read_text().splitlines()[1]
    assert key_body not in done.stdout + done.stderr
    assert list((pki.tmp / "run").iterdir()) == []
    sources = pki.sources(tmp_path / "src")
    sources["loader"] = signed
    sources.update({f"{name}.auth": tmp_path / "auth" / f"{name}.auth" for name in sb.VARIABLES})
    assert sb.check_tunaos_key_inputs(sources, pki.tuna_der, pki.certs) == []


def test_ci_sign_refuses_a_certificate_that_is_not_the_committed_one(pki, tmp_path):
    raw = pki.pe(tmp_path / "a.efi", None)
    # Default pin: the committed tunaOS certificate. The throwaway one differs.
    env = sign_env(pki)
    del env["TUNAOS_SB_EXPECTED_CERT"]
    done = run("bash", SB_DIR / "ci-sign.sh", "efi", raw, tmp_path / "a.signed", env=env)
    assert done.returncode == 1 and "differs from" in done.stderr
    assert not (tmp_path / "a.signed").exists()


def test_ci_sign_refuses_a_key_that_does_not_match_and_a_trace(pki, tmp_path):
    raw = pki.pe(tmp_path / "a.efi", None)
    env = sign_env(pki, TUNAOS_SB_KEY=(pki.keys / "other.key").read_text())
    done = run("bash", SB_DIR / "ci-sign.sh", "efi", raw, tmp_path / "a.signed", env=env)
    assert done.returncode == 1 and "does not match" in done.stderr
    done = run(
        "bash", "-x", SB_DIR / "ci-sign.sh", "efi", raw, tmp_path / "a.signed", env=sign_env(pki)
    )
    assert done.returncode == 1 and "refuse to run under set -x" in done.stderr
    assert "PRIVATE KEY" not in done.stderr


def test_ci_sign_reads_exactly_the_organisation_secret_names():
    text = (SB_DIR / "ci-sign.sh").read_text()
    assert "${TUNAOS_SB_KEY}" in text and "${TUNAOS_SB_CERT}" in text
    done = run(
        "bash",
        SB_DIR / "ci-sign.sh",
        "auth",
        "esl",
        "out",
        "--dry-run",
        env={"PATH": os.environ["PATH"]},
    )
    assert done.returncode == 0
    assert done.stdout.count("sbvarsign") == 3 and "<TUNAOS_SB_KEY>" in done.stdout
    done = run("bash", SB_DIR / "ci-sign.sh", "efi", "a", "b", env={"PATH": os.environ["PATH"]})
    assert done.returncode == 1 and "TUNAOS_SB_CERT is not set" in done.stderr


# --- docs and strings -------------------------------------------------------------


def test_every_plan_string_exists_in_strings_md():
    helper = (SB_DIR / "tuna-secure-boot").read_text()
    strings = (SB_DIR / "strings.md").read_text()
    import re

    ids = set(re.findall(r"string=(sb\.[a-z.-]+)", helper))
    assert ids, "tuna-secure-boot plan names no string"
    for string_id in ids:
        # An ID is one string, or the prefix of a `.title`/`.body` group.
        assert f"`{string_id}`" in strings or f"`{string_id}." in strings, string_id


def test_bases_table_matches_the_document():
    bases = sb._tomllib().loads((SB_DIR / "bases.toml").read_text())["base"]
    doc = (ROOT / "installer-medium/docs/SECURE-BOOT.md").read_text()
    assert len(bases) >= 14
    for row in bases:
        assert row["secure_boot"] in sb.MODES, row
        assert row["bootloader"] in ("grub", "systemd-boot"), row
        assert row["evidence"], row
        line = next(
            (line for line in doc.splitlines() if line.startswith(f"| {row['name']} |")), None
        )
        assert line, f"SECURE-BOOT.md has no row for {row['name']}"
        assert f"`{row['secure_boot']}`" in line and row["bootloader"] in line, line
