const { chromium } = require("@playwright/test");
(async () => {
  const b = await chromium.launch();
  const page = await b.newPage();
  page.on("pageerror", (e) => console.log("[pageerror]", String(e).slice(0, 400)));
  await page.goto("http://127.0.0.1:8932/");
  await page.locator("#image").fill("tuna-os/guppy:base");
  const t0 = Date.now();
  await page.locator("#introspect").click();
  let last = "";
  for (let i = 0; i < 90; i++) {
    await page.waitForTimeout(5000);
    const stage = await page.locator("#stage").textContent();
    if (stage !== last) { console.log(`[t+${((Date.now()-t0)/1000).toFixed(0)}s]`, stage); last = stage; }
    const log = await page.locator("#log").textContent();
    if (log.includes("error")) { console.log("LOG:", log.slice(-300)); break; }
    if (await page.locator("#facts").isVisible()) { console.log(`FACTS after ${((Date.now()-t0)/1000).toFixed(0)}s:`, await page.locator("#facts").textContent()); break; }
  }
  await b.close();
})();
