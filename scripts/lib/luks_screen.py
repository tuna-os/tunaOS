"""Screen path of the encrypted installed-boot gate (tunaOS#4090, #3380).

The installed system boots with `rhgb quiet` and no serial console, so the
cryptsetup prompt is painted by Plymouth on the framebuffer and never reaches
the serial port. This gate reads the framebuffer the way a person would:

  1. poll frames until the unlock prompt is visible, and decide whether it is
     the branded Plymouth prompt or the plain text-console fallback;
  2. keep exactly ONE frame, taken before any key is pressed (it cannot
     contain secret-derived pixels);
  3. optionally type a wrong passphrase and require the prompt to come back
     while serial shows no root file system;
  4. type the passphrase and require the prompt to go away.

No frame is captured between the first key and the submitting Return: the
entry field is the only place secret-derived pixels (bullets) can appear, and
the capture function refuses to run while an entry is in progress. Frames
taken after a submit are analysed and deleted, never retained.

The serial port stays an independent signal: a serial prompt is recorded, and
serial evidence of a mounted root after a WRONG passphrase fails the gate.

Outcomes, in observations.json and as `LUKS_SCREEN <key>=<value>` lines:
  prompt          prompt_observed_branded | prompt_observed_unbranded |
                  prompt_not_observed
  wrong_password  rejected | accepted | not_rejected | not_attempted
  unlocked        yes | no
  emergency       yes (only when the initramfs entered emergency mode before
                  any prompt; status emergency_observed)
  reached_session yes | no  (set by luks-first-boot.py from the serial
                            desktop contract marker)
"""

import importlib.util
import os
import re
import time
from pathlib import Path

from lib.qemu_monitor import command as monitor_command
from lib.visual_console import key_for

_SCRIPTS = Path(__file__).resolve().parents[1]


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, _SCRIPTS / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# Bounded read-only VNC capture, frame validation, bounded tesseract run and
# the frame labels come from the installed-boot observer; keyword matching
# comes from the install checkpoint OCR. One implementation of each.
observer = _load("installed_boot_observer", "observe-installed-boot.py")
checkpoints = _load("install_checkpoints", "install-checkpoints.py")

PROMPT_OBSERVED_BRANDED = "prompt_observed_branded"
PROMPT_OBSERVED_UNBRANDED = "prompt_observed_unbranded"
PROMPT_NOT_OBSERVED = "prompt_not_observed"

PROMPT_WORDS = ("password", "passphrase")
REJECTION_WORDS = ("try again", "incorrect", "no key available")
SERIAL_PROMPT_RE = re.compile(
    rb"passphrase for disk|please enter passphrase|enter passphrase for", re.I
)
# Anything that only happens once the root file system is unlocked and mounted.
SERIAL_ROOT_RE = re.compile(
    rb"Reached target [^\n]*(?:Switch Root|Initrd Root File System|Multi-User System)"
    rb"|Mounted [^\n]*sysroot|login:|TUNAOS_DESKTOP_CONTRACT_|TUNAOS_IMAGE_IDENTITY",
    re.I,
)
SERIAL_EMERGENCY = b"Entering emergency mode"

# Geometry of every TunaOS Plymouth theme
# (system_files/usr/share/plymouth/themes/*/*.script): a 200x200 sprite
# centred on a black window, the prompt PROMPT_GAP=28 px below it and the
# entry ("Enter disk password" until a key is pressed) ENTRY_GAP=10 px below
# the prompt. The text console fallback prints the prompt from column 0.
LOGO_SIDE = 200
PROMPT_BAND = 160
# Pixels whose brightest channel reaches this are drawn, not background.
INK_LEVEL = 48
LOGO_INK_FRACTION = 0.02
# Animated themes have blank sprite frames (dragon, rainbow, shark start
# empty), so a prompt with an empty logo square is re-sampled before it is
# called the text-console fallback.
UNBRANDED_CONFIRMATIONS = 3

# ── Time budget ─────────────────────────────────────────────────────
# Every wait the gate makes, so a caller that bounds the whole first boot
# (candidate-bounded.py in iso-e2e.sh) can cover it instead of killing a slow
# boot in the middle of a secret entry. first_boot_seconds() is the total.
PROMPT_TIMEOUT_MAX = 600
POLL_INTERVAL = 5
SETTLE = 8
VERDICT_TIMEOUT = 180
# One poll: a serial read (luks-first-boot.py's 5 s socket timeout), a VNC
# capture (5 s) that may fall back to an HMP screendump (10 s socket
# timeout), and two bounded OCR runs (10 s each).
SERIAL_READ_MAX = 5
VNC_CAPTURE_MAX = 5
SCREENDUMP_MAX = 10
OCR_MAX = 10
POLL_MAX = SERIAL_READ_MAX + VNC_CAPTURE_MAX + SCREENDUMP_MAX + 2 * OCR_MAX
# One entry: a serial read for the mark, then every key of the longest
# passphrase lib/luks_secret.py accepts (256) plus Return, each paced by
# KEY_INTERVAL and allowed KEY_SEND_MAX for its HMP round trip.
KEY_INTERVAL = 0.05
KEY_SEND_MAX = 0.2
MAX_PASSPHRASE_KEYS = 256
ENTRY_MAX = SERIAL_READ_MAX + (MAX_PASSPHRASE_KEYS + 1) * (KEY_INTERVAL + KEY_SEND_MAX)
# After the unlock luks-first-boot.py waits for userspace, then the 60 s
# first-boot enrollment window, then the desktop contract wait.
USERSPACE_WAIT = 240
ENROLLMENT_WINDOW = 60
# Emergency harvest (3 + 5 + 30 s drain) or the graceful powerdown (5
# connect tries + 8 s), plus the TERM grace of the outer bound.
EXIT_MARGIN = 60


def gate_seconds(wrong_first, prompt_timeout=PROMPT_TIMEOUT_MAX, interval=POLL_INTERVAL,
                 verdict_timeout=VERDICT_TIMEOUT):
    """Longest ScreenGate.run(): each phase may overrun its deadline by one poll."""
    poll = POLL_MAX + interval
    entries = 2 if wrong_first else 1
    return prompt_timeout + poll + entries * (ENTRY_MAX + verdict_timeout + poll)


def post_unlock_seconds(contract_wait):
    return USERSPACE_WAIT + ENROLLMENT_WINDOW + contract_wait


def first_boot_seconds(timeout, contract_wait, wrong_first):
    """Longest luks-first-boot.py run in screen mode, in whole seconds."""
    total = (gate_seconds(wrong_first, prompt_timeout=min(PROMPT_TIMEOUT_MAX, timeout))
             + post_unlock_seconds(contract_wait) + EXIT_MARGIN)
    return int(total) + (total > int(total))


RETAINED_FRAME = "frame-000.ppm"
POLL_FRAME = "poll.ppm"
MAX_FRAME_RECORDS = 400
WRONG_PASSPHRASES = ("tunaos-wrong-passphrase", "tunaos-wrong-passphrase-2")

_PPM_HEADER = re.compile(rb"P6\n([0-9]{1,4}) ([0-9]{1,4})\n255\n")
# install-checkpoints.py's measured dark-UI recipe (negate, level 10%..90%),
# as one byte table so it costs one bytes.translate per frame.
_DARK_UI = bytes(
    max(0, min(255, round(((255 - value) - 25.5) * 255 / 204))) for value in range(256)
)


class ScreenGateError(Exception):
    """Only fixed, non-secret category strings may be supplied."""


def read_ppm(path):
    data = Path(path).read_bytes()
    header = _PPM_HEADER.match(data)
    if not header:
        raise ScreenGateError("invalid_frame")
    width, height = int(header.group(1)), int(header.group(2))
    pixels = data[header.end():]
    if not (width and height) or len(pixels) != width * height * 3:
        raise ScreenGateError("invalid_frame")
    return width, height, pixels


def write_ppm(path, width, height, pixels):
    with open(path, "xb") as stream:
        stream.write(b"P6\n%d %d\n255\n" % (width, height))
        stream.write(pixels)


def crop(width, height, pixels, x0, y0, x1, y1):
    x0, x1 = max(0, x0), min(width, x1)
    y0, y1 = max(0, y0), min(height, y1)
    if x1 <= x0 or y1 <= y0:
        return 0, 0, b""
    rows = [pixels[(y * width + x0) * 3:(y * width + x1) * 3] for y in range(y0, y1)]
    return x1 - x0, y1 - y0, b"".join(rows)


def logo_box(width, height):
    side = min(LOGO_SIDE, width, height)
    left, top = width // 2 - side // 2, height // 2 - side // 2
    return left, top, left + side, top + side


def prompt_band(width, height):
    _, _, _, logo_bottom = logo_box(width, height)
    return width // 6, logo_bottom, width - width // 6, logo_bottom + PROMPT_BAND


def logo_present(width, height, pixels):
    """Whether the theme's sprite square holds drawn pixels, not empty black."""
    box_w, box_h, box = crop(width, height, pixels, *logo_box(width, height))
    if not box:
        return False
    drawn = sum(
        1 for i in range(0, len(box), 3) if max(box[i], box[i + 1], box[i + 2]) >= INK_LEVEL
    )
    return drawn >= LOGO_INK_FRACTION * box_w * box_h


def _ocr_copy(path, width, height, pixels, scale):
    """Dark-on-light copy for tesseract; light-on-dark text reads as nothing."""
    light = pixels.translate(_DARK_UI)
    if scale == 2:
        rows = []
        stride = width * 3
        for y in range(height):
            row = light[y * stride:(y + 1) * stride]
            doubled = b"".join(row[i:i + 3] * 2 for i in range(0, stride, 3))
            rows.append(doubled)
            rows.append(doubled)
        light, width, height = b"".join(rows), width * 2, height * 2
    write_ppm(path, width, height, light)


def _says(text, words):
    flat = checkpoints.normalize(text or "")
    tight = checkpoints.despace(flat)
    return any(word in flat or checkpoints.despace(word) in tight for word in words)


def analyse(frame, ocr, scratch):
    """Label one frame. Only booleans and a fixed label leave this function."""
    width, height, pixels = read_ppm(frame)
    center = scratch / "ocr-center.ppm"
    full = scratch / "ocr-full.ppm"
    try:
        band = crop(width, height, pixels, *prompt_band(width, height))
        center_text = ""
        if band[2]:
            _ocr_copy(center, *band, scale=2)
            center_text = ocr(center)
        _ocr_copy(full, width, height, pixels, scale=1)
        full_text = ocr(full)
    finally:
        for path in (center, full):
            if path.exists():
                path.unlink()
    centred = _says(center_text, PROMPT_WORDS)
    anywhere = centred or _says(full_text, PROMPT_WORDS)
    logo = logo_present(width, height, pixels)
    branded = centred and logo
    if branded:
        label = "prompt_branded"
    elif anywhere:
        label = "prompt_unbranded"
    else:
        label = observer.classify(full_text)
    return {
        "label": label,
        "prompt": anywhere,
        "branded": branded,
        "prompt_centred": centred,
        "logo": logo,
        "rejection_text": _says(center_text + "\n" + full_text, REJECTION_WORDS),
    }


def _category(error):
    """A fixed label: exception text never reaches the report."""
    if isinstance(error, ScreenGateError):
        return str(error)
    if isinstance(error, observer.ObservationError):
        category = str(error)
        return category if category in observer.ERROR_CATEGORIES else "observer_internal_error"
    if isinstance(error, OSError):
        return "local_io_error"
    return "internal_error"


class ScreenGate:
    """Drive the encrypted boot's unlock prompt on screen.

    capture(path) writes one P6 frame; ocr(path) returns text; sendkey(name)
    presses one key; poll_serial() returns every serial byte seen so far.
    """

    def __init__(self, output, passphrase, *, capture, ocr, sendkey, poll_serial,
                 clock, sleep, log, wrong_first=False, diagnostic=False,
                 prompt_timeout=PROMPT_TIMEOUT_MAX, interval=POLL_INTERVAL, settle=SETTLE,
                 verdict_timeout=VERDICT_TIMEOUT):
        self._passphrase_keys = self._keys(passphrase)
        wrong = next(w for w in WRONG_PASSPHRASES if w != passphrase)
        self._wrong_keys = self._keys(wrong)
        output = Path(output)
        output.mkdir(mode=0o700, parents=False, exist_ok=False)
        self.output = output
        self._capture_frame = capture
        self._ocr = ocr
        self._sendkey = sendkey
        self._poll_serial = poll_serial
        self.clock = clock
        self.sleep = sleep
        self.log = log
        self.wrong_first = wrong_first
        self.diagnostic = diagnostic
        self.prompt_timeout = prompt_timeout
        self.interval = interval
        self.settle = settle
        self.verdict_timeout = verdict_timeout
        self.started = clock()
        self.captures = 0
        self._entering = False
        self._serial_mark = 0
        self.emergency = None
        self.report = {
            "kind": "installed_boot_screen_gate",
            "qualified": False,
            "status": "observing",
            "observations": {
                "prompt": PROMPT_NOT_OBSERVED,
                "wrong_password": "not_attempted",
                "unlocked": False,
                "emergency": False,
                "reached_session": False,
            },
            "serial": {"prompt_seen": False, "root_after_wrong_password": False},
            "frames": [],
            "secret_entries": [],
            "errors": [],
        }
        self._write()

    @staticmethod
    def _keys(secret):
        keys = [key_for(char) for char in secret]
        if not keys or None in keys:
            # Never name the character: it is part of a secret.
            raise ScreenGateError("passphrase_not_typeable")
        return keys

    # ── evidence ─────────────────────────────────────────────────────
    def _write(self):
        observer.write_report(self.output, self.report)

    def _observe(self, key, value):
        self.report["observations"][key] = value
        shown = ("yes" if value else "no") if isinstance(value, bool) else value
        self.log(f"LUKS_SCREEN {key}={shown}")
        self._write()

    def _finish(self, status):
        self.report["status"] = status
        self.log(f"LUKS_SCREEN status={status}")
        self._write()
        return self.report["observations"]

    def _serial(self):
        data = self._poll_serial()
        if not self.report["serial"]["prompt_seen"] and SERIAL_PROMPT_RE.search(data):
            self.report["serial"]["prompt_seen"] = True
        return data

    def _frame(self, phase, retain):
        """Capture and label one frame. retain=False deletes it afterwards."""
        if self._entering:
            raise ScreenGateError("capture_during_secret_entry")
        poll = self.output / POLL_FRAME
        if poll.exists():
            poll.unlink()
        self.captures += 1
        try:
            self._capture_frame(poll)
            # Validate the bounded P6 frame before any OCR process sees it.
            digest = observer.frame_digest(poll)
            verdict = analyse(poll, self._ocr, self.output)
        except Exception as error:  # noqa: BLE001 - persist a fixed category only
            if poll.exists():
                poll.unlink()
            category = _category(error)
            if len(self.report["errors"]) < MAX_FRAME_RECORDS:
                self.report["errors"].append({"phase": phase, "category": category})
            if category == "ocr_unavailable":
                raise ScreenGateError("ocr_unavailable") from None
            return None
        record = {
            "phase": phase,
            "elapsed_seconds": round(self.clock() - self.started, 3),
            "sha256": digest,
            "classification": verdict["label"],
        }
        if retain:
            os.replace(poll, self.output / RETAINED_FRAME)
            self.report["retained_frame"] = dict(
                record, file=RETAINED_FRAME, captured_before_secret_entry=True
            )
        else:
            poll.unlink()
        if len(self.report["frames"]) < MAX_FRAME_RECORDS:
            self.report["frames"].append(record)
        return verdict

    # ── phases ───────────────────────────────────────────────────────
    def await_prompt(self):
        deadline = self.clock() + self.prompt_timeout
        unbranded = 0
        outcome = PROMPT_NOT_OBSERVED
        while True:
            serial = self._serial()
            if SERIAL_EMERGENCY in serial:
                self.report["serial"]["emergency_seen"] = True
                self.emergency = "serial"
                break
            # Every frame here precedes any key press, so the newest one
            # replaces the single retained frame.
            verdict = self._frame("before_secret_entry", retain=True)
            if verdict is not None:
                if verdict["branded"]:
                    outcome = PROMPT_OBSERVED_BRANDED
                    break
                if verdict["prompt"]:
                    unbranded += 1
                    if unbranded >= UNBRANDED_CONFIRMATIONS:
                        outcome = PROMPT_OBSERVED_UNBRANDED
                        break
                else:
                    unbranded = 0
                if verdict["label"] == "emergency":
                    self.emergency = "screen"
                    break
            if self.clock() >= deadline:
                break
            self.sleep(self.interval)
        self._observe("prompt", outcome)
        return outcome

    def _enter(self, keys, kind):
        captures = self.captures
        self._serial_mark = len(self._poll_serial())
        self._entering = True
        try:
            for key in keys + ["ret"]:
                self._sendkey(key)
                # The same pacing as iso-e2e.sh's send_text: one key at a time.
                self.sleep(KEY_INTERVAL)
        except ScreenGateError:
            raise
        except Exception:  # noqa: BLE001 - never echo a key or monitor reply
            raise ScreenGateError("sendkey_failed") from None
        finally:
            self._entering = False
        self.report["secret_entries"].append(
            {"kind": kind, "frames_captured_during_entry": self.captures - captures}
        )
        self._write()
        return self.clock()

    def _root_on_serial(self):
        return bool(SERIAL_ROOT_RE.search(self._serial()[self._serial_mark:]))

    def await_rejection(self, submitted):
        """The wrong passphrase must bring the prompt back with no root mounted.

        Two consecutive prompt frames after the settle time: a prompt that only
        lingered while an accepted key switched root would not survive both,
        and serial evidence of a mounted root fails the entry outright.
        """
        deadline = submitted + self.verdict_timeout
        self.sleep(self.settle)
        result = "not_rejected"
        prompts = 0
        rejection_text = False
        while True:
            if self._root_on_serial():
                self.report["serial"]["root_after_wrong_password"] = True
                result = "accepted"
                break
            verdict = self._frame("after_wrong_submit", retain=False)
            if verdict is not None:
                prompts = prompts + 1 if verdict["prompt"] else 0
                rejection_text = rejection_text or verdict["rejection_text"]
                if prompts >= 2:
                    result = "rejected"
                    break
            if self.clock() >= deadline:
                break
            self.sleep(self.interval)
        self.report["rejection_text_seen"] = rejection_text
        self._observe("wrong_password", result)
        return result

    def await_unlock(self, submitted):
        """The passphrase must take the prompt away (screen) or mount root (serial)."""
        deadline = submitted + self.verdict_timeout
        self.sleep(self.settle)
        cleared = 0
        signal = None
        while True:
            if self._root_on_serial():
                signal = "serial"
                break
            verdict = self._frame("after_submit", retain=False)
            if verdict is not None:
                cleared = 0 if verdict["prompt"] else cleared + 1
                if cleared >= 2:
                    signal = "screen"
                    break
            if self.clock() >= deadline:
                break
            self.sleep(self.interval)
        self.report["unlock_signal"] = signal
        self._observe("unlocked", signal is not None)
        return signal is not None

    def run(self):
        """Return the observations; the caller maps them to exit statuses."""
        try:
            if self.await_prompt() == PROMPT_NOT_OBSERVED:
                if self.emergency:
                    # Initramfs gave up before any prompt: a distinct outcome
                    # the caller harvests, not a prompt that failed to paint.
                    self._observe("emergency", True)
                    return self._finish("emergency_observed")
                return self._finish("prompt_not_observed")
            if self.diagnostic:
                # Diagnostic boots observe the prompt and never unlock.
                return self._finish("diagnostic_stopped_at_prompt")
            if self.wrong_first:
                submitted = self._enter(self._wrong_keys, "wrong_passphrase")
                result = self.await_rejection(submitted)
                if result != "rejected":
                    return self._finish("wrong_password_" + result)
            submitted = self._enter(self._passphrase_keys, "passphrase")
            if not self.await_unlock(submitted):
                return self._finish("not_unlocked")
            return self._finish("unlocked")
        except Exception as error:  # noqa: BLE001 - persist a fixed category only
            self.report["error_category"] = _category(error)
            return self._finish("gate_error")

    def reached_session(self, reached):
        self._observe("reached_session", bool(reached))


def production(output, vnc, monitor, passphrase, **options):
    """The real VM: VNC capture (HMP screendump fallback), tesseract, HMP sendkey."""

    def capture(path):
        try:
            observer.vnc_capture(vnc, path, time.monotonic() + VNC_CAPTURE_MAX)
        except observer.ObservationError:
            if Path(path).exists():
                Path(path).unlink()
            # Plain -vga virtio scanout: QEMU writes the same P6 frame itself.
            monitor_command(monitor, f"screendump {path}")

    def ocr(path):
        return observer.ocr_frame(path, time.monotonic() + OCR_MAX)

    def sendkey(key):
        monitor_command(monitor, f"sendkey {key}")

    return ScreenGate(output, passphrase, capture=capture, ocr=ocr, sendkey=sendkey, **options)


if __name__ == "__main__":
    # `python3 -m lib.luks_screen budget <timeout> <contract_wait> <wrong_first>`
    # prints first_boot_seconds() for the outer bound in iso-e2e.sh.
    import sys

    if len(sys.argv) != 5 or sys.argv[1] != "budget":
        raise SystemExit("usage: luks_screen budget <timeout> <contract_wait> <wrong_first 0|1>")
    print(first_boot_seconds(int(sys.argv[2]), int(sys.argv[3]), sys.argv[4] == "1"))
