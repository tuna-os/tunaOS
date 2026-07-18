const { chromium } = require("@playwright/test");
(async () => {
  const b = await chromium.launch();
  const page = await b.newPage();
  let rx = 0, reqs = 0;
  page.on("response", async (r) => { reqs++; try { const h = r.headers()["content-length"]; if (h) rx += parseInt(h); } catch {} });
  page.on("pageerror", (e) => console.log("[pageerror]", String(e).slice(0, 400)));
  await page.goto("http://127.0.0.1:8931/");
  await page.locator("#image").fill("tuna-os/guppy:base");
  await page.locator("#introspect").click();
  let last = "";
  for (let i = 0; i < 60; i++) {
    await page.waitForTimeout(10000);
    const stage = await page.locator("#stage").textContent();
    const line = `stage="${stage}" responses=${reqs} rx≈${(rx/1e6).toFixed(0)}MB`;
    if (line !== last) { console.log(`[t+${(i+1)*10}s]`, line); last = line; }
    const log = await page.locator("#log").textContent();
    if (log.includes("error")) { console.log("LOG:", log.slice(-300)); break; }
    if (await page.locator("#facts").isVisible()) { console.log("FACTS:", await page.locator("#facts").textContent()); break; }
  }
  await b.close();
})();
