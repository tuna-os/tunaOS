"""Harness contracts only: these fixtures do not constitute native VM acceptance."""
import base64
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import stat
import shutil
import urllib.error
import zipfile

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("installer_proof", ROOT / "scripts/qualify-fork-installer.py")
PROOF = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PROOF)
LOGIN_SPEC = importlib.util.spec_from_file_location("installer_login_ocr", ROOT / "scripts/qualify-fork-login.py")
LOGIN = importlib.util.module_from_spec(LOGIN_SPEC)
LOGIN_SPEC.loader.exec_module(LOGIN)
FIXTURES = ROOT / "tests/fixtures/fork-installer"
REAL_OCR = pytest.mark.skipif(not shutil.which("tesseract"), reason="tesseract is not installed")


def metadata():
    artifact = {"id": PROOF.ARTIFACT_ID, "name": PROOF.BUNDLE_NAME, "expired": False,
                "digest": "sha256:" + PROOF.ZIP_SHA256,
                "workflow_run": {"id": PROOF.RUN_ID, "head_sha": PROOF.SOURCE_HEAD}}
    run = {"id": PROOF.RUN_ID, "head_sha": PROOF.SOURCE_HEAD, "event": "pull_request",
           "repository": {"full_name": PROOF.REPOSITORY}, "status": "completed", "conclusion": "success"}
    return artifact, run


def test_exact_artifact_source_and_zip_provenance():
    receipt = PROOF.validate_metadata(*metadata())
    assert receipt["artifact_id"] == 12169166635
    assert receipt["run_id"] == 39214448822
    assert receipt["source_head"] == "7bf74f727a3a8696f6d7f7b509d51150939d8d1e"
    assert receipt["recorded_tested_merge"] == "01d54aa3bfd9e2a6e350d956a95eab449c7a13b4"


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
        PROOF.api_request("/actions/artifacts/12169166635", "sensitive-test-token")
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
    observed = {"instances": [{"pid": 42, "uid": 1000, "application": PROOF.APP, "app_commit": "app-commit"}],
                "stamps": [{"pid": 42, "namespace": "app-process-root", "uid": 1000, "fields": {"app_id": PROOF.APP, "window": "BootcWindow",
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
    image.paste("white", (308, 420, 768, 474))
    image.save(frame)
    return frame, reference


def exact_label(path, **kwargs):
    assert kwargs == {"psm": 7, "confidence": 0}
    assert Path(path).is_file()
    return [{"text": word, "conf": "95"} for word in ("Install", "Harbor", "Canary")]


def test_framebuffer_reference_match_must_be_above_the_real_heading(tmp_path):
    assert PROOF.visible_branding(*screen(tmp_path), words(), ocr=exact_label, private=tmp_path)["passed"] is True


@pytest.mark.parametrize("box,color", [(None, "#eb922d"), ((474, 190, 602, 318), "red"),
                                      ((100, 190, 228, 318), "#eb922d"),
                                      ((474, 190, 602, 230), "#eb922d"),
                                      ((0, 0, 1280, 800), "#eb922d")])
def test_missing_wrong_unrelated_or_nonsquare_logo_fails(tmp_path, box, color):
    assert not PROOF.visible_branding(*screen(tmp_path, box, color), words(), ocr=exact_label, private=tmp_path)["passed"]


def test_both_heading_and_install_row_are_required(tmp_path):
    frame, reference = screen(tmp_path)
    rows = words()
    assert not PROOF.visible_branding(frame, reference, rows, ocr=lambda *a, **kw: [], private=tmp_path)["passed"]
    rows[2]["text"] = "TunaOS"
    assert not PROOF.visible_branding(frame, reference, rows, ocr=exact_label, private=tmp_path)["passed"]


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


@pytest.fixture(params=["yellowfin", "grouper"])
def captured_welcome(request):
    provenance = json.loads((FIXTURES / "provenance.json").read_text())
    sample = provenance["screenshots"][request.param]
    frame = FIXTURES / sample["file"]
    assert PROOF.sha256(frame) == sample["sha256"]
    return frame, sample


def reference_logo(tmp_path):
    reference = tmp_path / "reference.png"
    PROOF.logo_reference(wrapped_logo(), reference)
    return reference


@REAL_OCR
def test_actual_native_welcome_uses_action_row_geometry_and_exact_crop(captured_welcome, tmp_path):
    """Run 39215796177 frames are OCR regressions, not a new native acceptance."""
    frame, sample = captured_welcome
    # Retain the measured old failure even if a newer Tesseract fixes PSM11.
    old_lines = PROOF.exact_lines(sample["full_frame_words"], "install harbor canary", isolated=False)
    assert bool(old_lines) == (sample["variant"] == "grouper")
    receipt = PROOF.visible_branding(frame, reference_logo(tmp_path), LOGIN.words(frame),
                                     ocr=LOGIN.words, private=tmp_path)
    assert receipt["passed"] is True
    assert receipt["frame_sha256"] == sample["sha256"]
    assert receipt["action_rows"][0]["bounds"] == sample["row_bbox"]
    assert receipt["install_row_ocr"]["crop_bbox"] == sample["crop_bbox"]
    assert receipt["install_row_ocr"]["psm"] == 7
    assert receipt["install_row_ocr"]["scale"] == 4
    assert [r["text"] for r in receipt["install_row_ocr"]["words"]] == ["Install", "Harbor", "Canary"]
    assert all(float(r["conf"]) >= 80 for r in receipt["install_row_ocr"]["words"])
    assert receipt["logo_matches"][0]["reference_matching_fraction"] >= .98
    assert not list(tmp_path.glob("installer-ocr-*")), "temporary crops must be removed"


@REAL_OCR
def test_native_welcome_detection_moves_with_the_window(captured_welcome, tmp_path):
    frame, _ = captured_welcome
    shifted = tmp_path / "shifted.png"
    with Image.open(frame) as source:
        image = Image.new("RGB", source.size, "#12394b")
        image.paste(source, (45, 23))
        image.save(shifted)
    assert PROOF.visible_branding(shifted, reference_logo(tmp_path), LOGIN.words(shifted),
                                  ocr=LOGIN.words, private=tmp_path)["passed"]


@pytest.mark.parametrize("collision", ["wrong-brand", "substring", "prefix", "suffix", "duplicate"])
def test_welcome_heading_requires_unique_complete_copy(captured_welcome, tmp_path, collision):
    frame, sample = captured_welcome
    rows = [dict(r) for r in sample["full_frame_words"]]
    heading = PROOF.exact_lines(rows, "welcome to harbor canary")[0]
    if collision == "wrong-brand":
        heading[2]["text"] = "TunaOS"
    elif collision == "substring":
        heading[-1]["text"] = "Canary2"
    elif collision == "duplicate":
        rows += [{**r, "block_num": "100", "top": "650"} for r in heading]
    else:
        # A separate TSV block on the same baseline must not hide extra copy.
        left, top, right, bottom = PROOF.text_bounds(heading)
        rows.append({**heading[0], "text": "Not" if collision == "prefix" else "Now",
                     "block_num": "100", "left": str(left - 42 if collision == "prefix" else right + 6),
                     "top": str(top), "width": "36", "height": str(bottom - top)})
    receipt = PROOF.visible_branding(frame, reference_logo(tmp_path), rows,
                                     ocr=lambda *a, **kw: pytest.fail("ambiguous heading reached crop OCR"), private=tmp_path)
    assert not receipt["passed"]
    assert receipt["reason"] == "no unique exact welcome heading"


@pytest.mark.parametrize("label", [[], ["Harbor", "Canary"], ["Reinstall", "Harbor", "Canary"],
                                  ["Install", "Harbor", "Canary2"], ["Install", "TunaOS"],
                                  ["Do", "not", "Install", "Harbor", "Canary"],
                                  ["Install", "Harbor", "Canary", "now"], ["Install", "Harbor", "Canary!"],
                                  ["Canary", "Harbor", "Install"]])
def test_crop_requires_exact_complete_label(captured_welcome, tmp_path, label):
    frame, sample = captured_welcome
    receipt = PROOF.visible_branding(frame, reference_logo(tmp_path), sample["full_frame_words"],
                                     ocr=lambda *a, **kw: [{"text": word, "conf": 99} for word in label], private=tmp_path)
    assert not receipt["passed"]
    assert receipt["reason"] == "action row label is not exactly Install Harbor Canary"


@pytest.mark.parametrize("confidence", [0, 20.99, 79.99])
def test_crop_cannot_reuse_icon_merged_low_confidence_text(captured_welcome, tmp_path, confidence):
    frame, sample = captured_welcome
    label = [{"text": word, "conf": 99} for word in ("Install", "Harbor", "Canary")]
    label[0]["conf"] = confidence
    receipt = PROOF.visible_branding(frame, reference_logo(tmp_path), sample["full_frame_words"],
                                     ocr=lambda *a, **kw: label, private=tmp_path)
    assert not receipt["passed"]
    assert not list(tmp_path.glob("installer-ocr-*"))


def test_unrelated_or_duplicate_install_copy_does_not_substitute_for_row(captured_welcome, tmp_path):
    frame, sample = captured_welcome
    rows = sample["full_frame_words"] + [{**r, "block_num": "100", "top": "650"} for r in words()[4:]]
    receipt = PROOF.visible_branding(frame, reference_logo(tmp_path), rows, ocr=exact_label, private=tmp_path)
    assert not receipt["passed"]
    assert receipt["reason"] == "conflicting install label outside the welcome action row"


@pytest.mark.parametrize("geometry", ["missing", "off-center", "page", "ambiguous", "unknown-theme"])
def test_absent_or_ambiguous_action_row_fails_before_ocr(tmp_path, geometry):
    frame, reference = screen(tmp_path)
    with Image.open(frame) as source:
        image = source.copy()
    image.paste("#333333", (308, 420, 768, 474))
    if geometry == "off-center":
        image.paste("white", (50, 420, 510, 474))
    elif geometry == "page":
        image.paste("white", (0, 380, 1280, 800))
    elif geometry == "ambiguous":
        image.paste("white", (308, 390, 768, 426))
        image.paste("white", (308, 432, 768, 468))
    elif geometry == "unknown-theme":
        image.paste("#444444", (308, 420, 768, 474))
    image.save(frame)
    receipt = PROOF.visible_branding(frame, reference, words(),
                                     ocr=lambda *a, **kw: pytest.fail("invalid row reached OCR"), private=tmp_path)
    assert not receipt["passed"]
    assert receipt["reason"] == "no unique first action row below the welcome heading"


@REAL_OCR
@pytest.mark.parametrize("text", ["", "Install TunaOS", "Reinstall Harbor Canary", "Do not Install Harbor Canary",
                                 "Install Harbor Canary now", "Install Harbor Canary2"])
def test_real_crop_ocr_rejects_changed_visible_copy(captured_welcome, tmp_path, text):
    from PIL import ImageDraw, ImageFont
    frame, sample = captured_welcome
    changed = tmp_path / "changed.png"
    with Image.open(frame) as source:
        image = source.copy()
    left, top, right, bottom = sample["crop_bbox"]
    image.paste("white", (left, top, right, bottom))
    ImageDraw.Draw(image).text((left + 3, top + 4), text, font=ImageFont.load_default(size=14), fill="#333333")
    image.save(changed)
    receipt = PROOF.visible_branding(changed, reference_logo(tmp_path), LOGIN.words(changed),
                                     ocr=LOGIN.words, private=tmp_path)
    assert not receipt["passed"]


def test_private_crop_is_removed_if_ocr_fails(captured_welcome, tmp_path):
    frame, sample = captured_welcome

    def fail(path, **kwargs):
        assert Path(path).is_file()
        raise RuntimeError("OCR failed")

    with pytest.raises(RuntimeError, match="OCR failed"):
        PROOF.visible_branding(frame, reference_logo(tmp_path), sample["full_frame_words"], ocr=fail, private=tmp_path)
    assert not list(tmp_path.glob("installer-ocr-*"))


def test_fisherman_diagnostics_use_same_desktop_portal_without_execution():
    compile(PROOF.FISHERMAN_PATH_PROBE, "fisherman-path-probe", "exec")
    compile(PROOF.GUEST_FISHERMAN_DIAGNOSTICS, "guest-path-probe", "exec")
    assert 'user_env()' in PROOF.GUEST_FISHERMAN_DIAGNOSTICS
    assert '["flatpak-spawn", "--host"]' in PROOF.FISHERMAN_PATH_PROBE
    assert '"readelf", "-l"' in PROOF.FISHERMAN_PATH_PROBE
    assert '"sha256sum"' in PROOF.FISHERMAN_PATH_PROBE
    assert '"interpreter"' in PROOF.FISHERMAN_PATH_PROBE
    assert '"pkexec"' not in PROOF.FISHERMAN_PATH_PROBE
    assert '"chmod"' not in PROOF.FISHERMAN_PATH_PROBE
    assert '"sudo"' not in PROOF.FISHERMAN_PATH_PROBE
    assert '"fisherman", "probe"' not in PROOF.FISHERMAN_PATH_PROBE


def test_fisherman_diagnostics_reads_elf_interpreter_without_running_binary(tmp_path, monkeypatch, capsys):
    import struct
    from types import SimpleNamespace
    home = tmp_path / "home"
    binary = home / ".cache/bootc-installer/fisherman"
    binary.parent.mkdir(parents=True)
    interpreter = b"/lib64/ld-linux-x86-64.so.2\0"
    header = bytearray(64)
    header[:6] = b"\x7fELF\x02\x01"
    struct.pack_into("<Q", header, 32, 64)
    struct.pack_into("<HH", header, 54, 56, 1)
    program = bytearray(56)
    struct.pack_into("<I", program, 0, 3)
    struct.pack_into("<Q", program, 8, 120)
    struct.pack_into("<Q", program, 32, len(interpreter))
    binary.write_bytes(header + program + interpreter)
    import sys
    monkeypatch.setitem(sys.modules, "bootc_installer.utils.fisherman_runner", SimpleNamespace(HOST_PATH=str(binary)))
    commands = []
    def fake_run(args, **kwargs):
        commands.append(args)
        assert kwargs["timeout"] == 15
        assert args[0] != str(binary)
        return SimpleNamespace(returncode=0, stdout="observed", stderr="")
    monkeypatch.setattr(PROOF.subprocess, "run", fake_run)
    exec(PROOF.FISHERMAN_PATH_PROBE, {})
    result = json.loads(capsys.readouterr().out)
    assert result["interpreter"]["path"] == interpreter.rstrip(b"\0").decode()
    assert ["flatpak-spawn", "--host", "stat", "--", result["interpreter"]["path"]] in commands
    assert ["flatpak-spawn", "--host", "sha256sum", "--", str(binary)] in commands


@pytest.mark.parametrize("field,value", [("pid", 43), ("namespace", "host-runtime"), ("uid", 0)])
def test_readiness_stamp_must_belong_to_exact_live_app_namespace(field, value):
    observed, launched, installed = window()
    observed["stamps"][0][field] = value
    assert not PROOF.validate_window(observed, launched, installed)


@pytest.mark.parametrize("exits", [False, True])
def test_observer_reads_actual_app_process_runtime_not_host_paths(tmp_path, capsys, exits):
    namespace = tmp_path / "42/root/run/user/1000"
    namespace.mkdir(parents=True)
    (namespace / "tuna-installer-ready").write_text("window=BootcWindow\nsignal=gtk-map\n")
    instance = {"pid": 42, "uid": 1000, "application": PROOF.APP, "app_commit": "app-commit"}
    calls = iter([[instance], [] if exits else [instance]])
    scope = {"instances": lambda: next(calls), "PROC_ROOT": tmp_path,
             "runtime": Path("/run/user/1000"), "json": json}
    exec(PROOF.GUEST_OBSERVE.removeprefix(PROOF.GUEST_COMMON), scope)
    result = json.loads(capsys.readouterr().out)
    if exits:
        assert result == {"instances": [], "stamps": []}
    else:
        assert result["stamps"][0]["pid"] == 42
        assert result["stamps"][0]["namespace"] == "app-process-root"
        assert result["stamps"][0]["fields"]["signal"] == "gtk-map"
