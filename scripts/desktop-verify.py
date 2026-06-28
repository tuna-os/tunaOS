#!/usr/bin/env python3
"""
Desktop verification via Vision Language Model (VLM).
Sends a screenshot to Gemini or Lemonade with structured assertions
about desktop state (booted, logged in, compositor running, apps open).

Usage:
  python3 desktop-verify.py screenshot.png [--backend gemini|lemonade]

Returns exit code 0 if all checks pass, 1 otherwise.
Checks are defined inline — no reference images needed.
"""

import argparse
import base64
import json
import os
import sys
from io import BytesIO

try:
    from PIL import Image
    import requests
except ImportError:
    print("ERROR: requires Pillow and requests. pip install Pillow requests")
    sys.exit(77)

# ── Desktop verification assertions ─────────────────────────────────────────
# These are asked of the VLM for every desktop screenshot.
# The model looks at the image and answers Pass/Fail for each.

DESKTOP_CHECKS = [
    {
        "id": "boot-complete",
        "assertion": "The system has booted to a graphical desktop or login screen. "
                     "There should be a desktop background, panel bar, or login prompt visible."
    },
    {
        "id": "compositor-active",
        "assertion": "The display is showing a graphical desktop environment, not a text console, "
                     "boot log, or blank screen."
    },
    {
        "id": "no-crash",
        "assertion": "There are no visible error dialogs, crash reporters, or warning messages "
                     "overlaid on the screen."
    },
]

LOGIN_CHECKS = [
    {
        "id": "login-prompt",
        "assertion": "The display manager login screen is visible with a user list or "
                     "username/password input fields."
    },
]

DESKTOP_SESSION_CHECKS = [
    {
        "id": "desktop-loaded",
        "assertion": "A fully loaded desktop is visible with a panel bar (top or bottom), "
                     "application menu, clock, and system tray area."
    },
    {
        "id": "apps-available",
        "assertion": "The desktop appears functional: icons are visible, the panel shows "
                     "active indicators, and there are no frozen or blank areas."
    },
]


def encode_image(image_path: str) -> str:
    """Resize to 1024px max dimension and base64 encode."""
    img = Image.open(image_path)
    max_dim = 1024
    if max(img.size) > max_dim:
        ratio = max_dim / max(img.size)
        img = img.resize((int(img.size[0] * ratio), int(img.size[1] * ratio)), Image.LANCZOS)
    buf = BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("utf-8")


def call_gemini(image_b64: str, checks: list, api_key: str) -> dict:
    """Send screenshot + assertions to Gemini 2.5 Flash."""
    prompt = (
        "You are verifying a desktop Linux system screenshot. "
        "For each assertion below, respond with exactly one line:\n"
        "Result: Pass. Evidence: <brief reason>\nor\n"
        "Result: Fail. Evidence: <brief reason>\n\n"
        "Assertions:\n"
    )
    for i, c in enumerate(checks):
        prompt += f"{i+1}. {c['assertion']}\n"

    resp = requests.post(
        "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent",
        params={"key": api_key},
        json={
            "contents": [{
                "parts": [
                    {"inline_data": {"mime_type": "image/png", "data": image_b64}},
                    {"text": prompt}
                ]
            }]
        },
        timeout=30
    )
    resp.raise_for_status()
    data = resp.json()
    text = data.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")
    return _parse_results(text, checks)


def call_lemonade(image_b64: str, checks: list) -> dict:
    """Send screenshot + assertions to local Lemonade server (Gemma/Gemini)."""
    # Build multi-modal message for Lemonade (OpenAI-compatible API)
    prompt = (
        "You are verifying a desktop Linux system screenshot. "
        "For each assertion below, respond with exactly one line:\n"
        "Result: Pass. Evidence: <brief reason>\nor\n"
        "Result: Fail. Evidence: <brief reason>\n"
    )
    messages = [
        {"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_b64}"}},
            {"type": "text", "text": prompt + "\n".join(f"{i+1}. {c['assertion']}" for i, c in enumerate(checks))}
        ]}
    ]
    try:
        resp = requests.post(
            "https://lemonade.manatee-basking.ts.net/v1/chat/completions",
            json={"model": "gpt-4o", "messages": messages, "max_tokens": 1024},
            timeout=60
        )
        resp.raise_for_status()
        data = resp.json()
        text = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        return _parse_results(text, checks)
    except Exception as e:
        return {"error": str(e), "results": {c["id"]: False for c in checks}}


def _parse_results(text: str, checks: list) -> dict:
    """Parse 'Result: Pass/Fail' lines from VLM response."""
    results = {}
    lines = text.strip().split("\n")
    for i, c in enumerate(checks):
        found = False
        for line in lines:
            if "Result: Pass" in line or "Result:Fail" in line or "Pass." in line:
                if i == 0 or any(str(i+1) in line for _ in [1]):
                    pass
            if c["id"].replace("-", " ") in line.lower() or f"{i+1}." in line:
                if "pass" in line.lower():
                    results[c["id"]] = True
                    found = True
                elif "fail" in line.lower():
                    results[c["id"]] = False
                    found = True
        if not found:
            # Fallback: check 'Result:' prefix
            for line in lines:
                if line.strip().startswith("Result:"):
                    if "Pass" in line:
                        results[c["id"]] = True
                    elif "Fail" in line:
                        results[c["id"]] = False
                    found = True
                    break
        if not found:
            results[c["id"]] = None  # unknown / parse error
    return {"results": results, "raw": text}


def main():
    parser = argparse.ArgumentParser(description="Desktop verification via VLM")
    parser.add_argument("screenshot", help="Path to screenshot PNG/PPM")
    parser.add_argument("--backend", choices=["gemini", "lemonade"], default="lemonade",
                        help="VLM backend (default: lemonade)")
    parser.add_argument("--mode", choices=["boot", "login", "desktop"], default="desktop",
                        help="Verification mode (default: desktop)")
    args = parser.parse_args()

    if not os.path.exists(args.screenshot):
        print(f"ERROR: screenshot not found: {args.screenshot}")
        sys.exit(1)

    # Choose checks based on mode
    if args.mode == "boot":
        checks = DESKTOP_CHECKS
    elif args.mode == "login":
        checks = DESKTOP_CHECKS + LOGIN_CHECKS
    else:
        checks = DESKTOP_CHECKS + LOGIN_CHECKS + DESKTOP_SESSION_CHECKS

    # Convert PPM to PNG if needed
    img_path = args.screenshot
    if img_path.endswith(".ppm"):
        png_path = img_path.replace(".ppm", ".png")
        if os.path.exists(png_path):
            img_path = png_path
        else:
            try:
                Image.open(img_path).save(png_path)
                img_path = png_path
            except Exception:
                pass  # use PPM directly

    print(f"Verifying desktop: {img_path} ({args.backend}, mode={args.mode})")
    print(f"  Checks: {len(checks)}")
    for c in checks:
        print(f"    - {c['id']}: {c['assertion'][:60]}...")

    image_b64 = encode_image(img_path)

    if args.backend == "gemini":
        api_key = os.environ.get("GEMINI_API_KEY", "")
        if not api_key:
            print("ERROR: GEMINI_API_KEY not set")
            sys.exit(77)
        result = call_gemini(image_b64, checks, api_key)
    else:
        result = call_lemonade(image_b64, checks)

    if "error" in result:
        print(f"ERROR: VLM call failed: {result['error']}")
        sys.exit(1)

    print("\n--- Results ---")
    all_pass = True
    for c in checks:
        status = result["results"].get(c["id"], None)
        if status is True:
            print(f"  ✅ {c['id']}: Pass")
        elif status is False:
            print(f"  ❌ {c['id']}: Fail")
            all_pass = False
        else:
            print(f"  ❓ {c['id']}: Unknown (parse error)")
            all_pass = False

    print(f"\nRaw VLM response:\n{result['raw'][:500]}")

    if all_pass:
        print("\n✅ Desktop verification PASSED")
        sys.exit(0)
    else:
        print("\n❌ Desktop verification FAILED — see results above")
        sys.exit(1)


if __name__ == "__main__":
    main()
