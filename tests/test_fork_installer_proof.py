"""Harness contracts only: these fixtures do not constitute native VM acceptance."""
import base64
import hashlib
import importlib.util
import io
from pathlib import Path
import stat
import urllib.error
import zipfile

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("installer_proof", ROOT / "scripts/qualify-fork-installer.py")
PROOF = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PROOF)


def metadata():
    artifact = {"id": PROOF.ARTIFACT_ID, "name": PROOF.BUNDLE_NAME, "expired": False,
                "digest": "sha256:" + PROOF.ZIP_SHA256,
                "workflow_run": {"id": PROOF.RUN_ID, "head_sha": PROOF.SOURCE_HEAD}}
    run = {"id": PROOF.RUN_ID, "head_sha": PROOF.SOURCE_HEAD, "event": "pull_request",
           "repository": {"full_name": PROOF.REPOSITORY}, "status": "completed", "conclusion": "success"}
    return artifact, run


def test_exact_artifact_source_and_zip_provenance():
    receipt = PROOF.validate_metadata(*metadata())
    assert receipt["artifact_id"] == 12163907071
    assert receipt["run_id"] == 39200715506
    assert receipt["source_head"] == "4d0e653f9283debb57b460fe495f65184f9d2c6c"
    assert receipt["recorded_tested_merge"] == "7b6cbf9c152147c031f9ba362ddf4e909f36f643"


@pytest.mark.parametrize("key,value", [("id", 123), ("name", "different.flatpak"),
                                      ("expired", True), ("digest", "sha256:" + "0" * 64),
                                      ("workflow_run", {"id": PROOF.RUN_ID, "head_sha": "wrong"})])
def test_reject_artifact_metadata_drift(key, value):
    artifact, run = metadata()
    artifact[key] = value
    with pytest.raises(ValueError):
        PROOF.validate_metadata(artifact, run)


@pytest.mark.parametrize("key,value", [("id", 123), ("head_sha", "wrong"), ("event", "push"),
                                      ("repository", {"full_name": "other/repo"}), ("status", "in_progress"),
                                      ("conclusion", "failure"), ("conclusion", None)])
def test_reject_workflow_source_drift(key, value):
    artifact, run = metadata()
    run[key] = value
    with pytest.raises(ValueError):
        PROOF.validate_metadata(artifact, run)


@pytest.mark.parametrize("url", ["http://store.blob.core.windows.net/x", "https://api.github.com/x",
                                "https://blob.core.windows.net.evil.invalid/x", "https://evil.invalid/x",
                                "https://user:secret@store.blob.core.windows.net/x", "https://store.blob.core.windows.net:444/x"])
def test_archive_redirect_rejects_other_destinations(url):
    with pytest.raises(ValueError):
        PROOF.public_archive_url(url)


def test_archive_storage_redirect_does_not_need_credentials():
    url = "https://store.blob.core.windows.net/artifact?temporary=signed"
    assert PROOF.public_archive_url(url) == url
    assert PROOF.NoRedirect().redirect_request(None, None, 302, "", {}, url) is None


@pytest.mark.parametrize("status", [401, 403, 404])
def test_api_denial_is_bounded_and_never_falls_back_or_logs_token(monkeypatch, status):
    calls = []
    class Opener:
        def open(self, request, timeout):
            calls.append(request)
            assert request.headers["Authorization"] == "Bearer sensitive-test-token"
            raise urllib.error.HTTPError(request.full_url, status, "denied sensitive-test-token", {}, None)
    monkeypatch.setattr(PROOF.urllib.request, "build_opener", lambda *args: Opener())
    with pytest.raises(RuntimeError, match=f"HTTP {status}") as error:
        PROOF.api_request("/actions/artifacts/12163907071", "sensitive-test-token")
    assert "sensitive-test-token" not in str(error.value)
    assert len(calls) == 1


def archive(tmp_path, monkeypatch, members):
    source = tmp_path / "artifact.zip"
    with zipfile.ZipFile(source, "w") as zipped:
        for member, data in members:
            zipped.writestr(member, data)
    monkeypatch.setattr(PROOF, "ZIP_SHA256", hashlib.sha256(source.read_bytes()).hexdigest())
    target = tmp_path / "extract"
    target.mkdir()
    return source, target


def test_verified_zip_records_independent_inner_checksum(tmp_path, monkeypatch):
    data = b"fixture-only-not-a-flatpak"
    source, target = archive(tmp_path, monkeypatch, [(PROOF.BUNDLE_NAME, data)])
    bundle, checksums = PROOF.unpack(source, target)
    assert bundle.read_bytes() == data
    assert checksums["bundle_sha256"] == hashlib.sha256(data).hexdigest()
    assert checksums["archive_sha256"] != checksums["bundle_sha256"]
    with pytest.raises(FileExistsError):
        PROOF.unpack(source, target)


def test_archive_checksum_is_checked_before_extraction(tmp_path, monkeypatch):
    source, target = archive(tmp_path, monkeypatch, [(PROOF.BUNDLE_NAME, b"data")])
    source.write_bytes(source.read_bytes() + b"modified")
    with pytest.raises(ValueError, match="checksum"):
        PROOF.unpack(source, target)
    assert not list(target.iterdir())


@pytest.mark.parametrize("members", [[("../" + PROOF.BUNDLE_NAME, b"data")],
                                     [("/tmp/" + PROOF.BUNDLE_NAME, b"data")],
                                     [(PROOF.BUNDLE_NAME, b"")],
                                     [(PROOF.BUNDLE_NAME, b"a"), ("extra", b"b")]])
def test_reject_unsafe_unexpected_or_empty_zip_members(tmp_path, monkeypatch, members):
    source, target = archive(tmp_path, monkeypatch, members)
    with pytest.raises(ValueError):
        PROOF.unpack(source, target)
    assert not list(target.iterdir())


def test_reject_symlink_zip_member(tmp_path, monkeypatch):
    link = zipfile.ZipInfo(PROOF.BUNDLE_NAME)
    link.create_system = 3
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    source, target = archive(tmp_path, monkeypatch, [(link, b"/etc/shadow")])
    with pytest.raises(ValueError):
        PROOF.unpack(source, target)


def window():
    launched = {"uid": 1000, "started_at": 123.45}
    installed = {"app_commit": "app-commit"}
    observed = {"instances": [{"uid": 1000, "application": PROOF.APP, "app_commit": "app-commit"}],
                "stamps": [{"uid": 1000, "fields": {"app_id": PROOF.APP, "window": "BootcWindow",
                                                   "signal": "gtk-map", "mapped_at": "123.46"}}]}
    return observed, launched, installed


def test_live_exact_commit_and_new_real_wizard_map_both_required():
    assert PROOF.validate_window(*window())
    for key in ("instances", "stamps"):
        observed, launched, installed = window()
        observed[key] = []
        assert not PROOF.validate_window(observed, launched, installed)


@pytest.mark.parametrize("field,value", [("app_id", "other.app"), ("window", "BootcRamWindow"),
                                        ("window", "BootcCpuWindow"), ("window", "BootcUnsupportedWindow"),
                                        ("signal", "first-frame"), ("mapped_at", "122.0")])
def test_warning_or_stale_or_wrong_window_is_not_acceptance(field, value):
    observed, launched, installed = window()
    observed["stamps"][0]["fields"][field] = value
    assert not PROOF.validate_window(observed, launched, installed)


@pytest.mark.parametrize("field,value", [("uid", 0), ("application", "other.app"), ("app_commit", "stale")])
def test_wrong_user_app_or_commit_cannot_pass(field, value):
    observed, launched, installed = window()
    observed["instances"][0][field] = value
    assert not PROOF.validate_window(observed, launched, installed)


def wrapped_logo(color="#eb922d", size=(128, 128)):
    stream = io.BytesIO()
    Image.new("RGB", size, color).save(stream, "PNG")
    return '<svg><image href="data:image/png;base64,' + base64.b64encode(stream.getvalue()).decode() + '"/></svg>'


def test_reference_is_the_exact_deployed_canary_logo(tmp_path):
    path = tmp_path / "reference.png"
    svg = wrapped_logo()
    assert PROOF.logo_reference(svg, path) == hashlib.sha256(svg.encode()).hexdigest()
    assert Image.open(path).size == (128, 128)
    for bad in (wrapped_logo("red"), wrapped_logo(size=(32, 32)), "<svg><text>fake</text></svg>"):
        with pytest.raises(ValueError):
            PROOF.logo_reference(bad, path)


def words():
    result = []
    for line, text, top in [(1, "Welcome to Harbor Canary", 350), (2, "Install Harbor Canary", 440)]:
        left = 400
        for word in text.split():
            width = len(word) * 12
            result.append({"text": word, "left": str(left), "top": str(top), "width": str(width),
                           "height": "24", "page_num": "1", "block_num": "1", "par_num": "1", "line_num": str(line)})
            left += width + 12
    return result


def screen(tmp_path, box=(474, 190, 602, 318), color="#eb922d"):
    reference = tmp_path / "reference.png"
    frame = tmp_path / "screen.png"
    PROOF.logo_reference(wrapped_logo(), reference)
    image = Image.new("RGB", (1280, 800), "#333333")
    if box:
        image.paste(color, box)
    image.save(frame)
    return frame, reference


def test_framebuffer_reference_match_must_be_above_the_real_heading(tmp_path):
    assert PROOF.visible_branding(*screen(tmp_path), words())["passed"] is True


@pytest.mark.parametrize("box,color", [(None, "#eb922d"), ((474, 190, 602, 318), "red"),
                                      ((100, 190, 228, 318), "#eb922d"),
                                      ((474, 190, 602, 230), "#eb922d"),
                                      ((0, 0, 1280, 800), "#eb922d")])
def test_missing_wrong_unrelated_or_nonsquare_logo_fails(tmp_path, box, color):
    assert not PROOF.visible_branding(*screen(tmp_path, box, color), words())["passed"]


def test_both_heading_and_install_row_are_required(tmp_path):
    frame, reference = screen(tmp_path)
    rows = words()
    assert not PROOF.visible_branding(frame, reference, rows[:4])["passed"]
    rows[2]["text"] = "TunaOS"
    assert not PROOF.visible_branding(frame, reference, rows)["passed"]


def test_guest_sources_compile_and_use_normal_existing_session():
    for source in (PROOF.GUEST_INSTALL.replace("__BUNDLE_SHA__", repr("0" * 64)), PROOF.GUEST_LAUNCH, PROOF.GUEST_OBSERVE):
        compile(source, "guest helper", "exec")
        for forbidden in ("GITHUB_TOKEN", "Authorization", "--command", "--autoinstall", "IGNORE_RAM", "IGNORE_CPU",
                          "BOOTC_INSTALLER_FAKE", "BOOTC_INSTALLER_BRANDING", "dbus-run-session", "gnome-session"):
            assert forbidden not in source
    assert '["flatpak", "run", "--system", APP]' in PROOF.GUEST_LAUNCH
    assert '"systemctl", "--user", "show-environment"' in PROOF.GUEST_COMMON
    assert '"--noninteractive", "--reinstall"' in PROOF.GUEST_INSTALL
    source = (ROOT / "scripts/qualify-fork-installer.py").read_text()
    assert '"installer_committed_install": "not-run"' in source
    assert '"production_installer_qualified": False' in source


def test_host_download_never_forwards_token_to_storage(tmp_path, monkeypatch):
    import json
    source, _ = archive(tmp_path, monkeypatch, [(PROOF.BUNDLE_NAME, b"fixture bundle")])
    archive_bytes = source.read_bytes()
    artifact, workflow = metadata()
    calls = []

    class Response(io.BytesIO):
        code = 200
        headers = {}

    def api(path, token):
        calls.append((path, token))
        if path.endswith("/zip"):
            response = Response()
            response.code = 302
            response.headers = {"Location": "https://store.blob.core.windows.net/artifact?signature=fixture"}
            return response
        return Response(json.dumps(workflow if "/runs/" in path else artifact).encode())

    class Storage:
        def open(self, url, timeout):
            assert isinstance(url, str) and url.startswith("https://store.blob.core.windows.net/")
            assert "host-only-test-token" not in url
            return Response(archive_bytes)

    monkeypatch.setenv("GITHUB_TOKEN", "host-only-test-token")
    monkeypatch.setattr(PROOF, "api_request", api)
    monkeypatch.setattr(PROOF.urllib.request, "build_opener", lambda handler: Storage())
    output = tmp_path / "download"
    receipt = PROOF.download(output)
    assert len(calls) == 3
    assert all(token == "host-only-test-token" for _, token in calls)
    assert receipt["bundle_sha256"] == hashlib.sha256(b"fixture bundle").hexdigest()
    for path in output.iterdir():
        assert b"host-only-test-token" not in path.read_bytes()
        assert b"signature=fixture" not in path.read_bytes()


def test_actual_ocr_parser_can_find_the_two_required_lines(tmp_path):
    """Synthetic image checks OCR integration only, not a native app window."""
    import shutil
    from PIL import ImageDraw, ImageFont
    if not shutil.which("tesseract"):
        pytest.skip("tesseract is not installed on this test host")
    spec = importlib.util.spec_from_file_location("login_ocr", ROOT / "scripts/qualify-fork-login.py")
    login = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(login)
    reference = tmp_path / "reference.png"
    frame = tmp_path / "ocr.png"
    PROOF.logo_reference(wrapped_logo(), reference)
    image = Image.new("RGB", (1280, 800), "#333333")
    image.paste("#eb922d", (576, 190, 704, 318))
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=28)
    draw.text((640, 360), "Welcome to Harbor Canary", anchor="mm", font=font, fill="white")
    draw.text((640, 450), "Install Harbor Canary", anchor="mm", font=font, fill="white")
    image.save(frame)
    assert PROOF.visible_branding(frame, reference, login.words(frame))["passed"]
