"""Native GnuPG/APT verification with an isolated, signed file-transport fixture.

Only the HTTPS download is stubbed. Generated deb822 paths/URI are relocated to
private local files for native apt, not used as evidence of HTTPS transport.
No host sources, package databases, config hooks or package installs are used.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
from email.utils import formatdate

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(not Path("/usr/bin/apt-get").is_file() or not shutil.which("gpg"),
                    reason="native APT/GnuPG unavailable")
def test_native_apt_accepts_signed_source_and_rejects_tamper(tmp_path, request):
    # GnuPG needs a local agent socket; restricted executors may forbid it.
    try:
        with socket.socket(socket.AF_UNIX) as probe:
            probe.bind(str(tmp_path / "agent-probe.sock"))
    except PermissionError:
        pytest.skip("executor forbids GnuPG agent sockets; native signing fixture needs CI")
    home = tmp_path / "gpg"
    home.mkdir(mode=0o700)
    request.addfinalizer(lambda: subprocess.run(["gpgconf", "--homedir", str(home), "--kill", "gpg-agent"],
                                               capture_output=True, check=False))
    gpg = [shutil.which("gpg"), "--homedir", str(home), "--batch", "--pinentry-mode", "loopback", "--passphrase", ""]
    subprocess.run(gpg + ["--quick-generate-key", "Fixture <fixture@example.invalid>", "ed25519", "sign", "0"],
                   check=True, capture_output=True)
    key = tmp_path / "key.asc"
    key.write_bytes(subprocess.check_output(gpg + ["--armor", "--export", "fixture@example.invalid"]))
    repo = tmp_path / "repo"
    release_dir = repo / "dists/stable"
    packages = release_dir / "main/binary-amd64/Packages"
    packages.parent.mkdir(parents=True)
    packages.write_bytes(b"")
    release = release_dir / "Release"
    release.write_text("Origin: Fixture\nLabel: Fixture\nSuite: stable\nCodename: stable\n"
                       f"Date: {formatdate(usegmt=True)}\nArchitectures: amd64\nComponents: main\nSHA256:\n"
                       f" {hashlib.sha256(b'').hexdigest()} 0 main/binary-amd64/Packages\n")
    signed = release_dir / "InRelease"
    subprocess.run(gpg + ["--digest-algo", "SHA256", "--output", str(signed), "--clearsign", str(release)],
                   check=True, capture_output=True)
    declaration = {"id": "fixture", "type": "apt", "url": "https://fixture.invalid/repo",
                   "key_url": "https://fixture.invalid/key.asc", "key_sha256": hashlib.sha256(key.read_bytes()).hexdigest(),
                   "suites": ["stable"], "components": ["main"]}
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"intent": {"packages": {"repositories": [declaration]}}}))
    image_root = tmp_path / "image"
    image_root.mkdir()
    bindir = tmp_path / "bin"
    bindir.mkdir()
    curl = bindir / "curl"
    curl.write_text('''#!/bin/bash
while (($#)); do
    if [[ "$1" == --output ]]; then cp "$KEY_FIXTURE" "$2"; exit; fi
    shift
done
exit 9
''')
    curl.chmod(0o755)
    subprocess.run(["bash", "-c", 'source "$1"; source "$2"; tunaos_fork_apt_repositories "$3" "$4"', "test",
                    str(ROOT / "build_scripts/lib/fork-packages.sh"),
                    str(ROOT / "build_scripts/lib/fork-apt-repositories.sh"), str(manifest), str(image_root)],
                   env=dict(os.environ, PATH=f"{bindir}:/usr/bin:/bin", KEY_FIXTURE=str(key)),
                   check=True, capture_output=True)
    generated = (image_root / "etc/apt/sources.list.d/fork-fixture.sources").read_text()
    local_source = tmp_path / "fixture.sources"
    local_source.write_text(generated.replace(declaration["url"], repo.as_uri())
                           .replace("/usr/share/keyrings/", str(image_root / "usr/share/keyrings") + "/"))
    apt_root = tmp_path / "apt"
    (apt_root / "state/lists/partial").mkdir(parents=True)
    (apt_root / "cache/archives/partial").mkdir(parents=True)
    (apt_root / "status").write_text("")
    config = tmp_path / "apt.conf"
    config.write_text(f'''Dir::Etc::parts "-";
Dir::Etc::main "/dev/null";
Dir::Etc::sourcelist "{local_source}";
Dir::Etc::sourceparts "-";
Dir::State "{apt_root}/state";
Dir::State::status "{apt_root}/status";
Dir::Cache "{apt_root}/cache";
APT::Architecture "amd64";
APT::Update::Error-Mode "any";
Acquire::AllowInsecureRepositories "false";
Acquire::AllowDowngradeToInsecureRepositories "false";
''')
    command = ["/usr/bin/apt-get", "update"]
    env = dict(os.environ, APT_CONFIG=str(config))
    good = subprocess.run(command, env=env, text=True, capture_output=True)
    assert good.returncode == 0, good.stdout + good.stderr
    signed.write_text(signed.read_text().replace("Origin: Fixture", "Origin: Tampered"))
    bad = subprocess.run(command, env=env, text=True, capture_output=True)
    assert bad.returncode != 0, bad.stdout + bad.stderr
    assert "signature" in (bad.stdout + bad.stderr).lower()
