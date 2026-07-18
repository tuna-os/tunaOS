// E2E for the TunaOS ISO Builder web app — drives the real WASM engine
// against the real registry relay.
//
// The @walkthrough tests double as the documentation pipeline: every
// screenshot lands in ../../../../docs/iso-builder/ and is embedded by
// docs/iso-builder-guide.md. Regenerate with `npm run walkthrough`
// (or the iso-builder-e2e workflow), then commit the refreshed images.
//
// TBOX_E2E_FULL=1 additionally runs the full ISO build + download —
// heavy (real image in browser memory); off by default in CI.

const { test, expect } = require("./fixtures");
const path = require("path");
const fs = require("fs");

const SHOTS = path.resolve(__dirname, "../../../../docs/iso-builder");
// sailfin:base: smallest clean image with kernel + systemd-boot
// (guppy:base ships a /tmp build tree — tunaOS#672).
const IMAGE = process.env.TBOX_E2E_IMAGE || "tuna-os/sailfin:base";

function shot(page, name) {
  fs.mkdirSync(SHOTS, { recursive: true });
  return page.screenshot({ path: path.join(SHOTS, name), fullPage: true });
}

test.describe("iso builder", () => {
  test("page loads with engine UI @walkthrough", async ({ page }) => {
    await page.goto("/");
    await expect(page).toHaveTitle(/TunaOS ISO Builder/);
    await expect(page.locator("#image")).toBeVisible();
    await expect(page.locator("#introspect")).toBeEnabled();
    await shot(page, "01-home.png");
  });

  test("url params prefill the form", async ({ page }) => {
    await page.goto("/?image=example/os:tag&label=DEMO&flatpaks=org.example.App");
    await expect(page.locator("#image")).toHaveValue("example/os:tag");
    await expect(page.locator("#label")).toHaveValue("DEMO");
    await expect(page.locator("#flatpaks")).toHaveValue(/org\.example\.App/);
    await expect(page.locator("#share")).toContainText("image=example");
  });

  test("inspect detects the image and fills flatpak defaults @walkthrough", async ({ page }) => {
    await page.goto("/");
    await page.locator("#image").fill(IMAGE);
    await shot(page, "02-image-entered.png");
    await page.locator("#introspect").click();

    // Engine load + manifest resolve + full unpack (network).
    await expect(page.locator("#facts")).toBeVisible({ timeout: 600_000 });
    await expect(page.locator(".badge.de")).toContainText(/gnome|kde|niri|cosmic|xfce|none/);
    await expect(page.locator("#build")).toBeEnabled();
    await shot(page, "03-inspected.png");

    // Advanced panel: per-DE flatpak defaults are prefilled.
    await page.locator("summary").click();
    const flatpaks = await page.locator("#flatpaks").inputValue();
    expect(flatpaks.length).toBeGreaterThan(0);
    await shot(page, "04-advanced.png");
  });

  test("full build streams a bootable ISO @full", async ({ page }) => {
    test.skip(!process.env.TBOX_E2E_FULL, "set TBOX_E2E_FULL=1 for the full build");
    const initrd = process.env.TBOX_E2E_INITRD_URL || "";
    await page.goto(`/?image=${encodeURIComponent(IMAGE)}&autodl=1${initrd ? `&initrd=${encodeURIComponent(initrd)}` : ""}`);
    await expect(page.locator("#build")).toBeEnabled({ timeout: 600_000 });

    const download = page.waitForEvent("download", { timeout: 600_000 });
    await page.locator("#build").click();
    await shot(page, "05-building.png");
    const dl = await download;
    const out = path.join(SHOTS, "..", "iso-builder-e2e-output.iso");
    await dl.saveAs(out);
    const size = fs.statSync(out).size;
    expect(size).toBeGreaterThan(100 * 1024 * 1024);
    // ISO9660 PVD signature at sector 16.
    const fd = fs.openSync(out, "r");
    const buf = Buffer.alloc(6);
    fs.readSync(fd, buf, 0, 6, 16 * 2048);
    fs.closeSync(fd);
    expect(buf.toString("latin1", 1, 6)).toBe("CD001");
    await expect(page.locator("#stage")).toContainText(/Done/, { timeout: 120_000 });
    await shot(page, "06-done.png");
    fs.unlinkSync(out);
  });
});
