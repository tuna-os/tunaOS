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
      77 if OCR is unavailable and --strict was given.
"""
import argparse
import glob
import json
import os
import re
import shutil
import subprocess
import sys

# Same floor scripts/iso-e2e.sh and installer-walkthrough.py use for "this
# screen looks blank" — keep the three in step, a frame is either blank or it
# is not and three different answers would be worse than a wrong one.
BLANK_STDDEV = 0.02

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


def ocr(path):
    """OCR one frame, caching the text next to it as <frame>.ocr.txt.

    Two passes: --psm 6 reads the block-of-text layout that installer pages and
    console screens present, --psm 11 ("sparse text") is what finds the handful
    of isolated words on a display-manager or desktop screen, where psm 6
    frequently returns nothing at all. Both are searched, because a checkpoint
    keyword may live in either layout.
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
    joined = "\n".join(text)
    try:
        with open(cache, "w") as f:
            f.write(joined)
    except OSError:
        pass
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
    for family in ("kde", "gnome", "cosmic", "niri", "xfce"):
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
    """
    import yaml
    with open(path) as f:
        return yaml.safe_load(f)


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
        return 77
    except OSError as e:
        print(f"Bail out! cannot read checkpoint contract: {e}", flush=True)
        return 77
    checkpoints = spec.get("checkpoints", [])
    if args.phase:
        checkpoints = [c for c in checkpoints if c.get("phase") in args.phase]

    print(f"# install-pipeline checkpoints — variant={args.variant or '?'} "
          f"flavor={args.flavor} desktop={family}", flush=True)
    if not HAVE_OCR:
        if args.strict:
            print("Bail out! tesseract not installed and --strict was given",
                  flush=True)
            return 77
        note("tesseract not installed — keyword and forbidden-text assertions "
             "are SKIPPED; only presence and render checks ran")

    results = []
    sheet_frames, sheet_labels = [], []

    for cp in checkpoints:
        cid = cp["id"]
        required = bool(cp.get("required", False))
        keywords = cp.get("desktops", {}).get(family) or cp.get("keywords", [])
        mode = cp.get("match", "any")
        forbid = cp.get("forbid", []) or []

        frames = []
        for basename in cp.get("frames", []):
            frames += find_frames(args.outdir, basename)

        record = {"id": cid, "phase": cp.get("phase"), "required": required,
                  "frames": [os.path.basename(p) for p in frames],
                  "matched": [], "forbidden": [], "rendered": None}

        if not frames:
            tap(False, f"[{cid}] frame captured",
                "none of " + ", ".join(cp.get("frames", [])) +
                f" found in {args.outdir}", enforced=required)
            results.append(record)
            continue
        tap(True, f"[{cid}] frame captured", enforced=required)

        # RENDERS — measured per frame, passing if any frame has content. A
        # blank retry alongside a good capture is not a failure of the stage.
        devs = [(p, stddev(p)) for p in frames]
        measurable = [(p, d) for p, d in devs if d >= 0]
        if measurable:
            best_path, best_dev = max(measurable, key=lambda t: t[1])
            record["rendered"] = round(best_dev, 4)
            tap(best_dev > BLANK_STDDEV, f"[{cid}] screen renders content",
                f"best stddev {best_dev:.4f} <= {BLANK_STDDEV} "
                f"({os.path.basename(best_path)} is blank)", enforced=required)
        else:
            note(f"[{cid}] no ImageMagick — render check skipped")

        if not HAVE_OCR:
            results.append(record)
            sheet_frames.append(frames[0])
            sheet_labels.append(cid)
            continue

        texts = {p: normalize(ocr(p)) for p in frames}
        squeezed = {p: despace(t) for p, t in texts.items()}
        record["ocr_chars"] = {os.path.basename(p): len(t) for p, t in texts.items()}

        # SAYS — the keyword assertion is satisfied by whichever frame of the
        # checkpoint satisfies it; they are alternative captures of one stage.
        if keywords:
            per_frame_hits = {
                p: [k for k in keywords
                    if k.lower() in t or despace(k.lower()) in squeezed[p]]
                for p, t in texts.items()}
            best = max(per_frame_hits.items(), key=lambda kv: len(kv[1]))
            hits = best[1]
            record["matched"] = hits
            ok = len(hits) == len(keywords) if mode == "all" else bool(hits)
            seen = "; ".join(
                f"{os.path.basename(p)}: {t[:160] or '<no text>'}"
                for p, t in texts.items())
            quoted = ", ".join(f'"{k}"' for k in keywords)
            desc = (f"[{cid}] screen says one of: {quoted}" if mode == "any"
                    else f"[{cid}] screen says all of: {quoted}")
            tap(ok, desc, f"matched {hits or 'nothing'} — OCR read: {seen}",
                enforced=required)

        # CLEAN — always enforced when the frame exists, on optional
        # checkpoints too: a panic is a panic wherever it is photographed.
        bad = sorted({f for p, t in texts.items() for f in forbid
                      if f.lower() in t or despace(f.lower()) in squeezed[p]})
        record["forbidden"] = bad
        if forbid:
            tap(not bad, f"[{cid}] screen free of failure text",
                f"found {bad}", enforced=True)

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
        "variant": args.variant,
        "flavor": args.flavor,
        "desktop": family,
        "ocr": HAVE_OCR,
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
    return _fails


if __name__ == "__main__":
    sys.exit(main())
