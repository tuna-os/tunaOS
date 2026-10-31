"""Screen path of the encrypted installed-boot gate (tunaOS#4090).

Fixture frames are drawn here at the TunaOS Plymouth theme geometry (200x200
sprite centred, prompt below it) and as the text-console fallback (prompt from
column 0). The OCR stand-in reads the pixels it is given: it reports prompt
text only when the prompt's ink is inside the image, so the centred-region
logic is exercised, not bypassed. A fake guest answers HMP sendkey the way the
initramfs does. Nothing connects to QEMU, VNC or a network.
"""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from lib import luks_screen  # noqa: E402

spec = importlib.util.spec_from_file_location(
    "luks_first_boot_harness", ROOT / "tests/test_luks_first_boot.py"
)
harness = importlib.util.module_from_spec(spec)
spec.loader.exec_module(harness)

PASSPHRASE = "tunaos-e2e-luks"
W, H = 1024, 768
CX, CY = W // 2, H // 2
# Ink colours of the drawn text. The OCR stand-in recognises them after the
# gate's dark-UI transform, exactly as tesseract only sees what was drawn.
PROMPT_INK = (10, 200, 30)
REJECT_INK = (200, 30, 180)
LOGO_INK = (240, 140, 20)
KERNEL_INK = (170, 170, 170)


def draw(kind):
    pixels = bytearray(W * H * 3)

    def rect(x0, y0, x1, y1, colour):
        for y in range(y0, y1):
            pixels[(y * W + x0) * 3:(y * W + x1) * 3] = bytes(colour) * (x1 - x0)

    if kind in ("boot", "text_console"):
        rect(0, 0, 420, 14, KERNEL_INK)  # one kernel line
    if kind in ("branded", "branded_reject", "splash"):
        rect(CX - 70, CY - 70, CX + 70, CY + 70, LOGO_INK)  # the sushi sprite
    if kind in ("branded", "branded_reject", "blank_logo_prompt"):
        rect(CX - 150, CY + 128, CX + 150, CY + 146, PROMPT_INK)  # prompt line
        rect(CX - 80, CY + 156, CX + 80, CY + 172, PROMPT_INK)  # "Enter disk password"
    if kind == "branded_reject":
        rect(CX - 60, CY + 180, CX + 60, CY + 194, REJECT_INK)
    if kind == "text_console":
        rect(0, 16, 380, 30, PROMPT_INK)  # "Please enter passphrase for disk root:"
    if kind == "desktop":
        rect(0, 0, W, 32, (60, 60, 60))
    return b"P6\n%d %d\n255\n" % (W, H) + bytes(pixels)


def transformed(colour):
    return bytes(luks_screen._DARK_UI[c] for c in colour)


def fake_ocr(path):
    _, _, pixels = luks_screen.read_ppm(path)
    text = []
    if transformed(PROMPT_INK) in pixels:
        text.append("Please enter passphrase for disk root:\nEnter disk password")
    if transformed(REJECT_INK) in pixels:
        text.append("Sorry, try again")
    return "\n".join(text)


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class FakeGuest:
    """The installed boot as seen through VNC, HMP sendkey and serial."""

    def __init__(self, clock, boot, passphrase=PASSPHRASE, accept_any=False,
                 reprompt=True, serial_after_unlock=b""):
        self.clock = clock
        self.boot = list(boot)
        self.passphrase = passphrase
        self.accept_any = accept_any
        self.reprompt = reprompt
        self.serial_after_unlock = serial_after_unlock
        self.screens = []
        self.typed = ""
        self.typing = False
        self.keys = []
        self.entries = []
        self.captures = []  # (typing_in_progress, screen kind)
        self.serial = b"Booting `Skipjack (ostree:0)'\n"
        self.unlocked = False

    def screen(self):
        if self.screens:
            return self.screens.pop(0) if len(self.screens) > 1 else self.screens[0]
        return self.boot.pop(0) if len(self.boot) > 1 else self.boot[0]

    def capture(self, path):
        self.clock.now += 1
        kind = self.screen()
        self.captures.append((self.typing, kind))
        Path(path).write_bytes(draw(kind))

    def sendkey(self, key):
        self.keys.append(key)
        if key != "ret":
            self.typing = True
            char = {"minus": "-", "spc": " "}.get(key, key)
            if char.startswith("shift-"):
                char = char[6:].upper()
            self.typed += char
            return
        self.typing = False
        self.entries.append(self.typed)
        correct = self.typed == self.passphrase
        self.typed = ""
        if correct or self.accept_any:
            self.unlocked = True
            self.screens = ["splash", "splash", "desktop"]
            self.serial += self.serial_after_unlock
        elif self.reprompt:
            self.screens = ["splash", "branded_reject", "branded"]
        else:
            self.screens = ["splash"]

    def poll_serial(self):
        self.clock.now += 1
        return self.serial


def gate(tmp_path, guest, clock, lines=None, **options):
    options.setdefault("prompt_timeout", 120)
    return luks_screen.ScreenGate(
        tmp_path / "observation",
        options.pop("passphrase", PASSPHRASE),
        capture=guest.capture,
        ocr=fake_ocr,
        sendkey=guest.sendkey,
        poll_serial=guest.poll_serial,
        clock=clock,
        sleep=clock.sleep,
        log=(lines if lines is not None else []).append,
        **options,
    )


def report(tmp_path):
    return json.loads((tmp_path / "observation/observations.json").read_text())


def frame_digest(kind, tmp_path):
    fixture = tmp_path / f"fixture-{kind}.ppm"
    fixture.write_bytes(draw(kind))
    return luks_screen.observer.frame_digest(fixture)


# ── Frame analysis ───────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "kind,prompt,branded",
    [
        ("branded", True, True),
        ("text_console", True, False),
        ("blank_logo_prompt", True, False),
        ("boot", False, False),
        ("splash", False, False),
    ],
)
def test_frame_analysis_reads_layout_not_just_words(tmp_path, kind, prompt, branded):
    frame = tmp_path / "frame.ppm"
    frame.write_bytes(draw(kind))
    verdict = luks_screen.analyse(frame, fake_ocr, tmp_path)
    assert (verdict["prompt"], verdict["branded"]) == (prompt, branded)
    # OCR scratch copies never outlive the analysis.
    assert sorted(p.name for p in tmp_path.iterdir()) == ["frame.ppm"]


# ── Prompt outcomes ──────────────────────────────────────────────────────────

def test_branded_prompt_is_observed_and_unlocked(tmp_path):
    clock = Clock()
    guest = FakeGuest(clock, ["boot", "boot", "branded"])
    lines = []
    observed = gate(tmp_path, guest, clock, lines).run()
    assert observed["prompt"] == "prompt_observed_branded"
    assert observed["unlocked"] is True
    assert observed["wrong_password"] == "not_attempted"
    assert guest.entries == [PASSPHRASE]
    assert "LUKS_SCREEN prompt=prompt_observed_branded" in lines
    assert "LUKS_SCREEN unlocked=yes" in lines
    assert report(tmp_path)["status"] == "unlocked"


def test_text_console_prompt_is_unbranded(tmp_path):
    clock = Clock()
    guest = FakeGuest(clock, ["boot", "text_console"])
    observed = gate(tmp_path, guest, clock).run()
    assert observed["prompt"] == "prompt_observed_unbranded"
    # Three text-console frames in a row before the verdict, then the unlock
    # evidence is still collected.
    before = [kind for typing, kind in guest.captures[: guest.captures.index((False, "text_console")) + 3]]
    assert before.count("text_console") == luks_screen.UNBRANDED_CONFIRMATIONS
    assert observed["unlocked"] is True


def test_blank_animation_frame_is_resampled_before_unbranded(tmp_path):
    clock = Clock()
    guest = FakeGuest(clock, ["boot", "blank_logo_prompt", "branded"])
    observed = gate(tmp_path, guest, clock).run()
    assert observed["prompt"] == "prompt_observed_branded"


def test_no_prompt_is_not_observed_and_nothing_is_typed(tmp_path):
    clock = Clock()
    guest = FakeGuest(clock, ["boot"])
    lines = []
    observed = gate(tmp_path, guest, clock, lines).run()
    assert observed["prompt"] == "prompt_not_observed"
    assert guest.keys == []
    assert "LUKS_SCREEN prompt=prompt_not_observed" in lines
    out = tmp_path / "observation"
    # The last pre-secret frame is kept for diagnosis; it is the only frame.
    assert sorted(p.name for p in out.iterdir()) == ["frame-000.ppm", "observations.json"]
    assert report(tmp_path)["retained_frame"]["sha256"] == frame_digest("boot", tmp_path)


def test_ocr_unavailable_is_not_observed(tmp_path):
    clock = Clock()
    guest = FakeGuest(clock, ["branded"])

    def no_ocr(path):
        raise luks_screen.observer.ObservationError("ocr_unavailable")

    observed = luks_screen.ScreenGate(
        tmp_path / "observation", PASSPHRASE, capture=guest.capture, ocr=no_ocr,
        sendkey=guest.sendkey, poll_serial=guest.poll_serial, clock=clock,
        sleep=clock.sleep, log=lambda line: None).run()
    assert observed["prompt"] == "prompt_not_observed" and guest.keys == []
    assert report(tmp_path)["status"] == "gate_error"


# ── Secret entry ─────────────────────────────────────────────────────────────

def test_frames_during_entry_are_never_captured_or_retained(tmp_path):
    clock = Clock()
    guest = FakeGuest(clock, ["boot", "branded"])
    lines = []
    observed = gate(tmp_path, guest, clock, lines, wrong_first=True).run()
    assert observed["unlocked"] is True
    assert not any(typing for typing, _ in guest.captures)
    out = tmp_path / "observation"
    assert sorted(p.name for p in out.iterdir()) == ["frame-000.ppm", "observations.json"]
    result = report(tmp_path)
    # The one retained frame is the pre-entry prompt, not anything later.
    assert result["retained_frame"]["sha256"] == frame_digest("branded", tmp_path)
    assert result["retained_frame"]["captured_before_secret_entry"] is True
    assert (out / "frame-000.ppm").read_bytes() == draw("branded")
    assert [e["frames_captured_during_entry"] for e in result["secret_entries"]] == [0, 0]
    after = [f for f in result["frames"] if f["phase"] != "before_secret_entry"]
    assert after and all("file" not in f for f in after)
    # Neither the passphrase nor the wrong one, nor their lengths, are recorded.
    published = (out / "observations.json").read_text() + "\n".join(lines)
    for secret in (PASSPHRASE, *luks_screen.WRONG_PASSPHRASES):
        assert secret not in published
    assert "keys" not in json.dumps(result["secret_entries"])


def test_capture_during_entry_is_refused(tmp_path):
    clock = Clock()
    guest = FakeGuest(clock, ["branded"])
    screen = gate(tmp_path, guest, clock)
    original = guest.sendkey

    def sendkey_with_concurrent_capture(key):
        original(key)
        if key != "ret":
            screen._frame("before_secret_entry", retain=True)

    screen._sendkey = sendkey_with_concurrent_capture
    screen.run()
    result = report(tmp_path)
    assert result["status"] == "gate_error"
    assert result["error_category"] == "capture_during_secret_entry"
    assert not any(typing for typing, _ in guest.captures)
    assert result["retained_frame"]["sha256"] == frame_digest("branded", tmp_path)


def test_untypeable_passphrase_is_refused_before_any_key(tmp_path):
    clock = Clock()
    guest = FakeGuest(clock, ["branded"])
    with pytest.raises(luks_screen.ScreenGateError) as error:
        gate(tmp_path, guest, clock, passphrase="pässword")
    assert "ä" not in str(error.value) and guest.keys == []
    assert not (tmp_path / "observation").exists()


def test_diagnostic_boot_observes_and_never_types(tmp_path):
    clock = Clock()
    guest = FakeGuest(clock, ["boot", "branded"])
    observed = gate(tmp_path, guest, clock, diagnostic=True, wrong_first=True).run()
    assert observed["prompt"] == "prompt_observed_branded"
    assert guest.keys == []
    assert report(tmp_path)["status"] == "diagnostic_stopped_at_prompt"


# ── Wrong passphrase ─────────────────────────────────────────────────────────

def test_wrong_passphrase_is_rejected_then_the_passphrase_unlocks(tmp_path):
    clock = Clock()
    guest = FakeGuest(clock, ["boot", "branded"])
    lines = []
    observed = gate(tmp_path, guest, clock, lines, wrong_first=True).run()
    assert guest.entries[0] != PASSPHRASE and guest.entries[1] == PASSPHRASE
    assert observed["wrong_password"] == "rejected"
    assert observed["unlocked"] is True
    result = report(tmp_path)
    assert [e["kind"] for e in result["secret_entries"]] == ["wrong_passphrase", "passphrase"]
    assert result["serial"]["root_after_wrong_password"] is False
    assert result["rejection_text_seen"] is True
    # Separate observations, in order.
    assert [line for line in lines if line.startswith("LUKS_SCREEN ")][:3] == [
        "LUKS_SCREEN prompt=prompt_observed_branded",
        "LUKS_SCREEN wrong_password=rejected",
        "LUKS_SCREEN unlocked=yes",
    ]


def test_wrong_passphrase_that_mounts_root_fails(tmp_path):
    clock = Clock()
    guest = FakeGuest(clock, ["branded"], accept_any=True,
                      serial_after_unlock=b"TUNAOS_DESKTOP_CONTRACT_OK\n")
    observed = gate(tmp_path, guest, clock, wrong_first=True).run()
    assert observed["wrong_password"] == "accepted"
    assert observed["unlocked"] is False
    assert len(guest.entries) == 1  # the real passphrase is never typed
    result = report(tmp_path)
    assert result["status"] == "wrong_password_accepted"
    assert result["serial"]["root_after_wrong_password"] is True


def test_wrong_passphrase_without_a_returning_prompt_fails(tmp_path):
    clock = Clock()
    guest = FakeGuest(clock, ["branded"], reprompt=False)
    observed = gate(tmp_path, guest, clock, wrong_first=True).run()
    assert observed["wrong_password"] == "not_rejected"
    assert len(guest.entries) == 1
    assert report(tmp_path)["status"] == "wrong_password_not_rejected"


def test_passphrase_that_leaves_the_prompt_is_not_unlocked(tmp_path):
    clock = Clock()
    guest = FakeGuest(clock, ["branded"], passphrase="something-else")
    observed = gate(tmp_path, guest, clock).run()
    assert observed["unlocked"] is False
    assert report(tmp_path)["status"] == "not_unlocked"


# ── luks-first-boot.py screen mode ───────────────────────────────────────────

def run_script(tmp_path, monkeypatch, guest_options, serial, wrong_first="0"):
    guests = []

    def production(output, vnc, monitor, passphrase, **options):
        clock = Clock()
        clock.now = options["clock"]()  # the script's (fake) time
        guest = FakeGuest(clock, **guest_options)
        guests.append(guest)
        return luks_screen.ScreenGate(output, passphrase, capture=guest.capture,
                                      ocr=fake_ocr, sendkey=guest.sendkey, **options)

    monkeypatch.setattr(luks_screen, "production", production)
    monkeypatch.setenv("TUNAOS_LUKS_SCREEN_OUTPUT", str(tmp_path / "observation"))
    monkeypatch.setenv("TUNAOS_LUKS_SCREEN_WRONG_FIRST", wrong_first)
    monkeypatch.delenv("TUNAOS_LUKS_GRUB_APPEND", raising=False)
    monkeypatch.delenv("TUNAOS_INSTALLED_BOOT_DIAGNOSTIC", raising=False)
    res = harness._run(harness._argv(timeout="900", passphrase=PASSPHRASE), serial_chunks=serial)
    return res, guests[0]


def test_script_unlocks_on_screen_and_never_types_into_serial(tmp_path, monkeypatch):
    res, guest = run_script(
        tmp_path, monkeypatch, {"boot": ["boot", "branded"]},
        [b"Please enter passphrase for disk root:\n"] + [b"\n"] * 8
        + [b"TUNAOS_DESKTOP_CONTRACT_OK\n"],
        wrong_first="1",
    )
    assert res["exit_code"] == 0, res["stdout"]
    assert res["serial_sent"] == ""
    assert guest.entries[-1] == PASSPHRASE
    for line in ("LUKS_SCREEN prompt=prompt_observed_branded", "LUKS_SCREEN wrong_password=rejected",
                 "LUKS_SCREEN unlocked=yes", "LUKS_SCREEN reached_session=yes"):
        assert line in res["stdout"]
    assert PASSPHRASE not in res["stdout"]
    result = report(tmp_path)
    assert result["observations"]["reached_session"] is True
    assert result["serial"]["prompt_seen"] is True


def test_script_without_screen_prompt_exits_2_even_with_serial_prompt(tmp_path, monkeypatch):
    res, guest = run_script(
        tmp_path, monkeypatch, {"boot": ["boot"]},
        [b"Please enter passphrase for disk root:\n"],
    )
    assert res["exit_code"] == 2
    assert "!!! passphrase prompt never appeared" in res["stdout"]
    assert res["serial_sent"] == "" and guest.keys == []


def test_script_fails_when_the_wrong_passphrase_unlocks(tmp_path, monkeypatch):
    # The script's own serial carries the guest's root evidence right after
    # the wrong passphrase was submitted.
    res, guest = run_script(
        tmp_path, monkeypatch, {"boot": ["branded"], "accept_any": True},
        [b"\n", b"\n", b"\n", b"TUNAOS_DESKTOP_CONTRACT_OK\n"], wrong_first="1",
    )
    assert len(guest.entries) == 1
    assert res["exit_code"] == 6
    assert "LUKS_SCREEN wrong_password=accepted" in res["stdout"]


def test_script_refuses_grub_edits_with_the_screen_gate(tmp_path, monkeypatch):
    monkeypatch.setenv("TUNAOS_LUKS_SCREEN_OUTPUT", str(tmp_path / "observation"))
    monkeypatch.setenv("TUNAOS_LUKS_GRUB_APPEND", "console=ttyS0")
    res = harness._run(harness._argv(passphrase=PASSPHRASE), serial_chunks=[b"\n"])
    assert res["exit_code"] == 5
    assert not (tmp_path / "observation").exists()


# ── iso-e2e.sh: nothing else captures the screen during the unlock ───────────

def test_strict_luks_boots_run_no_concurrent_frame_capture():
    source = (ROOT / "scripts/iso-e2e.sh").read_text()
    body = source[source.index("verify_strict_installed_boot() {"):
                  source.index("emit_qualification_evidence() {")]
    assert body.count("TUNAOS_LUKS_SCREEN_OUTPUT=") == 2
    for forbidden in ("setsid", "observe-installed-boot", "screendump", "record-timelapse"):
        assert forbidden not in body
