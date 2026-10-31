#!/usr/bin/env python3
"""OCR-assert the screenshots an install run left behind.

scripts/iso-e2e.sh already photographs the pipeline: 10-ready when the live
session comes up, 30-installed / installed-desktop after the installed disk
reboots, installed-tpm-autounlock on the no-passphrase boot. Until now those
frames were only ever *uploaded* — a human had to open them to find out
whether the image worked. Every interesting failure (a compositor that never
started, a black screen behind a running installer, an installed disk sitting
in an emergency shell or at an unanswered LUKS prompt) still produces a
perfectly valid PNG, so "a screenshot exists" asserts nothing.

This reads each frame, OCRs it, and checks it against the checkpoint contract
in tests/install-pipeline-screens.yaml:

  1. PRESENT  — the frame the stage should have produced is there at all.
  2. RENDERS  — it has real content (grayscale stddev above a floor), which is
                what catches a black screen the serial log calls a success.
  3. SAYS     — its text matches the checkpoint's keywords, so we know WHICH
                screen was reached, not just that something was drawn.
  4. CLEAN    — its text contains none of the checkpoint's forbidden strings
                (panics, emergency shells, a LUKS prompt still waiting after
                the passphrase was supposedly accepted).
  5. FRESH    — (distinct_from) it is not pixel-identical to an earlier
                stage's frame, i.e. not the previous screen photographed again.
  6. IDENTITY — (regions) crops of it say their keywords and match the
                artwork this repo ships, by perceptual hash — whose screen it
                is, not just which screen.

The installer's own pages are NOT asserted here — that is
scripts/installer-walkthrough.py's contract (tests/installer-screens.yaml),
which drives the frontend and OCRs each page as it steps through it. When that
harness has run in the same evidence directory, its walkthrough-<desktop>.json
is folded into this summary so one artifact reports the whole pipeline.

Output is TAP on stdout plus a JSON summary and a labelled contact sheet, both
written next to the frames for CI artifact upload.

Usage:
  install-checkpoints.py <evidence-dir> [--flavor kde] [--variant marlin]
                         [--spec FILE] [--phase live|installed]
                         [--json FILE] [--sheet FILE] [--strict]

Exit: number of enforced failures (0 = the pipeline looked right on screen).
      77 if OCR is unavailable and --strict was given, or if there was no
         enforced failure but a required checkpoint could not be judged
         (outcome "not-run": tesseract or ImageMagick missing) — a missing
         dependency is never reported as a pass.
      78 if the contract is not a valid schema_version 1 document.

Every checkpoint in the JSON summary carries an `outcome` (passed, failed,
blocked, not-run or unsupported — see classify())
and a stable `reason` token, so a consumer reads the verdict per checkpoint
instead of inferring it from which TAP lines happened to be printed.
"""
import argparse
import glob
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

# Same floor scripts/iso-e2e.sh and installer-walkthrough.py use for "this
# screen looks blank" — keep the three in step, a frame is either blank or it
# is not and three different answers would be worse than a wrong one.
BLANK_STDDEV = 0.02

# ── Contract schema (tests/install-pipeline-screens.yaml) ────────────────────
# The one contract version this script reads. Anything else is refused rather
# than half-understood: a key this script does not know is a check it would
# silently not run, and a check that silently does not run is a pass nobody
# earned.
SCHEMA_VERSION = 1
DESKTOP_FAMILIES = ("kde", "gnome", "cosmic", "niri", "xfce")
PHASES = ("live", "installed")
MATCH_MODES = ("any", "all")
# crash_text and luks_prompt_text hold the YAML anchors the checkpoints'
# forbid lists alias; they are read only through those aliases.
TOP_LEVEL_KEYS = ("schema_version", "crash_text", "luks_prompt_text",
                  "needs_virgl", "checkpoints")
CHECKPOINT_KEYS = ("id", "phase", "frames", "required", "match", "keywords",
                   "forbid", "desktops", "distinct_from", "regions")
CHECKPOINT_REQUIRED_KEYS = ("id", "phase", "frames")
REGION_KEYS = ("id", "box", "keywords", "match", "artwork")
REGION_REQUIRED_KEYS = ("id", "box")
ARTWORK_KEYS = ("asset", "max_distance", "asset_box", "background")
ARTWORK_REQUIRED_KEYS = ("asset", "max_distance")
# dHash compares a 9x8 grayscale thumbnail column by column: 64 bits.
HASH_BITS = 64
EXIT_MISSING_DEPENDENCY = 77
EXIT_BAD_CONTRACT = 78

# Per-checkpoint outcomes in the JSON summary, as classify() returns them:
#   passed       every assertion that applies ran and held
#   failed       an assertion ran and did not hold
#   blocked      the frame exists but could not be read (OCR produced no text)
#   not-run      an assertion was skipped because a tool is missing on the host
#   unsupported  the host cannot render this desktop (no virgl, see
#                needs_virgl), so a blank or unreadable frame is not a verdict


class SpecError(ValueError):
    """The checkpoint contract is not a valid schema_version 1 document."""


def _check_keys(where, mapping, allowed, required=()):
    unknown = sorted(str(k) for k in mapping if k not in allowed)
    if unknown:
        raise SpecError(f"{where}: unknown key(s): {', '.join(unknown)} "
                        f"(allowed: {', '.join(sorted(allowed))})")
    missing = [k for k in required if k not in mapping]
    if missing:
        raise SpecError(f"{where}: missing key(s): {', '.join(missing)}")


def _check_strings(where, value, allow_empty_list):
    """A list of non-blank strings. A blank keyword is a substring of every
    transcript, so it would pass any screen; a bare string would be iterated
    character by character."""
    if not isinstance(value, list):
        raise SpecError(f"{where}: must be a list of strings, "
                        f"got {type(value).__name__}")
    if not value and not allow_empty_list:
        raise SpecError(f"{where}: must not be empty")
    for i, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            raise SpecError(f"{where}[{i}]: must be a non-blank string, "
                            f"got {item!r}")


def _check_desktops(where, value):
    _check_strings(where, value, allow_empty_list=True)
    unknown = sorted(d for d in value if d not in DESKTOP_FAMILIES)
    if unknown:
        raise SpecError(f"{where}: unknown desktop(s): {', '.join(unknown)} "
                        f"(allowed: {', '.join(sorted(DESKTOP_FAMILIES))})")


def _check_box(where, value):
    """[x, y, w, h], fractions of the frame, wholly inside it.

    Relative, not pixels: iso-e2e.sh captures at whatever mode the guest set,
    and a pixel box written against 1280x800 would crop the wrong thing (or
    nothing) at 1024x768.
    """
    if (not isinstance(value, list) or len(value) != 4
            or any(isinstance(v, bool) or not isinstance(v, (int, float))
                   for v in value)):
        raise SpecError(f"{where}: must be [x, y, w, h] numbers, got {value!r}")
    x, y, w, h = value
    if not (0 <= x < 1 and 0 <= y < 1 and 0 < w <= 1 and 0 < h <= 1
            and x + w <= 1 + 1e-9 and y + h <= 1 + 1e-9):
        raise SpecError(f"{where}: must lie inside the frame (0 <= x, y; "
                        f"0 < w, h; x + w <= 1; y + h <= 1), got {value!r}")


def _check_artwork(where, art):
    if not isinstance(art, dict):
        raise SpecError(f"{where}: must be a mapping, got {type(art).__name__}")
    _check_keys(where, art, ARTWORK_KEYS, required=ARTWORK_REQUIRED_KEYS)
    asset = art["asset"]
    if not isinstance(asset, str) or not asset.strip():
        raise SpecError(f"{where}.asset: must be a non-blank string, got {asset!r}")
    # The expected artwork is a file this repo ships, so a reference outside
    # the checkout would compare the frame against whatever the host has.
    if (os.path.isabs(asset) or ".." in asset.split("/")
            or re.search(r"[{}]", asset.replace("{variant}", ""))):
        raise SpecError(f"{where}.asset: must be a repo-relative path whose "
                        f"only placeholder is {{variant}}, got {asset!r}")
    dist = art["max_distance"]
    if isinstance(dist, bool) or not isinstance(dist, int) \
            or not 0 <= dist < HASH_BITS // 2:
        # Half the bits or more is what two unrelated images score: a
        # threshold there accepts any artwork at all.
        raise SpecError(f"{where}.max_distance: must be an integer in "
                        f"0..{HASH_BITS // 2 - 1}, got {dist!r}")
    if "asset_box" in art:
        _check_box(f"{where}.asset_box", art["asset_box"])
    if "background" in art and not (
            isinstance(art["background"], str)
            and re.fullmatch(r"#[0-9a-fA-F]{6}", art["background"])):
        raise SpecError(f"{where}.background: must be #rrggbb, "
                        f"got {art['background']!r}")


def _check_regions(where, regions):
    if not isinstance(regions, list) or not regions:
        raise SpecError(f"{where}: must be a non-empty list")
    seen = set()
    for j, region in enumerate(regions):
        rwhere = f"{where}[{j}]"
        if not isinstance(region, dict):
            raise SpecError(f"{rwhere}: must be a mapping, "
                            f"got {type(region).__name__}")
        _check_keys(rwhere, region, REGION_KEYS, required=REGION_REQUIRED_KEYS)
        rid = region["id"]
        if not isinstance(rid, str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]*", rid):
            # It names the crop file written into the evidence directory.
            raise SpecError(f"{rwhere}.id: must match [a-z0-9][a-z0-9-]*, "
                            f"got {rid!r}")
        if rid in seen:
            raise SpecError(f"{rwhere}.id: duplicate region id {rid!r}")
        seen.add(rid)
        rwhere = f"{where}[{j}] ({rid})"
        _check_box(f"{rwhere}.box", region["box"])
        if "keywords" in region:
            _check_strings(f"{rwhere}.keywords", region["keywords"],
                           allow_empty_list=False)
        if "match" in region and region["match"] not in MATCH_MODES:
            raise SpecError(f"{rwhere}.match: must be one of "
                            f"{', '.join(MATCH_MODES)}, got {region['match']!r}")
        if "artwork" in region:
            _check_artwork(f"{rwhere}.artwork", region["artwork"])
        if "keywords" not in region and "artwork" not in region:
            raise SpecError(f"{rwhere}: needs keywords, artwork or both "
                            "(a region with neither asserts nothing)")


def validate_spec(doc):
    """Check a parsed contract against the schema_version 1 shape; return it.

    Raises SpecError with a deterministic message naming the first offending
    path. MEASURED/DERIVED provenance lives in YAML comments, which the parser
    never sees, so it is deliberately not part of the checked shape.
    """
    if not isinstance(doc, dict):
        raise SpecError(f"contract: must be a mapping, got {type(doc).__name__}")
    if "schema_version" not in doc:
        raise SpecError("schema_version: missing (this script reads "
                        f"schema_version {SCHEMA_VERSION})")
    version = doc["schema_version"]
    if isinstance(version, bool) or not isinstance(version, int):
        raise SpecError(f"schema_version: must be an integer, got {version!r}")
    if version != SCHEMA_VERSION:
        raise SpecError(f"schema_version: unsupported value {version} "
                        f"(this script reads schema_version {SCHEMA_VERSION})")
    _check_keys("contract", doc, TOP_LEVEL_KEYS, required=("checkpoints",))
    for key in ("crash_text", "luks_prompt_text"):
        if key in doc:
            _check_strings(key, doc[key], allow_empty_list=False)
    if "needs_virgl" in doc:
        _check_desktops("needs_virgl", doc["needs_virgl"])

    checkpoints = doc["checkpoints"]
    if not isinstance(checkpoints, list) or not checkpoints:
        raise SpecError("checkpoints: must be a non-empty list")
    seen = {}
    for i, cp in enumerate(checkpoints):
        where = f"checkpoints[{i}]"
        if not isinstance(cp, dict):
            raise SpecError(f"{where}: must be a mapping, got {type(cp).__name__}")
        if isinstance(cp.get("id"), str) and cp["id"].strip():
            where = f"checkpoints[{i}] ({cp['id']})"
        _check_keys(where, cp, CHECKPOINT_KEYS, required=CHECKPOINT_REQUIRED_KEYS)
        cid = cp["id"]
        if not isinstance(cid, str) or not cid.strip():
            raise SpecError(f"{where}.id: must be a non-blank string, got {cid!r}")
        if cid in seen:
            raise SpecError(f"{where}.id: duplicate of checkpoints[{seen[cid]}]")
        seen[cid] = i
        if cp["phase"] not in PHASES:
            raise SpecError(f"{where}.phase: must be one of "
                            f"{', '.join(PHASES)}, got {cp['phase']!r}")
        _check_strings(f"{where}.frames", cp["frames"], allow_empty_list=False)
        if "required" in cp and not isinstance(cp["required"], bool):
            raise SpecError(f"{where}.required: must be true or false, "
                            f"got {cp['required']!r}")
        if "match" in cp and cp["match"] not in MATCH_MODES:
            raise SpecError(f"{where}.match: must be one of "
                            f"{', '.join(MATCH_MODES)}, got {cp['match']!r}")
        for key in ("keywords", "forbid"):
            if key in cp:
                _check_strings(f"{where}.{key}", cp[key], allow_empty_list=True)
        if "desktops" in cp:
            desktops = cp["desktops"]
            if not isinstance(desktops, dict):
                raise SpecError(f"{where}.desktops: must be a mapping, "
                                f"got {type(desktops).__name__}")
            _check_desktops(f"{where}.desktops", sorted(desktops, key=str))
            for family in sorted(desktops):
                # An empty override would silently fall back to the default
                # list (`desktops[family] or keywords`), so say so instead.
                _check_strings(f"{where}.desktops.{family}", desktops[family],
                               allow_empty_list=False)
        if "distinct_from" in cp:
            _check_strings(f"{where}.distinct_from", cp["distinct_from"],
                           allow_empty_list=False)
            for other in cp["distinct_from"]:
                # Earlier only: the comparison runs in contract order, so a
                # later id would have no frames yet and compare against nothing.
                if other == cid or other not in seen:
                    raise SpecError(f"{where}.distinct_from: {other!r} is not "
                                    "an earlier checkpoint id")
        if "regions" in cp:
            _check_regions(f"{where}.regions", cp["regions"])
    return doc


HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_SPEC = os.path.join(HERE, "..", "tests", "install-pipeline-screens.yaml")

_tap = []
_fails = 0


def tap(ok, desc, diagnostic="", enforced=True):
    """Record a TAP assertion. Non-enforced ones report but never fail."""
    global _fails
    print(f"{'ok' if ok else 'not ok'} - {desc}", flush=True)
    # Only explain failures: printing the diagnostic unconditionally produces
    # self-contradicting output ("ok - ..." followed by "# not found"), the
    # same trap installer-walkthrough.py documents.
    if diagnostic and not ok:
        for line in str(diagnostic).splitlines():
            print(f"  # {line}", flush=True)
    _tap.append({"ok": bool(ok), "desc": desc, "enforced": bool(enforced)})
    if not ok and enforced:
        _fails += 1


def note(msg):
    print(f"  # {msg}", flush=True)


# ── ImageMagick / tesseract resolution ───────────────────────────────────────
# IM7 makes `convert` and `compare` subcommands of `magick`; a bare `convert`
# raises FileNotFoundError there. Resolve once, the same way
# installer-walkthrough.py does.
def _im_convert():
    if shutil.which("magick"):
        return ["magick"]
    if shutil.which("convert"):
        return ["convert"]
    return None


IM = _im_convert()
HAVE_OCR = shutil.which("tesseract") is not None


def stddev(path):
    """Grayscale standard deviation in [0,1]; -1 when it cannot be measured."""
    if IM is None:
        return -1.0
    try:
        out = subprocess.run(
            IM + [path, "-colorspace", "Gray", "-format",
                  "%[fx:standard_deviation]", "info:"],
            capture_output=True, text=True, check=False).stdout.strip()
        return float(out)
    except (ValueError, OSError):
        return -1.0


def _dark_ui_variant(path):
    """A contrast-stretched, inverted, upscaled copy for light-on-dark UIs.

    MEASURED 2026-09-07 on a real marlin:kde live frame showing the Marlin
    Installer's welcome page — white text on a near-black window on a black
    desktop. Tesseract read the raw frame as ", |": nothing. The same frame
    through `-colorspace Gray -negate -level 10%,90% -resize 200%` reads
    cleanly:

        Install Marlin
        This wizard will guide you through installing Marlin onto this computer.
        You will choose a target disk and how it should be encrypted. ...

    Every TunaOS installer frontend and every greeter in the fleet is dark by
    default, so without this pass the contract reports a WORKING installer as
    "screen says nothing" — a false failure, which is the kind that gets a gate
    switched off. Inverting alone is not enough and upscaling alone is not
    enough; the level stretch is what separates the text from the panel it sits
    on, and 200% gets 12px UI text near the size tesseract is trained for.
    """
    if IM is None:
        return None
    out = os.path.splitext(path)[0] + ".darkui.png"
    r = subprocess.run(
        IM + [path, "-colorspace", "Gray", "-negate",
              "-level", "10%,90%", "-resize", "200%", out],
        check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if r.returncode == 0 and os.path.exists(out) and os.path.getsize(out) > 0:
        return out
    return None


def ocr(path):
    """OCR one frame, caching the text next to it as <frame>.ocr.txt.

    Three passes, unioned, because no single one reads every screen this
    pipeline produces:

      --psm 6  on the raw frame  — the block-of-text layout that console
                                   screens and dark-on-light pages present
      --psm 11 on the raw frame  — "sparse text", which is what finds the
                                   handful of isolated words on a display
                                   manager or an empty desktop, where psm 6
                                   frequently returns nothing at all
      --psm 6  on a dark-UI copy — see _dark_ui_variant: without it, a
                                   light-on-dark installer reads as empty
    """
    if not HAVE_OCR:
        return ""
    cache = os.path.splitext(path)[0] + ".ocr.txt"
    if os.path.exists(cache) and os.path.getmtime(cache) >= os.path.getmtime(path):
        with open(cache, errors="replace") as f:
            return f.read()
    text = []
    for psm in ("6", "11"):
        r = subprocess.run(["tesseract", path, "stdout", "--psm", psm],
                           capture_output=True, text=True, check=False)
        if r.returncode == 0:
            text.append(r.stdout)
    dark = _dark_ui_variant(path)
    if dark:
        r = subprocess.run(["tesseract", dark, "stdout", "--psm", "6"],
                           capture_output=True, text=True, check=False)
        if r.returncode == 0:
            text.append(r.stdout)
        try:
            os.remove(dark)
        except OSError as exc:
            # A leftover temp file must never fail a screenshot assertion:
            # the OCR text is already collected above, so the only thing lost
            # is disk space in a scratch dir the harness discards anyway.
            # Reported so a full or read-only TMPDIR is visible rather than
            # silent, since that WOULD eventually break the next capture.
            print(f"# note: could not remove {dark}: {exc}", file=sys.stderr)
    joined = "\n".join(text)
    try:
        with open(cache, "w") as f:
            f.write(joined)
    except OSError as exc:
        # The cache is an optimisation and an evidence artifact, not a result.
        # `joined` is returned either way, so a failure here must not turn a
        # passing checkpoint into a failing one — but it is printed, because a
        # cache that silently never writes makes every re-run pay full OCR
        # cost and leaves no .ocr.txt in the uploaded evidence.
        print(f"# note: could not write OCR cache {cache}: {exc}", file=sys.stderr)
    return joined


def normalize(text):
    """Lowercase and collapse whitespace so keywords can span OCR line breaks.

    Tesseract wraps a heading wherever the framebuffer wrapped it, so a
    two-word keyword like "get started" is regularly split across lines.
    Collapsing first is what makes multi-word keywords — the only kind the
    contract allows, since bare nouns match by accident — usable at all.
    """
    return re.sub(r"\s+", " ", text.lower())


def despace(text):
    """The same text with every space removed.

    MEASURED 2026-09-07 on a real GDM greeter frame
    (/var/tmp/utah-luks-e2e/screenshots/installed-greeter.png): tesseract read
    GNOME's "Not listed?" as "Notlisted?" — the space between the words simply
    is not in the transcript. Tight kerning at greeter font sizes does that
    often enough that a contract of multi-word headings would fail on screens
    it can plainly see, which is the worst kind of false alarm: it trains
    people to disable the gate.

    So a keyword matches if it appears in the collapsed text OR if its
    space-free form appears in the space-free text. This cannot make a keyword
    match a *different* screen — removing spaces from both sides only ever
    joins words that were already adjacent.
    """
    return re.sub(r"\s+", "", text)


def find_frames(outdir, basename):
    """Resolve a checkpoint frame basename to real files in the evidence dir.

    iso-e2e.sh writes PNGs when it can and PPMs when the capture came straight
    off the QEMU monitor without ImageMagick around; take the PNG when both
    exist, convert the PPM when it is all there is.
    """
    png = os.path.join(outdir, basename + ".png")
    ppm = os.path.join(outdir, basename + ".ppm")
    if os.path.exists(png) and os.path.getsize(png) > 0:
        return [png]
    if os.path.exists(ppm) and os.path.getsize(ppm) > 0:
        if IM is None:
            return [ppm]  # tesseract reads PPM directly; stddev will report -1
        subprocess.run(IM + [ppm, png], check=False,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if os.path.exists(png) and os.path.getsize(png) > 0:
            return [png]
        return [ppm]
    # Screenshot retries land as <name>-1.png etc. in some paths; take them
    # too rather than reporting a stage as unphotographed because the first
    # capture attempt was the one that failed.
    extra = sorted(glob.glob(os.path.join(outdir, basename + "-*.png")))
    return [p for p in extra if os.path.getsize(p) > 0]


def desktop_family(flavor):
    """kde-nvidia -> kde. Flavor tags are <desktop>[-hardware]."""
    f = (flavor or "").lower()
    for family in DESKTOP_FAMILIES:
        if f.startswith(family):
            return family
    return f or "gnome"


def load_spec(path):
    """Parse the checkpoint contract. PyYAML only — no hand-rolled fallback.

    installer-walkthrough.py ships a line-by-line fallback parser for its
    spec; this one deliberately does not. The contract uses YAML anchors so
    every checkpoint forbids the same crash strings from one list, and a
    fallback parser that silently dropped them would turn "no panic on screen"
    into an assertion that never runs — the failure mode this whole script
    exists to remove. Missing PyYAML is reported as a missing dependency (77)
    instead.

    The parsed document is then held to the schema_version 1 shape
    (validate_spec); malformed YAML and an invalid shape both raise SpecError.
    """
    import yaml
    with open(path) as f:
        try:
            doc = yaml.safe_load(f)
        except yaml.YAMLError as e:
            raise SpecError(f"not valid YAML: {e}") from e
    return validate_spec(doc)


def classify(best_dev, pixels_blind, texts, keywords, forbid, says_ok, forbidden):
    """One checkpoint's (outcome, reason, detail) once its frames were found.

    best_dev is the best measured stddev (None: no ImageMagick), texts the
    normalized OCR per frame (None: no tesseract), says_ok the keyword
    assertion's result (None: no keywords). The order is the precedence: text
    that proves a failure beats everything, a blank frame beats anything read
    off it, and only a checkpoint whose every applicable assertion actually ran
    can come out "passed".
    """
    if forbidden:
        return "failed", "forbidden-text", f"screen shows {forbidden}"
    if best_dev is not None and best_dev <= BLANK_STDDEV:
        if pixels_blind:
            return ("unsupported", "no-virgl",
                    f"blank frame (stddev {best_dev:.4f}) on a desktop that "
                    "cannot render without virgl, on a host without it")
        return ("failed", "frame-blank",
                f"best stddev {best_dev:.4f} <= {BLANK_STDDEV}")
    needs_text = bool(keywords or forbid)
    if needs_text and texts is None:
        return ("not-run", "ocr-unavailable",
                "tesseract not installed; keyword and forbidden-text "
                "assertions did not run")
    text_read = bool(texts) and any(t.strip() for t in texts.values())
    if needs_text and not text_read:
        if pixels_blind:
            return ("unsupported", "no-virgl",
                    "OCR read no text on a desktop that cannot render "
                    "without virgl, on a host without it")
        # An empty transcript satisfies every forbid list vacuously, so this
        # must never fall through to "passed".
        return ("blocked", "ocr-empty",
                "OCR produced no text for any frame (tesseract failed, timed "
                "out or read nothing)")
    if keywords and not says_ok:
        if pixels_blind:
            return ("unsupported", "no-virgl",
                    "keywords not on screen of a desktop that cannot render "
                    "without virgl, on a host without it")
        return "failed", "keyword-missing", "screen does not say the keywords"
    # Text read off the frame proves it is not blank; without that, an
    # unmeasured frame is an unchecked one.
    if best_dev is None and not text_read:
        return ("not-run", "render-unmeasured",
                "ImageMagick not installed; render assertion did not run")
    return "passed", "checks-held", ""


def conclude(record, verdict, fails_before):
    """Stamp a checkpoint's outcome on its record and hold the invariant that
    a required checkpoint that failed or was blocked is an enforced failure.

    Every "failed" path already produced one through its own assertion; the
    one that does not is a blocked forbid-only checkpoint, whose CLEAN
    assertion holds vacuously on an empty transcript.
    """
    outcome, reason, detail = verdict
    record.update(outcome=outcome, reason=reason, detail=detail)
    note(f"[{record['id']}] outcome: {outcome} ({reason})")
    if (record["required"] and outcome in ("failed", "blocked")
            and _fails == fails_before):
        tap(False, f"[{record['id']}] required checkpoint judged",
            f"{outcome}: {reason} — {detail}", enforced=True)


# ── Regions, artwork identity and stale frames ───────────────────────────────
# Whole-frame keywords say WHICH screen was reached; they cannot say whose. A
# greeter showing another variant's name, an About page with a swapped logo
# or a desktop on the wrong wallpaper all OCR as the right screen. Regions
# crop a box out of the frame and assert it on its own: keywords OCR'd off the
# crop alone (so a word elsewhere on screen cannot satisfy it), and artwork
# compared by perceptual hash against the file this repo ships.
#
# Region outcomes (`regions` in each checkpoint record):
#   passed   every assertion the region declares ran and held
#   failed   one ran and did not hold
#   blocked  the frame exists but the region could not be judged: no
#            tesseract, no Pillow, no SVG renderer, OCR read nothing, or the
#            asset names {variant} and the run gave none. Never a pass.
#   not-run  the checkpoint failed before regions were looked at (frame
#            missing or stale), so judging a crop of it would mean nothing
REPO_ROOT = os.path.normpath(os.path.join(HERE, ".."))


def _pil_image():
    """PIL.Image, or None when Pillow is not installed on this host."""
    try:
        from PIL import Image
    except ImportError:
        return None
    return Image


def frame_digest(path):
    """A digest of the frame's pixels (of its bytes without Pillow).

    Pixels, not bytes, when it can: a PPM converted to PNG, or a PNG
    re-encoded, is the same picture and must count as the same screen.
    """
    image_mod = _pil_image()
    if image_mod is not None:
        try:
            with image_mod.open(path) as img:
                rgb = img.convert("RGB")
                h = hashlib.sha256(f"{rgb.size}".encode())
                h.update(rgb.tobytes())
                return h.hexdigest()
        except OSError:
            pass
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def _pixel_box(size, box):
    width, height = size
    x, y, w, h = box
    left, top = int(round(x * width)), int(round(y * height))
    right = max(left + 1, min(width, int(round((x + w) * width))))
    bottom = max(top + 1, min(height, int(round((y + h) * height))))
    return left, top, right, bottom


def dhash(img):
    """64-bit difference hash: does each pixel of a 9x8 grayscale thumbnail
    get brighter or darker to its right. Survives scaling and mild
    compression, which a capture of a rendered asset always goes through."""
    image_mod = _pil_image()
    resample = getattr(image_mod, "Resampling", image_mod).LANCZOS
    px = img.convert("L").resize((9, 8), resample).tobytes()
    bits = 0
    for row in range(8):
        for col in range(8):
            bits = (bits << 1) | (px[row * 9 + col] > px[row * 9 + col + 1])
    return bits


def render_asset(path, background):
    """The shipped asset as an RGB image: (image, None) or (None, verdict).

    Transparent marks are flattened onto `background`, the colour they are
    drawn over on screen; SVGs go through rsvg-convert.
    """
    image_mod = _pil_image()
    if not os.path.isfile(path):
        return None, ("failed", "artwork-asset-missing",
                      f"expected asset {os.path.relpath(path, REPO_ROOT)} "
                      "does not exist")
    src = path
    tmp = None
    if path.lower().endswith(".svg"):
        if not shutil.which("rsvg-convert"):
            return None, ("blocked", "artwork-renderer-unavailable",
                          "rsvg-convert not installed; cannot render "
                          f"{os.path.relpath(path, REPO_ROOT)}")
        fd, tmp = tempfile.mkstemp(suffix=".png")
        os.close(fd)
        r = subprocess.run(["rsvg-convert", "-w", "512", "-o", tmp, path],
                           capture_output=True, text=True, check=False)
        if r.returncode != 0:
            os.remove(tmp)
            return None, ("failed", "artwork-asset-unreadable",
                          f"rsvg-convert failed on {path}: {r.stderr.strip()}")
        src = tmp
    try:
        with image_mod.open(src) as img:
            rgba = img.convert("RGBA")
    except OSError as e:
        return None, ("failed", "artwork-asset-unreadable", f"{path}: {e}")
    finally:
        if tmp:
            os.remove(tmp)
    flat = image_mod.new("RGBA", rgba.size, background)
    flat.alpha_composite(rgba)
    return flat.convert("RGB"), None


def _combine(parts):
    """Worst of several (outcome, reason, detail): failed beats blocked."""
    for outcome in ("failed", "blocked"):
        hits = [p for p in parts if p[0] == outcome]
        if hits:
            return hits[0][0], hits[0][1], "; ".join(p[2] for p in hits)
    return "passed", "checks-held", ""


def judge_region(cid, region, frames, variant, enforced):
    """Judge one region across a checkpoint's alternative frames.

    Like the whole-frame keywords, a region holds if ANY frame of the
    checkpoint satisfies it. Each crop is written next to its frame as
    <frame>.region-<id>.png, so the evidence shows exactly what was judged.
    """
    rid = region["id"]
    result = {"id": rid, "matched": [], "distance": None}
    image_mod = _pil_image()
    if image_mod is None:
        result.update(outcome="blocked", reason="pillow-unavailable",
                      detail="Pillow not installed; cannot crop the region")
        return result

    crops = []
    for path in frames:
        try:
            with image_mod.open(path) as img:
                rgb = img.convert("RGB")
        except OSError as e:
            note(f"[{cid}] region {rid}: cannot open {path}: {e}")
            continue
        crop = rgb.crop(_pixel_box(rgb.size, region["box"]))
        crop_path = os.path.splitext(path)[0] + f".region-{rid}.png"
        crop.save(crop_path)
        crops.append((crop_path, crop))
    if not crops:
        result.update(outcome="blocked", reason="frame-unreadable",
                      detail="no frame of the checkpoint could be decoded")
        return result

    parts = []
    if region.get("keywords"):
        parts.append(_judge_region_text(cid, region, crops, result, enforced))
    if "artwork" in region:
        parts.append(_judge_region_artwork(cid, region, crops, variant, result,
                                           enforced))
    outcome, reason, detail = _combine(parts)
    result.update(outcome=outcome, reason=reason, detail=detail)
    return result


def _judge_region_text(cid, region, crops, result, enforced):
    rid, keywords = region["id"], region["keywords"]
    if not HAVE_OCR:
        return ("blocked", "region-ocr-unavailable",
                f"region {rid}: tesseract not installed")
    texts = {p: normalize(ocr(p)) for p, _ in crops}
    if not any(t.strip() for t in texts.values()):
        return ("blocked", "region-ocr-empty",
                f"region {rid}: OCR read no text off the crop")
    hits = max(([k for k in keywords
                 if k.lower() in t or despace(k.lower()) in despace(t)]
                for t in texts.values()), key=len)
    result["matched"] = hits
    mode = region.get("match", "any")
    ok = len(hits) == len(keywords) if mode == "all" else bool(hits)
    quoted = ", ".join(f'"{k}"' for k in keywords)
    seen = "; ".join(f"{os.path.basename(p)}: {t[:160]}" for p, t in texts.items())
    tap(ok, f"[{cid}] region {rid} says {'one' if mode == 'any' else 'all'} "
            f"of: {quoted}",
        f"matched {hits or 'nothing'} — OCR read: {seen}", enforced=enforced)
    if ok:
        return "passed", "checks-held", ""
    return ("failed", "region-keyword-missing",
            f"region {rid} does not say {quoted} (read: {seen})")


def _judge_region_artwork(cid, region, crops, variant, result, enforced):
    rid, art = region["id"], region["artwork"]
    asset = art["asset"]
    if "{variant}" in asset:
        if not variant:
            return ("blocked", "variant-unknown",
                    f"region {rid}: asset {asset} names {{variant}} and the "
                    "run gave no --variant")
        asset = asset.replace("{variant}", variant)
    expected, verdict = render_asset(os.path.join(REPO_ROOT, asset),
                                     art.get("background", "#000000"))
    if verdict:
        return verdict
    if "asset_box" in art:
        expected = expected.crop(_pixel_box(expected.size, art["asset_box"]))
    want = dhash(expected)
    best_path, best = min(((p, bin(dhash(c) ^ want).count("1")) for p, c in crops),
                          key=lambda t: t[1])
    result["distance"] = best
    result["max_distance"] = art["max_distance"]
    ok = best <= art["max_distance"]
    tap(ok, f"[{cid}] region {rid} shows {asset}",
        f"perceptual distance {best} > {art['max_distance']} "
        f"({os.path.basename(best_path)})", enforced=enforced)
    if ok:
        return "passed", "checks-held", ""
    return ("failed", "artwork-mismatch",
            f"region {rid}: distance {best} to {asset} exceeds "
            f"{art['max_distance']}")


def with_regions(verdict, region_results, pixels_blind):
    """Fold the region outcomes into the checkpoint's classify() verdict.

    A verdict that is already failed or unsupported stands. A failed region
    beats a blocked or not-run checkpoint (a proven wrong screen is a
    verdict), and a blocked region beats a not-run or passed one — a
    checkpoint whose identity could not be judged is never "passed".
    """
    if verdict[0] in ("failed", "unsupported"):
        return verdict
    failed = [r for r in region_results if r["outcome"] == "failed"]
    if failed:
        if pixels_blind:
            return ("unsupported", "no-virgl",
                    "region assertions failed on a desktop that cannot render "
                    "without virgl, on a host without it")
        return "failed", failed[0]["reason"], "; ".join(r["detail"] for r in failed)
    if verdict[0] == "blocked":
        return verdict
    blocked = [r for r in region_results if r["outcome"] == "blocked"]
    if blocked:
        return ("blocked", blocked[0]["reason"],
                "; ".join(r["detail"] for r in blocked))
    return verdict


def contact_sheet(frames, out_path, labels):
    """Build one labelled image out of every frame, for the CI artifact.

    A reviewer opening a failed run should see the whole pipeline in one
    picture rather than downloading five PNGs and remembering what order they
    were taken in.
    """
    if IM is None or not frames:
        return False
    cmd = ["montage"] if shutil.which("montage") else None
    if shutil.which("magick"):
        cmd = ["magick", "montage"]
    if cmd is None:
        return False
    args = []
    for path, label in zip(frames, labels):
        args += ["-label", label, path]
    r = subprocess.run(cmd + args + ["-tile", "2x", "-geometry", "640x400+6+6",
                                     "-background", "#111", "-fill", "white",
                                     out_path],
                       check=False, capture_output=True, text=True)
    return r.returncode == 0 and os.path.exists(out_path)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("outdir", help="evidence directory (iso-e2e.sh --output)")
    ap.add_argument("--flavor", default=os.environ.get("FLAVOR", "gnome"))
    ap.add_argument("--variant", default=os.environ.get("VARIANT", ""))
    ap.add_argument("--spec", default=DEFAULT_SPEC)
    ap.add_argument("--phase", action="append", default=[],
                    choices=["live", "installed"],
                    help="only assert these phases (repeatable). The installer "
                         "pages are a third phase, asserted by "
                         "installer-walkthrough.py rather than by this script.")
    ap.add_argument("--json", dest="json_path", default=None)
    ap.add_argument("--sheet", dest="sheet_path", default=None)
    ap.add_argument("--no-gpu", action="store_true",
                    help="the run had no virgl; do not enforce pixel "
                         "assertions for desktops that cannot render without "
                         "it (see needs_virgl in the contract)")
    ap.add_argument("--strict", action="store_true",
                    help="fail (77) when OCR is unavailable instead of "
                         "degrading to render-only checks")
    args = ap.parse_args()

    family = desktop_family(args.flavor)
    try:
        spec = load_spec(args.spec)
    except ImportError:
        print("Bail out! PyYAML is required to read the checkpoint contract "
              f"({args.spec}) — install python3-pyyaml", flush=True)
        return EXIT_MISSING_DEPENDENCY
    except OSError as e:
        print(f"Bail out! cannot read checkpoint contract: {e}", flush=True)
        return EXIT_MISSING_DEPENDENCY
    except SpecError as e:
        # Not 77: that code means "missing dependency, no verdict" and callers
        # (iso-e2e.sh) skip on it. A broken contract is a defect in this repo.
        print(f"Bail out! invalid checkpoint contract {args.spec}: {e}",
              flush=True)
        return EXIT_BAD_CONTRACT
    checkpoints = spec["checkpoints"]
    if args.phase:
        checkpoints = [c for c in checkpoints if c.get("phase") in args.phase]

    # Can this run's pixels be judged at all? cosmic-comp, niri and xfwl4 are
    # Smithay compositors and draw nothing without virgl, which no CI runner
    # has. Reporting their blank frames is useful; FAILING on them would fail
    # every such cell forever, for a reason that is about the host.
    no_gpu = (args.no_gpu
              or os.environ.get("TUNAOS_CHECKPOINT_NO_GPU") == "1")
    pixels_blind = no_gpu and family in (spec.get("needs_virgl") or [])
    if pixels_blind:
        note(f"no virgl on this host and {family} needs it to render — the "
             f"render and keyword assertions are REPORTED, not enforced")

    print(f"# install-pipeline checkpoints — variant={args.variant or '?'} "
          f"flavor={args.flavor} desktop={family}", flush=True)
    if not HAVE_OCR:
        if args.strict:
            print("Bail out! tesseract not installed and --strict was given",
                  flush=True)
            return EXIT_MISSING_DEPENDENCY
        note("tesseract not installed — keyword and forbidden-text assertions "
             "are SKIPPED; only presence and render checks ran")

    results = []
    sheet_frames, sheet_labels = [], []
    digests = {}  # checkpoint id -> {frame path: pixel digest}, for distinct_from
    by_id = {c["id"]: c for c in spec["checkpoints"]}

    for cp in checkpoints:
        cid = cp["id"]
        required = bool(cp.get("required", False))
        keywords = cp.get("desktops", {}).get(family) or cp.get("keywords", [])
        mode = cp.get("match", "any")
        forbid = cp.get("forbid", []) or []
        fails_before = _fails

        frames = []
        for basename in cp.get("frames", []):
            frames += find_frames(args.outdir, basename)

        record = {"id": cid, "phase": cp.get("phase"), "required": required,
                  "frames": [os.path.basename(p) for p in frames],
                  "matched": [], "forbidden": [], "rendered": None}
        regions = cp.get("regions") or []
        if regions:
            record["regions"] = [
                {"id": r["id"], "outcome": "not-run", "reason": "not-reached",
                 "detail": "", "matched": [], "distance": None}
                for r in regions]

        if not frames:
            missing = ("none of " + ", ".join(cp.get("frames", [])) +
                       f" found in {args.outdir}")
            tap(False, f"[{cid}] frame captured", missing, enforced=required)
            for r in record.get("regions", []):
                r["reason"] = "frame-missing"
            conclude(record, ("failed", "frame-missing", missing), fails_before)
            results.append(record)
            continue
        tap(True, f"[{cid}] frame captured", enforced=required)

        # FRESH — a frame pixel-identical to an earlier stage's is that
        # stage's screen photographed again (a hung VM, a capture that
        # re-read a stale framebuffer), whatever this stage's name says.
        # Identical frames are dropped; if none is left, the stage was
        # never photographed. Two checkpoints listing the same file are not
        # a stale capture, and a blank frame is left to RENDERS, whose
        # `frame-blank` says more than "same black as before".
        devs = {p: stddev(p) for p in frames}
        for other in cp.get("distinct_from", []):
            if other not in digests:
                digests[other] = {
                    p: frame_digest(p) for b in by_id[other]["frames"]
                    for p in find_frames(args.outdir, b)}
        earlier = [(op, d, other) for other in cp.get("distinct_from", [])
                   for op, d in digests[other].items()]
        if earlier:
            stale = {}
            for p in frames:
                d = frame_digest(p)
                if 0 <= devs[p] <= BLANK_STDDEV:
                    continue
                for op, od, other in earlier:
                    if od == d and os.path.realpath(op) != os.path.realpath(p):
                        stale[p] = other
                        break
            frames = [p for p in frames if p not in stale]
            record["stale"] = {os.path.basename(p): o for p, o in stale.items()}
            tap(bool(frames), f"[{cid}] frame differs from "
                f"{', '.join(cp['distinct_from'])}",
                "identical: " + ", ".join(f"{os.path.basename(p)} = {o}"
                                          for p, o in stale.items()),
                enforced=required)
            if not frames:
                for r in record.get("regions", []):
                    r["reason"] = "frame-stale"
                conclude(record, ("failed", "frame-stale",
                                  "every frame is identical to one of "
                                  f"{', '.join(sorted(set(stale.values())))}"),
                         fails_before)
                results.append(record)
                continue

        # RENDERS — measured per frame, passing if any frame has content. A
        # blank retry alongside a good capture is not a failure of the stage.
        measurable = [(p, devs[p]) for p in frames if devs[p] >= 0]
        best_dev = None
        if measurable:
            best_path, best_dev = max(measurable, key=lambda t: t[1])
            record["rendered"] = round(best_dev, 4)
            tap(best_dev > BLANK_STDDEV, f"[{cid}] screen renders content",
                f"best stddev {best_dev:.4f} <= {BLANK_STDDEV} "
                f"({os.path.basename(best_path)} is blank)",
                enforced=required and not pixels_blind)
        else:
            note(f"[{cid}] no ImageMagick — render check skipped")

        texts, says_ok, bad = None, None, []
        if HAVE_OCR:
            texts = {p: normalize(ocr(p)) for p in frames}
            squeezed = {p: despace(t) for p, t in texts.items()}
            record["ocr_chars"] = {os.path.basename(p): len(t)
                                   for p, t in texts.items()}

            # SAYS — the keyword assertion is satisfied by whichever frame of
            # the checkpoint satisfies it; they are alternative captures of one
            # stage.
            if keywords:
                per_frame_hits = {
                    p: [k for k in keywords
                        if k.lower() in t or despace(k.lower()) in squeezed[p]]
                    for p, t in texts.items()}
                best = max(per_frame_hits.items(), key=lambda kv: len(kv[1]))
                hits = best[1]
                record["matched"] = hits
                says_ok = (len(hits) == len(keywords) if mode == "all"
                           else bool(hits))
                seen = "; ".join(
                    f"{os.path.basename(p)}: {t[:160] or '<no text>'}"
                    for p, t in texts.items())
                quoted = ", ".join(f'"{k}"' for k in keywords)
                desc = (f"[{cid}] screen says one of: {quoted}" if mode == "any"
                        else f"[{cid}] screen says all of: {quoted}")
                tap(says_ok, desc,
                    f"matched {hits or 'nothing'} — OCR read: {seen}",
                    enforced=required and not pixels_blind)

            # CLEAN — always enforced when the frame exists, on optional
            # checkpoints too: a panic is a panic wherever it is photographed.
            bad = sorted({f for p, t in texts.items() for f in forbid
                          if f.lower() in t or despace(f.lower()) in squeezed[p]})
            record["forbidden"] = bad
            if forbid:
                tap(not bad, f"[{cid}] screen free of failure text",
                    f"found {bad}", enforced=True)

        # REGIONS — identity: what a box of the frame says and shows. Only on
        # frames with content: a crop of a blank frame "mismatches" every
        # artwork, which would report the one blank-screen defect N times.
        lit = [p for p in frames if not 0 <= devs[p] <= BLANK_STDDEV]
        if regions and not lit:
            for r in record["regions"]:
                r["reason"] = "frame-blank"
        elif regions:
            record["regions"] = [
                judge_region(cid, r, lit, args.variant,
                             enforced=required and not pixels_blind)
                for r in regions]
        for r in record.get("regions", []):
            note(f"[{cid}] region {r['id']}: {r['outcome']} ({r['reason']})")

        verdict = classify(best_dev, pixels_blind, texts, keywords, forbid,
                           says_ok, bad)
        conclude(record, with_regions(verdict, record.get("regions", []),
                                      pixels_blind), fails_before)
        results.append(record)
        sheet_frames.append(frames[0])
        sheet_labels.append(cid)

    # ── The installer's own pages ────────────────────────────────────────────
    # This script deliberately asserts nothing about them: they are
    # installer-walkthrough.py's contract (tests/installer-screens.yaml), which
    # drives the frontend with sendkey and OCRs each page as it goes — a thing
    # only a harness holding the QEMU monitor can do. What was missing is a
    # single place to read the whole pipeline's verdict, so when that harness
    # ran in the same evidence directory, fold its result into this summary and
    # report it. Reported, never re-judged: the walkthrough already failed its
    # own run if a required page was missing, and asserting it twice would
    # report one defect as two.
    wt_path = os.path.join(args.outdir, f"walkthrough-{family}.json")
    walkthrough = None
    if os.path.exists(wt_path):
        try:
            with open(wt_path) as f:
                walkthrough = json.load(f)
            reached = [k for k, v in (walkthrough.get("screens") or {}).items() if v]
            note(f"installer pages (from {os.path.basename(wt_path)}): "
                 f"{', '.join(reached) or '(none detected)'}; "
                 f"{walkthrough.get('failures', 0)} walkthrough failure(s)")
        except (OSError, ValueError) as e:
            note(f"could not read {wt_path}: {e}")

    summary = {
        "spec_schema_version": spec.get("schema_version"),
        "variant": args.variant,
        "flavor": args.flavor,
        "desktop": family,
        "ocr": HAVE_OCR,
        "pixels_enforced": not pixels_blind,
        "checkpoints": results,
        "installer_walkthrough": walkthrough,
        "assertions": _tap,
        "failures": _fails,
    }
    json_path = args.json_path or os.path.join(
        args.outdir, f"install-checkpoints-{family}.json")
    try:
        with open(json_path, "w") as f:
            json.dump(summary, f, indent=2)
            f.write("\n")
        note(f"summary: {json_path}")
    except OSError as e:
        note(f"could not write {json_path}: {e}")

    sheet_path = args.sheet_path or os.path.join(
        args.outdir, f"install-checkpoints-{family}.png")
    if contact_sheet(sheet_frames, sheet_path, sheet_labels):
        note(f"contact sheet: {sheet_path}")

    print(f"1..{len(_tap)}", flush=True)
    print(f"# {len(_tap) - _fails}/{len(_tap)} assertions passed "
          f"({_fails} enforced failure{'s' if _fails != 1 else ''})", flush=True)
    not_run = [r["id"] for r in results
               if r["required"] and r["outcome"] == "not-run"]
    if not _fails and not_run:
        # Zero enforced failures would read as "the pipeline looked right" —
        # but these required checkpoints were never judged.
        print(f"# required checkpoint(s) not run: {', '.join(not_run)} — "
              f"exit {EXIT_MISSING_DEPENDENCY}, not a pass", flush=True)
        return EXIT_MISSING_DEPENDENCY
    return _fails


if __name__ == "__main__":
    sys.exit(main())
