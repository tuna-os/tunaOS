"""tunaOS#3980: copied Gentoo templates must pass the branding gate.

Run 40251865603 at 861a871f passed the base package proofs but failed the
modified GNOME desktop's branding check: identity ran before the template COPY.
Execute the full writer, its final Count Me installer, and the full verifier
against redirected files, with only OS detection stubbed. No image is built.

Falsification: behavioural — re-copy any of the seven templates after the
writer and require the real verifier to reject it; re-render and require OK.
The Containerfile projection also fails if COPY moves after the first writer
or the final desktop copy loses its following writer.
"""
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_anime_finalization import Image, ROOT  # noqa: E402

METADATA = {
    "usr/share/plasma/look-and-feel/org.tunaos.desktop/metadata.json": "Guppy",
    "usr/share/plasma/look-and-feel/org.tunaos.light.desktop/metadata.json": "Guppy Light",
    "usr/share/wallpapers/TunaOS/metadata.json": "Guppy",
}
UNITS = "usr/lib/systemd/system/"
RECIPE = "etc/bootc-installer/recipe.json"
TOKEN_PATHS = (*METADATA, UNITS + "tunaos-live-ready.service",
               UNITS + "tunaos-countme.service", UNITS + "tunaos-countme.timer", RECIPE)


class GentooImage(Image):
    def __init__(self, tmp_path, policy):
        super().__init__(tmp_path, "guppy", "gnome")
        self.env.update({f"IS_{base}": "false" for base in (
            "FEDORA", "HUMMINGBIRD", "ALMALINUX", "ALMALINUXKITTEN", "CENTOS",
            "UBUNTU", "DEBIAN", "ARCH", "OPENSUSE")}, IS_GENTOO="true")
        self.project = "TunaOS" if policy == "stock" else "Harbor (OS) 2.0+"
        self.project_id = "tunaos" if policy == "stock" else "harbor"
        self.metrics = "https://tunaos.org/metrics"
        self.home = "https://github.com/tuna-os/tunaos"
        self.endpoint = "https://countme.tunaos.org/v1/report"
        config = (ROOT / "tunaos.toml").read_text()
        if policy != "stock":
            self.home = "https://harbor.example/?a=1&b=two%7Cthree"
            self.metrics = "https://harbor.example/metrics?a=1&b=two%7Cthree"
            self.endpoint = "https://harbor.example/v1/report"
            if policy == "fork-disabled":
                self.metrics = self.endpoint = ""
            for before, after in (
                ('[project]\nname = "TunaOS"', f'[project]\nname = "{self.project}"'),
                ('id = "tunaos"', f'id = "{self.project_id}"'),
                ('homepage = "https://github.com/tuna-os/tunaos"', f'homepage = "{self.home}"'),
                ('countme_endpoint = "https://countme.tunaos.org/v1/report"',
                 f'countme_endpoint = "{self.endpoint}"'),
                ('countme_metrics_url = "https://tunaos.org/metrics"',
                 f'countme_metrics_url = "{self.metrics}"'),
            ):
                assert config.count(before) == 1
                config = config.replace(before, after)
            self.env["IMAGE_VENDOR"] = "harbor-owner"
        config_root = tmp_path / "config"
        config_root.mkdir()
        (config_root / "tunaos.toml").write_text(config)
        subprocess.run([sys.executable, str(ROOT / "scripts/config.py"), "generate-identity",
                        "--root", str(config_root), "--output",
                        str(self.context / "build_scripts/lib/identity.env")], check=True,
                       capture_output=True, text=True)

        # Replace Image's Count Me boundary stub with the actual last writer.
        shutil.copy2(ROOT / "build_scripts/install-countme.sh",
                     self.context / "build_scripts/install-countme.sh")
        self.env.update(TUNAOS_COUNTME_ROOT=str(self.root), TUNAOS_COUNTME_CONTEXT=str(self.context))
        for path in ("usr/libexec/tunaos-countme", "usr/bin/tunaos-countme",
                     "usr/share/tunaos/countme-allowlist.json",
                     UNITS + "tunaos-countme.service", UNITS + "tunaos-countme.timer"):
            target = self.context / "files" / path
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / "system_files" / path, target)
        self.opt_out = self.root / "etc/systemd/system/tunaos-countme.timer"
        self.opt_out.parent.mkdir(parents=True)
        self.opt_out.symlink_to("/dev/null")
        disabled = self.root / "etc/tunaos/countme/disabled"
        disabled.parent.mkdir(parents=True)
        disabled.write_text("operator opt-out\n")
        logo = self.root / "usr/share/pixmaps/tunaos.svg"
        logo.parent.mkdir(parents=True)
        shutil.copyfile(ROOT / "system_files/usr/share/pixmaps/tunaos.svg", logo)
        (self.root / "usr/share/plymouth/themes/tunaos").mkdir(parents=True)

        # Full verifier, including the exit status and serial verdict. Redirect
        # ttyS0 too: even build mode tees its verdict to that device.
        source = (ROOT / "build_scripts/checks/verify-branding.sh").read_text()
        source = source.replace("/usr/", f"{self.root}/usr/").replace("/etc/", f"{self.root}/etc/")
        source = source.replace("/dev/ttyS0", str(tmp_path / "ttyS0"))
        self.verifier = self.context / "verify-branding.sh"
        self.verifier.write_text(source)

    def copy_templates(self, paths=TOKEN_PATHS):
        for path in paths:
            target = self.root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / "system_files" / path, target)

    def verify(self, bad_path=None):
        # The installed-policy path must work without the build environment.
        result = subprocess.run(["bash", str(self.verifier), "guppy"],
                                env={"PATH": self.env["PATH"]}, capture_output=True, text=True)
        output = result.stdout + result.stderr
        if bad_path is None:
            assert result.returncode == 0, output
            assert "TUNAOS_BRANDING_OK variant=guppy" in output
        else:
            assert result.returncode != 0, output
            assert "unrendered @TUNAOS_*@ identity token" in output
            assert str(self.root / bad_path) in output
            assert "TUNAOS_BRANDING_FAIL variant=guppy" in output

    def assert_identity(self):
        for path in TOKEN_PATHS:
            assert not re.search(r"@TUNAOS_[A-Z_]+@", (self.root / path).read_text()), path
        for path, name in METADATA.items():
            plugin = json.loads((self.root / path).read_text())["KPlugin"]
            assert plugin["Name"] == name
            assert plugin["Authors"][0]["Name"] == f"{self.project} Contributors"
            if "Website" in plugin:
                assert plugin["Website"] == self.home
        live = (self.root / UNITS / "tunaos-live-ready.service").read_text()
        assert f"Description={self.project} live environment ready marker" in live
        assert f"Documentation={self.home}/blob/main/docs/IMPROVEMENT_PLAN.md" in live
        recipe = json.loads((self.root / RECIPE).read_text())
        assert recipe["tour"]["completed"]["description"] == (
            "Reboot your machine to enter your new Guppy workstation environment!")
        assert recipe["tour"]["distro"]["title"] == "Built on Gentoo Linux"
        assert recipe["tour"]["desktop"]["title"] == "GNOME Desktop"
        assert recipe["imgref"] == f"ghcr.io/{self.env['IMAGE_VENDOR']}/guppy:gnome"
        assert recipe["local_imgref"] == "containers-storage:" + recipe["imgref"]
        for unit in ("service", "timer"):
            body = (self.root / UNITS / f"tunaos-countme.{unit}").read_text()
            assert self.project in body
            if self.metrics:
                assert f"Documentation={self.metrics}\n" in body
            else:
                assert "Documentation=" not in body
        service = (self.root / UNITS / "tunaos-countme.service").read_text()
        assert "ConditionPathExists=!/etc/tunaos/countme/disabled" in service
        assert "ConditionKernelCommandLine=!tunaos.countme=0" in service
        assert self.opt_out.readlink() == Path("/dev/null")
        assert (self.root / "etc/tunaos/countme/disabled").read_text() == "operator opt-out\n"
        settings = json.loads((self.root / "usr/share/tunaos/countme-service.json").read_text())
        assert settings == {"endpoint": self.endpoint, "metrics_url": self.metrics}
        timer = self.root / UNITS / "timers.target.wants/tunaos-countme.timer"
        assert timer.is_symlink() == bool(self.endpoint)
        assert not (self.root / "var/lib/tunaos-countme").exists()


@pytest.mark.parametrize("policy", ["stock", "fork", "fork-disabled"])
def test_copy_full_writer_and_verifier_survive_final_writers(tmp_path, policy):
    image = GentooImage(tmp_path, policy)
    # Project the relevant Containerfile steps, retaining their actual order.
    # Desktop install's branding gate is exercised here without package builds.
    stages = re.split(r"(?m)^FROM .* AS ", (ROOT / "Containerfile.gentoo").read_text())
    for stage in ("desktop-build", "desktop"):
        body = next(part.split("\n", 1)[1] for part in stages if part.startswith(stage + "\n"))
        events = []
        for line in body.splitlines():
            if line.startswith("COPY --from=context /files /"):
                image.copy_templates()
                events.append("copy")
            elif line.strip().startswith("/run/context/build_scripts/90-image-info.sh"):
                image.info()
                events.append("identity")
            elif line.strip().startswith("/run/context/build_scripts/desktop/install-desktop.sh"):
                image.verify()
                image.desktop()
                events.append("desktop")
        assert events == (["copy", "identity", "desktop"] if stage == "desktop-build" else ["copy", "identity"])
        image.assert_identity()
        image.verify()
    rendered = {path: (image.root / path).read_bytes() for path in TOKEN_PATHS}
    image.info()
    assert rendered == {path: (image.root / path).read_bytes() for path in TOKEN_PATHS}
    image.copy_templates()
    image.info()
    assert rendered == {path: (image.root / path).read_bytes() for path in TOKEN_PATHS}
    # GNOME's common overlay can overwrite units; the final Count Me install
    # must restore them without losing /etc opt-outs or enabling an empty URL.
    image.copy_templates((UNITS + "tunaos-countme.service", UNITS + "tunaos-countme.timer"))
    image.run("build_scripts/install-countme.sh")
    image.assert_identity()
    image.verify()


@pytest.mark.parametrize("policy", ["stock", "fork-disabled"])
@pytest.mark.parametrize("path", TOKEN_PATHS)
def test_verifier_rejects_each_template_copied_after_identity(tmp_path, policy, path):
    image = GentooImage(tmp_path, policy)
    image.copy_templates()
    image.info()
    image.verify()
    image.copy_templates((path,))
    image.verify(bad_path=path)
    image.info()
    image.assert_identity()
    image.verify()
