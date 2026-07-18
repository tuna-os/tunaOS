// Persistent browser contexts on real disk: Chrome derives the OPFS
// quota from the profile partition's free space, and the default
// ephemeral profile lands on /tmp — a 2 GB tmpfs on dev boxes, which
// caps origin storage below what a real image pull needs.
const base = require("@playwright/test");
const path = require("path");
const fs = require("fs");

exports.test = base.test.extend({
  context: async ({ browserName }, use, testInfo) => {
    const dir = path.join(process.env.HOME, "tmp", `pw-prof-${testInfo.workerIndex}`);
    fs.rmSync(dir, { recursive: true, force: true });
    const ctx = await base[browserName].launchPersistentContext(dir, {
      viewport: { width: 1180, height: 820 },
      baseURL: "http://127.0.0.1:8931",
      args: ["--disable-dev-shm-usage"],
    });
    await use(ctx);
    await ctx.close();
    fs.rmSync(dir, { recursive: true, force: true });
  },
  page: async ({ context }, use) => {
    await use(context.pages()[0] || (await context.newPage()));
  },
});
exports.expect = base.expect;
