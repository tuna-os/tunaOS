// Playwright config for the ISO builder web app.
// Serves ../app statically; tests drive the real WASM engine against the
// real registry relay (network!), so timeouts are generous.
const { defineConfig } = require("@playwright/test");

module.exports = defineConfig({
  testDir: "./tests",
  timeout: 900_000,
  retries: 0,
  workers: 1,
  use: {
    baseURL: "http://127.0.0.1:8931",
    viewport: { width: 1180, height: 820 },
    screenshot: "only-on-failure",
    // OPFS quota is derived from the profile partition's free space —
    // a /tmp (tmpfs) profile caps origin storage at ~2 GB and fails
    // real-image pulls. Keep browser state on real disk.
    launchOptions: { args: ["--disable-dev-shm-usage"] },
  },
  webServer: {
    command: "python3 -m http.server 8931 --directory ../app/public",
    url: "http://127.0.0.1:8931",
    reuseExistingServer: true,
  },
  reporter: [["list"]],
});
